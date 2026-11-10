"""Temporal workflows for My Fairy Goals."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

# Activities touch SQLite and other non-deterministic libraries. Letting the
# sandbox import the module normally would make Temporal complain, so pass the
# import through and keep the workflow body deterministic.
with workflow.unsafe.imports_passed_through():
    from backend.temporal.activities import build_and_record_check_ins


@workflow.defn
class DailyGoalCheckInWorkflow:
    """One tick of the daily schedule: record a nudge for every active dreamer."""

    @workflow.run
    async def run(self, identity: str | None = None) -> dict[str, Any]:
        return await workflow.execute_activity(
            build_and_record_check_ins,
            identity,
            start_to_close_timeout=timedelta(minutes=1),
        )
