# White-Label Voice-Agent Platform Scan (O5)

**Status:** research / decision-support doc. No code. Feeds the build-vs-white-label decision.
**Owner:** Oliver. **Date:** 2026-07-01.

Purpose: give the build-vs-buy call (see [STT_STREAMING_DECISION.md](STT_STREAMING_DECISION.md) and
the joint decision) real options with real numbers. Question each platform has to answer: **can it
hold the compliance chain (BAA + encryption + audit) so we don't rebuild it in Jarvis, and can Jarvis
sit on top as the integration/value-add layer — or does it replace `twilio_server.py` wholesale?**

> **Headline:** For a **HIPAA** vertical, **Retell AI** is the standout — it's the only major platform
> offering a **self-service BAA on all paid plans** (no enterprise negotiation). For a **pure agency
> reselling** play (marketing, non-PHI), **Synthflow** has the strongest white-label/sub-account +
> Stripe-rebilling infrastructure but gates HIPAA behind Enterprise + a 30% BAA premium. **Vapi** is
> the most flexible/developer-centric but bolts HIPAA on as a paid add-on and stacks fees.
> Treat all vendor ROI claims as marketing; the pricing bands below are corroborated across sources.

---

## The three candidates

### 1. Retell AI — best for HIPAA vertical
- **BAA / HIPAA:** ✅ **Self-service BAA on all paid plans** — the only one that doesn't require an
  enterprise contract for HIPAA. HIPAA + SOC 2 Type I/II + GDPR across every plan; automatic PII
  redaction and RBAC standard.
- **Pricing:** ~$0.07/min headline (flat — STT, verified numbers, branded calls, batch included).
  **Realistic production cost $0.13–$0.31/min** once you add knowledge bases, concurrency, branded
  numbers. ~$1,050/mo for 5,000 3-min calls at headline rate.
- **White-label / agency:** batch calling + branded numbers included; multi-tenant reseller specifics
  are not fully public — confirm with sales.
- **Fit with Jarvis:** strong. Retell owns telephony + ASR + BAA; Jarvis becomes the **value-add
  integration layer** (local memory, Gmail/Calendar/Slack, workflow logic) rather than owning the
  PHI/telecom hop. This is the cleanest "keep Jarvis's differentiator, offload compliance" path.

### 2. Synthflow — best for pure agency reselling (non-PHI)
- **BAA / HIPAA:** ⚠️ **Enterprise plan only**, and the **BAA add-on is ~+30% on the per-minute
  rate**. Added HIPAA support only in early 2026. Most expensive route to a BAA of the three.
- **Pricing / white-label:** **Agency tier ~$1,400/mo**; **White-Label & Reseller Toolkit ~$2,000/mo**
  (custom domain, white-label branding, sub-account management, Stripe rebilling). Genuinely the
  strongest white-label/sub-account model in the category for agency use.
- **Fit with Jarvis:** good for a **non-PHI marketing-agency** motion where the value is
  reselling/rebilling many sub-accounts. Weaker/pricier for HIPAA. In this model Synthflow largely
  **replaces** the Twilio stack; Jarvis is less central.

### 3. Vapi — most flexible / developer-centric
- **BAA / HIPAA:** ⚠️ HIPAA as a **~$1,000 add-on**.
- **Pricing:** ~$0.05/min headline but **real cost $0.20–$0.33/min**; stacks a fixed platform fee on
  top of per-minute, charges extra for STT, variable phone-number pricing.
- **White-label:** highly composable/programmable; agency multi-tenancy is doable but more DIY.
- **Fit with Jarvis:** best if we want deep programmatic control and are willing to assemble more
  ourselves — but that partly defeats the "offload compliance/infra" goal. Middle option.

### Aggregator note — VoiceAIWrapper
Positions itself as a layer to **white-label Vapi/Retell/ElevenLabs et al. with BAA-on-demand**. Worth
a look if we want one reseller wrapper over multiple engines, but it adds a dependency and a margin
layer — evaluate only if the direct platforms don't fit.

---

## Economics (corroborated ranges, not vendor ROI claims)
- **Purpose-built HIPAA dental voice agent: $300–$900/mo per practice** (vs a $3,500–$4,500/mo
  fully-loaded front-desk hire). This is the resale price band we'd charge SMBs.
- **Agency model:** fixed platform cost ($1,400–$2,500/mo) + per-minute usage, resold at
  $300–$900/mo/client → **break-even ~9–10 clients, 60–80% gross margin at scale** (consistent with
  the market analysis).
- HIPAA BAA premiums (Vapi +$1k, Synthflow +30%/min) materially change unit economics — factor into
  any medical pricing.

---

## Recommendation
1. **If we commit to a HIPAA vertical (dental/medical): shortlist Retell AI.** Self-service BAA on all
   paid plans is a decisive advantage, and it maps cleanly to "Jarvis as integration layer on top of a
   compliant platform" — we keep our differentiator and offload the PHI/telecom/compliance chain.
2. **If the first pilot is marketing agencies (non-PHI, recommended per [O4](COMPLIANCE_TELECOM.md)):**
   Synthflow's white-label/rebilling is the fastest path to a multi-client reseller product; HIPAA can
   wait.
3. **Keep Vapi as the fallback** if we later need deep programmatic control.
4. **Do not decide until the WER gate is in.** If local `large-v3-turbo` (or a streaming engine) clears
   the phone-WER bar, we may keep more of the stack in-house; if it doesn't, white-labeling the whole
   voice+phone layer becomes the obvious call. This scan exists so that decision has options attached.

---

## Sources
- [Retell AI — pricing](https://www.retellai.com/pricing)
- [Retell AI — 10 best HIPAA-compliant AI voice agents 2026](https://www.retellai.com/blog/10-best-hipaa-compliant-ai-voice-agents-for-healthcare-clinics)
- [Retell AI — Vapi review / comparison](https://www.retellai.com/comparisons/retell-vs-vapi)
- [Synthflow AI pricing explained (Zeeg, 2026)](https://zeeg.me/en/blog/post/synthflow-ai-pricing)
- [getprosper — HIPAA-compliant voice AI providers 2026](https://www.getprosper.ai/blog/hipaa-compliant-voice-ai-providers-healthcare-guide)
- [VoiceAIWrapper — HIPAA-compliant voice AI white label](https://voiceaiwrapper.com/uses/hipaa-compliant-voice-ai-providers)

*Caveat: pricing, BAA terms, and tiers change frequently and much of this comes from vendor and
reseller sources with an incentive to inflate. Re-validate directly with sales (and get BAA terms in
writing) before committing budget.*
