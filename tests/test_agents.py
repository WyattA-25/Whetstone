import importlib
import pkgutil

import pytest

import whetstone
from whetstone.agents import extract_tag, propose
from whetstone.llm import ChatResult


def test_every_module_imports():
    for m in pkgutil.walk_packages(whetstone.__path__, "whetstone."):
        importlib.import_module(m.name)


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def chat(self, messages, **kw):
        return ChatResult(self.text, 10, 10, 0.0, 0.0)


def _propose(text):
    return propose(FakeLLM(text), "mutate", description="d", objective="o",
                   parents=[{"id": "p", "prompt": "old", "score": "1"}], lessons=[], failures=[],
                   reference_prompt="ref")


@pytest.mark.parametrize("reply,expected", [
    ("<prompt>\nClassify the message carefully.\n</prompt>", "Classify the message carefully."),
    ("<Prompt>Classify the message carefully.</Prompt>", "Classify the message carefully."),
    ("<prompt>\nClassify the message carefully.\n</", "Classify the message carefully."),            # truncated
    ("```\nClassify the message carefully into exactly one label from the list; reply with the label only.\n```",
     "Classify the message carefully into exactly one label from the list; reply with the label only."),  # untagged
])
def test_propose_parses_reply_variants(reply, expected):
    assert _propose(reply).prompt == expected


def test_propose_strips_nested_wrapper_tags():
    reply = "<prompt>\n<prompt>\nClassify the message carefully.\n</prompt>\n</prompt>"
    assert _propose(reply).prompt == "Classify the message carefully."


def test_propose_rejects_empty_reply():
    with pytest.raises(ValueError):
        _propose("")


def test_extract_tag_none():
    assert extract_tag("no tags here", "prompt") is None
