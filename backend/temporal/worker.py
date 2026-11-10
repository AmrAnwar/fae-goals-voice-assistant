"""Run the Temporal worker for the fairy's scheduled jobs.

Start it in its own terminal (or as a container)::

    .venv/bin/python -m backend.temporal.worker

It connects to the Temporal frontend at TEMPORAL_ADDRESS and polls the
TEMPORAL_TASK_QUEUE queue for DailyGoalCheckInWorkflow tasks.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from backend.temporal import config
from backend.temporal.activities import build_and_record_check_ins
from backend.temporal.workflows import DailyGoalCheckInWorkflow

logger = logging.getLogger("fairy.temporal")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
    )
    worker = Worker(
        client,
        task_queue=config.TEMPORAL_TASK_QUEUE,
        workflows=[DailyGoalCheckInWorkflow],
        activities=[build_and_record_check_ins],
    )

    logger.info(
        "Fairy worker listening on %s (namespace=%s, task_queue=%s)",
        config.TEMPORAL_ADDRESS,
        config.TEMPORAL_NAMESPACE,
        config.TEMPORAL_TASK_QUEUE,
    )
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
