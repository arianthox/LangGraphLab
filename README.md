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

Uses Ollama to extract recipient, subject, and body from a natural-language request, then sends the email via the Gmail API. If no valid email address is found, it shows the draft for your review instead of sending.

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

Stores free-text reminders in SQLite, scoped per Telegram `chat_id`. No time-based delivery yet — reminders are stored and can be listed on demand.

**Add a reminder — trigger keywords:** `remind me`, `reminder`, `don't forget`, `set a reminder`, `note to self`, `remember to`, `memo`

**List reminders — trigger keywords:** `my reminders`, `list reminders`, `show reminders`, `what are my reminders`

**Example messages:**
- `remind me to call the dentist`
- `note to self: review the PR before EOD`
- `my reminders`

---

### 6. General Conversation (with Memory)

**Handler:** `main.py` → `src/agents/base.py`

All messages that don't match any of the above are handled by `BaseAgent` — a `ChatOllama`-backed conversational agent. The last 10 messages per user are loaded from SQLite and passed as context, so the bot remembers earlier parts of the conversation.

**Special commands:**

| Command | Effect |
|---|---|
| `/clear` | Wipes your conversation history |
| `forget our conversation` | Same as `/clear` |
| `clear history` | Same as `/clear` |

---

## Quick Start

### 1. Prerequisites

- [Ollama](https://ollama.com/) running locally with `qwen3:14b` pulled:
  ```bash
  ollama pull qwen3:14b
  ```
- Python 3.11+

### 2. Install

```bash
git clone git@github.com:arianthox/LangGraphLab.git
cd LangGraphLab
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install ddgs   # DuckDuckGo search (renamed package)
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

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
4. Save to the path set in `GMAIL_CREDENTIALS_FILE`
5. Generate the OAuth token (run this on the server — it prints a URL to open in your browser):

```bash
source .venv/bin/activate
python3 -c "
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE
import json

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.send']

flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
auth_url, _ = flow.authorization_url(prompt='consent')
print('Open this URL:', auth_url)
code = input('Paste the code: ')
flow.fetch_token(code=code)
creds = flow.credentials
with open(GMAIL_TOKEN_FILE, 'w') as f:
    json.dump({'token': creds.token, 'refresh_token': creds.refresh_token,
               'token_uri': creds.token_uri, 'client_id': creds.client_id,
               'client_secret': creds.client_secret, 'scopes': list(creds.scopes)}, f)
print('Token saved.')
"
```

### 5. Run

```bash
source .venv/bin/activate
python3 -m src.main
```

Or in the background:

```bash
nohup python3 -m src.main > /tmp/assistant.log 2>&1 &
```

### 6. LangGraph Studio (optional)

```bash
langgraph dev --host 0.0.0.0 --port 8123
```

Then open `https://smith.langchain.com/studio/?baseUrl=http://localhost:8123`.

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
