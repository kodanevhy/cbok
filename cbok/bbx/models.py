from django.db import models


class ChromePluginAutoLoginHostInfo(models.Model):
    ip_address = models.GenericIPAddressField(protocol='IPv4', blank=False, null=False)
    username = models.CharField(max_length=64)
    password = models.CharField(max_length=128)

    def __str__(self):
        return f"{self.ip_address} / {self.password}"


class ZSphereUpgradeState(models.Model):
    name = models.CharField(max_length=64, unique=True)
    iso_url = models.URLField(max_length=512)
    latest_iso_name = models.CharField(max_length=255, blank=True, default="")
    latest_iso_modified_at = models.DateTimeField(blank=True, null=True)
    last_checked_at = models.DateTimeField(blank=True, null=True)
    last_upgraded_iso_name = models.CharField(max_length=255, blank=True, default="")
    last_upgraded_iso_modified_at = models.DateTimeField(blank=True, null=True)
    last_upgraded_at = models.DateTimeField(blank=True, null=True)
    nodes = models.TextField(blank=True, default="")

    def __str__(self):
        return f"{self.name}: {self.last_upgraded_iso_name or 'not upgraded'}"
