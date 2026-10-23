"""Real SQLite state-machine tests with local protocol-v1 subprocess fixtures."""
import importlib
import json
from pathlib import Path
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from cbok.alert import models
from cbok.notification.channels import register_channel


class MonitoringStateTests(TestCase):
    def setUp(self):
        for name in ('Source', 'Section', 'DetectorCheck', 'AnomalyType', 'CheckRun',
                     'Incident', 'NotificationChannel', 'NotificationDelivery',
                     'CollectedItem', 'ModelProfile'):
            self.assertIsNotNone(getattr(models, name, None), f'Missing persistent {name}')
        self.service = importlib.import_module('cbok.alert.monitoring.service')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.result_path = self.root / 'result.json'
        plugin = self.root / 'plugin'
        plugin.mkdir()
        (plugin / 'manifest.toml').write_text('name="fixture"\nprotocol_version=1\nentrypoint="check.py"\ntimeout=2\nmax_output_bytes=8192\n')
        (plugin / 'check.py').write_text('import json,sys\nx=json.load(sys.stdin)\nassert x["protocol_version"]==1\nassert x["source"]["adapter"]=="fixture-source"\nassert x["section"]["key"]=="news"\nprint(open(x["check"]["config"]["params"]["result_path"]).read())\n')
        self.catalog = self.root / 'types.toml'
        self.catalog.write_text('[anomalies.CUSTOM_FAILURE]\nlabel="Custom contract"\nscope="contract"\n[anomalies.OTHER_FAILURE]\nlabel="Other contract"\nscope="contract"\n')
        self.source = models.Source.objects.create(key='fixture', kind='news', adapter='fixture-source')
        self.section = models.Section.objects.create(source=self.source, key='news', name='News')
        self.check = models.DetectorCheck.objects.create(section=self.section, key='feed', detector='fixture', config={'params': {'result_path': str(self.result_path)}})
        self.channel = models.NotificationChannel.objects.create(key='admin', kind='email', config={'to': ['admin@example.invalid']})
        self.source.notification_channels.add(self.channel)
        self.output()

    def output(self, code=None, rule='required', status=None, message='Required field missing'):
        self.result_path.write_text(json.dumps({'protocol_version': 1, 'status': status or ('fail' if code else 'pass'), 'issues': [] if not code else [{'code': code, 'rule_id': rule, 'message': message}]}))

    def run_check(self, apply=True, notify=True):
        return self.service.run_check(self.check.pk, apply=apply, notify=notify, detector_paths=[self.root], catalog_path=self.catalog)

    def test_new_catalog_type_persists_and_delivers_through_registered_channel(self):
        self.output('CUSTOM_FAILURE')
        result = self.run_check()
        self.assertEqual('fail', result['status'])
        self.assertEqual(1, models.CheckRun.objects.count())
        self.assertEqual(result['run_id'], str(models.CheckRun.objects.get().pk))
        incident = models.Incident.objects.get()
        self.assertEqual('CUSTOM_FAILURE', incident.anomaly_type.code)
        self.assertEqual('active', incident.status)
        delivery = models.NotificationDelivery.objects.get()
        self.assertEqual('pending', delivery.status)
        self.service.deliver_pending()
        delivery.refresh_from_db()
        self.assertEqual('sent', delivery.status)
        self.assertEqual(['admin@example.invalid'], mail.outbox[0].to)
        self.assertIn('CUSTOM_FAILURE', mail.outbox[0].body)
        self.assertIn('fixture', mail.outbox[0].body)

    def test_threshold_records_immediately_and_deduplicates_ongoing_issue(self):
        self.check.config['policies'] = {'CUSTOM_FAILURE': {'threshold': 2}}
        self.check.save()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        incident = models.Incident.objects.get()
        self.assertEqual(1, incident.occurrences)
        self.assertEqual(0, models.NotificationDelivery.objects.count())
        self.run_check()
        self.run_check()
        incident.refresh_from_db()
        self.assertEqual(3, incident.occurrences)
        self.assertEqual(3, models.CheckRun.objects.count())
        self.assertEqual(1, models.NotificationDelivery.objects.count())

    def test_threshold_requires_consecutive_occurrences(self):
        self.check.config['policies'] = {'CUSTOM_FAILURE': {'threshold': 2}}
        self.check.save()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.output('NETWORK_ERROR', status='unknown')
        self.run_check()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.assertEqual(0, models.NotificationDelivery.objects.filter(incident__anomaly_type__code='CUSTOM_FAILURE').count())
        self.run_check()
        self.assertEqual(1, models.NotificationDelivery.objects.filter(incident__anomaly_type__code='CUSTOM_FAILURE').count())

    def test_sent_alert_recovers_once_and_recurrence_creates_new_incident(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        first = models.Incident.objects.get()
        self.service.deliver_pending()
        self.output()
        self.run_check()
        self.run_check()
        first.refresh_from_db()
        self.assertEqual('resolved', first.status)
        self.assertEqual(1, models.NotificationDelivery.objects.filter(event_kind='recovery').count())
        self.service.deliver_pending()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.assertEqual(2, models.Incident.objects.count())
        self.assertEqual(2, models.NotificationDelivery.objects.filter(event_kind='alert').count())

    def test_unsent_recovered_alert_is_cancelled_without_orphan_recovery(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.output()
        self.run_check()
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get().status)
        self.service.deliver_pending()
        self.assertEqual(0, len(getattr(mail, 'outbox', [])))

    def test_recurrence_cancels_stale_recovery(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.service.deliver_pending()
        self.output()
        self.run_check()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get(event_kind='recovery').status)

    def test_unavailability_preserves_existing_contract_incident_without_false_recovery(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.service.deliver_pending()
        self.output('NETWORK_ERROR', status='unknown')
        self.run_check()
        self.assertEqual(2, models.Incident.objects.filter(status='active').count())
        self.assertEqual(0, models.NotificationDelivery.objects.filter(event_kind='recovery').count())
        self.assertEqual(1, models.NotificationDelivery.objects.filter(incident__anomaly_type__code='NETWORK_ERROR').count())

    def test_dry_run_never_changes_formal_state_or_creates_deliveries(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        original = models.Incident.objects.get()
        self.check.refresh_from_db()
        before = (self.check.next_run_at, self.check.revision, self.check.last_result)
        self.output()
        self.run_check(apply=False, notify=False)
        original.refresh_from_db()
        self.check.refresh_from_db()
        self.assertEqual('active', original.status)
        self.assertEqual(1, original.occurrences)
        self.assertEqual(before, (self.check.next_run_at, self.check.revision, self.check.last_result))
        self.assertEqual(1, models.NotificationDelivery.objects.count())
        self.assertEqual(2, models.CheckRun.objects.count())

    def test_notify_requires_apply(self):
        with self.assertRaises(ValueError):
            self.run_check(apply=False, notify=True)
        self.assertEqual(0, models.CheckRun.objects.count())

    def test_config_revision_supersedes_incident_and_cancels_old_delivery(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        first = models.Incident.objects.get()
        self.check.refresh_from_db()
        self.check.config['contracts'] = [{'rule_id': 'new'}]
        self.check.save()
        self.run_check()
        first.refresh_from_db()
        self.assertEqual('superseded', first.status)
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get(incident=first).status)
        self.assertEqual(2, models.Incident.objects.count())
        self.assertNotEqual(first.revision, models.Incident.objects.get(status='active').revision)

    def test_messages_do_not_change_fingerprint_but_rule_id_does(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.output('CUSTOM_FAILURE', message='Different article today')
        self.run_check()
        self.assertEqual(1, models.Incident.objects.count())
        self.output('CUSTOM_FAILURE', rule='another-required-field')
        self.run_check()
        self.assertEqual(2, models.Incident.objects.count())

    def test_retry_is_bounded_backed_off_and_does_not_expose_transport_secrets(self):
        def failure(config):
            class Broken:
                def send(self, message):
                    raise RuntimeError('password=secret-value')
            return Broken()
        name = 'failing-' + self._testMethodName
        register_channel(name, failure)
        self.channel.kind = name
        self.channel.save()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.service.deliver_pending()
        delivery = models.NotificationDelivery.objects.get()
        self.assertEqual(1, delivery.attempts)
        self.assertEqual('failed', delivery.status)
        self.assertGreater(delivery.next_attempt_at, timezone.now())
        self.assertNotIn('secret-value', delivery.last_error)
        self.service.deliver_pending()
        delivery.refresh_from_db()
        self.assertEqual(1, delivery.attempts)
        for _ in range(10):
            models.NotificationDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
            self.service.deliver_pending()
        delivery.refresh_from_db()
        self.assertLessEqual(delivery.attempts, 5)
        self.assertEqual('exhausted', delivery.status)

    def test_due_scan_isolates_missing_detector_and_filters_disabled_parents(self):
        second = models.DetectorCheck.objects.create(section=self.section, key='bad', detector='not-installed')
        disabled = models.Source.objects.create(key='disabled', kind='news', adapter='fixture-source', enabled=False)
        section = models.Section.objects.create(source=disabled, key='news', name='Disabled')
        models.DetectorCheck.objects.create(section=section, key='skip', detector='fixture')
        with patch.object(self.service, 'discover_detectors', wraps=lambda paths=None: importlib.import_module('cbok.alert.monitoring.plugins').discover_detectors([self.root])):
            results = self.service.run_due_checks()
        self.assertEqual(2, len(results))
        self.assertEqual({'pass', 'unknown'}, {r['status'] for r in results})
        self.assertEqual(2, models.CheckRun.objects.count())
        second.refresh_from_db()
        self.assertIsNone(second.lease_until)
        self.assertGreater(second.next_run_at, timezone.now())

    def test_held_lease_prevents_overlap_and_expired_lease_can_be_reclaimed(self):
        models.DetectorCheck.objects.filter(pk=self.check.pk).update(lease_token='other-worker', lease_until=timezone.now() + timedelta(minutes=10))
        self.assertEqual('skipped', self.run_check()['status'])
        self.assertEqual(0, models.CheckRun.objects.count())
        models.DetectorCheck.objects.filter(pk=self.check.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual('pass', self.run_check()['status'])
        self.check.refresh_from_db()
        self.assertEqual('', self.check.lease_token)
        self.assertIsNone(self.check.lease_until)

    def test_replaced_lease_worker_cannot_overwrite_formal_state(self):
        runner = self.service.run_detector
        def replace_lease(*args):
            result = runner(*args)
            models.DetectorCheck.objects.filter(pk=self.check.pk).update(lease_token='replacement', lease_until=timezone.now() + timedelta(minutes=10), last_result={'status': 'replacement'})
            return result
        self.output('CUSTOM_FAILURE')
        with patch.object(self.service, 'run_detector', side_effect=replace_lease):
            result = self.run_check()
        self.assertTrue(result.get('stale'))
        self.assertEqual(0, models.Incident.objects.count())
        self.check.refresh_from_db()
        self.assertEqual('replacement', self.check.lease_token)
        self.assertEqual({'status': 'replacement'}, self.check.last_result)

    def test_delivery_lease_prevents_overlapping_sends(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        models.NotificationDelivery.objects.update(lease_token='other-sender', lease_until=timezone.now() + timedelta(minutes=10))
        self.service.deliver_pending()
        self.assertEqual(0, len(getattr(mail, 'outbox', [])))
        models.NotificationDelivery.objects.update(lease_until=timezone.now() - timedelta(seconds=1))
        self.service.deliver_pending()
        self.assertEqual(1, len(mail.outbox))

    def test_configured_db_anomaly_policy_is_authoritative(self):
        self.service.sync_catalog(importlib.import_module('cbok.alert.monitoring.catalog').load_catalog(self.catalog))
        anomaly = models.AnomalyType.objects.get(code='CUSTOM_FAILURE')
        anomaly.policy = {'threshold': 3, 'notify': True, 'recovery': True}
        anomaly.save()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.run_check()
        self.assertEqual(0, models.NotificationDelivery.objects.count())
        self.run_check()
        self.assertEqual(1, models.NotificationDelivery.objects.count())

    def test_source_section_check_and_item_identity_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.Section.objects.create(source=self.source, key='news', name='Duplicate')
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.DetectorCheck.objects.create(section=self.section, key='feed', detector='fixture')
        models.CollectedItem.objects.create(source=self.source, external_id='article-1', payload={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            models.CollectedItem.objects.create(source=self.source, external_id='article-1', payload={})

    def test_silent_applied_failure_can_notify_on_later_formal_round(self):
        self.output('CUSTOM_FAILURE')
        self.run_check(notify=False)
        self.assertEqual(1, models.Incident.objects.count())
        self.assertEqual(0, models.NotificationDelivery.objects.count())
        self.run_check()
        self.assertEqual(1, models.NotificationDelivery.objects.count())

    def test_each_channel_requires_its_own_successful_alert_before_recovery(self):
        second = models.NotificationChannel.objects.create(key='second', kind='email', config={'to': ['other@example.invalid']})
        self.source.notification_channels.add(second)
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.service.deliver_pending(limit=1)
        self.output()
        self.run_check()
        recovery = models.NotificationDelivery.objects.get(event_kind='recovery')
        self.assertEqual(self.channel.pk, recovery.channel_id)
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get(channel=second).status)

    def test_pending_event_is_cancelled_if_admin_changes_check_config_before_next_run(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.check.refresh_from_db()
        self.check.config['contracts'] = [{'rule_id': 'replacement'}]
        self.check.save()
        self.service.deliver_pending()
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get().status)
        self.assertEqual(0, len(getattr(mail, 'outbox', [])))

    def test_source_and_section_config_edits_invalidate_queued_event(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.section.config['channel_id'] = 'different'
        self.section.save()
        self.service.deliver_pending()
        self.assertEqual('cancelled', models.NotificationDelivery.objects.get().status)

    def test_invalid_db_policy_is_visible_as_configuration_failure(self):
        self.check.config['policies'] = {'CUSTOM_FAILURE': {'threshold': 0}}
        self.check.save()
        self.output('CUSTOM_FAILURE')
        result = self.run_check()
        self.assertEqual('unknown', result['status'])
        self.assertEqual('CHECK_CONFIG_ERROR', result['issues'][0]['code'])
        self.assertEqual('CHECK_CONFIG_ERROR', models.Incident.objects.get().anomaly_type.code)

    def test_invalid_policy_on_execution_issue_cannot_break_error_persistence(self):
        self.check.config['policies'] = {'CHECK_CONFIG_ERROR': {'notify': 'invalid'}}
        self.check.save()
        self.check.detector = 'not-installed'
        self.check.save()
        result = self.run_check()
        self.assertEqual('CHECK_CONFIG_ERROR', result['issues'][0]['code'])
        self.assertEqual(1, models.CheckRun.objects.count())
        self.assertEqual(1, models.Incident.objects.count())
        self.check.refresh_from_db()
        self.assertEqual('', self.check.lease_token)

    def test_replaced_sender_cannot_overwrite_new_sender_state(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        sender = self.service.send_notification
        def replaced(*args):
            sender(*args)
            models.NotificationDelivery.objects.update(lease_token='replacement', lease_until=timezone.now() + timedelta(minutes=10), last_error='replacement sender')
        with patch.object(self.service, 'send_notification', side_effect=replaced):
            self.service.deliver_pending()
        delivery = models.NotificationDelivery.objects.get()
        self.assertEqual('pending', delivery.status)
        self.assertEqual('replacement', delivery.lease_token)
        self.assertEqual('replacement sender', delivery.last_error)

    def test_recovery_policy_can_disable_recovery_event(self):
        self.check.config['policies'] = {'CUSTOM_FAILURE': {'recovery': False}}
        self.check.save()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.service.deliver_pending()
        self.output()
        self.run_check()
        self.assertEqual('resolved', models.Incident.objects.get().status)
        self.assertFalse(models.NotificationDelivery.objects.filter(event_kind='recovery').exists())

    def test_db_indeterminate_metadata_controls_unknown_preservation(self):
        self.service.sync_catalog(importlib.import_module('cbok.alert.monitoring.catalog').load_catalog(self.catalog))
        anomaly = models.AnomalyType.objects.get(code='OTHER_FAILURE')
        anomaly.indeterminate = True
        anomaly.scope = 'availability'
        anomaly.save()
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.output('OTHER_FAILURE', status='fail')
        self.run_check()
        self.assertEqual(2, models.Incident.objects.filter(status='active').count())

    def test_run_is_visible_before_external_detector_finishes(self):
        runner = self.service.run_detector
        def observe_run(*args):
            persisted = models.CheckRun.objects.get()
            self.assertEqual('running', persisted.status)
            self.assertIsNone(persisted.finished_at)
            return runner(*args)
        with patch.object(self.service, 'run_detector', side_effect=observe_run):
            self.run_check()
        self.assertEqual('pass', models.CheckRun.objects.get().status)

    def test_changed_active_rule_does_not_leave_old_recovery_queued(self):
        self.output('CUSTOM_FAILURE')
        self.run_check()
        self.service.deliver_pending()
        self.output('CUSTOM_FAILURE', rule='new-required-field')
        self.run_check()
        self.assertFalse(models.NotificationDelivery.objects.filter(event_kind='recovery', status__in=['pending', 'failed']).exists())

    def test_invalid_channel_retry_configuration_does_not_block_other_channels(self):
        self.channel.config = {'to': [], 'retry': 'invalid'}
        self.channel.save()
        second = models.NotificationChannel.objects.create(key='healthy', kind='email', config={'to': ['healthy@example.invalid']})
        self.source.notification_channels.add(second)
        self.output('CUSTOM_FAILURE')
        self.run_check()
        result = self.service.deliver_pending()
        self.assertEqual(1, result['sent'])
        self.assertEqual(1, result['failed'])
        self.assertEqual('sent', models.NotificationDelivery.objects.get(channel=second).status)
        self.assertEqual(['healthy@example.invalid'], mail.outbox[0].to)

    def test_persisted_diagnostics_redact_transport_credentials(self):
        self.result_path.write_text(json.dumps({'protocol_version': 1, 'status': 'fail', 'issues': [{
            'code': 'CUSTOM_FAILURE', 'rule_id': 'required',
            'message': 'Authorization: Bearer credential-one',
            'evidence': {'url': 'https://user:credential-two@example.invalid/article', 'api_key': 'credential-three'},
        }]}))
        self.run_check()
        persisted = json.dumps(models.CheckRun.objects.get().result)
        payload = json.dumps(models.NotificationDelivery.objects.get().payload)
        for secret in ('credential-one', 'credential-two', 'credential-three'):
            self.assertNotIn(secret, persisted)
            self.assertNotIn(secret, payload)

    def test_settings_detector_paths_apply_to_manual_and_due_runs(self):
        with self.settings(ALERT_DETECTOR_PATHS=[self.root]):
            result = self.service.run_check(self.check.pk, apply=True)
            self.assertEqual('pass', result['status'])
            models.DetectorCheck.objects.filter(pk=self.check.pk).update(next_run_at=None)
            results = self.service.run_due_checks()
            self.assertEqual(['pass'], [run['status'] for run in results])

    def test_all_100_protocol_issues_are_persisted_and_final_type_creates_incident(self):
        manifest = self.root / 'plugin' / 'manifest.toml'
        manifest.write_text(manifest.read_text().replace('max_output_bytes=8192', 'max_output_bytes=65536'))
        issues = [{'code': 'CUSTOM_FAILURE', 'rule_id': f'required-{i}', 'message': 'Missing'} for i in range(99)]
        issues.append({'code': 'OTHER_FAILURE', 'rule_id': 'final', 'message': 'Final missing'})
        self.result_path.write_text(json.dumps({'protocol_version': 1, 'status': 'fail', 'issues': issues}))
        result = self.run_check()
        self.assertEqual(100, len(result['issues']))
        self.assertEqual(100, len(models.CheckRun.objects.get().result['issues']))
        self.assertEqual({'CUSTOM_FAILURE', 'OTHER_FAILURE'}, set(models.Incident.objects.values_list('anomaly_type__code', flat=True)))
        self.assertEqual(2, models.NotificationDelivery.objects.count())

    def test_extra_diagnostic_fields_cannot_displace_protocol_business_fields(self):
        issue = {f'extra-{i}': 'diagnostic' for i in range(35)}
        issue.update(code='CUSTOM_FAILURE', rule_id='required', message='Missing')
        result = {f'extra-{i}': 'diagnostic' for i in range(35)}
        result.update(protocol_version=1, status='fail', issues=[issue])
        self.result_path.write_text(json.dumps(result))
        output = self.run_check()
        self.assertEqual('fail', output['status'])
        self.assertEqual('CUSTOM_FAILURE', models.Incident.objects.get().anomaly_type.code)

    def test_detector_context_receives_safe_catalog_descriptors_without_policy(self):
        (self.root / 'plugin' / 'check.py').write_text('''import json,sys
x=json.load(sys.stdin)
assert x['anomaly_types']['CUSTOM_FAILURE']=={'code':'CUSTOM_FAILURE','label':'Custom contract','scope':'contract','indeterminate':False}
assert all(set(value)=={'code','label','scope','indeterminate'} for value in x['anomaly_types'].values())
print(json.dumps({'protocol_version':1,'status':'pass','issues':[]}))
''')
        result = self.run_check()
        self.assertEqual('pass', result['status'])
