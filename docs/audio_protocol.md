# WIZPR Ring Audio Protocol

Identified 2026-05-03 by decoding captured BLE characteristic `00000001` payloads.

---

## Codec

**IMA ADPCM (Intel/DVI ADPCM), 4-bit**

- Sample rate: **16,000 Hz**
- Channels: **mono**
- Bit depth: 4 bits/sample (ADPCM encoded), decodes to 16-bit PCM
- Frame size: **224 bytes per BLE packet** = 448 samples = **28ms per packet**
- Packet rate: **~35.4 packets/second**
- Encoded bitrate: ~64 kbps
- Decoded audio bandwidth: 0–8 kHz (Nyquist at 16kHz)

**Critical:** ADPCM state (predictor value + step index) is **continuous across packets**. Do NOT reset state between BLE notifications. Each packet continues from where the previous one left off.

---

## Decoding in Python

```python
import audioop

def decode_audio_stream(packets: list[bytes]) -> bytes:
    """
    Decode a sequence of char 00000001 BLE packets to 16-bit PCM.

    packets: list of raw bytes from consecutive BLE notifications
    returns: PCM bytes (16-bit signed LE, 16kHz, mono) ready for wav or playback
    """
    state = (0, 0)  # (predicted_sample, step_index) — carry across packets
    pcm_chunks = []
    for pkt in packets:
        pcm, state = audioop.adpcm2lin(pkt, 2, state)
        pcm_chunks.append(pcm)
    return b"".join(pcm_chunks)
```

**Writing to WAV:**

```python
import wave

def save_wav(pcm: bytes, path: str, rate: int = 16000) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
```

**Real-time decoding (accumulate packets, decode on MIC_OFF):**

```python
class RingAudioDecoder:
    def __init__(self):
        self._state = (0, 0)
        self._chunks: list[bytes] = []

    def reset(self):
        self._state = (0, 0)
        self._chunks = []

    def feed(self, packet: bytes) -> None:
        """Call for each char 00000001 BLE notification while mic is active."""
        pcm, self._state = audioop.adpcm2lin(packet, 2, self._state)
        self._chunks.append(pcm)

    def get_pcm(self) -> bytes:
        """Call on MIC_OFF to retrieve the complete decoded audio."""
        return b"".join(self._chunks)
```

---

## Integration with Ring Events

```
MIC_PRE_ON  →  prepare decoder (call reset())
MIC_ON      →  start feeding char 00000001 packets to decoder
[packets]   →  decoder.feed(packet) for each notification
MIC_OFF     →  pcm = decoder.get_pcm() → transcribe / play / save
```

---

## Identification Method

All 243 audio packets across two voice captures were exactly **224 bytes** — fixed size. This ruled out Opus (variable bitrate). The math for IMA ADPCM at 16kHz: 224 bytes × 2 nibbles/byte = 448 samples ÷ 16000 Hz = **28ms per packet**. At 35.4 pkt/s × 28ms = 0.99 seconds of audio per real second — confirmed.

Tested: μ-law 8kHz, A-law 8kHz, ADPCM reset-per-packet 8kHz/16kHz, ADPCM continuous 8kHz/16kHz, raw PCM 8kHz/16kHz. Only `adpcm_cont_16000` produced intelligible audio.
