from unittest.mock import patch
from django.test import TestCase, override_settings
from cbok.alert.models import ModelProfile
from cbok.alert.llm import LLMConfigurationError


class ModelProfileTests(TestCase):
    def test_explicit_db_profile_only(self):
        from cbok.alert.model_profiles import configured_model_client
        ModelProfile.objects.create(key='local', backend='g4f', model='configured')
        with self.assertRaises(LLMConfigurationError):
            configured_model_client()
        with override_settings(ALERT_MODEL_PROFILE='local'), patch('cbok.alert.model_profiles.create_client') as factory:
            self.assertIs(configured_model_client(), factory.return_value)
            self.assertEqual(factory.call_args.args[0]['model'], 'configured')
        ModelProfile.objects.update(enabled=False)
        with self.assertRaises(LLMConfigurationError):
            configured_model_client('local')
