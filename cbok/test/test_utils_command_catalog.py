import configparser
import unittest

from cbok.cmd import args

try:
    from cbok import utils
except configparser.Error as exc:
    utils = None
    UTILS_IMPORT_ERROR = exc
else:
    UTILS_IMPORT_ERROR = None


class FakeBaseCommand:
    def base_action(self):
        return 0


class FakePatchCommands(FakeBaseCommand):
    @args.action_description("Upload patch")
    def put(self):
        return 0

    def raw_doc(self):
        """
        Raw doc fallback
        """
        return 0

    def _internal(self):
        return 0


class FakeDefaultCommands(FakeBaseCommand):
    @args.action_description("Checkout master and rebase")
    def rebase(self):
        return 0


@unittest.skipIf(utils is None, "cbok.conf unavailable: %s" % UTILS_IMPORT_ERROR)
class CommandCatalogTest(unittest.TestCase):
    def test_discover_command_groups_filters_base_and_private_methods(self):
        groups = utils.discover_command_groups(
            {"patch": FakePatchCommands},
            FakeBaseCommand,
        )

        command_names = [name for _cat, _obj, commands in groups for name, _method in commands]

        self.assertEqual(["put", "raw_doc"], command_names)

    def test_format_command_catalog_uses_action_description_and_doc_fallback(self):
        groups = utils.discover_command_groups(
            {"patch": FakePatchCommands},
            FakeBaseCommand,
        )

        catalog = utils.format_command_catalog(groups)

        self.assertIn("commands:", catalog)
        self.assertIn("patch put", catalog)
        self.assertIn("Upload patch", catalog)
        self.assertIn("patch raw_doc", catalog)
        self.assertIn("Raw doc fallback", catalog)
        self.assertNotIn("base_action", catalog)
        self.assertNotIn("_internal", catalog)

    def test_format_command_catalog_lists_default_commands_without_category_prefix(self):
        groups = utils.discover_command_groups(
            {
                "default": FakeDefaultCommands,
                "patch": FakePatchCommands,
            },
            FakeBaseCommand,
        )

        catalog = utils.format_command_catalog(groups)

        self.assertIn("rebase", catalog)
        self.assertIn("Checkout master and rebase", catalog)
        rebase_line = next(line for line in catalog.splitlines() if "Checkout master and rebase" in line)
        patch_put_line = next(line for line in catalog.splitlines() if "Upload patch" in line)
        self.assertEqual(
            patch_put_line.index("Upload patch"),
            rebase_line.index("Checkout master and rebase"),
        )
        self.assertNotIn("\n  rebase", catalog)
        self.assertNotIn("default:", catalog)
        self.assertNotIn("default rebase", catalog)
