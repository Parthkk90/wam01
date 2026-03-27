# PS-01: The Loan Officer Who Never Forgets
## Complete Workflow & Step-by-Step System Flow

**Date**: 2026-03-27  
**Status**: Comprehensive System Documentation  
**Purpose**: Understand how the system works at each stage without code implementation details

---

## 📋 Table of Contents

1. [System Overview](#1-system-overview)
2. [Session Initialization Flow](#2-session-initialization-flow)
3. [Conversation & Fact Collection](#3-conversation--fact-collection)
4. [Session End & Processing](#4-session-end--processing)
5. [Event-Driven Memory Pipeline](#5-event-driven-memory-pipeline)
6. [Data Security & Tokenization](#6-data-security--tokenization)
7. [Memory Storage & Retrieval](#7-memory-storage--retrieval)
8. [Compliance & Consent Management](#8-compliance--consent-management)

---

## 1. System Overview

### 1.1 What is PS-01?

PS-01 is a memory-augmented AI system for loan officers. It remembers customer details across multiple conversations so that:
- **Rajesh doesn't repeat himself** — when he speaks to a second officer, the system already knows his income, co-applicant, and existing EMIs
- **No information is lost** — if an officer updates Rajesh's income, the system detects conflicts (e.g., income jumped 75%) and flags them for review
- **Data stays in the bank** — nothing leaves the bank's server; all memory, transcription, and processing happen locally
- **Work in Hindi or English** — the system understands both languages and code-switches between them

### 1.2 Core Components & Their Role

| Component | What it does | When it activates |
|-----------|-------------|-------------------|
| **IndicASR v2** | Transcribe audio (Hindi/English) | Every time an agent talks to customer |
| **spaCy NER** | Detect & hide sensitive data (PAN, Aadhaar, mobile) | Before any fact enters memory |
| **Mem0** | Store facts as relationships (customer → income, co-applicant) | After tokenization & conflict check |
| **ChromaDB** | Vector database for semantic search | When finding related facts |
| **Phi-4-Mini SLM** | Generate greetings, summaries, next steps | At session start & session end |
| **Ollama** | Host Phi-4-Mini locally | Runs as background service |
| **FastAPI** | HTTP API for agents to call | Every agent action (start session, converse, end session) |
| **Redpanda** | Message queue for async processing | When facts need to be validated (conflict check, adversarial check) |
| **WAL (wal.jsonl)** | Append-only log of all facts | Before Mem0 write (crash protection) |

### 1.3 Hardware Requirements

- **CPU-only** (no GPU)
- **16GB RAM** (Phi-4-Mini, Mem0, ChromaDB, Redpanda)
- **500GB SSD** (transcripts archive, Mem0 history, ChromaDB index)
- **Two Docker containers**: IndicASR + Ollama

---

## 2. Session Initialization Flow

### Step 1: Agent Opens Session for Customer

**Trigger**: Loan officer clicks "New/Resume Session" button in their interface

**Input**: 
- Customer ID (or phone number)
- Agent ID (loan officer's ID)
- Bank ID (cooperative bank branch code)

**What happens**:

1. **System checks if customer already exists**
   - Search Mem0 for existing customer profile
   - If no profile → customer is new
   - If profile exists → customer is resuming (has conversation history)

2. **Retrieve previous context** (if resuming)
   - Query Mem0: "What do we know about this customer?"
   - Get back: income, co-applicants, EMIs, documents, last update date
   - Fetch most recent session compaction summary (clean, deduplicated version)

3. **Check consent record**
   - Before showing ANY customer data, verify consent exists in WAL for this customer
   - If no consent → system blocks all memory reads, shows "Consent Required" dialog
   - Agent must obtain explicit consent (signature + timestamp) before proceeding
   - Consent record written to WAL as immutable first entry for customer

4. **Initialize session in-memory**
   - Generate unique `session_id` (e.g., "S004")
   - Create session state object in Redis:
     - `session_id`
     - `customer_id`
     - `agent_id`
     - `bank_id`
     - `start_time`
     - `facts_collected` (empty at start)
     - `conflicts_detected` (empty array)
   - Set session TTL (auto-expire after 8 hours of inactivity)

---

### Step 2: Generate Greeting & Initial Context

**Trigger**: Session initialized, consent verified

**Input**: 
- Customer profile from Mem0 (if resuming)
- Agent's preferred style/tone
- Current date/time

**What happens**:

1. **If NEW customer**:
   - SLM (Phi-4-Mini) generates warm greeting with agent's name
   - Example: "Namaste, I'm Priya, your loan officer. I'm here to help you apply for a home loan. Let me start by understanding your income."
   - Greeting includes next expected step (income verification → co-applicant → document collection)

2. **If RESUMING customer**:
   - System fetches last session's compaction summary from Mem0
   - Summarizer converts summary to natural language
   - SLM generates context-aware greeting that references previous conversation
   - Example: "Welcome back, Rajesh! Last time we confirmed your monthly income as ₹62,000. Today let's verify your co-applicant's documents. Have they changed?"
   - Greeting includes what's **still needed** (not what we already know)

3. **Inject context into Phi-4-Mini system prompt**
   - System prompt now includes:
     - Customer's verified facts (income, co-applicants, EMI obligations)
     - Contradictions flagged from previous sessions
     - What still needs to be collected
     - Loan eligibility estimate (based on income - EMIs)
   - This biases Phi-4 to ask smart next questions, not repeat

4. **Return greeting + next-step guidance to agent**
   - Agent sees greeting on screen
   - Agent sees suggested next question (hardcoded + SLM-generated)

---

## 3. Conversation & Fact Collection

### Step 3: Agent Converses with Customer (Multi-Turn)

**Trigger**: Agent starts talking to customer; system listening

**Input**: 
- Audio stream from agent-customer conversation
- Session context (customer ID, facts collected so far)

**What happens** (for each agent turn):

1. **Transcription**
   - Audio captured → sent to IndicASR v2 Docker container
   - IndicASR recognizes audio as Hindi, English, or code-switched
   - Returns transcription: "Income per month is 55,000 rupees"

2. **Named Entity Recognition (NER) Pass**
   - spaCy reads transcript → identifies sensitive fields:
     - PAN numbers → `[A-Z]{5}[0-9]{4}[A-Z]` pattern
     - Aadhaar numbers → `[0-9]{12}` pattern
     - Mobile numbers → `+91` followed by 10 digits
     - Income amounts → `[digit] rupees per [month/year]`
   - Example: "PAN is ABCDE1234F, income ₹55000" → NER marks `ABCDE1234F` and `55000` as entities

3. **Tokenization** (Security Boundary)
   - PAN `ABCDE1234F` replaced with token `PAN:***1234` (last 4 digits only)
   - Aadhaar `123456789012` replaced with token `AADH:***9012`
   - Mobile `9876543210` replaced with token `MOBILE:***3210`
   - Income kept as numeric `55000` (not sensitive for memory)
   - **Result**: `"Income per month is 55000 rupees, PAN is PAN:***1234"`

4. **Structured Fact Extraction**
   - System converts natural text to structured facts:
     - `type: "income"`
     - `value: "55000_INR_MONTHLY"`
     - `source: "customer_verbal"`
     - `verified: false` (not yet doc-backed)
   - Each fact gets a unique `fact_id` (e.g., "F042")

5. **Suggested Next Question**
   - Phi-4-Mini uses updated system prompt (with new income fact) to suggest next question
   - Example: "Now ask about existing EMI obligations"
   - Agent sees suggestion on screen, can follow or deviate

6. **Store Fact in Session State** (temporary, in-memory)
   - Add to `session.facts_collected`:
     ```
     {
       "fact_id": "F042",
       "type": "income",
       "value": "55000_INR_MONTHLY",
       "relationship": "establishes",
       "source": "customer_verbal",
       "verified": false,
       "timestamp": "2025-03-18T14:15:00"
     }
     ```
   - NOT yet written to Mem0 or WAL (that happens at session end)

---

### Step 4: Multi-Turn Conversation Loop

**Trigger**: Agent continues asking questions

**What happens** (repeat for each agent-customer exchange):

1. **Agent asks question** → (optional: SLM generates suggestion)
2. **Customer responds** → Audio captured
3. **IndicASR transcribes** → NER masks sensitive fields → fact extracted
4. **Fact added to session state** → suggested next question shown
5. **Repeat until agent decides to end session**

**Example conversation trace:**

| Turn | Entity | Text | Fact captured |
|------|--------|------|----------------|
| 1 | Agent | "What is your monthly income?" | — |
| 1 | Customer | "Fifty five thousand rupees" | `income: 55000_INR_MONTHLY` |
| 2 | Agent (SLM-suggested) | "Do you have any existing EMI obligations?" | — |
| 2 | Customer | "Yes, car loan of 8000 and home loan of 15000 per month" | `emi_outgoing: 23000_INR_MONTHLY` |
| 3 | Agent | "Is your wife a co-applicant?" | — |
| 3 | Customer | "Yes, her name is Geeta, she earns 30000 per month" | `co_applicant_income: 30000_INR_MONTHLY` + `co_applicant_name: Geeta` (tokenized) |

---

## 4. Session End & Processing

### Step 5: Agent Ends Session

**Trigger**: Agent clicks "End Session" button or session times out

**Input**: 
- All facts collected during session in memory
- Customer profile from Mem0 (for conflict detection)

**What happens**:

1. **Mark session as closed**
   - Set `session.status = "ended"`
   - Record `end_time` and total duration

2. **Prepare facts for processing**
   - Gather all facts from `session.facts_collected`
   - Add metadata:
     - `session_id`
     - `customer_id` (hashed)
     - `bank_id`
     - `agent_id`
     - `timestamp`

3. **Publish to Redpanda message queue**
   - Create Redpanda message with all facts
   - Publish to topic: `customer-facts-{bank_id}`
   - Message format: JSON with session metadata + facts array

---

## 5. Event-Driven Memory Pipeline

### Step 6: Consume & Process Facts (Async)

**Trigger**: ConsumerOrchestrationService reads from Redpanda queue

**What happens** (for each fact message):

#### 5.6a: Fetch Existing Customer Facts

1. **Check Redis cache first**
   - Query Redis: `customer:{customer_id}:profile`
   - If cached → return instantly (99% case for busy customers)
   - If cache miss → query Mem0 (slower, ~500ms)

2. **Mem0 query**
   - Search Mem0: "What do we know about customer_id?"
   - Returns existing facts:
     - Previous income (e.g., "F001: 60000_INR_MONTHLY")
     - Previous EMI (e.g., "F005: 20000_INR_MONTHLY")
     - Previous co-applicant names
   - Also returns `relationship` metadata (e.g., "F047 updates F001")

3. **Refresh Redis cache**
   - Store in Redis with TTL (1 hour)
   - Next session for same customer hits cache (fast)

---

#### 5.6b: Detect Conflicts

**Input**: New facts from session + existing facts from Mem0

**What happens**:

1. **For each new fact, check if it contradicts existing fact of same type**

   Example:
   - New fact: `income: 62000_INR_MONTHLY`
   - Existing fact: `income: 60000_INR_MONTHLY` (from 2 weeks ago)
   - **Conflict detected?** No (2.4k increase, only 3.3%)

   Another example:
   - New fact: `income: 90000_INR_MONTHLY`
   - Existing fact: `income: 60000_INR_MONTHLY`
   - **Conflict detected?** Yes (30k increase, 50%)

2. **Flag details**:
   - Type of conflict: `numeric_increase` / `text_mismatch` / `structure_change`
   - Old value vs new value
   - Percentage change (for numeric)
   - First flagged time
   - Supersedes relationship (new fact updates old fact)

3. **Store conflict record**
   - Add to conflict log (WAL + Mem0 metadata)
   - Mark fact as `requires_review=true` if conflict significant

---

#### 5.6c: Adversarial Guard Check

**Input**: Conflict details + fact values

**What happens**:

1. **Run banking-specific thresholds**
   - Income change >50%? → `suspicious_flag: true`
   - EMI obligation decrease >30%? → `suspicious_flag: true`
   - Loan amount increased >100%? → `suspicious_flag: true`
   - Any other field type → pass through (no fixed threshold)

2. **Example**:
   - Income jumped from ₹60k to ₹95k (58% increase)
   - Threshold: >50% is suspicious
   - **Result**: `suspicious: true, review_required: true`

3. **Mark in fact**
   - Set `adversarial_flagged: true`
   - Add `review_reason: "Income jumped 58% (₹60k → ₹95k)"`
   - Do NOT block write, but flag for officer review later

---

#### 5.6d: Calculate Derived Facts

**Input**: All customer facts (existing + new)

**What happens**:

1. **Total EMI Burden**
   - Sum all EMI obligations: car loan + home loan + personal loan + etc.
   - Example: 8k + 15k + 5k = 28k per month
   - Store as new derived fact: `total_emi_burden: 28000_INR_MONTHLY`

2. **Net Income**
   - Calculate: gross income - EMI burden
   - Example: 62k - 28k = 34k net per month
   - Store as derived fact: `net_income: 34000_INR_MONTHLY`

3. **Loan Eligibility**
   - Rule: Banks lend 60× monthly net income (5-year EMI ceiling)
   - Example: 34k × 60 = 20.4 lakh eligibility
   - Store as derived fact: `loan_eligibility: 2040000_INR_TOTAL`

4. **When to calculate**:
   - Only if we have income data (income is mandatory)
   - Only if we have EMI data (optional; if missing, assume 0)
   - Every time income or EMI updates → recalculate all three

---

#### 5.6e: Decision & WAL Write

**Input**: All processing results (conflicts, adversarial flags, derived facts)

**What happens**:

1. **Compile final fact record**
   - Combine new facts + derived facts + conflict metadata
   - Create WAL entry with all fields:
     ```
     {
       "session_id": "S004",
       "timestamp": "2025-03-18T14:22:00",
       "customer_id": "hash_C001",
       "bank_id": "COOP_123",
       "facts": [
         {
           "fact_id": "F047",
           "type": "income",
           "value": "62000_INR_MONTHLY",
           "relationship": "updates",
           "supersedes": "F001",
           "verified": false,
           "source": "customer_verbal",
           "conflict": {
             "detected": true,
             "old_value": "60000_INR_MONTHLY",
             "pct_change": 3.3,
             "type": "numeric_increase"
           },
           "adversarial": {
             "checked": true,
             "flagged": false,
             "reason": null
           }
         }
       ]
     }
     ```

2. **Write WAL FIRST** (Write-Ahead Log)
   - Append entry to `wal.jsonl` (local disk, atomic append)
   - **This is the crash-protection guarantee**: if server crashes after this point, facts survive
   - WAL write blocks until disk-synced (slow but safe)

3. **Write to Mem0**
   - Call `memory.add()` with tokenised structured facts
   - Mem0 automatically:
     - Creates relationship edges (income → customer, co-applicant → customer)
     - Detects internal contradictions (using Phi-4-Mini)
     - Stores in SQLite graph + ChromaDB vector index
   - Any fact with `adversarial_flagged: true` is marked for officer review

4. **Return result to ConsumerOrchestrationService**
   - Orchestrator commits Redpanda offset (consumer ack)
   - If error → offset NOT committed, message retried on next consumer restart

---

#### 5.6f: Compaction (Background Job)

**Trigger**: After all facts written to Mem0

**What happens**:

1. **Summarization**
   - Phi-4-Mini reads customer's complete fact history from Mem0
   - Generates clean, deduplicated, current summary:
     ```
     {
       "verified_facts": {
         "income": "₹62,000/month (verbal, needs doc)",
         "emi_outgoing": "₹28,000/month (cars + homes)"
       },
       "derived_facts": {
         "loan_eligibility": "₹20.4L"
       },
       "contradictions": [
         "Income: was ₹60k in previous session, now ₹62k"
       ],
       "next_steps": ["Submit income document", "Get co-applicant sign-off"]
     }
     ```

2. **Deduplication**
   - Phi-4 reads "customer income is 60k" + "customer income is 62k" → outputs "income: ₹62k (was ₹60k)"
   - One sentence per fact instead of multiple entries

3. **Cache in Redis**
   - Store compacted summary in Redis: `customer:{customer_id}:summary`
   - TTL: 24 hours (expires after 1 day, forces refresh)

4. **Next session optimization**
   - When officer starts next session with same customer:
     - Loads compacted summary from Redis (instant)
     - SLM uses this for greeting (avoids reading 15 raw facts)
     - Officer sees "Rajesh's monthly income: ₹62k. We still need: co-applicant documents"

---

## 6. Data Security & Tokenization

### Step 7: What Stays Out of Memory

**Boundary**: Before Mem0 write, sensitive data is masked

#### 6.7a: PAN (Permanent Account Number)

- **Raw**: `ABCDE1234F`
- **In transcript**: "My PAN is ABCDE1234F" (captured by IndicASR)
- **After NER**: Recognized as PAN entity
- **After tokenization**: `PAN:***1234` (last 4 digits visible for manual review, if needed)
- **In Mem0**: Only token stored (`PAN:***1234`), never raw number
- **RBI audit trail**: Raw transcript encrypted, stored offline, accessible only with warrant

#### 6.7b: Aadhaar (National ID Number)

- **Raw**: `123456789012`
- **After tokenization**: `AADH:***9012`
- **In Mem0**: Only token
- **Offline archive**: Raw Aadhaar encrypted in compliance vault

#### 6.7c: Mobile Numbers

- **Raw**: `9876543210`
- **After tokenization**: `MOBILE:***3210`
- **In Mem0**: Only token

#### 6.7d: Income (NOT masked, needed for calculations)

- **Raw**: `55000 rupees per month`
- **Structured**: `{type: "income", value: "55000_INR_MONTHLY"}`
- **In Mem0**: Full numeric value (not sensitive)
- **Used for**: Loan eligibility calculation, conflict detection

#### 6.7e: Co-applicant Names

- **Raw**: "My wife Geeta"
- **After tokenization**: `COAPP_NAME:***` or `PERSON:***` (masked)
- **In Mem0**: Only partial reference if needed, full name encrypted offline

---

### Step 8: Offline Archive (Encrypted)

**Trigger**: Every session end

**What happens**:

1. **Original transcript with PII**
   - Keep raw transcript (for legal disputes)
   - AES-256 encrypt it
   - Store in vault: `/transcripts/{session_id}.aes256`
   - Key stored separately (not in Mem0, not in regular backups)

2. **WAL also has sensitive backup**
   - WAL contains original PII before tokenization (optional design choice)
   - WAL itself should be encrypted at rest (disk-level or file-level)

3. **Access control**
   - Only RBI auditors + legal team can decrypt
   - Audit log every access attempt
   - Key rotation every 90 days

---

## 7. Memory Storage & Retrieval

### Step 9: How Next Session Finds Information

**Trigger**: New session starts with same customer

**What happens**:

1. **Redis cache hit** (most common)
   - Query Redis: `customer:{customer_id}:profile`
   - If exists → return profile instantly (< 10ms)
   - Cached profile includes: verified facts + derived facts + last conflict date

2. **Cache miss fallback to Mem0**
   - Query Mem0 with semantic search: "What does this customer look like?"
   - Mem0 ChromaDB returns top-K semantically similar facts
   - Example: search "income" → returns [income fact, avg_emi fact, loan_request fact]
   - Mem0 SQLite graph returns graph relationships: income → customer, customer → co-applicant

3. **Relationship-aware recall**
   - Instead of "here are all facts," Mem0 returns: "this customer earns ₹62k, has ₹28k EMI, eligible for ₹20.4L"
   - Relationships are explicit (income → customer, not just "income + customer + same session")

4. **Conflict metadata attached**
   - Alongside income fact: "previous value ₹60k, changed 3.3%"
   - Flags like `requires_review: true` visible in profile

---

### Step 10: Memory Update Semantics

**When facts update**:

#### Old-to-New Relationship

- **Old fact**: `F001 = income: ₹60k (from 2 weeks ago)`
- **New fact**: `F047 = income: ₹62k (from today)`
- **Relationship recorded**: `F047.supersedes = F001`
- **In Mem0**: Both facts stored (for audit trail), but next session prioritizes F047
- **In Mem0 summary**: "Income: most recent ₹62k, previous ₹60k, changed 3.3%"

#### Types of Relationships

| Relationship | Meaning | Example |
|---|---|---|
| `establishes` | First time this fact is stated | New customer states income for first time |
| `updates` | Fact replaced by new value | Income revised upward |
| `extends` | Fact refined, not contradicted | "Monthly income ₹60k" → "Monthly income ₹60k + ₹5k bonus" |
| `derives` | Calculated from other facts | `loan_eligibility` derived from `income` + `emi` |
| `contradicts` | Conflict detected, requires review | Income jumped 75%, flagged for verification |

---

## 8. Compliance & Consent Management

### Step 11: Consent Gate (DPDP Act)

**Trigger**: First session with new customer

**What happens**:

1. **Before ANY memory read/write**:
   - Check WAL for consent record: `{consent_id: UUID, customer_id, timestamp, scope}`
   - If no consent record exists → **block all operations**

2. **Obtain consent**:
   - Agent obtains handwritten + digital signature from customer
   - Signature captures:
     - Date & time
     - Purpose: "Home Loan Processing"
     - Scope: Data to be stored (income, documents, co-applicants, NOT PAN)
     - Retention period: "6 months after loan closure"
   - Consent ID generated (UUID tied to customer legal name)

3. **Write consent to WAL**:
   - First immutable entry in customer's WAL: `{consent_id, timestamp, scope, signature_hash}`
   - Signature hash (SHA-256 of signature file) stored for RBI audit
   - Original signature image encrypted + archived

4. **License to operate**:
   - Once consent WAL entry exists, system can read/write memory for this customer
   - Every `mem0.add()` call includes consent_id metadata
   - Every data access logs: "Read customer_id by agent_id under consent_id"

---

### Step 12: Session Audit Trail

**What is logged**:

| What | When | Who can access |
|-----|------|-----------------|
| Session start/end timestamps | Every session | Supervisor + Compliance |
| Facts collected (tokenised) | Every session | Supervisor + Compliance |
| Conflicts detected | When detected | Officer + Compliance |
| Adversarial flags | When triggered | Compliance officer (manual review) |
| Memory writes to Mem0 | Every session end | Compliance audit log |
| PII access (decrypt audit) | On legal request | Legal team + RBI (warrant required) |

---

### Step 13: Redaction for Agent UI

**What agent SEES on screen**:

- ✅ Income: ₹62,000/month
- ✅ EMI obligations: ₹28,000/month
- ✅ Loan eligibility: ₹20.4 lakh
- ✅ Co-applicant: "Geeta" + status (verified/pending)
- ✅ Conflicts: "Income changed 50% from last session"
- ❌ PAN: "PAN:***1234" (never full number on screen)
- ❌ Aadhaar: "AADH:***5678" (masked)
- ❌ Raw transcript: Not shown (compliance vault only)

---

## 📊 Complete Event Flow Diagram

```
Session Start
    ↓
[Check Consent] → Block if no consent
    ↓
[Fetch Memory from Mem0/Redis] → Get customer profile
    ↓
[Phi-4 Greeting + Context Injection] → Agent sees greeting + next-step
    ↓
Multi-Turn Conversation Loop:
  ├─ [IndicASR Transcription] → Hindi/English audio → text
  ├─ [spaCy NER] → Identify sensitive fields (PAN, Aadhaar)
  ├─ [Tokenization] → Mask PII (PAN:***1234)
  ├─ [Structured Extraction] → Create facts (income, EMI, etc.)
  └─ [Add to Session State] → Store temporarily in memory
    ↓
Session End
    ↓
[Compile Facts + Metadata] → Gather all session facts
    ↓
[Publish to Redpanda] → Queue for async processing
    ↓
Async Event Pipeline:
  ├─ [Get Existing Facts] → Query Redis/Mem0
  ├─ [Conflict Detector] → Check contradictions
  ├─ [Adversarial Guard] → Flag suspicious changes
  ├─ [Derives Worker] → Calculate derived facts (loan_eligibility)
  ├─ [Write WAL] → Append-only log (crash-safe)
  ├─ [Write Mem0] → Store in memory graph + vector DB
  └─ [Compactor] → Summarize, deduplicate, cache in Redis
    ↓
Next Session:
  └─ [Get Summary from Redis] → Fast greeting + context
```

---

## 🔄 State Transitions for a Fact

Every fact goes through these states:

```
COLLECTED (in session state)
    ↓
QUEUED (in Redpanda message)
    ↓
CONFLICT_CHECKED (ConflictDetector ran)
    ↓
ADVERSARIAL_CHECKED (AdversarialGuard ran)
    ↓
DERIVED (DerivesWorker calculated related facts)
    ↓
WAL_WRITTEN (Appended to wal.jsonl)
    ↓
MEM0_WRITTEN (Stored in Mem0 + ChromaDB)
    ↓
COMPACTED (Included in post-session summary)
    ↓
CACHED (Cached in Redis for next session)
```

---

## 🎯 Success Criteria for Each Step

| Step | Success Looks Like | Failure Handling |
|------|-------------------|-----------------|
| 1. Session Init | Customer profile loaded, consent verified | Block session, show error |
| 2. Greeting | Agent sees personalized greeting in <2s | Fallback to template |
| 3. Conversation | Transcription + NER + tokenization successful | Retry with fallback NER |
| 4. Fact Collection | All facts clearly marked in session state | Log which facts partial |
| 5. Session End | All facts published to Redpanda | Retry queue (auto-recovery) |
| 6.6a. Get Existing | Facts retrieved from Redis or Mem0 | Continue with empty profile |
| 6.6b. Conflict Check | Conflicts detected + flagged for review | Log conflict, continue |
| 6.6c. Adversarial Guard | Suspicious facts flagged, not written | Write normally, flag for review |
| 6.6d. Derive Facts | Eligibility calculated correctly | Skip derivation if data incomplete |
| 6.6e. WAL Write | Entry appended atomically to wal.jsonl | Crash + retry on restart |
| 6.6e. Mem0 Write | Facts in graph + vector index | Mem0 error shouldn't block WAL |
| 6.6f. Compaction | Summary generated + cached in Redis | Skip compaction, use last summary |
| 8. Consent | Consent record verified in WAL | Block memory access until consent |
| 12. Audit Trail | Log entry created for every operation | Critical: audit trail never fails |

---

## 🚀 Next Session: The Happy Path

When Rajesh calls back 3 days later:

1. **Agent enters session**: System checks consent ✅
2. **System queries Redis**: Gets Rajesh's profile in <10ms
   - Income: ₹62,000/month ✅
   - EMI: ₹28,000/month ✅
   - Eligible for: ₹20.4 lakh ✅
   - Last update: 3 days ago ✅
   - Conflicts: None ✅
3. **SLM generates greeting**: "Welcome back, Rajesh! Last time we confirmed your income as ₹62,000 and total EMI as ₹28,000. Today let's get your co-applicant's documentation. Are you ready?"
4. **Conversation continues**: Agent asks for remaining docs, no repeat of income questions
5. **Rajesh feels heard** ✅

---

## 📝 Summary Table: What Happens at Each Major Checkpoint

| Checkpoint | Input | Output | Systems Involved |
|-----------|-------|--------|------------------|
| Session Init | Customer ID, Agent ID | Session state, customer profile, greeting | Mem0, FastAPI, Phi-4 |
| Audio Collection | Audio stream | Tokenised transcript | IndicASR, spaCy, FastAPI |
| Session End | All facts in session state | Facts published to queue | FastAPI, Redpanda |
| Conflict Detection | New facts + existing facts | Conflict records, flagged facts | ConflictDetector, Mem0 |
| Adversarial Check | Conflict magnitude | Suspicious flags | AdversarialGuard |
| Derivation | Income + EMI data | Eligibility, net_income, emi_burden | DerivesWorker |
| Memory Write | Tokenised + flagged facts | Facts in Mem0 + WAL | Mem0, WAL file system |
| Compaction | Complete customer history | Clean summary in Redis | Phi-4 SLM, Redis |
| Next Session | Customer ID | Profile from Redis (or Mem0 fallback) | Redis, Mem0 |

---

**Document Version**: 1.0  
**Last Updated**: 2026-03-27  
**Maintainer**: Engineering Team  
**Status**: Complete & Ready for Review
