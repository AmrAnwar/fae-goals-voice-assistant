"""Temporal worker, workflows, and schedules for My Fairy Goals.

The app uses Temporal for durable scheduled work: once a day a workflow asks
the goal store for every dreamer's active goals and records a gentle check-in
that Fae can mention the next time they talk.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "fairy-goals")

TEMPORAL_SCHEDULE_ID = os.getenv("TEMPORAL_SCHEDULE_ID", "fairy-daily-check-in")
TEMPORAL_SCHEDULE_CRON = os.getenv("TEMPORAL_SCHEDULE_CRON", "0 9 * * *")
TEMPORAL_SCHEDULE_TZ = os.getenv("TEMPORAL_SCHEDULE_TZ", "UTC")

# Cheap text model used to write scheduled notes ahead of time. The realtime
# Gemini Live model is only used for the voice session itself, where audio
# tokens are far more expensive per run than a short text completion.
#
# A comma-separated list is allowed. Models are tried in order, cheapest first,
# so a busy or retired model does not stop the daily note.
FAIRY_NOTE_MODELS = [
    name.strip()
    for name in os.getenv(
        "FAIRY_NOTE_MODEL", "gemini-3.5-flash-lite,gemini-3.8-flash"
    ).split(",")
    if name.strip()
]

# Attempts per model before moving on (or falling back to the template).
FAIRY_NOTE_ATTEMPTS = int(os.getenv("FAIRY_NOTE_ATTEMPTS", "3"))

# Seconds to wait for one model response before treating it as transient.
FAIRY_NOTE_TIMEOUT = float(os.getenv("FAIRY_NOTE_TIMEOUT", "20"))

GOALS_DB = os.getenv("GOALS_DB", str(ROOT / "data" / "goals.db"))
