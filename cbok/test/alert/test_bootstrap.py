from unittest.mock import patch
from django.test import TestCase
from cbok.alert.models import Source, Section, DetectorCheck, CollectedItem, NotificationChannel, AnomalyType
from cbok.alert.sources import SourceItem


class BootstrapTests(TestCase):
    def test_defaults_idempotent_preserve_admin(self):
        from cbok.alert.monitoring.bootstrap import bootstrap_defaults
        bootstrap_defaults()
        source = Source.objects.get(key='tencent')
        source.config = {'timeout': 77}
        source.save()
        section = Section.objects.get(key='news')
        section.enabled = False
        section.save()
        AnomalyType.objects.filter(code='EMPTY_RESULT').update(policy={'notify': False})
        bootstrap_defaults()
        self.assertEqual(Source.objects.count(), 1)
        self.assertEqual(Section.objects.count(), 3)
        self.assertEqual(DetectorCheck.objects.count(), 9)
        self.assertEqual(Source.objects.get().config, {'timeout': 77})
        self.assertFalse(Section.objects.get(key='news').enabled)
        self.assertEqual(AnomalyType.objects.get(code='EMPTY_RESULT').policy, {'notify': False})
        self.assertFalse(NotificationChannel.objects.exists())

    def test_register_preserves_unless_update_and_atomic_invalid(self):
        from cbok.alert.monitoring.bootstrap import register_configuration
        data = {'sources': [{'key': 'test', 'kind': 'web', 'adapter': 'tencent', 'enabled': False}]}
        register_configuration(data)
        data['sources'][0]['enabled'] = True
        register_configuration(data)
        self.assertFalse(Source.objects.get().enabled)
        register_configuration(data, update=True)
        self.assertTrue(Source.objects.get().enabled)
        with self.assertRaises(ValueError):
            register_configuration({'sources': [dict(data['sources'][0], key='other')],
                'sections': [{'source': 'missing', 'key': 'bad', 'name': 'bad'}]})
        self.assertFalse(Source.objects.filter(key='other').exists())

    def test_register_validates_registry_refs_and_duplicates(self):
        from cbok.alert.monitoring.bootstrap import register_configuration
        for data in ({'sources': [{'key': 'x', 'kind': 'web', 'adapter': 'missing'}]},
                     {'notification_channels': [{'key': 'x', 'kind': 'missing'}]},
                     {'model_profiles': [{'key': 'x', 'backend': 'missing', 'model': 'x'}]},
                     {'sources': [{'key': 'x', 'adapter': 'tencent', 'kind': 'web'}] * 2}):
            with self.assertRaises(ValueError):
                register_configuration(data)

    def test_collect_upserts_only_items(self):
        from cbok.alert.monitoring.bootstrap import bootstrap_defaults, collect_items
        bootstrap_defaults()
        with patch('cbok.alert.monitoring.bootstrap.create_source') as factory:
            factory.return_value.collect.return_value = [SourceItem('id', title='one')]
            collect_items('tencent', 'news', 2)
            factory.return_value.collect.return_value = [SourceItem('id', title='two')]
            collect_items('tencent', 'news', 2)
            factory.return_value.collect.assert_called_with(Section.objects.get(key='news').config, limit=2)
        self.assertEqual(CollectedItem.objects.get().payload['title'], 'two')

    def test_registration_references_policies_and_validation(self):
        from cbok.alert.monitoring.bootstrap import register_configuration
        data = {'notification_channels': [{'key': 'admin', 'kind': 'email', 'config': {'to': ['admin@example.invalid']}}],
                'sources': [{'key': 'local', 'kind': 'web', 'adapter': 'tencent', 'notification_channels': ['admin']}],
                'sections': [{'key': 'news', 'source': 'local', 'name': 'News'}],
                'checks': [{'key': 'feed', 'source': 'local', 'section': 'news', 'detector': 'source_contract',
                            'config': {'kind': 'feed', 'contracts': [{'id': 'required', 'kind': 'required', 'path': 'metadata.items'}]}}]}
        register_configuration(data)
        self.assertEqual(Source.objects.get().notification_channels.get().key, 'admin')
        self.assertEqual(DetectorCheck.objects.get().interval_seconds, 300)
        for update in ({'interval_seconds': 0}, {'lease_token': 'forged'},
                       {'enabled': 'true'}, {'id': -3},
                       {'config': {'contracts': [{'id': 'bad', 'kind': 'required', 'path': 'metadata..items'}]}},
                       {'config': []}):
            invalid = {'checks': [dict(data['checks'][0], **update)]}
            with self.subTest(update=update), self.assertRaises(ValueError):
                register_configuration(invalid, update=True)

    def test_reject_enabled_invalid_channel_and_inline_source_credentials(self):
        from cbok.alert.monitoring.bootstrap import register_configuration
        with self.assertRaises(ValueError):
            register_configuration({'notification_channels': [{'key': 'admin', 'kind': 'email', 'config': {'to': []}}]})
        with self.assertRaises(ValueError):
            register_configuration({'sources': [{'key': 'x', 'kind': 'web', 'adapter': 'tencent', 'config': {'api_key': 'inline'}}]})
