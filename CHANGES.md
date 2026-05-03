# Changes & Decisions

A running log of what changed, why, and what was rejected. Decisions live here so the code stays clean.

---

## 2026-05-02 — Initial fork, setup, first protocol captures

### Forked R-D-BioTech-Alaska/Wizpr-Suite

**Decision:** Fork rather than build from scratch.

The upstream project had already solved the hard problem: figuring out how to connect to the ring over BLE at all. It used `bleak` on Windows/macOS, built a GATT inspector that enumerates services and characteristics, and wired up a PySide6 UI. More importantly, the author had already identified that the ring's protocol is completely undocumented and that the path forward is user-controlled reverse engineering. Starting from that scaffolding instead of from scratch saved at least a day.

The upstream README says: "The ring protocol is not public (and may vary by firmware). This project is built for rapid integration anyway." That framing is exactly right and directly informed the approach taken here.

**What we kept:** BLE layer (`ble_manager.py`, `ring_controller.py`), core event bus and action routing, PySide6 patterns.

**What we replaced:** The entire UI (tabbed LLM control plane → linear guided capture flow), the purpose (general-purpose LLM router → focused protocol discovery tool).

---

### Renamed repo: `Wizpr-Suite` → `wizpr-tools`

**Decision:** Different name to signal different purpose.

The upstream is an app. This is a workshop. `wizpr-tools` makes clear it's a toolbox for exploring and mapping the ring, not a finished product. The iOS app, MCP integrations, and anything else that comes out of this work will be separate repos.

---

### Fixed four missing `@dataclass` decorators

The original code had `class RingProfile`, `class DiscoveredDevice`, `class OpenAIConfig`, `class OllamaConfig`, `class OpenAICompatConfig`, and `class AppConfig` all using dataclass features (`field()`, `asdict()`, etc.) without the `@dataclass` decorator. This caused `TypeError: RingProfile() takes no arguments` on first launch on macOS.

Also fixed: `self.ble.client` was defined as a method but called as a property in `gatt_summary()`, `subscribe()`, and `unsubscribe()`. Changed to `self.ble.client()`.

These were straightforward bugs, not design decisions. Committed as individual fixes so the history is readable.

---

### Built guided capture tool (replaced original UI)

**Decision:** Replace the tabbed LLM control plane with a linear capture flow.

The original UI had tabs for Devices, Models, Chat, Commands, Logs — a full LLM assistant UI. For protocol discovery, none of that was useful. What was needed was: connect, subscribe to everything, walk through labeled actions, save structured JSON.

**The flow:** auto-scan for WIZPR RING → connect → GATT enumerate → subscribe all notify characteristics → guided action prompts (one at a time, 5-second countdown) → JSON output.

**Guided vs. manual labeling:** Chose guided (app tells you what to do) over manual (user types the label). Reason: consistent labeling across sessions, no human error in the label, makes the JSON directly comparable across captures.

**`qasync` for event loop:** PySide6's Qt event loop and Python's asyncio don't share a loop by default. `qasync` bridges them so BLE async callbacks fire correctly while the Qt UI stays responsive. Without it, the BLE scan would block the UI thread.

**Audio freeze bug:** First run of the capture tool froze during voice captures. Root cause: BLE audio stream fires ~24 packets/second, each 200 bytes. The payload list widget was rendering every packet as a 400-character hex string at 24fps — killed the Qt main thread. Fix: audio packets (char `00000001`) are captured silently to JSON, shown only as a single updating counter (`🎙 Audio stream: N packets captured`). ASCII event packets (CLICK, MIC_ON, etc.) still show in the live list.

---

### Action list decisions

**Removed from capture suite:**

- `button_long` (long press) — turns the device off. Found out on first test run. Not a capture-able event.
- `tilt_down` — no signal. Three sessions confirmed zero payloads.
- `wear` / `remove` — no signal. Ring doesn't have proximity or capacitance sensor exposed over BLE.
- `shake` — no signal. The ring's IMU doesn't distinguish shake from other motion at the protocol level.

**Retained:**

- `button_single`, `button_double`, `button_triple` — clear CLICK count signal, fully confirmed.
- `voice_short`, `voice_long` — MIC_ON/MIC_OFF cycle, audio stream on char1.
- `tilt_up` — generates MIC_PRE_ON → MIC_ON. The ring's raise-to-speak gesture.
- `rotate_cw`, `rotate_ccw` — generates MIC cycling, same as tilt. Not a distinct gesture at protocol level, but worth capturing.
- `tap_body` — generates MIC_PRE_ON. Same motion trigger as tilt.
- `idle` — baseline noise capture. Zero events confirmed.

---

### BLE scan filter: WIZPR RING prefix only

**Decision:** Filter scan results to devices whose name starts with `"WIZPR RING"`.

The original app showed all 88+ BLE devices in the neighborhood (AirPods, Govee lights, TVs, neighbors' devices). Once the ring's advertised name was confirmed (`WIZPR RING-97:22`), there was no reason to surface any other device. The UI now shows only WIZPR RING devices.

**How we found the name:** The first several scans failed to find it because the ring was connected to an iPhone and wasn't advertising. Once disconnected from the iPhone, it appeared immediately as `WIZPR RING-97:22`. The `-97:22` suffix is the last two bytes of the ring's Bluetooth MAC address (`28:76:81:FA:97:22` — the `28:76:81` OUI belongs to Silicon Labs).

---

### `ring_daemon.py` — persistent interactive shell

**Decision:** Build a persistent ring connection daemon instead of one-shot scripts.

Early probing required: write a script → push to git → pull on MacBook → launch via osascript → wait → read log. Each round trip was 2–3 minutes. The ring daemon (`scripts/ring_daemon.py`) connects once, subscribes to everything, then reads commands from a named FIFO at `/tmp/ring.cmd` and writes all output to `/tmp/ring.log`. Commands can be sent via `echo "write 7 BATTERY" > /tmp/ring.cmd` from any SSH session.

**Why FIFO not HTTP:** Simplest possible IPC. No dependencies, no port management, no server lifecycle. The FIFO approach means any SSH command can interact with the ring in under 100ms.

**Bluetooth authorization:** Bleak on macOS requires the process to run in a GUI session with Bluetooth permission. Direct SSH processes don't have this permission. Solution: write scripts to `/tmp/*.py` and launch via `osascript` Terminal, then SSH to write to the FIFO and read the log file. Two SSH connections, one GUI process — clean separation.

---

## 2026-05-03 — Protocol mapping complete, btsnoop analysis

### Confirmed command vocabulary via live daemon probing

Probed ~40 ASCII commands against char7. Results:

**Commands with notify responses (confirmed working):**
- `BATTERY` → `BATTERY 87(3.679147)` — percentage + voltage
- `GET_VERSION` → `VER A005` — application firmware version
- `RESET` → ring disconnects — confirmed reboot command

**Commands silently accepted, no response:**
- `MIC_ON`, `MIC_OFF`, `LED_ON`, `LED_OFF`, `HAPTIC`, `VIBRATE`, `BEEP`, `STATUS`, `INFO`, `WAKE`, `GYRO`, `ACC`, `TEMP`, `GET_STATE`, dozens more

**Why RESET is significant:** Every other unknown command was silently absorbed. RESET actually rebooted the ring. This confirms char7 is a live command channel, not just a logging buffer. The ring processes writes — it just has a very small vocabulary.

**The echo buffer:** Char7 is readable. Reading it after a write returns the last written value zero-padded to 250 bytes. This is not a response channel — it's a write buffer. Confirmed by observing contamination: reading after `STATUS` showed `STATUS\r\nERY` because `BATTERY` was in the buffer from a previous write and the null-padding didn't fully clear.

---

### btsnoop analysis — iOS app only sends `LOCK`

Captured BLE traffic from the official iOS Wizpr app using Apple PacketLogger with a Bluetooth logging profile installed on iPhone 16 Pro.

**Setup friction:** PacketLogger initially showed nothing because it needs an Apple Bluetooth diagnostic profile installed on the iPhone to actually capture traffic. Without the profile, it shows the device name but captures zero packets. Profile installed from `developer.apple.com/bug-reporting/profiles-and-logs/`.

**File format:** PacketLogger exported as `.btsnoop` but the file is actually Apple's native PacketLogger format (magic bytes differ from standard btsnoop). Wrote a custom parser that reads the `length (4 LE) + timestamp (8 LE) + type (1) + payload` record structure.

**Result:** 7,113 records, 202 ACL TX packets, but only **2 TX packets to the ring's connection handle (0x403)**. Both were ATT WRITE_REQ to handle `0x0029` (char7) with value `LOCK\r\n`.

**What LOCK does:** Sent by the iOS app when the session ends (observed twice in a capture session). Presumably disables ring input — mic, motion, button — until the next connection or wake event.

**Implication:** The iOS app is almost entirely a listener. It subscribes to char7 and char1, handles events, streams audio — and only writes back when closing out a session. The ring is self-contained. This is excellent news for building a custom iOS app: there's no complex command handshake, no session initialization sequence, no auth. Connect, subscribe, listen, send LOCK when done.

---

### Device identity confirmed

From the Device Information service (standard BLE `0x180A`):

| Characteristic | Value |
|---|---|
| Manufacturer Name | Silicon Labs |
| Firmware Revision | 9.0.0 (BLE stack) |
| System ID | `287681fffefa9722` |

System ID is IEEE EUI-64 format. Remove the `fffffe` middle bytes: MAC = `28:76:81:FA:97:22`. OUI `28:76:81` = Silicon Labs. Last two bytes `97:22` match the advertised name suffix `WIZPR RING-97:22`. Confirmed.

Application firmware version (from `GET_VERSION` command): `VER A005`.

---

### Chars 2, 3, 4, 6 — write-only, purpose unknown

Five write-only characteristics on the ring's custom service (`00000000-dc2e-4362-93d3-df429eb3ad10`):

- `00000002` — Unknown
- `00000003` — Description says "RFCOMM" (repurposed UUID, not actual RFCOMM)
- `00000004` — Unknown
- `00000006` — Unknown

Probed with: ASCII strings (all known commands), single bytes `0x00`, `0x01`, `0xff`, `0xaa`, `0x55`, two-byte patterns. Zero notify responses to anything. No physical effects observed.

**Current hypothesis:** These may be audio configuration or stream control channels that require a specific binary framing the iOS app uses internally but never exposed in the capture session. Alternatively, they may be unused vestiges in the firmware. Not blocking for iOS app development since the audio stream (char1) works fine without touching them.

**What was not tried:** Binary framing with length prefixes, checksum-protected packets, or multi-packet sequences. If these ever need to be reverse-engineered further, a longer btsnoop capture where the iOS app is exercised more heavily would be the next step.

---

### `f7bf3564` (service `1d14d6ee`) — not probed

The third GATT service has one write-only characteristic (`f7bf3564-fb6d-4e53-88a4-5e37e0326063`). All probe attempts after `RESET` failed because the ring had disconnected. In the btsnoop capture, zero writes to this handle were observed from the iOS app. Likely OTA update or factory config channel. Not needed for the iOS app.
