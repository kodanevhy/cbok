import unittest

from cbok.registry import Registry


class RegistryTest(unittest.TestCase):
    def test_custom_registration_is_discoverable_without_framework_edits(self):
        registry = Registry('test')
        factory = lambda config: config['value']
        registry.register('custom', factory)
        self.assertEqual(42, registry.get('custom')({'value': 42}))
        self.assertEqual(('custom',), tuple(name for name, _ in registry.items()))

    def test_duplicate_and_unknown_registrations_are_explicit_errors(self):
        registry = Registry('test')
        registry.register('custom', object())
        with self.assertRaises(ValueError):
            registry.register('custom', object())
        with self.assertRaisesRegex(KeyError, 'missing'):
            registry.get('missing')
