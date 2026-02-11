#!/usr/bin/env bash
# =============================================================================
# Docker E2E Verification Script for T076
# Tests: health, API CRUD, templates, batch-bug-fix history, frontend
# Usage: bash tests/docker_e2e_verify.sh [BACKEND_URL] [FRONTEND_URL]
# =============================================================================

set -euo pipefail

BACKEND_URL="${1:-http://localhost:8000}"
FRONTEND_URL="${2:-http://localhost:3000}"
PASS=0
FAIL=0
TOTAL=0

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_pass() { ((PASS++)); ((TOTAL++)); echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { ((FAIL++)); ((TOTAL++)); echo -e "  ${RED}✗${NC} $1 — $2"; }
log_section() { echo -e "\n${YELLOW}▶ $1${NC}"; }

# Helper: HTTP status check
check_status() {
  local desc="$1" url="$2" expected="${3:-200}" method="${4:-GET}" body="${5:-}"
  local status
  if [ "$method" = "GET" ]; then
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null) || status="000"
  elif [ "$method" = "POST" ]; then
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -X POST \
      -H "Content-Type: application/json" -d "$body" "$url" 2>/dev/null) || status="000"
  elif [ "$method" = "DELETE" ]; then
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -X DELETE "$url" 2>/dev/null) || status="000"
  fi
  if [ "$status" = "$expected" ]; then
    log_pass "$desc (HTTP $status)"
  else
    log_fail "$desc" "expected $expected, got $status"
  fi
}

# Helper: JSON field check
check_json_field() {
  local desc="$1" url="$2" field="$3" expected="$4"
  local value
  value=$(curl -s --max-time 10 "$url" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    keys = '$field'.split('.')
    val = data
    for k in keys:
        val = val[k]
    print(val)
except Exception as e:
    print(f'ERROR:{e}')
" 2>/dev/null) || value="ERROR:curl_failed"
  if [ "$value" = "$expected" ]; then
    log_pass "$desc ($field=$value)"
  else
    log_fail "$desc" "expected $field=$expected, got $value"
  fi
}

# Helper: wait for service
wait_for_service() {
  local url="$1" name="$2" timeout="${3:-60}"
  echo -n "  Waiting for $name ($url) "
  for i in $(seq 1 "$timeout"); do
    if curl -s --max-time 2 "$url" > /dev/null 2>&1; then
      echo -e " ${GREEN}ready${NC} (${i}s)"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo -e " ${RED}timeout after ${timeout}s${NC}"
  return 1
}

echo "============================================"
echo "  Docker E2E Verification (T076)"
echo "  Backend:  $BACKEND_URL"
echo "  Frontend: $FRONTEND_URL"
echo "============================================"

# ─────────────────────────────────────────────────
# S1: Docker Compose Health
# ─────────────────────────────────────────────────
log_section "S1: Service Health Checks"

wait_for_service "$BACKEND_URL/health" "Backend API" 60 || { echo "Backend not ready, aborting."; exit 1; }
wait_for_service "$FRONTEND_URL" "Frontend" 60 || { echo "Frontend not ready, aborting."; exit 1; }

check_json_field "Backend /health" "$BACKEND_URL/health" "status" "ok"

# Check Docker container status
if command -v docker &>/dev/null; then
  echo ""
  echo "  Docker containers:"
  docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || \
    docker-compose ps 2>/dev/null || echo "  (docker compose not available in this dir)"
fi

# ─────────────────────────────────────────────────
# S2: Frontend Page Load
# ─────────────────────────────────────────────────
log_section "S2: Frontend Page Load"

check_status "Frontend root page" "$FRONTEND_URL" "200"

# Check for Next.js markers in HTML
FRONTEND_HTML=$(curl -s --max-time 10 "$FRONTEND_URL" 2>/dev/null)
if echo "$FRONTEND_HTML" | grep -q "__next\|_next"; then
  log_pass "Next.js page rendered (found __next marker)"
else
  log_fail "Next.js page render" "no __next marker found in HTML"
fi

# Check static assets
NEXT_STATIC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$FRONTEND_URL/_next/static" 2>/dev/null) || NEXT_STATIC="000"
# 200 or 404 are both acceptable (depends on exact path), but 000/502/503 means frontend down
if [ "$NEXT_STATIC" != "000" ] && [ "$NEXT_STATIC" != "502" ] && [ "$NEXT_STATIC" != "503" ]; then
  log_pass "Frontend static asset path accessible (HTTP $NEXT_STATIC)"
else
  log_fail "Frontend static assets" "got HTTP $NEXT_STATIC"
fi

# ─────────────────────────────────────────────────
# S3: Backend API Endpoints
# ─────────────────────────────────────────────────
log_section "S3: Backend API Verification"

check_status "GET /api/v2/workflows" "$BACKEND_URL/api/v2/workflows" "200"
check_status "GET /api/v2/node-types" "$BACKEND_URL/api/v2/node-types" "200"
check_status "GET /api/v2/templates" "$BACKEND_URL/api/v2/templates" "200"

# CCCC endpoints (may return empty lists, that's fine)
check_status "GET /api/v2/cccc/groups" "$BACKEND_URL/api/v2/cccc/groups" "200"
check_status "GET /api/v2/cccc/batch-bug-fix (history)" "$BACKEND_URL/api/v2/cccc/batch-bug-fix" "200"

# ─────────────────────────────────────────────────
# S4: Workflow CRUD + Template
# ─────────────────────────────────────────────────
log_section "S4: Workflow CRUD + Template"

# Create workflow
CREATE_RESP=$(curl -s --max-time 10 -X POST \
  -H "Content-Type: application/json" \
  -d '{"name":"Docker E2E Test Workflow","description":"Created by docker_e2e_verify.sh"}' \
  "$BACKEND_URL/api/v2/workflows" 2>/dev/null)

WORKFLOW_ID=$(echo "$CREATE_RESP" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('id', data.get('workflow_id', '')))
except: print('')
" 2>/dev/null)

if [ -n "$WORKFLOW_ID" ] && [ "$WORKFLOW_ID" != "" ]; then
  log_pass "POST /api/v2/workflows — created workflow $WORKFLOW_ID"
else
  log_fail "POST /api/v2/workflows" "no workflow_id in response: $CREATE_RESP"
fi

# Read workflow
if [ -n "$WORKFLOW_ID" ]; then
  check_status "GET /api/v2/workflows/$WORKFLOW_ID" "$BACKEND_URL/api/v2/workflows/$WORKFLOW_ID" "200"
fi

# List workflows (should have at least 1)
WF_COUNT=$(curl -s --max-time 10 "$BACKEND_URL/api/v2/workflows" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    items = data.get('items', data.get('workflows', []))
    print(len(items))
except: print(0)
" 2>/dev/null)
if [ "$WF_COUNT" -gt 0 ] 2>/dev/null; then
  log_pass "Workflow list contains $WF_COUNT item(s)"
else
  log_fail "Workflow list" "expected >0 items, got $WF_COUNT"
fi

# Get templates
TMPL_COUNT=$(curl -s --max-time 10 "$BACKEND_URL/api/v2/templates" 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list): print(len(data))
    else: print(len(data.get('templates', data.get('items', []))))
except: print(0)
" 2>/dev/null)
if [ "$TMPL_COUNT" -gt 0 ] 2>/dev/null; then
  log_pass "Templates endpoint returned $TMPL_COUNT template(s)"
else
  log_fail "Templates" "expected >0, got $TMPL_COUNT"
fi

# Validate workflow graph (empty graph returns 422, which is correct validation behavior)
if [ -n "$WORKFLOW_ID" ]; then
  check_status "POST validate-graph (empty → 422 expected)" \
    "$BACKEND_URL/api/v2/validate-graph" "422" "POST" \
    '{"nodes":[],"edges":[]}'
fi

# Delete workflow (cleanup)
if [ -n "$WORKFLOW_ID" ]; then
  check_status "DELETE /api/v2/workflows/$WORKFLOW_ID" "$BACKEND_URL/api/v2/workflows/$WORKFLOW_ID" "204" "DELETE"
fi

# Verify deletion
if [ -n "$WORKFLOW_ID" ]; then
  check_status "GET deleted workflow returns 404" "$BACKEND_URL/api/v2/workflows/$WORKFLOW_ID" "404"
fi

# ─────────────────────────────────────────────────
# S5: Batch Bug Fix History
# ─────────────────────────────────────────────────
log_section "S5: Batch Bug Fix History"

check_status "GET /api/v2/cccc/batch-bug-fix?page=1&page_size=5" \
  "$BACKEND_URL/api/v2/cccc/batch-bug-fix?page=1&page_size=5" "200"

HISTORY_RESP=$(curl -s --max-time 10 "$BACKEND_URL/api/v2/cccc/batch-bug-fix?page=1&page_size=5" 2>/dev/null)
HISTORY_OK=$(echo "$HISTORY_RESP" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    # Check it has expected shape (items/jobs array + total/pagination)
    has_items = 'items' in data or 'jobs' in data
    has_total = 'total' in data or 'page' in data
    print('ok' if has_items or has_total else 'bad_shape')
except Exception as e:
    print(f'parse_error:{e}')
" 2>/dev/null)
if [ "$HISTORY_OK" = "ok" ]; then
  log_pass "Batch bug fix history response has correct shape"
else
  log_fail "Batch bug fix history shape" "$HISTORY_OK"
fi

# ─────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────
echo ""
echo "============================================"
echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC} / $TOTAL total"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
  echo -e "${RED}VERIFICATION FAILED${NC} — $FAIL test(s) failed"
  exit 1
else
  echo -e "${GREEN}ALL CHECKS PASSED${NC}"
  exit 0
fi
