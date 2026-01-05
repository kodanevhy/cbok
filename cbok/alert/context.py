from cbok.alert import models


class DeriveContext(object):

    def __init__(self) -> None:
        pass

    def build_init_topic_context(self, article):
        messages = []

        message = {
            "role": "user",
            "content": (
                f"下面是一篇文章："
                f"标题：{article.title}"
                f"内容：{article.content}"
                "任务："
                "你觉得该文章有哪些值得人们感兴趣的问题，请提出，并基于该文章的内容对问题作出回答"
                "请返回可以直接被解析的 JSON 数据："
                "{"
                '"new_questions": [{"question": "...", "answer": "..."}]'
                "}"
            )
        }

        messages.append(message)
        return messages

    def build_further_context(self, article, active_questions):

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
