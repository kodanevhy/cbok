import json
import logging
import time

from django import db

from cbok.alert.crawler import google
from cbok.alert import llm
from cbok.alert import models
from cbok.alert import utils as alert_utils

LOG = logging.getLogger(__name__)


class AlertManager:
    def __init__(self):
        self.google_crawler = google.GoogleAlertCrawler()
        self.g4f = llm.G4F()

    def init_topic(self, topic: models.Topic):
        import pdb; pdb.set_trace()
        if topic.in_progress:
            return

        # TODO(koda): merge question in initial phrase
        # now in initial phrase, every question is fresh, even though the
        # answer derived is the same
        self.backfill(topic, recent=7)
        self.derive(topic, init_topic=True)

        topic.status = "initialized"
        topic.save(update_fields=["status"])
        LOG.info(f"Topic {topic.uuid} has been initialized")

    def backfill(self, topic: models.Topic, recent=1):
        LOG.info(f"Backing fill recent {recent} day(s)")

        history = self.google_crawler.analysis_history(topic.name, recent)

        exists_article_num = 0
        new_article_num = 0

        for h in history:
            url = h["url"]

            if models.Article.objects.filter(url=url).exists():
                exists_article_num += 1
                continue

            try:
                article_data = self.google_crawler.fetch_article(url)
            except Exception:
                # We can easily give up an unreachable article
                LOG.warning("Fetch article failed: %s", url)
                continue

            publish_date = alert_utils.parse_publish_date(
                article_data.get("date")
            )

            try:
                models.Article.objects.create(
                    topic=topic,
                    title=article_data.get("title", "")[:512],
                    url=url,
                    publish_date=publish_date,
                    content=article_data.get("content", ""),
                )

                new_article_num += 1
                time.sleep(1)
            except db.IntegrityError:
                pass
            except Exception:
                LOG.warning(f"{url} failed to crawl")

        LOG.info(f"Recent articles of {recent} day(s) are all backfilled, "
                 f"with {exists_article_num} exist and {new_article_num} "
                 f"insert")

    def derive(self, topic: models.Topic, init_topic=False):

        if not init_topic:
            models.Topic.objects.filter(
                uuid=article.topic.uuid
            ).update(status="evolving")

        conversation, _ = models.Conversation.objects.get_or_create(
            topic=topic
        )

        articles = (
            models.Article.objects
            .filter(topic=topic)
            .order_by("created_at")
        )

        for article in articles:
            if models.Answer.objects.filter(article=article).exists():
                continue

            self._derive_article(conversation, article)

            time.sleep(3)

    def _derive_article(self, conversation, article):
        active_questions = models.Question.objects.filter(
            topic=article.topic,
            status=models.Question._Status.ACTIVE,
        )

        messages = self.g4f.build_further_context(article, active_questions)

        # TODO(koda): g4f conversation length limit?
        LOG.debug(f"Article {article.uuid} is taking {len(active_questions)} "
                  f"question(s) to further derive {article.topic.name}")
        response = self.g4f.ask_llm(messages)

        try:
            llm_result = json.loads(response)
        except Exception:
            LOG.error("LLM invalid json: %s", response)
            # TODO: add notify to administrator? maybe we need to have an
            # optmization on llm input
            return

        with db.transaction.atomic():
            self._apply_answers(article, active_questions, llm_result)
            # TODO: now we only use chunked answer as context to compress input
            # for AI, next we maybe directly use history article content by g4f
            # conversation. But we must have an idea to limit the conversation
            # length
            # self._persist_messages(conversation, article, llm_result)

    def _apply_answers(self, article, questions, result):
        for item in result.get("answers", []):
            question = alert_utils.match_question(questions, item["question"])
            if not question:
                continue

            models.Answer.objects.get_or_create(
                question=question,
                article=article,
                defaults={"content": item["answer"]},
            )

        for item in result.get("new_questions", []):
            question, _ = models.Question.objects.get_or_create(
                topic=article.topic,
                summary=item["question"],
                defaults={
                    "status": models.Question._Status.ACTIVE,
                },
            )

            models.Answer.objects.get_or_create(
                question=question,
                article=article,
                defaults={"content": item["answer"]},
            )

    def _persist_messages(self, conversation, article, result):
        index = (
            models.Message.objects
            .filter(conversation=conversation)
            .count()
        )

        def save(role, content, ctype):
            nonlocal index
            index += 1
            models.Message.objects.create(
                conversation=conversation,
                index=index,
                role=role,
                content=content,
                content_type=ctype,
            )

        save(
            "user",
            f"处理文章：{article.title}",
            models.Message._ContentType.ARTICLE,
        )

        for item in result.get("answers", []):
            save(
                "system",
                f"补充问题：{item['question']}\n{item['answer']}",
                models.Message._ContentType.ANSWER,
            )

        for item in result.get("new_questions", []):
            save(
                "system",
                f"新问题：{item['question']}\n{item['answer']}",
                models.Message._ContentType.QUESTION,
            )
