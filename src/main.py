"""
main.py — entrypoint for langgraph-assistant.

Routing table
-------------
Intent           | Keywords (sample)                    | Handler
-----------------|--------------------------------------|-------------------------
research         | research, search, what is, explain … | research_graph
gmail read       | email, inbox, unread, summarize mail | gmail_graph (read path)
gmail send       | send email, draft email, reply to …  | gmail_graph (send path)
reminder         | remind me, reminder, don't forget …  | reminder_handler (SQLite)
clear history    | /clear, forget our conversation      | clear_history_handler
general          | (anything else)                      | BaseAgent + memory
"""

import asyncio
import json
import logging
import urllib.request
import urllib.error
from typing import Any, List

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.config import LOG_LEVEL
from src.integrations.gmail import authenticate_gmail
from src.integrations.telegram import TelegramHandler
from src.agents.base import BaseAgent
from src.workflows.research import is_research_intent, research_graph
from src.workflows.job_lookup import is_job_lookup_intent, job_lookup_graph
from src.workflows.gmail_wf import is_gmail_intent, gmail_graph
from src.memory.store import (
    init_db,
    add_message,
    get_history,
    clear_history,
    add_reminder,
    list_reminders,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Intent helpers ────────────────────────────────────────────────────────────
REMINDER_KEYWORDS = {
    "remind me", "reminder", "don't forget", "set a reminder",
    "note to self", "remember to", "memo",
}

LIST_REMINDERS_KEYWORDS = {
    "my reminders", "list reminders", "show reminders", "what are my reminders",
}

CLEAR_HISTORY_COMMANDS = {"/clear", "forget our conversation", "clear history"}

# Gmail Cleanup (via n8n webhook)
N8N_GMAIL_CLEANUP_URL = "http://localhost:5678/webhook/8VOqP3f8IUftharu/webhook/gmail-cleanup"

GMAIL_CLEANUP_KEYWORDS = {
    "clean up spam", "cleanup spam", "delete spam", "spam jobs", "spam emails",
    "clean old promos", "old promotions", "clean promotions", "promo cleanup",
    "unsubscribe cleanup", "clean unsubscribe", "unsubscribe emails",
    "inbox status", "inbox cleanup", "cleanup status", "email cleanup",
    "clean inbox", "trash spam",
}

CLEANUP_ACTION_MAP = {
    "spam_jobs":   {"spam jobs", "spam emails", "betterjobs", "auxsy",
                    "clean up spam", "cleanup spam", "delete spam", "trash spam"},
    "old_promos":  {"old promos", "old promotions", "clean promotions",
                    "promo cleanup", "clean old promo"},
    "unsubscribe": {"unsubscribe cleanup", "clean unsubscribe", "unsubscribe emails"},
    "status":      {"inbox status", "inbox cleanup", "cleanup status",
                    "email cleanup", "clean inbox"},
}


def is_gmail_cleanup_intent(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in GMAIL_CLEANUP_KEYWORDS)


def detect_cleanup_action(text: str) -> str:
    lower = text.lower()
    for action, keywords in CLEANUP_ACTION_MAP.items():
        if any(kw in lower for kw in keywords):
            return action
    return "status"


async def handle_gmail_cleanup(text: str) -> str:
    action = detect_cleanup_action(text)
    payload = json.dumps({"action": action}).encode()
    req = urllib.request.Request(
        N8N_GMAIL_CLEANUP_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        return f"Could not reach n8n cleanup webhook: {exc}"
    except Exception as exc:
        return f"Cleanup error: {exc}"

    if "error" in result:
        return f"Cleanup failed: {result['error']}"

    if action == "status":
        counts = result.get("counts", {})
        lines = [
            f"- Spam job emails (betterjobsonline/auxsy): ~{counts.get('spam_jobs', '?')}",
            f"- Old promotions (>6 months): ~{counts.get('old_promos', '?')}",
            f"- Unsubscribe emails (>6 months): ~{counts.get('unsubscribe', '?')}",
        ]
        return "Inbox Cleanup Status\n" + "\n".join(lines)

    trashed = result.get("trashed", 0)
    label = {
        "spam_jobs": "spam job emails",
        "old_promos": "old promotions",
        "unsubscribe": "unsubscribe emails",
    }.get(action, action)
    return f"Done! Moved {trashed} {label} to trash."



def is_reminder_intent(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in REMINDER_KEYWORDS)


def is_list_reminders_intent(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in LIST_REMINDERS_KEYWORDS)


def is_clear_history(text: str) -> bool:
    lower = text.strip().lower()
    return any(lower == cmd or lower.startswith(cmd) for cmd in CLEAR_HISTORY_COMMANDS)


# ── LangGraph State ───────────────────────────────────────────────────────────
class AssistantState(TypedDict):
    messages: List[Any]
    last_response: str
    chat_id: int


# ── Build general-purpose graph ───────────────────────────────────────────────
def build_assistant_graph():
    agent = BaseAgent(
        name="personal-assistant",
        system_prompt=(
            "You are a helpful personal AI assistant. "
            "You can help with tasks like summarising emails, drafting replies, "
            "setting reminders, and answering questions. "
            "Be concise and friendly."
        ),
    )
    graph = StateGraph(AssistantState)
    graph.add_node("assistant", agent.as_node())
    graph.add_edge(START, "assistant")
    graph.add_edge("assistant", END)
    return graph.compile()


# Module-level graph for LangGraph Studio
graph = build_assistant_graph()


# ── Handlers ──────────────────────────────────────────────────────────────────
async def _run_sync(fn, *args):
    """Run a synchronous callable in a thread pool (keeps event loop free)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


async def handle_reminder(text: str, chat_id: int) -> str:
    """Store a reminder and confirm."""
    reminder_id = await _run_sync(add_reminder, chat_id, text)
    return f"✅ Reminder saved (#{reminder_id}): _{text}_"


async def handle_list_reminders(chat_id: int) -> str:
    reminders = await _run_sync(list_reminders, chat_id)
    if not reminders:
        return "You have no pending reminders."
    lines = [f"#{r['id']} — {r['text']} _(set {r['created'][:16]})_" for r in reminders]
    return "📋 **Your reminders:**\n" + "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    logger.info("Starting langgraph-assistant…")

    # Initialise persistent memory
    init_db()
    logger.info("Memory DB ready.")

    # Optionally initialise Gmail
    gmail_service = authenticate_gmail()
    if gmail_service:
        logger.info("Gmail integration active.")
    else:
        logger.info("Gmail integration disabled (credentials not found).")

    workflow = build_assistant_graph()
    logger.info("LangGraph workflow compiled.")

    telegram = TelegramHandler()

    # Build a BaseAgent instance for history-aware general replies
    general_agent = BaseAgent(
        name="personal-assistant",
        system_prompt=(
            "You are a helpful personal AI assistant. "
            "You can help with tasks like summarising emails, drafting replies, "
            "setting reminders, and answering questions. "
            "Be concise and friendly."
        ),
    )

    async def on_message(text: str, chat_id: int) -> str:
        # ── 0. Special commands ───────────────────────────────────────────
        if is_clear_history(text):
            await _run_sync(clear_history, chat_id)
            return "🧹 Conversation history cleared."

        if is_list_reminders_intent(text):
            return await handle_list_reminders(chat_id)

        # ── 1. Persist user message ───────────────────────────────────────
        await _run_sync(add_message, chat_id, "user", text)

        # ── 2. Route by intent ────────────────────────────────────────────
        answer: str

        if is_gmail_cleanup_intent(text):
            logger.info("Gmail cleanup intent - routing to n8n: %r", text)
            answer = await handle_gmail_cleanup(text)

        elif is_gmail_intent(text):
            logger.info("Gmail intent — routing to gmail_graph: %r", text)
            try:
                result = await _run_sync(
                    gmail_graph.invoke,
                    {"query": text, "gmail_intent": None, "emails": None,
                     "draft_to": None, "draft_subject": None, "draft_body": None,
                     "summary": None, "error": None},
                )
                answer = result.get("summary") or result.get("error") or "(no result)"
            except Exception as exc:
                logger.exception("Gmail workflow error")
                answer = f"Sorry, I ran into a problem with Gmail: {exc}"

        elif is_job_lookup_intent(text):
            logger.info("Job lookup intent — routing to job_lookup_graph: %r", text)
            try:
                result = await _run_sync(
                    job_lookup_graph.invoke,
                    {"query": text, "parsed_params": None,
                     "job_results": None, "formatted_response": None, "error": None},
                )
                answer = result.get("formatted_response") or result.get("error") or "(no result)"
            except Exception as exc:
                logger.exception("Job lookup workflow error")
                answer = f"Sorry, I ran into a problem searching for jobs: {exc}"

        elif is_research_intent(text):
            logger.info("Research intent — routing to research_graph: %r", text)
            try:
                result = await _run_sync(
                    research_graph.invoke,
                    {"query": text},
                )
                answer = result.get("summary") or result.get("error") or "(no result)"
            except Exception as exc:
                logger.exception("Research workflow error")
                answer = f"Sorry, I ran into a problem researching that: {exc}"

        elif is_reminder_intent(text):
            answer = await handle_reminder(text, chat_id)

        else:
            # ── 3. General assistant with conversation memory ─────────────
            history = await _run_sync(get_history, chat_id, 10)
            history_messages = [
                HumanMessage(content=m["content"]) if m["role"] == "user"
                else SystemMessage(content=m["content"])
                for m in history[:-1]   # exclude the message we just stored
            ]
            all_messages = history_messages + [HumanMessage(content=text)]
            try:
                answer = await general_agent.invoke(all_messages)
            except Exception as exc:
                logger.exception("General agent error")
                answer = f"Sorry, something went wrong: {exc}"

        # ── 4. Persist assistant reply ────────────────────────────────────
        await _run_sync(add_message, chat_id, "assistant", answer)
        return answer

    telegram.set_message_handler(on_message)
    telegram.run_polling()


if __name__ == "__main__":
    main()
