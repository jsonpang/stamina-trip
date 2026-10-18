"""Compatibility entry point; planning uses deterministic Python."""
from .cli import create_plan


def ask(question: str) -> dict:
    return create_plan(question)
