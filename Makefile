.PHONY: setup dev agent server reset-goals test temporal-up temporal-down temporal-worker temporal-schedule temporal-schedule-list temporal-schedule-trigger temporal-run

setup:
	./scripts/setup.sh

dev:
	./scripts/dev.sh

# Individual pieces, if you prefer separate terminals
agent:
	.venv/bin/python -m backend.fairy_agent dev

server:
	.venv/bin/python -m uvicorn backend.server:app --host 127.0.0.1 --port 3000

LIVEKIT_SERVER ?= $(shell if [ -x bin/livekit-server ]; then echo bin/livekit-server; else echo livekit-server; fi)

livekit:
	$(LIVEKIT_SERVER) --dev --bind 127.0.0.1

test:
	.venv/bin/python -m unittest discover -s tests -v

reset-goals:
	rm -f data/goals.db
	@echo "Goal database cleared."

# ------------------------------------------------------------------ Temporal
# Bring up minikube + Temporal (Postgres, frontend, web UI) and port-forwards.
temporal-up:
	./scripts/temporal-up.sh

# Stop port-forwards. Use `./scripts/temporal-down.sh --purge` to delete the
# Temporal release and its data.
temporal-down:
	./scripts/temporal-down.sh

# Run the worker that executes scheduled check-ins (foreground).
temporal-worker:
	.venv/bin/python -m backend.temporal.worker

# Create the daily check-in schedule from TEMPORAL_SCHEDULE_* in .env.
temporal-schedule:
	.venv/bin/python -m backend.temporal.schedules create

temporal-schedule-list:
	.venv/bin/python -m backend.temporal.schedules list

temporal-schedule-trigger:
	.venv/bin/python -m backend.temporal.schedules trigger

# Run one check-in immediately, without waiting for the cron cadence.
temporal-run:
	.venv/bin/python -m backend.temporal.schedules run
