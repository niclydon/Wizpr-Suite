#!/usr/bin/env python3
"""
analyze_audio.py — codec hypothesis tester for WIZPR RING char1 audio stream.

Usage:
    python scripts/analyze_audio.py <session.json> [--out-dir ./audio_out]

What it does:
  1. Loads a CaptureSession JSON, extracts all char 00000001 payloads.
  2. Reports packet rate, size distribution, and first-byte histogram.
  3. Attempts to decode the audio under multiple codec hypotheses
     (Opus, IMA ADPCM, mu-law, A-law, raw PCM) and writes WAVs for each.
  4. Whichever WAV sounds intelligible is the codec.

Optional dependency:
    pip install opuslib   # for Opus decode attempt

Built-in fallbacks (audioop) handle ADPCM / mu-law / A-law / PCM.
"""
from __future__ import annotations

import argparse
import audioop
import json
import struct
import sys
import wave
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median, pstdev

AUDIO_CHAR_UUID = "00000001-dc2e-4362-93d3-df429eb3ad10"
# Some captures may store the short form. Match either.
SHORT_FORM = "00000001"

OPUS_CONFIG_NAMES = {
    # (config_idx) -> (mode, bandwidth, frame_ms)
    0: ("SILK", "NB",  10), 1: ("SILK", "NB",  20), 2: ("SILK", "NB",  40), 3: ("SILK", "NB",  60),
    4: ("SILK", "MB",  10), 5: ("SILK", "MB",  20), 6: ("SILK", "MB",  40), 7: ("SILK", "MB",  60),
    8: ("SILK", "WB",  10), 9: ("SILK", "WB",  20), 10:("SILK", "WB",  40), 11:("SILK", "WB",  60),
    12:("HYB",  "SWB", 10), 13:("HYB",  "SWB", 20), 14:("HYB",  "FB",  10), 15:("HYB",  "FB",  20),
    16:("CELT", "NB",  2.5),17:("CELT", "NB",   5),18:("CELT", "NB",  10),19:("CELT", "NB",  20),
    20:("CELT", "WB",  2.5),21:("CELT", "WB",   5),22:("CELT", "WB",  10),23:("CELT", "WB",  20),
    24:("CELT", "SWB", 2.5),25:("CELT", "SWB",  5),26:("CELT", "SWB", 10),27:("CELT", "SWB", 20),
    28:("CELT", "FB",  2.5),29:("CELT", "FB",   5),30:("CELT", "FB",  10),31:("CELT", "FB",  20),
}


def load_audio_payloads(session_path: Path):
    """Return list of (action_label, [(ts, bytes), ...]) for each capture with audio."""
    data = json.loads(session_path.read_text())
    out = []
    for cap in data.get("captures", []):
        if cap.get("skipped"):
            continue
        audio_pkts = []
        for p in cap.get("payloads", []):
            uuid = p.get("characteristic_uuid", "").lower()
            if AUDIO_CHAR_UUID in uuid or uuid.startswith(SHORT_FORM):
                ts = datetime.fromisoformat(p["timestamp"])
                payload = bytes(p.get("bytes") or bytes.fromhex(p["hex"]))
                audio_pkts.append((ts, payload))
        if audio_pkts:
            out.append((cap.get("action_label") or cap.get("action_id"), audio_pkts))
    return out


def report_stats(label: str, pkts):
    timestamps = [t for t, _ in pkts]
    sizes = [len(b) for _, b in pkts]
    span = (timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) > 1 else 0
    rate = len(pkts) / span if span > 0 else 0
    intervals_ms = [
        (timestamps[i+1] - timestamps[i]).total_seconds() * 1000
        for i in range(len(timestamps) - 1)
    ]
    first_bytes = Counter(b[0] for _, b in pkts if b)
    # If Opus, decode TOC byte structure
    toc_summary = Counter()
    for byte, count in first_bytes.most_common(10):
        config = byte >> 3
        stereo = (byte >> 2) & 1
        framing = byte & 0x3
        cfg = OPUS_CONFIG_NAMES.get(config, ("?", "?", "?"))
        toc_summary[(byte, config, cfg, stereo, framing)] = count

    print(f"\n=== {label} ===")
    print(f"  packets: {len(pkts)}")
    print(f"  span:    {span:.2f}s")
    print(f"  rate:    {rate:.1f} pkt/s")
    print(f"  payload size: min={min(sizes)} max={max(sizes)} mean={mean(sizes):.1f} median={median(sizes)}")
    print(f"  bitrate (raw):{sum(sizes)*8/span/1000:.1f} kbps" if span else "  bitrate: n/a")
    if intervals_ms:
        print(f"  interval ms:  mean={mean(intervals_ms):.1f} median={median(intervals_ms):.1f} stdev={pstdev(intervals_ms):.1f}")
    print(f"  unique payload sizes: {sorted(set(sizes))[:10]}{'...' if len(set(sizes))>10 else ''}")
    print(f"  top first bytes (Opus TOC interpretation if applicable):")
    for (byte, cfg_idx, cfg, stereo, framing), count in toc_summary.most_common(5):
        mode, bw, ms = cfg
        print(f"    0x{byte:02x}  cfg={cfg_idx:2d} ({mode:4s} {bw:3s} {ms}ms)  stereo={stereo}  frames={framing}  count={count}")


def write_wav(path: Path, samples: bytes, *, sample_rate: int, sample_width: int, channels: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(samples)


def try_opus(label: str, pkts, out_dir: Path):
    try:
        import opuslib
    except ImportError:
        print("  [opus] opuslib not installed — pip install opuslib to enable")
        return
    # Try a few sample rates; SILK NB=8k MB=12k WB=16k
    for sr in (8000, 12000, 16000, 24000, 48000):
        try:
            dec = opuslib.Decoder(sr, 1)
            pcm = bytearray()
            for _, payload in pkts:
                try:
                    pcm += dec.decode(payload, frame_size=int(sr * 0.06), decode_fec=False)
                except Exception:
                    continue
            if len(pcm) > 100:
                out = out_dir / f"{label}__opus_{sr}.wav"
                write_wav(out, bytes(pcm), sample_rate=sr, sample_width=2)
                print(f"  [opus]  wrote {out.name} ({len(pcm)} bytes pcm)")
        except Exception as e:
            print(f"  [opus]  sr={sr} failed: {e}")


def try_ima_adpcm(label: str, pkts, out_dir: Path):
    # IMA ADPCM 4-bit packed; assume 8kHz mono. State is per-stream, reset per packet to be safe.
    try:
        for sr in (8000, 16000):
            state = None
            pcm = bytearray()
            for _, payload in pkts:
                # Most ring ADPCM streams either keep state across packets or reset every packet.
                # Try keeping state — it's the more common encoding choice.
                samples, state = audioop.adpcm2lin(payload, 2, state)
                pcm += samples
            out = out_dir / f"{label}__ima_adpcm_{sr}.wav"
            write_wav(out, bytes(pcm), sample_rate=sr, sample_width=2)
            print(f"  [adpcm] wrote {out.name} ({len(pcm)} bytes pcm)")
    except Exception as e:
        print(f"  [adpcm] failed: {e}")


def try_mulaw(label: str, pkts, out_dir: Path):
    try:
        for sr in (8000, 16000):
            pcm = bytearray()
            for _, payload in pkts:
                pcm += audioop.ulaw2lin(payload, 2)
            out = out_dir / f"{label}__mulaw_{sr}.wav"
            write_wav(out, bytes(pcm), sample_rate=sr, sample_width=2)
            print(f"  [mulaw] wrote {out.name}")
    except Exception as e:
        print(f"  [mulaw] failed: {e}")


def try_alaw(label: str, pkts, out_dir: Path):
    try:
        for sr in (8000, 16000):
            pcm = bytearray()
            for _, payload in pkts:
                pcm += audioop.alaw2lin(payload, 2)
            out = out_dir / f"{label}__alaw_{sr}.wav"
            write_wav(out, bytes(pcm), sample_rate=sr, sample_width=2)
            print(f"  [alaw]  wrote {out.name}")
    except Exception as e:
        print(f"  [alaw] failed: {e}")


def try_raw_pcm(label: str, pkts, out_dir: Path):
    # Both endiannesses, 16-bit, common rates.
    raw = b"".join(p for _, p in pkts)
    for sr in (8000, 16000):
        for tag, data in (("le", raw), ("be", bytes(b ^ 0 for b in raw))):
            # endianness swap on 16-bit pairs
            if tag == "be":
                data = bytes(b for pair in zip(raw[1::2], raw[0::2]) for b in pair)
            out = out_dir / f"{label}__pcm16{tag}_{sr}.wav"
            write_wav(out, data, sample_rate=sr, sample_width=2)
    print(f"  [pcm]   wrote raw PCM variants ({len(raw)} bytes input)")


def sanitize(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_") or "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path, help="Path to session JSON")
    ap.add_argument("--out-dir", type=Path, default=Path("./audio_out"))
    args = ap.parse_args()

    if not args.session.exists():
        print(f"session not found: {args.session}", file=sys.stderr)
        sys.exit(1)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"loading {args.session}")
    audio = load_audio_payloads(args.session)
    if not audio:
        print("No audio payloads (char 00000001) found in this session.")
        sys.exit(0)

    for label, pkts in audio:
        slug = sanitize(label)
        report_stats(label, pkts)
        try_opus(slug, pkts, args.out_dir)
        try_ima_adpcm(slug, pkts, args.out_dir)
        try_mulaw(slug, pkts, args.out_dir)
        try_alaw(slug, pkts, args.out_dir)
        try_raw_pcm(slug, pkts, args.out_dir)

    print(f"\nDone. Outputs in {args.out_dir.resolve()}")
    print("Listen to each — whichever sounds like speech is the codec.")


if __name__ == "__main__":
    main()
