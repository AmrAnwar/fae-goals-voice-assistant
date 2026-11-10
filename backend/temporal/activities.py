"""Activities for the fairy's scheduled jobs.

Activities are where side effects live. Temporal retries them with durable
state, so a check-in is not lost if the worker or database hiccups.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from temporalio import activity

from backend.goals import GoalStore
from backend.temporal import config

logger = logging.getLogger("fairy.temporal")

_store: GoalStore | None = None


def _get_store() -> GoalStore:
    global _store
    if _store is None:
        _store = GoalStore(config.GOALS_DB)
    return _store


def _goal_summary(goals: list[dict[str, Any]]) -> str:
    """Compact, factual context for the text model."""
    lines = []
    for goal in goals[:5]:
        bits = [goal["title"]]
        if goal.get("why"):
            bits.append(f"why: {goal['why']}")
        if goal.get("deadline"):
            bits.append(f"deadline: {goal['deadline']}")
        if goal.get("first_step"):
            bits.append(f"first step: {goal['first_step']}")
        lines.append("- " + "; ".join(bits))
    return "\n".join(lines)


def _template_note(goals: list[dict[str, Any]]) -> str:
    """Zero-cost fallback used when no text model is configured."""
    goal = goals[0]
    count = len(goals)
    extra = f" You have {count} active goals; this one is the oldest." if count > 1 else ""
    step = ""
    if goal.get("first_step"):
        step = f" A small first step is {goal['first_step'].rstrip('.')}."
    elif goal.get("deadline"):
        step = f" Its deadline is {goal['deadline'].rstrip('.')}."
    return (
        f"Gentle check-in on '{goal['title']}'."
        f"{step}{extra} Ask the dreamer how it is going, one question at a time."
    )


def _note_client():
    """Create a cheap text-model client, or return None to use the fallback.

    The scheduled note is written ahead of time by a text model so the
    realtime Live model is only used for the (more expensive) voice session.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key or api_key in {"your-google-ai-studio-key", "PASTE_KEY_HERE"}:
        return None
    try:
        from google import genai
    except Exception:
        logger.warning("google-genai is unavailable; scheduled notes use the template")
        return None
    return genai.Client(api_key=api_key)


_TRANSIENT_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
    "TIMEOUT",
)


def _is_transient(exc: Exception) -> bool:
    """Busy or flaky model? Worth a short retry before using the template."""
    text = f"{type(exc).__name__} {exc}".upper()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


async def _generate_note(
    client, prompt: str
) -> tuple[str | None, str | None]:
    """Ask each configured model in turn; return (text, model) on success."""
    for model in config.FAIRY_NOTE_MODELS:
        for attempt in range(config.FAIRY_NOTE_ATTEMPTS):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                    ),
                    timeout=config.FAIRY_NOTE_TIMEOUT,
                )
                text = (getattr(response, "text", "") or "").strip().strip('"').strip()
                if text:
                    return text, model
                logger.warning("model %s returned an empty note", model)
                break
            except Exception as exc:
                if not _is_transient(exc):
                    logger.warning(
                        "model %s rejected the note request; trying the next model",
                        model,
                        exc_info=True,
                    )
                    break
                if attempt + 1 >= config.FAIRY_NOTE_ATTEMPTS:
                    logger.warning(
                        "model %s is busy after %d attempts; trying the next model",
                        model,
                        config.FAIRY_NOTE_ATTEMPTS,
                    )
                    break
                delay = min(2**attempt, 8)
                logger.info(
                    "model %s is busy; retrying in %ds", model, delay
                )
                await asyncio.sleep(delay)
    return None, None


async def _compose_note(
    client, goals: list[dict[str, Any]]
) -> tuple[str, str]:
    """Return ``(message, source)`` describing who actually wrote the note."""
    fallback = _template_note(goals)
    if client is None:
        return fallback, "template"

    prompt = f"""You are Fae, the warm, playful fairy goal-keeper from the My Fairy
Goals app. Write one gentle check-in that Fae can speak aloud the next time the
dreamer talks to her.

Rules:
- One or two short sentences, under 45 words.
- Mention one specific goal and, if present, its first step or deadline.
- Be encouraging without pressure. Never invent progress or facts.
- Plain spoken text only: no markdown, no emojis, no quotation marks, no labels.
- Never mention schedules, automation, notes, or databases.

The dreamer's active goals:
{_goal_summary(goals)}
"""

    text, model = await _generate_note(client, prompt)
    if text:
        return text, f"model:{model}"

    logger.warning("no text model produced a note; using the template")
    return fallback, "template"


@activity.defn
async def build_and_record_check_ins(identity: str | None = None) -> dict[str, Any]:
    """Create one check-in per dreamer with active goals.

    Pass ``identity`` to limit the run to a single dreamer (used by the UI's
    manual trigger). Returns a small summary so a schedule run is easy to
    inspect in the Temporal UI.
    """
    store = _get_store()
    identities = [identity] if identity else store.identities()
    note_client = _note_client()
    recorded: list[dict[str, Any]] = []

    for identity in identities:
        goals = store.active_goals(identity)
        if not goals:
            continue
        message, source = await _compose_note(note_client, goals)
        check_in = store.add_check_in(identity, message)
        recorded.append(
            {
                "identity": identity,
                "check_in_id": check_in["id"],
                "goals": [goal["title"] for goal in goals],
                "source": source,
            }
        )

    logger.info(
        "Recorded %d check-in(s) for %d dreamer(s)", len(recorded), len(identities)
    )
    return {"dreamers": len(identities), "check_ins": recorded}
