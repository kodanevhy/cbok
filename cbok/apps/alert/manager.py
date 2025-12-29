from datetime import datetime
import json
import logging

from django import db
from g4f import client
from g4f import models as g4f_models

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
        LOG.info(f"Topic {topic.uuid} has been initialized")

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

        self._derive_article("conversation", "")

        for article in articles:
            if models.Answer.objects.filter(article=article).exists():
                continue

            self._derive_article(conversation, article)

    def _derive_article(self, conversation, article):
        active_questions = models.Question.objects.filter(
            topic=article.topic,
            status=models.Question._Status.ACTIVE,
        )

        messages = self.build_llm_context(article, active_questions)
        response = self.ask_llm(messages)

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

        if llm_result.get("answers") or llm_result.get("new_questions"):
            models.Topic.objects.filter(
                uuid=article.topic.uuid
            ).update(has_evolving_answer=True)

    def build_llm_context(self, article, active_questions):

        messages = []

        def _build_fact_messages():
            messages.append({
                "role": "system",
                "content": (
                    f"你正在持续跟踪话题：{article.topic.name}。"
                    "下面是你已经知道的事实，以及一篇新文章。"
                )
            })
            if not active_questions.exists():
                messages.append({
                        "role": "user",
                        "content": "已知事实: " + "暂无"
                    })
                return

            # data structure:
            # ["问题：xxx，已知事实：1.xxx;2.xxx", "问题：xxx，已知事实：1.xxx;2.xxx"]
            active_question_with_facts = []
            for q in active_questions:
                chunks = (
                    models.Answer.objects
                    .filter(question=q)
                    .order_by("created_at")
                    .values_list("content", flat=True)
                )
                if not chunks:
                    continue

                joined = [f"{i}.{c};" for i, c in enumerate(chunks)]
                active_question_with_facts.append(
                    f"问题：{q.summary}，已知事实：{joined}"
                )

            if active_question_with_facts:
                messages.append({
                    "role": "system",
                    "content": "你已知: " + "-".join(active_question_with_facts)
                })

        _build_fact_messages()

        messages.append({
            "role": "user",
            "content": (
                f"下面是新文章："
                f"标题：{article.title}"
                f"内容：{article.content}"
                "任务："
                "1. 如果新文章补充或修正了上述事实，请更新对应问题的答案，如果暂无已知事实，请不要填充 fact_answers 字段"
                "2. 如果新文章引出了新的重要问题，请提出并回答"
                "请返回可以直接被解析的 JSON 数据："
                "{"
                '"fact_answers": [{"question": "...", "answer": "..."}],'
                '"new_questions": [{"question": "...", "answer": "..."}]'
                "}"
            )
        })

        return messages

    def ask_llm(self, messages):
        resp = self.llm.chat.completions.create(
            model=g4f_models.deepseek_v3,
            messages=messages,
            web_search=False,
            response_format={"type": "json_object"}
        )
        return resp.choices[0].message.content

    def _apply_answers(self, article, questions, result):
        for item in result.get("answers", []):
            question = self._match_question(questions, item["question"])
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

    def _match_question(self, questions, text):
        for qst in questions:
            if qst.summary and qst.summary in text:
                return qst
        return None

    def _parse_publish_date(self, date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return None
