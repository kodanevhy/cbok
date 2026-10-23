"""Database-authoritative check state and an at-least-once notification outbox.

Detector execution and channel sends happen outside database transactions. Claims
are conditional UPDATEs; every completion verifies its token so an expired worker
cannot overwrite the worker that reclaimed its lease. SMTP acknowledgment followed
by a crash before committing can still cause a duplicate delivery.
"""

from collections import defaultdict
from datetime import timedelta
import hashlib
import json
import logging
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from cbok.alert.models import (
    AnomalyType, CheckRun, DetectorCheck, Incident, NotificationDelivery,
)
from cbok.alert.monitoring.catalog import DEFAULT_POLICY, load_catalog
from cbok.alert.monitoring.plugins import discover_detectors
from cbok.alert.monitoring.runner import failure_result, run_detector
from cbok.notification.channels import NotificationMessage, send_notification


LOG = logging.getLogger(__name__)
_PENDING = ('pending', 'failed')
_SECRET_KEY = re.compile(r'password|passwd|secret|token|authorization|api.?key|credential', re.I)
_URL_CREDENTIALS = re.compile(r'([a-z][a-z0-9+.-]*://)[^/\s@]+@', re.I)
_AUTH_CREDENTIALS = re.compile(r'\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', re.I)
_SECRET_VALUE = re.compile(r'(?i)(password|passwd|secret|token|authorization|api[_-]?key)(\s*[=:]\s*)([^\s,;]+)')


def _safe(value, depth=0):
    """Keep diagnostics bounded and remove common credential-bearing fields."""
    if depth > 5:
        return '[truncated]'
    if isinstance(value, dict):
        return {str(k)[:120]: '[redacted]' if _SECRET_KEY.search(str(k)) else _safe(v, depth + 1)
                for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [_safe(item, depth + 1) for item in value[:30]]
    if isinstance(value, str):
        value = _URL_CREDENTIALS.sub(r'\1[redacted]@', value[:2000])
        value = _AUTH_CREDENTIALS.sub(r'\1 [redacted]', value)
        return _SECRET_VALUE.sub(r'\1\2[redacted]', value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return '[unsupported value]'


def sync_catalog(catalog):
    """Insert missing catalog descriptors, preserving administrator DB edits."""
    for code, descriptor in catalog.items():
        AnomalyType.objects.get_or_create(code=code, defaults={
            'label': descriptor['label'], 'description': descriptor.get('description', ''),
            'scope': descriptor.get('scope', 'contract'),
            'indeterminate': descriptor.get('indeterminate', False),
            'policy': dict(DEFAULT_POLICY, **descriptor.get('policy', {})),
        })


def _catalog(path, apply):
    catalog = load_catalog()
    if path is not None:
        catalog.update(load_catalog(path))
    if apply:
        sync_catalog(catalog)
    for anomaly in AnomalyType.objects.all():
        catalog[anomaly.code] = {
            'code': anomaly.code, 'label': anomaly.label, 'description': anomaly.description,
            'scope': anomaly.scope, 'indeterminate': anomaly.indeterminate,
            'policy': dict(DEFAULT_POLICY, **(anomaly.policy if isinstance(anomaly.policy, dict) else {})),
        }
    return catalog


def _context(check, run_id, catalog=None):
    source = check.section.source
    context = {
        'protocol_version': 1, 'run_id': str(run_id),
        'source': {'key': source.key, 'adapter': source.adapter, 'config': source.config},
        'section': {'key': check.section.key, 'config': check.section.config},
        'check': {'key': check.key, 'config': check.config},
    }
    if catalog is not None:
        context['anomaly_types'] = {code: {
            'code': code, 'label': descriptor['label'],
            'scope': descriptor.get('scope', 'contract'),
            'indeterminate': descriptor.get('indeterminate', False),
        } for code, descriptor in catalog.items()}
    return context


def _revision(check, spec):
    context = _context(check, '')
    context.pop('run_id')
    context['detector'] = check.detector
    context['detector_digest'] = spec.digest if spec else 'missing'
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _eligible_lease(now):
    return Q(lease_until__isnull=True) | Q(lease_until__lte=now)


def _claim(check_id, ttl, now=None, due=False):
    now = now or timezone.now()
    query = DetectorCheck.objects.filter(pk=check_id).filter(_eligible_lease(now))
    if due:
        query = query.filter(enabled=True, section__enabled=True, section__source__enabled=True)
        query = query.filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
    token = uuid.uuid4().hex
    changed = query.update(lease_token=token, lease_until=now + timedelta(seconds=ttl))
    return token if changed else None


def _policy(check, anomaly, strict=True):
    try:
        policy = dict(DEFAULT_POLICY, **anomaly.policy)
        override = check.config.get('policies', {}).get(anomaly.code, {})
        if not isinstance(override, dict):
            raise ValueError('Invalid anomaly policy override')
        policy.update(override)
        if type(policy.get('threshold')) is not int or policy['threshold'] < 1:
            raise ValueError('Invalid anomaly threshold')
        if any(type(policy.get(key)) is not bool for key in ('notify', 'recovery')):
            raise ValueError('Invalid anomaly notification policy')
        return policy
    except (ValueError, TypeError, AttributeError):
        if strict:
            raise ValueError('Invalid anomaly notification policy') from None
        # A malformed policy must itself be persistable as a configuration
        # incident; it cannot prevent error reporting or leave the lease held.
        return dict(DEFAULT_POLICY)


def _cancel(query):
    return query.filter(status__in=_PENDING).update(
        status='cancelled', lease_token='', lease_until=None,
    )


def _payload(incident, event_kind):
    check = incident.detector_check
    event = {
        'event_id': str(incident.pk), 'event_kind': event_kind,
        'code': incident.anomaly_type.code, 'label': incident.anomaly_type.label,
        'source': check.section.source.key, 'section': check.section.key, 'check': check.key,
        'revision': incident.revision, 'configuration_revision': _revision(check, None), 'first_seen': incident.first_seen.isoformat(),
        'last_seen': incident.last_seen.isoformat(), 'issues': incident.details,
    }
    subject = f'[{event_kind}] {incident.anomaly_type.label}: {check.section.source.key}/{check.section.key}/{check.key}'
    return {'subject': subject.replace('\r', ' ').replace('\n', ' ')[:250],
            'body': json.dumps(event, ensure_ascii=False, indent=2), 'metadata': event}


def _enqueue(incident, event_kind, channels):
    for channel in channels:
        NotificationDelivery.objects.get_or_create(
            incident=incident, channel=channel, event_kind=event_kind,
            defaults={'payload': _payload(incident, event_kind)},
        )


def _resolve(incident, now, notify, channels):
    incident.status = 'resolved'
    incident.consecutive_count = 0
    incident.last_seen = now
    incident.save(update_fields=['status', 'consecutive_count', 'last_seen'])
    _cancel(incident.deliveries.filter(event_kind='alert'))
    policy = _policy(incident.detector_check, incident.anomaly_type, strict=False)
    if notify and policy['notify'] and policy['recovery']:
        sent_channel_ids = incident.deliveries.filter(event_kind='alert', status='sent').values_list('channel_id', flat=True)
        _enqueue(incident, 'recovery', channels.filter(pk__in=sent_channel_ids))


def _apply_result(check, result, revision, now, notify):
    old = check.incidents.filter(status='active').exclude(revision=revision)
    old.update(status='superseded', consecutive_count=0)
    # Superseded resolved events can also have a queued recovery.
    _cancel(NotificationDelivery.objects.filter(incident__detector_check=check).exclude(incident__revision=revision))
    grouped = defaultdict(list)
    for issue in result['issues']:
        grouped[issue['code']].append(issue)
    active_ids = []
    channels = check.section.source.notification_channels.filter(enabled=True)
    if notify and grouped and not channels.exists():
        LOG.warning('Alert check %s has no enabled administrator notification channel', check.pk)
    anomalies = {a.code: a for a in AnomalyType.objects.filter(code__in=grouped)}
    has_indeterminate = any(a.indeterminate for a in anomalies.values())
    for code, issues in grouped.items():
        anomaly = anomalies[code]
        rules = sorted({issue['rule_id'] for issue in issues})
        fingerprint = hashlib.sha256(json.dumps([code, rules], sort_keys=True).encode()).hexdigest()
        incident, created = Incident.objects.get_or_create(
            detector_check=check, anomaly_type=anomaly, fingerprint=fingerprint,
            revision=revision, status='active',
            defaults={'first_seen': now, 'last_seen': now, 'details': issues},
        )
        if not created:
            incident.last_seen = now
            incident.occurrences += 1
            incident.consecutive_count += 1
            incident.details = issues
            incident.save(update_fields=['last_seen', 'occurrences', 'consecutive_count', 'details'])
        active_ids.append(incident.pk)
        policy = _policy(check, anomaly, strict=False)
        if notify and policy['notify'] and incident.consecutive_count >= policy['threshold']:
            _enqueue(incident, 'alert', channels)
    absent = check.incidents.filter(status='active', revision=revision).exclude(pk__in=active_ids).select_related('anomaly_type', 'detector_check__section__source')
    for incident in absent:
        if result['status'] == 'pass' or (result['status'] != 'unknown' and not has_indeterminate):
            _resolve(incident, now, notify, channels)
        else:
            # Unknown evidence cannot confirm recovery of an earlier contract.
            incident.consecutive_count = 0
            incident.save(update_fields=['consecutive_count'])
    if active_ids:
        _cancel(NotificationDelivery.objects.filter(incident__detector_check=check, event_kind='recovery'))


def _execute(check, spec, catalog, apply, notify, token=None, config_error=False):
    started = timezone.now()
    revision = _revision(check, spec)
    run = CheckRun.objects.create(detector_check=check, status='running', result={}, revision=revision, started_at=started)
    try:
        if config_error or spec is None:
            result = failure_result('Detector configuration is invalid or detector is not installed', 'CHECK_CONFIG_ERROR')
        else:
            # Validate DB policies before a detector run can mutate formal state.
            for anomaly in AnomalyType.objects.all():
                _policy(check, anomaly)
            result = run_detector(spec, _context(check, run.pk, catalog), catalog)
    except (ValueError, TypeError, KeyError, AttributeError):
        result = failure_result('Check configuration is invalid', 'CHECK_CONFIG_ERROR')
    except Exception:
        result = failure_result('Detector execution failed')
    # Preserve the entire validated business issue list (protocol maximum100).
    # Bound only diagnostic values; arbitrary extra keys cannot displace the
    # required protocol/code/rule fields during dictionary truncation.
    result = {
        'protocol_version': result['protocol_version'], 'status': result['status'],
        'issues': [{key: _safe(issue[key]) for key in
                    ('code', 'rule_id', 'message', 'expected', 'observed', 'evidence')
                    if key in issue} for issue in result['issues']],
    }
    finished = timezone.now()
    stale = False
    if apply:
        with transaction.atomic():
            # A write before reading state serializes ownership validation and all
            # subsequent transitions on SQLite as well as transactional databases.
            owner = DetectorCheck.objects.filter(pk=check.pk, lease_token=token, lease_until__gt=finished)
            if owner.update(lease_token='', lease_until=None):
                current = DetectorCheck.objects.select_related('section__source').get(pk=check.pk)
                if _revision(current, spec) != revision:
                    stale = True
                else:
                    _apply_result(current, result, revision, finished, notify)
                    current.revision = revision
                    current.last_result = result
                    current.next_run_at = finished + timedelta(seconds=current.interval_seconds)
                    current.save(update_fields=['revision', 'last_result', 'next_run_at'])
            else:
                stale = True
    if stale:
        result = dict(result, stale=True)
    run.status, run.result, run.finished_at = result['status'], result, finished
    run.save(update_fields=['status', 'result', 'finished_at'])
    return dict(result, run_id=str(run.pk))


def run_check(check_id, apply=False, notify=False, detector_paths=None, catalog_path=None):
    """Record one check; only explicit apply mutates official state or schedule."""
    if notify and not apply:
        raise ValueError('Notification requires apply=True')
    check = DetectorCheck.objects.select_related('section__source').get(pk=check_id)
    catalog = _catalog(catalog_path, apply)
    config_error = False
    try:
        paths = detector_paths if detector_paths is not None else getattr(settings, 'ALERT_DETECTOR_PATHS', None)
        spec = discover_detectors(paths).get(check.detector)
    except (OSError, ValueError, TypeError):
        spec, config_error = None, True
    token = None
    if apply:
        token = _claim(check.pk, (spec.timeout if spec else 300) + 60)
        if token is None:
            return {'status': 'skipped', 'reason': 'leased', 'check_id': str(check.pk)}
    return _execute(check, spec, catalog, apply, notify, token, config_error)


def run_due_checks(now=None, limit=100):
    """Claim each due check independently, isolating item configuration failures."""
    now = now or timezone.now()
    results = []
    query = DetectorCheck.objects.filter(enabled=True, section__enabled=True, section__source__enabled=True)
    query = query.filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now)).filter(_eligible_lease(now))
    ids = list(query.order_by('next_run_at', 'pk').values_list('pk', flat=True)[:max(0, limit)])
    catalog = _catalog(None, True)
    try:
        detectors, config_error = discover_detectors(getattr(settings, 'ALERT_DETECTOR_PATHS', None)), False
    except (OSError, ValueError, TypeError):
        detectors, config_error = {}, True
    for check_id in ids:
        check = DetectorCheck.objects.select_related('section__source').get(pk=check_id)
        spec = detectors.get(check.detector)
        token = _claim(check_id, (spec.timeout if spec else 300) + 60, now=now, due=True)
        if token is None:
            continue
        try:
            results.append(_execute(check, spec, catalog, True, True, token, config_error))
        except Exception:
            # Do not include exception text from source configs or transports.
            LOG.error('Alert check %s could not persist its result', check_id)
            DetectorCheck.objects.filter(pk=check_id, lease_token=token).update(
                lease_token='', lease_until=None,
                next_run_at=timezone.now() + timedelta(seconds=check.interval_seconds),
            )
            results.append({'status': 'unknown', 'check_id': str(check_id), 'error': 'Check persistence failed'})
    return results


def _delivery_is_current(delivery):
    incident = delivery.incident
    check = incident.detector_check
    if not (delivery.channel.enabled and check.enabled and check.section.enabled and check.section.source.enabled):
        return False
    if not check.section.source.notification_channels.filter(pk=delivery.channel_id).exists():
        return False
    if (check.revision != incident.revision
            or delivery.payload.get('metadata', {}).get('configuration_revision') != _revision(check, None)):
        return False
    if delivery.event_kind == 'alert':
        return incident.status == 'active'
    if delivery.event_kind == 'recovery':
        return (incident.status == 'resolved'
                and not check.incidents.filter(status='active').exists()
                and incident.deliveries.filter(channel=delivery.channel, event_kind='alert', status='sent').exists())
    return False


def _retry_config(channel):
    config = channel.config.get('retry', {}) if isinstance(channel.config, dict) else {}
    config = config if isinstance(config, dict) else {}
    def positive(key, default, maximum):
        value = config.get(key, default)
        return min(value, maximum) if type(value) is int and value > 0 else default
    default_attempts = getattr(settings, 'ALERT_NOTIFICATION_MAX_ATTEMPTS', 5)
    if type(default_attempts) is not int or not 1 <= default_attempts <= 20:
        default_attempts = 5
    return (positive('max_attempts', default_attempts, 20),
            positive('base_seconds', 30, 3600), positive('max_seconds', 3600, 86400))


def deliver_pending(limit=100):
    """Send claimed current events, with bounded retries and no raw error text."""
    now = timezone.now()
    summary = {'sent': 0, 'failed': 0, 'cancelled': 0, 'skipped': 0}
    query = NotificationDelivery.objects.filter(status__in=_PENDING).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
    ).filter(_eligible_lease(now))
    ids = list(query.order_by('pk').values_list('pk', flat=True)[:max(0, limit)])
    for delivery_id in ids:
        token = uuid.uuid4().hex
        with transaction.atomic():
            claimed = NotificationDelivery.objects.filter(pk=delivery_id, status__in=_PENDING).filter(
                Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
            ).filter(_eligible_lease(now)).update(
                lease_token=token, lease_until=now + timedelta(seconds=360),
            )
            if not claimed:
                summary['skipped'] += 1
                continue
            delivery = NotificationDelivery.objects.select_related('channel', 'incident__anomaly_type', 'incident__detector_check__section__source').get(pk=delivery_id)
            owner = NotificationDelivery.objects.filter(pk=delivery_id, lease_token=token, status__in=_PENDING)
            if not _delivery_is_current(delivery):
                owner.update(status='cancelled', lease_token='', lease_until=None)
                summary['cancelled'] += 1
                continue
            max_attempts, base, cap = _retry_config(delivery.channel)
            if delivery.attempts >= max_attempts:
                owner.update(status='exhausted', lease_token='', lease_until=None)
                summary['skipped'] += 1
                continue
            delivery.attempts += 1
            owner.update(attempts=delivery.attempts)
        try:
            send_notification(delivery.channel.kind, delivery.channel.config, NotificationMessage(**delivery.payload))
        except Exception:
            finished = timezone.now()
            changed = owner.filter(lease_until__gt=finished).update(
                status='exhausted' if delivery.attempts >= max_attempts else 'failed',
                last_error='Notification channel failed; delivery was not confirmed',
                next_attempt_at=finished + timedelta(seconds=min(cap, base * 2 ** (delivery.attempts - 1))),
                lease_token='', lease_until=None,
            )
            summary['failed' if changed else 'skipped'] += 1
        else:
            finished = timezone.now()
            changed = owner.filter(lease_until__gt=finished).update(
                status='sent', sent_at=finished, last_error='', next_attempt_at=None,
                lease_token='', lease_until=None,
            )
            summary['sent' if changed else 'skipped'] += 1
    return summary
