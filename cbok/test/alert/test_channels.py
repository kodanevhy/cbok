"""Notification dispatch contracts; all email uses Django's local memory backend."""
import importlib
import os
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cbok.test.alert.settings")

import django
from django.core import mail
from django.test import SimpleTestCase, override_settings

django.setup()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_FROM="monitor@example.com",
)
class NotificationChannelTests(SimpleTestCase):
    def setUp(self):
        self.channels = importlib.import_module("cbok.notification.channels")
        mail.get_connection()
        mail.outbox.clear()
        self.message = self.channels.NotificationMessage(
            subject="Feed schema changed", body="Missing title on item 7",
            metadata={"check": "finance-feed"},
        )

    def test_registered_email_delivers_exact_plain_text_message_and_recipients(self):
        result = self.channels.send_notification(
            "email", {"to": ["admin@example.com", "oncall@example.org"]}, self.message,
        )
        self.assertIsNone(result)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.subject, "Feed schema changed")
        self.assertEqual(sent.body, "Missing title on item 7")
        self.assertEqual(sent.to, ["admin@example.com", "oncall@example.org"])
        self.assertEqual(sent.from_email, "monitor@example.com")
        self.assertEqual(sent.alternatives, [])

    def test_custom_channel_factory_receives_configuration_and_delivers_message(self):
        delivered = []

        class RecordingChannel:
            def __init__(self, config):
                self.destination = config["destination"]

            def send(self, message):
                delivered.append((self.destination, message.subject, message.body))

        kind = "recording-" + uuid4().hex
        self.channels.register_channel(kind, RecordingChannel)
        self.channels.send_notification(kind, {"destination": "operations"}, self.message)
        self.assertEqual(delivered, [("operations", "Feed schema changed", "Missing title on item 7")])
        self.assertIn(kind, dict(self.channels.list_channels()))
        self.assertIn("email", dict(self.channels.list_channels()))

    def test_duplicate_registration_does_not_replace_channel(self):
        kind = "duplicate-" + uuid4().hex
        self.channels.register_channel(kind, lambda config: object())
        with self.assertRaises(ValueError):
            self.channels.register_channel(kind, lambda config: object())

    def test_unknown_channel_raises_without_sending_email(self):
        with self.assertRaises((KeyError, ValueError)):
            self.channels.send_notification("missing-channel", {}, self.message)
        self.assertEqual(mail.outbox, [])

    def test_invalid_recipient_config_is_rejected_before_delivery(self):
        configs = [
            {}, {"to": []}, {"to": "admin@example.com"},
            {"to": ("admin@example.com",)}, {"to": [None]},
            {"to": ["not-an-email"]}, {"to": ["admin@example.com\r\nBcc: bad@example.com"]},
            {"to": ["admin@example.com", "invalid"]},
        ]
        for config in configs:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    self.channels.send_notification("email", config, self.message)
        self.assertEqual(mail.outbox, [])

    def test_transport_failure_propagates_without_false_success(self):
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=OSError("transport unavailable")):
            with self.assertRaisesRegex(OSError, "transport unavailable"):
                self.channels.send_notification("email", {"to": ["admin@example.com"]}, self.message)
        self.assertEqual(mail.outbox, [])

    def test_zero_delivered_messages_raises_instead_of_reporting_success(self):
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "deliver"):
                self.channels.send_notification("email", {"to": ["admin@example.com"]}, self.message)
        self.assertEqual(mail.outbox, [])

    def test_custom_channel_failure_propagates(self):
        class BrokenChannel:
            def __init__(self, config):
                pass

            def send(self, message):
                raise RuntimeError("channel unavailable")

        kind = "broken-" + uuid4().hex
        self.channels.register_channel(kind, BrokenChannel)
        with self.assertRaisesRegex(RuntimeError, "channel unavailable"):
            self.channels.send_notification(kind, {}, self.message)

    def test_channel_nonconfirmation_is_not_reported_as_success(self):
        class UnconfirmedChannel:
            def __init__(self, config):
                pass

            def send(self, message):
                return False

        kind = "unconfirmed-" + uuid4().hex
        self.channels.register_channel(kind, UnconfirmedChannel)
        with self.assertRaisesRegex(RuntimeError, "deliver"):
            self.channels.send_notification(kind, {}, self.message)

    def test_noncallable_channel_factory_is_rejected_at_registration(self):
        with self.assertRaises(ValueError):
            self.channels.register_channel("invalid-" + uuid4().hex, None)

    def test_message_metadata_is_not_shared_between_messages_or_caller(self):
        metadata = {"evidence": {"item": 7}}
        first = self.channels.NotificationMessage("First", "body", metadata)
        metadata["evidence"]["item"] = 8
        second = self.channels.NotificationMessage("Second", "body")
        second.metadata["new"] = True
        third = self.channels.NotificationMessage("Third", "body")
        self.assertEqual(first.metadata, {"evidence": {"item": 7}})
        self.assertEqual(third.metadata, {})

    def test_import_does_not_require_django_settings_or_send_email(self):
        env = dict(os.environ)
        env.pop("DJANGO_SETTINGS_MODULE", None)
        env.pop("CBOK_CONF", None)
        script = """
from unittest.mock import patch
from django.conf import settings
with patch('django.core.mail.EmailMultiAlternatives.send', side_effect=AssertionError('sent during import')):
    import cbok.notification.channels
assert not settings.configured
"""
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
