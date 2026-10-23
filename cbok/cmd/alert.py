"""Thin, explicit CLI entry points for registered alert resources."""

import json
import math
from pathlib import Path
import time
import tomllib

from cbok.cmd import args, output
from cbok.cmd.base import BaseCommand


def _show(value):
    print(json.dumps(value, ensure_ascii=False, default=str, indent=2))


def _perform(label, action):
    try:
        result = action()
    except (ValueError, KeyError) as exc:
        # Domain validation messages are safe, but arbitrary adapter/backend
        # exceptions may contain credentials, URLs or request headers.
        from cbok.alert.llm import LLMConfigurationError
        from cbok.alert.monitoring.bootstrap import RegistrationError
        if isinstance(exc, (RegistrationError, LLMConfigurationError)):
            output.fail(f'{label}: {exc}')
        output.fail(f'{label} failed ({type(exc).__name__})')
    except Exception as exc:
        output.fail(f'{label} failed ({type(exc).__name__})')
    _show(result)
    return 0


def _registration_file(path):
    from cbok.alert.monitoring.bootstrap import RegistrationError
    from cbok.conf.files import resolve_cbok_conf_path
    from django.conf import settings
    file = Path(path).expanduser()
    if not file.is_absolute():
        conf = getattr(settings, 'CBOK_CONF_PATH', None)
        if conf is None:
            conf = resolve_cbok_conf_path(Path.cwd())
        file = Path(conf).parent / file
    if file.suffix.lower() == '.toml':
        with file.open('rb') as stream:
            data = tomllib.load(stream)
    elif file.suffix.lower() == '.json':
        with file.open(encoding='utf-8') as stream:
            data = json.load(stream)
    else:
        raise RegistrationError('Registration file must use .json or .toml')
    if not isinstance(data, dict):
        raise RegistrationError('Registration file must contain an object')
    if data.get('catalog'):
        catalog = Path(data['catalog']).expanduser()
        data['catalog'] = str(catalog if catalog.is_absolute() else file.parent / catalog)
    return data


class AlertCommands(BaseCommand):
    @args.action_description('Register Tencent defaults or import database configuration')
    @args.args('--file', help='JSON/TOML file; relative paths use CBOK_CONF directory')
    @args.args('--update', action='store_true', help='Explicitly replace imported fields on existing records')
    def register(self, file=None, update=False):
        """Register defaults or import records; preserve existing edits unless --update."""
        def action():
            from cbok.alert.monitoring.bootstrap import bootstrap_defaults, register_configuration
            if file:
                return register_configuration(_registration_file(file), update=update)
            return bootstrap_defaults(update=update)
        return _perform('Alert registration', action)

    @args.action_description('List database resources or installed extension names')
    @args.args('--kind', choices=['all', 'sources', 'sections', 'checks', 'anomaly_types', 'channels', 'models', 'registry'], default='all')
    def list(self, kind='all'):
        """Enumerate configuration without displaying credential-bearing config values."""
        def action():
            from django.conf import settings
            from cbok.alert import models
            from cbok.alert.llm import list_backends
            from cbok.alert.sources import list_sources
            from cbok.alert.monitoring.contracts import list_rules
            from cbok.alert.monitoring.plugins import discover_detectors
            from cbok.notification.channels import list_channels
            definitions = {
                'sources': (models.Source, ('id', 'key', 'kind', 'adapter', 'enabled')),
                'sections': (models.Section, ('id', 'source__key', 'key', 'name', 'enabled')),
                'checks': (models.DetectorCheck, ('id', 'section__source__key', 'section__key', 'key', 'detector', 'interval_seconds', 'enabled', 'next_run_at')),
                'anomaly_types': (models.AnomalyType, ('code', 'label', 'scope', 'indeterminate', 'policy')),
                'channels': (models.NotificationChannel, ('id', 'key', 'kind', 'enabled')),
                'models': (models.ModelProfile, ('id', 'key', 'backend', 'model', 'enabled')),
            }
            if kind not in (*definitions, 'all', 'registry'):
                raise ValueError('Unknown list kind')
            result = {name: list(model.objects.order_by('pk').values(*fields))
                      for name, (model, fields) in definitions.items() if kind in ('all', name)}
            if kind in ('all', 'registry'):
                result['registry'] = {
                    'sources': [name for name, _ in list_sources()],
                    'models': list(list_backends()),
                    'channels': [name for name, _ in list_channels()],
                    'detectors': sorted(discover_detectors(getattr(settings, 'ALERT_DETECTOR_PATHS', None))),
                    'rules': [name for name, _ in list_rules()],
                }
            return result
        return _perform('Alert listing', action)

    @args.action_description('Collect bounded items without model analysis or notifications')
    @args.args('--source', required=True, help='Registered source key')
    @args.args('--section', required=True, help='Section key within the source')
    @args.args('--limit', type=int, default=12, help='Maximum items, between 1 and 100')
    def collect(self, source, section, limit=12):
        """Collect and upsert source items without invoking models or notifications."""
        def action():
            from cbok.alert.monitoring.bootstrap import collect_items
            return collect_items(source, section, limit)
        return _perform('Alert collection', action)

    @args.action_description('Run one check; default dry run records only its CheckRun')
    @args.args('--id', required=True, type=int, help='Database DetectorCheck ID from alert list')
    @args.args('--apply', action='store_true', help='Apply this result to incidents and scheduling')
    @args.args('--notify', action='store_true', help='Enqueue and send notifications; requires --apply')
    def check(self, id, apply=False, notify=False):
        """Run a check; --notify requires --apply and enables notification delivery."""
        if type(id) is not int or id < 1:
            output.fail('Check ID must be a positive integer')
        if notify and not apply:
            output.fail('--notify requires --apply')
        def action():
            from cbok.alert.monitoring.service import run_check, deliver_pending
            result = run_check(id, apply=apply, notify=notify)
            if notify:
                return {'check': result, 'delivery': deliver_pending()}
            return result
        return _perform('Alert check', action)

    @args.action_description('Explicit worker: run due checks and deliver pending notifications')
    @args.args('--once', action='store_true', help='Run one bounded scan and exit')
    @args.args('--interval', type=float, default=60, help='Seconds between sequential scans')
    def run(self, once=False, interval=60):
        """Run a sequential worker explicitly; --once performs one scan only."""
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            output.fail('Worker interval must be a finite positive number')
        def action():
            from cbok.alert.monitoring.service import run_due_checks, deliver_pending
            return {'checks': run_due_checks(), 'delivery': deliver_pending()}
        try:
            while True:
                _perform('Alert worker', action)
                if once:
                    return 0
                time.sleep(interval)
        except KeyboardInterrupt:
            return 0

    @args.action_description('Explicitly invoke one enabled database model profile')
    @args.args('--profile', required=True, help='Database model profile key')
    @args.args('--prompt', required=True, help='User prompt sent to the selected model')
    def model_check(self, profile, prompt):
        """Invoke only the selected backend; this command can incur model charges."""
        def action():
            from cbok.alert.model_profiles import configured_model_client
            return {'response': configured_model_client(profile).ask([{'role': 'user', 'content': prompt}])}
        return _perform('Model check', action)
