from unittest import TestCase
from unittest.mock import patch
from cbok.batch import BatchProcessor


class BatchTests(TestCase):
    def test_two_tasks_capture_separate_functions_and_intervals(self):
        calls, threads, sleeps = [], [], []
        batch = BatchProcessor()
        batch.periodic_tasks = [{'app': 'x', 'name': key, 'interval': interval,
                                  'func': lambda key=key: calls.append(key)}
                                 for key, interval in [('a', 3), ('b', 7)]]
        with patch('cbok.batch.threading.Thread') as thread:
            thread.side_effect = lambda **kwargs: type('Thread', (), {'start': lambda self: threads.append(kwargs['target'])})()
            batch.run_periodic_tasks()
        class EndLoop(BaseException):
            pass
        def sleep(interval):
            sleeps.append(interval)
            raise EndLoop
        with patch('time.sleep', side_effect=sleep):
            for target in threads:
                with self.assertRaises(EndLoop):
                    target()
        self.assertEqual(calls, ['a', 'b'])
        self.assertEqual(sleeps, [3, 7])

    def test_monitor_gate_disabled_and_enabled(self):
        from django.test import override_settings
        from cbok.alert.gate import periodic_monitor
        with override_settings(ALERT_MONITOR_ENABLED=False), patch('cbok.alert.monitoring.service.run_due_checks') as due:
            periodic_monitor()
            due.assert_not_called()
        with override_settings(ALERT_MONITOR_ENABLED=True), patch('cbok.alert.monitoring.service.run_due_checks') as due, patch('cbok.alert.monitoring.service.deliver_pending') as send:
            periodic_monitor()
            due.assert_called_once_with()
            send.assert_called_once_with()
