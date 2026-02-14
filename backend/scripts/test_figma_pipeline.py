#!/usr/bin/env python3
"""End-to-end test for Figma → Code pipeline.

Usage:
    # Default: uses known test Figma file (像素芝士 V2.9)
    python scripts/test_figma_pipeline.py

    # Custom Figma URL:
    python scripts/test_figma_pipeline.py --figma-url "https://www.figma.com/design/xxx/yyy?node-id=123-456"

    # Use existing JSON mode (skip Figma fetch):
    python scripts/test_figma_pipeline.py --json-mode --design-file data/design_export/design_export.json

    # Custom backend URL:
    python scripts/test_figma_pipeline.py --base-url http://localhost:9000

Requires:
    - Backend running (make dev)
    - FIGMA_TOKEN env var set (for Figma mode)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.parse import urljoin

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Run: pip install httpx")
    sys.exit(1)

# --- Default test data ---
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_FIGMA_URL = (
    "https://www.figma.com/design/6kGd851qaAX4TiL44vpIrO/"
    "%E5%83%8F%E7%B4%A0%E8%8A%9D%E5%A3%ABV2.9%E7%89%88%E6%9C%AC"
    "?node-id=16650-538"
)
DEFAULT_OUTPUT_DIR = "output/e2e_test"
DEFAULT_DESIGN_FILE = "data/design_export/design_export.json"

POLL_INTERVAL = 3.0  # seconds
MAX_POLL_TIME = 600.0  # 10 minutes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E2E test for Figma→Code pipeline")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL,
        help=f"Backend API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--figma-url", default=DEFAULT_FIGMA_URL,
        help="Figma design URL",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for generated code (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--json-mode", action="store_true",
        help="Use JSON mode (POST /run) instead of Figma mode (POST /run-figma)",
    )
    parser.add_argument(
        "--design-file", default=DEFAULT_DESIGN_FILE,
        help=f"Design export JSON path (for --json-mode, default: {DEFAULT_DESIGN_FILE})",
    )
    parser.add_argument(
        "--max-retries", type=int, default=2,
        help="Max retries per component (default: 2)",
    )
    parser.add_argument(
        "--timeout", type=float, default=MAX_POLL_TIME,
        help=f"Max wait time in seconds (default: {MAX_POLL_TIME})",
    )
    return parser.parse_args()


def api_url(base: str, path: str) -> str:
    """Build full API URL."""
    return urljoin(base.rstrip("/") + "/", f"api/v2/design{path}")


def step(msg: str) -> None:
    """Print a step header."""
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def check_health(client: httpx.Client, base_url: str) -> bool:
    """Check if the backend is reachable."""
    try:
        resp = client.get(api_url(base_url, ""))
        return resp.status_code in (200, 404, 422)  # any response means server is up
    except httpx.ConnectError:
        return False


def start_job(
    client: httpx.Client, base_url: str, args: argparse.Namespace
) -> dict:
    """Start a pipeline job (Figma or JSON mode)."""
    if args.json_mode:
        endpoint = "/run"
        payload = {
            "design_file": args.design_file,
            "output_dir": args.output_dir,
            "max_retries": args.max_retries,
        }
    else:
        endpoint = "/run-figma"
        payload = {
            "figma_url": args.figma_url,
            "output_dir": args.output_dir,
            "max_retries": args.max_retries,
        }

    mode = "JSON" if args.json_mode else "Figma"
    print(f"  Mode: {mode}")
    print(f"  Endpoint: POST {endpoint}")
    print(f"  Payload: {json.dumps(payload, indent=2)}")

    resp = client.post(api_url(base_url, endpoint), json=payload)
    if resp.status_code != 201:
        print(f"  ERROR: {resp.status_code} — {resp.text}")
        sys.exit(1)

    data = resp.json()
    print(f"  Job ID: {data['job_id']}")
    print(f"  Status: {data['status']}")
    return data


def poll_until_done(
    client: httpx.Client, base_url: str, job_id: str, timeout: float
) -> dict:
    """Poll job status until completed or failed."""
    start_time = time.time()
    last_progress = ""

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            print(f"\n  TIMEOUT after {elapsed:.0f}s")
            sys.exit(1)

        resp = client.get(api_url(base_url, f"/{job_id}"))
        if resp.status_code != 200:
            print(f"  ERROR polling status: {resp.status_code}")
            sys.exit(1)

        data = resp.json()
        status = data["status"]
        total = data.get("components_total", 0)
        completed = data.get("components_completed", 0)
        failed = data.get("components_failed", 0)

        progress = f"{status} — {completed}/{total} components ({failed} failed)"
        if progress != last_progress:
            print(f"  [{elapsed:5.1f}s] {progress}")
            last_progress = progress

        if status in ("completed", "failed"):
            return data

        time.sleep(POLL_INTERVAL)


def check_files(client: httpx.Client, base_url: str, job_id: str) -> list:
    """Fetch generated files list."""
    resp = client.get(api_url(base_url, f"/{job_id}/files"))
    if resp.status_code != 200:
        print(f"  ERROR fetching files: {resp.status_code} — {resp.text}")
        return []

    data = resp.json()
    files = data.get("files", [])
    print(f"  Files generated: {len(files)}")
    for f in files:
        print(f"    - {f['path']} ({f['size']} bytes)")
    return files


def check_preview(client: httpx.Client, base_url: str, job_id: str) -> bool:
    """Verify preview endpoint returns valid HTML."""
    url = api_url(base_url, f"/{job_id}/preview")
    resp = client.get(url)

    if resp.status_code != 200:
        print(f"  ERROR: preview returned {resp.status_code}")
        return False

    content_type = resp.headers.get("content-type", "")
    html = resp.text
    has_html = "<html" in html.lower() or "<!doctype" in html.lower()
    has_react = "react" in html.lower() or "babel" in html.lower()

    print(f"  Status: {resp.status_code}")
    print(f"  Content-Type: {content_type}")
    print(f"  Size: {len(html)} bytes")
    print(f"  Contains HTML: {has_html}")
    print(f"  Contains React/Babel: {has_react}")
    print(f"  Preview URL: {url}")

    return has_html


def print_summary(job: dict, files: list, preview_ok: bool, elapsed: float) -> None:
    """Print final test results."""
    status = job["status"]
    total = job.get("components_total", 0)
    completed = job.get("components_completed", 0)
    failed = job.get("components_failed", 0)
    error = job.get("error")

    passed = status == "completed" and preview_ok and failed == 0

    print(f"\n  Job ID:     {job['job_id']}")
    print(f"  Status:     {status}")
    print(f"  Components: {completed}/{total} completed, {failed} failed")
    print(f"  Files:      {len(files)} generated")
    print(f"  Preview:    {'OK' if preview_ok else 'FAILED'}")
    print(f"  Duration:   {elapsed:.1f}s")
    if error:
        print(f"  Error:      {error}")

    print(f"\n  {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> None:
    args = parse_args()
    client = httpx.Client(timeout=30.0)

    # Step 0: Health check
    step("Step 0: Backend health check")
    if not check_health(client, args.base_url):
        print(f"  ERROR: Cannot connect to {args.base_url}")
        print(f"  Make sure the backend is running (make dev)")
        sys.exit(1)
    print(f"  Backend is reachable at {args.base_url}")

    # Step 1: Start job
    step("Step 1: Start pipeline job")
    start_time = time.time()
    job = start_job(client, args.base_url, args)
    job_id = job["job_id"]

    # Step 2: Poll until done
    step("Step 2: Waiting for pipeline completion")
    result = poll_until_done(client, args.base_url, job_id, args.timeout)
    elapsed = time.time() - start_time

    # Step 3: Check generated files
    step("Step 3: Checking generated files")
    files = check_files(client, args.base_url, job_id)

    # Step 4: Check preview
    step("Step 4: Verifying preview endpoint")
    preview_ok = check_preview(client, args.base_url, job_id)

    # Summary
    step("RESULTS")
    passed = print_summary(result, files, preview_ok, elapsed)

    client.close()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
