"""Discover installed detector manifests without a central import list."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import tomllib


DEFAULT_DETECTORS = Path(__file__).with_name('detectors')


@dataclass(frozen=True)
class DetectorSpec:
    name: str
    entrypoint: Path
    timeout: float
    max_output_bytes: int
    digest: str
    description: str = ''
    protocol_version: int = 1


def discover_detectors(paths=None, *, strict=True, diagnostics=None):
    """Discover plugins; runtime callers can isolate invalid manifests.

    Non-strict mode retains healthy names and disables every conflicting name.
    Optional diagnostics contain at most 100 bounded, non-secret descriptions;
    the same diagnostics are logged so scheduled failures remain observable.
    """
    import logging

    roots = paths if paths is not None else [DEFAULT_DETECTORS]
    found, seen, invalid = {}, set(), set()
    reported = 0

    def report(path, name, reason):
        nonlocal reported
        if reported >= 100:
            return
        diagnostic = {'path': str(path)[:400], 'name': str(name)[:120], 'reason': reason}
        if diagnostics is not None:
            diagnostics.append(diagnostic)
        logging.getLogger(__name__).warning('Invalid detector plugin: %s', diagnostic)
        reported += 1

    for root in roots:
        try:
            root = Path(root).resolve()
            if not root.is_dir():
                raise ValueError('Detector directory does not exist')
            manifests = sorted(root.rglob('manifest.toml'))
        except (OSError, ValueError, TypeError):
            if strict:
                raise
            report(root, '', 'Detector directory is unavailable')
            continue
        for manifest in manifests:
            name = ''
            reason = 'Invalid TOML manifest'
            try:
                with manifest.open('rb') as stream:
                    entry = tomllib.load(stream)
                reason = 'Invalid detector name'
                name = entry.get('name', '')
                if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]*', name):
                    raise ValueError(reason)
                reason = 'Duplicate detector name'
                if name in seen:
                    raise ValueError(reason)
                seen.add(name)
                reason = 'Unsupported detector protocol'
                if type(entry.get('protocol_version')) is not int or entry['protocol_version'] != 1:
                    raise ValueError(reason)
                reason = 'Invalid detector entrypoint'
                path = (manifest.parent / entry.get('entrypoint', '')).resolve()
                if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file() or path.suffix != '.py':
                    raise ValueError(reason)
                timeout = entry.get('timeout', 30)
                limit = entry.get('max_output_bytes', 65536)
                reason = 'Invalid detector timeout'
                if type(timeout) not in (int, float) or not 0 < timeout <= 300:
                    raise ValueError(reason)
                reason = 'Invalid detector output limit'
                if type(limit) is not int or not 512 <= limit <= 1048576:
                    raise ValueError(reason)
                reason = 'Detector files are unreadable'
                digest = hashlib.sha256(manifest.read_bytes() + path.read_bytes()).hexdigest()
                if name not in invalid:
                    found[name] = DetectorSpec(name, path, float(timeout), limit, digest,
                                               entry.get('description', ''))
            except (OSError, ValueError, TypeError):
                if strict:
                    raise
                if isinstance(name, str) and name:
                    invalid.add(name)
                    found.pop(name, None)
                report(manifest, name, reason)
    return found
