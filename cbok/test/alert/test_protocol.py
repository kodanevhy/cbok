import json
from pathlib import Path
import tempfile
import time
import unittest

from cbok.alert.monitoring.catalog import load_catalog
from cbok.alert.monitoring.plugins import discover_detectors
from cbok.alert.monitoring.runner import run_detector


class DetectorProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog_path = self.root / 'types.toml'
        self.catalog_path.write_text('[anomalies.CUSTOM_FAILURE]\nlabel="Custom failure"\nscope="contract"\n', encoding='utf-8')
        self.catalog = load_catalog()
        self.catalog.update(load_catalog(self.catalog_path))

    def plugin(self, code, timeout=2):
        folder = self.root / 'custom'
        folder.mkdir(exist_ok=True)
        (folder / 'manifest.toml').write_text(
            'name="custom"\nprotocol_version=1\nentrypoint="check.py"\n'
            f'timeout={timeout}\nmax_output_bytes=2048\n', encoding='utf-8')
        (folder / 'check.py').write_text(code, encoding='utf-8')
        return discover_detectors([self.root])['custom']

    def test_new_script_and_new_anomaly_work_without_framework_registration_edit(self):
        script = self.plugin('import json,sys\nx=json.load(sys.stdin)\nprint(json.dumps({"protocol_version":1,"status":"fail","issues":[{"code":"CUSTOM_FAILURE","rule_id":"custom_rule","message":x["check"]["config"]["message"]}]}))\n')
        result = run_detector(script, {'check': {'config': {'message': 'Custom test'}}}, self.catalog)
        self.assertEqual('fail', result['status'])
        self.assertEqual('CUSTOM_FAILURE', result['issues'][0]['code'])
        self.assertEqual('Custom test', result['issues'][0]['message'])

    def test_extension_catalog_preserves_framework_failure_types(self):
        catalog = load_catalog(self.catalog_path)
        self.assertIn('CUSTOM_FAILURE', catalog)
        self.assertIn('CHECK_EXECUTION_ERROR', catalog)

    def test_catalog_rejects_wrong_metadata_types_before_registration(self):
        for text in ('indeterminate="false"', 'scope=[]', 'policy=[]'):
            with self.subTest(text=text):
                self.catalog_path.write_text('[anomalies.CUSTOM_FAILURE]\nlabel="Custom"\n' + text + '\n')
                with self.assertRaises(ValueError):
                    load_catalog(self.catalog_path)

    def test_bad_json_unknown_type_and_failed_exit_become_visible_execution_issues(self):
        cases = [
            'print("not json")',
            'print(\'{"protocol_version":1,"status":"fail","issues":[{"code":"NOT_REGISTERED","rule_id":"x","message":"x"}]}\')',
            'raise RuntimeError("crash")',
            'print(\'{"protocol_version":1,"status":"pass","issues":[{"code":"CUSTOM_FAILURE","rule_id":"x","message":"x"}]}\')',
            'print("x"*10000)',
        ]
        for script in cases:
            with self.subTest(script=script):
                result = run_detector(self.plugin(script), {}, self.catalog)
                self.assertEqual('unknown', result['status'])
                self.assertEqual('CHECK_EXECUTION_ERROR', result['issues'][0]['code'])

    def test_timeout_is_bounded_and_next_script_still_executes(self):
        result = run_detector(self.plugin('import time;time.sleep(5)', timeout=0.1), {}, self.catalog)
        self.assertEqual('CHECK_EXECUTION_ERROR', result['issues'][0]['code'])
        result = run_detector(self.plugin('print(\'{"protocol_version":1,"status":"pass","issues":[]}\')'), {}, self.catalog)
        self.assertEqual('pass', result['status'])

    def test_manifest_cannot_escape_plugin_directory(self):
        self.plugin('pass')
        (self.root / 'custom' / 'manifest.toml').write_text('name="custom"\nprotocol_version=1\nentrypoint="../outside.py"\ntimeout=1\n')
        with self.assertRaises(ValueError):
            discover_detectors([self.root])

    def test_nonreading_script_cannot_block_large_input_past_timeout(self):
        script = self.plugin('import time;time.sleep(2)', timeout=0.1)
        started = time.monotonic()
        result = run_detector(script, {'payload': 'x' * 100000}, self.catalog)
        self.assertEqual('CHECK_EXECUTION_ERROR', result['issues'][0]['code'])
        self.assertLess(time.monotonic() - started, 1)
