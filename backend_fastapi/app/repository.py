"""Repository layer for workflow persistence.

Provides async CRUD operations for WorkflowModel using SQLAlchemy.
Designed to coexist with in-memory storage during migration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .db_models import WorkflowModel


class WorkflowRepository:
    """Data access layer for workflow definitions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        name: str,
        description: Optional[str] = None,
        graph_definition: Optional[Dict[str, Any]] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> WorkflowModel:
        """Create a new workflow."""
        workflow = WorkflowModel(
            name=name,
            description=description,
            graph_definition=graph_definition,
            parameters=parameters,
        )
        self.session.add(workflow)
        await self.session.flush()
        return workflow

    async def get(self, workflow_id: str) -> Optional[WorkflowModel]:
        """Get a workflow by ID."""
        result = await self.session.execute(
            select(WorkflowModel).where(WorkflowModel.id == workflow_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[WorkflowModel], int]:
        """List workflows with optional filtering and pagination.

        Returns:
            Tuple of (workflows, total_count)
        """
        query = select(WorkflowModel)
        count_query = select(func.count()).select_from(WorkflowModel)

        if status:
            query = query.where(WorkflowModel.status == status)
            count_query = count_query.where(WorkflowModel.status == status)

        query = query.order_by(WorkflowModel.updated_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(query)
        workflows = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return workflows, total

    async def update(
        self,
        workflow_id: str,
        **kwargs: Any,
    ) -> Optional[WorkflowModel]:
        """Update a workflow's fields.

        Accepts any WorkflowModel column name as keyword argument.
        """
        workflow = await self.get(workflow_id)
        if not workflow:
            return None

        for key, value in kwargs.items():
            if hasattr(workflow, key):
                setattr(workflow, key, value)

        await self.session.flush()
        return workflow

    async def update_graph(
        self,
        workflow_id: str,
        graph_definition: Dict[str, Any],
    ) -> Optional[WorkflowModel]:
        """Update workflow graph definition specifically."""
        return await self.update(
            workflow_id,
            graph_definition=graph_definition,
        )

    async def delete(self, workflow_id: str) -> bool:
        """Delete a workflow by ID. Returns True if deleted."""
        workflow = await self.get(workflow_id)
        if not workflow:
            return False
        await self.session.delete(workflow)
        await self.session.flush()
        return True

    async def update_status(
        self,
        workflow_id: str,
        status: str,
    ) -> Optional[WorkflowModel]:
        """Update workflow status (draft/published/archived)."""
        return await self.update(workflow_id, status=status)
