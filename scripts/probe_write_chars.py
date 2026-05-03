#!/usr/bin/env python3
"""
probe_write_chars.py — interactive probe campaign for the unmapped write-only
characteristics 00000002, 00000003, 00000004, 00000006.

Walks through a planned sequence of writes one probe at a time. After each
write, captures any notifications received on chars 00000007/00000001/00000005
and asks the user whether they felt, heard, or saw anything. Logs everything
to JSONL for later analysis.

Wear the ring. Manual feedback is the whole point: if a write triggers haptic,
that's the only signal you'll get.

Full plan: docs/explorations/2026-05-write-char-probe-plan.md (local-only).

Usage:
    python scripts/probe_write_chars.py
    python scripts/probe_write_chars.py --char 00000002          # only one char
    python scripts/probe_write_chars.py --skip-ascii-destructive # skip TEST/DIAG/FACTORY
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

SVC = "00000000-dc2e-4362-93d3-df429eb3ad10"


def _char(short: str) -> str:
    return f"{short}-dc2e-4362-93d3-df429eb3ad10"


CMD_CHAR        = _char("00000007")
AUDIO_CHAR      = _char("00000001")
MIC_STATE_CHAR  = _char("00000005")
PROBE_CHARS     = {
    "00000002": _char("00000002"),
    "00000003": _char("00000003"),
    "00000004": _char("00000004"),
    "00000006": _char("00000006"),
}

SINGLE_BYTES = [
    ("0x00",   b"\x00"),
    ("0x01",   b"\x01"),
    ("0xFF",   b"\xff"),
    ("0x55",   b"\x55"),
    ("0xAA",   b"\xaa"),
]

ASCII_SAFE = [
    "HAPTIC", "VIBRATE", "BUZZ", "BEEP", "PULSE", "BLINK",
    "HAPTIC ON", "HAPTIC 100", "VIBRATE 500",
    "LED_ON", "LED_OFF", "LED 1", "LED 0",
    "PING", "WAKE", "SLEEP", "STATUS",
    "PLAY", "STOP",
]

ASCII_DESTRUCTIVE = ["TEST", "DIAG", "FACTORY"]

LENGTH_VARIATIONS = [
    ("len-1-0xFF",   b"\xff" * 1),
    ("len-4-0xFF",   b"\xff" * 4),
    ("len-16-0xFF",  b"\xff" * 16),
    ("len-64-0xFF",  b"\xff" * 64),
    ("len-200-0xFF", b"\xff" * 200),
]

PATTERNS = [
    ("incr-00..0F", bytes(range(16))),
    ("decr-0F..00", bytes(range(15, -1, -1))),
]


def build_sequences(skip_destructive: bool) -> list[tuple[str, bytes]]:
    seq: list[tuple[str, bytes]] = []
    seq += [(f"single-byte {n}", v) for n, v in SINGLE_BYTES]
    ascii_cmds = ASCII_SAFE + ([] if skip_destructive else ASCII_DESTRUCTIVE)
    seq += [(f"ascii {cmd}", (cmd + "\r\n").encode()) for cmd in ascii_cmds]
    seq += [(f"length {n}", v) for n, v in LENGTH_VARIATIONS]
    seq += [(f"pattern {n}", v) for n, v in PATTERNS]
    return seq


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", choices=list(PROBE_CHARS.keys()),
                    help="Probe only this characteristic (default: all four)")
    ap.add_argument("--skip-ascii-destructive", action="store_true", default=True,
                    help="Skip ASCII commands like FACTORY/DIAG/TEST (default: True)")
    ap.add_argument("--include-destructive", action="store_true",
                    help="Include destructive ASCII commands (overrides --skip-ascii-destructive)")
    ap.add_argument("--wait-seconds", type=float, default=2.0,
                    help="Seconds to wait after each write before prompting (default 2.0)")
    args = ap.parse_args()
    skip_destructive = not args.include_destructive

    out_dir = Path("./probe_results")
    out_dir.mkdir(exist_ok=True)
    log_path = out_dir / f"probe-{datetime.now():%Y-%m-%d-%H-%M-%S}.jsonl"

    targets = (
        [(args.char, PROBE_CHARS[args.char])]
        if args.char else list(PROBE_CHARS.items())
    )

    print(f"Logging to: {log_path}")
    print(f"Targets:    {[t[0] for t in targets]}")
    print(f"Destructive ASCII: {'skipped' if skip_destructive else 'INCLUDED'}")
    print("")
    print("Reminders before you start:")
    print("  - Wear the ring")
    print("  - Charge it to 100%")
    print("  - Disconnect from the iPhone Wizpr app")
    print("  - You will be asked after each write whether you felt/heard/saw anything")
    print("  - Anything other than 'n' or empty counts as a hit and gets logged prominently")
    print("")
    input("Ready? Press Enter to scan for the ring...")

    device = await BleakScanner.find_device_by_filter(
        lambda d, _adv: (d.name or "").startswith("WIZPR RING"),
        timeout=10.0,
    )
    if not device:
        print("WIZPR RING not found.")
        sys.exit(1)

    log_f = log_path.open("w")

    def log(record: dict):
        log_f.write(json.dumps(record) + "\n")
        log_f.flush()

    captured: list[dict] = []

    def make_handler(name: str):
        def handler(_h, data: bytearray):
            evt = {
                "ts": datetime.now().isoformat(),
                "char": name,
                "hex": bytes(data).hex(),
                "len": len(data),
            }
            try:
                ascii_value = bytes(data).decode("utf-8", errors="replace").strip("\x00\r\n ")
                if ascii_value and ascii_value.isprintable():
                    evt["ascii"] = ascii_value
            except Exception:
                pass
            captured.append(evt)
            display = evt.get("ascii") or (evt["hex"][:48] + ("..." if len(evt["hex"]) > 48 else ""))
            print(f"  >> {name}: {display}")
        return handler

    print(f"Connecting to {device.name} ({device.address})...")
    async with BleakClient(device) as client:
        await client.start_notify(CMD_CHAR, make_handler("char7"))
        await client.start_notify(AUDIO_CHAR, make_handler("char1"))
        await client.start_notify(MIC_STATE_CHAR, make_handler("char5"))
        log({"event": "connected", "device": device.address, "name": device.name,
             "ts": datetime.now().isoformat()})

        sequences = build_sequences(skip_destructive)

        notable: list[dict] = []

        try:
            for short, char_uuid in targets:
                print(f"\n{'=' * 60}\n=== Probing characteristic {short}\n{'=' * 60}")
                input(f"Press Enter to start the {short} probe sequence...")

                for label, payload in sequences:
                    captured.clear()
                    print(f"\n[{short}] {label} ({len(payload)} bytes, hex={payload.hex()[:32]}{'...' if len(payload.hex())>32 else ''})")
                    input("  Press Enter to send...")

                    t0 = datetime.now()
                    write_error = None
                    try:
                        await client.write_gatt_char(char_uuid, payload, response=False)
                    except Exception as e:
                        write_error = repr(e)
                        print(f"  WRITE FAILED: {write_error}")

                    if write_error is None:
                        await asyncio.sleep(args.wait_seconds)

                    events_seen = list(captured)
                    user = input("  Felt/heard/saw anything? (n / y / notes): ").strip()

                    record = {
                        "ts": t0.isoformat(),
                        "char": short,
                        "probe": label,
                        "payload_hex": payload.hex(),
                        "payload_len": len(payload),
                        "events": events_seen,
                        "user_feedback": user,
                        "write_error": write_error,
                    }
                    log(record)

                    is_hit = (
                        bool(write_error)
                        or len(events_seen) > 0
                        or (user and user.lower() not in ("n", "no", ""))
                    )
                    if is_hit:
                        notable.append(record)
                        print(f"  [!] HIT logged. Total notable: {len(notable)}")

                    # Connection sanity check after potentially-disruptive writes
                    if not client.is_connected:
                        print("  Ring disconnected. Stopping.")
                        log({"event": "disconnected_during_probe", "after_probe": label,
                             "ts": datetime.now().isoformat()})
                        break
                else:
                    continue   # for-else: only triggers if inner loop did not break
                break          # propagate disconnect break to outer loop

            if client.is_connected:
                await client.write_gatt_char(CMD_CHAR, b"LOCK\r\n", response=False)
                print("\nSent LOCK on the way out.")

        except KeyboardInterrupt:
            print("\nInterrupted. Logging what we have.")

    log_f.close()

    print(f"\n{'=' * 60}")
    print(f"Done. Results: {log_path}")
    print(f"Notable probes: {len(notable)}")
    if notable:
        print("\nReview the notable hits with:")
        print(f"  jq 'select(.events | length > 0) // select(.user_feedback | test(\"^[^n]\"; \"i\"))' {log_path}")
        for n in notable[:10]:
            print(f"  - {n['char']} / {n['probe']}: events={len(n['events'])} feedback={n['user_feedback']!r}")
        if len(notable) > 10:
            print(f"  ... and {len(notable) - 10} more")


if __name__ == "__main__":
    asyncio.run(main())
