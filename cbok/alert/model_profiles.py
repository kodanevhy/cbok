"""Select only an explicitly configured, enabled database model profile."""
from django.conf import settings
from cbok.alert.llm import create_client, LLMConfigurationError


def configured_model_client(key=None):
    from cbok.alert.models import ModelProfile
    key = key or getattr(settings, 'ALERT_MODEL_PROFILE', '')
    if not key:
        raise LLMConfigurationError('Select a model profile explicitly')
    try:
        profile = ModelProfile.objects.get(key=key, enabled=True)
    except ModelProfile.DoesNotExist:
        raise LLMConfigurationError('Unknown or disabled model profile') from None
    return create_client({field: getattr(profile, field) for field in (
        'backend', 'model', 'provider', 'base_url', 'api_key_env', 'timeout', 'options')})
