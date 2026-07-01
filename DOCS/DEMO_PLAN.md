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

---

# Live Demo Runbook (the thing you read while nervous)

This is the operational half of the plan. If you blank mid-demo, read straight down this list.

## Machine state (verified 2026-07-01)
- **Demo machine:** this Mac. Do not switch machines.
- **STT:** `large-v3-turbo` via mlx. Model is downloaded and cached (warmup succeeded), so the
  first command will not stall on a download.
- **Tools:** `demo_mode: true` in `config.json`. Only 9 safe tools are exposed; the other 75 are
  hidden and cannot misfire. Nothing is deleted; flip `demo_mode` off to restore the full set.
- **Tests:** 648 passing.
- **Google OAuth: BROKEN on this machine** (`invalid_scope` on token refresh). Calendar and email
  commands will fail. They are **cut from the script**. Do not demo them unless you re-auth in a
  browser first and re-test.

## Pre-demo checklist (run in order, the morning of)
1. **Wifi on and stable.** Weather and web search make live API calls; no wifi means two dead
   commands.
2. **Model present:** `source .venv/bin/activate && python -c "from adapters.stt import warmup; warmup('large-v3-turbo','mlx')"`
   Should return instantly (already cached). If it downloads, wait for it to finish before demoing.
3. **Launch clean:** `./run.sh` and watch for a clean startup with no red error spew. If the orb
   appears and settles to idle, you are good.
4. **Sound check:** system output volume up, correct output device, ElevenLabs voice selected.
   Say "hey Jarvis, what time is it" once to confirm wake word + voice + STT all fire.
5. **Silence notifications:** turn on macOS Do Not Disturb so nothing pops up on screen-share.
6. **Rehearse the five commands cold, three times back to back.** If any command flakes twice,
   cut it from the script rather than gamble on it live.

## The 5-command script (safe, no OAuth needed)

1. **"Hey Jarvis, what time is it?"**
   Proves: wake word, STT, tool dispatch, and voice all work. Rock-solid opener with zero external
   dependencies. If this works, the plumbing works.

2. **"Hey Jarvis, what's the weather in San Rafael?"**
   Proves: a real, live external API call returning a visible, current result. Shows it is not
   scripted.

3. **"Hey Jarvis, search the web for Nuvolum marketing agency."**
   Proves: live web search. Ties the demo to the audience (their own agency).

4. **"Hey Jarvis, remember that our demo client is a dental practice in Marin."**
   Proves: persistent local memory. Sets up the "it remembers you" story without needing a second
   turn to pay off.

5. **"Hey Jarvis, play some music."**
   Proves: it acts on the real machine (Music.app). Ends on something tangible and crowd-pleasing.

**Optional 6th, ONLY if you re-auth Google first and re-test:**
6. "Hey Jarvis, what do I have on my calendar today?" (currently broken, see OAuth note above.)

## If something fails live (recovery lines)
- **Wake word misses:** pause, wait for the orb to return to idle, and say "hey Jarvis" again,
  cleanly. Do not talk over it. One clear repeat beats three rushed tries.
- **Wrong transcription / odd answer:** say "never mind" and move to the next command. Do not argue
  with it on stage; the script has five wins, you only need most of them to land.
- **A command flat-out fails:** skip it and continue. Never debug live. The next command resets the
  room.
- **Weather or web returns nothing:** it is almost always wifi. Glance at the wifi icon; fall back
  to the time, remember, and music commands, which need no network beyond the model.
- **Total freeze:** press Stop on the orb (or Escape) to cancel the turn, wait for idle, continue.

## Hard rule
If it is not on this page, do not demo it. The script is the product.
