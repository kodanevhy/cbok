"""Bounded subprocess protocol for trusted, administrator-installed detectors."""

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time


PROTOCOL_VERSION = 1


def failure_result(message, code='CHECK_EXECUTION_ERROR'):
    return {'protocol_version': 1, 'status': 'unknown', 'issues': [
        {'code': code, 'rule_id': 'detector_execution', 'message': message[:1000]}
    ]}


def _validate_result(result, catalog):
    if not isinstance(result, dict) or type(result.get('protocol_version')) is not int or result['protocol_version'] != 1:
        raise ValueError('Unsupported or missing detector protocol version')
    if result.get('status') not in ('pass', 'fail', 'unknown'):
        raise ValueError('Invalid detector status')
    issues = result.get('issues')
    if not isinstance(issues, list) or len(issues) > 100:
        raise ValueError('Detector issues must be a bounded list')
    if (result['status'] == 'pass') != (not issues):
        raise ValueError('Detector status and issues disagree')
    for issue in issues:
        if not isinstance(issue, dict) or issue.get('code') not in catalog:
            raise ValueError('Detector returned an unregistered anomaly code')
        for field in ('rule_id', 'message'):
            if not isinstance(issue.get(field), str) or not 0 < len(issue[field]) <= 2000:
                raise ValueError(f'Detector issue requires bounded {field}')
    return result


def _kill(process):
    # Kill descendants too when the top-level script already exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_detector(spec, context, catalog):
    """Run a plugin once. Infrastructure/protocol failures are typed results."""
    process = None
    try:
        context = dict(context, protocol_version=PROTOCOL_VERSION)
        payload = json.dumps(context, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(payload) > 1048576:
            raise ValueError('Detector input exceeds size limit')
        environment = os.environ.copy()
        project = str(Path(__file__).resolve().parents[3])
        environment['PYTHONPATH'] = os.pathsep.join(filter(None, [project, environment.get('PYTHONPATH')]))
        process = subprocess.Popen([sys.executable, '-u', str(spec.entrypoint)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=project, env=environment,
                                   start_new_session=True)
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        deadline = time.monotonic() + spec.timeout
        input_offset = 0
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
            for name in buffers:
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Detector timed out')
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == 'stdin':
                        try:
                            input_offset += os.write(key.fd, payload[input_offset:input_offset + 8192])
                        except BrokenPipeError:
                            raise ValueError('Detector closed its input before reading configuration') from None
                        if input_offset == len(payload):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.data].extend(chunk)
                    if sum(map(len, buffers.values())) > spec.max_output_bytes:
                        raise ValueError('Detector output exceeds size limit')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Detector timed out')
        process.wait(timeout=remaining)
        if process.returncode:
            # Do not include arbitrary stderr, which may contain credentials.
            raise ValueError(f'Detector exited with status {process.returncode}')
        text = bytes(buffers['stdout']).decode('utf-8')
        result = json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
        return _validate_result(result, catalog)
    except (OSError, ValueError, TypeError, TimeoutError, subprocess.SubprocessError):
        # All outward errors are bounded and contain no raw subprocess output.
        error = sys.exc_info()[1]
        return failure_result(str(error))
    finally:
        if process is not None:
            _kill(process)
            for name in ('stdin', 'stdout', 'stderr'):
                stream = getattr(process, name)
                if stream and not stream.closed:
                    stream.close()
