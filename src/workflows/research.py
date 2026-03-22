"""
research.py — web-search + summarise subgraph for langgraph-assistant.

Three-node pipeline:
  search_node   — DuckDuckGo top-5 results (no API key) via `ddgs` package
  fetch_node    — HTTP-fetch + BeautifulSoup text extraction (top 2-3 URLs)
  summarize_node — Ollama / Qwen3:14b summarisation

Exports
-------
research_graph      : compiled CompiledGraph
is_research_intent  : helper used by main.py for intent routing
"""

from __future__ import annotations

import logging
from typing import List, Optional

from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

RESEARCH_KEYWORDS = {
    "research", "search", "find", "what is", "what are",
    "summarize", "summarise", "look up", "tell me about", "explain",
    "how does", "how do", "who is", "when did", "where is",
    "latest", "news about", "overview of", "describe",
}


def is_research_intent(text: str) -> bool:
    """Return True when the user's message contains a research keyword."""
    lower = text.lower()
    return any(kw in lower for kw in RESEARCH_KEYWORDS)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ResearchState(TypedDict):
    query: str
    search_results: Optional[List[dict]]
    fetched_content: Optional[str]
    summary: Optional[str]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def search_node(state: ResearchState) -> ResearchState:
    """Run a DuckDuckGo text search and return the top 5 hits."""
    try:
        # prefer the new `ddgs` package; fall back to `duckduckgo_search` if needed
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore[no-redef]

        query = state["query"]
        results: List[dict] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
        logger.info("search_node: %d results for %r", len(results), query)
        return {**state, "search_results": results}
    except Exception as exc:
        logger.exception("search_node failed")
        return {**state, "search_results": [], "error": f"Search failed: {exc}"}


def fetch_node(state: ResearchState) -> ResearchState:
    """HTTP-fetch the top 2-3 URLs and extract clean body text."""
    import requests
    from bs4 import BeautifulSoup

    search_results: List[dict] = state.get("search_results") or []
    if not search_results:
        return {**state, "fetched_content": ""}

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
    all_content: List[str] = []

    for result in search_results[:3]:
        url = result.get("url", "")
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=8, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = " ".join(soup.get_text(separator=" ", strip=True).split())[:3000]
            if text:
                all_content.append(f"--- Source: {url} ---\n{text}")
        except Exception as exc:
            logger.debug("fetch_node: skipping %s — %s", url, exc)

    if not all_content:
        # Fallback: use the DuckDuckGo snippets
        snippets = [
            f"- {r['title']}: {r['snippet']}"
            for r in search_results
            if r.get("snippet")
        ]
        fetched_content = "\n".join(snippets)
    else:
        fetched_content = "\n\n".join(all_content)

    logger.info("fetch_node: %d chars of content", len(fetched_content))
    return {**state, "fetched_content": fetched_content}


def summarize_node(state: ResearchState) -> ResearchState:
    """Send all gathered content to Ollama and produce a final summary."""
    query = state["query"]
    fetched_content = state.get("fetched_content") or ""

    if not fetched_content:
        return {
            **state,
            "summary": (
                f"I searched the web but couldn't retrieve useful content "
                f"to answer: {query}"
            ),
        }

    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.0,
    )

    prompt = (
        "You are a research assistant. Based on the following web content, "
        f"provide a clear, concise summary answering: {query}\n\n"
        f"Content:\n{fetched_content[:8000]}\n\n"
        "Provide a well-structured answer. Be informative but concise."
    )

    try:
        response = llm.invoke(prompt)
        summary = response.content if hasattr(response, "content") else str(response)
        logger.info("summarize_node: produced %d-char summary", len(summary))
        return {**state, "summary": summary}
    except Exception as exc:
        logger.exception("summarize_node failed")
        return {
            **state,
            "error": f"Summarisation failed: {exc}",
            "summary": f"Error generating summary: {exc}",
        }


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_research_graph():
    wf = StateGraph(ResearchState)
    wf.add_node("search", search_node)
    wf.add_node("fetch", fetch_node)
    wf.add_node("summarize", summarize_node)
    wf.add_edge(START, "search")
    wf.add_edge("search", "fetch")
    wf.add_edge("fetch", "summarize")
    wf.add_edge("summarize", END)
    return wf.compile()


research_graph = build_research_graph()
