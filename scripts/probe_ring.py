"""
probe_ring.py — WIZPR Ring characteristic explorer

Connects to WIZPR RING, reads every readable characteristic,
then probes every writable characteristic with a set of test commands
and logs all responses. Saves a full report to ~/.wizprsuite/probe_<timestamp>.json
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

RING_NAME_PREFIX = "WIZPR RING"
OUTPUT_DIR = Path.home() / ".wizprsuite"

# Commands to try on every writable characteristic
PROBE_COMMANDS = [
    "STATUS",
    "PING",
    "VERSION",
    "INFO",
    "MIC_OFF",
    "MIC_ON",
    "RESET",
    "CONFIG",
    "BATTERY",
    "STATE",
    "GET_STATUS",
]


class RingProbe:
    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self.notify_log: list[dict] = []
        self.report: dict = {
            "timestamp": datetime.now().isoformat(),
            "device_name": "",
            "device_address": str(client.address),
            "readable": {},
            "writable_probes": {},
        }

    def _log(self, msg: str) -> None:
        print(msg)

    async def _notify_cb(self, char: BleakGATTCharacteristic, data: bytearray) -> None:
        try:
            text = data.decode("utf-8").strip()
        except Exception:
            text = data.hex()
        entry = {
            "timestamp": datetime.now().isoformat(),
            "uuid": str(char.uuid),
            "hex": data.hex(),
            "text": text,
        }
        self.notify_log.append(entry)
        self._log(f"    ← NOTIFY {str(char.uuid)[-8:]}  {text!r}")

    async def subscribe_all(self) -> None:
        for service in self.client.services:
            for char in service.characteristics:
                if "notify" in char.properties or "indicate" in char.properties:
                    try:
                        await self.client.start_notify(char, self._notify_cb)
                    except Exception as e:
                        self._log(f"  [warn] Could not subscribe {char.uuid}: {e}")

    async def read_all(self) -> None:
        self._log("\n── READING ALL READABLE CHARACTERISTICS ──────────────────")
        for service in self.client.services:
            self._log(f"\nService: {service.uuid}  ({service.description})")
            for char in service.characteristics:
                if "read" in char.properties:
                    try:
                        raw = await self.client.read_gatt_char(char)
                        try:
                            text = raw.decode("utf-8").strip()
                        except Exception:
                            text = None
                        entry = {
                            "description": char.description,
                            "properties": list(char.properties),
                            "hex": raw.hex(),
                            "text": text,
                            "bytes": list(raw),
                        }
                        self.report["readable"][str(char.uuid)] = entry
                        display = text if text and text.isprintable() else raw.hex()
                        self._log(f"  READ  {char.uuid}  ({char.description})")
                        self._log(f"        → {display!r}")
                    except Exception as e:
                        self._log(f"  READ  {char.uuid}  ERROR: {e}")

    async def probe_writable(self) -> None:
        self._log("\n── PROBING WRITABLE CHARACTERISTICS ──────────────────────")
        writable_chars = []
        for service in self.client.services:
            for char in service.characteristics:
                if any(p in char.properties for p in ("write", "write-without-response")):
                    writable_chars.append(char)

        for char in writable_chars:
            self._log(f"\nChar: {char.uuid}  ({char.description})  props={list(char.properties)}")
            self.report["writable_probes"][str(char.uuid)] = {
                "description": char.description,
                "properties": list(char.properties),
                "probes": [],
            }

            for cmd in PROBE_COMMANDS:
                self.notify_log.clear()
                payload = (cmd + "\r\n").encode("utf-8")
                self._log(f"  → WRITE {cmd!r}")
                try:
                    use_response = "write" in char.properties
                    await self.client.write_gatt_char(char, payload, response=use_response)
                    await asyncio.sleep(0.6)  # wait for any response

                    # Also try reading the char if readable
                    read_val = None
                    if "read" in char.properties:
                        try:
                            raw = await self.client.read_gatt_char(char)
                            try:
                                read_val = raw.decode("utf-8").strip()
                            except Exception:
                                read_val = raw.hex()
                            if read_val:
                                self._log(f"    ← READ after write: {read_val!r}")
                        except Exception:
                            pass

                    probe_entry = {
                        "command": cmd,
                        "success": True,
                        "read_response": read_val,
                        "notify_responses": list(self.notify_log),
                    }
                    if self.notify_log:
                        self._log(f"    ← {len(self.notify_log)} notify response(s)")
                except Exception as e:
                    self._log(f"    ✗ {e}")
                    probe_entry = {
                        "command": cmd,
                        "success": False,
                        "error": str(e),
                        "notify_responses": [],
                    }

                self.report["writable_probes"][str(char.uuid)]["probes"].append(probe_entry)

    def save(self) -> Path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        path = OUTPUT_DIR / f"probe_{ts}.json"
        path.write_text(json.dumps(self.report, indent=2))
        return path


async def main() -> None:
    print("Scanning for WIZPR RING...")
    device = None
    found = []

    def _cb(d, adv):
        name = (adv.local_name or d.name or "").strip()
        if name.startswith(RING_NAME_PREFIX):
            found.append(d)

    scanner = BleakScanner(detection_callback=_cb)
    await scanner.start()
    await asyncio.sleep(8.0)
    await scanner.stop()

    if not found:
        print("No WIZPR RING found. Make sure it's disconnected from iPhone.")
        return

    device = found[0]
    print(f"Found: {device.name} ({device.address})")
    print("Connecting...")

    async with BleakClient(device) as client:
        probe = RingProbe(client)
        probe.report["device_name"] = device.name or ""

        print("Subscribing to all notify characteristics...")
        await probe.subscribe_all()

        await probe.read_all()
        await probe.probe_writable()

        path = probe.save()
        print(f"\n✓ Report saved to {path}")
        print("\n── SUMMARY ───────────────────────────────────────────────")
        print(f"  Readable chars:  {len(probe.report['readable'])}")
        print(f"  Writable chars:  {len(probe.report['writable_probes'])}")
        total_probes = sum(len(v['probes']) for v in probe.report['writable_probes'].values())
        successful = sum(
            sum(1 for p in v['probes'] if p['success'])
            for v in probe.report['writable_probes'].values()
        )
        print(f"  Write attempts:  {total_probes} ({successful} accepted)")
        print(f"\nOpen {path} for full results.")


if __name__ == "__main__":
    asyncio.run(main())
