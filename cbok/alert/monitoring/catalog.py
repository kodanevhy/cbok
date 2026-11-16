"""Single enumerable anomaly catalog. Business codes are data, not branches."""

from pathlib import Path
import re
import tomllib


DEFAULT_CATALOG = Path(__file__).with_name('catalog') / 'anomalies.toml'
DEFAULT_POLICY = {'threshold': 1, 'notify': True, 'recovery': True}


def load_catalog(path=None):
    path = Path(path) if path else DEFAULT_CATALOG
    with path.open('rb') as stream:
        entries = tomllib.load(stream).get('anomalies')
    if not isinstance(entries, dict) or not entries:
        raise ValueError('Anomaly catalog must contain [anomalies.CODE] declarations')
    result = load_catalog() if path.resolve() != DEFAULT_CATALOG.resolve() else {}
    for code, entry in entries.items():
        if len(code) > 120 or not re.fullmatch(r'[A-Z][A-Z0-9_]*', code) or not isinstance(entry, dict):
            raise ValueError(f'Invalid anomaly declaration: {code}')
        label = entry.get('label')
        if not isinstance(label, str) or not label.strip() or len(label) > 255:
            raise ValueError(f'Anomaly {code} requires a label')
        if not isinstance(entry.get('policy', {}), dict):
            raise ValueError(f'Invalid policy for {code}')
        scope = entry.get('scope', 'contract')
        if not isinstance(scope, str) or not scope.strip() or len(scope) > 120:
            raise ValueError(f'Invalid scope for {code}')
        if type(entry.get('indeterminate', False)) is not bool:
            raise ValueError(f'Invalid indeterminate flag for {code}')
        if not isinstance(entry.get('description', ''), str):
            raise ValueError(f'Invalid description for {code}')
        policy = dict(DEFAULT_POLICY, **entry.get('policy', {}))
        if type(policy['threshold']) is not int or policy['threshold'] < 1:
            raise ValueError(f'Invalid threshold for {code}')
        for key in ('notify', 'recovery'):
            if type(policy[key]) is not bool:
                raise ValueError(f'Invalid {key} policy for {code}')
        result[code] = dict(entry, code=code, policy=policy,
                            scope=entry.get('scope', 'contract'),
                            indeterminate=bool(entry.get('indeterminate', False)))
    return result
