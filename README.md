# LangGraph Assistant

A personal AI assistant built with [LangGraph](https://langchain-ai.github.io/langgraph/), accessible via Telegram. It routes incoming messages to specialised subgraphs — web research, Gmail, job search, reminders — and falls back to a general conversational agent with per-user memory.

---

## Architecture

```
Telegram message
       │
       ▼
  Intent router (main.py)
       │
   ┌───┴──────────────────────────────────────────────┐
   │         │           │          │         │        │
   ▼         ▼           ▼          ▼         ▼        ▼
Research   Gmail      Gmail      Job       Reminder  General
 graph    (read)     (send)    Lookup     (SQLite)   Agent
                                                   + Memory
```

| Layer | Technology |
|---|---|
| Workflow orchestration | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| LLM backend | [Ollama](https://ollama.com/) — `qwen3:14b` by default |
| Telegram interface | [python-telegram-bot](https://python-telegram-bot.org/) |
| Gmail integration | [Google Gmail API](https://developers.google.com/gmail/api) via OAuth2 |
| Web search | [ddgs](https://pypi.org/project/ddgs/) (DuckDuckGo, no API key needed) |
| Conversation memory | SQLite (`~/.langgraph_assistant/memory.db`) |

---

## Quick Start

### 1. Prerequisites

- [Ollama](https://ollama.com/) running locally with `qwen3:14b` pulled:
  ```bash
  ollama pull qwen3:14b
  ```
- Python 3.11+
- `make` (pre-installed on Linux/macOS)

### 2. Clone and install

```bash
git clone git@github.com:arianthox/LangGraphLab.git
cd LangGraphLab
make install
```

This creates the virtual environment, installs all dependencies, and copies `.env.example` → `.env` if it doesn't exist yet.

### 3. Configure environment

Edit the generated `.env`:

```env
# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b

# Telegram — get a token from @BotFather
TELEGRAM_BOT_TOKEN=your-bot-token-here

# Gmail (optional — only needed for email flows)
GMAIL_CREDENTIALS_FILE=/app/data/gmail_credentials.json
GMAIL_TOKEN_FILE=/app/data/gmail_token.json
```

### 4. Set up Gmail (optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project
2. Enable the **Gmail API**
3. Create **OAuth 2.0 credentials** (Desktop app type) and download as JSON
4. Save the file to the path set in `GMAIL_CREDENTIALS_FILE`
5. Run the headless OAuth flow:
   ```bash
   make gmail-auth
   ```
   This prints a URL — open it in your browser, approve access, and paste the code back.

### 5. Run

```bash
make run          # start in background
make logs         # tail live output
```

Or run everything at once (assistant + LangGraph Studio):

```bash
make start-all
```

---

## Makefile Reference

Run `make help` at any time to see a summary of all commands.

### Setup

| Command | Description |
|---|---|
| `make install` | Create `.venv`, install all dependencies from `requirements.txt`, copy `.env.example` if no `.env` exists |
| `make gmail-auth` | Run the Gmail OAuth2 flow — safe on headless servers (prints URL, prompts for code) |

### Run

| Command | Description |
|---|---|
| `make run` | Kill any existing instance and start the assistant in the background (`/tmp/langgraph-assistant.log`) |
| `make dev` | Start in the foreground with live output — useful for debugging |
| `make studio` | Start LangGraph Studio in a `screen` session on port `8123` |
| `make start-all` | Run both `make run` and `make studio` in one step |

### Monitor

| Command | Description |
|---|---|
| `make status` | Show whether the assistant and LangGraph Studio are running (PID / screen session) |
| `make logs` | `tail -f` the assistant log (`/tmp/langgraph-assistant.log`) |
| `make studio-logs` | `tail -f` the LangGraph Studio log (`/tmp/langgraph-studio.log`) |

### Stop

| Command | Description |
|---|---|
| `make stop` | Kill the background assistant process |
| `make stop-studio` | Quit the `langgraph-studio` screen session |
| `make stop-all` | Stop both the assistant and Studio |

### Test

| Command | Description |
|---|---|
| `make smoke` | Fast intent-routing + memory sanity check — no Ollama call needed |
| `make test-research` | Run the full research pipeline end-to-end (calls Ollama, ~30 s) |

### Maintenance

| Command | Description |
|---|---|
| `make clean` | Remove all `__pycache__` directories and `.pyc` files |
| `make clean-memory` | Delete the local SQLite conversation memory DB (`~/.langgraph_assistant/memory.db`) |
| `make lint` | Run `ruff` linter over `src/` (auto-installs `ruff` if not present) |

---

## Supported Flows

### 1. Research

**File:** `src/workflows/research.py`

Searches the web, fetches the top pages, and synthesises a clear summary using Ollama.

```
search_node ──► fetch_node ──► summarize_node
(DuckDuckGo     (requests +    (ChatOllama)
 top 5 URLs)     BeautifulSoup
                 top 2-3 pages)
```

**Trigger keywords:** `research`, `search`, `find`, `what is`, `what are`, `summarize`, `explain`, `how does`, `how do`, `who is`, `when did`, `where is`, `latest`, `news about`, `overview of`, `describe`

**Example messages:**
- `research quantum computing`
- `what is LangGraph`
- `explain transformer architecture`
- `summarize what's new in Python 3.13`

---

### 2. Gmail — Read / Summarise

**File:** `src/workflows/gmail_wf.py` (read path)

Fetches the 8 most recent inbox emails (headers + snippet only, fast) and summarises them with Ollama.

```
set_intent ──► read_node ──► summarize_node
               (Gmail API     (ChatOllama)
                metadata)
```

**Trigger keywords:** `email`, `emails`, `inbox`, `mail`, `unread`, `read my`, `check my`, `show my`, `latest email`, `recent email`, `summarize email`, `what email`, `new email`

**Example messages:**
- `read my emails`
- `summarize my inbox`
- `any new emails?`
- `check my unread mail`

---

### 3. Gmail — Compose & Send

**File:** `src/workflows/gmail_wf.py` (send path)

Uses Ollama to extract recipient, subject, and body from a natural-language request, then sends via the Gmail API. If no valid address is found it shows the draft for review instead of sending.

```
set_intent ──► compose_node ──► send_node
               (ChatOllama       (Gmail API)
                extracts
                TO/SUBJECT/BODY)
```

**Trigger keywords:** `send email`, `send an email`, `write email`, `compose email`, `draft email`, `reply to`, `email to`, `email someone`

**Example messages:**
- `send email to alice@example.com saying the meeting is at 3pm`
- `compose email to bob about the project update`
- `write an email to the team announcing the launch`

---

### 4. Job Lookup

**File:** `src/workflows/job_lookup.py`

Parses natural-language job search requests, searches LinkedIn/Indeed/RemoteOK via DuckDuckGo, and returns a formatted Telegram-ready summary of top listings.

```
parse_query_node ──► search_jobs_node ──► format_results_node
(ChatOllama          (DuckDuckGo:         (ChatOllama
 extracts role,       LinkedIn, Indeed,    formats top 5
 location, remote)    RemoteOK)            for Telegram)
```

**Trigger keywords:** `job`, `jobs`, `hiring`, `position`, `career`, `careers`, `employment`, `vacancy`, `opening`, `job search`, `job listing`, `job posting`, `looking for work`, `find work`, `get a job`, `remote work`, `internship`

**Example messages:**
- `find Python developer jobs in Austin`
- `remote data scientist positions`
- `software engineer jobs at a startup`
- `junior backend developer openings`

---

### 5. Reminders

**Handler:** `main.py` → `src/memory/store.py`

Stores free-text reminders in SQLite, scoped per Telegram `chat_id`. Reminders are stored and can be listed on demand.

**Add a reminder — trigger keywords:** `remind me`, `reminder`, `don't forget`, `set a reminder`, `note to self`, `remember to`, `memo`

**List reminders — trigger keywords:** `my reminders`, `list reminders`, `show reminders`, `what are my reminders`

**Example messages:**
- `remind me to call the dentist`
- `note to self: review the PR before EOD`
- `my reminders`

---

### 6. General Conversation (with Memory)

**Handler:** `main.py` → `src/agents/base.py`

All messages that don't match the above are handled by `BaseAgent` — a `ChatOllama`-backed conversational agent. The last 10 messages per user are loaded from SQLite and passed as context so the bot remembers earlier parts of the conversation.

**Special commands:**

| Command | Effect |
|---|---|
| `/clear` | Wipes your conversation history |
| `forget our conversation` | Same as `/clear` |
| `clear history` | Same as `/clear` |

---

## Project Structure

```
src/
├── main.py                  # Entrypoint — intent router + Telegram handler
├── config.py                # Env var loading
├── agents/
│   └── base.py              # BaseAgent: ChatOllama-backed conversational agent
├── integrations/
│   ├── telegram.py          # python-telegram-bot wrapper
│   └── gmail.py             # Gmail OAuth2 + API helpers
├── memory/
│   └── store.py             # SQLite: conversation history + reminders
└── workflows/
    ├── base.py              # Abstract BaseWorkflow
    ├── research.py          # Web search + summarise subgraph
    ├── gmail_wf.py          # Gmail read/send subgraph
    └── job_lookup.py        # Job search subgraph
```

---

## Adding a New Flow

1. Create `src/workflows/your_flow.py` — subclass `BaseWorkflow` or build a `StateGraph` directly
2. Add an `is_your_intent(text: str) -> bool` helper
3. Import and wire it in `src/main.py`'s `on_message` handler
4. Export a module-level compiled graph if you want it visible in LangGraph Studio

---

## Roadmap

- [ ] Time-based reminder delivery (background scheduler → Telegram push)
- [ ] Google Calendar integration (read events, create meetings)
- [ ] Streaming responses to Telegram (shows typing indicator while Ollama generates)
- [ ] Per-user configurable Ollama model
- [ ] Docker / podman-compose deployment guide
