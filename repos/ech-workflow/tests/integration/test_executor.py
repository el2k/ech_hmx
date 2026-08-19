import pytest
from app.engine.executor import WorkflowExecutor
import asyncio

@pytest.mark.asyncio
async def test_workflow_executor_run():
    definition = {
        "nodes": [
            {
                "id": "input_1", 
                "type": "input", 
                "data": {"reference_key": "input", "label": "Input", "input_variables": [{"name": "text", "type": "string"}]}
            },
            {
                "id": "answer_1", 
                "type": "answer", 
                "data": {"reference_key": "answer", "label": "Answer", "output_type": "template", "output_template": "Processed: {{input.text}}"}
            }
        ],
        "edges": [
            {"source": "input_1", "target": "answer_1"}
        ]
    }
    
    executor = WorkflowExecutor(definition)
    inputs = {"text": "hello"}
    
    final_output = await executor.run(inputs)
    assert final_output == "Processed: hello"

@pytest.mark.asyncio
async def test_workflow_executor_with_condition():
    definition = {
        "nodes": [
            {
                "id": "input_1", 
                "type": "input", 
                "data": {"reference_key": "input", "label": "Input", "input_variables": [{"name": "val", "type": "number"}]}
            },
            {
                "id": "cond_1",
                "type": "condition",
                "data": {
                    "reference_key": "cond", 
                    "label": "Is Positive?",
                    "condition_type": "expression",
                    "expression": "input['val'] > 0"
                }
            },
            {
                "id": "answer_true", 
                "type": "answer", 
                "data": {"reference_key": "answer_t", "label": "Positive", "output_type": "template", "output_template": "Positive"}
            },
            {
                "id": "answer_false", 
                "type": "answer", 
                "data": {"reference_key": "answer_f", "label": "Negative", "output_type": "template", "output_template": "Negative"}
            }
        ],
        "edges": [
            {"source": "input_1", "target": "cond_1"},
            {"source": "cond_1", "target": "answer_true", "sourceHandle": "true"},
            {"source": "cond_1", "target": "answer_false", "sourceHandle": "false"}
        ]
    }
    
    # Case 1: Positive
    executor = WorkflowExecutor(definition)
    res = await executor.run({"val": 10})
    assert res == "Positive"
    
    # Case 2: Negative
    executor = WorkflowExecutor(definition)
    res = await executor.run({"val": -5})
    assert res == "Negative"

