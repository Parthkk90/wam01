from fastapi import APIRouter, Request
import logging

from app.database import (
    add_transcript_turn,
    close_call,
    get_recent_memory_by_phone,
    upsert_call_start,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Store calls in memory (just for this session)
calls_log = {}

@router.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"status": "invalid json"}

    event_type = body.get("message", {}).get("type", "")

    if event_type == "call-start":
        return await handle_call_start(body)

    elif event_type == "transcript":
        return await handle_transcript(body)

    elif event_type == "end-of-call-report":
        return await handle_call_end(body)

    return {"status": "ignored"}


@router.get("/memory/context/{phone_number}")
async def get_memory_context(phone_number: str):
    memories = await get_recent_memory_by_phone(phone_number)
    return {"phone_number": phone_number, "memories": memories}


@router.get("/memory/briefing/{phone_number}")
async def get_memory_briefing(phone_number: str):
    memories = await get_recent_memory_by_phone(phone_number, max_calls=3, max_turns_per_call=12)

    # Build a compact, next-agent-friendly summary from stored turns.
    highlights = []
    for mem in memories:
        user_turns = [t["text"] for t in mem.get("turns", []) if t.get("role") == "user"]
        if not user_turns:
            continue
        highlights.append(
            {
                "call_id": mem.get("call_id"),
                "duration_seconds": mem.get("duration_seconds", 0),
                "customer_highlights": user_turns[-3:],
            }
        )

    return {
        "phone_number": phone_number,
        "total_calls_found": len(memories),
        "highlights": highlights,
    }


async def handle_call_start(body: dict):
    msg   = body.get("message", {})
    call  = msg.get("call", {})
    call_id = call.get("id", "unknown")
    phone = call.get("customer", {}).get("number")

    calls_log[call_id] = []
    await upsert_call_start(call_id=call_id, phone_number=phone, metadata={"event": "call-start", "raw": msg})

    print("\n")
    print("=" * 60)
    print(f"📞  CALL STARTED")
    print(f"    Call ID : {call_id}")
    print(f"    Phone   : {phone or 'web call'}")
    print("=" * 60)

    previous = []
    if phone:
        previous = await get_recent_memory_by_phone(phone, max_calls=2, max_turns_per_call=6)
        if previous:
            print("\n🧠  MEMORY CONTEXT FOUND")
            print("-" * 60)
            for mem in previous:
                print(f"Call: {mem['call_id']} | Duration: {mem['duration_seconds']} sec")
                for turn in mem["turns"]:
                    who = "USER" if turn["role"] == "user" else "ASSISTANT"
                    print(f"  {who}: {turn['text']}")
            print("-" * 60)

    return {
        "status": "ok",
        "call_id": call_id,
        "phone_number": phone,
        "memory_context": previous,
    }


async def handle_transcript(body: dict):
    msg     = body.get("message", {})
    call    = msg.get("call", {})
    call_id = call.get("id", "unknown")
    role    = msg.get("role", "unknown")
    text    = msg.get("transcript", "").strip()

    if not text:
        return {"status": "empty"}

    # Save to memory
    if call_id not in calls_log:
        calls_log[call_id] = []
    calls_log[call_id].append({"role": role, "text": text})
    await add_transcript_turn(call_id=call_id, role=role, text=text)

    # Print to terminal nicely
    if role == "user":
        print(f"\n  🧑 USER      : {text}")
    else:
        print(f"  🤖 ASSISTANT : {text}")

    return {"status": "ok"}


async def handle_call_end(body: dict):
    msg      = body.get("message", {})
    call     = msg.get("call", {})
    call_id  = call.get("id", "unknown")
    duration = int(msg.get("durationSeconds", 0))
    full     = msg.get("transcript", "")

    print("\n")
    print("=" * 60)
    print(f"📵  CALL ENDED")
    print(f"    Call ID  : {call_id}")
    print(f"    Duration : {duration} seconds")
    print("=" * 60)
    print("\n📄  FULL TRANSCRIPT:")
    print("-" * 60)
    print(full if full else "No transcript available")
    print("-" * 60)
    print("\n")

    await close_call(call_id=call_id, duration_seconds=duration, full_transcript=full)

    return {"status": "ok"}