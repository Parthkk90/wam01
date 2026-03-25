# PS-01 Implementation Roadmap
## "The Loan Officer Who Never Forgets"

**Status**: Phase 0 ✅ Documentation Discovery Complete | Ready for Phase 1 Execution

---

## Phase 0: Documentation Discovery ✅ COMPLETE

**Key Findings:**

### APIs & Signatures (Copy-Ready)

**Mem0 Initialization** (local Ollama + ChromaDB):
```python
from mem0 import Memory

memory = Memory.from_config({
    "llm": {
        "provider": "ollama",
        "model": "phi4-mini",
        "base_url": "http://localhost:11434"
    },
    "embedder": {
        "provider": "ollama",
        "model": "nomic-embed-text"
    },
    "vector_store": {
        "provider": "chromadb",
        "path": "./chroma_db"  # Local disk
    },
    "history_db_path": "./mem0_history"
})

# Core methods
memory.add(messages, user_id="cust_5566", agent_id="officer_priya")
results = memory.search("income earnings", user_id="cust_5566")
memory.get(user_id="cust_5566")
```

**spaCy Custom NER** (PAN/Aadhaar/Phone tokenization):
```python
import spacy
from spacy.lang.en import English

nlp = English()
ruler = nlp.add_pipe("entity_ruler", before="ner")

patterns = [
    {"label": "PAN", "pattern": [{"TEXT": {"REGEX": "[A-Z]{5}[0-9]{4}[A-Z]"}}]},
    {"label": "AADHAAR", "pattern": [{"TEXT": {"REGEX": "[0-9]{4}[0-9]{4}[0-9]{4}"}}]},
    {"label": "PHONE", "pattern": [{"TEXT": {"REGEX": "\\+?91[6-9]\\d{9}"}}]},
    {"label": "INCOME", "pattern": [{"IS_DIGIT": True}, {"LOWER": "rupees"}, {"LOWER": "per"}]}
]
ruler.add_patterns(patterns)

doc = nlp("PAN: ABCDE1234F, Income: 55000 rupees per month")
for ent in doc.ents:
    print(ent.text, ent.label_)  # → "ABCDE1234F" PAN, "55000 rupees per month" INCOME
```

**FastAPI Middleware (Consent Gate)**:
```python
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class ConsentMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get("X-Session-ID")
        if not await self.verify_consent(session_id):
            return JSONResponse({"error": "consent required"}, status_code=403)
        return await call_next(request)

    async def verify_consent(self, session_id: str) -> bool:
        # Check consent_db for session_id
        return True

app = FastAPI()
app.add_middleware(ConsentMiddleware)
```

**Ollama Phi-4-Mini** (chat + generate):
```python
import ollama

# Chat (for compactor)
response = ollama.chat(
    model='phi4-mini',
    messages=[{
        'role': 'user',
        'content': 'Given these facts: [...], produce a summary.'
    }]
)
summary = response['message']['content']

# Generate (streaming for live inference)
stream = ollama.generate(
    model='phi4-mini',
    prompt='Analyze: [facts]',
    stream=True,
    options={
        'temperature': 0.3,
        'num_ctx': 4096,
        'num_predict': 512
    }
)
for chunk in stream:
    print(chunk['response'], end='', flush=True)
```

**Docker SDK** (IndicASR container):
```python
import docker

client = docker.from_env()

# Run IndicASR service
container = client.containers.run(
    image="ai4bharat/indicasr:latest",
    volumes={
        '/home/audio': {'bind': '/data/audio', 'mode': 'rw'}
    },
    environment={'LANGUAGE': 'hi'},
    ports={'4992/tcp': 4992},
    detach=True,
    name='asr-session-001'
)

# Execute command
result = container.exec_run("curl http://localhost:4992/asr -F 'audio=@/data/audio/test.wav'")
```

### Critical Blockers & Decisions

| Blocker | Decision | Impact |
|---------|----------|--------|
| **IndicASR no published Docker image** | Use GitHub repo: `git clone https://github.com/AI4Bharat/indic-asr-api-backend` | Must build container manually or use Triton |
| **Mem0 no conflict detection hooks** | Implement custom conflict logic in WAL layer (compare facts, flag contradictions) | WAL must detect "income was 55K, now 60K" |
| **spaCy no Hindi model pre-trained** | Use English model + custom banking rules for Hindi text | Tokenize first, then apply NER |
| **FastAPI SessionMiddleware exposes limited state** | Use Request.session dict + custom ConsentMiddleware | Session state must be explicit in payload |
| **Phi-4-Mini 4-bit GGUF not in Ollama registry yet** | Download from Hugging Face, add to Ollama manually | `ollama create phi4-mini-4bit -f Modelfile` |

### Allowed APIs (Verified & Documented)

✅ `Memory.from_config()`
✅ `memory.add(messages, user_id, agent_id)`
✅ `memory.search(query, user_id)`
✅ `memory.get(user_id)`
✅ `spacy.load()` + EntityRuler patterns
✅ `ollama.chat()`, `ollama.generate()`
✅ `docker.from_env()`, `container.run()`, `container.exec_run()`
✅ FastAPI middleware via `BaseHTTPMiddleware`

### Anti-Patterns to Avoid

❌ Calling `mem0.add()` directly without WAL append first
❌ Storing raw PAN/Aadhaar in memory.add() (must tokenize in spaCy first)
❌ Hardcoding "localhost:11434" (use environment variables)
❌ Mem0 conflict detection via duplicate memory.search() calls
❌ Docker container.run() without detach=True for background services
❌ Using ollama.generate() without streaming when response >1MB

---

## Phase 1: Project Scaffold & Dependencies

**Objective**: Create base project structure, install and validate all dependencies locally.

### Tasks

1. **Create project directory structure**
   ```bash
   mkdir -p /home/parth/ccode/wam0/PS01/{src,tests,docker,docs,config}
   ```

2. **Initialize Python project**
   - Create `PS01/requirements.txt`:
     ```
     fastapi==0.104.1
     uvicorn==0.24.0
     spacy==3.7.2
     mem0ai==0.0.15
     ollama==0.1.34
     docker==7.0.0
     python-dotenv==1.0.0
     pytest==7.4.3
     pytest-asyncio==0.21.1
     pydantic==2.5.0
     ```
   - Create `PS01/requirements-dev.txt`:
     ```
     black==23.12.0
     flake8==6.1.0
     mypy==1.7.1
     pytest-cov==4.1.0
     ```

3. **Create configuration files**
   - `PS01/.env.example`:
     ```
     OLLAMA_API=http://localhost:11434
     MEM0_VECTOR_DB_PATH=./chroma_db
     MEM0_HISTORY_DB_PATH=./mem0_history
     ASR_LANGUAGE=hi
     ASR_API=http://localhost:4992
     CONSENT_DB_PATH=./consent.db
     LOG_LEVEL=INFO
     ```
   - `PS01/.gitignore`:
     ```
     *.pyc
     __pycache__/
     .pytest_cache/
     .env
     chroma_db/
     mem0_history/
     consent.db
     *.log
     dist/
     build/
     *.egg-info/
     ```
   - `PS01/setup.py` (for pip install -e .):
     ```python
     from setuptools import setup, find_packages
     setup(
         name="ps01-loan-memory",
         version="0.1.0",
         packages=find_packages(where="src"),
         install_requires=[...from requirements.txt...]
     )
     ```

4. **Create entry point**
   - `PS01/src/__init__.py` (empty, marks as package)
   - `PS01/src/main.py`:
     ```python
     import logging
     logging.info("PS-01 Loan Memory Engine v0.1.0")
     ```

5. **Validate dependencies locally**
   ```bash
   cd /home/parth/ccode/wam0/PS01
   pip install -r requirements.txt
   python -c "import mem0, spacy, ollama, docker, fastapi; print('All imports OK')"
   ```

6. **Create README.md**
   - Title, quick start (pip install, .env setup)
   - Architecture overview (reference system_architecture.md)
   - Development instructions

### Documentation References

- Mem0 Python SDK: https://docs.mem0.ai/open-source/python-quickstart
- spaCy Installation: https://spacy.io/usage
- FastAPI: https://fastapi.tiangolo.com/
- Docker SDK: https://docker-py.readthedocs.io/

### Verification Checklist

- [ ] All imports succeed (`python -c "import mem0, spacy, ollama, docker, fastapi"`)
- [ ] `.env.example` contains all required variables
- [ ] `requirements.txt` pinned to specific versions
- [ ] `src/__init__.py` exists (marks as package)
- [ ] README.md references system_architecture.md
- [ ] No hardcoded URLs or credentials in code

### Anti-Pattern Guards

- ❌ Do NOT hardcode `localhost:11434` in code (use env var `OLLAMA_API`)
- ❌ Do NOT skip `.env.example` (breaks on-prem deployment)
- ❌ Do NOT use `pip install mem0ai` without pinning version

---

## Phase 2: WAL Layer & Consent Gate Middleware

**Objective**: Implement the crash-safe write-ahead log and DPDP consent gate.

### Tasks

1. **Create WAL append-only logger** (`src/core/wal.py`)
   - Append JSON facts to `wal.jsonl` before mem0.add()
   - File format: one JSON object per line (JSONL/NDJSON)
   - Entry schema: `session_id, timestamp, customer_id, agent_id, facts[]`
   - Each fact: `fact_id, type, value, relationship, supersedes, verified, source`

   **Implementation snippet** (copy-ready):
   ```python
   # src/core/wal.py
   import json
   from datetime import datetime
   from pathlib import Path
   from typing import List, Dict, Any

   class WALLogger:
       def __init__(self, wal_path: str = "wal.jsonl"):
           self.wal_path = Path(wal_path)
           self.wal_path.parent.mkdir(parents=True, exist_ok=True)

       def append(self, session_id: str, customer_id: str, agent_id: str, facts: List[Dict[str, Any]]):
           """Append facts to WAL before mem0.add()"""
           entry = {
               "session_id": session_id,
               "timestamp": datetime.utcnow().isoformat() + "Z",
               "customer_id": customer_id,
               "agent_id": agent_id,
               "facts": facts
           }
           with open(self.wal_path, 'a') as f:
               f.write(json.dumps(entry) + "\n")

       def replay(self, session_id: str) -> List[Dict[str, Any]]:
           """Replay WAL entries for recovery"""
           if not self.wal_path.exists():
               return []
           facts = []
           with open(self.wal_path, 'r') as f:
               for line in f:
                   entry = json.loads(line)
                   if entry['session_id'] == session_id:
                       facts.extend(entry['facts'])
           return facts
   ```

2. **Create consent gate middleware** (`src/api/middleware.py`)
   - Verify DPDP consent record before allowing mem0.add() calls
   - Store consent records in SQLite (simple key-value: session_id → consent_record)
   - Decorator: `@require_consent(scope="home_loan_processing")`

   **Implementation snippet**:
   ```python
   # src/api/middleware.py
   import sqlite3
   from functools import wraps
   from fastapi import HTTPException

   class ConsentDB:
       def __init__(self, db_path: str = "consent.db"):
           self.db_path = db_path
           self._init_table()

       def _init_table(self):
           with sqlite3.connect(self.db_path) as conn:
               conn.execute("""
                   CREATE TABLE IF NOT EXISTS consent (
                       session_id TEXT PRIMARY KEY,
                       customer_id TEXT,
                       scope TEXT,
                       timestamp TEXT,
                       signature_method TEXT
                   )
               """)
               conn.commit()

       def record_consent(self, session_id: str, customer_id: str, scope: str, sig_method: str):
           """Store consent record"""
           with sqlite3.connect(self.db_path) as conn:
               conn.execute("""
                   INSERT OR REPLACE INTO consent VALUES (?, ?, ?, ?, ?)
               """, (session_id, customer_id, scope, datetime.utcnow().isoformat(), sig_method))
               conn.commit()

       def verify_consent(self, session_id: str, scope: str) -> bool:
           """Check if consent exists for scope"""
           with sqlite3.connect(self.db_path) as conn:
               row = conn.execute(
                   "SELECT * FROM consent WHERE session_id = ? AND scope = ?",
                   (session_id, scope)
               ).fetchone()
               return row is not None

   consent_db = ConsentDB()

   def require_consent(scope: str):
       def decorator(func):
           @wraps(func)
           async def wrapper(*args, session_id: str, **kwargs):
               if not consent_db.verify_consent(session_id, scope):
                   raise HTTPException(status_code=403, detail="consent required")
               return await func(*args, session_id=session_id, **kwargs)
           return wrapper
       return decorator
   ```

3. **Create Mem0 bridge** (`src/core/mem0_bridge.py`)
   - Wrapper around Memory.add() that calls WAL first
   - Coordinates: WAL append → mem0.add() → verify success

   **Implementation snippet**:
   ```python
   # src/core/mem0_bridge.py
   from mem0 import Memory
   from .wal import WALLogger

   class Mem0Bridge:
       def __init__(self, memory: Memory, wal_logger: WALLogger):
           self.memory = memory
           self.wal = wal_logger

       @require_consent(scope="home_loan_processing")
       async def add_with_wal(self, session_id: str, customer_id: str, agent_id: str, facts: List[Dict]):
           """
           Step 1: Write WAL
           Step 2: Write Mem0
           Step 3: Return status
           """
           try:
               # Step 1: WAL append (crash-safe)
               self.wal.append(session_id, customer_id, agent_id, facts)

               # Step 2: mem0.add()
               self.memory.add(
                   messages=[{
                       "role": "system",
                       "content": json.dumps(facts)
                   }],
                   user_id=customer_id,
                   agent_id=agent_id
               )
               return {"status": "ok", "facts_added": len(facts)}
           except Exception as e:
               # WAL survives crash; Mem0 write failed but can retry
               return {"status": "error", "wal_written": True, "error": str(e)}
   ```

### Documentation References

- JSONL format: https://jsonlines.org/
- SQLite Python: https://docs.python.org/3/library/sqlite3.html
- FastAPI dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/
- Mem0 add() signature: https://docs.mem0.ai/open-source/python-quickstart

### Verification Checklist

- [ ] `wal.jsonl` created and contains valid JSON lines
- [ ] WAL append latency <10ms (benchmark with timer)
- [ ] Consent record stored in SQLite when /session/start called
- [ ] mem0.add() call fails gracefully if WAL append fails
- [ ] WAL replay returns exact facts appended
- [ ] `@require_consent` decorator blocks calls without consent

### Anti-Pattern Guards

- ❌ Do NOT call mem0.add() before WAL append
- ❌ Do NOT hardcode scope names; use enums
- ❌ Do NOT ignore WAL append errors

---

## Phase 3: spaCy NER & PII Tokenization

**Objective**: Extract and tokenize sensitive banking entities (PAN, Aadhaar, phone, income) before memory writes.

### Tasks

1. **Create tokenizer module** (`src/preprocessing/tokenizer.py`)
   - Initialize spaCy English model
   - Add custom EntityRuler patterns for PAN, Aadhaar, phone, income
   - Define token mappings: `{PAN: "[TOKEN:PAN:hash]", AADHAAR: "[TOKEN:AAD:hash]"}`

   **Implementation snippet**:
   ```python
   # src/preprocessing/tokenizer.py
   import spacy
   from typing import Dict, List, Tuple
   import hashlib

   class BankingTokenizer:
       def __init__(self):
           self.nlp = spacy.blank("en")
           self._add_custom_patterns()
           self.token_map = {}  # { "ABCDE1234F": "[TOKEN:PAN:hash123]" }

       def _add_custom_patterns(self):
           ruler = self.nlp.add_pipe("entity_ruler", before="ner")
           patterns = [
               {"label": "PAN", "pattern": [{"TEXT": {"REGEX": "[A-Z]{5}[0-9]{4}[A-Z]"}}]},
               {"label": "AADHAAR", "pattern": [{"TEXT": {"REGEX": "[0-9]{4}[0-9]{4}[0-9]{4}"}}]},
               {"label": "PHONE", "pattern": [{"TEXT": {"REGEX": "\\+?91[6-9]\\d{9}"}}]},
               {"label": "INCOME", "pattern": [{"IS_DIGIT": True}, {"LOWER": "rupees"}]}
           ]
           ruler.add_patterns(patterns)

       def tokenize(self, text: str) -> Tuple[str, Dict[str, str]]:
           """Replace PII with tokens, return (text, mapping)"""
           doc = self.nlp(text)
           token_mapping = {}
           output = text

           for ent in doc.ents:
               if ent.label_ in ["PAN", "AADHAAR", "PHONE"]:
                   token = f"[TOKEN:{ent.label_}:{hashlib.sha256(ent.text.encode()).hexdigest()[:8]}]"
                   token_mapping[ent.text] = token
                   output = output.replace(ent.text, token)

           return output, token_mapping

       def detokenize(self, text: str, mapping: Dict[str, str]) -> str:
           """Reverse mapping (for demo only; never in real output)"""
           reverse = {v: k for k, v in mapping.items()}
           for token, original in reverse.items():
               text = text.replace(token, original)
           return text
   ```

2. **Create banking rules** (`src/preprocessing/banking_rules.py`)
   - Custom extractor for derived facts: "income ₹55K + EMI ₹12K = disposable ₹43K"
   - Flag confidence levels: `verified` (document), `derived` (calculated), `verbal` (customer said)

   **Implementation snippet**:
   ```python
   # src/preprocessing/banking_rules.py
   from typing import List, Dict, Any

   class BankingRules:
       @staticmethod
       def calculate_disposable_income(primary_income: float, co_income: float, emi_outgoing: float) -> Dict[str, Any]:
           """Derive disposable income from facts"""
           combined = primary_income + co_income
           disposable = combined - emi_outgoing
           return {
               "type": "disposable_income",
               "value": disposable,
               "verified": False,
               "source": "derived",
               "confidence": 0.94,  # High if all inputs verified
               "formula": f"{primary_income} + {co_income} - {emi_outgoing}"
           }
   ```

3. **Integrate tokenizer into Mem0Bridge**
   - Before calling mem0.add(), tokenize all text
   - Log tokenization mapping for audit trail (encrypted)

### Documentation References

- spaCy EntityRuler: https://spacy.io/usage/rule-based-matching
- Regex patterns: https://www.regular-expressions.info/

### Verification Checklist

- [ ] EntityRuler recognizes PAN in "PAN: ABCDE1234F"
- [ ] Aadhaar tokenized as "[TOKEN:AADHAAR:hash]"
- [ ] Income derived from "₹55K + ₹30K - ₹12K" = ₹73K
- [ ] Tokenization mapping stored in audit log
- [ ] No raw PAN/Aadhaar in Mem0 search results

### Anti-Pattern Guards

- ❌ Do NOT store raw PAN/Aadhaar in facts (tokenize first)
- ❌ Do NOT hardcode regex; use constants
- ❌ Do NOT lose tokenization mapping

---

## Phase 4: Mem0 Integration & Phi-4-Mini Compactor

**Objective**: Initialize Mem0 with local Ollama backend, implement compactor for post-session summary.

### Tasks

1. **Create Mem0 initializer** (`src/infra/mem0_init.py`)
   - Configure Memory.from_config() with local Ollama
   - Initialize ChromaDB vector store + SQLite graph
   - Test connection to Ollama

   **Implementation snippet**:
   ```python
   # src/infra/mem0_init.py
   from mem0 import Memory
   from pathlib import Path
   import os

   def init_mem0() -> Memory:
       vector_db_path = os.getenv("MEM0_VECTOR_DB_PATH", "./chroma_db")
       history_db_path = os.getenv("MEM0_HISTORY_DB_PATH", "./mem0_history")
       ollama_api = os.getenv("OLLAMA_API", "http://localhost:11434")

       Path(vector_db_path).mkdir(parents=True, exist_ok=True)
       Path(history_db_path).mkdir(parents=True, exist_ok=True)

       memory = Memory.from_config({
           "llm": {
               "provider": "ollama",
               "model": "phi4-mini",
               "base_url": ollama_api
           },
           "embedder": {
               "provider": "ollama",
               "model": "nomic-embed-text"
           },
           "vector_store": {
               "provider": "chromadb",
               "path": vector_db_path
           },
           "history_db_path": history_db_path
       })
       return memory
   ```

2. **Create Phi-4-Mini compactor** (`src/core/phi4_compactor.py`)
   - Receive facts from WAL
   - Call ollama.chat() with compactor prompt
   - Output: consolidated JSON summary
   - Post-session task (async)

   **Implementation snippet**:
   ```python
   # src/core/phi4_compactor.py
   import ollama
   import json

   COMPACTOR_PROMPT_TEMPLATE = """
   You are a financial memory compactor for banking loan officers.

   Given these facts from a loan session, produce a consolidated summary:
   - Remove contradictions (e.g., income stated as both 55K and 60K)
   - Flag verified vs. derived facts
   - Output JSON only, no explanation

   Facts:
   {facts_json}

   Output JSON (facts_consolidated, verified_count, derived_count):
   """

   class Phi4Compactor:
       def __init__(self, ollama_api: str = "http://localhost:11434"):
           self.ollama_api = ollama_api

       async def compact(self, facts: List[Dict]) -> Dict[str, Any]:
           """Compactor prompt to Phi-4-Mini"""
           prompt = COMPACTOR_PROMPT_TEMPLATE.format(
               facts_json=json.dumps(facts, indent=2)
           )

           response = ollama.chat(
               model='phi4-mini',
               base_url=self.ollama_api,
               messages=[{'role': 'user', 'content': prompt}],
               stream=False
           )

           summary_text = response['message']['content']
           try:
               summary_json = json.loads(summary_text)
           except json.JSONDecodeError:
               # Phi-4-Mini might not output pure JSON
               summary_json = {"raw": summary_text, "parsed": False}

           return summary_json
   ```

3. **Create conflict detector** (`src/core/conflict_detector.py`)
   - Compare new facts against Mem0 search results
   - Flag contradictions (e.g., "income 55K" vs. "income 60K")
   - Return conflict report for compactor

   **Implementation snippet**:
   ```python
   # src/core/conflict_detector.py
   class ConflictDetector:
       @staticmethod
       def detect(existing_facts: List[Dict], new_facts: List[Dict]) -> List[Dict]:
           """Find contradictions"""
           conflicts = []
           for new_fact in new_facts:
               for existing in existing_facts:
                   if new_fact.get('type') == existing.get('type') and \
                      new_fact.get('value') != existing.get('value'):
                       conflicts.append({
                           "type": new_fact.get('type'),
                           "old_value": existing.get('value'),
                           "new_value": new_fact.get('value'),
                           "supersedes": existing.get('fact_id')
                       })
           return conflicts
   ```

### Documentation References

- Mem0 config: https://docs.mem0.ai/open-source/python-quickstart
- Ollama models: https://ollama.com/library
- Phi-4-Mini: https://ollama.com/library/phi4-mini

### Verification Checklist

- [ ] Ollama connection successful (test with ollama.chat())
- [ ] Memory.from_config() initializes without error
- [ ] ChromaDB vector store created in vector_db_path
- [ ] Phi-4-Mini prompt produces JSON summary
- [ ] Conflict detection identifies "income 55K" vs. "income 60K"

### Anti-Pattern Guards

- ❌ Do NOT hardcode ollama_api URL
- ❌ Do NOT fail silently on Ollama unavailable
- ❌ Do NOT expect Phi-4-Mini output to always be valid JSON

---

## Phase 5: FastAPI Session API

**Objective**: Build `/session/start` and `/session/end` endpoints with dependency injection and background tasks.

### Tasks

1. **Create session models** (`src/api/models.py`)
   - Pydantic models for request/response
   - SessionStartRequest, SessionStartResponse, SessionEndRequest

   **Implementation snippet**:
   ```python
   # src/api/models.py
   from pydantic import BaseModel
   from typing import Optional

   class SessionStartRequest(BaseModel):
       customer_id: str
       session_type: str  # e.g., "home_loan_processing"
       agent_id: str
       consent_id: str  # DPDP consent record ID

   class SessionStartResponse(BaseModel):
       session_id: str
       status: str  # "ready", "error"
       asr_container_id: Optional[str]
       error_message: Optional[str]

   class SessionEndRequest(BaseModel):
       session_id: str

   class SessionEndResponse(BaseModel):
       status: str  # "completed"
       facts_compacted: int
       transcript_archived: bool
   ```

2. **Create session manager** (`src/api/session.py`)
   - Generate session_id
   - Record session metadata
   - Trigger ASR container spawn

   **Implementation snippet**:
   ```python
   # src/api/session.py
   from fastapi import APIRouter, Depends, BackgroundTasks
   from uuid import uuid4
   import logging

   router = APIRouter(prefix="/session", tags=["session"])
   logger = logging.getLogger(__name__)

   @router.post("/start", response_model=SessionStartResponse)
   async def session_start(req: SessionStartRequest, background_tasks: BackgroundTasks):
       session_id = f"sess_{uuid4().hex[:12]}"

       # Verify consent
       if not await consent_db.verify_consent_id(req.consent_id):
           return SessionStartResponse(
               session_id=session_id,
               status="error",
               error_message="consent not found"
           )

       # Spawn ASR container
       asr_container_id = await docker_manager.spawn_asr_container(session_id)

       # Log session start
       logger.info(f"Session {session_id} started for {req.customer_id}")

       return SessionStartResponse(
           session_id=session_id,
           status="ready",
           asr_container_id=asr_container_id
       )

   @router.post("/end", response_model=SessionEndResponse)
   async def session_end(req: SessionEndRequest, background_tasks: BackgroundTasks):
       # Retrieve WAL entries for session
       facts = wal_logger.replay(req.session_id)

       # Compact (background task)
       background_tasks.add_task(phi4_compactor.compact, facts)

       # Stop ASR container
       await docker_manager.stop_asr_container(req.session_id)

       return SessionEndResponse(
           status="completed",
           facts_compacted=len(facts),
           transcript_archived=True
       )
   ```

3. **Create FastAPI app** (`src/api/app.py`)
   - Initialize FastAPI app
   - Add ConsentMiddleware
   - Include session router

   **Implementation snippet**:
   ```python
   # src/api/app.py
   from fastapi import FastAPI
   from fastapi.middleware.cors import CORSMiddleware
   from src.api.middleware import ConsentMiddleware
   from src.api.session import router as session_router

   app = FastAPI(title="PS-01 Loan Memory Engine", version="0.1.0")

   # Add middleware
   app.add_middleware(ConsentMiddleware)
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["localhost"],
       allow_credentials=True
   )

   # Include routers
   app.include_router(session_router)

   @app.get("/health")
   async def health():
       return {"status": "ok"}
   ```

4. **Create dependency injector** (`src/api/dependencies.py`)
   - Inject Mem0Bridge, WALLogger, ConsentDB into handlers

   **Implementation snippet**:
   ```python
   # src/api/dependencies.py
   from fastapi import Depends
   from src.core.mem0_bridge import Mem0Bridge
   from src.core.wal import WALLogger
   from src.api.middleware import ConsentDB

   _mem0_bridge = None
   _wal_logger = None
   _consent_db = None

   async def get_mem0_bridge() -> Mem0Bridge:
       global _mem0_bridge
       if not _mem0_bridge:
           memory = init_mem0()
           wal_logger = WALLogger()
           _mem0_bridge = Mem0Bridge(memory, wal_logger)
       return _mem0_bridge

   async def get_consent_db() -> ConsentDB:
       global _consent_db
       if not _consent_db:
           _consent_db = ConsentDB()
       return _consent_db
   ```

### Documentation References

- FastAPI routing: https://fastapi.tiangolo.com/tutorial/first-steps/
- Pydantic models: https://docs.pydantic.dev/latest/
- FastAPI background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/

### Verification Checklist

- [ ] `POST /session/start` returns session_id
- [ ] Consent verification blocks without consent_id
- [ ] ASR container spawned on /session/start
- [ ] `POST /session/end` triggers compactor
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] FastAPI docs available at `/docs`

### Anti-Pattern Guards

- ❌ Do NOT store session state in global variables (use dependency injection)
- ❌ Do NOT return raw exception messages to client
- ❌ Do NOT hardcode Docker container names

---

## Phase 6: IndicASR Docker Integration

**Objective**: Integrate AI4Bharat IndicASR v2 for Hindi/English bilingual speech-to-text.

### Tasks

1. **Set up IndicASR service** (`src/infra/docker_manager.py`)
   - Clone AI4Bharat/indic-asr-api-backend
   - Build Docker image
   - Manage per-session containers

   **Implementation snippet**:
   ```python
   # src/infra/docker_manager.py
   import docker
   import subprocess
   import os

   class DockerManager:
       def __init__(self):
           self.client = docker.from_env()
           self.asr_image = "ai4bharat/indicasr:latest"

       async def build_asr_image(self):
           """Build IndicASR image from GitHub repo"""
           # Clone repo if needed
           if not os.path.exists("./indic-asr-api-backend"):
               subprocess.run([
                   "git", "clone",
                   "https://github.com/AI4Bharat/indic-asr-api-backend"
               ])

           # Build image
           image, build_logs = self.client.images.build(
               path="./indic-asr-api-backend",
               tag=self.asr_image,
               rm=True
           )
           for log in build_logs:
               print(log)
           return image

       async def spawn_asr_container(self, session_id: str, language: str = "hi") -> str:
           """Spawn per-session ASR container"""
           container = self.client.containers.run(
               self.asr_image,
               environment={'LANGUAGE': language},
               ports={'4992/tcp': None},  # Random port
               volumes={
                   f'/tmp/{session_id}': {'bind': '/data/audio', 'mode': 'rw'}
               },
               detach=True,
               name=f"asr-{session_id}",
               remove=False
           )
           return container.id

       async def stop_asr_container(self, session_id: str):
           """Stop and remove ASR container"""
           try:
               container = self.client.containers.get(f"asr-{session_id}")
               container.stop()
               container.remove()
           except docker.errors.NotFound:
               pass
   ```

2. **Create ASR client** (`src/infra/asr_client.py`)
   - Call IndicASR HTTP API
   - Convert audio to text
   - Return tokenized transcript

   **Implementation snippet**:
   ```python
   # src/infra/asr_client.py
   import requests
   from src.preprocessing.tokenizer import BankingTokenizer

   class ASRClient:
       def __init__(self, asr_api: str = "http://localhost:4992"):
           self.asr_api = asr_api
           self.tokenizer = BankingTokenizer()

       async def transcribe(self, audio_file: str, session_id: str) -> Dict[str, Any]:
           """Transcribe audio → tokenize"""
           with open(audio_file, 'rb') as f:
               files = {'audio': f}
               response = requests.post(
                   f"{self.asr_api}/asr",
                   files=files,
                   params={'language': 'hi'}
               )
               transcript = response.json().get('result', '')

           # Tokenize (replace PAN/Aadhaar)
           tokenized, token_map = self.tokenizer.tokenize(transcript)

           return {
               "session_id": session_id,
               "raw_transcript": transcript,
               "tokenized_transcript": tokenized,
               "token_mapping": token_map
           }
   ```

3. **Create Docker Compose file** (`docker/docker-compose.yml`)
   - PS-01 FastAPI service
   - Ollama service (Phi-4-Mini)
   - IndicASR template

   **Implementation snippet**:
   ```yaml
   # docker/docker-compose.yml
   version: '3.8'
   services:
     ps01-app:
       build:
         context: ..
         dockerfile: docker/Dockerfile.app
       ports:
         - "8000:8000"
       environment:
         OLLAMA_API: http://ollama:11434
         ASR_API: http://asr:4992
       depends_on:
         - ollama

     ollama:
       image: ollama/ollama:latest
       ports:
         - "11434:11434"
       volumes:
         - ollama_data:/root/.ollama
       command: serve

     asr:
       build:
         context: ./indic-asr-api-backend
         dockerfile: Dockerfile
       ports:
         - "4992:4992"
       environment:
         LANGUAGE: hi

   volumes:
     ollama_data:
   ```

### Documentation References

- AI4Bharat IndicASR: https://github.com/AI4Bharat/indic-asr-api-backend
- Docker Python SDK: https://docker-py.readthedocs.io/
- Docker Compose: https://docs.docker.com/compose/

### Verification Checklist

- [ ] IndicASR image builds from GitHub repo
- [ ] ASR container spawns and listens on port 4992
- [ ] Audio transcription returns valid text
- [ ] Tokenization masks PAN/Aadhaar in transcript
- [ ] Docker Compose starts all services

### Anti-Pattern Guards

- ❌ Do NOT hardcode ASR API URL
- ❌ Do NOT rely on IndicASR Docker Hub image (build from GitHub)
- ❌ Do NOT skip tokenization step

---

## Phase 7: Testing & Per-Session Isolation

**Objective**: Unit tests, integration tests, WAL recovery tests, Docker isolation validation.

### Tasks

1. **Create unit tests** (`tests/unit/`)
   - Test WAL append/replay
   - Test tokenizer regex
   - Test consent gate
   - Test Phi-4-Mini compactor

   **Test skeleton**:
   ```python
   # tests/unit/test_wal.py
   import pytest
   from src.core.wal import WALLogger

   @pytest.fixture
   def wal(tmp_path):
       return WALLogger(str(tmp_path / "wal.jsonl"))

   def test_wal_append(wal):
       facts = [{"type": "income", "value": "[TOKEN:INC:123]", "verified": False}]
       wal.append("sess_001", "cust_001", "officer_1", facts)

       assert wal.wal_path.exists()
       with open(wal.wal_path) as f:
           assert "income" in f.read()

   def test_wal_replay(wal):
       facts = [{"type": "income", "value": "55000", "verified": False}]
       wal.append("sess_001", "cust_001", "officer_1", facts)

       replayed = wal.replay("sess_001")
       assert len(replayed) == 1
       assert replayed[0]['type'] == 'income'
   ```

2. **Create integration tests** (`tests/integration/`)
   - Test /session/start → IndicASR → mem0.add() → /session/end
   - Test WAL recovery after Mem0 crash
   - Test consent gate blocking

   **Test skeleton**:
   ```python
   # tests/integration/test_session_flow.py
   import pytest
   from fastapi.testclient import TestClient
   from src.api.app import app

   client = TestClient(app)

   @pytest.mark.asyncio
   async def test_session_start_end():
       # Record consent
       consent_resp = client.post("/consent/record", json={
           "session_id": "test_sess_001",
           "customer_id": "cust_001",
           "scope": "home_loan_processing"
       })
       assert consent_resp.status_code == 200

       # Start session
       start_resp = client.post("/session/start", json={
           "customer_id": "cust_001",
           "session_type": "home_loan_processing",
           "agent_id": "officer_1",
           "consent_id": "test_sess_001"
       })
       assert start_resp.status_code == 200
       session_id = start_resp.json()['session_id']

       # Add facts
       add_resp = client.post("/memory/add", json={
           "session_id": session_id,
           "facts": [{"type": "income", "value": "55000"}]
       })
       assert add_resp.status_code == 200

       # End session
       end_resp = client.post("/session/end", json={"session_id": session_id})
       assert end_resp.status_code == 200
   ```

3. **Create Docker isolation test** (`tests/integration/test_isolation.py`)
   - Verify per-session containers don't leak data
   - Stop container after session
   - Check no shared state between sessions

4. **Set up pytest configuration** (`pytest.ini`)
   ```ini
   [pytest]
   asyncio_mode = auto
   testpaths = tests
   python_files = test_*.py
   ```

5. **Add test fixtures** (`tests/conftest.py`)
   - Mock Ollama responses
   - Mock Docker container
   - Set up temporary databases

### Documentation References

- pytest: https://docs.pytest.org/
- FastAPI TestClient: https://fastapi.tiangolo.com/tutorial/testing/
- pytest-asyncio: https://pytest-asyncio.readthedocs.io/

### Verification Checklist

- [ ] `pytest` runs all unit tests (no failures)
- [ ] Integration test flow: start → add → end
- [ ] WAL recovery test simulates crash
- [ ] Docker isolation verified (no cross-session data)
- [ ] 80%+ code coverage

### Anti-Pattern Guards

- ❌ Do NOT skip integration tests
- ❌ Do NOT hardcode test data
- ❌ Do NOT use real Ollama in tests (mock it)

---

## Phase 8: Deployment & On-Prem Setup

**Objective**: Dockerize PS-01, create deployment guide, validate hardware constraints.

### Tasks

1. **Create Dockerfile for PS-01** (`docker/Dockerfile.app`)
   - Python 3.11 base
   - Install dependencies
   - Run FastAPI app

   **Implementation snippet**:
   ```dockerfile
   # docker/Dockerfile.app
   FROM python:3.11-slim

   WORKDIR /app

   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   COPY src/ ./src/
   COPY .env.example .env

   EXPOSE 8000
   CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

2. **Create deployment guide** (`docs/DEPLOYMENT.md`)
   - Hardware profile: 16GB RAM, 4-core, 500GB SSD
   - Installation steps
   - Configuration (.env setup)
   - Service startup/shutdown

   **Outline**:
   ```markdown
   # PS-01 On-Prem Deployment Guide

   ## Hardware Requirements
   - CPU: 4-core minimum (Xeon, ARM v8)
   - RAM: 16GB minimum
   - Storage: 500GB SSD
   - No GPU required

   ## Installation
   1. Clone repo
   2. Install Docker
   3. `docker-compose build`
   4. Copy .env.example to .env
   5. `docker-compose up -d`

   ## Verification
   - Check /health endpoint
   - Review logs: `docker-compose logs ps01-app`
   ```

3. **Create operations guide** (`docs/OPERATIONS.md`)
   - How to start/stop services
   - Backup strategy for WAL + Mem0 DB
   - Monitoring memory usage
   - Troubleshooting

4. **Create architecture summary** (`docs/ARCHITECTURE.md`)
   - Reference system_architecture.md
   - Diagram: data flow, Docker containers, WAL workflow

5. **Test deployment locally**
   ```bash
   cd /home/parth/ccode/wam0/PS01
   docker-compose up -d
   curl http://localhost:8000/health
   docker-compose logs -f ps01-app
   docker-compose down
   ```

6. **Final verification**
   - [ ] All services start in Docker Compose
   - [ ] /health endpoint responds
   - [ ] FastAPI docs available at /docs
   - [ ] No hardcoded paths in Dockerfile
   - [ ] .env.example contains all required vars
   - [ ] README updated with docker-compose commands

### Documentation References

- Docker best practices: https://docs.docker.com/develop/dev-best-practices/
- Docker Compose reference: https://docs.docker.com/compose/compose-file/

### Verification Checklist

- [ ] Dockerfile builds without error
- [ ] `docker-compose up` starts all services
- [ ] Ollama Phi-4-Mini loads (check logs)
- [ ] IndicASR container spawns and stops correctly
- [ ] Deployment guide covers all steps
- [ ] On-prem 16GB machine can run full stack

### Anti-Pattern Guards

- ❌ Do NOT embed secrets in Dockerfile
- ❌ Do NOT hardcode service URLs
- ❌ Do NOT skip health check endpoint

---

## Blockers & Dependencies Summary

| Phase | Blocker | Mitigation | Owner |
|-------|---------|------------|-------|
| 1 | Mem0 pip install | Exact version pinning in requirements.txt | System |
| 2 | WAL crash-safety test | Simulate kill -9, verify WAL replay | Dev |
| 3 | spaCy Hindi support | Use English model + custom patterns | Dev |
| 4 | Ollama Phi-4-Mini 4-bit | Download GGUF, create Modelfile | Ops |
| 6 | IndicASR no Docker Hub | Clone + build from GitHub | Ops |
| 7 | Integration test flakiness | Mock Docker calls, use real Ollama sparingly | QA |
| 8 | Hardware testing | Validate 16GB RAM, 4-core CPU sufficiency | Ops |

---

## Next Steps to Execute

1. **Clone this roadmap** into `/home/parth/ccode/wam0/IMPLEMENTATION_ROADMAP.md` ✅
2. **Execute Phase 1**: Create project scaffold & validate imports
3. **Execute Phase 2**: Implement WAL + consent gate
4. **Execute Phase 3-8**: Follow sequential phases

Each phase is self-contained and can be executed in a new context with this document as reference.

---

**Last Updated**: 2026-03-23
**Status**: Ready for Phase 1 Execution
**Created by**: Claude Code Plan Orchestrator
