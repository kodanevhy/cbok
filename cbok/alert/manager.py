import json
import logging
import time

from django import db

from cbok.alert import context
from cbok.alert.crawler import google
from cbok.alert import llm
from cbok.alert import models
from cbok.alert import utils as alert_utils

LOG = logging.getLogger(__name__)


class AlertManager:
    def __init__(self):
        self.google_crawler = google.GoogleAlertCrawler()
        self.llm_client = llm.Deepseek()
        self.context = context.DeriveContext()

    def init_topic(self, topic: models.Topic):
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

    def derive(self, topic: models.Topic, init_topic=False):

        if not init_topic:
            models.Topic.objects.filter(
                uuid=article.topic.uuid
            ).update(status="evolving")

        articles = (
            models.Article.objects
            .filter(topic=topic)
            .order_by("created_at")
        )

        for article in articles:
            # every article will only be derived one time, use derived
            # answer already written to database to join next derive
            if models.Answer.objects.filter(article=article).exists():
                continue

            if init_topic:
                self._init_topic_derive_article(article)
            else:
                self._further_derive_article(article)

            time.sleep(3)

        LOG.info(f"Topic {topic.uuid} has been derived intermediately")

    def _init_topic_derive_article(self, article):
        message = self.context.build_init_topic_context(article)
        response = self.llm_client.ask(message)

        try:
            llm_result = json.loads(response)
        except Exception:
            LOG.error("LLM invalid json: %s", response)
            return

        self._apply_answers(article, llm_result)

        LOG.info(f"Article {article.uuid} is initial derived")

    def _further_derive_article(self, article):
        active_questions = models.Question.objects.filter(
            topic=article.topic,
            status=models.Question._Status.ACTIVE,
        )

        messages = self.context.build_further_context(
            article, active_questions)

        # TODO(koda): llm conversation length limit?
        LOG.info(f"Article {article.uuid} is taking {len(active_questions)} "
                  f"question(s) to further derive {article.topic.uuid}")
        response = self.llm_client.ask(messages)

        try:
            llm_result = json.loads(response)
        except Exception:
            LOG.error("LLM invalid json: %s", response)
            # TODO: add notify to administrator? maybe we need to have an
            # optmization on llm request
            return

        with db.transaction.atomic():
            self._apply_answers(article, active_questions, llm_result)

    def _apply_answers(self, article, result, active_questions=None):
        for item in result.get("answers", []):
            question = alert_utils.match_question(
                active_questions, item["question"])
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

    def backfill(self, topic: models.Topic, recent=1):
        LOG.info(f"Backing fill recent {recent} day(s)")

        history = self.google_crawler.analysis_history(topic.name, recent)

        exists_article_num = 0
        new_article_num = 0

        for h in history:
            url = h["url"]

            if self.google_crawler.dedup(topic, url):
                exists_article_num += 1
                continue

            try:
                # TODO(koda): maybe we do not need to proxy to Chinese
                # website, so that reduce usage consumption
                article_data = self.google_crawler.fetch_article(url)

                if not article_data["content"]:
                    continue
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
