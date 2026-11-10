"""Shared Temporal client for the web API and schedule tooling."""

from __future__ import annotations

import asyncio
import time

from temporalio.client import Client

from backend.temporal import config
from backend.temporal.workflows import DailyGoalCheckInWorkflow

_client: Client | None = None
_lock = asyncio.Lock()


async def get_client() -> Client:
    """Connect once and reuse the gRPC channel across requests."""
    global _client
    if _client is not None:
        return _client
    async with _lock:
        if _client is None:
            _client = await Client.connect(
                config.TEMPORAL_ADDRESS,
                namespace=config.TEMPORAL_NAMESPACE,
            )
    return _client


async def start_check_in(identity: str | None = None) -> str:
    """Run the check-in workflow once, outside the cron cadence."""
    client = await get_client()
    suffix = identity or "all"
    handle = await client.start_workflow(
        DailyGoalCheckInWorkflow.run,
        identity,
        id=f"manual-check-in-{suffix}-{time.time_ns()}",
        task_queue=config.TEMPORAL_TASK_QUEUE,
    )
    return handle.id
