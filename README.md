# langgraph-assistant

A personal AI assistant built with LangGraph, accessible via Telegram, with Gmail integration.

## Architecture

- **LangGraph** orchestrates the workflow and subagents
- **Telegram** (python-telegram-bot) is the user interface
- **Gmail API** handles email-based workflows
- **OpenAI** (GPT-4o-mini by default) is the LLM backend
- **Podman / podman-compose** runs the containerised service

## Quick Start

### 1. Configure environment

Copy  to  (already done if you cloned this repo) and fill in:
-  — already populated from your machine
-  — get one from [@BotFather](https://t.me/BotFather)

### 2. Set up Gmail (optional)

1. Create a project at https://console.cloud.google.com/
2. Enable the **Gmail API**
3. Create **OAuth 2.0 credentials** (Desktop app type), download as JSON
4. Place the file at 
5. On first run the app will open a browser for OAuth consent and save a token

### 3. Run with podman-compose



Or run directly in a venv (development):



## Project Structure



## Next Steps

- [ ] Add your Telegram bot token to 
- [ ] Set up Gmail credentials if you want email workflows
- [ ] Extend  with task-specific graphs (e.g. email triage, reminders)
- [ ] Add memory/persistence with LangGraph checkpointers
- [ ] Wire up more tools (calendar, web search, etc.)
