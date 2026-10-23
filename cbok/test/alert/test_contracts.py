import unittest

from cbok.alert.sources import Observation, SourceError, register_source
from cbok.alert.monitoring.contracts import evaluate_context, register_rule


class ContractScriptTest(unittest.TestCase):
    def setUp(self):
        self.context = {'source': {'adapter': 'fixture_contract', 'config': {}},
                        'section': {'key': 'example', 'config': {}},
                        'check': {'key': 'feed', 'config': {'kind': 'feed', 'contracts': [
                            {'id': 'items', 'kind': 'min_items', 'path': 'metadata.items', 'minimum': 1}
                        ]}}}

    def test_normal_content_updates_do_not_violate_contract(self):
        for title in ('First news', 'Completely different news'):
            self.context['section']['config'] = {'title': title}
            result = evaluate_context(self.context)
            self.assertEqual('pass', result['status'])
            self.assertEqual([], result['issues'])

    def test_required_contract_failure_reports_exact_rule(self):
        self.context['check']['config']['contracts'].append(
            {'id': 'required_id', 'kind': 'required', 'path': 'metadata.essential_id'})
        result = evaluate_context(self.context)
        self.assertEqual('fail', result['status'])
        self.assertEqual('SECTION_CHANGED', result['issues'][0]['code'])
        self.assertEqual('required_id', result['issues'][0]['rule_id'])

    def test_network_error_is_indeterminate_not_contract_change(self):
        self.context['section']['config'] = {'network_error': True}
        result = evaluate_context(self.context)
        self.assertEqual('unknown', result['status'])
        self.assertEqual('NETWORK_ERROR', result['issues'][0]['code'])

    def test_unknown_rule_is_configuration_error(self):
        self.context['check']['config']['contracts'][0]['kind'] = 'missing_rule'
        result = evaluate_context(self.context)
        self.assertEqual('CHECK_CONFIG_ERROR', result['issues'][0]['code'])

    def test_new_registered_rule_runs_without_changing_evaluator(self):
        self.context['check']['config']['contracts'] = [
            {'id': 'custom', 'kind': 'fixture_custom', 'path': 'metadata.answer'}]
        self.assertEqual('pass', evaluate_context(self.context)['status'])

    def test_rule_can_use_new_catalog_type_supplied_by_registry_context(self):
        self.context['anomaly_types'] = {'CUSTOM_CHECK': {
            'code': 'CUSTOM_CHECK', 'label': 'Custom', 'scope': 'contract', 'indeterminate': False}}
        self.context['check']['config']['contracts'] = [
            {'id': 'new_check', 'kind': 'required', 'path': 'metadata.missing', 'code': 'CUSTOM_CHECK'}]
        result = evaluate_context(self.context)
        self.assertEqual('fail', result['status'])
        self.assertEqual('CUSTOM_CHECK', result['issues'][0]['code'])


class FixtureSource:
    def __init__(self, config):
        pass

    def observe(self, section, kind):
        if section.get('network_error'):
            raise SourceError('NETWORK_ERROR', 'Request timed out')
        return Observation('json', {'data': []}, {'items': [{'title': section.get('title')}], 'answer': 42})


register_source('fixture_contract', FixtureSource)
register_rule('fixture_custom', lambda observation, rule: observation['metadata']['answer'] == 42)
