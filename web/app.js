/* My Fairy Goals — browser client for the LiveKit voice agent. */

(() => {
  "use strict";

  const { Room, RoomEvent, Track, ConnectionState } = window.LivekitClient;

  const $ = (id) => document.getElementById(id);

  const els = {
    body: document.body,
    connect: $("connect-btn"),
    connectLabel: $("connect-btn").querySelector("span"),
    mute: $("mute-btn"),
    muteLabel: $("mute-btn").querySelector("span"),
    disconnect: $("disconnect-btn"),
    sound: $("sound-btn"),
    statusText: $("status-text"),
    transcript: $("transcript"),
    liveBadge: $("live-badge"),
    goalsList: $("goals-list"),
    goalsEmpty: $("goals-empty"),
    goalCount: $("goal-count"),
    toast: $("toast"),
  };

  const state = {
    room: null,
    identity: getIdentity(),
    connecting: false,
    micEnabled: true,
    segments: new Map(),
    audioEls: new Set(),
    audioCtx: null,
    analyser: null,
    sourceNode: null,
    rafId: 0,
    agentTimer: 0,
    toastTimer: 0,
    lastGoals: [],
  };

  /* ------------------------------------------------------------- identity */
  function getIdentity() {
    const key = "fairy-goals.identity";
    let id = "";
    try {
      id = localStorage.getItem(key) || "";
    } catch {
      /* localStorage can be blocked */
    }
    if (!id) {
      id = "dreamer-" + Math.random().toString(36).slice(2, 10);
      try {
        localStorage.setItem(key, id);
      } catch {
        /* ignore */
      }
    }
    return id;
  }

  /* ------------------------------------------------------------------ ui */
  function setState(name, message) {
    els.body.dataset.state = name;
    if (message) els.statusText.textContent = message;
  }

  function setControls(connected) {
    els.connect.hidden = connected;
    els.mute.hidden = !connected;
    els.disconnect.hidden = !connected;
    els.liveBadge.hidden = !connected;
  }

  function toast(message, ms = 5200) {
    els.toast.textContent = message;
    els.toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => els.toast.classList.remove("show"), ms);
  }

  function showSoundButton() {
    els.sound.hidden = false;
  }

  function hasAgent() {
    if (!state.room) return false;
    return [...state.room.remoteParticipants.values()].some(
      (p) => p.identity !== state.identity
    );
  }

  function refreshStatus() {
    if (!state.room) return;
    if (!hasAgent()) {
      setState("connecting", "Fae is arriving…");
      return;
    }
    setState("live", "Fae is listening. Say anything.");
  }

  /* ----------------------------------------------------------- connect */
  async function connect() {
    if (state.connecting || state.room) return;

    state.connecting = true;
    els.connect.disabled = true;
    els.connectLabel.textContent = "Opening the door…";
    setState("connecting", "Opening a little door between worlds…");

    try {
      const res = await fetch(
        `/api/token?identity=${encodeURIComponent(state.identity)}&name=Dreamer`
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not get a room token.");

      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
        disconnectOnPageLeave: true,
      });
      state.room = room;
      wireRoom(room);

      await room.connect(data.url, data.token);

      try {
        await room.startAudio();
      } catch {
        showSoundButton();
      }

      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        state.micEnabled = true;
        els.muteLabel.textContent = "Mute";
        els.mute.classList.remove("is-active");
      } catch (err) {
        toast("Fae needs your microphone. Allow access in your browser and try again.");
        await room.disconnect();
        resetUI("Microphone access was blocked. Tap to try again.");
        return;
      }

      setControls(true);
      resetTranscript();
      setState("connecting", "Fae is arriving…");

      state.agentTimer = window.setTimeout(() => {
        if (!hasAgent()) {
          setState(
            "connecting",
            "Fae has not arrived. Is the agent running? Check the terminal."
          );
          toast("No agent joined the room. Start it with: make dev", 8000);
        }
      }, 20000);

      fetchGoals();
    } catch (err) {
      console.error(err);
      toast(err.message || "Could not connect. Is the token server running?");
      resetUI("The door would not open. Tap to try again.");
    } finally {
      state.connecting = false;
      els.connect.disabled = false;
      els.connectLabel.textContent = "Summon Fae";
    }
  }

  function wireRoom(room) {
    room
      .on(RoomEvent.Connected, () => {
        els.liveBadge.hidden = false;
      })
      .on(RoomEvent.Reconnecting, () => {
        setState("connecting", "Holding the thread. Reconnecting…");
      })
      .on(RoomEvent.Reconnected, () => {
        refreshStatus();
        fetchGoals();
      })
      .on(RoomEvent.Disconnected, () => {
        resetUI("The door closed. Tap to summon Fae again.");
      })
      .on(RoomEvent.ParticipantConnected, (participant) => {
        if (participant.identity === state.identity) return;
        clearTimeout(state.agentTimer);
        setState("live", "Fae is here. Say anything.");
      })
      .on(RoomEvent.ParticipantDisconnected, (participant) => {
        if (participant.identity === state.identity) return;
        setState("connecting", "Fae stepped away. Waiting for her to return…");
      })
      .on(RoomEvent.TrackSubscribed, onTrackSubscribed)
      .on(RoomEvent.TrackUnsubscribed, onTrackUnsubscribed)
      .on(RoomEvent.ActiveSpeakersChanged, onActiveSpeakers)
      .on(RoomEvent.TranscriptionReceived, onTranscription)
      .on(RoomEvent.DataReceived, onData)
      .on(RoomEvent.ConnectionStateChanged, (connectionState) => {
        if (connectionState === ConnectionState.Connected) {
          els.liveBadge.hidden = false;
        }
      });

    if (RoomEvent.AudioPlaybackStatusChanged) {
      room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
        if (!room.canPlaybackAudio) showSoundButton();
      });
    }
  }

  async function disconnect() {
    if (!state.room) {
      resetUI("Tap to summon Fae.");
      return;
    }
    try {
      await state.room.disconnect();
    } catch {
      /* ignore */
    }
    resetUI("The door closed. Tap to summon Fae again.");
  }

  function resetUI(message) {
    clearTimeout(state.agentTimer);
    state.room = null;
    setControls(false);
    setState("idle", message || "Tap below to summon Fae. Microphone access is required.");
    els.mute.hidden = true;
    els.sound.hidden = true;
    cleanupAudio();
    document.documentElement.style.setProperty("--level", "0");
  }

  /* --------------------------------------------------------------- audio */
  function onTrackSubscribed(track, publication, participant) {
    if (track.kind !== Track.Kind.Audio) return;
    if (participant && participant.identity === state.identity) return;

    const el = track.attach();
    el.autoplay = true;
    el.setAttribute("playsinline", "");
    el.style.display = "none";
    document.body.appendChild(el);
    state.audioEls.add(el);

    el.play().catch(() => showSoundButton());
    setupAnalyser(track).catch(() => {
      /* visualisation is optional */
    });
  }

  function onTrackUnsubscribed(track) {
    const el = track.detach?.();
    if (el && el.length) {
      el.forEach((node) => {
        node.pause();
        node.remove();
        state.audioEls.delete(node);
      });
    }
    stopMeter();
  }

  async function setupAnalyser(track) {
    const mediaTrack = track.mediaStreamTrack;
    if (!mediaTrack) return;

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;

    if (!state.audioCtx) state.audioCtx = new AudioCtx();
    const ctx = state.audioCtx;
    if (ctx.state === "suspended") await ctx.resume();

    stopMeter({ keepContext: true });

    const source = ctx.createMediaStreamSource(new MediaStream([mediaTrack]));
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.78;
    source.connect(analyser);

    state.sourceNode = source;
    state.analyser = analyser;

    const data = new Uint8Array(analyser.fftSize);
    const tick = () => {
      if (!state.analyser) return;
      state.analyser.getByteTimeDomainData(data);

      let sum = 0;
      for (let i = 0; i < data.length; i += 1) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);
      const level = Math.min(1, rms * 4.2);
      document.documentElement.style.setProperty("--level", level.toFixed(3));
      state.rafId = requestAnimationFrame(tick);
    };

    cancelAnimationFrame(state.rafId);
    tick();
  }

  function stopMeter(opts = {}) {
    cancelAnimationFrame(state.rafId);
    state.rafId = 0;
    document.documentElement.style.setProperty("--level", "0");

    try {
      state.sourceNode?.disconnect();
    } catch {
      /* ignore */
    }
    try {
      state.analyser?.disconnect();
    } catch {
      /* ignore */
    }
    state.sourceNode = null;
    state.analyser = null;

    if (!opts.keepContext && state.audioCtx) {
      try {
        state.audioCtx.suspend();
      } catch {
        /* ignore */
      }
    }
  }

  function cleanupAudio() {
    stopMeter();
    state.audioEls.forEach((el) => {
      try {
        el.pause();
        el.srcObject = null;
        el.remove();
      } catch {
        /* ignore */
      }
    });
    state.audioEls.clear();
  }

  function onActiveSpeakers(speakers) {
    if (!hasAgent()) return;
    const agentSpeaking = speakers.some((p) => p.identity !== state.identity);
    const userSpeaking = speakers.some((p) => p.identity === state.identity);

    if (agentSpeaking) {
      setState("speaking", "Fae is speaking…");
    } else if (userSpeaking) {
      setState("listening", "Listening to you…");
    } else {
      setState("live", "Fae is listening. Say anything.");
    }
  }

  /* --------------------------------------------------------- transcript */
  function resetTranscript() {
    state.segments.clear();
    els.transcript.innerHTML = "";
    const empty = document.createElement("p");
    empty.className = "transcript-empty";
    empty.textContent = "Your words will appear here as you talk with Fae.";
    els.transcript.appendChild(empty);
  }

  function clearTranscriptEmpty() {
    const empty = els.transcript.querySelector(".transcript-empty");
    if (empty) empty.remove();
  }

  function onTranscription(segments, participant) {
    if (!segments || !segments.length) return;

    const isUser = participant ? participant.identity === state.identity : false;
    clearTranscriptEmpty();

    const nearBottom =
      els.transcript.scrollHeight - els.transcript.scrollTop - els.transcript.clientHeight < 90;

    for (const segment of segments) {
      if (!segment.text) continue;

      const key = `${participant?.identity || (isUser ? "you" : "fae")}:${segment.id}`;
      let row = state.segments.get(key);

      if (!row) {
        const wrapper = document.createElement("div");
        wrapper.className = "bubble" + (isUser ? " user" : "");

        const who = document.createElement("span");
        who.className = "who";
        who.textContent = isUser ? "You" : "Fae";

        const what = document.createElement("p");
        what.className = "what";

        wrapper.append(who, what);
        els.transcript.appendChild(wrapper);
        row = { el: wrapper, what };
        state.segments.set(key, row);
      }

      row.what.textContent = segment.text;
      row.el.classList.toggle("interim", segment.final === false);
    }

    if (nearBottom) {
      els.transcript.scrollTop = els.transcript.scrollHeight;
    }
  }

  /* -------------------------------------------------------------- goals */
  async function fetchGoals() {
    try {
      const res = await fetch(`/api/goals?identity=${encodeURIComponent(state.identity)}`);
      if (!res.ok) return;
      const data = await res.json();
      renderGoals(data.goals || []);
    } catch {
      /* offline / server restarting */
    }
  }

  function renderGoals(goals) {
    state.lastGoals = goals;
    els.goalsList.innerHTML = "";
    els.goalCount.textContent = String(goals.length);

    const hasGoals = goals.length > 0;
    els.goalsEmpty.hidden = hasGoals;
    els.goalsList.hidden = !hasGoals;

    if (!hasGoals) return;

    const fragment = document.createDocumentFragment();

    for (const goal of goals) {
      const done = goal.status === "done";
      const li = document.createElement("li");
      li.className = "goal" + (done ? " is-done" : "");
      li.dataset.id = goal.id;

      const check = document.createElement("button");
      check.type = "button";
      check.className = "goal-check";
      check.dataset.action = "complete";
      check.disabled = done;
      check.setAttribute(
        "aria-label",
        done ? `"${goal.title}" is complete` : `Mark "${goal.title}" complete`
      );

      const body = document.createElement("div");
      body.className = "goal-body";

      const top = document.createElement("div");
      top.className = "goal-top";

      const title = document.createElement("h3");
      title.className = "goal-title";
      title.textContent = goal.title;

      const del = document.createElement("button");
      del.type = "button";
      del.className = "goal-delete";
      del.dataset.action = "delete";
      del.setAttribute("aria-label", `Remove "${goal.title}"`);
      del.textContent = "×";

      top.append(title, del);

      const why = document.createElement("p");
      why.className = "goal-why";
      why.textContent = goal.why || "";
      if (!goal.why) why.hidden = true;

      const meta = document.createElement("div");
      meta.className = "goal-meta";

      if (goal.deadline) {
        const tag = document.createElement("span");
        tag.className = "goal-tag";
        tag.innerHTML =
          '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2v2M12 2v2M2.5 6h11M4 3.5h8a1.5 1.5 0 011.5 1.5v7A1.5 1.5 0 0112 13.5H4A1.5 1.5 0 012.5 12V5A1.5 1.5 0 014 3.5z" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';
        tag.append(document.createTextNode(goal.deadline));
        meta.appendChild(tag);
      }

      if (goal.first_step) {
        const step = document.createElement("span");
        step.className = "goal-tag first";
        step.textContent = "First step: " + goal.first_step;
        meta.appendChild(step);
      }

      body.append(top, why, meta);
      li.append(check, body);
      fragment.appendChild(li);
    }

    els.goalsList.appendChild(fragment);
  }

  async function completeGoal(goalId) {
    try {
      const res = await fetch(
        `/api/goals/${encodeURIComponent(goalId)}/complete?identity=${encodeURIComponent(
          state.identity
        )}`,
        { method: "POST" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the goal.");
      renderGoals(data.goals || []);
      toast("One wish, well and truly done. ✦");
    } catch (err) {
      toast(err.message);
    }
  }

  async function deleteGoal(goalId) {
    const goal = state.lastGoals.find((item) => item.id === goalId);
    if (!goal) return;

    const yes = window.confirm(`Remove “${goal.title}” from your goals?`);
    if (!yes) return;

    try {
      const res = await fetch(
        `/api/goals/${encodeURIComponent(goalId)}?identity=${encodeURIComponent(state.identity)}`,
        { method: "DELETE" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not remove the goal.");
      renderGoals(data.goals || []);
      toast("The goal drifted away.");
    } catch (err) {
      toast(err.message);
    }
  }

  function onData(payload, participant, kind, topic) {
    try {
      const text = new TextDecoder().decode(payload);
      const message = JSON.parse(text);
      if (message.type === "goals" && Array.isArray(message.goals)) {
        renderGoals(message.goals);
      }
    } catch {
      /* ignore non-JSON data */
    }
  }

  /* ------------------------------------------------------------- events */
  els.connect.addEventListener("click", connect);
  els.disconnect.addEventListener("click", disconnect);

  els.mute.addEventListener("click", async () => {
    if (!state.room) return;
    const next = !state.micEnabled;
    try {
      await state.room.localParticipant.setMicrophoneEnabled(next);
      state.micEnabled = next;
      els.muteLabel.textContent = next ? "Mute" : "Unmute";
      els.mute.classList.toggle("is-active", !next);
      setState(next ? "live" : "idle", next ? "Fae is listening. Say anything." : "You are muted.");
    } catch {
      toast("Could not change the microphone. Check browser permissions.");
    }
  });

  els.sound.addEventListener("click", async () => {
    if (!state.room) return;
    try {
      await state.room.startAudio();
      els.sound.hidden = true;
    } catch {
      toast("Tap again to let the browser play Fae’s voice.");
    }
  });

  els.goalsList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const goalEl = button.closest(".goal");
    if (!goalEl) return;
    if (button.dataset.action === "complete") completeGoal(goalEl.dataset.id);
    if (button.dataset.action === "delete") deleteGoal(goalEl.dataset.id);
  });

  /* ---------------------------------------------------------------- stars */
  function initStars() {
    const canvas = $("stars");
    if (!canvas || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let stars = [];
    let width = 0;
    let height = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const count = Math.min(130, Math.floor((width * height) / 16000));
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        r: Math.random() * 1.3 + 0.25,
        base: Math.random() * 0.5 + 0.15,
        speed: Math.random() * 0.0012 + 0.0004,
        phase: Math.random() * Math.PI * 2,
        warm: Math.random() > 0.72,
      }));
    };

    const draw = (time) => {
      ctx.clearRect(0, 0, width, height);
      for (const star of stars) {
        const twinkle = 0.45 + 0.55 * Math.sin(time * star.speed + star.phase);
        ctx.globalAlpha = star.base * twinkle;
        ctx.fillStyle = star.warm ? "#f0abfc" : "#e9d5ff";
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener("resize", resize, { passive: true });
    requestAnimationFrame(draw);
  }

  /* ----------------------------------------------------------------- init */
  function init() {
    initStars();
    setControls(false);
    fetchGoals();

    fetch("/api/health")
      .then((res) => (res.ok ? res.json() : null))
      .then((health) => {
        if (health && health.google_key_configured === false) {
          toast(
            "Google API key is not configured. Add GOOGLE_API_KEY to .env, then restart the demo.",
            9000
          );
        }
      })
      .catch(() => {});

    window.addEventListener("beforeunload", () => {
      if (state.room) state.room.disconnect();
    });
  }

  init();
})();
