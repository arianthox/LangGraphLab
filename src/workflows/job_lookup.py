"""
job_lookup.py — job search subgraph for langgraph-assistant.

Three-node pipeline:
  parse_query_node   — Qwen3:14b extracts structured search params from natural language
  search_jobs_node   — DuckDuckGo searches site:linkedin.com/jobs, site:indeed.com, site:remoteok.com
  format_results_node — Qwen3:14b formats top 5 results into Telegram-friendly summary

Exports
-------
job_lookup_graph     : compiled CompiledGraph
is_job_lookup_intent : helper used by main.py for intent routing
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

JOB_KEYWORDS = {
    "job", "jobs", "hiring", "position", "career", "careers",
    "employment", "vacancy", "vacancies", "opening", "openings",
    "job search", "job listing", "job posting",
    "looking for work", "find work", "get a job",
    "data scientist", "software engineer", "developer jobs",
    "remote work", "full-time", "part-time", "internship",
}


def is_job_lookup_intent(text: str) -> bool:
    """Return True when the user's message is about finding jobs."""
    lower = text.lower()
    return any(kw in lower for kw in JOB_KEYWORDS)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class JobLookupState(TypedDict):
    query: str
    parsed_params: Optional[dict]
    job_results: Optional[List[dict]]
    formatted_response: Optional[str]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def parse_query_node(state: JobLookupState) -> JobLookupState:
    """Use Qwen3 to extract structured job search params from user query."""
    query = state["query"]
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.0,
    )

    prompt = (
        "Extract job search parameters from this user query and return ONLY valid JSON.\n"
        "Return a JSON object with these fields:\n"
        "{\"role\": \"job title or role\", \"location\": \"city/country or empty string\", "
        "\"remote\": true/false, \"keywords\": [\"extra\", \"keywords\"], "
        "\"experience\": \"junior/mid/senior/any\"}\n\n"
        f"User query: {query}\n\n"
        "Return only the JSON object, nothing else."
    )

    try:
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        # Extract JSON from response
        match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if match:
            params = json.loads(match.group())
        else:
            params = json.loads(content.strip())
        logger.info("parse_query_node: extracted params: %s", params)
        return {**state, "parsed_params": params}
    except Exception as exc:
        logger.exception("parse_query_node failed, using defaults")
        # Fallback: basic extraction
        lower = query.lower()
        is_remote = any(w in lower for w in ["remote", "anywhere", "work from home", "wfh"])
        return {
            **state,
            "parsed_params": {
                "role": query,
                "location": "",
                "remote": is_remote,
                "keywords": [],
                "experience": "any",
            },
        }


def search_jobs_node(state: JobLookupState) -> JobLookupState:
    """Search multiple job sites via DuckDuckGo and collect results."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore

        params = state.get("parsed_params") or {}
        role = params.get("role", state["query"])
        location = params.get("location", "")
        is_remote = params.get("remote", False)

        role_clean = role.replace('"', "").strip()
        location_clean = location.replace('"', "").strip()

        # Build search queries
        queries = []
        if location_clean:
            queries.append(f"site:linkedin.com/jobs {role_clean} {location_clean}")
            queries.append(f"site:indeed.com {role_clean} {location_clean} jobs")
        else:
            queries.append(f"site:linkedin.com/jobs {role_clean}")
            queries.append(f"site:indeed.com {role_clean} jobs")

        if is_remote:
            queries.append(f"site:remoteok.com {role_clean}")
        else:
            queries.append(f"{role_clean} {location_clean} job hiring 2024 2025")

        all_results: List[dict] = []
        seen_urls: set = set()

        with DDGS() as ddgs:
            for q in queries:
                try:
                    for r in ddgs.text(q, max_results=4):
                        url = r.get("href", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_results.append({
                                "title": r.get("title", "Unknown Position"),
                                "url": url,
                                "snippet": r.get("body", ""),
                                "source": _detect_source(url),
                            })
                except Exception as e:
                    logger.debug("Query failed: %s — %s", q, e)

        logger.info("search_jobs_node: %d unique results found", len(all_results))
        return {**state, "job_results": all_results[:10]}

    except Exception as exc:
        logger.exception("search_jobs_node failed")
        return {**state, "job_results": [], "error": f"Job search failed: {exc}"}


def _detect_source(url: str) -> str:
    """Guess the source platform from the URL."""
    if "linkedin.com" in url:
        return "LinkedIn"
    elif "indeed.com" in url:
        return "Indeed"
    elif "remoteok.com" in url:
        return "RemoteOK"
    elif "glassdoor.com" in url:
        return "Glassdoor"
    return "Web"


def format_results_node(state: JobLookupState) -> JobLookupState:
    """Use Qwen3 to format job results into a Telegram-friendly summary."""
    query = state["query"]
    job_results = state.get("job_results") or []

    if not job_results:
        return {
            **state,
            "formatted_response": (
                f"Sorry, I couldn't find any job listings for: {query}\n\n"
                "Try being more specific, e.g. 'Python developer jobs in Austin' or 'remote data scientist roles'."
            ),
        }

    # Build a text summary of raw results for the LLM
    results_text = "\n\n".join([
        f"[{i+1}] {r.get('title','?')}\nSource: {r.get('source','?')}\nURL: {r.get('url','?')}\nSnippet: {r.get('snippet','')[:300]}"
        for i, r in enumerate(job_results[:8])
    ])

    params = state.get("parsed_params") or {}
    role = params.get("role", query)
    location = params.get("location", "")
    is_remote = params.get("remote", False)

    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.3,
    )

    search_context = f"Role: {role}"
    if location:
        search_context += f", Location: {location}"
    if is_remote:
        search_context += ", Remote: Yes"

    prompt = (
        "You are a job search assistant. Format these job search results into a clean, "
        "Telegram-friendly message (use emoji, bold with **, short lines).\n"
        f"Search: {search_context}\n\n"
        "Rules:\n"
        "- Show the top 5 most relevant results\n"
        "- Each entry: job title, company/source, location if known, link\n"
        "- Add a brief intro line and a closing tip\n"
        "- Keep it concise and scannable\n"
        "- Use Markdown formatting Telegram supports (* for bold, _ for italic)\n\n"
        f"Raw results:\n{results_text}\n\n"
        "Format the response now:"
    )

    try:
        response = llm.invoke(prompt)
        formatted = response.content if hasattr(response, "content") else str(response)
        logger.info("format_results_node: produced %d-char response", len(formatted))
        return {**state, "formatted_response": formatted}
    except Exception as exc:
        logger.exception("format_results_node failed, using plain fallback")
        # Fallback: plain text summary
        lines = [f"🔍 Job results for: {query}\n"]
        for i, r in enumerate(job_results[:5], 1):
            lines.append(f"{i}. *{r.get('title','?')}* ({r.get('source','?')})\n   {r.get('url','')}")
        return {**state, "formatted_response": "\n".join(lines)}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_job_lookup_graph():
    wf = StateGraph(JobLookupState)
    wf.add_node("parse_query", parse_query_node)
    wf.add_node("search_jobs", search_jobs_node)
    wf.add_node("format_results", format_results_node)
    wf.add_edge(START, "parse_query")
    wf.add_edge("parse_query", "search_jobs")
    wf.add_edge("search_jobs", "format_results")
    wf.add_edge("format_results", END)
    return wf.compile()


job_lookup_graph = build_job_lookup_graph()
