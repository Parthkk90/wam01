# src/core/wal.py
import json
import os
import threading
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import uuid4


class WALLogger:
    def __init__(self, wal_path: str = "wal.jsonl"):
        self.wal_path = Path(wal_path)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(
        self,
        session_id: str,
        customer_id: str,
        agent_id: str,
        bank_id: str,
        facts: List[Dict[str, Any]],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append facts to WAL before mem0.add().

        WAL rule: always write here BEFORE calling mem0.add().
        Filters out token_mapping to prevent raw PII in WAL.
        """
        # Filter out token_mapping to prevent raw PII leakage
        cleaned_facts = []
        for fact in facts:
            cleaned_fact = {k: v for k, v in fact.items() if k != "token_mapping"}
            cleaned_facts.append(cleaned_fact)
        
        entry = {
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "customer_id": customer_id,
            "agent_id": agent_id,
            "bank_id": bank_id,
            "facts": cleaned_facts,
            "idempotency_key": idempotency_key or str(uuid4()),
            "shipped": False,
        }
        with self._lock:
            with open(self.wal_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def replay(self, session_id: str) -> List[Dict[str, Any]]:
        """Replay WAL entries for recovery."""
        if not self.wal_path.exists():
            return []
        facts = []
        with open(self.wal_path, "r") as f:
            for line in f:
                entry = json.loads(line)
                if entry["session_id"] == session_id:
                    facts.extend(entry["facts"])
        return facts

    def get_unshipped(self) -> List[Dict]:
        """Return all WAL entries where shipped=False."""
        if not self.wal_path.exists():
            return []
        unshipped = []
        with open(self.wal_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if not entry.get("shipped", False):
                    unshipped.append(entry)
        return unshipped

    def get_all_for_customer(self, customer_id: str) -> List[Dict]:
        """Return ALL WAL entries (shipped or not) for a specific customer."""
        if not self.wal_path.exists():
            return []
        entries = []
        with open(self.wal_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("customer_id") == customer_id:
                    entries.append(entry)
        return entries

    def mark_shipped(self, idempotency_key: str) -> None:
        """Find all entries with the given idempotency_key and set shipped=True."""
        if not self.wal_path.exists():
            return
        with self._lock:
            lines = []
            with open(self.wal_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        lines.append(line)
                        continue
                    entry = json.loads(line)
                    if entry.get("idempotency_key") == idempotency_key:
                        entry["shipped"] = True
                    lines.append(json.dumps(entry))
            tmp_path = self.wal_path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                f.write("\n".join(lines))
                if lines:
                    f.write("\n")
            os.replace(tmp_path, self.wal_path)
