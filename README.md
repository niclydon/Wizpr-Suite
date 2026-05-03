# wizpr-tools

**A reverse-engineering and protocol exploration toolkit for the WIZPR Ring.**

This repo is a workshop — a place to map what the ring actually does over BLE, capture its signals, decode its protocol, and build the understanding needed to create real applications on top of it. Once the protocol is mapped, the actual apps (iOS client, MCP integrations, AI tooling) will live in their own separate repos.

---

## What's here

### Capture Tool (`wizpr-suite/`)
A macOS desktop app (PySide6) that:
- Scans for and connects to the WIZPR RING over BLE
- Subscribes to all notify characteristics simultaneously
- Walks through a guided capture session — one labeled action at a time (button press, voice, gesture)
- Saves a structured JSON session file with every raw BLE payload, timestamped and labeled
- Includes a live **Command Explorer** for writing commands back to the ring and watching responses

### What we've found so far

The ring communicates over a custom GATT service (`00000000-dc2e-4362-93d3-df429eb3ad10`) with three active characteristics:

| Characteristic | Direction | What it carries |
|---|---|---|
| `00000007` | read / write / notify | ASCII command strings (`CLICK`, `MIC_ON`, `MIC_OFF`, `MIC_PRE_ON`) |
| `00000005` | notify | Mic state bit (`31` = on, `30` = off) |
| `00000001` | indicate / notify | Raw audio stream (binary, ~24 packets/sec) |

**Mapped events so far:**

```
CLICK          → button pressed once
CLICK CLICK    → button double-press
CLICK CLICK CLICK → button triple-press
MIC_PRE_ON     → raise-to-speak gesture detected (pre-activation)
MIC_ON         → microphone active, audio streaming on char 00000001
MIC_OFF        → microphone deactivated
```

Four write-only characteristics (`00000002`, `00000003`, `00000004`, `00000006`) remain unexplored — these are likely the command channel from app → ring.

---

## Running it

```bash
# Requires Python 3.10+, macOS (CoreBluetooth via bleak)
git clone https://github.com/niclydon/wizpr-tools.git
cd wizpr-tools
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m wizpr-suite.app.main
```

Disconnect the ring from your iPhone before scanning. The ring only advertises when not already connected.

---

## Roadmap

- [ ] Decode audio stream format (codec, sample rate, bit depth)
- [ ] Map write-only characteristics — discover what commands the app sends to the ring
- [ ] Build protocol reference doc from captured sessions
- [ ] iOS app (separate repo)
- [ ] MCP tools / AI integrations (separate repo)

---

## Built on the shoulders of

This repo is a fork of [R-D-BioTech-Alaska/Wizpr-Suite](https://github.com/R-D-BioTech-Alaska/Wizpr-Suite) and none of this work would have been possible without it.

The original project did the genuinely hard parts: figuring out how to connect to the ring over BLE at all, building the GATT inspector to enumerate services and characteristics, wiring up bleak on Windows/macOS, scaffolding the PySide6 UI, and — critically — recognizing that the ring's protocol is undocumented and that the path forward is user-controlled reverse engineering. That framing and that tooling is what made it possible to go from zero to capturing real ring data in a single session.

What this fork adds is a different lens: instead of a general-purpose LLM control plane, this is a focused protocol discovery tool — automated guided capture sessions, structured JSON output for analysis, a command explorer for probing the write characteristics, and the groundwork for building a custom iOS client once the protocol is fully mapped.

Full credit and respect to the original authors. Go star [their repo](https://github.com/R-D-BioTech-Alaska/Wizpr-Suite).

Licensed MIT. See [LICENSE](LICENSE).
