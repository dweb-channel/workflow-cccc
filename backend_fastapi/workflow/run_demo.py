import asyncio
import uuid

from temporalio.client import Client

from .config import TASK_QUEUE
from .workflows import BusinessWorkflow


async def main() -> None:
    client = await Client.connect("localhost:7233")
    workflow_id = f"business-workflow-{uuid.uuid4().hex[:8]}"

    handle = await client.start_workflow(
        BusinessWorkflow.run,
        "Implement a multi-agent workflow with confirmation steps.",
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    await asyncio.sleep(1)
    await handle.signal(BusinessWorkflow.confirm_initial, True, "Looks good, proceed.")

    await asyncio.sleep(1)
    await handle.signal(BusinessWorkflow.confirm_final, True, "Approved for implementation.")

    result = await handle.result()
    print("Workflow result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
