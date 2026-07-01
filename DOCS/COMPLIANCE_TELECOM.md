# Compliance & Telecom Gate (O4)

**Status:** research / decision-support doc. No code. Gates any client pilot that touches PHI or the PSTN.
**Owner:** Oliver. **Date:** 2026-07-01.

This is the checklist that must be satisfied before Jarvis (or a Jarvis-integrated voice agent)
handles real patient data or answers real phone calls for a client. It doubles as a **remediation
backlog** — each requirement is mapped to Jarvis's current state so we know the delta.

> **Bottom line:** Jarvis today is nowhere near HIPAA-ready, and the gap is structural, not
> cosmetic. Two facts dominate: (1) the 2025 HIPAA Security Rule NPRM is about to make encryption
> and several other now-"addressable" controls **mandatory**, and (2) every cloud vendor in the
> voice path (Anthropic, ElevenLabs/Cartesia, Deepgram, Twilio) becomes a **Business Associate** the
> moment PHI flows through it — each needs its own signed BAA, or that hop must stay local. For a
> first pilot, **marketing-agency clients (no PHI) are dramatically lower-risk** than dental/medical.

---

## Part 1 — HIPAA / BAA checklist → Jarvis gap map

Scheduling data (names, phone numbers, appointment times, reason-for-visit) **is PHI**. Touching it
triggers the full Security Rule. The Dec 2024 NPRM (published Jan 6, 2025) tightens the bar: it
**removes the "required vs addressable" distinction and makes nearly all specs required**, explicitly
mandates encryption of ePHI at rest and in transit, adds MFA, annual compliance audits, semiannual
vulnerability scans + annual pen testing, and stronger business-associate verification.

| Requirement | Standard | Jarvis today | Gap |
|---|---|---|---|
| **Signed BAA with every vendor touching PHI** | Anthropic, ElevenLabs, Cartesia, Deepgram, Twilio each = Business Associate | No BAAs; PHI would flow to all of them in cloud paths | **BLOCKER** — sign BAAs or keep each hop local |
| **Encryption at rest (AES-256)** | NPRM: now *required* | `memory/variables.db`, `memory/semantic_index.db`, `memory/google_token.json` all **plaintext** | **BLOCKER** — add sqlcipher / OS-keyring for token |
| **Encryption in transit (TLS 1.2+)** | Required | Dashboard is localhost HTTP; Twilio media WS server binds `ws://0.0.0.0:8765` and relies on an external tunnel (ngrok) for `wss://` termination | Partial — fine behind tunnel, but internal hop unencrypted; formalize |
| **Access control / RBAC** | Required (unique user IDs, least privilege) | Single-user, no auth layer, no per-tool scoping | **BLOCKER for multi-user** — none exists |
| **Audit logging** | Tamper-evident, who/what/when | `tool_runs` table exists **but voice-path tool calls go only to `improvement.trace`, not `tool_runs`**; no hash-chain/tamper-evidence | Gap — centralize logging + make append-only |
| **Audit log retention ≥ 6 years** | HIPAA minimum | `db_retention_days` **default 90** — deletes `tool_runs`/`conversations` after 90 days | **DIRECT CONFLICT** — 90 days << 6 years; must exempt audit tables |
| **MFA** | NPRM: now required | None | Gap (matters once multi-user / remote) |
| **AI disclosure to caller** | FCC proposed rule + state law (see Part 2) | `PHONE_GREETING = "Hello, this is Jarvis. How can I help?"` — **does not disclose AI use** | **BLOCKER for phone** — must state AI up front |
| **Annual risk analysis + compliance audit** | NPRM: every 12 months | None | Process gap |
| **Breach notification (24h BA→CE under NPRM)** | Required | No incident-response plan | Process gap |

**Key architectural consequence:** "fully local" and "HIPAA-cheap" align. Every time we move a hop
to the cloud (streaming STT via Deepgram, TTS via ElevenLabs, LLM via Anthropic), we add a BAA and a
PHI-egress point. The local-first design is actually the *compliance-friendly* path — the tension is
purely latency/accuracy (see [STT_STREAMING_DECISION.md](STT_STREAMING_DECISION.md)).

---

## Part 2 — Telecom obligations once agents touch the PSTN (FCC / USAC / TCPA)

### USF contribution (FCC / USAC)
- **2026 de-minimis threshold: $37,175** in projected annual end-user interstate + international
  telecom revenue. Under that, no direct USF contribution and no quarterly **Form 499-Q**.
- **But** de-minimis providers **still must file the annual Form 499-A**, and they contribute
  *indirectly* through the underlying carrier (Twilio).
- Practical read: at pilot scale we're almost certainly de-minimis, but the **499-A filing
  obligation is not zero** — budget for it, don't ignore it.

### TCPA + AI-voice rules
- **Feb 8, 2024 FCC Declaratory Ruling:** an AI-generated voice **is "artificial" under the TCPA.**
  AI calls can't dodge TCPA. Callers must (1) get prior express (written, for marketing) consent,
  (2) provide identification/disclosure of who's responsible, and (3) offer opt-out.
- **July 2024 NPRM:** proposes a mandatory **up-front, in-call disclosure that the call uses
  AI-generated voice** — at the *opening* of the call, before substantive conversation. Expected to
  become federally mandatory within ~12–24 months; treat as imminent.
- **State laws already live:** Texas requires disclosure within 30 seconds; California, Florida,
  Colorado, Illinois, Utah have variants. The **Colorado AI Act (effective 2026)** may classify most
  voice AI as "high-risk" with added obligations.
- **Inbound vs outbound:** most TCPA consent burden is on *outbound* calling. Jarvis's phone agent is
  **inbound (caller dials in)**, which is far lower-risk on consent — but the **AI-disclosure
  requirement still applies**, and any outbound (callbacks, confirmations, reminders) re-triggers the
  full consent regime.

### Action items (phone track)
1. **Fix the greeting** — `PHONE_GREETING` must disclose AI in the first sentence (e.g. "Hi, you've
   reached Jarvis, an AI assistant for <practice>…"). Cheapest compliance win; do it before any pilot.
2. Confirm **Twilio is the carrier of record** (it is) → we ride its telecom compliance for
   transport, but the 499-A filing and TCPA/disclosure duties are still ours.
3. **No outbound automated calling** in the first pilot — keep it inbound-only to avoid the consent
   regime until we have a compliance process.

---

## Recommendation

- **First pilot = marketing agencies, not medical.** No PHI → no BAA chain, no HIPAA Security Rule,
  no 6-year retention rebuild. Proves the product and the managed-service motion at a fraction of the
  compliance cost.
- **If/when we do dental/medical:** treat the Part-1 blockers (BAAs, encryption at rest, RBAC,
  audit-retention exemption, AI disclosure) as hard prerequisites, and strongly prefer a **white-label
  platform that already holds the BAAs and compliance infrastructure** rather than rebuilding it in
  Jarvis — see [WHITELABEL_SCAN.md](WHITELABEL_SCAN.md).
- **Do the AI-disclosure greeting fix now regardless** — it's one line and it's required for any
  phone deployment, PHI or not.

---

## Sources
- [HHS — HIPAA Security Rule NPRM fact sheet](https://www.hhs.gov/hipaa/for-professionals/security/hipaa-security-rule-nprm/factsheet/index.html)
- [Federal Register — HIPAA Security Rule NPRM (Jan 6, 2025)](https://www.federalregister.gov/documents/2025/01/06/2024-30983/hipaa-security-rule-to-strengthen-the-cybersecurity-of-electronic-protected-health-information)
- [USAC — De Minimis](https://www.usac.org/service-providers/contributing-to-the-usf/forms-to-file/de-minimis/)
- [USAC — 2026 FCC Form 499-Q instructions (PDF)](https://www.usac.org/wp-content/uploads/service-providers/documents/forms/2026/2026-FCC-Form-499-Q-Instructions-and-Form.pdf)
- [FCC — TCPA applies to AI-generated voices (Feb 2024 ruling)](https://www.fcc.gov/document/fcc-confirms-tcpa-applies-ai-technologies-generate-human-voices)
- [Wilson Sonsini — FCC rules AI voices "artificial" under TCPA](https://www.wsgr.com/en/insights/fcc-rules-ai-generated-voices-are-artificial-under-the-tcpa.html)
- [Henson Legal — AI Voice Agent Compliance: TCPA/FCC/State (2026)](https://www.henson-legal.com/ai-voice-compliance)

*Caveat: regulatory status is fast-moving; the FCC in-call AI-disclosure rule is proposed, not final.
Re-validate before committing to a client contract.*
