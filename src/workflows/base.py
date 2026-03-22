"""
Base workflow class for langgraph-assistant.
All workflows should inherit from BaseWorkflow and implement build_graph().
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from langgraph.graph import StateGraph


class BaseWorkflow(ABC):
    """Abstract base for all LangGraph workflows."""

    def __init__(self, name: str):
        self.name = name
        self._graph = None

    @abstractmethod
    def build_graph(self) -> StateGraph:
        """Build and return the StateGraph for this workflow."""
        ...

    def compile(self):
        """Compile the workflow graph (call once before use)."""
        if self._graph is None:
            self._graph = self.build_graph().compile()
        return self._graph

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Run the workflow with the given initial state."""
        compiled = self.compile()
        return await compiled.ainvoke(state)
