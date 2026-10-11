"""Smoke test: `python -m whetstone.check_llm` makes one tiny call on each account."""
from .config import optimizer_endpoint, scoring_endpoint
from .llm import LLMClient


def main() -> None:
    for ep in (optimizer_endpoint(), scoring_endpoint()):
        llm = LLMClient(ep, temperature=0)
        r = llm.chat([{"role": "user", "content": "Reply with exactly: pong"}], max_tokens=200)
        print(f"[{ep.account}] {ep.model} -> {r.text.strip()!r} "
              f"({r.prompt_tokens}+{r.completion_tokens} tokens, ${r.usd:.6f}, {r.seconds:.2f}s)")


if __name__ == "__main__":
    main()
