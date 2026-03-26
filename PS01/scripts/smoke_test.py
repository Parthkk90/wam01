#!/usr/bin/env python3
"""
PS-01 Smoke Test — Verify all 8 critical components working end-to-end.

This script tests against real services (Ollama, Redis, Redpanda, Mem0).
No mocks. No pytest. Plain Python.

Run with: python3 scripts/smoke_test.py
"""

import sys
import os
import json
import time
import asyncio
import shutil
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
sys.path.insert(0, "/home/parth/ccode/wam0/PS01")

results = {}


def check_pass(name: str):
    """Mark a check as PASS."""
    results[name] = "PASS"
    print(f"  ✅ {name}: PASS")


def check_fail(name: str, error: str):
    """Mark a check as FAIL and print error."""
    results[name] = f"FAIL: {error[:100]}"
    print(f"  ❌ {name}: FAIL")
    print(f"     Error: {error[:150]}")


def print_summary():
    """Print final results."""
    print()
    print("━" * 50)
    print("PS-01 SMOKE TEST RESULTS")
    print("━" * 50)
    for check in [
        "CHECK 1: Services reachable",
        "CHECK 2: Mem0 init",
        "CHECK 3: WAL append + replay",
        "CHECK 4: PAN tokenization",
        "CHECK 5: Mem0 add + search",
        "CHECK 6: Redis cache",
        "CHECK 7: Redpanda produce",
        "CHECK 8: Phi-4-Mini compactor",
    ]:
        status = results.get(check, "UNKNOWN")
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {check}: {status}")

    print("━" * 50)
    if all(v == "PASS" for v in results.values()):
        print()
        print("✅ ALL 8 CHECKS PASSED — memory layer verified end-to-end")
        print("   Ready for: POST /demo/run-full")
        return True
    else:
        print()
        print("❌ FAILING CHECKS — fix before running demo")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 1 — Services reachable
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    import urllib.request
    
    # Test Ollama
    resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
    data = json.loads(resp.read())
    models = [m["name"] for m in data.get("models", [])]
    phi_ok = any("phi4-mini" in m for m in models)
    
    if not phi_ok:
        raise Exception(f"phi4-mini not found. Models: {models}")
    
    # Test Redis
    import redis as redis_lib
    r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
    r.ping()
    
    # Test Redpanda
    from aiokafka import AIOKafkaProducer
    
    async def probe_redpanda():
        p = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        await p.start()
        await p.stop()
    
    asyncio.run(probe_redpanda())
    
    check_pass("CHECK 1: Services reachable")
except Exception as e:
    check_fail("CHECK 1: Services reachable", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 2 — Mem0 initialises with real Ollama
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from src.infra.mem0_init import init_mem0
    from pathlib import Path
    
    # Use simpler paths that work better with mem0's path joining
    os.environ["MEM0_VECTOR_DB_PATH"] = "./test_chroma"
    os.environ["MEM0_HISTORY_DB_PATH"] = "./test_mem0_hist"
    os.environ["OLLAMA_API"] = "http://localhost:11434"
    
    memory = init_mem0(bank_id="smoke_test")
    assert memory is not None, "Memory object is None"
    
    # Cleanup test data
    import shutil
    shutil.rmtree("./test_chroma", ignore_errors=True)
    shutil.rmtree("./test_mem0_hist", ignore_errors=True)
    
    check_pass("CHECK 2: Mem0 init")
except Exception as e:
    check_fail("CHECK 2: Mem0 init", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 3 — WAL write + read
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from src.core.wal import WALLogger
    
    wal = WALLogger("/tmp/ps01_smoke_wal.jsonl")
    wal.append(
        session_id="SMOKE_S001",
        customer_id="SMOKE_C001",
        agent_id="SMOKE_AGT",
        bank_id="smoke",
        facts=[{
            "fact_id": "SF01",
            "type": "income",
            "value": "55000",
            "verified": False,
            "source": "customer_verbal",
            "relationship": "new"
        }]
    )
    
    replayed = wal.replay("SMOKE_S001")
    assert len(replayed) == 1, f"Expected 1 fact, got {len(replayed)}"
    assert replayed[0]["fact_id"] == "SF01", f"Wrong fact_id: {replayed[0].get('fact_id')}"
    
    # Cleanup
    os.remove("/tmp/ps01_smoke_wal.jsonl")
    
    check_pass("CHECK 3: WAL append + replay")
except Exception as e:
    check_fail("CHECK 3: WAL append + replay", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 4 — BankingTokenizer masks PAN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from src.preprocessing.tokenizer import BankingTokenizer
    
    tokenizer = BankingTokenizer()
    text = "Customer PAN is ABCDE1234F and income 55000"
    tokenized, mapping = tokenizer.tokenize(text)
    
    assert "ABCDE1234F" not in tokenized, f"Raw PAN leaked: {tokenized}"
    assert "[TOKEN:PAN:" in tokenized, f"PAN token not found: {tokenized}"
    assert "ABCDE1234F" in mapping, f"PAN not in mapping: {mapping}"
    
    check_pass("CHECK 4: PAN tokenization")
except Exception as e:
    check_fail("CHECK 4: PAN tokenization", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 5 — Mem0 add + search (real ChromaDB + Ollama)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from src.infra.mem0_init import init_mem0
    import time
    
    start = time.time()
    
    # Use simpler paths
    os.environ["MEM0_VECTOR_DB_PATH"] = "./test_chroma_add"
    os.environ["MEM0_HISTORY_DB_PATH"] = "./test_mem0_add"
    os.environ["OLLAMA_API"] = "http://localhost:11434"
    
    memory = init_mem0(bank_id="add_test")
    
    memory.add(
        [{"role": "user", "content": "income is 55000 rupees monthly"}],
        user_id="SMOKE_C001"
    )
    
    results_search = memory.search("income", user_id="SMOKE_C001")
    elapsed = time.time() - start
    
    assert len(results_search) > 0, "No results from memory search"
    
    # Cleanup
    shutil.rmtree("./test_chroma_add", ignore_errors=True)
    shutil.rmtree("./test_mem0_add", ignore_errors=True)
    
    print(f"  ✅ CHECK 5: Mem0 add + search: PASS (took {elapsed:.1f}s)")
    results["CHECK 5: Mem0 add + search"] = "PASS"
except Exception as e:
    check_fail("CHECK 5: Mem0 add + search", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 6 — Redis cache write + read
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    import redis as redis_lib
    
    r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
    r.set("smoke:test", "ps01_working", ex=60)
    val = r.get("smoke:test")
    
    assert val == "ps01_working", f"Expected 'ps01_working', got '{val}'"
    
    r.delete("smoke:test")
    
    check_pass("CHECK 6: Redis cache")
except Exception as e:
    check_fail("CHECK 6: Redis cache", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 7 — Redpanda produce to loan-facts topic
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from aiokafka import AIOKafkaProducer
    import json
    
    async def produce():
        producer = AIOKafkaProducer(bootstrap_servers="localhost:9092")
        await producer.start()
        try:
            msg = json.dumps({"smoke_test": True, "fact": "income_55000"})
            await producer.send_and_wait("loan-facts", msg.encode())
        finally:
            await producer.stop()
    
    asyncio.run(produce())
    
    check_pass("CHECK 7: Redpanda produce")
except Exception as e:
    check_fail("CHECK 7: Redpanda produce", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK 8 — Phi-4-Mini responds to compactor prompt
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    import ollama as ollama_lib
    import time
    
    start = time.time()
    response = ollama_lib.chat(
        model="phi4-mini",
        messages=[{
            "role": "user",
            "content": (
                "You are a fact compactor. Given this fact: "
                "income=55000 INR monthly, unverified. "
                "Output JSON only: {\"summary\": \"...\", \"verified\": false}"
            )
        }]
    )
    elapsed = time.time() - start
    
    text = response["message"]["content"]
    assert len(text) > 0, "Empty response from Phi-4-Mini"
    assert "55000" in text or "income" in text.lower(), (
        f"Expected 'income' or '55000' in response, got: {text[:100]}"
    )
    
    print(f"  ✅ CHECK 8: Phi-4-Mini compactor: PASS (took {elapsed:.1f}s)")
    results["CHECK 8: Phi-4-Mini compactor"] = "PASS"
except Exception as e:
    check_fail("CHECK 8: Phi-4-Mini compactor", str(e))
    print_summary()
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Final summary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
success = print_summary()
sys.exit(0 if success else 1)
