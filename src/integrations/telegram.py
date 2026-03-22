"""
Telegram bot integration for langgraph-assistant.
Receives messages from Telegram and dispatches them into the LangGraph workflow.
"""

import logging
from typing import Optional, Callable, Awaitable

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from src.config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)


class TelegramHandler:
    """
    Wraps python-telegram-bot and exposes a simple interface for
    routing messages to a LangGraph workflow handler.
    """

    def __init__(
        self,
        on_message: Optional[Callable[[str, int], Awaitable[str]]] = None,
    ):
        """
        Args:
            on_message: Async callback(text, chat_id) -> reply_text.
                        Called for every non-command user message.
        """
        self._on_message = on_message
        self._app: Optional[Application] = None

    def set_message_handler(self, handler: Callable[[str, int], Awaitable[str]]):
        self._on_message = handler

    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Hi! I am your personal AI assistant. Send me a message to get started."
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        chat_id = update.message.chat_id
        logger.info(f"Received message from chat_id={chat_id}: {text!r}")

        if self._on_message is None:
            await update.message.reply_text("Assistant is not yet configured.")
            return

        try:
            reply = await self._on_message(text, chat_id)
            await update.message.reply_text(reply)
        except Exception as e:
            logger.exception("Error handling Telegram message")
            await update.message.reply_text(f"Sorry, something went wrong: {e}")

    def build_app(self) -> Application:
        self._app = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )
        self._app.add_handler(CommandHandler("start", self._start))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        return self._app

    def run_polling(self):
        """Start the bot in polling mode (blocking). Use for development."""
        app = self.build_app()
        logger.info("Starting Telegram bot polling...")
        app.run_polling()
