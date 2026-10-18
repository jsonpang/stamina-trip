"""OpenAI-compatible chat client. Swapping providers is an env change, not a code change."""
from openai import OpenAI

from .config import llm_settings


def client_and_model() -> tuple[OpenAI, str]:
    base_url, model, key = llm_settings()
    return OpenAI(base_url=base_url, api_key=key, timeout=120), model
