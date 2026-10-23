"""Explicit database registration and bounded collection; no work on import."""

from collections.abc import Mapping
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from cbok.alert import models
from cbok.alert.llm import list_backends, _reject_inline_credentials, _profile
from cbok.alert.sources import create_source, list_sources
from cbok.notification.channels import list_channels
from .catalog import load_catalog
from .contracts import list_rules
from .plugins import discover_detectors
from .service import sync_catalog


class RegistrationError(ValueError):
    """Safe configuration diagnostic suitable for CLI output."""


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,119}', value):
        raise RegistrationError(f'{label} must be a valid nonempty identifier (maximum 120 characters)')
    return value


def _positive(value, label):
    if type(value) is not int or value < 1:
        raise RegistrationError(f'{label} must be a positive integer')


def _rows(data, kind):
    rows = data.get(kind, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RegistrationError(f'{kind} must be a list of objects')
    seen = set()
    for row in rows:
        key = _identifier(row.get('code' if kind == 'anomaly_types' else 'key'), kind)
        if 'enabled' in row and type(row['enabled']) is not bool:
            raise RegistrationError('enabled must be boolean')
        for reference in (('source', 'section') if kind == 'checks' else (('source',) if kind == 'sections' else ())):
            _identifier(row.get(reference), f'{kind} {reference}')
        identity = (row.get('source'), row.get('section'), key) if kind == 'checks' else ((row.get('source'), key) if kind == 'sections' else key)
        if identity in seen:
            raise RegistrationError(f'Duplicate {kind} identifier: {key}')
        seen.add(identity)
    return rows


def _save(model, lookup, values, update):
    allowed = {field.name for field in model._meta.fields if not field.primary_key}
    if model is models.DetectorCheck:
        allowed = {'key', 'detector', 'config', 'interval_seconds', 'enabled'}
    unknown = set(values) - allowed
    if unknown:
        raise RegistrationError(f'Unknown {model.__name__} fields: {", ".join(sorted(unknown))}')
    obj = model(**lookup, **values)
    try:
        obj.clean_fields(exclude=['id'])
    except ValidationError:
        raise RegistrationError(f'Invalid {model.__name__} field values') from None
    method = model.objects.update_or_create if update else model.objects.get_or_create
    return method(**lookup, defaults=values)[0]


def _contract_config(config, catalog):
    if not isinstance(config, dict):
        raise RegistrationError('Check config must be an object')
    rules = config.get('contracts', [])
    if not isinstance(rules, list):
        raise RegistrationError('contracts must be a list')
    registered = dict(list_rules())
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise RegistrationError('Each contract must be an object')
        rule_id = _identifier(rule.get('id'), 'Rule ID')
        if rule_id in ids:
            raise RegistrationError('Duplicate contract rule ID')
        ids.add(rule_id)
        kind = rule.get('kind')
        if kind not in registered or rule.get('code', 'SECTION_CHANGED') not in catalog:
            raise RegistrationError('Contract references unknown rule or anomaly type')
        if kind in ('required', 'equals', 'nonempty', 'type', 'min_items'):
            path = rule.get('path')
            if not isinstance(path, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+))*', path):
                raise RegistrationError('Contract path must be a valid dotted path')
        if kind == 'equals' and 'expected' not in rule:
            raise RegistrationError('Equality contract requires expected')
        if kind == 'type' and rule.get('expected') not in ('object', 'array', 'string', 'number', 'boolean', 'null'):
            raise RegistrationError('Unknown expected contract type')
        if kind in ('min_items', 'html_selector'):
            minimum = rule.get('minimum', 1)
            if type(minimum) is not int or minimum < (1 if kind == 'html_selector' else 0):
                raise RegistrationError('Invalid contract minimum')
        if kind == 'html_selector':
            from bs4 import BeautifulSoup
            try:
                selector = rule.get('selector')
                if not isinstance(selector, str) or not selector:
                    raise RegistrationError()
                BeautifulSoup('', 'html.parser').select(selector)
            except Exception:
                raise RegistrationError('Invalid HTML contract selector') from None


@transaction.atomic
def register_configuration(data, update=False):
    """Import JSON-compatible records. Existing DB edits survive normal imports.

    Sections refer to ``source`` keys; checks refer to ``source`` + ``section``
    keys. Channels are referenced by key in each source's notification_channels.
    Credentials are environment variable references; no clients are initialized.
    """
    if not isinstance(data, Mapping):
        raise RegistrationError('Registration data must be an object')
    groups = {name: _rows(data, name) for name in (
        'sources', 'sections', 'checks', 'anomaly_types', 'notification_channels', 'model_profiles')}
    catalog = load_catalog(data.get('catalog'))
    sync_catalog(catalog)
    adapters = dict(list_sources())
    channels = dict(list_channels())
    backends = list_backends()
    detectors = discover_detectors(getattr(settings, 'ALERT_DETECTOR_PATHS', None))
    for row in groups['anomaly_types']:
        values = dict(row)
        code = values.pop('code')
        if not re.fullmatch('[A-Z][A-Z0-9_]*', code):
            raise RegistrationError('Anomaly code must be uppercase')
        policy = values.get('policy', {})
        if not isinstance(policy, dict):
            raise RegistrationError('Anomaly policy must be an object')
        if 'threshold' in policy:
            _positive(policy['threshold'], 'Anomaly threshold')
        for field in ('notify', 'recovery'):
            if field in policy and type(policy[field]) is not bool:
                raise RegistrationError('Anomaly notification policy must be boolean')
        if not values.get('label'):
            raise RegistrationError('Anomaly label is required')
        _save(models.AnomalyType, {'code': code}, values, update)
        catalog[code] = row
    catalog.update({entry.code: {} for entry in models.AnomalyType.objects.all()})
    for row in groups['notification_channels']:
        values = dict(row)
        key = values.pop('key')
        if values.get('kind') not in channels:
            raise RegistrationError('Unknown notification channel kind')
        if not isinstance(values.get('config', {}), dict):
            raise RegistrationError('Channel config must be an object')
        _reject_inline_credentials(values)
        if values.get('enabled', True) and values['kind'] == 'email':
            from cbok.notification.channels import EmailChannel
            try:
                EmailChannel(values.get('config', {}))
            except ValueError:
                raise RegistrationError('Enabled email channel requires valid recipient addresses') from None
        _save(models.NotificationChannel, {'key': key}, values, update)
    for row in groups['model_profiles']:
        values = dict(row)
        key = values.pop('key')
        if values.get('backend') not in backends:
            raise RegistrationError('Unknown model backend')
        _reject_inline_credentials(values)
        _positive(values.get('timeout', 30), 'Model timeout')
        _profile(values)  # structural validation only, no SDK or credential lookup
        if not values.get('model') or not isinstance(values.get('options', {}), dict):
            raise RegistrationError('Model name and object options are required')
        env = values.get('api_key_env')
        if env and (not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env)):
            raise RegistrationError('api_key_env must name an environment variable')
        _save(models.ModelProfile, {'key': key}, values, update)
    for row in groups['sources']:
        values = dict(row)
        key = values.pop('key')
        targets = values.pop('notification_channels', None)
        if values.get('adapter') not in adapters:
            raise RegistrationError('Unknown source adapter')
        if not values.get('kind') or not isinstance(values.get('config', {}), dict):
            raise RegistrationError('Source kind and object config are required')
        _reject_inline_credentials(values)
        resolved = []
        if targets is not None:
            if not isinstance(targets, list) or any(not isinstance(value, str) for value in targets) or len(targets) != len(set(targets)):
                raise RegistrationError('notification_channels must contain unique channel keys')
            for target in targets:
                try:
                    resolved.append(models.NotificationChannel.objects.get(key=target))
                except models.NotificationChannel.DoesNotExist:
                    raise RegistrationError('Unknown source notification channel reference') from None
        exists = models.Source.objects.filter(key=key).exists()
        source = _save(models.Source, {'key': key}, values, update)
        if targets is not None and (update or not exists):
            source.notification_channels.set(resolved)
    for row in groups['sections']:
        values = dict(row)
        key = values.pop('key')
        source_key = values.pop('source', None)
        try:
            source = models.Source.objects.get(key=source_key)
        except models.Source.DoesNotExist:
            raise RegistrationError('Unknown section source reference') from None
        if not isinstance(values.get('config', {}), dict) or not values.get('name'):
            raise RegistrationError('Section name and object config are required')
        _save(models.Section, {'source': source, 'key': key}, values, update)
    for row in groups['checks']:
        values = dict(row)
        key = values.pop('key')
        source_key, section_key = values.pop('source', None), values.pop('section', None)
        try:
            section = models.Section.objects.get(source__key=source_key, key=section_key)
        except models.Section.DoesNotExist:
            raise RegistrationError('Unknown check section reference') from None
        if values.get('detector') not in detectors:
            raise RegistrationError('Unknown detector')
        _positive(values.get('interval_seconds', 300), 'Check interval')
        config = values.get('config', {})
        if not isinstance(config, dict):
            raise RegistrationError('Check config must be an object')
        if values['detector'] == 'source_contract':
            if config.get('kind', 'feed') not in ('page', 'feed', 'article'):
                raise RegistrationError('Unknown source observation kind')
            _contract_config(config, catalog)
        elif not isinstance(config, dict):
            raise RegistrationError('Check config must be an object')
        _save(models.DetectorCheck, {'section': section, 'key': key}, values, update)
    return {name: len(rows) for name, rows in groups.items()}


def bootstrap_defaults(update=False):
    """Seed Tencent defaults without recipients, models or implicit requests."""
    sections, checks = [], []
    for key, name, page, channel, feed in (
        ('news', '腾讯要闻', 'https://news.qq.com/', 'news_news_top', 'hot'),
        ('finance', '腾讯财经', 'https://news.qq.com/ch/finance/', 'news_news_finance', 'pc'),
        ('tech', '腾讯科技', 'https://news.qq.com/ch/tech/', 'news_news_tech', 'pc')):
        sections.append({'source': 'tencent', 'key': key, 'name': name, 'config': {
            'channel_key': key, 'channel_id': channel, 'page_url': page, 'feed_kind': feed}})
        contracts = {
            'page': [{'id': 'channel', 'kind': 'equals', 'path': 'metadata.channel_key', 'expected': key}],
            'feed': [{'id': 'items', 'kind': 'min_items', 'path': 'metadata.items', 'minimum': 1, 'code': 'EMPTY_RESULT'}],
            'article': [{'id': 'title', 'kind': 'html_selector', 'selector': 'h1#article-title'},
                        {'id': 'content', 'kind': 'html_selector', 'selector': '#article-content'}]}
        for kind, rules in contracts.items():
            checks.append({'source': 'tencent', 'section': key, 'key': kind, 'detector': 'source_contract',
                           'config': {'kind': kind, 'contracts': rules}, 'interval_seconds': 300})
    return register_configuration({'sources': [{'key': 'tencent', 'kind': 'web', 'adapter': 'tencent',
        'config': {'timeout': 10, 'trust_env': False}}], 'sections': sections, 'checks': checks}, update=update)


def collect_items(source_key, section_key, limit=12):
    """Collect at most 100 items and upsert payloads without models or events."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise RegistrationError('Collection limit must be between 1 and 100')
    try:
        source = models.Source.objects.get(key=source_key, enabled=True)
        section = source.sections.get(key=section_key, enabled=True)
    except (models.Source.DoesNotExist, models.Section.DoesNotExist):
        raise RegistrationError('Unknown or disabled source/section') from None
    items = create_source(source.adapter, source.config).collect(section.config, limit=limit)
    with transaction.atomic():
        for item in items[:limit]:
            models.CollectedItem.objects.update_or_create(source=source, external_id=item.external_id,
                                                          defaults={'payload': item.to_dict()})
    return [item.to_dict() for item in items[:limit]]
