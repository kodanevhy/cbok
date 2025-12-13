from django.db import models


class Topic(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=255, unique=True)
    first_crawled = models.BooleanField(default=False)
    has_evolving_answer = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Article(models.Model):
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
        return f"{self.topic: self.title}"


class Question(models.Model):
    class _Status(models.TextChoices):
        ACTIVE = 'active'
        COMPLETE = 'complete'
        SUSPEND = 'suspend'
        DELETED = 'deleted'
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=10,
        choices=_Status.choices,
        default=_Status.SUSPEND,
    )


class EvolvingAnswerForActiveQuestion(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer = models.TextField()


class Conversation(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    class _Role(models.TextChoices):
        USER = 'user'
        ASSISTANT = 'assistant'
        SYSTEM = 'system'

    class _ContentType(models.TextChoices):
        ARTICLE = 'article'
        QUESTION = 'question'
        ARTICLE_QUESTION = 'article_question'
        ANSWER = 'answer'

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
