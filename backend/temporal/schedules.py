"""Create and manage the daily check-in schedule.

Examples::

    .venv/bin/python -m backend.temporal.schedules create
    .venv/bin/python -m backend.temporal.schedules list
    .venv/bin/python -m backend.temporal.schedules trigger   # run it now
    .venv/bin/python -m backend.temporal.schedules run       # ad-hoc workflow
    .venv/bin/python -m backend.temporal.schedules pause
    .venv/bin/python -m backend.temporal.schedules delete

Configure the cadence with TEMPORAL_SCHEDULE_CRON (a cron expression) and
TEMPORAL_SCHEDULE_TZ (an IANA time zone) in .env.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleSpec,
)

from backend.temporal import config
from backend.temporal.workflows import DailyGoalCheckInWorkflow


def _schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            DailyGoalCheckInWorkflow.run,
            id=f"{config.TEMPORAL_SCHEDULE_ID}-workflow",
            task_queue=config.TEMPORAL_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            cron_expressions=[config.TEMPORAL_SCHEDULE_CRON],
            time_zone_name=config.TEMPORAL_SCHEDULE_TZ,
        ),
    )


async def _connect() -> Client:
    return await Client.connect(
        config.TEMPORAL_ADDRESS,
        namespace=config.TEMPORAL_NAMESPACE,
    )


async def _create(client: Client, replace: bool) -> None:
    try:
        await client.create_schedule(config.TEMPORAL_SCHEDULE_ID, _schedule())
    except ScheduleAlreadyRunningError:
        if not replace:
            print(
                f"Schedule '{config.TEMPORAL_SCHEDULE_ID}' already exists "
                "(use create --replace to recreate it)."
            )
            return
        handle = client.get_schedule_handle(config.TEMPORAL_SCHEDULE_ID)
        await handle.delete()
        await client.create_schedule(config.TEMPORAL_SCHEDULE_ID, _schedule())
        print(f"Recreated schedule '{config.TEMPORAL_SCHEDULE_ID}'.")
        return

    print(
        f"Created schedule '{config.TEMPORAL_SCHEDULE_ID}' "
        f"({config.TEMPORAL_SCHEDULE_CRON} {config.TEMPORAL_SCHEDULE_TZ}) "
        f"on task queue '{config.TEMPORAL_TASK_QUEUE}'."
    )


def _cron_label(description) -> str:
    """The server normalises cron into calendar specs, so fall back to config."""
    spec = description.schedule.spec
    cron = ",".join(spec.cron_expressions)
    if cron:
        return cron
    if description.id == config.TEMPORAL_SCHEDULE_ID:
        return config.TEMPORAL_SCHEDULE_CRON
    return "calendar-based"


async def _list(client: Client) -> None:
    found = False
    async for description in await client.list_schedules():
        found = True
        spec = description.schedule.spec
        state = "paused" if description.schedule.state.paused else "running"
        print(
            f"{description.id}\t{_cron_label(description)}\t"
            f"{spec.time_zone_name or 'UTC'}\t{state}"
        )
    if not found:
        print("No schedules found.")


async def _describe(client: Client) -> None:
    handle = client.get_schedule_handle(config.TEMPORAL_SCHEDULE_ID)
    description = await handle.describe()
    spec = description.schedule.spec
    print(f"id:           {config.TEMPORAL_SCHEDULE_ID}")
    print(f"cron:         {_cron_label(description)}")
    print(f"time zone:    {spec.time_zone_name}")
    print(f"paused:       {description.schedule.state.paused}")
    print(f"task queue:   {description.schedule.action.task_queue}")
    print(f"next runs:    {description.info.next_action_times}")


async def _trigger(client: Client) -> None:
    handle = client.get_schedule_handle(config.TEMPORAL_SCHEDULE_ID)
    await handle.trigger()
    print(f"Triggered '{config.TEMPORAL_SCHEDULE_ID}' once, outside the cron cadence.")


async def _run(client: Client) -> None:
    """Start one check-in workflow directly (no schedule needed)."""
    handle = await client.start_workflow(
        DailyGoalCheckInWorkflow.run,
        None,
        id=f"manual-check-in-all-{time.time_ns()}",
        task_queue=config.TEMPORAL_TASK_QUEUE,
    )
    print(f"Started check-in workflow '{handle.id}'.")


async def _pause(client: Client, paused: bool) -> None:
    handle = client.get_schedule_handle(config.TEMPORAL_SCHEDULE_ID)
    if paused:
        await handle.pause(note="Paused from backend.temporal.schedules")
        print(f"Paused '{config.TEMPORAL_SCHEDULE_ID}'.")
    else:
        await handle.unpause(note="Resumed from backend.temporal.schedules")
        print(f"Resumed '{config.TEMPORAL_SCHEDULE_ID}'.")


async def _delete(client: Client) -> None:
    handle = client.get_schedule_handle(config.TEMPORAL_SCHEDULE_ID)
    await handle.delete()
    print(f"Deleted '{config.TEMPORAL_SCHEDULE_ID}'.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the fairy check-in schedule.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create the schedule")
    create.add_argument(
        "--replace",
        action="store_true",
        help="delete and recreate it if it already exists",
    )
    sub.add_parser("list", help="list schedules")
    sub.add_parser("describe", help="show the schedule details")
    sub.add_parser("trigger", help="run the workflow once, now")
    sub.add_parser("run", help="start a check-in workflow directly, no schedule needed")
    sub.add_parser("pause", help="stop future runs")
    sub.add_parser("unpause", help="resume future runs")
    sub.add_parser("delete", help="delete the schedule")
    return parser


async def _main(args: argparse.Namespace) -> None:
    client = await _connect()
    if args.command == "create":
        await _create(client, args.replace)
    elif args.command == "list":
        await _list(client)
    elif args.command == "describe":
        await _describe(client)
    elif args.command == "trigger":
        await _trigger(client)
    elif args.command == "run":
        await _run(client)
    elif args.command == "pause":
        await _pause(client, paused=True)
    elif args.command == "unpause":
        await _pause(client, paused=False)
    elif args.command == "delete":
        await _delete(client)


if __name__ == "__main__":
    asyncio.run(_main(_parser().parse_args()))
