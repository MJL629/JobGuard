"""
LangGraph 图结构测试
"""

import pytest
from app.graph.builder import build_jobguard_graph


class TestJobGuardGraph:

    def test_graph_builds(self):
        """Test that the graph compiles without errors"""
        workflow = build_jobguard_graph()
        graph = workflow.compile()
        assert graph is not None

    def test_graph_has_all_nodes(self):
        """Test that all required nodes are present"""
        workflow = build_jobguard_graph()
        graph = workflow.compile()

        # Get node names from the graph
        nodes = graph.get_graph().nodes
        node_names = {n for n in nodes if n != "__start__" and n != "__end__"}

        expected = {
            "router", "profile", "job_parse", "background_check",
            "job_match", "resume_generate", "recommend", "fallback",
        }
        assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"

    def test_graph_has_entry_point(self):
        """Test that the graph has a valid entry point"""
        workflow = build_jobguard_graph()
        graph = workflow.compile()

        # Should not raise when getting graph structure
        graph_struct = graph.get_graph()
        assert graph_struct is not None
