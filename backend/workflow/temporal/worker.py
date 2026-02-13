import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import execute_dynamic_graph_activity
from .batch_activities import execute_batch_bugfix_activity
from ..config import TASK_QUEUE, TEMPORAL_ADDRESS
from .workflows import DynamicWorkflow
from .batch_workflow import BatchBugFixWorkflow


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[DynamicWorkflow, BatchBugFixWorkflow],
        activities=[execute_dynamic_graph_activity, execute_batch_bugfix_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
