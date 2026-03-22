"""
Base agent class for langgraph-assistant.
Uses Ollama (via langchain_ollama.ChatOllama) as the local LLM backend.
"""

from typing import Any, Dict, List, Optional
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_ollama import ChatOllama
from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL


class BaseAgent:
    """A local Ollama-backed agent node for use inside LangGraph workflows."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.0,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = ChatOllama(
            model=model or OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=temperature,
        )

    async def invoke(
        self,
        messages: List[BaseMessage],
        state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Invoke the agent with a list of messages, returning the text response."""
        full_messages = [SystemMessage(content=self.system_prompt)] + messages
        response = await self.llm.ainvoke(full_messages)
        return response.content

    def as_node(self):
        """Return a callable suitable for use as a LangGraph node."""
        async def node_fn(state: Dict[str, Any]) -> Dict[str, Any]:
            messages = state.get("messages", [])
            response = await self.invoke(messages, state)
            return {"messages": messages + [response], "last_response": response}
        return node_fn
