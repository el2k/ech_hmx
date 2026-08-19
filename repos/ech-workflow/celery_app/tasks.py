import asyncio
from celery_app.celery import celery_app
from app.database import AsyncSessionLocal
from app.services.workflow_service import WorkflowService
from app.models.execution import WorkflowExecution, NodeExecution
from app.engine.executor import WorkflowExecutor
from datetime import datetime
from sqlalchemy import update
import time
from app.core.logging import logger
import asyncio

@celery_app.task(
    name="execute_workflow_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True
)
def execute_workflow_task(self, execution_id: str, workflow_id: str, inputs: dict, project_id: str):
    try:
        return asyncio.run(async_execute_workflow(execution_id, workflow_id, inputs, project_id))
    except Exception as exc:
        logger.error(f"Task failed, retrying: {exc}")
        raise self.retry(exc=exc)

async def async_execute_workflow(execution_id: str, workflow_id: str, inputs: dict, project_id: str):
    async with AsyncSessionLocal() as db:
        # 1. Fetch workflow and execution
        workflow = await WorkflowService.get_by_id(db, workflow_id, project_id)
        if not workflow:
            logger.error(f"Workflow {workflow_id} not found for project {project_id}")
            return
            
        # Update status to running
        await db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id, WorkflowExecution.project_id == project_id)
            .values(status="running", started_at=datetime.utcnow())
        )
        await db.commit()
        
        executor = WorkflowExecutor(workflow.definition, project_id=project_id)
        
        start_time = time.time()
        
        async def on_node_complete(node_id, node_type, status, input, output, error, duration):
            logger.info(f"Node complete: {node_id} ({node_type}) status={status} duration={duration}ms")
            node_exec = NodeExecution(
                execution_id=execution_id,
                project_id=project_id,
                node_id=node_id,
                node_type=node_type,
                status=status,
                input=input,
                output=output,
                error=error,
                duration=duration,
                started_at=datetime.utcnow() # Simplified
            )
            db.add(node_exec)
            await db.commit()

        try:
            logger.info(f"Starting workflow execution: {execution_id} for workflow: {workflow_id}")
            final_output = await executor.run(inputs, on_node_complete=on_node_complete)
            
            duration = int((time.time() - start_time) * 1000)
            await db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id, WorkflowExecution.project_id == project_id)
                .values(
                    status="completed",
                    output={"result": final_output},
                    completed_at=datetime.utcnow(),
                    duration=duration
                )
            )
            logger.info(f"Workflow execution completed: {execution_id} in {duration}ms")
        except Exception as e:
            duration = int((time.time() - start_time) * 1000)
            logger.error(f"Workflow execution failed: {execution_id} error={e}")
            await db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id, WorkflowExecution.project_id == project_id)
                .values(
                    status="failed",
                    error=str(e),
                    completed_at=datetime.utcnow(),
                    duration=duration
                )
            )
            
        await db.commit()

