from django.db import models


class ChromePluginAutoLoginHostInfo(models.Model):
    ip_address = models.GenericIPAddressField(protocol='IPv4', blank=False, null=False)
    username = models.CharField(max_length=64)
    password = models.CharField(max_length=128)

    def __str__(self):
        return f"{self.ip_address} / {self.password}"
