.PHONY: setup dev agent server reset-goals test

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
