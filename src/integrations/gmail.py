"""
Gmail integration stub for langgraph-assistant.

First-time setup:
  1. Go to https://console.cloud.google.com/ and create a project.
  2. Enable the Gmail API.
  3. Create OAuth2 credentials (Desktop app) and download as JSON.
  4. Save the file to the path set in GMAIL_CREDENTIALS_FILE (.env).
  5. Run authenticate_gmail() once to generate the token.
"""

import os
import logging
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    
]


def authenticate_gmail() -> Optional[object]:
    """
    Authenticate with Gmail using OAuth2.
    On first run this will open a browser for consent.
    On subsequent runs the saved token is refreshed automatically.
    Returns the Gmail API service object, or None if credentials are missing.
    """
    creds = None

    if os.path.exists(GMAIL_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GMAIL_CREDENTIALS_FILE):
                logger.warning(
                    f"Gmail credentials not found at {GMAIL_CREDENTIALS_FILE}. "
                    "Gmail integration is disabled. See src/integrations/gmail.py for setup instructions."
                )
                return None
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(GMAIL_TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail service authenticated successfully.")
    return service


def list_recent_emails(service, max_results: int = 10) -> List[dict]:
    """Return a list of recent email message summaries."""
    try:
        results = service.users().messages().list(
            userId="me", maxResults=max_results
        ).execute()
        messages = results.get("messages", [])
        return messages
    except HttpError as e:
        logger.error(f"Gmail API error: {e}")
        return []


def get_email_body(service, message_id: str) -> str:
    """Fetch and return the plain-text body of a Gmail message."""
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        parts = msg.get("payload", {}).get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                import base64
                data = part["body"].get("data", "")
                return base64.urlsafe_b64decode(data).decode("utf-8")
        return "(no plain-text body found)"
    except HttpError as e:
        logger.error(f"Gmail API error fetching message {message_id}: {e}")
        return ""
