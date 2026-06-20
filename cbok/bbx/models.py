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


class ZsvWorktreeContainerState(models.Model):
    worktree_key = models.CharField(max_length=64, unique=True)
    zstack_root = models.CharField(max_length=512)
    premium_root = models.CharField(max_length=512, blank=True, default="")
    docker_host = models.CharField(max_length=255, blank=True, default="")
    image = models.CharField(max_length=255)
    platform = models.CharField(max_length=64, blank=True, default="")
    workdir = models.CharField(max_length=255, default="/work")
    container_name = models.CharField(max_length=128, unique=True)
    m2_volume = models.CharField(max_length=128, blank=True, default="")
    zstack_head = models.CharField(max_length=64, blank=True, default="")
    premium_head = models.CharField(max_length=64, blank=True, default="")
    full_compile_done = models.BooleanField(default=False)
    full_compile_started_at = models.DateTimeField(blank=True, null=True)
    full_compile_finished_at = models.DateTimeField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, default="")

    def __str__(self):
        status = "compiled" if self.full_compile_done else "pending"
        return f"{self.container_name}: {status}"
