"""Explicit, registered model clients with optional SDKs imported on selection.

Profiles contain credential *environment variable names*, never API keys. Model
calls are independent of collection/monitoring; a failed backend is never replaced
with another backend. JSON output is requested by default, but callers must still
validate the returned text against their own schema.
"""

from collections.abc import Mapping
from copy import deepcopy
import importlib
import json
import math
import os
import re
from urllib.parse import urlsplit

from cbok.registry import Registry


class LLMConfigurationError(ValueError):
    """The selected model profile or request is invalid."""


class LLMError(RuntimeError):
    """The selected SDK failed or returned no usable text."""


_BACKENDS = Registry("model backend")


def register_backend(name, factory):
    """Register a factory accepting a profile mapping; duplicates are errors."""
    if not callable(factory):
        raise LLMConfigurationError("Model backend factory must be callable")
    return _BACKENDS.register(name, factory)


def list_backends():
    """Return the registered backend names in stable order."""
    return tuple(name for name, _ in _BACKENDS.items())


def create_client(config: Mapping) -> "LLMClient":
    """Construct only the explicitly selected backend, without database access."""
    if not isinstance(config, Mapping):
        raise LLMConfigurationError("Model profile must be a mapping")
    name = config.get("backend")
    if not isinstance(name, str) or not name.strip():
        raise LLMConfigurationError("Select a model backend explicitly")
    try:
        factory = _BACKENDS.get(name)
    except KeyError:
        raise LLMConfigurationError("Unknown model backend") from None
    return factory(dict(config))


_SECRET_FIELDS = {"api_key", "token", "access_token", "authorization", "password",
                  "headers", "extra_headers", "cookies"}
_RESERVED_OPTIONS = {
    "model", "messages", "provider", "base_url", "api_key_env", "timeout",
    "stream", "max_retries", "api_base", "api_endpoint", "extra_query",
    "extra_json", "extra_parameters", "raw", "ignore_stream", "stream_timeout",
    "proxy", "proxies",
}


def _reject_inline_credentials(value):
    if isinstance(value, Mapping):
        for name, child in value.items():
            if not isinstance(name, str):
                raise LLMConfigurationError("Model option names must be strings")
            if name.lower().replace("-", "_") in _SECRET_FIELDS:
                raise LLMConfigurationError("Use api_key_env for model credentials")
            _reject_inline_credentials(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _reject_inline_credentials(child)


def _optional_string(config, field):
    value = config.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise LLMConfigurationError("Optional model fields must be nonempty strings")
    return value


def _profile(config, *, default_base_url=None):
    if not isinstance(config, Mapping):
        raise LLMConfigurationError("Model profile must be a mapping")
    _reject_inline_credentials(config)
    model = config.get("model")
    if not isinstance(model, str) or not model.strip():
        raise LLMConfigurationError("Model name is required")
    provider = _optional_string(config, "provider")
    base_url = _optional_string(config, "base_url") or default_base_url
    if base_url is not None:
        if not isinstance(base_url, str):
            raise LLMConfigurationError("Model base_url must be an HTTP(S) URL")
        try:
            parsed = urlsplit(base_url)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment)
            # Accessing port also validates malformed/non-numeric ports.
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise LLMConfigurationError("Model base_url must be an HTTP(S) URL without credentials or query")
    timeout = config.get("timeout", 30)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise LLMConfigurationError("Model timeout must be a finite positive number")
    env_name = _optional_string(config, "api_key_env")
    if env_name is not None and (not isinstance(env_name, str)
                                 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name)):
        raise LLMConfigurationError("api_key_env must name an environment variable")
    options = config.get("options", {})
    if not isinstance(options, Mapping):
        raise LLMConfigurationError("Model options must be a mapping")
    if _RESERVED_OPTIONS.intersection(options):
        raise LLMConfigurationError("Model options cannot override profile, transport, or streaming controls")
    options = deepcopy(dict(options))
    if "extra_body" in options:
        body = options["extra_body"]
        if not isinstance(body, Mapping):
            raise LLMConfigurationError("Model extra_body must be a mapping")
        # OpenAI merges extra_body over its generated body. G4F provider
        # templates also accept this lane, so protect the same fields in both.
        protected = _RESERVED_OPTIONS | set(options) | {"response_format"}
        if protected.intersection(body):
            raise LLMConfigurationError("Model extra_body cannot override profile or request fields")
    response_format = options.setdefault("response_format", {"type": "json_object"})
    if (not isinstance(response_format, Mapping)
            or response_format.get("type") not in {"text", "json_object"}
            or set(response_format) != {"type"}):
        raise LLMConfigurationError("Supported response_format types are text and json_object")
    return model, provider, base_url, env_name, timeout, options


def _credential(env_name, *, required=False):
    if env_name is None:
        if required:
            raise LLMConfigurationError("Selected backend requires api_key_env")
        return None
    value = os.environ.get(env_name)
    if not isinstance(value, str) or not value.strip():
        raise LLMConfigurationError("Configured model credential environment variable is empty or unset")
    return value


def _messages(messages):
    if (not isinstance(messages, list) or not messages
            or any(not isinstance(message, dict)
                   or not isinstance(message.get("role"), str)
                   or not message["role"].strip()
                   or not isinstance(message.get("content"), (str, list))
                   for message in messages)):
        raise LLMConfigurationError("Messages must be a nonempty list of role/content dictionaries")


class LLMClient:
    def ask(self, messages: list[dict]) -> str:
        raise NotImplementedError


class _CompletionClient(LLMClient):
    def ask(self, messages: list[dict]) -> str:
        _messages(messages)
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, stream=False,
                **self.request_options,
            )
        except Exception:
            # SDK exceptions may contain URLs, request headers, and credentials.
            raise LLMError("Selected model backend request failed") from None
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError, TypeError):
            raise LLMError("Model backend returned an invalid completion") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Model backend returned empty or non-text content")
        return content


class G4F(_CompletionClient):
    """G4F adapter; service/provider availability is not guaranteed by this API."""

    def __init__(self, config=None, **overrides):
        if config is None:
            config = {"model": "deepseek-v3"}
        config = {**config, **overrides}
        (self.model, provider, base_url, env_name,
         timeout, self.request_options) = _profile(config)
        key = _credential(env_name)
        self.request_options["timeout"] = timeout
        if provider:
            self.request_options["provider"] = provider
        if base_url:
            # G4F provider templates name their endpoint override api_base.
            self.request_options["api_base"] = base_url
        # Keep the historical behavior while letting profiles override it.
        self.request_options.setdefault("web_search", False)
        try:
            sdk = importlib.import_module("g4f.client")
            self.client = sdk.Client(**({"api_key": key} if key else {}))
        except Exception:
            raise LLMError("G4F backend is unavailable or could not initialize") from None

    def ask(self, messages: list[dict]) -> str:
        _messages(messages)
        request_messages = deepcopy(messages)
        json_object = self.request_options["response_format"]["type"] == "json_object"
        if json_object:
            # G4F 6.7 consumes response_format in its local postprocessor; it
            # does not forward that argument to the provider. Messages do reach
            # the provider, so request JSON explicitly there and validate below.
            request_messages.insert(0, {
                "role": "system",
                "content": "Return exactly one valid JSON object. Do not include "
                           "Markdown fences or text outside the object.",
            })
        content = super().ask(request_messages)
        if json_object:
            try:
                parsed = json.loads(content, parse_constant=_reject_json_constant)
            except (ValueError, RecursionError):
                raise LLMError("G4F backend did not return a valid JSON object") from None
            if not isinstance(parsed, dict):
                raise LLMError("G4F backend did not return a JSON object")
        return content


def _reject_json_constant(value):
    # Python's JSON decoder otherwise accepts NaN/Infinity, which are not JSON.
    raise ValueError("Non-JSON numeric constant")


class OpenAICompatible(_CompletionClient):
    """Selected OpenAI-compatible endpoint, with SDK retries disabled."""

    def __init__(self, config, *, _legacy_key=None, _deepseek=False):
        (self.model, provider, base_url, env_name,
         timeout, self.request_options) = _profile(
            config, default_base_url="https://api.deepseek.com" if _deepseek else None)
        if provider:
            raise LLMConfigurationError("provider is only supported by the G4F backend")
        if not base_url:
            raise LLMConfigurationError("OpenAI-compatible backend requires an explicit base_url")
        key = _legacy_key if _legacy_key is not None else _credential(env_name, required=_deepseek)
        if key is not None and (not isinstance(key, str) or not key.strip()):
            raise LLMConfigurationError("Selected model credential is empty")
        try:
            sdk = importlib.import_module("openai")
            # An explicit placeholder supports local unauthenticated endpoints
            # and prevents the SDK from implicitly reading OPENAI_API_KEY.
            self.client = sdk.OpenAI(api_key=key if key else "not-required",
                                     base_url=base_url, timeout=timeout,
                                     max_retries=0)
        except Exception:
            raise LLMError("OpenAI-compatible backend is unavailable or could not initialize") from None


class Deepseek(OpenAICompatible):
    """DeepSeek adapter; only an explicit no-argument call reads legacy CONF."""

    def __init__(self, config=None, **overrides):
        legacy_key = None
        if config is None and not overrides:
            try:
                settings = importlib.import_module("cbok.settings")
                legacy_key = settings.CONF.get("llm_api_key", "deepseek")
            except Exception:
                raise LLMConfigurationError("Legacy DeepSeek credential is unavailable") from None
            if not isinstance(legacy_key, str) or not legacy_key.strip():
                raise LLMConfigurationError("Legacy DeepSeek credential is empty")
            config = {"model": "deepseek-chat"}
        super().__init__({**(config or {}), **overrides},
                         _legacy_key=legacy_key, _deepseek=True)


register_backend("g4f", G4F)
register_backend("deepseek", Deepseek)
register_backend("openai_compatible", OpenAICompatible)
