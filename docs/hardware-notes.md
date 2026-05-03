# Hardware & usage notes

Things about the WIZPR Ring you only learn by using it. Observations from one ring (firmware `VER A005`, BLE stack `9.0.0`, advertised as `WIZPR RING-97:22`) over a few days of capture sessions and probing. Treat as one data point, not gospel.

---

## Connection model

**One client at a time.** The ring accepts exactly one active BLE connection. While connected to one device, it does not advertise and is invisible to scans from other devices. To switch from iPhone to Mac (or vice versa), you have to disconnect the current client first - either close the official Wizpr iOS app, or turn off Bluetooth on the iPhone.

**No bonding, no pairing.** The ring does not require a pairing handshake. Any client can connect, subscribe to characteristics, and start exchanging data immediately. There is no authentication. If you can see it, you can talk to it.

**One connection at a time means the iOS app blocks you.** During development, this was the single biggest source of "why isn't my code working" - the ring is paired to the official iOS app by default and will not show up in macOS scans until that connection is dropped. Toggle Bluetooth off and on on the iPhone if you need a clean state quickly.

---

## Battery and charging

Observed values from `BATTERY` queries: `BATTERY 87(3.679147)` format - percentage, then voltage in volts. Voltage drops slightly between consecutive queries (3.679 -> 3.677 -> 3.676), which is consistent with real cell behavior. The percentage appears to track linearly with voltage rather than being a true coulomb count, so expect the usual lithium-ion gauge wobble (sits at 100% for a while, then drops faster near the end).

Charging dock is the small puck included in the package. The ring sits on the dock; charging is contact-based, not induction. Took ~90 minutes to charge from ~20% to 100% in observed sessions.

**Battery life under heavy use** (many sessions, daemon held open for hours): ~6-8 hours per charge. Standby (worn but idle) is much longer - multiple days. Heavy BLE notification rates and frequent mic activations are the dominant drain.

---

## Gestures and physical interaction

**Button** is a small clickable cap on the ring face. Tactile click, easy to press while wearing on index finger using the thumb. Single, double, and triple presses are all distinguishable; quadruple-press has not been observed (the ring may cap at three).

**Long press / hold** triggers a power-related sequence - confirmed during early probing that holding the button turns the ring off (it disconnects and stops advertising). This is why `button_long_press` was removed from the capture action list. Avoid teaching users a long-press gesture; it conflicts with the power button.

**Raise-to-speak** is motion-triggered. The ring has an IMU; any sustained motion above a threshold fires `MIC_PRE_ON` and then `MIC_ON`. "Raise to face" is the canonical trigger but rotation, tapping the ring body, and other firm motions can also trip it. The threshold is generous - you do not need to pantomime a phone call; lifting your hand from a desk to a normal speaking position is enough.

**Wear orientation matters less than you'd expect.** The IMU appears to detect the gesture as a relative motion event, not an absolute orientation. Wearing the ring on your right hand vs left, or with the button facing palm-up vs palm-down, doesn't break gesture detection.

**Output channels: one LED, no haptic, no audio output.** The ring has a single purple (RGB) LED visible on the body. It fires briefly on every BLE connect as a connection-acknowledgment indicator. It is not controllable from any GATT characteristic we have tested (134+ probes across the four unmapped write-only chars `00000002`, `00000003`, `00000004`, `00000006`, plus the documented chars). The LED behavior appears to be hardwired into the chip's BLE stack at firmware level, not exposed at the application layer.

No haptic motor or vibration was detected during any probe. No audible tone or speaker was detected. The ring is effectively input-only from a programmatic perspective.

**Methodology note:** an earlier version of this doc claimed "no LED visible" based on a single wearing session. That was wrong. The LED is small and brief; missing it on a single observation was easy. The correction came from running `scripts/probe_led_isolate.py`, which walks each step of the BLE connect+subscribe sequence with prompts and isolated the LED to the connect step specifically. Negative claims about hardware features deserve more than one observation - a lesson that's also called out in `audio_protocol.md`'s identification method section, where the audio codec was identified by measuring invariants (fixed packet size) rather than relying on a single guess.

---

## BLE range

Reliable to ~10 meters line-of-sight from a 2024-era MacBook Pro. Drops connection through one interior wall at ~5 meters. This is normal Bluetooth LE behavior; the ring's antenna is small and the host's antenna placement is the bigger variable. Do not expect it to work from another room.

---

## macOS Bluetooth permission gotcha

Processes launched over SSH do not inherit Bluetooth permission on macOS. The system requires the process to be running inside an active GUI session for `CoreBluetooth` to grant access. If you SSH into your Mac and run `python -m wizpr-suite.app.main`, scanning will return zero devices forever even if the ring is right there.

Workarounds:

- Run from a Terminal window inside an active login session on the Mac itself.
- Launch via `osascript` from SSH (opens a real Terminal window owned by your GUI session).
- The ring daemon (`scripts/ring_daemon.py`) uses this trick: it must be started from a GUI session, but once running, any SSH client can talk to it through the FIFO at `/tmp/ring.cmd`.

This is not a wizpr-suite bug. It applies to any BLE program on macOS.

---

## Capturing iOS app traffic with PacketLogger

If you want to see what the official iOS app is actually sending, Apple's PacketLogger tool (ships with Additional Tools for Xcode) captures HCI traffic from a connected iPhone over USB. Without configuration, PacketLogger will show the iPhone but capture zero traffic.

**You need a Bluetooth diagnostic profile installed on the iPhone:**

1. On the iPhone: visit `developer.apple.com/bug-reporting/profiles-and-logs/` in Safari
2. Install the "Bluetooth" profile (Settings -> General -> VPN & Device Management)
3. Reboot the phone
4. Connect by USB to the Mac, open PacketLogger, traffic now flows

Without the profile, the kernel logging hook is not active and PacketLogger captures nothing. This is by design and is not documented well.

**Output format:** PacketLogger's "btsnoop" export is *Apple's native format*, not the standard btsnoop format. Magic bytes are `1c0000002f6ff669` rather than `btsnoop\0`. The records are `uint32_le length + uint64_le timestamp + uint8 type + payload`. Types: 0 = HCI command, 1 = HCI event, 2 = ACL TX (host -> controller), 3 = ACL RX (controller -> host), 252 = text metadata. Standard btsnoop parsers will choke on this; you'll need a custom parser or PacketLogger's own re-export feature.

---

## Things to know that aren't really gotchas

- The advertised name suffix `-97:22` is the last two bytes of the BLE MAC. If you have multiple rings, this gives them stable distinguishable names without needing to read the address. Useful for filter logic.
- Reading char7 returns the last value *written* to it, zero-padded to 250 bytes. It's a write echo register, not a response register. If you want responses to commands, subscribe to char7 notifications - reads will not give you what you want.
- The ring's hardware revision and model number characteristics in the standard Device Information service (`0000180a`) return null. Only the firmware revision and System ID are populated. Do not rely on those fields for device identification.
