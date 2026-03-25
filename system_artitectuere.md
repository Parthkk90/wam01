# PS-01 — The Loan Officer Who Never Forgets
### Hackathon Recommended Build Plan

| | |
|---|---|
| **Theme** | Long Context Memory · WAL-First · On-Premise Banking |
| **Memory Engine** | Mem0 (self-hosted open-source) + WAL durability layer |
| **SLM** | Phi-4-Mini 3.8B via Ollama (local, <10B param) |
| **Language** | Hindi + English bilingual via AI4Bharat IndicASR v2 |
| **Constraint** | Zero data leaves bank server — PAN/income tokenised before storage |
| **Date** | 18 March 2026 |
| **Status** | Hackathon Submission Build Plan |

---

## 1. The Problem

Rajesh is applying for a home loan at a cooperative bank. Over three weeks, he has spoken to four different agents about his income, co-applicant, existing EMIs, and land documents. Every call starts from zero. Every agent asks the same questions. Rajesh — patient, hopeful — repeats himself again.

This is not a UX problem. It is an architecture problem. And it costs banks and customers every single day.

| What breaks | Why it happens | What it costs |
|---|---|---|
| Every agent starts from zero | No persistent memory across sessions | ~15 min wasted per session, customer frustration |
| Income revisions get lost | No update/conflict detection in CRM notes | Risk of wrong eligibility calculation |
| Co-applicant details repeat every call | Flat CRM stores facts without relationships | Officer error, missed cross-sell opportunities |
| Document context lost between sessions | No session-to-session continuity layer | Duplicate document requests, compliance risk |

---

## 2. Non-Negotiable Constraints

Every architectural decision in this plan is made against these five constraints. If any solution violates one, it is rejected.

| # | Constraint | Implication |
|---|---|---|
| 1 | Model under 10B parameters | Phi-4-Mini 3.8B or Qwen2.5 7B — no GPT-4, no Claude API |
| 2 | All data stays on bank server | Mem0 self-hosted only — cloud Mem0 platform is off the table |
| 3 | Hindi + English bilingual | AI4Bharat IndicASR v2 for transcription — no Whisper cloud API |
| 4 | PAN / Aadhaar / income never stored raw | spaCy NER tokenisation runs before any memory write |
| 5 | Works on cooperative bank hardware | CPU-only mode, 16GB RAM, 500GB SSD — no GPU required |

---

## 3. Why Mem0 Self-Hosted — and Why Not the Alternatives

We evaluated four approaches. The table below shows why Mem0 self-hosted is the right choice for this hackathon — and why each alternative falls short on at least one hard constraint.

| Dimension | PS-01 v1 | PS-01 v2 WAL | Mem0 Cloud | Mem0 Self-hosted | Diagram ref |
|---|---|---|---|---|---|
| **Setup time** | 4–6 wks | 3–4 wks | 2 hrs | 1 day | 2–3 wks |
| **Data stays local** | Yes | Yes | No | Yes | Yes |
| **Hindi support** | Yes | Yes | Partial | Yes | Partial |
| **Relationships** | Yes | Partial | Yes | Yes | No |
| **Intelligent forget** | No | No | Yes | Yes | No |
| **Demo in hackathon** | No | Partial | Yes | Yes | Partial |
| **Crash safety (WAL)** | No | Yes | No | No* | No |

*\* WAL layer is added on top of Mem0 self-hosted as our original contribution — see Section 5.*

> **Why Mem0 Cloud is rejected**
>
> Mem0's managed platform sends memory data to their servers. A customer's income figure, co-applicant name, and loan context would leave the bank's network. This directly violates Constraint 2. The self-hosted open-source version uses the identical API but runs entirely within the bank's LAN. This is the only version we use.

---

## 4. The Recommended Full Stack

| Layer | Component | Version / Config | Why this choice |
|---|---|---|---|
| Transcription | AI4Bharat IndicASR v2 | Docker container, local | 22 Indian languages, Hindi/English code-switching, zero cloud |
| Sensitive field guard | spaCy NER + custom banking rules | Python, runs pre-Mem0 | Intercepts PAN, Aadhaar, mobile before any storage write |
| Memory engine | Mem0 open-source (self-hosted) | `pip install mem0ai` | Conflict detection, graph relationships, intelligent forgetting — pre-built |
| Vector store | ChromaDB (local) | Mem0 config | Runs in-process, no server needed for hackathon |
| Graph store | SQLite-backed (Mem0 default) | Mem0 config | No Neo4j to install or manage |
| WAL layer | Custom 15-line Python | append-only `wal.jsonl` | Crash-safe durability — our original contribution on top of Mem0 |
| Local SLM | Phi-4-Mini 3.8B via Ollama | 4-bit GGUF, CPU mode | <10B param, 4s response, no GPU needed |
| Compact step | Phi-4-Mini compactor prompt | Post-session hook | Rewrites summary after every session, removes superseded facts |
| Consent gate | Custom Python middleware | Runs before `mem0.add()` | DPDP Act compliance — blocks all writes without consent record |
| Session API | FastAPI | 2 endpoints | Thin wrapper: `/session/start` and `/session/end` |
| Container isolation | Docker | Per-session containers | Session contexts cannot leak across customers |

---

## 5. The WAL Layer — Our Original Contribution

Mem0 self-hosted is powerful but has no crash-recovery guarantee. If the `mem0.add()` call fails mid-session, facts are lost. We solve this by adding a Write-Ahead Log step borrowed from OpenClaw's architecture, adapted for banking. This is the technical differentiator we present to judges.

### How it works — three steps at session end

| Step | Action | Guarantee |
|---|---|---|
| Step 1 — Write WAL | Append extracted facts to local `wal.jsonl` before calling `mem0.add()` | If Step 2 crashes, facts survive in WAL and replay on restart |
| Step 2 — Write Mem0 | Call `mem0.add()` with tokenised, structured facts | Memory graph updated with conflict detection and relationship edges |
| Step 3 — Compact | Run Phi-4-Mini compactor to rewrite customer summary | Next session opens with a clean, current, deduplicated context |

### WAL entry format

Each line in `wal.jsonl` is a JSON object. The `relationship` field encodes Updates/Extends/Derives semantics that survive even without a graph database:

```json
{
  "session_id": "S004",
  "timestamp": "2025-03-18T14:22:00+05:30",
  "customer_id": "hashed_C001",
  "agent_id": "AGT_D",
  "facts": [
    {
      "fact_id": "F012",
      "type": "income",
      "value": "62000_INR_MONTHLY",
      "relationship": "updates",
      "supersedes": "F001",
      "verified": false,
      "source": "customer_verbal"
    }
  ]
}
```

> **Judge story for the WAL layer**
>
> "We used Mem0 as the memory engine, but added a write-ahead guarantee borrowed from database theory — the same technique that makes PostgreSQL crash-safe. Before any fact enters Mem0, it is first written to an append-only log. This means a power cut at 2pm in a branch does not lose a customer's income revision from that morning. No existing banking AI memory solution does this."

---

## 6. Sensitive Data Flow — PAN Never Enters Mem0

The tokenisation step is the security boundary. Everything to the left of this boundary may contain raw PAN and Aadhaar. Everything to the right sees only tokens. Mem0 never sees a raw PAN number.

| Stage | What happens | Contains raw PAN? |
|---|---|---|
| IndicASR transcription | Audio → bilingual text transcript | Yes — full transcript |
| spaCy NER pass | Detects PAN, Aadhaar, mobile, bank account fields | Yes — being read |
| Tokenisation | `PAN:***6789`, `AADH:***5678`, `MOBILE:***7890` substituted | No — tokens only |
| Encrypted archive | Original transcript AES-256 encrypted to `/transcripts/` | Yes — for RBI audit only |
| WAL write | Tokenised facts appended to `wal.jsonl` | No |
| `mem0.add()` | Tokenised structured facts sent to local Mem0 | No |
| SLM context | Compacted summary injected into system prompt | No |

---

## 7. Consent — DPDP Act Compliance

India's Digital Personal Data Protection Act 2023 requires explicit, purpose-limited consent before storing personal data. Our consent gate is the first action for any new customer — it is hardcoded to block all `mem0.add()` calls until a consent record exists in the WAL.

| Consent field | Value captured | Stored where |
|---|---|---|
| `consent_id` | UUID generated at capture time | First immutable entry in `wal.jsonl` |
| `scope` | `home_loan_processing` only | WAL + Mem0 memory metadata |
| `retention_period` | 24 months from last session | WAL — triggers auto-delete job at expiry |
| `withdrawal_method` | Customer requests erasure → all Mem0 memories + WAL purged | Erasure certificate written to audit log |

---

## 8. Rajesh's Journey — Session by Session

This is the live demo script. Walk judges through all four sessions to show the system working end-to-end.

### Session 1 — Agent A, Day 1 (cold start)

- **Consent gate fires first. Rajesh confirms DPDP consent. Consent written to WAL as immutable first entry.**
- `mem0.search()` returns nothing — no prior memories. Agent A asks full question set. This is unavoidable and honest.
- Session ends. spaCy NER tokenises PAN. WAL Step 1 writes: income F001 (₹55k, unverified, customer_verbal), employer F002, co-applicant F003 (Sunita).
- `mem0.add()` called. Compact runs. Summary created.

> **Summary after Session 1**
>
> Rajesh [C001] — as of Day 1
> Income: ₹55,000/month [UNVERIFIED — customer verbal]
> Employer: Pune MNC [UNVERIFIED]
> Co-applicant: Sunita (wife) — income unknown
> Consent: DPDP recorded Day 1, scope: home_loan_processing

### Session 2 — Agent B, Day 6

- **Agent B opens session. `mem0.search()` retrieves Rajesh's memories. System prompt Zone 2 filled with summary.**
- Agent B sees: income, employer, Sunita — without asking. Rajesh does not repeat himself.
- Rajesh adds: car loan EMI ₹12k/month, Sunita earns ₹30k/month.
- Mem0 detects: Sunita income extends F003 (co-applicant node). EMI is new fact F004.
- Post-session: Phi-4-Mini derives combined disposable income = (55+30)k − 12k = ₹73k. Derives fact F005 written to WAL with confidence 0.94.
- Compact rewrites summary with EMI, Sunita income, and derived eligibility tier.

> **Summary after Session 2**
>
> Rajesh [C001] — as of Day 6
> Income: ₹55,000/month [UNVERIFIED] | Sunita: ₹30,000/month [UNVERIFIED]
> EMI outgoing: ₹12,000/month (car loan)
> Combined disposable: ₹73,000/month [DERIVED, confidence 0.94]
> Indicative eligibility: ~₹43L [DERIVED — treat as indicative, incomes unverified]

### Session 3 — Agent C, Day 11

- **Agent C opens. Full two-session picture visible before Rajesh says a word.**
- Rajesh uploads 7/12 extract PDF. `doc_parser` extracts: survey number, Nashik district, area sqm, encumbrance status clean.
- Structured land data written to WAL as verified F006 (source: `document_parsed`, verified: true).
- Mem0 stores land record as a new memory node linked to Rajesh's profile.
- Compact updates summary with land section.

### Session 4 — Agent D, Day 19 (the key demo moment)

- **Agent D opens. Full 19-day picture loads. Agent D has never met Rajesh.**
- Rajesh mentions salary revised to ₹62k after appraisal.
- Mem0 conflict detection fires: ₹62k conflicts with existing ₹55k memory. Mem0 updates the memory automatically. Old ₹55k decays.
- WAL appends F007: income ₹62k, relationship: updates, supersedes: F001, verified: false.
- Phi-4-Mini re-derives: updated eligibility ~₹48L. Derives F008 written.
- Compact rewrites summary — only ₹62k appears, flagged [UNVERIFIED — awaiting payslip].
- Agent D says: "Your revised salary of ₹62k gives an indicative eligibility of ~₹48L. To confirm, we will need your latest payslip or Form 16."

> **The moment that wins the demo**
>
> Agent D has never spoken to Rajesh. The system opens with: "Rajesh has spoken to three agents over 19 days. Income revised from ₹55k to ₹62k today (unverified). Co-applicant Sunita ₹30k (unverified). Car EMI ₹12k. Land record: Nashik plot, encumbrance clean. Indicative eligibility ~₹48L pending income verification." Agent D continues the conversation, not a new one.

---

## 9. Hackathon Build Timeline

| Day | Focus | Deliverable by end of day |
|---|---|---|
| Day 1 | Core memory loop | Ollama + Phi-4-Mini running locally. Mem0 self-hosted on ChromaDB. `mem0.add()` and `mem0.search()` working with a test customer profile. |
| Day 2 | Ingestion pipeline | IndicASR transcription pipeline in Docker. spaCy NER tokeniser intercepting PAN and income before any Mem0 write. Encrypted transcript archive. |
| Day 3 | WAL + consent | 15-line WAL write step before every `mem0.add()`. Consent gate middleware blocking writes without consent record. `wal.jsonl` replay on startup. |
| Day 4 | Intelligence layer | Compact step with Phi-4-Mini compactor prompt. Derives inference for combined income and eligibility. Verified field logic in system prompt Zone 2. |
| Day 5 | Demo polish | Rajesh 4-session demo script. FastAPI `/session/start` and `/session/end` endpoints. UI showing memory surfacing in real time. Rehearse judge walkthrough. |

> **Minimum hardware required**
>
> 16GB RAM · 4-core CPU · 500GB SSD · No GPU needed (Phi-4-Mini runs in 4-bit CPU mode at ~4s/response). Entire stack runs on a single laptop for the hackathon demo.

---

## 10. Anticipating the Two Hardest Judge Questions

**Q1: "Why not just use Mem0 cloud — it's faster to set up?"**

Because Mem0 cloud sends customer financial data to external servers. A loan applicant's income, co-applicant name, and EMI history would leave the bank's network. Under India's DPDP Act and RBI data localisation guidelines, this is not permitted for personal financial data. Self-hosted Mem0 uses the identical API with zero egress. The one-day setup cost is the cost of compliance.

**Q2: "What happens if the system produces a wrong eligibility figure and an agent acts on it?"**

Every derived fact in our system carries two properties: `verified` (boolean) and `source` (`customer_verbal` / `document_parsed` / `cbs_fetched` / `derived`). The system prompt instructs the SLM to surface [UNVERIFIED] and [DERIVED — INDICATIVE] warnings on any figure used in an eligibility statement where the underlying income has not been backed by a parsed document. No eligibility figure is presented as final — it is always "indicative, pending verification." The agent is prompted to request the document. The system assists — it does not decide.

---

## 11. The Two-Sentence Pitch

> **Every loan customer in India repeats themselves to every new agent — this is not a UX problem, it is an architecture problem.**
>
> *We built a write-ahead-logged, bilingual, on-premise memory layer using Mem0 + Phi-4-Mini that gives every loan officer a customer's complete financial context the moment they open a session — with PAN and income never leaving the bank server.*

---

*PS-01 Hackathon Build Plan | Confidential | Build it.*