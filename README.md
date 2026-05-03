# wizpr-tools

**A reverse-engineering and protocol exploration toolkit for the WIZPR Ring.**

This repo is a workshop — a place to map what the ring actually does over BLE, capture its signals, decode its protocol, and build the understanding needed to create real applications on top of it. The actual apps (iOS client, MCP integrations, AI tooling) will live in their own separate repos once the protocol is mapped.

The protocol is now mapped. See [`docs/protocol.md`](docs/protocol.md) for the full reference and [`docs/discovery.md`](docs/discovery.md) for the story of how we got there.

---

## TL;DR — What the ring does over BLE

The ring speaks plain ASCII text on characteristic `00000007`:

```
CLICK           → button pressed (one event per press)
MIC_PRE_ON      → raise-to-speak motion detected
MIC_ON          → mic active, audio streaming on char 00000001
MIC_OFF         → mic deactivated
BATTERY N(V)    → response to BATTERY query
VER XXXX        → response to GET_VERSION query
```

The phone sends one command back:

```
LOCK            → session end, disables ring input
```

That's the complete protocol. Binary audio streams on a second characteristic at ~24 packets/second while the mic is active. No pairing required. No session handshake. Connect, subscribe, listen.

---

## What's in this repo

### Guided Capture Tool (`wizpr-suite/`)

A macOS desktop app (PySide6 + qasync) that:
- Scans and auto-connects to WIZPR RING
- Subscribes to all notify characteristics simultaneously
- Walks through labeled capture actions one at a time (button presses, voice, gestures)
- Saves a structured JSON session file with every BLE payload, timestamped and labeled
- Includes a live **Command Explorer** for writing commands back to the ring

**Run it:**
```bash
git clone https://github.com/niclydon/wizpr-tools.git
cd wizpr-tools
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m wizpr-suite.app.main
```

Disconnect the ring from your iPhone before scanning. The ring only advertises when not already connected to another device.

### Ring Daemon (`scripts/ring_daemon.py`)

A persistent connection daemon for interactive ring probing. Connects once, subscribes to everything, reads commands from a named pipe at `/tmp/ring.cmd`, writes all output to `/tmp/ring.log`.

```bash
# Terminal 1 — run the daemon (needs GUI session for macOS BT permissions)
python scripts/ring_daemon.py

# Terminal 2 — send commands
echo "write 7 BATTERY" > /tmp/ring.cmd

# Terminal 3 — watch responses
tail -f /tmp/ring.log
```

---

## Documentation

- [`docs/protocol.md`](docs/protocol.md) — Complete GATT map, event reference, command vocabulary, iOS integration notes
- [`docs/discovery.md`](docs/discovery.md) — Narrative account of the reverse-engineering process
- [`CHANGES.md`](CHANGES.md) — Decision log: what changed, why, what was rejected

---

## What's still open

- **Audio codec** — char1 streams compressed binary audio. Format not yet identified. The ring likely uses ADPCM or a Silicon Labs codec. Decoding this is the remaining piece before fully offline voice pipeline is possible.
- **Write-only chars** (`00000002`, `00000003`, `00000004`, `00000006`) — silently accept writes, purpose unknown. Not needed for basic functionality.

---

## Built on the shoulders of

Forked from [R-D-BioTech-Alaska/Wizpr-Suite](https://github.com/R-D-BioTech-Alaska/Wizpr-Suite). None of this work would have been possible without it.

The original project did the genuinely hard parts: figuring out how to connect to the ring over BLE at all, building the GATT inspector, wiring up bleak on macOS, and — critically — recognizing that the ring's protocol is undocumented and that the path forward is user-controlled reverse engineering. That framing and tooling is what made it possible to go from zero to a complete protocol map in a single session.

Go star [their repo](https://github.com/R-D-BioTech-Alaska/Wizpr-Suite).

Licensed MIT. See [LICENSE](LICENSE).
