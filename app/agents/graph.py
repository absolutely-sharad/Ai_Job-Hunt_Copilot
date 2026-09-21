"""Pipeline wiring: parse -> retrieve -> analyse -> draft -> verify -> outputs."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agents.nodes import CopilotNodes
from app.agents.state import CopilotState
from app.core.config import Settings
from app.services.llm import BaseLLM
from app.services.retrieval import RetrievalService


def build_graph(llm: BaseLLM, retrieval: RetrievalService, settings: Settings):
    """Compile the copilot state graph.

    The verify -> draft_resume edge is a bounded self-correction loop: if the
    critic rejects every bullet for missing citations, the drafter runs once
    more with the violations fed back as instructions.
    """
    nodes = CopilotNodes(llm, retrieval, settings)
    graph = StateGraph(CopilotState)

    graph.add_node("parse_jd", nodes.parse_jd)
    graph.add_node("retrieve_evidence", nodes.retrieve_evidence)
    graph.add_node("analyze_match", nodes.analyze_match)
    graph.add_node("draft_resume", nodes.draft_resume)
    graph.add_node("verify_grounding", nodes.verify_grounding)
    graph.add_node("draft_cover_letter", nodes.draft_cover_letter)
    graph.add_node("build_interview_prep", nodes.build_interview_prep)

    graph.set_entry_point("parse_jd")
    graph.add_edge("parse_jd", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "analyze_match")
    graph.add_edge("analyze_match", "draft_resume")
    graph.add_edge("draft_resume", "verify_grounding")
    graph.add_conditional_edges(
        "verify_grounding",
        nodes.should_retry,
        {"retry": "draft_resume", "continue": "draft_cover_letter"},
    )
    graph.add_edge("draft_cover_letter", "build_interview_prep")
    graph.add_edge("build_interview_prep", END)

    return graph.compile()
