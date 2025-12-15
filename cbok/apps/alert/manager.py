from datetime import datetime
import json
import logging

from django import db
from g4f import client

from cbok.apps.alert.crawler import google
from cbok.apps.alert import models


LOG = logging.getLogger(__name__)


class AlertManager:
    def __init__(self):
        self.google_crawler = google.GoogleAlertCrawler()
        self.llm = client.Client()

    def init_topic(self, topic: models.Topic):
        if topic.initialized:
            return

        self.backfill(topic, recent=7)

        self.derive(topic)

        topic.initialized = True
        topic.save(update_fields=["initialized"])
        LOG.info(f"Topic {topic.name} has been initialized")

    def backfill(self, topic: models.Topic, recent=1):
        date = recent
        history = self.google_crawler.analysis_history(topic.name, date)

        for h in history:
            url = h["url"]

            if models.Article.objects.filter(url=url).exists():
                LOG.debug(f"Article exists: {url}")
                continue

            try:
                article_data = self.google_crawler.fetch_article(url)
            except Exception:
                # We can easily give up an unreachable article
                LOG.warning("Fetch article failed: %s", url)
                continue

            publish_date = self._parse_publish_date(
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
                LOG.info(f"Article crawled for {topic.name}: {url}")
            except db.IntegrityError:
                pass

    def derive(self, topic: models.Topic):

        conversation, _ = models.Conversation.objects.get_or_create(
            topic=topic
        )

        articles = (
            models.Article.objects
            .filter(topic=topic)
            .order_by("created_at")
        )

        for article in articles:
            if models.AnswerChunk.objects.filter(article=article).exists():
                continue

            self._derive_article(conversation, article)

    def _derive_article(self, conversation, article):
        active_questions = models.Question.objects.filter(
            topic=article.topic,
            status=models.Question._Status.ACTIVE,
        )

        # TODO: now we only use chunked answer as context to compress input
        # for AI, next we maybe directly use history article content by g4f
        # conversation. But we must have an idea to limit the conversation
        # length
        messages = self.build_llm_context_by_answer_chunk(
            article, active_questions)
        response = self.ask_llm(messages)

        try:
            llm_result = json.loads(response)
        except Exception:
            LOG.error("LLM invalid json: %s", response)
            return

        with db.transaction.atomic():
            self._apply_answers(article, active_questions, llm_result)
            self._persist_messages(conversation, article, llm_result)

        if llm_result.get("answers") or llm_result.get("new_questions"):
            models.Topic.objects.filter(
                id=article.topic.id
            ).update(has_evolving_answer=True)

    def build_llm_context_by_answer_chunk(self, article, active_questions):
        messages = []

        messages.append({
            "role": "system",
            "content": (
                f"你正在持续跟踪话题「{article.topic.name}」。\n"
                "下面是你已经知道的事实，以及一篇新文章。"
            )
        })

        if active_questions.exists():
            facts = []
            for q in active_questions:
                chunks = (
                    models.AnswerChunk.objects
                    .filter(question=q)
                    .order_by("created_at")
                    .values_list("content", flat=True)
                )
                if not chunks:
                    continue

                joined = "\n".join(f"- {c}" for c in chunks)
                facts.append(
                    f"问题：{q.summary}\n已知事实：\n{joined}"
                )

            if facts:
                messages.append({
                    "role": "system",
                    "content": "【已知事实】\n" + "\n\n".join(facts)
                })

        messages.append({
            "role": "user",
            "content": (
                f"【新文章】\n"
                f"标题：{article.title}\n\n"
                f"{article.content}\n\n"
                "任务：\n"
                "1. 如果新文章补充或修正了上述事实，请更新对应问题的答案\n"
                "2. 如果新文章引出了新的重要问题，请提出并回答\n\n"
                "请返回 JSON：\n"
                "{\n"
                '  "answers": [{"question": "...", "answer": "..."}],\n'
                '  "new_questions": [{"question": "...", "answer": "..."}]\n'
                "}"
            )
        })

        return messages

    def ask_llm(self, messages):
        resp = self.llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            web_search=False,
        )
        return resp.choices[0].message.content

    def _apply_answers(self, article, questions, result):
        for item in result.get("answers", []):
            q = self._match_question(questions, item["question"])
            if not q:
                continue

            models.AnswerChunk.objects.get_or_create(
                question=q,
                article=article,
                defaults={"content": item["answer"]},
            )

        for item in result.get("new_questions", []):
            q, _ = models.Question.objects.get_or_create(
                topic=article.topic,
                summary=item["question"],
                defaults={
                    "status": models.Question._Status.ACTIVE,
                },
            )

            models.AnswerChunk.objects.get_or_create(
                question=q,
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

    def _match_question(self, questions, text):
        for q in questions:
            if q.summary and q.summary in text:
                return q
        return None

    def _parse_publish_date(self, date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return None
