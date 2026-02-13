"""Conftest for workflow tests.

Mocks external dependencies (temporalio) that may not be installed
in all test environments. This must run before any workflow.temporal
imports happen.
"""

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock temporalio if not installed
# ---------------------------------------------------------------------------
# batch_activities.py, activities.py, workflows.py, etc. all import from
# temporalio at module level. If temporalio is not installed, we need to
# provide mock modules so the imports succeed.
#
# Only install mocks if temporalio is genuinely missing — if it IS installed
# (e.g., in the project venv), use the real thing.
# ---------------------------------------------------------------------------

if "temporalio" not in sys.modules:
    try:
        import temporalio  # noqa: F401
    except ModuleNotFoundError:
        # Create mock module hierarchy
        _temporalio = MagicMock()

        # temporalio.activity — needs .defn as a passthrough decorator
        _activity = MagicMock()
        _activity.defn = lambda fn=None, **kwargs: fn if fn else (lambda f: f)
        _activity.heartbeat = MagicMock()
        _activity.info = MagicMock()
        _temporalio.activity = _activity

        # temporalio.workflow — needs .defn and .run as passthrough decorators
        _workflow = MagicMock()
        _workflow.defn = lambda cls=None, **kwargs: cls if cls else (lambda c: c)
        _workflow.run = lambda fn=None, **kwargs: fn if fn else (lambda f: f)
        _temporalio.workflow = _workflow

        # temporalio.client
        _temporalio.client = MagicMock()

        # temporalio.worker
        _temporalio.worker = MagicMock()

        # Register in sys.modules
        sys.modules["temporalio"] = _temporalio
        sys.modules["temporalio.activity"] = _activity
        sys.modules["temporalio.workflow"] = _workflow
        sys.modules["temporalio.client"] = _temporalio.client
        sys.modules["temporalio.worker"] = _temporalio.worker
