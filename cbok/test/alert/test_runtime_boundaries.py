"""Deterministic clock/transport interleavings, using isolated SQLite state."""
from datetime import timedelta
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from cbok.alert import models
from cbok.alert.monitoring import service

PASS = {'protocol_version': 1, 'status': 'pass', 'issues': []}
FAIL = {'protocol_version': 1, 'status': 'fail', 'issues': [
    {'code': 'SECTION_CHANGED', 'rule_id': 'required', 'message': 'Missing field'}]}


class RuntimeBoundaryTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.plugin('slow', 120)
        self.plugin('fast', 2)
        override = self.settings(ALERT_DETECTOR_PATHS=[self.root])
        override.enable()
        self.addCleanup(override.disable)
        self.source = models.Source.objects.create(key='source', kind='test', adapter='test')
        self.section = models.Section.objects.create(source=self.source, key='section', name='Section')
        self.check = models.DetectorCheck.objects.create(section=self.section, key='first', detector='slow')
        self.channel = self.add_channel('first')

    def plugin(self, name, timeout=2, directory=None):
        path = self.root / (directory or name)
        path.mkdir()
        (path / 'manifest.toml').write_text(
            f'name="{name}"\nprotocol_version=1\nentrypoint="check.py"\ntimeout={timeout}\n')
        (path / 'check.py').write_text('print(\'{"protocol_version":1,"status":"pass","issues":[]}\')\n')
        return path

    def add_channel(self, key):
        channel = models.NotificationChannel.objects.create(
            key=key, kind='email', config={'to': [f'{key}@example.invalid']})
        self.source.notification_channels.add(channel)
        return channel

    def apply(self, result, notify=True):
        with patch.object(service, 'run_detector', return_value=result):
            return service.run_check(self.check.pk, apply=True, notify=notify)

    def test_slow_previous_check_does_not_consume_next_checks_lease(self):
        second = models.DetectorCheck.objects.create(section=self.section, key='second', detector='fast')
        clock = [timezone.now()]
        leases = []
        competing_claims = []
        def run(spec, *args):
            if spec.name == 'slow':
                clock[0] += timedelta(seconds=100)
                return PASS
            second.refresh_from_db()
            leases.append((second.lease_until - clock[0]).total_seconds())
            competing_claims.append(service._claim(second.pk, 62))
            return FAIL
        with patch.object(service.timezone, 'now', side_effect=lambda: clock[0]), patch.object(service, 'run_detector', side_effect=run):
            results = service.run_due_checks()
        self.assertEqual([62], leases)
        self.assertEqual([None], competing_claims)
        self.assertFalse(any(r.get('stale') for r in results))
        self.assertEqual('SECTION_CHANGED', models.Incident.objects.get(detector_check=second).anomaly_type.code)
        second.refresh_from_db()
        self.assertGreater(second.next_run_at, clock[0])

    def test_each_send_gets_full_lease_after_slow_previous_sends(self):
        for i in range(3):
            self.add_channel(f'other{i}')
        self.apply(FAIL)
        clock = [timezone.now()]
        leases = []
        reclaimable = []
        def bounded_send(*args):
            row = models.NotificationDelivery.objects.exclude(lease_token='').get()
            leases.append((row.lease_until - clock[0]).total_seconds())
            reclaimable.append(models.NotificationDelivery.objects.filter(pk=row.pk).filter(service._eligible_lease(clock[0])).exists())
            clock[0] += timedelta(seconds=150)
        with patch.object(service.timezone, 'now', side_effect=lambda: clock[0]), patch.object(service, 'send_notification', side_effect=bounded_send):
            summary = service.deliver_pending()
        self.assertEqual([360, 360, 360, 360], leases)
        self.assertEqual([False] * 4, reclaimable)
        self.assertEqual(4, summary['sent'])
        self.assertEqual(4, models.NotificationDelivery.objects.filter(status='sent').count())

    def test_bad_manifests_and_conflicts_leave_healthy_runtime_checks_available(self):
        bad = self.root / 'bad-toml'
        bad.mkdir()
        (bad / 'manifest.toml').write_text('name = invalid TOML')
        missing = self.plugin('missing')
        (missing / 'check.py').unlink()
        self.plugin('conflict', directory='duplicate-a')
        self.plugin('conflict', directory='duplicate-b')
        for name in ('missing', 'conflict', 'bad-toml'):
            models.DetectorCheck.objects.create(section=self.section, key=name, detector=name)
        results = service.run_due_checks()
        self.check.refresh_from_db()
        self.assertEqual('pass', self.check.last_result['status'])
        self.assertEqual(3, sum(r['issues'][0]['code'] == 'CHECK_CONFIG_ERROR' for r in results if r['issues']))
        self.assertEqual('pass', service.run_check(self.check.pk)['status'])

    def test_runtime_discovery_diagnostics_are_bounded_and_conflicts_unavailable(self):
        from cbok.alert.monitoring.plugins import discover_detectors
        self.plugin('conflict', directory='duplicate-a')
        self.plugin('conflict', directory='duplicate-b')
        diagnostics = []
        found = discover_detectors([self.root], strict=False, diagnostics=diagnostics)
        self.assertIn('slow', found)
        self.assertNotIn('conflict', found)
        self.assertTrue(diagnostics)
        self.assertLessEqual(len(diagnostics), 100)
        self.assertLessEqual(len(str(diagnostics[0])), 1024)
        with self.assertRaises(ValueError):
            discover_detectors([self.root])

    def interleaved_send(self, transition='resolve', success=True, notify=True, recovery=True):
        second = self.add_channel('second')
        if not recovery:
            self.check.config = {'policies': {'SECTION_CHANGED': {'recovery': False}}}
            self.check.save()
        self.apply(FAIL)
        incident = models.Incident.objects.get()
        def send(*args):
            if transition == 'supersede':
                self.check.refresh_from_db()
                self.check.config = {'params': {'new': True}}
                self.check.save()
            self.apply(PASS, notify=notify)
            if not success:
                raise TimeoutError('transport timed out')
        with patch.object(service, 'send_notification', side_effect=send):
            summary = service.deliver_pending()
        alert = models.NotificationDelivery.objects.get(incident=incident, channel=self.channel, event_kind='alert')
        self.assertEqual('sent' if success else 'cancelled', alert.status)
        self.assertEqual(1 if success else 0, summary['sent'])
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get(incident=incident, channel=second, event_kind='alert').status)
        recoveries = models.NotificationDelivery.objects.filter(incident=incident, event_kind='recovery')
        self.assertEqual(1 if success and notify and recovery and transition == 'resolve' else 0, recoveries.count())
        if recoveries.exists():
            self.assertEqual(self.channel.pk, recoveries.get().channel_id)
            self.assertEqual(1, service.deliver_pending()['sent'])

    def test_recovery_during_successful_send_preserves_ack_and_sends_recovery(self):
        self.interleaved_send()

    def test_silent_recovery_during_send_does_not_later_authorize_notification(self):
        self.interleaved_send(notify=False)
        self.apply(PASS)
        self.assertFalse(models.NotificationDelivery.objects.filter(event_kind='recovery').exists())

    def test_disabled_recovery_policy_during_successful_send_preserves_ack_only(self):
        self.interleaved_send(recovery=False)

    def test_recovery_during_failed_send_cancels_without_orphan_recovery(self):
        self.interleaved_send(success=False)

    def test_supersession_during_successful_send_preserves_ack_without_false_recovery(self):
        self.interleaved_send(transition='supersede')

    def test_supersession_during_failed_send_cancels_without_recovery(self):
        self.interleaved_send(transition='supersede', success=False)

    def test_smtp_timeout_is_finite_and_next_delivery_and_check_can_run(self):
        self.add_channel('second')
        self.apply(FAIL)
        timeouts = []
        from smtplib import SMTP
        def smtp(*args, **kwargs):
            timeouts.append(kwargs.get('timeout'))
            if len(timeouts) == 1:
                raise TimeoutError('greeting timed out')
            from unittest.mock import MagicMock
            connection = MagicMock(spec=SMTP)
            connection.sendmail.return_value = {}
            return connection
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='smtp.example.invalid', EMAIL_USE_TLS=False, EMAIL_USE_SSL=False, EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD=''), patch('django.core.mail.backends.smtp.smtplib.SMTP', side_effect=smtp):
            summary = service.deliver_pending()
        self.assertEqual({'sent': 1, 'failed': 1, 'cancelled': 0, 'skipped': 0}, summary)
        self.assertTrue(all(type(timeout) in (int, float) and 0 < timeout <= 30 for timeout in timeouts), timeouts)
        self.assertEqual('failed', models.NotificationDelivery.objects.order_by('pk').first().status)
        models.DetectorCheck.objects.update(next_run_at=None)
        self.assertEqual('pass', service.run_due_checks()[0]['status'])
