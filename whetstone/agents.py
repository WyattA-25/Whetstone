"""The optimizer's agents. They run on OUR Luminal account and know nothing about any specific task
beyond the adapter's plain-language description, the prompts, and failure notes."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import LLMClient

STRATEGIES = ("mutate", "crossover", "fresh")

SYSTEM = """You are an expert prompt engineer on a team that iteratively improves a production prompt.

TASK THE PROMPT IS FOR:
{description}

OPTIMIZATION OBJECTIVE: {objective}

Rules:
- Keep every hard requirement of the task (required output format, valid labels/values, etc.).
- Never add instructions that depend on specific test examples; generalize from failures.
- Prefer clear, compact prompts. Length costs tokens on every call.
- Return ONLY the new prompt, wrapped in <prompt></prompt> tags."""


def _lessons_block(lessons: list[str]) -> str:
    return "\n".join(f"- {l}" for l in lessons) if lessons else "(none yet)"


def _failures_block(failures: list[str]) -> str:
    return "\n\n".join(f"[{i + 1}]\n{f}" for i, f in enumerate(failures)) if failures else "(none)"


def extract_tag(text: str, tag: str) -> str | None:
    m = re.findall(rf"<{tag}>(.*?)</{tag}>", text, flags=re.S | re.I)  # models vary tag case
    if m:
        return m[-1].strip()
    # Reply cut off before (or inside) the closing tag: keep the body, drop the partial tag.
    m = re.search(rf"<{tag}>(.*)$", text, flags=re.S | re.I)
    return re.sub(r"</?\w*>?\s*$", "", m.group(1)).strip() if m else None


@dataclass
class Proposal:
    strategy: str
    prompt: str
    parents: list[str]


def propose(llm: LLMClient, strategy: str, *, description: str, objective: str, parents: list[dict],
            lessons: list[str], failures: list[str], reference_prompt: str) -> Proposal:
    """parents: [{"id","prompt","score"}]; raises ValueError if the model didn't return a usable prompt."""
    sys = SYSTEM.format(description=description, objective=objective)
    if strategy == "mutate":
        p = parents[0]
        user = (f"CURRENT BEST PROMPT (score {p['score']}):\n<current>\n{p['prompt']}\n</current>\n\n"
                f"LESSONS LEARNED SO FAR:\n{_lessons_block(lessons)}\n\n"
                f"RECENT FAILURES OF THIS PROMPT:\n{_failures_block(failures)}\n\n"
                "Make small, targeted edits that fix the failure patterns above without breaking what works.")
    elif strategy == "crossover":
        a, b = parents[0], parents[1]
        user = (f"PROMPT A (score {a['score']}):\n<a>\n{a['prompt']}\n</a>\n\n"
                f"PROMPT B (score {b['score']}):\n<b>\n{b['prompt']}\n</b>\n\n"
                f"LESSONS LEARNED SO FAR:\n{_lessons_block(lessons)}\n\n"
                "Combine the strongest parts of both into one prompt that should beat both.")
    elif strategy == "fresh":
        user = (f"ORIGINAL PROMPT (for the facts and requirements it contains, not its wording):\n"
                f"<original>\n{reference_prompt}\n</original>\n\n"
                f"LESSONS LEARNED SO FAR:\n{_lessons_block(lessons)}\n\n"
                f"EXAMPLE FAILURES OF THE CURRENT BEST PROMPT:\n{_failures_block(failures)}\n\n"
                "Write a new prompt from scratch with a different approach than the current ones.")
    else:
        raise ValueError(strategy)
    temp = 1.0 if strategy == "fresh" else 0.7
    r = llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": user}],
                 temperature=temp, max_tokens=4096)
    prompt = extract_tag(r.text, "prompt")
    if not prompt or len(prompt) < 20:
        raise ValueError(f"no usable <prompt> block ({r.completion_tokens} tokens); "
                         f"reply ends: {r.text.strip()[-150:]!r}")
    return Proposal(strategy, prompt, [p["id"] for p in parents])


ANALYST = """You are the analyst on a prompt-optimization team. You read failure cases of the current best
prompt and write short, general LESSONS that will help the next round of prompt proposals.

TASK: {description}

Rules:
- Each lesson is one sentence, concrete and actionable (e.g. "X and Y are often confused; the deciding cue is Z").
- Generalize: never quote or refer to a specific test example.
- Merge with the existing lessons: keep the useful ones, drop wrong or redundant ones. At most 8 lessons total.
- Return the full updated list as lines starting with "- ", wrapped in <lessons></lessons> tags."""


def analyze(llm: LLMClient, *, description: str, prompt: str, failures: list[str],
            lessons: list[str]) -> list[str]:
    user = (f"CURRENT BEST PROMPT:\n<current>\n{prompt}\n</current>\n\n"
            f"EXISTING LESSONS:\n{_lessons_block(lessons)}\n\n"
            f"FAILURES:\n{_failures_block(failures)}")
    r = llm.chat([{"role": "system", "content": ANALYST.format(description=description)},
                  {"role": "user", "content": user}], temperature=0.3, max_tokens=4096)
    block = extract_tag(r.text, "lessons")
    if not block:
        return lessons
    new = [l.strip()[2:].strip() for l in block.splitlines() if l.strip().startswith("- ")]
    return new[:8] or lessons
