#!/bin/bash

BASE="http://localhost:8000"

echo "=== QUICK SYSTEM TEST ==="
echo ""

# 1. Health check
echo "[1] Health check..."
curl -s $BASE/health | python3 -m json.tool
echo ""

# 2. Start session
echo "[2] Starting session..."
SESS_RESPONSE=$(curl -s -X POST $BASE/session/start \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"test_cust_quick","session_type":"home_loan_processing","agent_id":"test_agent","consent_id":"test_consent_ok"}')

SESS_ID=$(echo "$SESS_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id', 'ERROR'))" 2>/dev/null)
echo "Session ID: $SESS_ID"
echo ""

if [ "$SESS_ID" == "ERROR" ] || [ -z "$SESS_ID" ]; then
  echo "Failed to get session ID"
  echo "$SESS_RESPONSE" | python3 -m json.tool
  exit 1
fi

# 3. Test conversation with income revision
echo "[3] Testing conversation with income revision..."
CONV_RESPONSE=$(curl -s -X POST $BASE/session/converse \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESS_ID\",\"customer_id\":\"test_cust_quick\",\"customer_message\":\"Meri income ab 75000 rupees ho gayi hain\"}")

echo "$CONV_RESPONSE" | python3 -m json.tool
echo ""

# 4. Check income_revised  
INCOME_REVISED=$(echo "$CONV_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('income_revised', d.get('memory_updated', d.get('facts_count',0))))" 2>/dev/null)
echo ">>> Income Revised: $INCOME_REVISED"
echo ""

# 5. Document mention test
echo "[4] Testing document mention detection..."
DOC_RESPONSE=$(curl -s -X POST $BASE/session/converse \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESS_ID\",\"customer_id\":\"test_cust_quick\",\"customer_message\":\"Mera payslip bhi attach kar doon?\"}")

echo "$DOC_RESPONSE" | python3 -m json.tool
echo ""

# 6. End session
echo "[5] Ending session..."
curl -s -X POST $BASE/session/end \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESS_ID\"}" | python3 -m json.tool
echo ""

echo "=== TEST COMPLETE ==="
