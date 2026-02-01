# Test Fixtures Maintenance Guide

## Overview

This directory contains the **Single Source of Truth (SSOT)** for workflow validation testing across front-end and back-end.

### Key Principle: One Fixture, Two Runtimes

```
validation_test_cases.json
    ├── Frontend (TypeScript): FixtureLoader → Jest/Vitest tests
    └── Backend (Python): FixtureLoader → pytest tests
```

**Goal**: Front-end and back-end validation logic **MUST** produce identical results for the same input.

## File Structure

```
tests/fixtures/
├── validation_test_cases.json    # Main fixture file (SSOT)
├── README.md                      # This file
└── [future]                       # Additional fixture categories (e.g., sse_events.json)
```

## validation_test_cases.json Schema

### Top-Level Structure

```json
{
  "version": "1.0",
  "last_updated": "YYYY-MM-DD",
  "schema_version": "1.0",
  "description": "...",
  "validation_test_cases": [...],
  "metadata": {
    "usage_notes": [...],
    "version_history": [...]
  }
}
```

### Test Case Structure

Each test case contains:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique identifier (e.g., `circular_dependency`) |
| `since_version` | string | ✅ | Version when test was added (e.g., `"1.0"`) |
| `phase` | string | ✅ | Implementation phase (e.g., `"Phase 1"`) |
| `priority` | string | ✅ | `P0` (CI gate, <5sec), `P1` (regression), `P2` (performance) |
| `tags` | array | ✅ | Categorization (e.g., `["graph-structure", "error"]`) |
| `description` | string | ✅ | What this test validates (in Chinese) |
| `workflow` | object | ✅ | Workflow definition (nodes + edges) |
| `expected_validation_result` | object | ✅ | Expected validation output |
| `test_instructions` | object | ✅ | Implementation guidance for frontend/backend/CI |

### Error Object Structure (in expected_validation_result)

```json
{
  "code": "ERROR_CODE",
  "message": "Human-readable description",
  "severity": "error" | "warning",
  "node_ids": ["node-1", "node-2"],  // Always plural array
  "context": {
    // Error-specific context fields
    // MUST be complete and actionable (zero defensive checks in frontend)
  }
}
```

### Context Field Contracts (Critical)

These guarantees enable **zero defensive checks** in frontend code:

| Error Code | Required Context Fields | Contract |
|------------|------------------------|----------|
| `MISSING_FIELD_REFERENCE` | `field`, `available_fields`, `upstream_node_ids` | `available_fields` MUST be non-empty array |
| `CIRCULAR_DEPENDENCY` | `cycle_path` | `cycle_path` MUST have at least 3 nodes (start + 1+ middle + start) |
| `DANGLING_NODE` | `node_ids` | Always single node; `connection_suggestions` optional |
| `INVALID_NODE_CONFIG` | `node_type`, `validation_errors` | `validation_errors` MUST be non-empty array of `{field, error}` |
| `JUMP_REFERENCE` | `referenced_field`, `intermediate_nodes`, `suggestion` | `intermediate_nodes` MUST be non-empty array |

**Frontend Code Example**:

```typescript
// ✅ CORRECT: Zero defensive checks (guaranteed by fixture contract)
function renderFieldPicker(error: ValidationError) {
  return <FieldPicker fields={error.context.available_fields} />;
  // No need for: if (!error.context.available_fields?.length) ...
}

// ❌ WRONG: Defensive programming (fixture contract violated)
function renderFieldPicker(error: ValidationError) {
  const fields = error.context.available_fields || [];
  if (fields.length === 0) return <div>No fields available</div>;
  return <FieldPicker fields={fields} />;
}
```

## Adding New Test Cases

### Step 1: Determine Metadata

1. **ID**: Use snake_case, descriptive name (e.g., `state_schema_mismatch`)
2. **Priority**:
   - `P0`: Blocks workflow execution, MUST run in CI (<5 sec)
   - `P1`: Important but non-blocking (e.g., warnings)
   - `P2`: Performance/edge cases
3. **Phase**: Which implementation phase this belongs to
4. **Tags**: At least 2 tags for categorization

### Step 2: Design Minimal Workflow

- Use **minimal nodes/edges** to reproduce the error
- Avoid unrelated complexity
- Node IDs: `node-1`, `node-2`, etc. (consistent numbering)

### Step 3: Define Expected Result

- `valid`: `true` (warnings only) or `false` (has errors)
- `errors`: Array of error objects (empty if valid)
- `warnings`: Array of warning objects

**Critical**: Ensure `context` fields satisfy the contracts above.

### Step 4: Write Test Instructions

Provide clear guidance for:
- **Frontend**: How to render UI (which context fields to use)
- **Backend**: Algorithm/logic to implement
- **CI gate**: Performance requirements

### Step 5: Update Version History

Add entry to `metadata.version_history`:

```json
{
  "version": "1.1",
  "date": "YYYY-MM-DD",
  "changes": "Added state_schema_mismatch test for Phase 2"
}
```

### Step 6: Notify Team for Review

After adding test case:

1. Create PR or commit to feature branch
2. Notify:
   - `@code-simplifier` - Frontend compatibility review
   - `@domain-expert` - Backend completeness review
   - `@superpowers-peer` - Architecture consistency review
3. Get approval before merging

## Fixture Version Evolution

### Version Numbering

- **Major version** (e.g., `1.0` → `2.0`): Breaking schema changes
- **Minor version** (e.g., `1.0` → `1.1`): New test cases, backward compatible

### Backward Compatibility Rules

**✅ Safe Changes**:
- Adding new test cases
- Adding optional context fields to existing errors
- Adding new tags
- Updating descriptions

**❌ Breaking Changes** (require major version bump):
- Removing test cases (mark as `deprecated` instead)
- Removing required context fields
- Changing error codes
- Changing `expected_validation_result` structure

### Deprecating Test Cases

Instead of deleting, add `deprecated: true`:

```json
{
  "id": "old_test",
  "deprecated": true,
  "deprecated_since": "1.2",
  "deprecated_reason": "Replaced by new_test",
  ...
}
```

## Frontend Usage

### TypeScript FixtureLoader

```typescript
import fixtures from '@/tests/fixtures/validation_test_cases.json';

export class FixtureLoader {
  static getTestCase(id: string) {
    return fixtures.validation_test_cases.find(tc => tc.id === id);
  }

  static getTestCasesByPriority(priority: 'P0' | 'P1' | 'P2') {
    return fixtures.validation_test_cases.filter(tc => tc.priority === priority);
  }

  static getTestCasesByTag(tag: string) {
    return fixtures.validation_test_cases.filter(tc => tc.tags.includes(tag));
  }
}
```

### Jest/Vitest Test Example

```typescript
import { FixtureLoader } from './FixtureLoader';
import { validateWorkflowClient } from '@/lib/validation/validator';

describe('Validation: Circular Dependency', () => {
  it('should detect circular dependencies', () => {
    const fixture = FixtureLoader.getTestCase('circular_dependency');
    const result = validateWorkflowClient(fixture.workflow);

    expect(result).toEqual(fixture.expected_validation_result);
  });
});
```

## Backend Usage

### Python FixtureLoader

```python
import json
from pathlib import Path
from typing import Dict, List, Any

class FixtureLoader:
    _fixtures = None

    @classmethod
    def load(cls):
        if cls._fixtures is None:
            fixture_path = Path(__file__).parent / 'validation_test_cases.json'
            with open(fixture_path, 'r', encoding='utf-8') as f:
                cls._fixtures = json.load(f)
        return cls._fixtures

    @classmethod
    def get_test_case(cls, test_id: str) -> Dict[str, Any]:
        fixtures = cls.load()
        for tc in fixtures['validation_test_cases']:
            if tc['id'] == test_id:
                return tc
        raise ValueError(f"Test case not found: {test_id}")

    @classmethod
    def get_test_cases_by_priority(cls, priority: str) -> List[Dict[str, Any]]:
        fixtures = cls.load()
        return [tc for tc in fixtures['validation_test_cases'] if tc['priority'] == priority]
```

### Pytest Test Example

```python
import pytest
from tests.fixtures.FixtureLoader import FixtureLoader
from app.validation.validator import validate_workflow

def test_circular_dependency():
    fixture = FixtureLoader.get_test_case('circular_dependency')
    result = validate_workflow(fixture['workflow'])

    assert result == fixture['expected_validation_result']
```

## CI Integration

### CI Configuration (.github/workflows/validation-tests.yml)

```yaml
name: Validation Tests

on: [push, pull_request]

jobs:
  fast-validation:
    name: Fast Validation (P0 only)
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - uses: actions/checkout@v3
      - name: Run P0 tests
        run: |
          # Frontend
          npm test -- --testNamePattern="P0"

          # Backend
          pytest -m "priority_p0" --maxfail=1 --timeout=5

  full-validation:
    name: Full Validation (P0 + P1 + P2)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run all validation tests
        run: |
          npm test -- tests/validation/
          pytest tests/validation/
```

### pytest Markers (conftest.py)

```python
import pytest
from tests.fixtures.FixtureLoader import FixtureLoader

def pytest_configure(config):
    config.addinivalue_line("markers", "priority_p0: P0 priority tests (fast CI)")
    config.addinivalue_line("markers", "priority_p1: P1 priority tests (regression)")
    config.addinivalue_line("markers", "priority_p2: P2 priority tests (performance)")

# Auto-generate test markers from fixture metadata
def pytest_collection_modifyitems(config, items):
    fixtures = FixtureLoader.load()
    fixture_priorities = {tc['id']: tc['priority'] for tc in fixtures['validation_test_cases']}

    for item in items:
        # Extract fixture ID from test name
        for fixture_id, priority in fixture_priorities.items():
            if fixture_id in item.nodeid:
                item.add_marker(getattr(pytest.mark, f'priority_{priority.lower()}'))
```

## Maintenance Schedule

| Frequency | Task | Owner |
|-----------|------|-------|
| Per PR | Review new test cases | code-simplifier, domain-expert, superpowers-peer |
| Per Phase | Add phase-specific test cases | browser-tester |
| Per Release | Validate fixture integrity | browser-tester |
| Monthly | Review deprecated tests for removal | Team consensus |

## Contact

Questions or issues with fixtures?

- **Fixture design**: `@browser-tester`
- **Frontend compatibility**: `@code-simplifier`
- **Backend completeness**: `@domain-expert`
- **Architecture consistency**: `@superpowers-peer`

---

**Last updated**: 2026-01-31
**Fixture version**: 1.0
**Maintained by**: browser-tester
