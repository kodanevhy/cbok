"""Registered model clients, using SDK transport doubles without network access."""

import ast
from copy import deepcopy
import importlib
import importlib.metadata
import os
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


MESSAGES = [{"role": "user", "content": "Return a JSON object."}]


def completion(content):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
    )


class Transport:
    """Record the constructor/request boundary shared by the two SDKs."""

    def __init__(self, response=None, error=None):
        self.response = completion('{"ok": true}') if response is None else response
        self.error = error
        self.clients = []
        self.requests = []

    def client(self, **kwargs):
        self.clients.append(kwargs)
        return types.SimpleNamespace(chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create)))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return self.response

    def modules(self):
        return {
            "openai": types.SimpleNamespace(OpenAI=self.client),
            "g4f": types.SimpleNamespace(),
            "g4f.client": types.SimpleNamespace(Client=self.client),
        }


def installed_g4f_completion_client(provider_requests):
    """Run the installed SDK dispatch method with its provider iterator replaced.

    Loading just this method avoids importing optional G4F providers or creating
    their clients. Its real argument binding still consumes response_format, as
    G4F 6.7 does, so a Client-level kwargs double cannot hide the missing prompt.
    """
    distribution = importlib.metadata.distribution("g4f")
    path = distribution.locate_file("g4f/client/__init__.py")
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "Completions")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == "create")
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        method,
    ], type_ignores=[])
    ast.fix_missing_locations(module)

    def provider_iterator(provider, **payload):
        provider_requests.append(deepcopy(payload))
        # A provider may edit content internally; caller input must remain owned
        # by the caller even when nested message dictionaries are modified.
        payload["messages"][-1]["content"] = "provider-mutated input"
        return iter([completion('{"ok": true}')])

    namespace = {
        "AnyProvider": object(),
        "resolve_media": lambda *args: None,
        "filter_none": lambda **kwargs: {key: value for key, value in kwargs.items()
                                         if value is not None},
        "iter_run_tools": provider_iterator,
        "iter_response": lambda response, *args: response,
        "iter_append_model_and_provider": lambda response, *args: response,
    }
    exec(compile(module, str(path), "exec"), namespace)

    def client(**kwargs):
        completions = types.SimpleNamespace(
            client=types.SimpleNamespace(proxy=None, api_key=kwargs.get("api_key")),
            provider=None,
        )
        completions.create = types.MethodType(namespace["create"], completions)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))

    return client


class LazyImportTests(unittest.TestCase):
    def test_import_does_not_load_sdk_or_production_settings(self):
        script = """
import importlib.abc
import sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'g4f', 'openai', 'django'} or fullname == 'cbok.settings':
            raise AssertionError('Forbidden import: ' + fullname)
sys.meta_path.insert(0, Block())
from cbok.alert import llm
assert set(llm.list_backends()) >= {'g4f', 'deepseek', 'openai_compatible'}
"""
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_backend_does_not_import_any_sdk(self):
        script = """
import importlib.abc
import sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'g4f', 'openai'} or fullname == 'cbok.settings':
            raise AssertionError('Forbidden import: ' + fullname)
sys.meta_path.insert(0, Block())
from cbok.alert import llm
class Fake:
    def __init__(self, config): self.model = config['model']
    def ask(self, messages): return self.model
llm.register_backend('offline', Fake)
assert llm.create_client({'backend': 'offline', 'model': 'fake'}).ask([]) == 'fake'
"""
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class ModelClientTests(unittest.TestCase):
    def setUp(self):
        self.llm = importlib.import_module("cbok.alert.llm")

    def test_custom_backend_receives_selected_profile_and_rejects_duplicate(self):
        class Fake:
            def __init__(self, config):
                self.model = config["model"]

            def ask(self, messages):
                return self.model

        self.llm.register_backend("test-offline", Fake)
        self.assertEqual(self.llm.create_client({
            "backend": "test-offline", "model": "local-model"
        }).ask(MESSAGES), "local-model")
        self.assertIn("test-offline", self.llm.list_backends())
        with self.assertRaises(ValueError):
            self.llm.register_backend("test-offline", Fake)

    def test_unknown_or_unselected_backend_is_configuration_error(self):
        for config in ({}, {"backend": "not-registered"}, [], None):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.llm.create_client(config)

    def test_g4f_selection_needs_no_deepseek_key_or_sdk(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {}, clear=True):
            sys.modules["openai"] = None
            sys.modules["cbok.settings"] = None
            client = self.llm.create_client({
                "backend": "g4f", "model": "free-model", "provider": "FreeProvider",
                "base_url": "https://free.example/v1", "timeout": 17,
                "options": {"web_search": False, "temperature": 0.2,
                            "response_format": {"type": "json_object"}},
            })
            self.assertEqual(client.ask(MESSAGES), '{"ok": true}')
        self.assertEqual(len(transport.clients), 1)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual({key: value for key, value in transport.requests[0].items()
                          if key != "messages"}, {
            "model": "free-model", "provider": "FreeProvider",
            "api_base": "https://free.example/v1", "timeout": 17,
            "stream": False, "web_search": False,
            "temperature": 0.2, "response_format": {"type": "json_object"},
        })
        self.assertEqual(transport.requests[0]["messages"][1:], MESSAGES)

    def test_g4f_json_requirement_reaches_provider_when_sdk_consumes_response_format(self):
        provider_requests = []
        try:
            client_factory = installed_g4f_completion_client(provider_requests)
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("Optional G4F SDK source is not installed")
        messages = [{"role": "user", "content": "Describe a useful result."}]
        original = deepcopy(messages)
        with patch.dict(sys.modules, {
            "g4f.client": types.SimpleNamespace(Client=client_factory),
        }):
            client = self.llm.create_client({"backend": "g4f", "model": "free-model"})
            self.assertEqual(client.ask(messages), '{"ok": true}')
        self.assertEqual(messages, original)
        self.assertEqual(len(provider_requests), 1)
        payload = provider_requests[0]
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["messages"][1:], original)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("JSON object", payload["messages"][0]["content"])
        self.assertIn("Markdown", payload["messages"][0]["content"])

    def test_g4f_json_mode_rejects_invalid_or_nonobject_output_without_fallback(self):
        for content in ("prose with credential-secret", "[]", "null", "1", '"text"',
                        '{"number": NaN}', '{"number": Infinity}'):
            with self.subTest(content=content):
                transport = Transport(response=completion(content))
                with patch.dict(sys.modules, transport.modules()):
                    client = self.llm.create_client({"backend": "g4f", "model": "free-model"})
                    with self.assertRaises(RuntimeError) as raised:
                        client.ask(MESSAGES)
                self.assertNotIn("credential-secret", str(raised.exception))
                self.assertEqual(len(transport.clients), 1)
                self.assertEqual(len(transport.requests), 1)

    def test_g4f_json_object_text_is_preserved_after_validation(self):
        transport = Transport(response=completion('  {"ok": true} \n'))
        with patch.dict(sys.modules, transport.modules()):
            client = self.llm.create_client({"backend": "g4f", "model": "free-model"})
            self.assertEqual(client.ask(MESSAGES), '  {"ok": true} \n')

    def test_extra_body_cannot_replace_protected_profile_or_request_fields(self):
        forbidden = {
            "model": "different-priced-model", "messages": [], "stream": True,
            "response_format": {"type": "json_schema"}, "timeout": 99,
            "base_url": "https://other.example", "api_base": "https://other.example",
            "provider": "OtherProvider", "temperature": 0.99,
            "extra_query": {"model": "other"},
        }
        for backend in ("g4f", "deepseek", "openai_compatible"):
            for field, value in forbidden.items():
                with self.subTest(backend=backend, field=field):
                    transport = Transport()
                    with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {"MODEL_KEY": "secret"}):
                        with self.assertRaises(ValueError):
                            self.llm.create_client({
                                "backend": backend, "model": "configured-model",
                                "base_url": "https://models.example/v1", "api_key_env": "MODEL_KEY",
                                "options": {"temperature": 0.2, "extra_body": {field: value}},
                            })
                    self.assertEqual(transport.clients, [])

    def test_extra_body_requires_mapping_but_preserves_vendor_fields(self):
        for invalid in (None, [], "body", 4):
            with self.subTest(invalid=invalid):
                transport = Transport()
                with patch.dict(sys.modules, transport.modules()):
                    with self.assertRaises(ValueError):
                        self.llm.create_client({
                            "backend": "openai_compatible", "model": "configured-model",
                            "base_url": "https://models.example/v1",
                            "options": {"extra_body": invalid},
                        })
                self.assertEqual(transport.clients, [])
        for backend in ("g4f", "deepseek", "openai_compatible"):
            with self.subTest(backend=backend):
                transport = Transport()
                vendor_body = {"enable_thinking": False, "vendor_settings": {"mode": "fast"}}
                with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {"MODEL_KEY": "secret"}):
                    client = self.llm.create_client({
                        "backend": backend, "model": "configured-model",
                        "base_url": "https://models.example/v1", "api_key_env": "MODEL_KEY",
                        "options": {"extra_body": vendor_body},
                    })
                    self.assertEqual(client.ask(MESSAGES), '{"ok": true}')
                self.assertEqual(transport.requests[0]["extra_body"], {
                    "enable_thinking": False, "vendor_settings": {"mode": "fast"},
                })

    def test_sdk_escape_hatches_cannot_override_profile_transport_or_streaming(self):
        overrides = {
            "api_base": "https://other.example", "api_endpoint": "https://other.example/chat",
            "extra_query": {"model": "other"}, "extra_json": {"model": "other"},
            "extra_parameters": ["model"], "raw": True, "ignore_stream": True,
            "stream_timeout": 999, "proxy": "http://other.example", "proxies": {},
        }
        for backend in ("g4f", "openai_compatible"):
            for field, value in overrides.items():
                with self.subTest(backend=backend, field=field):
                    transport = Transport()
                    with patch.dict(sys.modules, transport.modules()):
                        with self.assertRaises(ValueError):
                            self.llm.create_client({
                                "backend": backend, "model": "configured-model",
                                "base_url": "https://models.example/v1", "options": {field: value},
                            })
                    self.assertEqual(transport.clients, [])

    def test_openai_compatible_forwards_profile_and_only_named_key(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {
            "TEST_MODEL_KEY": "named-secret", "OPENAI_API_KEY": "wrong-secret"
        }, clear=True):
            sys.modules["g4f"] = None
            client = self.llm.create_client({
                "backend": "openai_compatible", "model": "configured-model",
                "base_url": "https://models.example/v1", "api_key_env": "TEST_MODEL_KEY",
                "timeout": 9.5, "options": {"max_tokens": 123},
            })
            self.assertEqual(client.ask(MESSAGES), '{"ok": true}')
        self.assertEqual(transport.clients, [{
            "api_key": "named-secret", "base_url": "https://models.example/v1",
            "timeout": 9.5, "max_retries": 0,
        }])
        self.assertEqual(transport.requests, [{
            "model": "configured-model", "messages": MESSAGES, "stream": False,
            "max_tokens": 123, "response_format": {"type": "json_object"},
        }])

    def test_unauthenticated_endpoint_does_not_use_ambient_openai_key(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {"OPENAI_API_KEY": "unselected-secret"}):
            client = self.llm.create_client({
                "backend": "openai_compatible", "model": "local-model",
                "base_url": "http://localhost:8000/v1",
                "options": {"response_format": {"type": "text"}},
            })
            self.assertEqual(client.ask(MESSAGES), '{"ok": true}')
        self.assertEqual(transport.clients[0]["api_key"], "not-required")
        self.assertEqual(transport.requests[0]["response_format"], {"type": "text"})

    def test_compatible_backend_requires_endpoint_and_rejects_unhandled_provider(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()):
            for overrides in ({}, {"base_url": "https://local.example", "provider": "unsupported"}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    self.llm.create_client({
                        "backend": "openai_compatible", "model": "local-model", **overrides,
                    })
        self.assertEqual(transport.clients, [])

    def test_falsy_optional_values_do_not_silently_disable_configuration(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()):
            for field in ("provider", "base_url", "api_key_env"):
                for value in (False, 0, [], {}):
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        self.llm.create_client({
                            "backend": "g4f", "model": "free-model", field: value,
                        })
        self.assertEqual(transport.clients, [])

    def test_unavailable_selected_sdk_is_explicit_and_does_not_load_another(self):
        for backend, module in (("g4f", "g4f.client"), ("openai_compatible", "openai")):
            with self.subTest(backend=backend), patch.dict(sys.modules, {module: None}):
                with self.assertRaises(RuntimeError):
                    self.llm.create_client({
                        "backend": backend, "model": "configured-model",
                        "base_url": "https://models.example/v1",
                    })

    def test_deepseek_is_explicit_and_configurable_without_legacy_settings(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {"DS_KEY": "secret"}):
            sys.modules["cbok.settings"] = None
            client = self.llm.create_client({
                "backend": "deepseek", "model": "deepseek-reasoner",
                "base_url": "https://custom.example", "api_key_env": "DS_KEY",
            })
            self.assertEqual(client.ask(MESSAGES), '{"ok": true}')
        self.assertEqual(transport.clients[0]["base_url"], "https://custom.example")
        self.assertEqual(transport.clients[0]["timeout"], 30)
        self.assertEqual(transport.requests[0]["model"], "deepseek-reasoner")

    def test_modern_deepseek_requires_named_key_and_never_reads_legacy_settings(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {}, clear=True):
            sys.modules["cbok.settings"] = None
            for config in ({"backend": "deepseek", "model": "deepseek-chat"},
                           {"backend": "deepseek", "model": "deepseek-chat", "api_key_env": "MISSING_KEY"}):
                with self.subTest(config=config), self.assertRaises(ValueError):
                    self.llm.create_client(config)
        self.assertEqual(transport.clients, [])

    def test_no_argument_deepseek_preserves_explicit_legacy_key_lookup(self):
        transport = Transport()

        class LegacyConf:
            def get(self, section, name):
                if (section, name) != ("llm_api_key", "deepseek"):
                    raise AssertionError("unexpected legacy setting")
                return "legacy-secret"

        fake_settings = types.ModuleType("cbok.settings")
        fake_settings.CONF = LegacyConf()
        with patch.dict(sys.modules, {**transport.modules(), "cbok.settings": fake_settings}):
            client = self.llm.Deepseek()
            self.assertEqual(client.ask(MESSAGES), '{"ok": true}')
        self.assertEqual(transport.clients[0]["api_key"], "legacy-secret")
        self.assertEqual(transport.clients[0]["base_url"], "https://api.deepseek.com")
        self.assertEqual(transport.requests[0]["model"], "deepseek-chat")

    def test_explicit_g4f_class_preserves_old_ask(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()):
            self.assertEqual(self.llm.G4F().ask(MESSAGES), '{"ok": true}')
        self.assertEqual(transport.requests[0]["model"], "deepseek-v3")

    def test_backend_failure_is_sanitized_and_never_falls_back(self):
        transport = Transport(error=RuntimeError("Authorization: secret-key at https://user:pass@host"))
        with patch.dict(sys.modules, transport.modules()):
            client = self.llm.create_client({"backend": "g4f", "model": "free-model"})
            with self.assertRaises(RuntimeError) as raised:
                client.ask(MESSAGES)
        self.assertNotIn("secret-key", str(raised.exception))
        self.assertNotIn("user:pass", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(len(transport.clients), 1)
        self.assertEqual(len(transport.requests), 1)

    def test_sdk_initialization_errors_do_not_expose_secrets(self):
        def broken(**kwargs):
            raise RuntimeError("secret-key")

        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=broken)}), \
                patch.dict(os.environ, {"DS_KEY": "secret-key"}):
            with self.assertRaises(RuntimeError) as raised:
                self.llm.create_client({"backend": "deepseek", "model": "chat", "api_key_env": "DS_KEY"})
        self.assertNotIn("secret-key", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_empty_or_malformed_responses_fail_for_each_builtin(self):
        for backend in ("g4f", "deepseek", "openai_compatible"):
            for response in (completion(""), completion(" \n"), completion(None),
                             completion({"error": "secret"}), types.SimpleNamespace(choices=[]),
                             types.SimpleNamespace(error={"message": "secret"}), "not-a-completion"):
                with self.subTest(backend=backend, response=response):
                    transport = Transport(response=response)
                    with patch.dict(sys.modules, transport.modules()), patch.dict(os.environ, {"MODEL_KEY": "secret"}):
                        client = self.llm.create_client({
                            "backend": backend, "model": "chat", "api_key_env": "MODEL_KEY",
                            "base_url": "https://models.example/v1",
                        })
                        with self.assertRaises(RuntimeError) as raised:
                            client.ask(MESSAGES)
                    self.assertNotIn("secret", str(raised.exception))

    def test_text_mode_preserves_unstructured_response_and_messages(self):
        transport = Transport(response=completion("  not json  "))
        with patch.dict(sys.modules, transport.modules()):
            client = self.llm.create_client({
                "backend": "g4f", "model": "free-model",
                "options": {"response_format": {"type": "text"}},
            })
            self.assertEqual(client.ask(MESSAGES), "  not json  ")
        self.assertEqual(transport.requests[0]["messages"], MESSAGES)

    def test_invalid_builtin_configuration_fails_before_sdk_initialization(self):
        invalid = [
            {"model": ""}, {"model": None}, {"timeout": 0}, {"timeout": -2},
            {"timeout": True}, {"timeout": float("nan")}, {"timeout": "soon"},
            {"provider": 42}, {"base_url": "file:///tmp/socket"},
            {"base_url": "https://user:password@models.example"},
            {"api_key_env": "SECRET=KEY"}, {"options": []},
            {"api_key": "literal-secret"},
            {"options": {"api_key": "literal-secret"}},
            {"options": {"extra_headers": {"Authorization": "literal-secret"}}},
            {"options": {"model": "override"}}, {"options": {"timeout": 99}},
            {"options": {"stream": True}},
            {"options": {"response_format": {"type": "json_schema"}}},
        ]
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()):
            for overrides in invalid:
                config = {"backend": "g4f", "model": "free-model", **overrides}
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    self.llm.create_client(config)
        self.assertEqual(transport.clients, [])

    def test_invalid_messages_never_reach_transport(self):
        transport = Transport()
        with patch.dict(sys.modules, transport.modules()):
            client = self.llm.create_client({"backend": "g4f", "model": "free-model"})
            for messages in (None, "prompt", [], [{}], [{"role": "user"}]):
                with self.subTest(messages=messages), self.assertRaises(ValueError):
                    client.ask(messages)
        self.assertEqual(transport.requests, [])


if __name__ == "__main__":
    unittest.main()
