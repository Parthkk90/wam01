# PS-01: The Loan Officer Who Never Forgets

PS-01 is a local, memory-augmented loan assistant for multi-session conversations.
It keeps customer context across agent handoffs with WAL-first durability, Mem0 recall,
and phi4-mini generation through Ollama.

## What Is Current

- Model runtime: `phi4-mini` via Ollama
- Memory strategy: `WAL -> Mem0/Chroma -> Redis cache`
- PII handling: tokenization before storage write paths
- WAL default path: `PS01/data/wal/ps01_wal.jsonl` (durable, configurable via `WAL_PATH`)
- Session behavior: full backend flow (`/session/start`, `/session/converse`, `/session/end`)
- Language behavior: customer language is detected and locked per customer (`hindi` or `english`) and reused in future sessions

## Quick Start (Current Execution)

### 1. Install Dependencies

```bash
cd /home/parth/ccode/wam0/PS01
pip install -r requirements.txt
```

### 2. Export Runtime Environment

```bash
export PYTHONPATH=/home/parth/ccode/wam0/PS01
export REDIS_URL=redis://localhost:6379
export REDPANDA_BROKERS=localhost:9092
export OLLAMA_API=http://localhost:11434
export OLLAMA_HOST=http://localhost:11434
export BANK_ID=cooperative_bank_01
export WAL_PATH=/home/parth/ccode/wam0/PS01/data/wal/ps01_wal.jsonl
```

### 3. Run API Server

```bash
cd /home/parth/ccode/wam0/PS01
uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

### 4. Health Check

```bash
curl -s http://localhost:8000/health
```

## End-to-End Workflow (Realtime)

The active session lifecycle is:

1. Start session: `/session/start`
2. Converse: `/session/converse`
3. End session: `/session/end`
4. Reopen with same customer: `/session/start` again
5. Recall should include previous facts and grounded greeting

### Run Realtime Script (Auto)

From repo root:

```bash
cd /home/parth/ccode/wam0
python3 scripts/realtime_memory_test.py --mode auto --customer judge_rt_demo_01
```

From PS01 folder:

```bash
cd /home/parth/ccode/wam0/PS01
python3 scripts/realtime_memory_test.py --mode auto --customer judge_rt_demo_01
```

### Run Realtime Script (Interactive, Dynamic Input)

```bash
cd /home/parth/ccode/wam0/PS01
python3 scripts/realtime_memory_test.py --mode interactive --customer judge_rt_demo_02 --agent AGT_DYN --timeout 90
```

Interactive mode supports:

- Plain text input -> sent to `/session/converse`
- `/start` -> start session
- `/fact <type> <value>` -> add fact
- `/end <transcript>` -> end session
- `/wal` -> show customer WAL entries
- `/watch <seconds>` -> stream WAL changes for customer
- `/restart` -> new agent with same customer
- `/exit` -> quit

## System Layer Update

### Layer 1: API Layer (FastAPI)

- Session routes in `src/api/session.py`
- Dependency wiring in `src/api/dependencies.py`
- Runtime agent identity comes from session metadata, not hardcoded env only

### Layer 2: Preprocessing Layer

- Tokenization with `BankingTokenizer` before persisted writes
- Prevents raw sensitive values from being written into WAL facts

### Layer 3: Durability Layer (WAL)

- WAL-first rule enforced before memory sync
- Durable WAL file under `PS01/data/wal/ps01_wal.jsonl`
- Timestamp format normalized to UTC `Z`

### Layer 4: Memory Layer (Mem0 + Chroma)

- Mem0 sync follows WAL write
- Briefing retrieval merges WAL facts with Mem0 hits
- Compacted summary can be written and reused as context

### Layer 5: Cache Layer (Redis)

- Session metadata cache (`session:{session_id}`)
- Briefing cache (`briefing:{customer_id}`)
- Summary cache (`summary:{customer_id}`)

### Layer 6: Conversation Layer (phi4-mini)

- Opening/greeting generation via briefing speech builder
- Live conversation via conversation agent
- Deterministic recall fields reduce hallucinated openings

### Layer 7: Language Consistency Layer

- Detect user language from customer message (`hindi` or `english`)
- Persist `preferred_language` as a fact
- Reuse same language for future sessions and greetings
- Prevent language drift across sessions for the same customer

## Core Endpoints

- `POST /session/start`
- `POST /session/converse`
- `POST /session/end`
- `POST /session/add-fact`
- `POST /memory/add`
- `GET /health`

## Validation Scripts

- Smoke test: `python3 scripts/smoke_test.py`
- Realtime test: `python3 scripts/realtime_memory_test.py --mode auto --customer <id>`
- Quick shell flow: `bash quick_test.sh`

## Troubleshooting

- If command returns exit 127: it usually means shell command formatting or unknown command in terminal.
- If API calls return empty/JSON decode errors just after restart: wait 1-2 seconds and retry once.
- If memory seems stale: verify `WAL_PATH`, then inspect latest entries in WAL.

```bash
tail -n 20 /home/parth/ccode/wam0/PS01/data/wal/ps01_wal.jsonl
```

## Additional Docs

- Workflow steps: [WORKFLOW_STEPS.md](WORKFLOW_STEPS.md)
- Memory guide: [docs/MEMORY_LAYER_GUIDE.md](docs/MEMORY_LAYER_GUIDE.md)
- Architecture reference: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
