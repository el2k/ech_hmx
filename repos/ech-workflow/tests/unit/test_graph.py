import pytest
from app.engine.graph import WorkflowGraph

def test_workflow_graph_init():
    nodes = [
        {"id": "node1", "type": "input", "data": {}},
        {"id": "node2", "type": "answer", "data": {}}
    ]
    edges = [
        {"source": "node1", "target": "node2"}
    ]
    graph = WorkflowGraph(nodes, edges)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.adj["node1"] == ["node2"]
    assert graph.rev_adj["node2"] == ["node1"]

def test_topo_sort():
    nodes = [
        {"id": "node1", "type": "input", "data": {}},
        {"id": "node2", "type": "llm", "data": {}},
        {"id": "node3", "type": "answer", "data": {}}
    ]
    edges = [
        {"source": "node1", "target": "node2"},
        {"source": "node2", "target": "node3"}
    ]
    graph = WorkflowGraph(nodes, edges)
    sort = graph.get_topo_sort()
    assert sort == ["node1", "node2", "node3"]

def test_get_next_nodes():
    nodes = [
        {"id": "node1", "type": "condition", "data": {}},
        {"id": "node2", "type": "llm", "data": {}},
        {"id": "node3", "type": "api", "data": {}}
    ]
    edges = [
        {"source": "node1", "target": "node2", "sourceHandle": "true"},
        {"source": "node1", "target": "node3", "sourceHandle": "false"}
    ]
    graph = WorkflowGraph(nodes, edges)
    assert graph.get_next_nodes("node1", "true") == ["node2"]
    assert graph.get_next_nodes("node1", "false") == ["node3"]

