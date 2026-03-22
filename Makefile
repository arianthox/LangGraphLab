VENV        := .venv
PYTHON      := $(VENV)/bin/python3
PIP         := $(VENV)/bin/pip
LANGGRAPH   := $(VENV)/bin/langgraph
LOG_FILE    := /tmp/langgraph-assistant.log
STUDIO_LOG  := /tmp/langgraph-studio.log
STUDIO_PORT := 8123

.DEFAULT_GOAL := help

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  LangGraph Assistant — available commands"
	@echo ""
	@echo "  Setup"
	@echo "    make install        Create venv and install all dependencies"
	@echo "    make gmail-auth     Run the Gmail OAuth flow (headless server safe)"
	@echo ""
	@echo "  Run"
	@echo "    make run            Start the assistant in the background"
	@echo "    make dev            Start the assistant in the foreground (with live logs)"
	@echo "    make studio         Start LangGraph Studio (port $(STUDIO_PORT))"
	@echo "    make start-all      Start assistant + LangGraph Studio"
	@echo ""
	@echo "  Monitor"
	@echo "    make status         Show whether the assistant is running"
	@echo "    make logs           Tail live assistant logs"
	@echo "    make studio-logs    Tail live LangGraph Studio logs"
	@echo ""
	@echo "  Stop"
	@echo "    make stop           Stop the background assistant process"
	@echo "    make stop-studio    Stop the LangGraph Studio screen session"
	@echo "    make stop-all       Stop everything"
	@echo ""
	@echo "  Test"
	@echo "    make smoke          Run the intent-routing + memory smoke test"
	@echo "    make test-research  Run the full research pipeline (calls Ollama)"
	@echo ""
	@echo "  Maintenance"
	@echo "    make clean          Remove __pycache__ and .pyc files"
	@echo "    make clean-memory   Delete the local conversation memory DB"
	@echo "    make lint           Run ruff linter (if installed)"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
.PHONY: install
install:
	@echo "→ Creating virtual environment…"
	python3 -m venv $(VENV)
	@echo "→ Installing dependencies…"
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt -q
	$(PIP) install ddgs -q
	@echo "✓ Done. Copy .env.example to .env and fill in your tokens."
	@test -f .env || (cp .env.example .env && echo "  Created .env from .env.example")

.PHONY: gmail-auth
gmail-auth:
	@echo "→ Starting Gmail OAuth flow…"
	$(PYTHON) -c "\
from google_auth_oauthlib.flow import InstalledAppFlow; \
from src.config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE; \
import json; \
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', \
          'https://www.googleapis.com/auth/gmail.send']; \
flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES); \
flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'; \
auth_url, _ = flow.authorization_url(prompt='consent'); \
print('\nOpen this URL in your browser:\n'); print(auth_url); print(); \
code = input('Paste the authorisation code: '); \
flow.fetch_token(code=code); creds = flow.credentials; \
import os; os.makedirs(os.path.dirname(GMAIL_TOKEN_FILE), exist_ok=True); \
open(GMAIL_TOKEN_FILE, 'w').write(json.dumps({'token': creds.token, \
  'refresh_token': creds.refresh_token, 'token_uri': creds.token_uri, \
  'client_id': creds.client_id, 'client_secret': creds.client_secret, \
  'scopes': list(creds.scopes)})); \
print('✓ Token saved to', GMAIL_TOKEN_FILE)"

# ── Run ───────────────────────────────────────────────────────────────────────
.PHONY: run
run: _check-env
	@echo "→ Starting assistant in background…"
	@pkill -f 'python3 -m src.main' 2>/dev/null || true
	@sleep 1
	nohup $(PYTHON) -m src.main >> $(LOG_FILE) 2>&1 &
	@sleep 2
	@$(MAKE) --no-print-directory status

.PHONY: dev
dev: _check-env
	@echo "→ Starting assistant (foreground — Ctrl+C to stop)…"
	$(PYTHON) -m src.main

.PHONY: studio
studio: _check-env
	@echo "→ Starting LangGraph Studio on port $(STUDIO_PORT)…"
	@screen -S langgraph-studio -X quit 2>/dev/null || true
	@sleep 1
	screen -dmS langgraph-studio bash -c \
		"$(LANGGRAPH) dev --host 0.0.0.0 --port $(STUDIO_PORT) >> $(STUDIO_LOG) 2>&1"
	@sleep 4
	@echo "✓ Studio running — https://smith.langchain.com/studio/?baseUrl=http://localhost:$(STUDIO_PORT)"
	@tail -4 $(STUDIO_LOG) 2>/dev/null || true

.PHONY: start-all
start-all: run studio

# ── Monitor ───────────────────────────────────────────────────────────────────
.PHONY: status
status:
	@if pgrep -f 'python3 -m src.main' > /dev/null; then \
		echo "✓ Assistant is running (PID $$(pgrep -f 'python3 -m src.main'))"; \
	else \
		echo "✗ Assistant is NOT running  (run: make run)"; \
	fi
	@if screen -ls 2>/dev/null | grep -q langgraph-studio; then \
		echo "✓ LangGraph Studio is running (screen: langgraph-studio)"; \
	else \
		echo "✗ LangGraph Studio is NOT running  (run: make studio)"; \
	fi

.PHONY: logs
logs:
	@echo "→ Tailing $(LOG_FILE) — Ctrl+C to stop"
	tail -f $(LOG_FILE)

.PHONY: studio-logs
studio-logs:
	@echo "→ Tailing $(STUDIO_LOG) — Ctrl+C to stop"
	tail -f $(STUDIO_LOG)

# ── Stop ──────────────────────────────────────────────────────────────────────
.PHONY: stop
stop:
	@pkill -f 'python3 -m src.main' 2>/dev/null && echo "✓ Assistant stopped" || echo "  Assistant was not running"

.PHONY: stop-studio
stop-studio:
	@screen -S langgraph-studio -X quit 2>/dev/null && echo "✓ Studio stopped" || echo "  Studio was not running"

.PHONY: stop-all
stop-all: stop stop-studio

# ── Tests ─────────────────────────────────────────────────────────────────────
.PHONY: smoke
smoke:
	@echo "→ Running intent-routing + memory smoke test…"
	$(PYTHON) -c "\
import sys, warnings; warnings.filterwarnings('ignore'); sys.path.insert(0, '.'); \
from src.workflows.gmail_wf import is_gmail_intent, classify_gmail_intent; \
from src.workflows.research import is_research_intent; \
from src.main import is_reminder_intent, is_list_reminders_intent, is_clear_history; \
from src.memory.store import init_db, add_message, get_history; \
cases = [('read my emails','gmail'),('send email to x@y.com','gmail-send'), \
         ('research quantum computing','research'),('remind me to call dentist','reminder'), \
         ('my reminders','list-reminders'),('/clear','clear'),('hello','general')]; \
print('Intent routing:'); \
[print('  [' + ('OK' if (lambda t: 'clear' if is_clear_history(t) else 'list-reminders' if is_list_reminders_intent(t) else ('gmail-send' if classify_gmail_intent(t)=='send' else 'gmail') if is_gmail_intent(t) else 'research' if is_research_intent(t) else 'reminder' if is_reminder_intent(t) else 'general')(t) == e else 'FAIL') + '] ' + repr(t) + ' -> ' + e) for t,e in cases]; \
init_db(); add_message(99,'user','hello'); h=get_history(99); \
print('Memory: ' + ('OK' if len(h)==1 else 'FAIL'))"

.PHONY: test-research
test-research:
	@echo "→ Running research pipeline (this calls Ollama — may take ~30s)…"
	$(PYTHON) -c "\
import sys, warnings; warnings.filterwarnings('ignore'); sys.path.insert(0, '.'); \
from src.workflows.research import research_graph; \
r = research_graph.invoke({'query': 'what is LangGraph'}); \
s = r.get('summary') or r.get('error') or 'no result'; \
print('Result (first 400 chars):'); print(s[:400])"

# ── Maintenance ───────────────────────────────────────────────────────────────
.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	@echo "✓ Cleaned"

.PHONY: clean-memory
clean-memory:
	@rm -f ~/.langgraph_assistant/memory.db && echo "✓ Memory DB deleted" || true

.PHONY: lint
lint:
	@$(VENV)/bin/ruff check src/ 2>/dev/null || \
		($(PIP) install ruff -q && $(VENV)/bin/ruff check src/)

# ── Internal ──────────────────────────────────────────────────────────────────
.PHONY: _check-env
_check-env:
	@test -f .env || (echo "✗ .env not found — run: cp .env.example .env" && exit 1)
	@test -f $(PYTHON) || (echo "✗ venv not found — run: make install" && exit 1)
