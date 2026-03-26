"""
Memory Timeline — WAL-based history reconstruction (read-only).

CRITICAL: This module reads from WAL only. Zero Mem0 calls.
"""

import json
from datetime import datetime, UTC
from typing import List, Dict, Any
from pathlib import Path
from dataclasses import dataclass
from src.core.wal import WALLogger


@dataclass
class TimelineEvent:
    """Represents a session's memory activity in timeline."""
    session_id: str
    agent_id: str
    timestamp: str
    facts_added: int
    facts_updated: int
    facts_verified: int
    facts_flagged: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "facts_added": self.facts_added,
            "facts_updated": self.facts_updated,
            "facts_verified": self.facts_verified,
            "facts_flagged": self.facts_flagged
        }


class MemoryTimeline:
    """Reconstruct memory timeline from WAL (read-only, zero mem0 calls)."""

    def __init__(self, wal: WALLogger, memory=None):
        """
        Args:
            wal: WALLogger instance to read from
            memory: Mem0 instance (unused — kept for consistency but NEVER called)
        """
        self.wal = wal
        self.memory = memory  # Intentionally unused

    async def get_timeline(self, customer_id: str) -> List[Dict[str, Any]]:
        """
        Get timeline of all sessions for a customer from WAL.

        Returns:
            List of TimelineEvent dicts in chronological order.
            Empty list if WAL file doesn't exist or no entries found.
        """
        events = []

        # Check if WAL file exists
        if not self.wal.wal_path.exists():
            return events

        # Read WAL and group by session_id
        sessions = {}
        try:
            with open(self.wal.wal_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("customer_id") != customer_id:
                        continue

                    session_id = entry.get("session_id")
                    if session_id not in sessions:
                        sessions[session_id] = {
                            "agent_id": entry.get("agent_id"),
                            "timestamp": entry.get("timestamp", datetime.now(UTC).isoformat()),
                            "facts": []
                        }
                    sessions[session_id]["facts"].extend(entry.get("facts", []))
        except FileNotFoundError:
            return events

        # Convert to TimelineEvent dicts
        for session_id in sorted(sessions.keys()):
            session_data = sessions[session_id]
            facts = session_data["facts"]

            # Count fact types
            facts_added = sum(1 for f in facts if f.get("relationship") == "new")
            facts_updated = sum(1 for f in facts if f.get("relationship") == "updates")
            facts_verified = sum(1 for f in facts if f.get("verified") is True)
            facts_flagged = sum(1 for f in facts if f.get("source") == "pending_review")

            event = TimelineEvent(
                session_id=session_id,
                agent_id=session_data["agent_id"],
                timestamp=session_data["timestamp"],
                facts_added=facts_added,
                facts_updated=facts_updated,
                facts_verified=facts_verified,
                facts_flagged=facts_flagged
            )
            events.append(event.to_dict())

        return events

    async def get_snapshot(self, customer_id: str, up_to_session_id: str) -> List[Dict[str, Any]]:
        """
        Replay WAL up to and including a specific session.

        Args:
            customer_id: Customer ID to filter
            up_to_session_id: Include facts up to this session (inclusive)

        Returns:
            List of fact dicts as they existed at that point in time.
        """
        facts_by_id = {}
        facts_list = []  # Maintain order for facts without IDs

        if not self.wal.wal_path.exists():
            return facts_list

        try:
            with open(self.wal.wal_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("customer_id") != customer_id:
                        continue

                    session_id = entry.get("session_id")

                    # Stop after reaching target session
                    if self._session_id_after(session_id, up_to_session_id):
                        break

                    # Process facts
                    for fact in entry.get("facts", []):
                        fact_id = fact.get("fact_id")
                        
                        if fact.get("relationship") == "updates" and fact_id:
                            # This updates a prior fact
                            if fact_id in facts_by_id:
                                facts_by_id[fact_id] = fact
                            else:
                                facts_by_id[fact_id] = fact
                        elif fact.get("relationship") == "verifies" and fact_id:
                            # Update verification status
                            if fact_id in facts_by_id:
                                facts_by_id[fact_id]["verified"] = True
                                facts_by_id[fact_id]["source"] = fact.get("source", facts_by_id[fact_id].get("source"))
                        elif fact_id:
                            # New fact with ID
                            facts_by_id[fact_id] = fact
                        else:
                            # Fact without ID (add to list in order)
                            facts_list.append(fact)
        except FileNotFoundError:
            pass

        # Combine facts with IDs and facts without IDs
        return list(facts_by_id.values()) + facts_list

    @staticmethod
    def _session_id_after(current: str, target: str) -> bool:
        """Check if current session_id is after target (alphabetically/numerically)."""
        # Assume session IDs are like "S001", "S002", etc.
        try:
            current_num = int(current[1:])
            target_num = int(target[1:])
            return current_num > target_num
        except (ValueError, IndexError):
            # Fallback to string comparison
            return current > target
