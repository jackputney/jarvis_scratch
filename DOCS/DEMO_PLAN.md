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

2. **Cut tools from ~84 to ~5–6** that look great and never flake. Suggested set: today's
   calendar, weather, play music, web search / answer a question, take-a-note / remember. Use the
   existing risk-tier / developer-mode hiding in `tools/registry.py` to hide everything else so it
   can't misfire mid-demo. This is flipping switches, not deleting code.

3. **Pick ONE demo machine and make only it perfect.** Recommend Jack's Mac (better STT via mlx +
   the polished orb UI). Do not chase Windows/Mac parity.

4. **Write and rehearse a fixed 4–5 command demo script.** Drill it until each command works cold,
   back-to-back, no wake-word miss, no wrong answer. The script *is* the product now. Flaky
   command → fix it or cut it from the script.

5. **Polish what's seen and heard:** clean startup (no error spew), the orb reacting on
   listen/speak, and the premium ElevenLabs voice. That surface is most of what makes it feel
   finished.

## Explicitly NOT doing
- No phone, compliance, medical/vertical work.
- No new integrations or tools.
- No accuracy/WER harness (that was for the phone go/no-go — irrelevant now).
- No cross-platform parity.

## Definition of "done" (so we actually stop)
On the demo machine: starts clean → wakes to "hey Jarvis" → runs the 4–5 scripted commands
correctly **three times in a row** with the orb animating and a natural voice. When that passes,
**stop and schedule the demo.**
