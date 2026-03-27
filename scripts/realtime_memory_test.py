#!/usr/bin/env python3
"""
Realtime PS01 runner aligned with current API wiring.

Supports:
- Auto end-to-end flow:
  session/start -> session/add-fact -> session/end -> session/start
- Live WAL visibility for the same customer
- Interactive mode for repeated realtime CRUD-style operations
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import ReadTimeout


def _project_root_from_here() -> Path:
    # Script is in <repo>/scripts/. PS01 is expected at <repo>/PS01.
    return Path(__file__).resolve().parents[1]


def _default_wal_path() -> Path:
    env_path = os.getenv("WAL_PATH")
    if env_path:
        return Path(env_path)
    return _project_root_from_here() / "PS01" / "data" / "wal" / "ps01_wal.jsonl"


def api_post(
    base_url: str,
    path: str,
    payload: Dict[str, Any],
    timeout: int,
    retries: int = 2,
) -> Dict[str, Any]:
    url = f"{base_url}{path}"
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code >= 400:
                raise RuntimeError(f"{path} failed [{resp.status_code}]: {resp.text}")
            return resp.json()
        except ReadTimeout as exc:
            last_exc = exc
            if attempt >= retries:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{path} timed out after retries: {last_exc}")


def api_post_query(base_url: str, path_with_query: str, timeout: int) -> Dict[str, Any]:
    url = f"{base_url}{path_with_query}"
    resp = requests.post(url, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"{path_with_query} failed [{resp.status_code}]: {resp.text}")
    return resp.json()


def wait_for_api(base_url: str, timeout: int = 3) -> None:
    resp = requests.get(f"{base_url}/health", timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"health check failed [{resp.status_code}]: {resp.text}")


def start_session(base_url: str, customer_id: str, agent_id: str, session_type: str, timeout: int) -> Dict[str, Any]:
    return api_post(
        base_url,
        "/session/start",
        {
            "customer_id": customer_id,
            "session_type": session_type,
            "agent_id": agent_id,
            "consent_id": f"consent_{customer_id}_{int(time.time())}",
        },
        timeout,
    )


def add_fact(
    base_url: str,
    session_id: str,
    customer_id: str,
    agent_id: str,
    fact_type: str,
    fact_value: str,
    timeout: int,
) -> Dict[str, Any]:
    query = (
        "/session/add-fact"
        f"?session_id={session_id}"
        f"&customer_id={customer_id}"
        f"&agent_id={agent_id}"
        f"&fact_type={fact_type}"
        f"&fact_value={fact_value}"
    )
    return api_post_query(base_url, query, timeout)


def end_session(base_url: str, session_id: str, transcript: str, timeout: int) -> Dict[str, Any]:
    return api_post(
        base_url,
        "/session/end",
        {
            "session_id": session_id,
            "transcript": transcript,
        },
        timeout,
    )


def converse(
    base_url: str,
    session_id: str,
    customer_id: str,
    message: str,
    timeout: int,
) -> Dict[str, Any]:
    return api_post(
        base_url,
        "/session/converse",
        {
            "session_id": session_id,
            "customer_id": customer_id,
            "customer_message": message,
        },
        timeout,
    )


def _read_wal_entries(wal_path: Path) -> List[Dict[str, Any]]:
    if not wal_path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in wal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def show_customer_wal(wal_path: Path, customer_id: str, limit: int = 10) -> None:
    entries = [e for e in _read_wal_entries(wal_path) if e.get("customer_id") == customer_id]
    print(f"\nWAL entries for {customer_id}: {len(entries)}")
    for e in entries[-limit:]:
        ts = e.get("timestamp")
        sid = e.get("session_id")
        aid = e.get("agent_id")
        facts = e.get("facts", [])
        print(f"- {ts} | session={sid} | agent={aid} | facts={len(facts)}")
        for f in facts:
            ftype = f.get("type")
            fval = f.get("value")
            print(f"    {ftype}: {fval}")


def watch_customer_wal(wal_path: Path, customer_id: str, seconds: int = 8) -> None:
    print(f"\nWatching WAL for {customer_id} for {seconds}s...")
    start = time.time()
    seen = 0
    while time.time() - start < seconds:
        entries = [e for e in _read_wal_entries(wal_path) if e.get("customer_id") == customer_id]
        if len(entries) > seen:
            for e in entries[seen:]:
                print(json.dumps(e, ensure_ascii=True))
            seen = len(entries)
        time.sleep(0.5)


def run_auto(base_url: str, wal_path: Path, customer_id: str, timeout: int) -> int:
    agent_a = "AGT_RT_A"
    agent_b = "AGT_RT_B"

    print("\n[1] Starting session 1")
    s1 = start_session(base_url, customer_id, agent_a, "home_loan_processing", timeout)
    session_id = s1.get("session_id")
    if not session_id:
        raise RuntimeError("session/start did not return session_id")
    print(f"session_id={session_id}")
    print(f"greeting={s1.get('greeting_message')}")

    print("\n[2] Adding facts via add-fact endpoint")
    r1 = add_fact(base_url, session_id, customer_id, agent_a, "co_applicant_name", "Sunita", timeout)
    r2 = add_fact(base_url, session_id, customer_id, agent_a, "co_applicant_income", "30000", timeout)
    print(f"add-fact-1 status={r1.get('status')} wal_written={r1.get('wal_written')}")
    print(f"add-fact-2 status={r2.get('status')} wal_written={r2.get('wal_written')}")

    print("\n[3] Ending session 1")
    e1 = end_session(base_url, session_id, "co-applicant Sunita income 30000", timeout)
    print(f"end status={e1.get('status')} facts_count={e1.get('facts_count')}")

    print("\n[4] Starting session 2 (new agent, same customer)")
    s2 = start_session(base_url, customer_id, agent_b, "home_loan_processing", timeout)
    recall = (s2.get("briefing") or {}).get("deterministic_recall")
    print(f"recall={recall}")
    print(f"greeting={s2.get('greeting_message')}")

    print("\n[5] WAL snapshot")
    show_customer_wal(wal_path, customer_id, limit=10)

    return 0


def run_interactive(base_url: str, wal_path: Path, customer_id: str, agent_id: str, timeout: int) -> int:
    print("\nInteractive mode commands:")
    print("  /start                start new session")
    print("  /fact <type> <value>  add fact")
    print("  /end <transcript>     end session")
    print("  /wal                  show WAL entries for customer")
    print("  /watch <seconds>      watch WAL updates for customer")
    print("  /restart              start new session with a different agent")
    print("  /exit                 quit")
    print("  any plain text        send to /session/converse")

    current_session: Optional[str] = None
    current_agent = agent_id

    while True:
        raw = input("\nrealtime> ").strip()
        if not raw:
            continue

        if raw == "/exit":
            return 0

        if raw == "/start":
            s = start_session(base_url, customer_id, current_agent, "home_loan_processing", timeout)
            current_session = s.get("session_id")
            print(f"session_id={current_session}")
            print(f"greeting={s.get('greeting_message')}")
            continue

        if raw.startswith("/fact "):
            if not current_session:
                print("start a session first: /start")
                continue
            parts = raw.split(" ", 2)
            if len(parts) < 3:
                print("usage: /fact <type> <value>")
                continue
            fact_type = parts[1]
            fact_value = parts[2]
            out = add_fact(base_url, current_session, customer_id, current_agent, fact_type, fact_value, timeout)
            print(out)
            continue

        if raw.startswith("/end"):
            if not current_session:
                print("start a session first: /start")
                continue
            transcript = raw[4:].strip() or "session ended"
            out = end_session(base_url, current_session, transcript, timeout)
            print(out)
            current_session = None
            continue

        if raw == "/wal":
            show_customer_wal(wal_path, customer_id, limit=20)
            continue

        if raw.startswith("/watch"):
            parts = raw.split(" ", 1)
            seconds = 8
            if len(parts) == 2:
                try:
                    seconds = int(parts[1])
                except ValueError:
                    pass
            watch_customer_wal(wal_path, customer_id, seconds=seconds)
            continue

        if raw == "/restart":
            current_agent = f"AGT_RT_{int(time.time())}"
            s = start_session(base_url, customer_id, current_agent, "home_loan_processing", timeout)
            current_session = s.get("session_id")
            print(f"agent={current_agent} session_id={current_session}")
            print(f"greeting={s.get('greeting_message')}")
            continue

        # Default path: treat input as customer message and send to converse.
        if not current_session:
            s = start_session(base_url, customer_id, current_agent, "home_loan_processing", timeout)
            current_session = s.get("session_id")
            print(f"auto-started session_id={current_session}")
            print(f"greeting={s.get('greeting_message')}")

        out = converse(base_url, current_session, customer_id, raw, timeout)
        print(f"agent_response={out.get('agent_response')}")
        if out.get("facts_extracted"):
            print(f"facts_extracted={out.get('facts_extracted')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime PS01 CRUD-like memory runner")
    parser.add_argument("--api", default=os.getenv("PS01_API_URL", "http://localhost:8000"), help="API base URL")
    parser.add_argument("--wal-path", default=str(_default_wal_path()), help="WAL file path")
    parser.add_argument("--customer", default=f"judge_rt_{int(time.time())}", help="Customer ID")
    parser.add_argument("--agent", default="AGT_RT", help="Agent ID for interactive mode")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    parser.add_argument("--mode", choices=["auto", "interactive"], default="auto", help="Run mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wal_path = Path(args.wal_path)

    try:
        wait_for_api(args.api)
    except Exception as exc:
        print(f"API not ready: {exc}")
        return 1

    print(f"API={args.api}")
    print(f"WAL={wal_path}")
    print(f"CUSTOMER={args.customer}")

    if args.mode == "auto":
        return run_auto(args.api, wal_path, args.customer, args.timeout)
    return run_interactive(args.api, wal_path, args.customer, args.agent, args.timeout)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
        raise SystemExit(130)
