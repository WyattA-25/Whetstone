"""Settings loaded from .env. Secrets are read here and nowhere else."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


@dataclass(frozen=True)
class EndpointConfig:
    """One OpenAI-compatible endpoint plus its (estimated) prices in USD per 1M tokens."""
    account: str          # "optimizer" (our Luminal account) or "scoring" (customer's key)
    api_key: str
    base_url: str
    model: str
    price_in_per_m: float
    price_out_per_m: float

    def __repr__(self) -> str:  # never print the key
        return f"EndpointConfig(account={self.account!r}, base_url={self.base_url!r}, model={self.model!r})"


def optimizer_endpoint() -> EndpointConfig:
    return EndpointConfig(
        account="optimizer",
        api_key=os.environ["LUMINAL_API_KEY"],
        base_url=os.environ["LUMINAL_BASE_URL"],
        model=os.environ["LUMINAL_MODEL"],
        price_in_per_m=_f("LUMINAL_PRICE_IN_PER_M", 0.10),
        price_out_per_m=_f("LUMINAL_PRICE_OUT_PER_M", 0.40),
    )


def scoring_endpoint() -> EndpointConfig:
    """The customer's key. For the hackathon demo, falls back to our Luminal key."""
    return EndpointConfig(
        account="scoring",
        api_key=os.getenv("SCORING_API_KEY") or os.environ["LUMINAL_API_KEY"],
        base_url=os.getenv("SCORING_BASE_URL") or os.environ["LUMINAL_BASE_URL"],
        model=os.getenv("SCORING_MODEL") or os.environ["LUMINAL_MODEL"],
        price_in_per_m=_f("SCORING_PRICE_IN_PER_M", _f("LUMINAL_PRICE_IN_PER_M", 0.10)),
        price_out_per_m=_f("SCORING_PRICE_OUT_PER_M", _f("LUMINAL_PRICE_OUT_PER_M", 0.40)),
    )


MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY") or 8)
OPTIMIZER_MAX_USD_PER_RUN = _f("OPTIMIZER_MAX_USD_PER_RUN", 2.00)
