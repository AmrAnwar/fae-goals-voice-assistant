# My Fairy Goals

A live voice demo built with **LiveKit Agents** and **Google Gemini Live**. Talk to **Fae**, a fairy goal-keeper, and watch your spoken wishes turn into saved goal cards on screen in real time.

- **Speech-to-speech** — Gemini Live handles listening and speaking, so no separate STT/TTS keys are needed.
- **Live transcription** — your conversation appears as it happens.
- **Real tool calls** — Fae saves, completes, and removes goals through function tools backed by SQLite.
- **Live UI updates** — goal cards appear instantly through a LiveKit data channel.
- **Local by default** — the LiveKit server, token server, SQLite database, and web UI all run on your machine. The only cloud service is Gemini.

---

## Quick start

```bash
./scripts/setup.sh    # Python deps + local LiveKit server + .env
# add your Google key to .env
./scripts/dev.sh      # or: make dev
```

Then open **http://localhost:3000** and click **Summon Fae**. Allow microphone access and start talking.

> On macOS, `make dev` can fail with an `xcrun: error: active developer path ... does not exist` if Xcode was removed. Either run `./scripts/dev.sh` directly or prefix the command with `DEVELOPER_DIR=/Library/Developer/CommandLineTools`.

Get a Gemini API key at **https://aistudio.google.com/apikey** (it starts with `AIza`).

```dotenv
# .env
GOOGLE_API_KEY=AIza...
```

> The demo refuses to start until the placeholder key is replaced, so you get a clear message instead of a mysterious agent crash.

---

## How it works

```
┌──────────────────────┐        WebRTC audio + data         ┌─────────────────────────┐
│  Browser (web/)      │ ◄────────────────────────────────► │  livekit-server --dev   │
│  livekit-client SDK  │                                    │  ws://localhost:7880    │
└──────────┬───────────┘                                    └────────────┬────────────┘
           │ token                                    auto-dispatched job │
           ▼                                                                 ▼
┌──────────────────────┐                                    ┌─────────────────────────┐
│  FastAPI (server.py) │                                    │  Fae (fairy_agent.py)   │
│  /api/token          │                                    │  livekit-agents 1.8     │
│  /api/goals          │◄────────── SQLite ─────────────────►│  Gemini Live realtime   │
└──────────────────────┘               data/goals.db         └─────────────────────────┘
```

1. The browser asks the FastAPI server for a LiveKit token.
2. It joins the `fairy-goals` room and publishes the microphone.
3. The agent worker auto-joins the room and opens a Gemini Live speech-to-speech session.
4. Fae's tool calls write to SQLite and publish a fresh goal snapshot on the `goals` data topic.
5. The browser renders the transcript and goal cards. Completing or deleting a card calls the same store.

The agent uses automatic dispatch (`@server.rtc_session()` with no `agent_name`), which is why no extra dispatch call is needed.

---

## Project layout

```
agent / server
  backend/fairy_agent.py   Fae's persona, tools, Gemini Live session
  backend/server.py        LiveKit token endpoint, goals API, static files
  backend/goals.py         SQLite goal store
web/
  index.html               Voice UI
  styles.css               Magical aurora / orb / glass design
  app.js                   LiveKit client, audio visualiser, transcripts, goals
scripts/
  setup.sh                 One-time install
  dev.sh                   Runs LiveKit + web server + agent together
tests/test_goals.py        Store unit tests
```

---

## Configuration

All settings live in `.env`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOOGLE_API_KEY` | — | Gemini API key (required) |
| `LIVEKIT_URL` | `ws://localhost:7880` | Server URL used by the agent and token response |
| `PUBLIC_LIVEKIT_URL` | falls back to `LIVEKIT_URL` | Browser-facing URL, useful behind a proxy |
| `LIVEKIT_API_KEY` | `devkey` | Local dev server key |
| `LIVEKIT_API_SECRET` | `secret` | Local dev server secret |
| `GOOGLE_LIVE_MODEL` | `gemini-3.8-live` | Gemini Live model. Older `gemini-2.5-flash-native-audio-*` previews can close the socket with a `1007` “audio content type not supported” error mid-session. |
| `FAIRY_VOICE` | `Aoede` | Gemini voice: `Aoede`, `Puck`, `Kore`, `Leda`, `Zephyr`, `Charon`, `Fenrir`, `Orus` |
| `FAIRY_ROOM` | `fairy-goals` | Default room name |
| `GOALS_DB` | `data/goals.db` | SQLite file location |

### Using LiveKit Cloud instead of the local server

Create a free project at https://cloud.livekit.io, then set:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

Run the token server and agent without starting the local server:

```bash
make server     # terminal 1
make agent      # terminal 2
```

The agent connects out to LiveKit Cloud, so no inbound ports are required.

---

## Playing with Fae

Try:

- “I want to run a 10k by summer, but I keep putting it off.”
- “I've been saying I'll learn guitar for two years.”
- “Help me build a morning writing habit.”
- “What goals do I have?”
- “I finished the writing one — mark it done.”

Fae asks one question at a time, reflects back what she hears, and only saves a goal after you agree on the wording. Goal cards update live in the right-hand panel.

To reset everything, run `make reset-goals`. The browser keeps a random `dreamer-...` identity in `localStorage`, which is how goals persist between sessions.

---

## Customising

- **Persona and coaching style** — edit `INSTRUCTIONS` in `backend/fairy_agent.py`.
- **Tools** — add a `@function_tool` method to the `Fairy` class. Gemini Live calls it automatically.
- **Model** — set `GOOGLE_LIVE_MODEL`. The default here is `gemini-3.8-live`; other Live models your key can use include `gemini-3.1-flash-live-preview`. Avoid the `gemini-2.5-flash-native-audio-*` previews for long sessions: they can close with `1007` and the plugin then ends the session instead of reconnecting.
- **Look** — the palette and orb live in `web/styles.css` (`:root` variables and the `.orb` block).
- **Voice** — set `FAIRY_VOICE`; `Aoede` is airy and fairy-like.

---

## Troubleshooting

**“Fae has not arrived” in the browser**
Check the `make dev` terminal. The agent must be running and connected to the same LiveKit URL as the token server. If you used LiveKit Cloud, make sure all three `LIVEKIT_*` values match. On a busy machine, LiveKit can also refuse to dispatch a job if the worker reports a load of 1.0; this demo reports an idle worker (`load_fnc=lambda: 0.0`) so that does not happen here.

**`GOOGLE_API_KEY is not set`**
Add the key to `.env` (not `.env.example`) and restart `make dev`. The setup script creates `.env` on first run.

**Gemini connection / 404 / model errors**
Your key may not have access to the default preview model. Set `GOOGLE_LIVE_MODEL` to a Live model enabled for your key, and check the terminal for the exact error from Google.

**No sound**
Browsers often block autoplay. Click **Enable sound** when it appears, or click anywhere on the page and try again.

**Microphone blocked**
Use `http://localhost:3000` rather than opening the HTML file directly. Browsers require a secure context (`localhost` counts) for microphone access.

**Port already in use**
`make dev` reuses a running server on `:3000` and `:7880`. To use another web port, run `PORT=3001 make dev` (the agent's token response then points the browser at the same origin).

**Slow first agent start**
PyAV's native libraries can take a minute to be verified the first time on macOS. Later starts are faster.

---

## Notes

- This is a local demo, not a hardened service. Tokens are issued without authentication so anyone on your machine can join the room.
- Only goal text is stored in SQLite. Audio goes directly through LiveKit to Gemini and is not recorded by this app.
- Gemini Live usage is billed by Google according to your API key's plan.
