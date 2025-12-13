from django.db import models


class Topic(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=255, unique=True)

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
    # topic =
    # status: active, complete, suspend, deleted
    # 如果有新文章，遍历所有topic（可能后期会检查article直接和topic的相关性），还在active的问题，带问题去问AI这个article，去做document answer
    pass


class EvolvingAnswerForActiveQuestion(models.Model):
    # question = id
    # answer_item1 =
    # answer_item2 =
    pass


class Conversation(models.Model):
    # topic =
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    index = models.IntegerField(help_text="对话中的序号")
    role = models.CharField(
        max_length=20,
        choices=[("user", "user"), ("assistant", "assistant"), ("system", "system")],
    )

    content = models.TextField(help_text="消息内容")
    content_type = models.CharField(
        max_length=20,
        choices=[
            ("article", "Article"),
            ("question", "Question"),
            ("article_question", "Article + Question"),
            ("answer", "Answer"),
        ]
    )

    created_at = models.DateTimeField(auto_now_add=True)
