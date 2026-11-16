from unittest.mock import patch

from django.test import TestCase, override_settings

from cbok.alert.llm import register_backend
from cbok.alert.models import ModelProfile


class FixtureModel:
    def ask(self, messages):
        return '{"selected":"database_profile"}'


register_backend('manager_fixture', lambda config: FixtureModel())


class ManagerModelSelectionTest(TestCase):
    @override_settings(ALERT_MODEL_PROFILE='manager_profile')
    def test_legacy_topic_manager_uses_explicit_profile_not_legacy_paid_backend(self):
        from cbok.alert.manager import AlertManager
        ModelProfile.objects.create(key='manager_profile', backend='manager_fixture', model='fixture')
        with patch('cbok.alert.llm.Deepseek', side_effect=AssertionError('Unselected legacy backend constructed')):
            with patch.object(AlertManager, '_init_google_crawler'):
                manager = AlertManager()
        self.assertEqual('{"selected":"database_profile"}', manager.llm_client.ask([{'role': 'user', 'content': 'test'}]))
