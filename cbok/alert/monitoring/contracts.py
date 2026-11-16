"""Contract helpers used by detector scripts, outside the execution engine.

Custom logic can register a rule from a detector script, or install an entirely
new script. No business rule is dispatched in the scheduler/state machine.
"""

from bs4 import BeautifulSoup

from cbok.registry import Registry
from cbok.alert.sources import SourceError, create_source
from .catalog import load_catalog


_rules = Registry('contract rule')
_MISSING = object()


def register_rule(name, evaluator):
    return _rules.register(name, evaluator)


def list_rules():
    return _rules.items()


def _path(observation, rule):
    path = rule.get('path')
    if not isinstance(path, str) or not path:
        raise ValueError('Contract rule requires a dotted path')
    value = observation
    for part in path.split('.'):
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def _required(observation, rule):
    return _path(observation, rule) is not _MISSING


def _equals(observation, rule):
    if 'expected' not in rule:
        raise ValueError('Equality rule requires expected')
    return _path(observation, rule) == rule['expected']


def _nonempty(observation, rule):
    value = _path(observation, rule)
    return isinstance(value, (str, list, dict)) and bool(value)


def _type(observation, rule):
    allowed = {'object': (dict,), 'array': (list,), 'string': (str,),
               'number': (int, float), 'boolean': (bool,), 'null': (type(None),)}
    expected = rule.get('expected')
    if expected not in allowed:
        raise ValueError('Unknown JSON type in contract')
    return type(_path(observation, rule)) in allowed[expected]


def _min_items(observation, rule):
    minimum = rule.get('minimum', 1)
    if type(minimum) is not int or minimum < 0:
        raise ValueError('minimum must be a nonnegative integer')
    value = _path(observation, rule)
    return isinstance(value, list) and len(value) >= minimum


def _selector(observation, rule):
    selector = rule.get('selector')
    if not isinstance(selector, str) or not selector:
        raise ValueError('HTML rule requires selector')
    minimum = rule.get('minimum', 1)
    if type(minimum) is not int or minimum < 1:
        raise ValueError('HTML rule minimum must be a positive integer')
    if not isinstance(observation['data'], str):
        return False
    try:
        matches = BeautifulSoup(observation['data'], 'html.parser').select(selector)
    except Exception:
        raise ValueError('Invalid HTML selector in contract') from None
    return len(matches) >= minimum and all(item.get_text(strip=True) for item in matches[:minimum])


for _name, _function in [('required', _required), ('equals', _equals),
                         ('nonempty', _nonempty), ('type', _type),
                         ('min_items', _min_items), ('html_selector', _selector)]:
    register_rule(_name, _function)


def _result(issues, catalog):
    status = 'pass'
    if issues:
        status = 'unknown' if all(catalog[x['code']]['indeterminate'] for x in issues) else 'fail'
    return {'protocol_version': 1, 'status': status, 'issues': issues}


def evaluate_context(context):
    """Builtin script implementation; adapters/rules remain replaceable."""
    catalog = load_catalog()
    try:
        extensions = context.get('anomaly_types', {})
        if not isinstance(extensions, dict):
            raise ValueError('Invalid registered anomaly metadata')
        for code, descriptor in extensions.items():
            if (not isinstance(code, str) or not isinstance(descriptor, dict)
                    or type(descriptor.get('indeterminate', False)) is not bool):
                raise ValueError('Invalid registered anomaly descriptor')
            catalog[code] = dict(descriptor, indeterminate=descriptor.get('indeterminate', False))
        source = context['source']
        section = context['section']
        config = context['check']['config']
        kind = config.get('kind', 'feed')
        contracts = config.get('contracts', [])
        if not isinstance(contracts, list):
            raise ValueError('contracts must be a list')
        ids = set()
        for rule in contracts:
            if (not isinstance(rule, dict) or not isinstance(rule.get('id'), str)
                    or not rule['id'] or rule['id'] in ids):
                raise ValueError('Contract rules require unique nonempty IDs')
            ids.add(rule['id'])
            _rules.get(rule.get('kind'))
            if rule.get('code', 'SECTION_CHANGED') not in catalog:
                raise ValueError('Contract references unregistered anomaly code')
        adapter = create_source(source['adapter'], source.get('config', {}))
        observation = adapter.observe(section['config'], kind).to_dict()
        issues = []
        for rule in contracts:
            if not _rules.get(rule['kind'])(observation, rule):
                # Record bounded summaries, never entire news pages or bodies.
                issues.append({'code': rule.get('code', 'SECTION_CHANGED'),
                    'rule_id': rule['id'], 'message': f'Contract {rule["id"]} failed',
                    'expected': {key: value for key, value in rule.items() if key in ('path', 'expected', 'minimum', 'selector')},
                    'observed': {'format': observation['format']},
                    'evidence': observation.get('metadata', {}).get('url')})
        return _result(issues, catalog)
    except SourceError as exc:
        if exc.code not in catalog:
            return _result([{'code': 'CHECK_CONFIG_ERROR', 'rule_id': 'source_error',
                             'message': 'Source returned an unregistered anomaly type'}], catalog)
        return _result([{'code': exc.code, 'rule_id': f'source_{context.get("check", {}).get("config", {}).get("kind", "feed")}',
                         'message': exc.message[:2000], 'evidence': exc.evidence}], catalog)
    except (KeyError, TypeError, ValueError):
        return _result([{'code': 'CHECK_CONFIG_ERROR', 'rule_id': 'check_configuration',
                         'message': 'Invalid adapter, observation kind or contract configuration'}], catalog)
