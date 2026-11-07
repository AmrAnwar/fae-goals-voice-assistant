"""Fae — a voice-first fairy goal-keeper powered by Gemini Live + LiveKit Agents.

Run in dev mode:  .venv/bin/python -m backend.fairy_agent dev
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobExecutorType,
    RunContext,
    function_tool,
    room_io,
)
from livekit.plugins import google

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from backend.goals import GoalStore  # noqa: E402  (after load_dotenv)

logger = logging.getLogger("fairy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STORE = GoalStore(os.getenv("GOALS_DB", str(ROOT / "data" / "goals.db")))
VOICE = os.getenv("FAIRY_VOICE", "Aoede")
MODEL = os.getenv("GOOGLE_LIVE_MODEL", "").strip()

INSTRUCTIONS = """
You are Fae, a warm, playful fairy goal-keeper who lives inside an app called
My Fairy Goals. Your job is to help the dreamer turn a fuzzy wish into a clear,
doable goal, and then keep them gently accountable.

VOICE AND STYLE
- This is a spoken conversation. Speak naturally, like a close friend with a
  little magic. Use one to three short sentences per turn.
- Never use markdown, bullet points, emojis, stage directions, or spelled-out
  symbols. Your words are heard, not read.
- Ask at most one question at a time. Leave room for the dreamer to think.
- Reflect back what you heard in your own words before adding advice.
- A light touch of fairy imagery is seasoning, not the meal. Do not overdo it.

HOW TO COACH
1. Understand what the dreamer actually wants and why it matters to them.
2. Shape it into something specific, real, and anchored to a deadline they
   choose. If they have no deadline, help them pick a gentle one.
3. Find the smallest first step they could take within the next 48 hours.
4. When the dreamer agrees to save the goal, you MUST call add_goal in that
   same turn, before you speak your confirmation. Never say a goal was saved
   unless the add_goal tool returned a success message.
5. Only call add_goal after the dreamer agrees on the wording. If they revise
   the goal later, call add_goal again with the corrected wording.
6. Do not invent details. If a wish is vague, ask one clarifying question.

TOOLS
- add_goal: save a goal after the dreamer confirms it. If they say "yes",
  "save it", or anything that clearly means yes, call add_goal immediately.
- list_goals: check what is already saved. Use it when the dreamer asks, or when
  you are unsure what they are referring to.
- complete_goal: mark a goal done when they say they finished it.
- remove_goal: remove a goal only when the dreamer clearly asks you to.
After a tool call, confirm briefly in your own voice. Never read IDs aloud and
never say the word "tool".

BOUNDARIES
- You are not a therapist, doctor, lawyer, or financial adviser.
- If the dreamer mentions self-harm, abuse, or a medical emergency, gently urge
  them to contact local emergency services or a trusted professional, and stop
  goal coaching for that turn.
- Do not claim to have done anything in the real world beyond saving, updating,
  or removing their goals.

BEGINNING
Greet the dreamer warmly, mention that you can turn a wish into a first step,
and ask what they have been dreaming about. Do not list their saved goals
unless they ask.
""".strip()


def _instructions_for(identity: str) -> str:
    goals = STORE.list(identity)
    if not goals:
        return INSTRUCTIONS + "\n\nThis dreamer has no saved goals yet."

    lines = []
    for goal in goals[:12]:
        bits = [f"- {goal['title']} [{goal['status']}]"]
        if goal["deadline"]:
            bits.append(f"deadline: {goal['deadline']}")
        if goal["first_step"]:
            bits.append(f"first step: {goal['first_step']}")
        lines.append("; ".join(bits))
    saved = "\n".join(lines)
    return (
        INSTRUCTIONS
        + "\n\nSaved goals for this dreamer:\n"
        + saved
        + "\nUse this context naturally. Do not read the list aloud unless asked."
    )


class Fairy(Agent):
    def __init__(self, room: rtc.Room, identity: str) -> None:
        super().__init__(instructions=_instructions_for(identity))
        self._room = room
        self._identity = identity

    async def _sync_goals(self) -> None:
        """Push the current goal list to the browser over LiveKit data messages."""
        try:
            payload = json.dumps({"type": "goals", "goals": STORE.list(self._identity)})
            await self._room.local_participant.publish_data(
                payload.encode("utf-8"),
                reliable=True,
                topic="goals",
            )
        except Exception:
            logger.warning("could not publish goal sync", exc_info=True)

    @function_tool
    async def add_goal(
        self,
        context: RunContext,
        title: str,
        why: str = "",
        deadline: str = "",
        first_step: str = "",
    ) -> str:
        """Save or update a goal for the dreamer. Only call after they confirm it.

        Args:
            title: Short, specific goal title, such as "Run a 10k by June".
            why: The dreamer's reason for wanting this, in their own words.
            deadline: When they want to achieve it, as they described it.
            first_step: The smallest next action they can take in 48 hours.
        """
        try:
            goal = STORE.add(
                self._identity,
                title=title,
                why=why,
                deadline=deadline,
                first_step=first_step,
            )
        except ValueError as exc:
            return f"I could not save that goal: {exc}."
        except Exception:
            logger.exception("add_goal failed")
            return "Something went wrong while saving that goal. Please try again."

        await self._sync_goals()
        detail = f" Deadline: {goal['deadline']}." if goal["deadline"] else ""
        step = f" First step: {goal['first_step']}." if goal["first_step"] else ""
        return f"Saved the goal '{goal['title']}'.{detail}{step}"

    @function_tool
    async def list_goals(self, context: RunContext) -> str:
        """List the dreamer's saved goals, including their status."""
        goals = STORE.list(self._identity)
        if not goals:
            return "The dreamer has no saved goals yet."

        lines = []
        for index, goal in enumerate(goals, start=1):
            line = f"{index}. {goal['title']} — {goal['status']}"
            if goal["deadline"]:
                line += f", deadline {goal['deadline']}"
            if goal["first_step"]:
                line += f", first step: {goal['first_step']}"
            lines.append(line)
        return "Saved goals:\n" + "\n".join(lines)

    @function_tool
    async def complete_goal(self, context: RunContext, title: str) -> str:
        """Mark a saved goal as complete, matching it by its title.

        Args:
            title: The title of the goal the dreamer says they finished.
        """
        goal = STORE.complete_by_title(self._identity, title)
        if not goal:
            return f"I could not find an active goal matching '{title}'."
        await self._sync_goals()
        return f"Marked '{goal['title']}' as complete. That is worth celebrating."

    @function_tool
    async def remove_goal(self, context: RunContext, title: str) -> str:
        """Remove a saved goal, matching it by its title.

        Use only when the dreamer clearly asks to delete or abandon a goal.

        Args:
            title: The title of the goal to remove.
        """
        goal = STORE.remove_by_title(self._identity, title)
        if not goal:
            return f"I could not find a goal matching '{title}'."
        await self._sync_goals()
        return f"Removed '{goal['title']}' from the dreamer's goals."


# This is a single-user local demo, so run jobs in-process. The default
# PROCESS executor spawns a fresh interpreter per job; on a slow Intel Mac the
# import alone can exceed the 10s initialization timeout and dispatch fails.
# THREAD avoids that startup cost.
#
# The server also refuses to dispatch to a worker whose reported load is >= 1.0.
# This Intel Mac idles near a load average of 1, which made LiveKit think the
# worker had zero capacity and silently drop job requests. A local single-user
# demo does not need load-aware dispatch, so report an idle worker.
server = AgentServer(
    job_executor_type=JobExecutorType.THREAD,
    load_threshold=float("inf"),
    load_fnc=lambda: 0.0,
)


@server.rtc_session()
async def fairy_session(ctx: JobContext) -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        logger.error(
            "GOOGLE_API_KEY is missing. Add it to .env, then restart the agent."
        )
        raise RuntimeError("GOOGLE_API_KEY is missing")

    participant = await ctx.wait_for_participant()
    identity = participant.identity
    logger.info(
        "Fae joining room %s for %s (model=%s)",
        ctx.room.name,
        identity,
        MODEL or "plugin-default",
    )

    model_kwargs: dict = {
        "voice": VOICE,
        "temperature": 0.85,
        # The plugin leaves this to google-genai's default, which currently
        # resolves to an endpoint that 404s for Gemini Live. v1beta is the
        # working Live API version for this key.
        "api_version": os.getenv("GOOGLE_LIVE_API_VERSION", "v1beta"),
    }
    if MODEL:
        model_kwargs["model"] = MODEL

    session = AgentSession(llm=google.realtime.RealtimeModel(**model_kwargs))

    await session.start(
        agent=Fairy(ctx.room, identity),
        room=ctx.room,
        room_options=room_io.RoomOptions(),
    )

    existing = STORE.list(identity)
    nudge = ""
    if existing:
        open_count = sum(1 for goal in existing if goal["status"] == "active")
        if open_count:
            nudge = (
                f" The dreamer has {open_count} active goal"
                f"{'s' if open_count != 1 else ''} saved. Do not list them unprompted,"
                " but you may gently reference them if relevant."
            )

    await session.generate_reply(
        instructions=(
            "Greet the dreamer warmly as Fae, in one or two short spoken sentences."
            " Mention you can turn a wish into a first step, then ask what they have"
            " been dreaming about." + nudge
        )
    )


if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
