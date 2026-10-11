"""OpenAI-compatible chat client with concurrency limit, retries, and cost/budget tracking."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from .config import MAX_CONCURRENCY, EndpointConfig

RETRYABLE = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)


class BudgetExceeded(Exception):
    """Raised before a call when an account's spend limit is reached. Runs catch this and stop gracefully."""


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0   # includes hidden reasoning tokens
    usd: float = 0.0
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens, "usd": round(self.usd, 6),
                "seconds": round(self.seconds, 2)}


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    usd: float
    seconds: float


@dataclass
class LLMClient:
    endpoint: EndpointConfig
    max_usd: float | None = None          # hard budget for this account in this run
    temperature: float = 0.7
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        self._client = OpenAI(api_key=self.endpoint.api_key, base_url=self.endpoint.base_url,
                              timeout=120, max_retries=0)
        self._sem = threading.Semaphore(MAX_CONCURRENCY)
        self._lock = threading.Lock()

    def remaining_usd(self) -> float | None:
        return None if self.max_usd is None else self.max_usd - self.usage.usd

    def chat(self, messages: list[dict], *, temperature: float | None = None,
             max_tokens: int = 2048) -> ChatResult:
        if self.max_usd is not None and self.usage.usd >= self.max_usd:
            raise BudgetExceeded(f"{self.endpoint.account} budget ${self.max_usd:.2f} reached")
        with self._sem:
            t = time.time()
            resp = self._create(messages, self.temperature if temperature is None else temperature, max_tokens)
            dt = time.time() - t
        u = resp.usage
        pt, ct = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        usd = pt / 1e6 * self.endpoint.price_in_per_m + ct / 1e6 * self.endpoint.price_out_per_m
        with self._lock:
            self.usage.calls += 1
            self.usage.prompt_tokens += pt
            self.usage.completion_tokens += ct
            self.usage.usd += usd
            self.usage.seconds += dt
        return ChatResult(resp.choices[0].message.content or "", pt, ct, usd, dt)

    @retry(retry=retry_if_exception_type(RETRYABLE), wait=wait_random_exponential(min=1, max=30),
           stop=stop_after_attempt(8), reraise=True)
    def _create(self, messages, temperature, max_tokens):
        return self._client.chat.completions.create(
            model=self.endpoint.model, messages=messages,
            temperature=temperature, max_tokens=max_tokens)
