import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from backend.goals import GoalStore
from backend.temporal import activities


class _FakeClient:
    """Minimal stand-in for google.genai.Client's async models API."""

    def __init__(self, *, text: str | None = None, error: Exception | None = None):
        self._text = text
        self._error = error
        self.calls: list[str] = []
        self.aio = self
        self.models = self

    async def generate_content(self, model: str, contents: str):
        self.calls.append(model)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(text=self._text)


class CheckInActivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = GoalStore(Path(self.tmp.name) / "goals.db")
        activities._store = self.store
        # Force the zero-cost template path so the test never calls a model.
        self._old_key = os.environ.pop("GOOGLE_API_KEY", None)

    def tearDown(self) -> None:
        activities._store = None
        if self._old_key is not None:
            os.environ["GOOGLE_API_KEY"] = self._old_key
        self.tmp.cleanup()

    def test_records_a_template_note_when_no_model_is_configured(self) -> None:
        self.store.add("alice", "Run a 10k", first_step="buy shoes")

        result = asyncio.run(activities.build_and_record_check_ins("alice"))

        self.assertEqual(len(result["check_ins"]), 1)
        self.assertEqual(result["check_ins"][0]["source"], "template")
        notes = self.store.list_check_ins("alice")
        self.assertEqual(len(notes), 1)
        self.assertIn("Run a 10k", notes[0]["message"])

    def test_reports_the_model_that_wrote_the_note(self) -> None:
        self.store.add("alice", "Run a 10k", first_step="buy shoes")
        client = _FakeClient(text="Fae wonders how the running shoes feel.")

        with mock.patch.object(activities, "_note_client", return_value=client), \
             mock.patch.object(activities.config, "FAIRY_NOTE_MODELS", ["fake-lite"]), \
             mock.patch.object(activities.config, "FAIRY_NOTE_ATTEMPTS", 1):
            result = asyncio.run(activities.build_and_record_check_ins("alice"))

        self.assertEqual(result["check_ins"][0]["source"], "model:fake-lite")
        note = self.store.list_check_ins("alice")[0]
        self.assertEqual(note["message"], "Fae wonders how the running shoes feel.")

    def test_reports_template_when_every_model_fails(self) -> None:
        self.store.add("alice", "Run a 10k", first_step="buy shoes")
        client = _FakeClient(error=RuntimeError("503 UNAVAILABLE high demand"))

        with mock.patch.object(activities, "_note_client", return_value=client), \
             mock.patch.object(activities.config, "FAIRY_NOTE_MODELS", ["fake-lite"]), \
             mock.patch.object(activities.config, "FAIRY_NOTE_ATTEMPTS", 1):
            result = asyncio.run(activities.build_and_record_check_ins("alice"))

        # The template actually wrote the note, so do not claim a model did.
        self.assertEqual(result["check_ins"][0]["source"], "template")
        note = self.store.list_check_ins("alice")[0]
        self.assertIn("Run a 10k", note["message"])

    def test_skips_dreamers_without_active_goals(self) -> None:
        result = asyncio.run(activities.build_and_record_check_ins("alice"))
        self.assertEqual(result["check_ins"], [])
        self.assertEqual(self.store.list_check_ins("alice"), [])

    def test_run_without_identity_checks_every_dreamer(self) -> None:
        self.store.add("alice", "Alice goal")
        self.store.add("bob", "Bob goal")
        self.store.add("carol", "Done goal")
        self.store.complete_by_title("carol", "Done goal")

        result = asyncio.run(activities.build_and_record_check_ins())

        self.assertEqual({row["identity"] for row in result["check_ins"]}, {"alice", "bob"})


if __name__ == "__main__":
    unittest.main()
