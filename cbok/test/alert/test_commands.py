from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import TestCase


class CommandTests(TestCase):
    def setUp(self):
        from cbok.cmd.alert import AlertCommands
        self.command = AlertCommands()

    def test_register_list_collect_check_once(self):
        from cbok.alert.models import DetectorCheck
        with redirect_stdout(StringIO()):
            self.assertEqual(self.command.register(), 0)
        stream = StringIO()
        with redirect_stdout(stream):
            self.assertEqual(self.command.list(kind='checks'), 0)
        self.assertEqual(len(json.loads(stream.getvalue())['checks']), 9)
        with patch('cbok.alert.monitoring.bootstrap.collect_items', return_value=[]) as collect, redirect_stdout(StringIO()):
            self.assertEqual(self.command.collect(source='tencent', section='news', limit=4), 0)
            collect.assert_called_once_with('tencent', 'news', 4)
        check_id = DetectorCheck.objects.first().pk
        with patch('cbok.alert.monitoring.service.run_check', return_value={'status': 'pass'}) as run, patch('cbok.alert.monitoring.service.deliver_pending') as send, redirect_stdout(StringIO()):
            self.assertEqual(self.command.check(id=check_id), 0)
            run.assert_called_once_with(check_id, apply=False, notify=False)
            send.assert_not_called()
        with patch('cbok.alert.monitoring.service.run_due_checks', return_value=[]) as due, patch('cbok.alert.monitoring.service.deliver_pending', return_value={}) as send, redirect_stdout(StringIO()):
            self.assertEqual(self.command.run(once=True), 0)
            due.assert_called_once_with()
            send.assert_called_once_with()

    def test_notify_requires_apply_before_running(self):
        with patch('cbok.alert.monitoring.service.run_check') as run, patch('cbok.cmd.output.LOG.error'), patch('sys.stderr', new_callable=StringIO):
            with self.assertRaises(SystemExit) as error:
                self.command.check(id=1, notify=True)
            self.assertNotEqual(error.exception.code, 0)
            run.assert_not_called()

    def test_explicit_notification_and_model_check(self):
        with patch('cbok.alert.monitoring.service.run_check', return_value={}) as run, patch('cbok.alert.monitoring.service.deliver_pending', return_value={}) as send, redirect_stdout(StringIO()):
            self.command.check(id=1, apply=True, notify=True)
            run.assert_called_once_with(1, apply=True, notify=True)
            send.assert_called_once_with()
        with patch('cbok.alert.model_profiles.configured_model_client') as client, redirect_stdout(StringIO()):
            client.return_value.ask.return_value = 'test response'
            self.assertEqual(self.command.model_check(profile='local', prompt='test'), 0)
            client.assert_called_once_with('local')
            client.return_value.ask.assert_called_once_with([{'role': 'user', 'content': 'test'}])

    def test_file_import_json_toml_and_safe_error(self):
        from cbok.alert.models import Source
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            path = Path(directory) / 'register.toml'
            path.write_text('[[sources]]\nkey="local"\nkind="web"\nadapter="tencent"\n')
            self.command.register(file=str(path))
            self.assertTrue(Source.objects.filter(key='local').exists())
            path = Path(directory) / 'register.json'
            path.write_text(json.dumps({'sources': [{'key': 'two', 'kind': 'web', 'adapter': 'tencent'}]}))
            self.command.register(file=str(path))
            self.assertTrue(Source.objects.filter(key='two').exists())
        with patch('cbok.alert.monitoring.bootstrap.collect_items', side_effect=RuntimeError('secret-value')), patch('cbok.cmd.output.LOG.error'), patch('sys.stderr', new_callable=StringIO) as stderr:
            with self.assertRaises(SystemExit):
                self.command.collect(source='x', section='x')
            self.assertNotIn('secret-value', stderr.getvalue())

    def test_help_in_process_patches_only_existing_guards(self):
        from cbok.cmd import main
        directory = os.getcwd()
        try:
            for name in ('register', 'list', 'collect', 'check', 'run', 'model_check'):
                with self.subTest(name=name), patch.object(main, '_ensure_source_branch_is_master'), patch.object(main, '_resolve_and_reexec_venv'), patch('cbok.utils.assert_cbok_home', return_value=directory), patch('sys.argv', ['cbok', 'alert', name, '--help']), patch('cbok.alert.monitoring.service.run_due_checks') as due, redirect_stdout(StringIO()) as stdout:
                    with self.assertNumQueries(0), self.assertRaises(SystemExit) as error:
                        main.main()
                    self.assertEqual(error.exception.code, 0)
                    self.assertIn('usage:', stdout.getvalue())
                    due.assert_not_called()
        finally:
            os.chdir(directory)
