"""
gmail_wf.py — Gmail read/summarise/send subgraph for langgraph-assistant.

Two paths:
  read  → read_node  → summarize_node → END   (inbox summary, search)
  send  → compose_node → send_node    → END   (draft & send)

Exports
-------
gmail_graph          : compiled CompiledGraph
is_gmail_intent      : helper used by main.py
classify_gmail_intent: returns "read" | "send"
"""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from typing import List, Optional

from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from src.integrations.gmail import authenticate_gmail

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent helpers
# ---------------------------------------------------------------------------

GMAIL_READ_KEYWORDS = {
    "email", "emails", "inbox", "mail", "unread",
    "read my", "check my", "show my", "latest email",
    "recent email", "summarize email", "summarise email",
    "what email", "any email", "new email",
}

GMAIL_SEND_KEYWORDS = {
    "send email", "send an email", "write email", "compose email",
    "draft email", "reply to", "email to", "email someone",
}


def is_gmail_intent(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in GMAIL_READ_KEYWORDS | GMAIL_SEND_KEYWORDS)


def classify_gmail_intent(text: str) -> str:
    lower = text.lower()
    if any(kw in lower for kw in GMAIL_SEND_KEYWORDS):
        return "send"
    return "read"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class GmailState(TypedDict):
    query: str
    gmail_intent: Optional[str]       # "read" | "send"
    emails: Optional[List[dict]]
    draft_to: Optional[str]
    draft_subject: Optional[str]
    draft_body: Optional[str]
    summary: Optional[str]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def read_node(state: GmailState) -> GmailState:
    """Fetch the 8 most recent emails (headers + snippet only — fast)."""
    service = authenticate_gmail()
    if not service:
        return {**state, "error": "Gmail is not configured.", "emails": []}

    try:
        results = service.users().messages().list(
            userId="me", maxResults=8, labelIds=["INBOX"]
        ).execute()
        raw_messages = results.get("messages", [])

        emails: List[dict] = []
        for m in raw_messages:
            msg = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            emails.append({
                "id": m["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })

        logger.info("read_node: fetched %d emails", len(emails))
        return {**state, "emails": emails}
    except Exception as exc:
        logger.exception("read_node failed")
        return {**state, "error": f"Failed to read inbox: {exc}", "emails": []}


def summarize_gmail_node(state: GmailState) -> GmailState:
    """Summarise the fetched emails using Ollama."""
    emails = state.get("emails") or []
    query = state["query"]

    if not emails:
        return {**state, "summary": state.get("error") or "No emails found in your inbox."}

    email_text = "\n\n".join(
        f"From: {e['from']}\nSubject: {e['subject']}\nDate: {e['date']}\nSnippet: {e['snippet']}"
        for e in emails
    )

    llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.0)
    prompt = (
        f"You are a helpful email assistant. The user asked: {query}\n\n"
        f"Here are their most recent emails:\n\n{email_text}\n\n"
        "Provide a clear, concise summary. Highlight anything urgent or important."
    )

    try:
        response = llm.invoke(prompt)
        summary = response.content if hasattr(response, "content") else str(response)
        return {**state, "summary": summary}
    except Exception as exc:
        logger.exception("summarize_gmail_node failed")
        return {**state, "summary": f"Error summarising emails: {exc}"}


def compose_node(state: GmailState) -> GmailState:
    """Use Ollama to extract recipient, subject, and body from the user's request."""
    query = state["query"]
    llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.3)

    prompt = (
        "Extract the email details from this request and respond in this exact format:\n"
        "TO: <email address or name>\n"
        "SUBJECT: <subject line>\n"
        "BODY:\n<email body>\n\n"
        f"User request: {query}\n\n"
        "If the email address is not specified, use 'unknown@example.com' as placeholder."
    )

    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)

        to_line = ""
        subject_line = ""
        body_lines = []
        in_body = False

        for line in text.splitlines():
            if line.upper().startswith("TO:") and not in_body:
                to_line = line[3:].strip()
            elif line.upper().startswith("SUBJECT:") and not in_body:
                subject_line = line[8:].strip()
            elif line.upper().startswith("BODY:"):
                in_body = True
            elif in_body:
                body_lines.append(line)

        return {
            **state,
            "draft_to": to_line,
            "draft_subject": subject_line,
            "draft_body": "\n".join(body_lines).strip(),
        }
    except Exception as exc:
        logger.exception("compose_node failed")
        return {**state, "error": f"Failed to compose email: {exc}"}


def send_node(state: GmailState) -> GmailState:
    """Send the composed email via Gmail API."""
    to = state.get("draft_to", "")
    subject = state.get("draft_subject", "")
    body = state.get("draft_body", "")

    if not to or "unknown@example.com" in to:
        return {
            **state,
            "summary": (
                f"I composed this email but couldn't determine the recipient.\n\n"
                f"**Subject:** {subject}\n\n{body}\n\n"
                "Please specify the recipient's email address and try again."
            ),
        }

    service = authenticate_gmail()
    if not service:
        return {**state, "error": "Gmail is not configured.", "summary": "Gmail not configured."}

    try:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info("send_node: sent email to %s", to)
        return {
            **state,
            "summary": f"✅ Email sent to **{to}**\n**Subject:** {subject}",
        }
    except Exception as exc:
        logger.exception("send_node failed")
        return {**state, "error": f"Failed to send email: {exc}", "summary": f"Failed to send: {exc}"}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_gmail(state: GmailState) -> str:
    return state.get("gmail_intent") or "read"


def set_intent(state: GmailState) -> GmailState:
    return {**state, "gmail_intent": classify_gmail_intent(state["query"])}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_gmail_graph():
    wf = StateGraph(GmailState)

    wf.add_node("set_intent", set_intent)
    wf.add_node("read", read_node)
    wf.add_node("summarize", summarize_gmail_node)
    wf.add_node("compose", compose_node)
    wf.add_node("send", send_node)

    wf.add_edge(START, "set_intent")
    wf.add_conditional_edges(
        "set_intent",
        route_gmail,
        {"read": "read", "send": "compose"},
    )
    wf.add_edge("read", "summarize")
    wf.add_edge("summarize", END)
    wf.add_edge("compose", "send")
    wf.add_edge("send", END)

    return wf.compile()


gmail_graph = build_gmail_graph()
