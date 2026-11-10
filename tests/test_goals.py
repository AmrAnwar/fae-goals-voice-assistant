import tempfile
import unittest
from pathlib import Path

from backend.goals import GoalStore


class GoalStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = GoalStore(Path(self.tmp.name) / "goals.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_add_and_list(self) -> None:
        goal = self.store.add(
            "alice",
            "Run a 10k",
            why="feel strong",
            deadline="June",
            first_step="buy shoes",
        )
        self.assertEqual(goal["status"], "active")
        self.assertEqual(goal["title"], "Run a 10k")

        goals = self.store.list("alice")
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]["id"], goal["id"])

    def test_add_same_title_updates_in_place(self) -> None:
        first = self.store.add("alice", "Learn guitar")
        second = self.store.add("alice", "learn guitar", deadline="December")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list("alice")), 1)
        self.assertEqual(second["deadline"], "December")

    def test_identities_are_isolated(self) -> None:
        self.store.add("alice", "Alice goal")
        self.store.add("bob", "Bob goal")
        self.assertEqual([g["title"] for g in self.store.list("alice")], ["Alice goal"])
        self.assertEqual([g["title"] for g in self.store.list("bob")], ["Bob goal"])

    def test_complete_by_title(self) -> None:
        self.store.add("alice", "Write every morning")
        done = self.store.complete_by_title("alice", "write")
        self.assertIsNotNone(done)
        self.assertEqual(done["status"], "done")
        self.assertIsNone(self.store.complete_by_title("alice", "write"))

    def test_remove_by_title(self) -> None:
        self.store.add("alice", "Read 12 books")
        removed = self.store.remove_by_title("alice", "12 books")
        self.assertIsNotNone(removed)
        self.assertEqual(self.store.list("alice"), [])

    def test_remove_respects_identity(self) -> None:
        goal = self.store.add("alice", "Private goal")
        self.assertFalse(self.store.remove("bob", goal["id"]))
        self.assertEqual(len(self.store.list("alice")), 1)

    def test_active_goals_and_identities(self) -> None:
        self.store.add("alice", "Learn guitar")
        self.store.add("alice", "Run a 10k")
        self.store.add("bob", "Write daily")
        self.store.complete_by_title("alice", "guitar")

        self.assertEqual(
            [goal["title"] for goal in self.store.active_goals("alice")],
            ["Run a 10k"],
        )
        self.assertEqual(self.store.identities(), ["alice", "bob"])

    def test_check_ins_are_stored_separately_from_goals(self) -> None:
        self.store.add("alice", "Run a 10k")
        first = self.store.add_check_in("alice", "Gentle check-in on 'Run a 10k'.")
        second = self.store.add_check_in("alice", "Another nudge.")
        self.store.add_check_in("bob", "Bob's nudge.")

        alice = self.store.list_check_ins("alice")
        self.assertEqual([row["id"] for row in alice], [second["id"], first["id"]])
        self.assertEqual(
            [row["message"] for row in self.store.list_check_ins("bob")],
            ["Bob's nudge."],
        )
        # Check-ins live in their own table and never affect the goal list.
        self.assertEqual(len(self.store.list("alice")), 1)


if __name__ == "__main__":
    unittest.main()
