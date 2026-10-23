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


def discover_detectors(paths=None):
    roots = paths if paths is not None else [DEFAULT_DETECTORS]
    found = {}
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError(f'Detector directory does not exist: {root}')
        for manifest in sorted(root.rglob('manifest.toml')):
            with manifest.open('rb') as stream:
                entry = tomllib.load(stream)
            name = entry.get('name', '')
            if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]*', name):
                raise ValueError(f'Invalid detector name in {manifest}')
            if name in found:
                raise ValueError(f'Duplicate detector: {name}')
            if type(entry.get('protocol_version')) is not int or entry['protocol_version'] != 1:
                raise ValueError(f'Unsupported detector protocol for {name}')
            path = (manifest.parent / entry.get('entrypoint', '')).resolve()
            if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file() or path.suffix != '.py':
                raise ValueError(f'Invalid detector entrypoint for {name}')
            timeout = entry.get('timeout', 30)
            limit = entry.get('max_output_bytes', 65536)
            if type(timeout) not in (int, float) or not 0 < timeout <= 300:
                raise ValueError(f'Invalid detector timeout for {name}')
            if type(limit) is not int or not 512 <= limit <= 1048576:
                raise ValueError(f'Invalid detector output limit for {name}')
            digest = hashlib.sha256(manifest.read_bytes() + path.read_bytes()).hexdigest()
            found[name] = DetectorSpec(name, path, float(timeout), limit, digest,
                                       entry.get('description', ''))
    return found
