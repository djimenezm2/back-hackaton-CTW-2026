"""
Where the chat model comes from.

One factory, so every agent shares the same model, the same timeout and the same failure
message. Configuration is read from the environment rather than passed around, because
which model is in use is an operational fact and not an argument any caller should be able
to get wrong.
"""

import os

from langchain_core.language_models import BaseChatModel

DEFAULT_MODEL = "gpt-4o"
REQUEST_TIMEOUT_SECONDS = 60


class LLMNotConfigured(RuntimeError):
    """Credentials are missing. Raised at build time, never mid-conversation."""


def build_chat_model(temperature: float = 0.2) -> BaseChatModel:
    """
    Build the chat model every agent runs on.

    Args:
        temperature (float): Low by default. These agents choose between concrete options
            and write short factual messages; variety is not a feature here.

    Returns:
        BaseChatModel: An OpenAI chat model, per `OPENAI_MODEL`.

    Raises:
        LLMNotConfigured: When the API key is missing.

    Note:
        `OPENAI_BASE_URL` is honoured when set, so a gateway or an OpenAI-compatible
        provider needs no code change. The model must support tool calling: agents here do
        nothing but call tools, and one that cannot will fail at the first turn rather than
        degrade.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMNotConfigured("missing environment variable: OPENAI_API_KEY")

    from langchain_openai import ChatOpenAI

    options: dict = {
        "model": os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        "api_key": api_key,
        "temperature": temperature,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "max_retries": 2,
    }

    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        options["base_url"] = base_url

    return ChatOpenAI(**options)
