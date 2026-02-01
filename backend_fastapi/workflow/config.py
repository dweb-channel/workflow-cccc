"""Workflow configuration constants."""

import os

# Temporal task queue name — single source of truth
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "business-workflow-task-queue")
