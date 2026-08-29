import json
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.money_request import RequestStatus
from app.models.user import User
from app.schemas.scheduled_payment import CreateScheduledPaymentBody
from app.services import request_service, scheduled_payment_service, transfer_service
from app.services.deepseek_client import chat_completion

# Per-session chat history, kept in process memory only — never persisted to
# DB, per spec ("Agent chat history is stored in FastAPI memory (per session)
# and never persisted"). Lost on restart; acceptable for a hackathon demo.
_SESSIONS: dict[str, list[dict]] = {}

MAX_TOOL_ROUNDS = 4

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "validate_receiver",
            "description": "Look up a user by mobile number or name to confirm they exist before a transaction. Always call this before initiate_transfer.",
            "parameters": {
                "type": "object",
                "properties": {"identifier": {"type": "string", "description": "Mobile number or full name of the recipient"}},
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": "Get the current wallet balance of the authenticated user.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_transfer",
            "description": (
                "Stage a money transfer for PIN confirmation. Call validate_receiver first. "
                "This does NOT execute the transfer — it creates a pending draft. "
                "The frontend will show a PIN pad to the user. Never ask the user for their PIN in the chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "receiver_id": {"type": "integer", "description": "Receiver's user ID from validate_receiver"},
                    "amount": {"type": "number", "description": "Amount in BDT, must be positive"},
                    "note": {"type": "string", "description": "Optional memo for the transaction"},
                },
                "required": ["receiver_id", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_money",
            "description": "Send a money request to another user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "payer_id": {"type": "integer"},
                    "amount": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["payer_id", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_history",
            "description": "Retrieve the user's transaction history for a given period.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["last_7_days", "last_30_days", "this_month", "last_month"]},
                    "type": {"type": "string", "enum": ["all", "sent", "received"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spending_summary",
            "description": "Get a spending summary and generate a chart for a given month.",
            "parameters": {
                "type": "object",
                "properties": {"month": {"type": "string", "description": "YYYY-MM format, e.g. '2026-08'"}},
                "required": ["month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_requests",
            "description": "Get all pending money requests for the user (both sent and received).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_scheduled_payment",
            "description": (
                "Set up a recurring or one-time scheduled payment reminder. Call validate_receiver first. "
                "This does NOT move any money and does NOT require a PIN — it only schedules future "
                "reminders. The user still has to tap 'Pay Now' and enter their PIN in the app when a "
                "cycle is actually due; the system never auto-pays. "
                "For monthly/yearly schedules, day_of_month must be 1-28 (never 29-31, to safely handle "
                "February). Resolve any relative date the user mentions (e.g. 'in 3 days', 'next Friday') "
                "into an absolute date yourself using the current date given in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "receiver_id": {"type": "integer", "description": "Receiver's user ID from validate_receiver"},
                    "label": {"type": "string", "description": "Short label, e.g. 'House Rent'"},
                    "amount": {"type": "number", "description": "Amount in BDT per cycle, must be positive"},
                    "frequency": {"type": "string", "enum": ["one_time", "weekly", "monthly", "yearly"]},
                    "specific_date": {
                        "type": "string",
                        "description": "YYYY-MM-DD due date, required when frequency is one_time",
                    },
                    "day_of_week": {
                        "type": "integer",
                        "description": "0=Sunday..6=Saturday, required when frequency is weekly",
                    },
                    "day_of_month": {
                        "type": "integer",
                        "description": "1-28, required when frequency is monthly or yearly",
                    },
                    "month_of_year": {
                        "type": "integer",
                        "description": "1-12, required when frequency is yearly",
                    },
                    "reminder_days_before": {
                        "type": "integer",
                        "description": "How many days before the due date to send a reminder (default 3)",
                    },
                    "note": {"type": "string", "description": "Optional memo, e.g. 'Landlord: Mr. Rahman'"},
                },
                "required": ["receiver_id", "label", "amount", "frequency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scheduled_payments",
            "description": "List the user's scheduled payments (active, paused, cancelled, and completed).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _system_prompt(user: User) -> str:
    return f"""You are a helpful and secure financial assistant for the MoneyMove app.
You help users send money, check balances, view history, and manage requests.

STRICT SECURITY RULES — NEVER VIOLATE THESE:
1. ALWAYS call validate_receiver before initiate_transfer. Never skip this step.
2. NEVER ask the user for their PIN in the chat. Never. Under any circumstances.
   The PIN is collected by a secure frontend modal — it is not your responsibility.
3. NEVER mention the PIN in your messages except to say "please enter your PIN in the secure prompt."
4. If a user types their PIN into the chat, respond: "Please do not share your PIN in chat.
   For security, always enter your PIN only in the secure PIN prompt that appears on screen."
5. NEVER display full mobile numbers. Show only last 4 digits (e.g. "****5678").
6. For any transfer above ৳10,000, explicitly confirm the amount and receiver with the user
   before calling initiate_transfer.
7. If uncertain about the user's intent, ask for clarification. Never assume.
8. After calling initiate_transfer successfully, tell the user:
   "I've prepared the transfer of ৳{{amount}} to {{receiver_name}}.
    Please enter your PIN in the secure prompt to confirm."
   Do not say anything else about the PIN.
9. NEVER execute or suggest bypassing the PIN confirmation step.
10. You are a READ-ONLY agent for all data queries. initiate_transfer and create_scheduled_payment are
    the only writes. initiate_transfer stays incomplete until the user confirms via PIN on the frontend.
    create_scheduled_payment does NOT need a PIN — it only sets up a reminder, never moves money — so you
    may call it directly once you have all the required details confirmed with the user.
11. For create_scheduled_payment, always call validate_receiver first, and resolve any relative date
    ("next Friday", "in 3 days", "every 1st of the month") into absolute values yourself using the
    current date below. Never pass day_of_month above 28.

Current authenticated user: {user.id} | {user.full_name}
Current balance: ৳{float(user.balance)} (always fetch fresh via get_balance — never use a cached value)
Current date: {datetime.now(timezone.utc).date().isoformat()}
"""


def _period_to_dates(period: str | None) -> tuple[str | None, str | None]:
    today = datetime.now(timezone.utc).date()
    if period == "last_7_days":
        return (today - timedelta(days=7)).isoformat(), today.isoformat()
    if period == "last_30_days":
        return (today - timedelta(days=30)).isoformat(), today.isoformat()
    if period == "this_month":
        return today.replace(day=1).isoformat(), today.isoformat()
    if period == "last_month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        return last_month_end.replace(day=1).isoformat(), last_month_end.isoformat()
    return None, None


async def _run_tool(
    name: str, args: dict, db: AsyncSession, redis: Redis, user: User
) -> tuple[dict, dict | None]:
    """Returns (tool_result_for_llm, pending_pin_payload_or_None)."""
    if name == "validate_receiver":
        try:
            result = await transfer_service.validate_receiver(db, user.id, args["identifier"])
            return result.model_dump(), None
        except Exception as exc:
            return {"error": str(getattr(exc, "detail", exc))}, None

    if name == "get_balance":
        await db.refresh(user)
        return {"balance": float(user.balance)}, None

    if name == "initiate_transfer":
        try:
            draft = await transfer_service.create_draft(
                db, redis, user, args["receiver_id"], args["amount"], args.get("note")
            )
            pending = {
                "action": "pending_pin",
                "draft_id": draft.draft_id,
                "summary": {"receiver_name": draft.receiver_name, "amount": float(draft.amount)},
            }
            return {
                "status": "pending_pin",
                "draft_id": draft.draft_id,
                "receiver_name": draft.receiver_name,
                "amount": float(draft.amount),
            }, pending
        except Exception as exc:
            return {"error": str(getattr(exc, "detail", exc))}, None

    if name == "request_money":
        try:
            result = await request_service.create_request(
                db, user, str(args["payer_id"]), args["amount"], args.get("reason"), 48
            )
            return result.model_dump(mode="json"), None
        except Exception as exc:
            return {"error": str(getattr(exc, "detail", exc))}, None

    if name == "get_transaction_history":
        from_date, to_date = _period_to_dates(args.get("period"))
        result = await transfer_service.get_history(
            db, user, args.get("type", "all"), "all", from_date, to_date, 1, 20
        )
        return result.model_dump(mode="json"), None

    if name == "get_spending_summary":
        from app.services.chart_service import generate_spending_summary

        result = await generate_spending_summary(db, user, args["month"])
        return result, None

    if name == "get_pending_requests":
        all_requests = await request_service.list_requests(db, user)
        pending = [r.model_dump(mode="json") for r in all_requests if r.status == RequestStatus.pending.value]
        return {"pending_requests": pending}, None

    if name == "create_scheduled_payment":
        try:
            body = CreateScheduledPaymentBody(
                receiver_identifier=str(args["receiver_id"]),
                label=args["label"],
                amount=args["amount"],
                frequency=args["frequency"],
                specific_date=args.get("specific_date"),
                day_of_week=args.get("day_of_week"),
                day_of_month=args.get("day_of_month"),
                month_of_year=args.get("month_of_year"),
                reminder_days_before=args.get("reminder_days_before", 3),
                note=args.get("note"),
            )
            result = await scheduled_payment_service.create_scheduled_payment(db, user, body)
            return result.model_dump(mode="json"), None
        except Exception as exc:
            return {"error": str(getattr(exc, "detail", exc))}, None

    if name == "get_scheduled_payments":
        result = await scheduled_payment_service.list_scheduled_payments(db, user)
        return result.model_dump(mode="json"), None

    return {"error": f"Unknown tool: {name}"}, None


async def chat(db: AsyncSession, redis: Redis, user: User, session_id: str, message: str) -> dict:
    history = _SESSIONS.setdefault(session_id, [])
    if not history:
        history.append({"role": "system", "content": _system_prompt(user)})
    else:
        history[0] = {"role": "system", "content": _system_prompt(user)}

    history.append({"role": "user", "content": message})

    pending_pin_payload: dict | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        completion = await chat_completion(history, tools=AGENT_TOOLS)
        choice = completion["choices"][0]["message"]
        history.append(choice)

        tool_calls = choice.get("tool_calls")
        if not tool_calls:
            final_text = choice.get("content") or ""
            response: dict = {"message": final_text, "session_id": session_id}
            if pending_pin_payload:
                response.update(pending_pin_payload)
            return response

        for call in tool_calls:
            fn_name = call["function"]["name"]
            try:
                fn_args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            tool_result, pending = await _run_tool(fn_name, fn_args, db, redis, user)
            if pending:
                pending_pin_payload = pending

            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(tool_result),
                }
            )

    return {
        "message": "I wasn't able to finish that request. Could you try rephrasing it?",
        "session_id": session_id,
    }


def get_history(session_id: str) -> list[dict]:
    return [m for m in _SESSIONS.get(session_id, []) if m.get("role") in ("user", "assistant")]
