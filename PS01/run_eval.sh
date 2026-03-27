#!/bin/bash

BASE="http://localhost:8000"
CUSTOMER="cust_rajesh_001"
AGENT="officer_priya"

echo "=============================="
echo " PS-01 EVAL RUNNER"
echo "=============================="

# ── STEP 0: Health check ──────────────────────────────────────────
echo ""
echo "[0] Health check..."
curl -s $BASE/health | python3 -m json.tool
echo ""

# ── STEP 1: Seed session (plant historical facts) ─────────────────
echo "[1] Starting seed session..."
SEED=$(curl -s -X POST $BASE/session/start \
  -H "Content-Type: application/json" \
  -d "{
    \"customer_id\": \"$CUSTOMER\",
    \"session_type\": \"home_loan_processing\",
    \"agent_id\": \"$AGENT\",
    \"consent_id\": \"consent_rajesh_001\"
  }")
echo $SEED | python3 -m json.tool
SEED_ID=$(echo $SEED | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Seed session ID: $SEED_ID"
echo ""

# ── STEP 2: Add historical facts ─────────────────────────────────
echo "[2] Adding historical facts..."
curl -s -X POST $BASE/memory/add \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SEED_ID\",
    \"customer_id\": \"$CUSTOMER\",
    \"facts\": [
      {\"type\": \"income\",       \"value\": \"55000\",  \"verified\": false, \"source\": \"customer_verbal\"},
      {\"type\": \"co_applicant\", \"value\": \"Sunita\",  \"verified\": false, \"source\": \"customer_verbal\"},
      {\"type\": \"co_income\",    \"value\": \"30000\",  \"verified\": false, \"source\": \"customer_verbal\"},
      {\"type\": \"property\",     \"value\": \"Nashik\", \"verified\": false, \"source\": \"customer_verbal\"},
      {\"type\": \"emi_existing\", \"value\": \"8000\",   \"verified\": false, \"source\": \"customer_verbal\"}
    ]
  }" | python3 -m json.tool
echo ""

# ── STEP 3: End seed session (triggers compactor) ─────────────────
echo "[3] Ending seed session (compactor runs in background)..."
curl -s -X POST $BASE/session/end \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SEED_ID\"}" | python3 -m json.tool
echo ""
echo "Waiting 3s for compactor..."
sleep 3

# ── TEST 1: New session opening ───────────────────────────────────
echo "=============================="
echo "TEST 1 — Opening statement"
echo "=============================="
SESSION=$(curl -s -X POST $BASE/session/start \
  -H "Content-Type: application/json" \
  -d "{
    \"customer_id\": \"$CUSTOMER\",
    \"session_type\": \"home_loan_processing\",
    \"agent_id\": \"$AGENT\",
    \"consent_id\": \"consent_rajesh_002\"
  }")
echo $SESSION | python3 -m json.tool
SESSION_ID=$(echo $SESSION | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session ID: $SESSION_ID"
echo ""
echo ">>> MANUAL CHECK: Does opening_statement sound human? No JSON? Hinglish? ONE fact?"
echo ""

# ── TEST 2: Natural response to customer message ──────────────────
echo "=============================="
echo "TEST 2 — Natural conversation"
echo "=============================="
curl -s -X POST $BASE/session/converse \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION_ID\",
    \"customer_id\": \"$CUSTOMER\",
    \"customer_message\": \"Haan, Nashik wali property ke documents aa gaye hain\"
  }" | python3 -m json.tool
echo ""
echo ">>> MANUAL CHECK: Does agent acknowledge docs without asking for income again?"
echo ""

# ── TEST 3: Income revision detection ────────────────────────────
echo "=============================="
echo "TEST 3 — Income revision"
echo "=============================="
REVISION=$(curl -s -X POST $BASE/session/converse \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION_ID\",
    \"customer_id\": \"$CUSTOMER\",
    \"customer_message\": \"Actually, meri income ab 62000 ho gayi hai, promotion mila\"
  }")
echo $REVISION | python3 -m json.tool
echo ""
REVISED=$(echo $REVISION | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS' if d.get('income_revised') else 'FAIL')" 2>/dev/null)
echo "income_revised check: $REVISED"
echo ""

# ── TEST 4: Does not re-ask known facts ───────────────────────────
echo "=============================="
echo "TEST 4 — No re-asking known facts"
echo "=============================="
curl -s -X POST $BASE/session/converse \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION_ID\",
    \"customer_id\": \"$CUSTOMER\",
    \"customer_message\": \"Toh loan kitna milega mujhe?\"
  }" | python3 -m json.tool
echo ""
echo ">>> MANUAL CHECK: Uses 62000 (not 55000)? Mentions Sunita? Does NOT ask for income?"
echo ""

# ── TEST 5: Cross-session memory (CRITICAL) ───────────────────────
echo "=============================="
echo "TEST 5 — Cross-session memory (CRITICAL)"
echo "=============================="
echo "Ending current session..."
curl -s -X POST $BASE/session/end \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\"}" | python3 -m json.tool
echo ""
echo "Waiting 3s for compactor..."
sleep 3

echo "Starting BRAND NEW session..."
NEW_SESSION=$(curl -s -X POST $BASE/session/start \
  -H "Content-Type: application/json" \
  -d "{
    \"customer_id\": \"$CUSTOMER\",
    \"session_type\": \"home_loan_processing\",
    \"agent_id\": \"$AGENT\",
    \"consent_id\": \"consent_rajesh_003\"
  }")
echo $NEW_SESSION | python3 -m json.tool
NEW_SESSION_ID=$(echo $NEW_SESSION | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo ""
echo ">>> CRITICAL CHECK: Does opening mention 62000 (revised)? Not 55000 (old)?"
echo ">>> If it shows 55000 or nothing — Redpanda bridge is not wired. Fix mem0 call in session/end."
echo ""

# ── TEST 6: PII tokenization ──────────────────────────────────────
echo "=============================="
echo "TEST 6 — PII tokenization (bonus)"
echo "=============================="
curl -s -X POST $BASE/session/converse \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$NEW_SESSION_ID\",
    \"customer_id\": \"$CUSTOMER\",
    \"customer_message\": \"Mera PAN hai ABCDE1234F aur Aadhaar 9876 5432 1098\"
  }" | python3 -m json.tool
echo ""
echo ">>> Checking WAL for raw PAN..."
if grep -q "ABCDE1234F" ../wal.jsonl 2>/dev/null; then
  echo "FAIL — raw PAN found in wal.jsonl"
else
  echo "PASS — no raw PAN in wal.jsonl (or WAL not at ../wal.jsonl, check your path)"
fi
echo ""

# ── TEST 7: Context window (6 messages) ───────────────────────────
echo "=============================="
echo "TEST 7 — Context window (6 turns)"
echo "=============================="
MSGS=("Property registration kab karein?" "Processing fee kitni hogi?" "EMI approximate kya hogi?" "Joint account chahiye kya?" "Insurance mandatory hai?" "Kitne time mein disbursement hoga?")
for i in "${!MSGS[@]}"; do
  echo "Turn $((i+1)): ${MSGS[$i]}"
  RESP=$(curl -s -X POST $BASE/session/converse \
    -H "Content-Type: application/json" \
    -d "{
      \"session_id\": \"$NEW_SESSION_ID\",
      \"customer_id\": \"$CUSTOMER\",
      \"customer_message\": \"${MSGS[$i]}\"
    }")
  TURN=$(echo $RESP | python3 -c "import sys,json; print('turn_count='+str(json.load(sys.stdin).get('turn_count','?')))" 2>/dev/null)
  echo "  $TURN"
done
echo ">>> PASS if no 500 errors and turn 6 response is coherent"
echo ""

# ── TEST 8: Consent gate ──────────────────────────────────────────
echo "=============================="
echo "TEST 8 — Consent gate"
echo "=============================="
CONSENT_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/session/start \
  -H "Content-Type: application/json" \
  -d "{
    \"customer_id\": \"cust_no_consent_999\",
    \"session_type\": \"home_loan_processing\",
    \"agent_id\": \"$AGENT\",
    \"consent_id\": \"INVALID_CONSENT_XYZ\"
  }")
echo "HTTP status: $CONSENT_RESP"
if [ "$CONSENT_RESP" = "403" ] || [ "$CONSENT_RESP" = "400" ]; then
  echo "PASS — blocked without valid consent"
else
  echo "FAIL — should return 403, got $CONSENT_RESP"
fi
echo ""

# ── TEST 9: The exact problem statement scenario ──────────────────
echo "=============================="
echo "TEST 9 — The co-applicant scenario (CRITICAL)"
echo "=============================="
echo "This is the exact sentence from the problem statement."
echo "Starting fresh session for $CUSTOMER..."
FINAL_SESSION=$(curl -s -X POST $BASE/session/start \
  -H "Content-Type: application/json" \
  -d "{
    \"customer_id\": \"$CUSTOMER\",
    \"session_type\": \"home_loan_processing\",
    \"agent_id\": \"$AGENT\",
    \"consent_id\": \"consent_rajesh_final\"
  }")
echo $FINAL_SESSION | python3 -m json.tool
echo ""
echo ">>> CRITICAL CHECK: Does the agent say something like:"
echo ">>> 'Aapne last time Sunita ji ka mention kiya tha — kya unka income factor karein?'"
echo ">>> If YES: your system passes the core judging criterion."
echo ">>> If NO:  cross-session memory is broken. Fix /session/end -> mem0 write."
echo ""

echo "=============================="
echo " ALL TESTS COMPLETE"
echo "=============================="
echo "Tests 5 and 9 are your make-or-break."
echo "If both pass, you meet all judging criteria."
