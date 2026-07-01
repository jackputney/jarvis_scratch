# STT Streaming Decision — Build vs Buy (O2)

**Status:** Decision doc · **no implementation**  
**Authors:** Oliver (draft) · **Jack sign-off required**  
**Date:** 2026-07-01  
**Gate:** Do **not** build streaming STT until this doc is reviewed **and** Jack supplies local WER numbers on Oliver's phone-audio corpus.

---

## Executive recommendation

| Lane | Recommendation | Rationale |
|------|----------------|-----------|
| **Desktop mic** (orb, hotkey, wake word) | **Keep local batch** (`large-v3-turbo` / faster-whisper) | End-of-utterance latency is dominated by **VAD trailing silence** (`vad_silence_ms` ≈ 1400 ms), not batch STT. Local turbo on CPU is typically sub-second for short turns. Zero marginal cost; no PHI egress. |
| **Twilio phone** (`twilio_server.py`) | **Conditional buy — lean Deepgram Flux** after WER gate | Telephony (8 kHz μ-law → 16 kHz upsample) is the accuracy and latency pain point. Flux's integrated end-of-turn (EOT) can replace **both** the silence tail and batch transcribe step, targeting **~260 ms EOT** vs **~1.4 s+ today**. **Only adopt if** Jack's phone WER on Flux/Scribe beats local turbo by a agreed margin **or** perceived turn latency fails user testing. |
| **Future clinical / PHI** | **Local batch only** unless Enterprise BAA + zero-retention cloud is procured | Any streaming cloud STT sends audio off-box → BAA required before PHI. Default posture: local STT for sensitive lanes. |

**Bottom line:** Don't rip out Whisper. Add an **optional third `STTBackend`** for phone (and later desktop) **only after** measured WER on real Oliver phone calls. Spike order: **Deepgram Flux** (EOT-native, phone-shaped) → **ElevenLabs Scribe v2 Realtime** (vendor consolidation with existing TTS).

---

## Problem — batch vs streaming tension

Both audits flagged the same structural issue: Jarvis STT is **batch-after-VAD**, not streaming.

```
User speaks → VAD accumulates frames → trailing silence detected → full utterance buffer
           → batch transcribe (Whisper) → text → LLM → TTS
```

Whisper (mlx-whisper / faster-whisper) never sees partial audio. Latency is paid **after** the user finishes speaking, in two chunks:

1. **Silence tail** — wait `vad_silence_ms` (default **1400 ms**) of non-speech before `_finish()`.
2. **Batch inference** — transcribe the entire PCM buffer (local turbo: ~**200–1500 ms** for typical 3–10 s utterances on CPU, hardware-dependent).

Streaming engines emit **partial** transcripts during speech and **finalize** soon after speech ends (vendor-claimed **150–400 ms**), and Flux adds **model-integrated EOT** so the silence tail can shrink or disappear.

---

## Current architecture (integration baseline)

### Desktop / orb path

| Step | Location | Notes |
|------|----------|-------|
| Capture + VAD | `adapters/audio_io.py` — `_record_from_queue`, `frame_is_speech` | 16 kHz PCM, webrtcvad + energy fallback |
| Utterance assembly | `pipeline._capture_and_transcribe` | Honors `vad_silence_ms`, `vad_min_capture_ms` |
| Batch STT | `pipeline._transcribe` → `adapters/stt.transcribe` | `effective_stt_model()` → `large-v3-turbo` default |
| Warmup (off hot path) | `pipeline.warmup_stt` → `adapters/stt.warmup` | Model load at startup, not per turn |

### Phone path

| Step | Location | Notes |
|------|----------|-------|
| μ-law ingest | `twilio_server.PhoneCallSession.handle_message` (`event == "media"`) | Twilio Media Streams WebSocket |
| VAD + utterance | `adapters/twilio_call.MulawUtteranceDetector.feed` | Same `vad_silence_ms` / `vad_min_capture_ms` from `Config`; 8 kHz μ-law → 16 kHz PCM via `mulaw_to_pcm` |
| Turn handler | `twilio_server.PhoneCallSession._handle_utterance` (~line 133) | `asyncio.to_thread(transcribe_utterance, …)` under `_turn_lock` |
| Batch STT | `adapters/twilio_call.transcribe_utterance` → `pipeline._transcribe` | Reuses desktop STT stack on telephony audio |

**Implication:** A streaming backend is not a drop-in swap inside `_transcribe` alone. It requires a **long-lived WebSocket** per call, **chunked feed** from media frames, and a different **turn boundary** signal (provider EOT vs local VAD `_finish()`).

---

## Options evaluated

### A — Local batch (baseline): faster-whisper `large-v3-turbo`

| Attribute | Value |
|-----------|-------|
| Deployed | ✅ Yes (Oliver Windows default after recent upgrade) |
| Model | `large-v3-turbo` (Systran CT2; CUDA float16 / CPU int8) |
| Interface | Batch `transcribe(audio_np, …)` |
| Cost | **$0** marginal (GPU/CPU amortized) |
| PHI | Stays on machine |

### B — Deepgram Flux (streaming + integrated EOT)

| Attribute | Value |
|-----------|-------|
| Model | Conversational STT; Nova-3-class accuracy (vendor) |
| API | WebSocket `/v2/listen`; **80 ms audio chunks** recommended |
| Latency (vendor) | Transcription **150–300 ms**; median EOT **~260 ms**; `EagerEndOfTurn` for early LLM prep |
| EOT | Replaces external VAD pipeline (vendor positioning) |
| Pricing (Pay-as-you-go, Jul 2026) | **$0.0065/min** English Flux (~**$0.39/hr**); Multilingual **$0.0078/min** |
| PHI | Off-box; BAA available (org-level HIPAA config); `redact=phi` on streaming |

### C — ElevenLabs Scribe v2 Realtime

| Attribute | Value |
|-----------|-------|
| Model | `scribe_v2_realtime` |
| API | WebSocket realtime STT; partial + committed transcripts; VAD auto-commit or manual `commit()` |
| Latency (vendor) | **~150 ms** end-to-end (excludes app/network) |
| Pricing (API, Jul 2026) | **$0.39/hr** (~**$0.0065/min**) |
| PHI | Off-box; BAA **Enterprise only** + Zero Retention Mode |
| Synergy | Jarvis already uses ElevenLabs TTS (`tts/elevenlabs.py`) — single vendor for phone audio stack |

### D — Local streaming Whisper (not evaluated for build)

Community patterns (`whisper_streaming`, WhisperLive) still sit on batch Whisper windows; typical **500–800 ms** partial latency. Doesn't solve EOT as cleanly as Flux. **Out of scope** unless cloud is rejected on cost/compliance and measured local batch is still too slow (unlikely on turbo).

---

## Dimension 1 — Real latency

### How to measure (apples-to-apples)

| Metric | Definition | Matters for |
|--------|------------|-------------|
| **TTFT** (time to first partial token) | First partial transcript after speech onset | Live captions, barge-in UX |
| **Finalize latency** | Speech end → stable final transcript | Turn-taking, LLM trigger |
| **EOT latency** | Speech end → "user done" signal | Phone + voice agents |

Jarvis today only uses **finalize** (no partials). Phone turn latency ≈ **silence tail + batch STT + thread hop**.

### Modeled latency budget (typical 5 s utterance)

| Stage | Local batch (today) | Deepgram Flux | ElevenLabs Scribe v2 RT |
|-------|-------------------|---------------|-------------------------|
| Trailing silence / EOT | **1400 ms** (`vad_silence_ms`) | **~260 ms** EOT (vendor median); tunable `eot_threshold` | VAD commit (~similar order; vendor claims ~150 ms finalize **after** commit) |
| Transcribe / finalize | **300–800 ms** (CPU int8 turbo, 5 s audio, warm model) | Included in EOT stream (partial during speech) | **~150 ms** after commit (vendor) |
| App overhead | ~10–50 ms (`to_thread`) | WS send + parse (~20–80 ms) | WS send + parse (~20–80 ms) |
| Network (phone) | 0 (local) | **+30–100 ms** RTT to Deepgram | **+30–100 ms** RTT to ElevenLabs |
| **Total (speech end → text)** | **~1.7–2.3 s** | **~0.35–0.55 s** (est.) | **~0.35–0.55 s** (est.) |

**Desktop:** Even with streaming, if we **keep** `vad_silence_ms` at 1400 ms and only swap the transcribe step, savings are **~300–800 ms** — modest. To win on desktop, we'd need to **shorten or bypass** local VAD tail using provider EOT (behavior change).

**Phone:** Savings are **~1.0–1.5 s per turn** — user-perceptible on a call.

> **Numbers status:** Latency rows for Flux/Scribe are **vendor + architecture model**, not Jarvis benchmarks. Required spike: record 20 phone turns, measure `speech_end → transcript` with existing `stt_ms` trace + parallel cloud WS.

---

## Dimension 2 — WER / accuracy

### Published benchmarks (not Oliver's phone audio)

| Engine | WER proxy | Source | Caveat |
|--------|-----------|--------|--------|
| faster-whisper `large-v3-turbo` | **~7.7%** (batched GPU, clean EN test set) | [SYSTRAN #1030](https://github.com/SYSTRAN/faster-whisper/issues/1030) | Clean audio; not 8 kHz telephony |
| faster-whisper `large-v3-turbo` | **~9.5%** (non-batched) | Same | |
| ElevenLabs Scribe v2 RT | **~6.5%** implied (93.5% accuracy claim) | ElevenLabs marketing / FLEURS | Vendor benchmark; 30-language subset |
| Deepgram Flux / Nova-3 | Competitive with Whisper large (vendor) | Deepgram docs, Coval 2026 roundup | No public Oliver-phone corpus |

### Oliver phone audio — **missing data (blocker)**

Telephony path degrades accuracy:

- **8 kHz μ-law** bandwidth → lost fricatives / consonants
- **GSM artifacts**, room noise, mobile mic
- **Upsample 8→16 kHz** (`adapters/twilio_audio.mulaw_to_pcm`) does not restore lost information

| Corpus | Owner | Status |
|--------|-------|--------|
| ≥50 labeled phone utterances (PCM + reference transcript) | Jack | **Required before build** |
| Side-by-side: local turbo vs Flux vs Scribe v2 RT | Jack | **Required before build** |
| Desktop mic corpus (optional) | Jack | Nice-to-have; batch likely sufficient |

**Acceptance proposal (tunable):**

- Phone: cloud streaming **only if** WER ≤ local turbo **or** ≤ local + **2% absolute** *and* finalize latency p50 **< 600 ms** on corpus.
- If local turbo WER ≤ cloud on phone audio, **stay local** despite latency gap (accuracy wins for names, tools, clinical terms).

---

## Dimension 3 — Cost per minute

### Vendor list rates (Jul 2026, pay-as-you-go)

| Provider | $/min | $/hr | Notes |
|----------|-------|------|-------|
| Deepgram Flux (EN) | $0.0065 | $0.39 | Streaming; EOT included |
| ElevenLabs Scribe v2 Realtime | $0.0065 | $0.39 | Same order of magnitude |
| Local faster-whisper | $0 | $0 | Electricity + hardware only |

### Monthly estimates (STT audio minutes, not wall-clock call time)

Assume **active speech ≈ 40%** of call duration (rest is Jarvis TTS + thinking).

| Use case | Speech min/mo | Flux / Scribe cost | Local cost |
|----------|---------------|-------------------|------------|
| Light phone (30 min calls) | ~12 min | **~$0.08** | $0 |
| Regular phone (2 hr calls) | ~48 min | **~$0.31** | $0 |
| Heavy phone (10 hr calls) | ~240 min | **~$1.56** | $0 |
| Desktop STT (5 hr/mo mic) | 300 min | **~$1.95** if cloud | $0 |

**Conclusion:** At Jarvis's expected personal volume, **cloud STT cost is negligible** vs LLM + TTS spend. Cost is **not** the deciding factor unless volume reaches contact-center scale (1000+ min/mo → **~$6.50+/mo** still modest).

**Billing nuance:** Streaming APIs often bill on **audio sent**, including silence if streamed continuously. Architecture should **not** forward mute frames blindly — feed only speech segments or use provider VAD.

---

## Dimension 4 — Fully local vs cloud + BAA (PHI)

| Concern | Local batch Whisper | Cloud streaming (Flux / Scribe) |
|---------|---------------------|----------------------------------|
| Audio egress | None | Every utterance leaves the box |
| HIPAA / PHI | Compatible with on-prem posture | **BAA required** before any PHI |
| Deepgram | N/A | BAA on request; HIPAA-eligible org + keys; optional self-hosted / VPC |
| ElevenLabs | N/A | BAA **Enterprise**; Zero Retention Mode; LLM allowlist restrictions |
| Default Jarvis (personal assistant) | No BAA friction | Fine for non-PHI |
| Future clinical workflows | **Preferred default** | Viable only after legal + Enterprise procurement |

**Tradeoff framing:**

- **Privacy-first / air-gap:** local batch only.
- **Phone UX-first (non-PHI):** cloud streaming acceptable with API key in `.env`.
- **Clinical:** treat cloud STT as **blocked** until BAA executed; even then, prefer local STT for transcription of record, cloud only for non-recorded UX prototypes.

**Important:** Jarvis already sends **text** to cloud LLMs. Adding cloud STT increases **raw voice** exposure (biometric-adjacent signal, harder to redact). Document in threat model if enabled.

---

## Comparative summary

| Dimension | Local batch turbo | Deepgram Flux | ElevenLabs Scribe v2 RT |
|-----------|-------------------|---------------|-------------------------|
| End-of-turn latency (phone) | **Poor** (~1.7–2.3 s) | **Best fit** (integrated EOT) | **Good** (VAD commit) |
| End-of-turn latency (desktop) | **Moderate** (VAD-bound) | Good if VAD replaced | Good if VAD replaced |
| WER on phone | **TBD — Jack** | **TBD — Jack** | **TBD — Jack** |
| Cost at Jarvis volume | **$0** | **< $2/mo** typical | **< $2/mo** typical |
| PHI / clinical | **✅ On-box** | BAA + HIPAA org setup | Enterprise BAA + ZRM |
| Integration effort | Done | Medium (WS + EOT) | Medium (WS + commit) |
| Vendor fit | mlx + faster-whisper | New vendor | **Already on ElevenLabs TTS** |
| Offline | ✅ | ❌ | ❌ |

---

## Where streaming plugs in (future design sketch — not built)

### 1. Third `STTBackend` in `adapters/stt.py`

```text
STTBackend (Protocol)
├── MlxWhisperBackend          # batch — macOS
├── FasterWhisperBackend       # batch — Windows/Linux
└── StreamingSTTBackend        # NEW — WebSocket, chunked feed
    ├── DeepgramFluxBackend
    └── ElevenLabsScribeRealtimeBackend
```

New protocol methods (conceptual):

- `open_stream(config) → StreamHandle`
- `feed_audio(pcm_chunk: bytes) → None`
- `on_partial(callback)` / `on_final(callback)` / `on_eot(callback)`
- `close_stream() → None`

`transcribe(batch)` remains for desktop backward compatibility.

Config levers (proposed):

```json
{
  "stt_backend": "faster",
  "stt_phone_backend": "deepgram_flux",
  "stt_streaming_eot_threshold": 0.7
}
```

### 2. `MulawUtteranceDetector` — reshape or bypass

**Today:** accumulates frames → returns one PCM blob on silence.

**Streaming path options:**

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **B1 — Bypass** | Feed each 20–80 ms PCM chunk directly to WS; delete local `_finish()` for phone | Lowest latency; Flux EOT | Biggest refactor; lose local VAD tuning |
| **B2 — Hybrid** | Keep detector for pre-roll / barge-in; stream `_frames` incrementally; EOT from provider | Safer migration | Risk of double-EOT if both fire |
| **B3 — Phone-only streaming** | Desktop unchanged | Scoped spike | Two behaviors to maintain |

**Recommendation:** **B3 + B1 on phone** — `PhoneCallSession` owns a per-call streaming session; `MulawUtteranceDetector` retired or reduced to pre-roll only.

### 3. `PhoneCallSession._handle_utterance` (`twilio_server.py` ~133)

**Today:**

```text
utterance_pcm = detector.feed(mulaw)   # batch blob
→ create_task(_handle_utterance(pcm))
→ to_thread(transcribe_utterance)      # batch STT
→ to_thread(run_phone_turn)
→ _speak
```

**Streaming:**

```text
on media: stream_session.feed(pcm_chunk)   # every frame
on provider EOT/final: _handle_utterance(text)   # text, not bytes
→ run_phone_turn (no STT thread)
→ _speak
```

`_turn_lock` stays. **Remove** `asyncio.to_thread(transcribe_utterance)` from hot path.

### 4. Desktop `pipeline._transcribe`

Leave batch unless we adopt EOT globally. Optional phase 2: streaming for follow-up window only.

---

## Spike plan (pre-build, ~1–2 days)

1. **Corpus** — Jack exports 50+ phone utterances (PCM 16 kHz + reference text) from Twilio test calls.
2. **WER script** — offline: run local turbo, Flux batch (baseline), Flux stream, Scribe RT on same files; compute WER (normalized).
3. **Latency script** — inject recorded μ-law through `MulawUtteranceDetector` vs streaming WS; histogram `speech_end → final text`.
4. **Cost check** — 1 hr test call → compare Deepgram vs ElevenLabs dashboard meters.
5. **Decision meeting** — fill § "Decision record" below; Jack signs.

---

## Decision record (to complete)

| Question | Answer | Date | By |
|----------|--------|------|-----|
| Local turbo WER on phone corpus | _pending_ | | Jack |
| Flux WER on same corpus | _pending_ | | Jack |
| Scribe v2 RT WER on same corpus | _pending_ | | Jack |
| p50/p95 finalize latency (local vs cloud) | _pending_ | | Jack |
| Clinical / PHI path in next 6 mo? | _pending_ | | Jack + Oliver |
| **Go / no-go streaming build** | _pending_ | | Jack |

### If GO

- [ ] Vendor: Deepgram Flux **or** ElevenLabs Scribe v2 RT (justify in row above)
- [ ] Scope: phone-only v1
- [ ] Config: `stt_phone_backend` + API key in `.env`
- [ ] Fallback: local batch if WS drops

### If NO-GO

- [ ] Tune `vad_silence_ms` / `followup_vad_silence_ms` for phone profile
- [ ] Consider GPU / CUDA for Oliver desktop if `stt_ms` traces high
- [ ] Revisit when call volume or clinical requirements change

---

## References

- `adapters/stt.py` — `STTBackend`, `FasterWhisperBackend`, `MlxWhisperBackend`
- `pipeline._transcribe`, `pipeline._capture_and_transcribe`, `pipeline.warmup_stt`
- `adapters/twilio_call.py` — `MulawUtteranceDetector`, `transcribe_utterance`
- `twilio_server.py` — `PhoneCallSession._handle_utterance`
- [Deepgram Flux quickstart](https://developers.deepgram.com/docs/flux/quickstart)
- [Deepgram measuring streaming latency](https://developers.deepgram.com/docs/measuring-streaming-latency)
- [Deepgram pricing](https://deepgram.com/pricing)
- [ElevenLabs Scribe v2 Realtime](https://elevenlabs.io/realtime-speech-to-text)
- [ElevenLabs API pricing](https://elevenlabs.io/pricing/api)
- [faster-whisper large-v3-turbo benchmarks](https://github.com/SYSTRAN/faster-whisper/issues/1030)
