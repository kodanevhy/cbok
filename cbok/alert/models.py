import uuid

from django.db import models


class Topic(models.Model):

    class _Status(models.TextChoices):
        CREATED = "created"
        INITIALIZED = "initialized"
        EVOLVING = "evolving"

    uuid = models.UUIDField(primary_key=True,
                            default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=20,
        choices=_Status.choices,
        default=_Status.CREATED,
    )

    def __str__(self):
        return f"{self.uuid}"

    @property
    def in_progress(self):
        return self.status in (self._Status.INITIALIZED.value,
                               self._Status.EVOLVING.value)


class Article(models.Model):
    uuid = models.UUIDField(primary_key=True,
                            default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    title = models.CharField(max_length=512)
    url = models.URLField(
        max_length=2048,
        unique=True,
        db_index=True,
        blank=False,
        null=False,
    )
    publish_date = models.DateField(null=True, blank=True)
    content = models.TextField()

    def __str__(self):
        return f"{self.uuid}"


class Question(models.Model):
    class _Status(models.TextChoices):
        ACTIVE = 'active'
        COMPLETE = 'complete'
        SUSPEND = 'suspend'
        DELETED = 'deleted'

    uuid = models.UUIDField(primary_key=True,
                            default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=10,
        choices=_Status.choices,
        default=_Status.SUSPEND,
    )
    summary = models.TextField()

    def __str__(self):
        return f"{self.uuid}"


class Answer(models.Model):
    uuid = models.UUIDField(primary_key=True,
                            default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    content = models.TextField()

    class Meta:
        unique_together = ('question', 'article')

    def __str__(self):
        return f"{self.uuid}"


class Conversation(models.Model):
    uuid = models.UUIDField(primary_key=True,
                            default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.uuid}"


class Message(models.Model):
    class _Role(models.TextChoices):
        USER = 'user'
        SYSTEM = 'system'

    class _ContentType(models.TextChoices):
        ARTICLE = 'article'
        QUESTION = 'question'
        ANSWER = 'answer'

    uuid = models.UUIDField(primary_key=True,
                            default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    index = models.IntegerField(null=False)
    role = models.CharField(
        max_length=20,
        choices=_Role.choices,
        null=False,
        blank=False,
    )

    content = models.TextField()
    content_type = models.CharField(
        max_length=20,
        choices=_ContentType.choices,
        null=False,
        blank=False,
    )


class NotificationChannel(models.Model):
    key = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=120)
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)


class Source(models.Model):
    key = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=120)
    adapter = models.CharField(max_length=120)
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    notification_channels = models.ManyToManyField(NotificationChannel, blank=True)


class Section(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='sections')
    key = models.CharField(max_length=120)
    name = models.CharField(max_length=255)
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'key'], name='alert_section_source_key')]


class DetectorCheck(models.Model):
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='checks')
    key = models.CharField(max_length=120)
    detector = models.CharField(max_length=120)
    config = models.JSONField(default=dict, blank=True)
    interval_seconds = models.PositiveIntegerField(default=300)
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lease_token = models.CharField(max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True, blank=True)
    last_result = models.JSONField(default=dict, blank=True)
    revision = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['section', 'key'], name='alert_check_section_key'),
            models.CheckConstraint(condition=models.Q(interval_seconds__gt=0), name='alert_positive_interval'),
        ]


class AnomalyType(models.Model):
    code = models.CharField(max_length=120, unique=True)
    label = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    scope = models.CharField(max_length=120, default='contract')
    indeterminate = models.BooleanField(default=False)
    policy = models.JSONField(default=dict, blank=True)


class CheckRun(models.Model):
    detector_check = models.ForeignKey(DetectorCheck, db_column='check_id', on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=20)
    result = models.JSONField(default=dict)
    revision = models.CharField(max_length=64)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)


class Incident(models.Model):
    detector_check = models.ForeignKey(DetectorCheck, db_column='check_id', on_delete=models.CASCADE, related_name='incidents')
    anomaly_type = models.ForeignKey(AnomalyType, on_delete=models.PROTECT)
    fingerprint = models.CharField(max_length=64)
    revision = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default='active')
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    occurrences = models.PositiveIntegerField(default=1)
    consecutive_count = models.PositiveIntegerField(default=1)
    # Authorization captured at recovery; a later send acknowledgment cannot
    # turn an explicit apply-without-notify into a notification.
    recovery_notify = models.BooleanField(default=False)
    details = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['detector_check', 'fingerprint', 'revision'], condition=models.Q(status='active'),
            name='alert_active_incident_unique',
        )]


class NotificationDelivery(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='deliveries')
    channel = models.ForeignKey(NotificationChannel, on_delete=models.PROTECT)
    event_kind = models.CharField(max_length=20)
    status = models.CharField(max_length=20, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    last_error = models.CharField(max_length=1000, blank=True, default='')
    lease_token = models.CharField(max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['incident', 'channel', 'event_kind'], name='alert_delivery_event_unique',
        )]


class CollectedItem(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='items')
    external_id = models.CharField(max_length=512)
    payload = models.JSONField(default=dict)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'external_id'], name='alert_item_source_external')]


class ModelProfile(models.Model):
    key = models.CharField(max_length=120, unique=True)
    backend = models.CharField(max_length=120)
    model = models.CharField(max_length=255)
    provider = models.CharField(max_length=255, blank=True, default='')
    base_url = models.CharField(max_length=2048, blank=True, default='')
    api_key_env = models.CharField(max_length=255, blank=True, default='')
    timeout = models.PositiveIntegerField(default=30)
    options = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
