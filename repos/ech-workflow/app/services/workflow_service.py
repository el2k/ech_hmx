from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, desc, func, or_
from app.models.workflow import Workflow
from app.models.execution import WorkflowExecution, NodeExecution
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate, WorkflowDefinition
from typing import List, Optional, Tuple
import uuid

class WorkflowService:
    @staticmethod
    async def get_all(
        db: AsyncSession, 
        project_id: str,
        skip: int = 0, 
        limit: int = 100, 
        status: Optional[str] = None,
        search: Optional[str] = None,
        tags: Optional[List[str]] = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc"
    ) -> Tuple[List[Workflow], int]:
        # Count total
        count_query = select(func.count()).select_from(Workflow).where(Workflow.project_id == project_id)
        
        # Base query
        query = select(Workflow).where(Workflow.project_id == project_id)
        
        # Filters
        filters = []
        if status:
            filters.append(Workflow.status == status)
        if search:
            filters.append(or_(
                Workflow.name.ilike(f"%{search}%"),
                Workflow.description.ilike(f"%{search}%")
            ))
        if tags:
            filters.append(Workflow.tags.overlap(tags))
            
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)
            
        # Sorting
        sort_attr = getattr(Workflow, sort_by, Workflow.updated_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_attr))
        else:
            query = query.order_by(sort_attr)
            
        # Pagination
        query = query.offset(skip).limit(limit)
        
        # Execute
        count_result = await db.execute(count_query)
        total = count_result.scalar_one()
        
        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def get_by_id(db: AsyncSession, workflow_id: str, project_id: str) -> Optional[Workflow]:
        query = select(Workflow).where(Workflow.id == workflow_id, Workflow.project_id == project_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_ids(db: AsyncSession, project_id: str, workflow_ids: List[str]) -> List[Workflow]:
        query = select(Workflow).where(Workflow.id.in_(workflow_ids), Workflow.project_id == project_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create(db: AsyncSession, project_id: str, workflow_in: WorkflowCreate) -> Workflow:
        definition = {
            "nodes": [node.model_dump() for node in workflow_in.nodes],
            "edges": [edge.model_dump() for edge in workflow_in.edges]
        }
        db_workflow = Workflow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=workflow_in.name,
            description=workflow_in.description,
            definition=definition,
            tags=workflow_in.tags,
            status="draft",
            version=1
        )
        db.add(db_workflow)
        await db.flush()
        await db.refresh(db_workflow)
        return db_workflow

    @staticmethod
    async def update(db: AsyncSession, workflow_id: str, project_id: str, workflow_in: WorkflowUpdate) -> Optional[Workflow]:
        workflow = await WorkflowService.get_by_id(db, workflow_id, project_id)
        if not workflow:
            return None
        
        update_data = workflow_in.model_dump(exclude_unset=True)
        
        # Handle definition update if nodes or edges are provided
        if "nodes" in update_data or "edges" in update_data:
            nodes = update_data.pop("nodes", workflow.definition.get("nodes", []))
            edges = update_data.pop("edges", workflow.definition.get("edges", []))
            if isinstance(edges, list) and len(edges) > 0 and not isinstance(edges[0], dict):
                edges = [edge.model_dump() if hasattr(edge, "model_dump") else edge for edge in edges]
            workflow.definition = {"nodes": nodes, "edges": edges}
            workflow.version += 1

        for key, value in update_data.items():
            setattr(workflow, key, value)
        
        await db.flush()
        await db.refresh(workflow)
        return workflow

    @staticmethod
    async def delete(db: AsyncSession, workflow_id: str, project_id: str) -> bool:
        # Check if workflow exists first to avoid unnecessary deletions
        workflow = await WorkflowService.get_by_id(db, workflow_id, project_id)
        if not workflow:
            return False

        # 1. Delete node executions related to this workflow's executions
        # We need to find all execution IDs first
        execution_ids_query = select(WorkflowExecution.id).where(WorkflowExecution.workflow_id == workflow_id)
        execution_ids_result = await db.execute(execution_ids_query)
        execution_ids = execution_ids_result.scalars().all()
        
        if execution_ids:
            delete_node_execs = delete(NodeExecution).where(NodeExecution.execution_id.in_(execution_ids))
            await db.execute(delete_node_execs)

        # 2. Delete workflow executions
        delete_workflow_execs = delete(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)
        await db.execute(delete_workflow_execs)

        # 3. Delete the workflow itself
        query = delete(Workflow).where(Workflow.id == workflow_id, Workflow.project_id == project_id)
        result = await db.execute(query)
        
        await db.flush() # Ensure deletions are processed
        return result.rowcount > 0

    @staticmethod
    async def duplicate(db: AsyncSession, workflow_id: str, project_id: str, new_name: Optional[str] = None) -> Optional[Workflow]:
        original = await WorkflowService.get_by_id(db, workflow_id, project_id)
        if not original:
            return None
        
        new_workflow = Workflow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=new_name or f"{original.name} (Copy)",
            description=original.description,
            definition=original.definition.copy(),
            tags=original.tags,
            status="draft",
            version=1
        )
        db.add(new_workflow)
        await db.flush()
        await db.refresh(new_workflow)
        return new_workflow

    @staticmethod
    async def publish(db: AsyncSession, workflow_id: str, project_id: str) -> Optional[Workflow]:
        workflow = await WorkflowService.get_by_id(db, workflow_id, project_id)
        if not workflow:
            return None
        
        workflow.status = "active"
        workflow.version += 1
        await db.flush()
        await db.refresh(workflow)
        return workflow

