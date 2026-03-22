"""
Configuration and environment loading for langgraph-assistant.
All settings are read from environment variables (via .env file or host env).
"""

import os
from dotenv import load_dotenv

# Load .env from the project root (one level up from src/)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{key}' is not set. "
            f"Please add it to your .env file."
        )
    return value


def _optional(key: str, default: str = '') -> str:
    return os.getenv(key, default)


# -- LLM (Ollama) --------------------------------------------------------------
OLLAMA_BASE_URL: str = _optional('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL: str = _optional('OLLAMA_MODEL', 'qwen3:14b')

# -- Telegram ------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = _require('TELEGRAM_BOT_TOKEN')
TELEGRAM_BOT_NAME: str = _optional('TELEGRAM_BOT_NAME', 'Assistant')

# -- Gmail ---------------------------------------------------------------------
GMAIL_CREDENTIALS_FILE: str = _optional('GMAIL_CREDENTIALS_FILE', '/app/data/gmail_credentials.json')
GMAIL_TOKEN_FILE: str = _optional('GMAIL_TOKEN_FILE', '/app/data/gmail_token.json')

# -- General -------------------------------------------------------------------
LOG_LEVEL: str = _optional('LOG_LEVEL', 'INFO')
