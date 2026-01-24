import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import parse_requirements, plan_review_dispatch
from .config import TASK_QUEUE
from .workflows import BusinessWorkflow


async def main() -> None:
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[BusinessWorkflow],
        activities=[parse_requirements, plan_review_dispatch],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
