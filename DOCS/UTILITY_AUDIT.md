# Jarvis — Honest Utility Audit

**Date:** 2026-06-30
**Audience:** Jack, Oliver, and Nuvolum leadership
**Author:** Cursor (Claude), acting as an independent reviewer
**Scope:** This is a value audit, not a code audit. The question is not "is the code good" but "is this worth building and maintaining for a real agency team and their clients."

A note on method: I read the codebase, the docs, and (most importantly) the actual usage data in `memory/variables.db`. Where I make a claim about how Jarvis behaves in the real world, it is grounded in that data, not in the docs. The docs describe the intended system. The database describes the system that actually ran. They are not the same thing, and the gap between them is the heart of this memo.

---

## The single most important fact

In the entire recorded history of this project, Jarvis has cost **77 cents** in Claude API spend across 144 calls and roughly 111 conversations, spanning 20 days (2026-06-10 to 2026-06-30). The turn log contains **83 instrumented turns**, of which the clear majority are developer test strings: "first", "c2", "c3", "c4", "hello", "q", "hi". There are **23 wake-word events** total. The only fact stored in long-term memory is `test_key = hello`.

This is not a product that is being used. It is a product that is being built. That distinction governs everything below. Nobody at Nuvolum has lived inside Jarvis for a week and relied on it. Until that happens, every claim about utility is a hypothesis.

---

## Section 1 — What Jarvis actually is today

In plain English, for an account manager who has never seen it: Jarvis is a voice assistant that runs on your own Mac. You say "hey Jarvis", it listens through your microphone, turns your speech into text on the device, sends that text to Claude, and speaks the answer back in a synthetic voice. It can also do a fixed set of actions for you: read your Google Calendar and Gmail, draft and send email, post to Slack, search the web, control your Mac (volume, brightness, open apps), play music, look up the weather, and build a basic PowerPoint. There is a control panel in your browser at `localhost:7777` that shows what it is doing and lets you type to it instead of speaking. It keeps a local memory of facts and notes that never leaves your machine.

That is the honest framing of the concept. Now the five specific questions.

**1. Can a non-developer run it today without Jack or Oliver?**
Partly. There is a built `Jarvis.app` in `dist/`, and there is a first-run onboarding wizard, so a non-developer could in principle double-click and go. But full functionality requires up to **seven secrets** configured by hand: an Anthropic key (paid), Cartesia, ElevenLabs, Google client ID and secret, a Brave key, and a GitHub token. Google features require an OAuth browser dance. The from-source path (`run.sh`) needs Homebrew, a Python virtualenv, and a roughly 1 GB dependency install. A non-developer can launch the app; they cannot stand up the integrations that make it useful without help. So: runnable yes, self-serviceable no.

**2. What happens when it breaks, and is there a recovery path a non-developer can follow?**
The known-issues list tells the story: "delete `semantic_index.db` if it corrupts", "abort trap on Ctrl+C is cosmetic, ignore it", "webrtcvad missing on Windows, energy fallback works". These are developer recovery paths, not user ones. When Jarvis mishears you, loops on empty audio, or the wake word misfires, there is no in-product "it's broken, here's what to do". The recovery path is to message Jack or Oliver. For a busy non-technical user, that is a dead end.

**3. How long from cold start to first working voice interaction?**
From source on a clean machine: realistically 10 to 30 minutes (Homebrew, venv, ~1 GB of mlx/torch/Qt, wake-model download), plus key setup. From the `.app`: a few minutes to launch, but you still cannot use Google, Slack, or premium voice until the keys and OAuth are done. After everything is configured, a warm start to first reply is seconds.

**4. What percentage of voice commands work on the first attempt, from the DB?**
This cannot be answered honestly as a clean percentage, and that is itself the finding. There is no success label on a turn, `stt_confidence` is **NULL for every single row** (it is never recorded), and roughly 90% of the 66 voice turns are synthetic test strings. Among the handful of genuine spoken commands, the transcription quality is visibly poor, because the Whisper model is set to **`tiny`**. Real captured examples: "And now, all there was my energy from one to two, I guess", and a pure hallucination loop, "1.5 cm 1.5 cm 1.5 cm 1.5 cm..." on silence. Several real turns ended in clarification loops ("Who is him?") rather than action. The honest summary: on the small real sample, a meaningful share of first attempts were garbled or did not complete, and the system does not currently measure its own accuracy well enough to claim otherwise. Anyone who tells you Jarvis has a known first-attempt success rate is guessing.

**5. What does it do that Claude.ai in a browser tab cannot?**
Three real things. It is **hands-free and ambient**: you can talk to it without touching a keyboard. It can **act on your local machine and accounts**: open apps, set volume, send a real email through your Gmail, post to your Slack, read your actual calendar. And it keeps **local, private memory** that never goes to a third party. Everything else (reasoning, drafting, summarising, answering questions) Claude.ai does at least as well, usually better, with no setup.

---

## Section 2 — The comparison test

For each real agency task: Jarvis vs Claude.ai in a browser vs the dedicated tool. Score and one sentence.

**A. Draft a client email update on campaign performance.**
Jarvis: **Worse.** It can draft and even send, but you cannot see and edit a long email comfortably by voice; Claude.ai lets you read, refine, and copy with full control.

**B. Pull this week's calendar and prep for a meeting.**
Jarvis: **Better** (narrowly). It reads your actual Google Calendar aloud and surfaces Zoom links hands-free; Claude.ai has no calendar access, and opening Google Calendar yourself is more steps but more reliable.

**C. Search past client notes and surface relevant context.**
Jarvis: **Same to Worse.** Its local semantic memory is real but nearly empty and unproven; a well-maintained Notion or a Claude Project with uploaded notes will out-recall it today.

**D. Send a Slack update to the team.**
Jarvis: **Worse.** Posting by voice with a confirm step is slower and riskier than just typing in Slack, which everyone already has open.

**E. Look up a contact's email and phone.**
Jarvis: **Better** for pure speed: "hey Jarvis, what's Sarah's email" beats opening Contacts, if the name transcribes correctly. The "if" is doing heavy lifting.

**F. Generate a slide deck for a client presentation.**
Jarvis: **Worse.** The `create_pitch_deck` tool produces a skeletal PPTX; Claude.ai plus a human in Google Slides produces something you would actually show a client.

**G. Get the weather before a client site visit.**
Jarvis: **Same.** It works and is convenient hands-free, but this is a solved problem on every phone.

**H. Search for recent news on a client's industry.**
Jarvis: **Worse.** Its web search is a single DuckDuckGo/Brave lookup; Claude.ai with web access or a normal browser gives richer, more current results.

**I. Log a note after a client call.**
Jarvis: **Better** (this is its sweet spot). Hands-free, immediately after a call, "hey Jarvis, log a note: client wants the revised proposal by Friday" is genuinely faster than opening any app. The value depends entirely on transcription accuracy.

**J. Set a reminder for a follow-up.**
Jarvis: **Worse.** There is a `calendar_reminder` plugin, but a phone or Google Calendar reminder is more reliable and syncs everywhere; Jarvis reminders live only where Jarvis is running.

Pattern: Jarvis wins exactly where the value is **hands-free capture and quick lookup in the moment** (notes, contacts, calendar read). It loses everywhere the task benefits from a screen, editing, or a tool the team already lives in.

---

## Section 3 — The real user test

**1. Would a Nuvolum account manager use Jarvis instead of typing into Claude.ai?**
For most tasks, no. Claude.ai requires no setup, no maintenance, and gives a screen to read and edit on. They would reach for Jarvis only for the narrow hands-free moments in Section 2 (notes, contacts, calendar read), and only if those worked reliably, which today they do not, because of the `tiny` Whisper model and the absence of accuracy measurement.

**2. Learning curve to get value on day one?**
The concepts are easy ("say hey Jarvis, then talk"). The friction is everything around it: configuring keys, granting microphone and accessibility permissions, learning what it can and cannot do, and recovering when it mishears. A non-technical user gets near-zero value on day one without someone sitting beside them.

**3. What breaks the experience most: wake word, voice recognition, response quality, or tool execution?**
**Voice recognition, decisively.** The DB proves it: garbled transcripts and a hallucination loop, all traceable to `whisper_model: tiny`. Claude's response quality is fine; the tools mostly work. But if Jarvis hears "send audience email" when you said something else, nothing downstream matters. This is the single highest-leverage fix in the whole project, and it is a one-line config change to a larger model, at the cost of speed.

**4. Is the dashboard a daily non-developer tool or a developer tool?**
It is a developer tool wearing a nice coat. Eleven views including "Jarvis Thinks" (self-improvement suggestions), an SSE activity feed, tool risk tiers, and token-budget bars. An account manager has no reason to open this daily. The only genuinely user-facing parts are the talk box, the email/calendar views, and settings.

**5. What would have to be true for someone to say "I use Jarvis every day"?**
Voice recognition reliable enough that they stop repeating themselves (bigger Whisper model, measured accuracy). One workflow that is genuinely faster hands-free than the alternative (note capture is the best candidate). Zero-maintenance operation: it just works every morning without a developer. And a recovery path a non-technical person can follow. None of these four are true today.

---

## Section 4 — The client use case

**1. What client-facing use cases does it support today?**
Honestly, none that are production-ready. Everything is built around a single developer's own Mac, accounts, and API keys. There is no multi-tenant model, no per-client isolation, no client-safe permissioning. It is a personal assistant, not a deployable service.

**2. What would "Jarvis for a dental practice" or "Jarvis for a medical group" look like?**
In principle: a receptionist's voice helper that books appointments, reads the day's schedule, logs call notes, and drafts patient follow-ups hands-free. In practice today, none of that exists. There is no scheduling integration, no practice-management hookup, no patient-data handling, and critically no HIPAA posture. Medical and dental clients sit under strict privacy regulation, and a voice assistant that sends email and reads calendars would need a compliance story this project has not started.

**3. Liability and trust risks of a voice AI that can send emails and make phone calls for a client.**
Significant, and partly already live. By design, `send_email` is **AUTO_ALLOW on the voice path**: a misheard command can send a real email with no confirm step (this is documented as an accepted risk in `registry.py`). Given the transcription quality shown in the data, that is a real exposure. On phone calls: despite the sprint targets naming a "Twilio AI phone agent", **no phone-calling capability exists in the code at all.** Presenting Jarvis as able to make calls on a client's behalf would be selling something that does not exist. The general risk: an AI acting on a client's accounts, on misheard input, with weak audit trails, is a reputation and legal hazard for an agency that owns the client relationship.

**4. How does it compare to Siri, Google Assistant, Microsoft Copilot, ChatGPT voice mode?**
Unfavourably on every axis a client would care about: reliability, polish, support, and trust. Those products have world-class speech recognition, are maintained by trillion-dollar companies, and already sit on the client's phone or in their Microsoft 365. ChatGPT voice mode in particular does the "talk to a smart assistant" job dramatically better out of the box. Jarvis's only differentiators are local privacy and bespoke tool actions, and neither is currently strong enough to overcome the gap.

**5. Is there a client problem Jarvis solves that no commercial tool does?**
There is one defensible seam: **a fully local, private voice assistant wired into a specific, controlled set of business actions, with no client data leaving the device.** For a privacy-sensitive client who distrusts Big Tech assistants, that is a real story. But it is a narrow seam, and Jarvis is nowhere near able to fill it for a client today.

---

## Section 5 — The maintenance reality

**1. If Jack stopped tomorrow, can Oliver maintain it alone?**
With difficulty. The architecture is deliberately split by platform and by ownership, and the coordination overhead is real: a list of "coordinated files" that require messaging the other dev before editing (`pipeline.py`, `main.py`, `config.py`, `registry.py`, `speech_state.py`, `events.py`, `core.py`). The two riskiest files are also the two largest: `pipeline.py` at 1,279 lines and `registry.py` at 1,238. Oliver could keep the Windows side and basics alive, but the self-improvement engine, the orb, and the macOS-specific paths are Jack's territory.

**2. If both stopped, could a new developer pick it up from the docs?**
The docs are unusually good for a project this size (DOCS/, spec files, a signed changelog, an agent protocol). A competent Python developer could get oriented. But they would inherit ~5,600 lines of core code, 72 tools, a custom orchestrator, a speech state machine, a two-platform matrix, and a self-improvement subsystem that does not yet do anything. The docs would shorten the ramp; they would not make it short.

**3. How much time per week to maintain at the current state?**
At zero real users, maintenance is whatever the developers choose to spend, and the evidence (9 sprints, 564 tests, two people) is that this is a substantial ongoing investment, plausibly a meaningful chunk of two developers' weeks. The moment it has real daily users, that number goes **up**, because every dependency break, API change, and mis-transcription becomes a support ticket.

**4. Biggest technical risk that could make the whole thing stop working?**
Upstream API and dependency churn. Jarvis depends on Anthropic model names (`claude-haiku-4-5`, `claude-sonnet-4-6`), ElevenLabs and Cartesia APIs, Google OAuth, openWakeWord, and a heavy native stack (mlx-whisper, PyQt6, PyAudio/PortAudio, webrtcvad). Any one of these changing or breaking can take the assistant down, and several have already caused issues (the ElevenLabs 403 on pcm_44100, the missing `download_file` import that silently broke a whole tool, webrtcvad not building on Windows). This is a brittle surface for an unattended product.

**5. What does it cost per month to run?**
Today, effectively nothing, because it is barely used: 77 cents of Claude spend in three weeks. At light real daily use the dominant costs would be Claude (the budget caps are set at $2/day and $40/month, but those are theoretical ceilings, not actuals) and the voice services. The real near-term ceiling is the **ElevenLabs free tier at 10,000 characters per month**, which the docs themselves flag as something you run out of fast with daily use. So: pennies while it is a toy, low tens of dollars per active user per month if it becomes real, plus the developer time that dwarfs all of it.

---

## Section 6 — The honest comparison

**A. Claude.ai Pro ($20/month) in a browser.**
What Jarvis adds: hands-free voice, local actions (email/Slack/calendar/Mac control), private on-device memory. What it costs you: setup, maintenance, and worse reliability. For 90% of agency knowledge work, Claude.ai Pro wins on day one and never needs a developer.

**B. Claude.ai + Zapier for automations.**
What Jarvis adds: voice and a single private surface. What Zapier adds that Jarvis cannot match: hundreds of maintained, reliable integrations that run unattended in the cloud, with proper logging and error handling. For "when X happens, do Y" automation, Zapier is in a different league.

**C. Microsoft Copilot (already in M365).**
If Nuvolum is on Microsoft 365, Copilot is already paid for and already wired into mail, calendar, Teams, and documents, with enterprise-grade voice and support. Jarvis offers local privacy and bespoke actions; Copilot offers everything else, today, with no build cost. This is the most threatening alternative if the team is on M365.

**D. A custom Claude.ai Project with good system prompts and uploaded context.**
This is the sleeper. A well-built Claude Project captures most of Jarvis's actual delivered value (smart, context-aware text help with the team's knowledge loaded) in an afternoon, with zero maintenance and zero infrastructure. What it lacks is voice and local actions. For a lot of the agency's real needs, this is 80% of the value at 1% of the cost.

**E. Building nothing and using existing tools better.**
For most of the agency, this genuinely competes. Better use of Google Workspace, Slack, and one good AI subscription would cover the everyday work. Jarvis only beats "nothing" in the specific hands-free, local-action, private moments, and only once it is reliable.

---

## Section 7 — The verdict

No hedging.

**1. Strongest genuine use case right now.**
Hands-free, in-the-moment capture and lookup on a single power user's own Mac: "log this note", "what's on my calendar", "what's Sarah's email", "send that quick update". That is the one place Jarvis is meaningfully better than typing into Claude.ai.

**2. The single most valuable thing it does that justifies the development cost.**
Honestly: as a product, nothing yet justifies the cost, because it has no users. As an asset, the most valuable thing built is the **local action layer plus private memory** (the wiring from voice to real Gmail/Slack/Calendar/Mac actions with on-device storage). That is the genuinely hard, genuinely differentiated part. The voice loop and the self-improvement engine are not.

**3. What should be stopped or descoped immediately.**
- **The self-improvement engine ("Jarvis Thinks", reflect/judge/research, the turns/events/corrections/lessons/baselines tables).** It has produced 2 suggestions, 1 correction, 0 lessons, 0 baselines, and `stt_confidence` is not even recorded. It is sophisticated machinery with no fuel. Freeze it.
- **The 72-tool sprawl.** Many tools (brightness, screen saver, Wi-Fi toggling, screen lock, pitch decks, GitHub self-write) add surface area and maintenance without serving the core use case. Cut to the ~10 tools that matter.
- **Any client-facing or phone-agent ambition.** The "Twilio AI phone agent" does not exist; stop implying it does. Client deployment is years of compliance work away.
- **Dual-platform parity as a near-term goal.** Pick one OS (Mac, where it is furthest along) and stop paying the cross-platform coordination tax until there is a user.

**4. Minimum viable version that would actually be used daily.**
One Mac, one user. Wake word plus the `small` (or larger) Whisper model so it hears correctly. Five tools: log a note, read calendar, read/send email **with a confirm step on send**, search memory, web search. Local memory on. No dashboard beyond a status indicator and settings. No self-improvement engine. Measure first-attempt success honestly from day one. If that version is used every day for two weeks, you have proven something. If it is not, no amount of additional tools will save it.

**5. Keep building, narrow scope, or redirect?**
**Narrow hard, then prove it.** Do not keep building at the current breadth, and do not abandon it, because the local-action-plus-privacy seam is real and the engineering is competent. But the project has been optimising the wrong things: 9 sprints went into orchestration, self-improvement, 72 tools, and cross-platform parity, while the one thing that actually breaks the experience (voice recognition accuracy) still runs on the `tiny` model and is not even measured, and the system has essentially never been used in anger. Cut Jarvis down to the MVV above, put it in front of one real Nuvolum user for two weeks, and let usage data, not sprint momentum, decide whether it lives. If after a fair trial nobody reaches for it over Claude.ai, redirect the effort: a well-built Claude Project plus better use of existing tools will serve Nuvolum sooner, cheaper, and with no maintenance burden.

---

## Executive summary

Jarvis is a competently engineered, well-documented voice assistant that, on the evidence of its own database, has never actually been used: 77 cents of API spend, 23 wake events, and a memory containing one test value. The genuinely valuable and hard part is the local action layer (real Gmail, Slack, Calendar, and Mac control) combined with private on-device memory. The part that is breaking the experience, voice recognition, is running on the smallest, least accurate model and is not even measured. Effort has gone into the wrong places: a self-improvement engine with no data, 72 tools, and cross-platform parity, while the core reliability problem and the absence of real users went unaddressed. For almost everything a Nuvolum account manager does, Claude.ai in a browser or Microsoft Copilot wins today with zero setup and zero maintenance. The recommendation is not to kill Jarvis and not to keep building at current breadth, but to narrow it hard to a single-Mac, five-tool, accurate-voice MVV, put it in front of one real user for two weeks, and let usage decide. If nobody reaches for it over Claude.ai, redirect the effort to a Claude Project and better use of the tools the team already has.
