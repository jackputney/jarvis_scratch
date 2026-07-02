# Jarvis — Demo Plan (scope freeze)

**Goal:** the simplest version of Jarvis that demos impressively, finished ASAP. It needs to
survive a ~5-minute live demo and earn a "nice work." We are **not** building a maintained
product or a phone service. The job now is to **subtract, polish, and stop.**

## The one rule
Stop adding capability. Every hour from here goes into making a *small* set of things work
*every single time*. A demo dies on one embarrassing mistake, not on a missing feature.

## Five moves

1. **Drop the phone stuff entirely.** All Twilio/phone code stays in the tree but is **out of the
   demo and out of scope**. The compliance (`DOCS/COMPLIANCE_TELECOM.md`) and white-label
   (`DOCS/WHITELABEL_SCAN.md`) docs only mattered for a phone/medical product we're no longer
   chasing — ignore them. Don't delete anything; just don't run or demo it.

2. **Cut tools to a small allowlist — DONE.** Added `Config.demo_mode` (default off) + a
   `DEMO_TOOLS` allowlist in `tools/registry.py`. Turn it on with `"demo_mode": true` in the demo
   machine's `config.json`; everything outside the list is hidden so it can't misfire. Reversible,
   nothing deleted. Current 9-tool set: `get_todays_schedule`, `get_calendar_events`,
   `get_unread_emails`, `search_emails`, `send_email`, `get_weather`, `web_search`, `remember`,
   `search_and_play`. **Gmail + Calendar need the Google account signed in on the demo machine.**

3. **Pick ONE demo machine and make only it perfect.** Recommend Jack's Mac (better STT via mlx +
   the polished orb UI). Do not chase Windows/Mac parity.

4. **Write and rehearse a fixed 4–5 command demo script.** Drill it until each command works cold,
   back-to-back, no wake-word miss, no wrong answer. The script *is* the product now. Flaky
   command → fix it or cut it from the script.

5. **Polish what's seen and heard:** clean startup (no error spew), the orb reacting on
   listen/speak, and the premium ElevenLabs voice. That surface is most of what makes it feel
   finished.

## Voice & smoothness (Mac tuning — this is what makes it feel "perfect")

**ElevenLabs only — DONE in code.** In `demo_mode` the TTS router uses ElevenLabs and will NOT
fall back to Cartesia/pyttsx3 on error (it logs loudly instead), so the voice can never switch
mid-demo. Streaming + `eleven_flash_v2_5` already on. The rest below must be tuned live on the Mac
by ear — cannot be done from Windows:

- **Pick the voice deliberately.** Current default `elevenlabs_voice_id = JBFqnCBsd6RMkjVDRZzb` is
  generic. Audition voices in the dashboard picker and choose one that sounds great *streaming*.
- **Model dial:** `eleven_flash_v2_5` (fastest, snappiest). If the voice sounds thin, try
  `eleven_turbo_v2_5` (richer, still fast). Pick by ear.
- **Warm up before the demo** — one throwaway "hey Jarvis" so the first real reply isn't the slow one.
- **Tune `vad_silence_ms`** (pause before Jarvis replies, currently 1400ms). Lower = snappier but
  risks cutting the speaker off. Adjust by ear on the Mac.
- **Good mic + solid WiFi** — ElevenLabs streaming is network-dependent; weak connection = stutter.
  Test on the actual demo network.
- **Barge-in** (talking over Jarvis): test it, or keep it out of the script if it feels rough.

## Explicitly NOT doing
- No phone, compliance, medical/vertical work.
- No new integrations or tools.
- No accuracy/WER harness (that was for the phone go/no-go — irrelevant now).
- No cross-platform parity.

## Definition of "done" (so we actually stop)
On the demo machine: starts clean → wakes to "hey Jarvis" → runs the 4–5 scripted commands
correctly **three times in a row** with the orb animating and a natural voice. When that passes,
**stop and schedule the demo.**
