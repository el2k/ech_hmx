from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.execution import WorkflowExecution, NodeExecution
import asyncio
import traceback
from app.schemas.execution import (
    WorkflowExecution as WorkflowExecutionSchema, 
    WorkflowExecuteRequest,
    WorkflowExecutionCancelResponse,
    WorkflowStartedEvent,
    WorkflowStartedData,
    NodeStartedEvent,
    NodeStartedData,
    NodeFinishedEvent,
    NodeFinishedData,
    WorkflowFinishedEvent,
    WorkflowFinishedData
)
from celery_app.celery import celery_app
from datetime import datetime
import time
import json
from celery_app.tasks import execute_workflow_task
from app.engine.executor import WorkflowExecutor
from app.services.workflow_service import WorkflowService
from app.core.logging import logger
from typing import List
import uuid

router = APIRouter()

# --- Helper Methods ---

async def _create_execution_record(
    db: AsyncSession, 
    workflow_id: str, 
    project_id: str, 
    inputs: dict, 
    status: str = "running"
) -> WorkflowExecution:
    execution_id = str(uuid.uuid4())
    db_execution = WorkflowExecution(
        id=execution_id,
        project_id=project_id,
        workflow_id=workflow_id,
        status=status,
        input=inputs,
        started_at=datetime.utcnow()
    )
    db.add(db_execution)
    await db.commit()
    return db_execution

async def _run_stream_execution(
    workflow_id: str,
    project_id: str,
    execution_id: str,
    inputs: dict,
    workflow_definition: dict,
    started_at: datetime,
    db: AsyncSession
):
    start_time = time.time()
    task_id = f"stream-{execution_id}"
    node_count = 0
    
    # 1. Emit workflow_started
    started_event = WorkflowStartedEvent(
        workflow_run_id=execution_id,
        task_id=task_id,
        data=WorkflowStartedData(
            id=execution_id,
            workflow_id=workflow_id,
            inputs=inputs,
            created_at=int(started_at.timestamp())
        )
    )
    yield f"data: {started_event.model_dump_json()}\n\n"

    executor = WorkflowExecutor(workflow_definition, project_id=project_id)
    queue = asyncio.Queue()

    # Re-defining callbacks to use the queue
    async def q_on_node_start(node_id, node_type, node_data, index):
        nonlocal node_count
        node_count += 1
        event = NodeStartedEvent(
            workflow_run_id=execution_id,
            task_id=task_id,
            data=NodeStartedData(
                id=str(uuid.uuid4()),
                node_id=node_id,
                node_type=node_type,
                title=node_data.get("title", node_type),
                index=index,
                created_at=int(time.time())
            )
        )
        await queue.put(f"data: {event.model_dump_json()}\n\n")

    async def q_on_node_complete(node_id, node_type, status, input, output, error, duration):
        # Save to DB
        node_exec_id = str(uuid.uuid4())
        node_exec = NodeExecution(
            id=node_exec_id,
            execution_id=execution_id,
            project_id=project_id,
            node_id=node_id,
            node_type=node_type,
            status=status,
            input=input,
            output=output,
            error=error,
            duration=duration,
            started_at=datetime.utcnow()
        )
        db.add(node_exec)
        await db.commit()

        event = NodeFinishedEvent(
            workflow_run_id=execution_id,
            task_id=task_id,
            data=NodeFinishedData(
                id=node_exec_id,
                node_id=node_id,
                node_type=node_type,
                inputs=input,
                outputs=output,
                status="succeeded" if status == "completed" else "failed",
                error=error,
                elapsed_time=duration / 1000.0,
                finished_at=int(time.time())
            )
        )
        await queue.put(f"data: {event.model_dump_json()}\n\n")

    status = "completed"
    error_msg = None
    final_output = None

    try:
        # Run executor in a separate task
        async def run_executor():
            nonlocal final_output, status, error_msg
            try:
                final_output = await executor.run(inputs, on_node_start=q_on_node_start, on_node_complete=q_on_node_complete)
            except Exception as e:
                status = "failed"
                error_msg = str(e)
                logger.error(f"Workflow stream execution error: {traceback.format_exc()}")
            finally:
                await queue.put(None) # Signal end

        executor_task = asyncio.create_task(run_executor())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    except Exception as e:
        status = "failed"
        error_msg = str(e)

    # Update WorkflowExecution in DB
    duration_ms = int((time.time() - start_time) * 1000)
    await db.execute(
        update(WorkflowExecution)
        .where(WorkflowExecution.id == execution_id)
        .values(
            status=status,
            output=final_output,
            error=error_msg,
            completed_at=datetime.utcnow(),
            duration=duration_ms
        )
    )
    await db.commit()

    # Emit workflow_finished
    finished_event = WorkflowFinishedEvent(
        workflow_run_id=execution_id,
        task_id=task_id,
        data=WorkflowFinishedData(
            id=execution_id,
            workflow_id=workflow_id,
            status="succeeded" if status == "completed" else "failed",
            outputs=final_output if final_output is not None else {},
            error=error_msg,
            elapsed_time=duration_ms / 1000.0,
            total_steps=node_count,
            finished_at=int(time.time())
        )
    )
    yield f"data: {finished_event.model_dump_json()}\n\n"

async def _run_sync_execution(
    workflow_id: str,
    project_id: str,
    execution_id: str,
    inputs: dict,
    workflow_definition: dict,
    started_at: datetime,
    db: AsyncSession
):
    perf_start = time.time()
    executor = WorkflowExecutor(workflow_definition, project_id=project_id)
    
    # 定义同步模式下的回调（保存到 DB）
    async def sync_on_node_complete(node_id, node_type, status, input, output, error, duration):
        node_exec = NodeExecution(
            id=str(uuid.uuid4()),
            execution_id=execution_id,
            project_id=project_id,
            node_id=node_id,
            node_type=node_type,
            status=status,
            input=input,
            output=output,
            error=error,
            duration=duration,
            started_at=datetime.utcnow()
        )
        db.add(node_exec)
        await db.commit()

    success = True
    final_output = None
    error_msg = None
    try:
        final_output = await executor.run(inputs, on_node_complete=sync_on_node_complete)
    except Exception as e:
        success = False
        error_msg = str(e)
        logger.error(f"Workflow sync execution error: {traceback.format_exc()}")

    perf_duration = time.time() - perf_start
    end_time_dt = datetime.utcnow()
    
    # 更新最终状态
    await db.execute(
        update(WorkflowExecution)
        .where(WorkflowExecution.id == execution_id)
        .values(
            status="completed" if success else "failed",
            output=final_output,
            error=error_msg,
            completed_at=end_time_dt,
            duration=int(perf_duration * 1000)
        )
    )
    await db.commit()

    return {
        "success": success,
        "output": final_output if final_output is not None else {},
        "metadata": {
            "duration": round(perf_duration, 3),
            "startTime": started_at.isoformat() + "Z",
            "endTime": end_time_dt.isoformat() + "Z"
        }
    }

# --- Routes ---

@router.post(
    "/{workflow_id}/execute",
    summary="Execute Workflow",
    description="""
    Execute a workflow using one of three supported modes:
    
    1. **Synchronous Mode (Default, `stream=False`, `async=False`)**:
       Executes the workflow immediately and returns the final output. Ideal for short-lived tasks.
    
    2. **Asynchronous Mode (`async=True`)**:
       Creates an execution record and triggers a background Celery task. Returns the execution record immediately.
    
    3. **Streaming Mode (`stream=True`)**:
       Returns a Server-Sent Events (SSE) stream, pushing real-time events as the workflow progresses.
    
    ### Streaming Mode Events (SSE):
    When `stream=True`, the response header includes `Content-Type: text/event-stream`.
    Each message starts with `data: ` followed by a JSON string and ends with `\n\n`.
    
    - **workflow_started**: Workflow execution initialized.
    - **node_started**: A specific node has started executing.
    - **node_finished**: A specific node has finished (success or failure).
    - **workflow_finished**: Entire workflow has finished.
    """,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/WorkflowSyncResponse"},
                            {"$ref": "#/components/schemas/WorkflowExecution"}
                        ]
                    },
                    "examples": {
                        "sync_mode": {
                            "summary": "Synchronous Mode (Default)",
                            "description": "Returns final output and metadata.",
                            "value": {
                                "success": True,
                                "output": {"answer": "Paris is the capital of France."},
                                "metadata": {
                                    "duration": 1.234,
                                    "startTime": "2026-01-03T06:16:44.478Z",
                                    "endTime": "2026-01-03T06:16:45.712Z"
                                }
                            }
                        },
                        "async_mode": {
                            "summary": "Asynchronous Mode (async=true)",
                            "description": "Returns the execution record with 'pending' status.",
                            "value": {
                                "id": "d73d5f18-3cc0-400f-ab18-c0a5f05625f5",
                                "project_id": "proj-123",
                                "workflow_id": "wf-456",
                                "status": "pending",
                                "input": {"query": "What is the capital of France?"},
                                "output": None,
                                "error": None,
                                "started_at": "2026-01-03T06:16:44.478Z",
                                "completed_at": None,
                                "duration": None,
                                "node_executions": []
                            }
                        }
                    }
                },
                "text/event-stream": {
                    "description": "Streaming Mode (stream=true)",
                    "example": (
                        "data: {\"event\": \"workflow_started\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"uuid-1\", \"workflow_id\": \"wf-1\", \"inputs\": {}, \"created_at\": 1735790000}}\n\n"
                        "data: {\"event\": \"node_started\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"node-exec-1\", \"node_id\": \"node-1\", \"node_type\": \"llm\", \"title\": \"AI Chat\", \"index\": 1, \"created_at\": 1735790001}}\n\n"
                        "data: {\"event\": \"node_finished\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"node-exec-1\", \"node_id\": \"node-1\", \"node_type\": \"llm\", \"inputs\": {}, \"outputs\": {\"text\": \"Hello\"}, \"status\": \"succeeded\", \"error\": null, \"elapsed_time\": 0.5, \"finished_at\": 1735790002}}\n\n"
                        "data: {\"event\": \"workflow_finished\", \"workflow_run_id\": \"uuid-1\", \"task_id\": \"stream-uuid-1\", \"data\": {\"id\": \"uuid-1\", \"workflow_id\": \"wf-1\", \"status\": \"succeeded\", \"outputs\": {\"result\": \"Hello\"}, \"error\": null, \"elapsed_time\": 0.6, \"total_steps\": 1, \"finished_at\": 1735790002}}\n\n"
                    )
                }
            }
        },
        404: {"description": "Workflow not found"}
    }
)
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest,
    project_id: str = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db)
):
    # 1. Verify workflow exists and belongs to project
    workflow = await WorkflowService.get_by_id(db, workflow_id, project_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if request.stream:
        # --- 1. 流式执行模式 (SSE) ---
        db_execution = await _create_execution_record(db, workflow_id, project_id, request.inputs, status="running")
        return StreamingResponse(
            _run_stream_execution(
                workflow_id, project_id, db_execution.id, request.inputs, workflow.definition, db_execution.started_at, db
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    elif request.async_mode:
        # --- 2. 异步执行模式 (Celery) ---
        db_execution = await _create_execution_record(db, workflow_id, project_id, request.inputs, status="pending")
        
        # Trigger Celery task
        execute_workflow_task.delay(db_execution.id, workflow_id, request.inputs, project_id=project_id)
        
        # Re-query with eager loading to avoid lazy loading issues
        stmt = (
            select(WorkflowExecution)
            .options(selectinload(WorkflowExecution.node_executions))
            .where(WorkflowExecution.id == db_execution.id)
        )
        result = await db.execute(stmt)
        return result.scalar_one()
    else:
        # --- 3. 同步执行模式 (默认) ---
        db_execution = await _create_execution_record(db, workflow_id, project_id, request.inputs, status="running")
        return await _run_sync_execution(
            workflow_id, project_id, db_execution.id, request.inputs, workflow.definition, db_execution.started_at, db
        )

@router.get("/executions/{execution_id}", response_model=WorkflowExecutionSchema)
async def get_execution_status(
    execution_id: str,
    project_id: str = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(WorkflowExecution)
        .options(selectinload(WorkflowExecution.node_executions))
        .where(WorkflowExecution.id == execution_id, WorkflowExecution.project_id == project_id)
    )
    result = await db.execute(query)
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return execution

@router.get("/{workflow_id}/executions", response_model=List[WorkflowExecutionSchema])
async def get_workflow_executions(
    workflow_id: str,
    project_id: str = Query(..., description="Project ID"),
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(WorkflowExecution)
        .options(selectinload(WorkflowExecution.node_executions))
        .where(WorkflowExecution.workflow_id == workflow_id, WorkflowExecution.project_id == project_id)
        .order_by(desc(WorkflowExecution.started_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())

@router.post("/executions/{execution_id}/cancel", response_model=WorkflowExecutionCancelResponse)
async def cancel_execution(
    execution_id: str,
    project_id: str = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(WorkflowExecution)
        .where(WorkflowExecution.id == execution_id, WorkflowExecution.project_id == project_id)
    )
    result = await db.execute(query)
    execution = result.scalar_one_or_none()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
        
    if execution.status not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel execution in {execution.status} status")
        
    # Update status in DB
    execution.status = "cancelled"
    completed_at = datetime.utcnow()
    execution.completed_at = completed_at
    await db.commit()
    
    # Terminate Celery task if it's running
    celery_app.control.revoke(execution_id, terminate=True)
    
    return WorkflowExecutionCancelResponse(
        id=execution_id,
        status="cancelled",
        cancelled_at=completed_at
    )
