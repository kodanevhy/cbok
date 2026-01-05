from g4f import client as g4f_client
from g4f import models as g4f_models
import openai

from cbok import settings


CONF = settings.CONF


class LLMClient(object):
    def __init__(self) -> None:
        self.client = None

    def ask(self, messages):
        pass


# Not stable
class G4F(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.client = g4f_client.Client()

    def ask(self, messages):
        resp = self.client.chat.completions.create(
            model=g4f_models.deepseek_v3,
            messages=messages,
            web_search=False,
            response_format={"type": "json_object"}
        )

        return resp.choices[0].message.content


class Deepseek(LLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.client = openai.OpenAI(
            api_key=CONF.get("llm_api_key", "deepseek"),
            base_url="https://api.deepseek.com")

    def ask(self, messages):
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            stream=False,
            response_format={"type": "json_object"}
        )

        return response.choices[0].message.content
