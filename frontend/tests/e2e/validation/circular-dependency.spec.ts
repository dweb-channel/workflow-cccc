/**
 * P0 E2E Test: Circular Dependency Detection
 *
 * Phase 1A - API Contract Validation
 * Author: browser-tester
 * Date: 2026-01-31
 *
 * Test Scope:
 * - ValidationResult API contract verification
 * - CIRCULAR_DEPENDENCY error code validation
 * - Context field contract validation (cycle_path)
 * - Zero defensive checks principle verification
 *
 * Not in Scope (Phase 1B - awaiting design):
 * - ErrorActionable component interactions
 * - UI fix suggestions
 * - User repair workflows
 */

import { test, expect } from '@playwright/test';

test.describe('P0 - Circular Dependency Detection', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to test harness page
    await page.goto('http://localhost:3000/test-harness');
  });

  test('should detect circular dependency and return valid ValidationResult', async ({ page }) => {
    // 1. Select circular_dependency fixture
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');

    // 2. Run validation
    await page.click('[data-testid="run-validation"]');

    // 3. Wait for results to appear
    await page.waitForSelector('[data-testid="validation-result"]', {
      state: 'visible',
      timeout: 5000 // P0 requirement: < 5 seconds
    });

    // 4. Verify validation status shows invalid
    const validText = await page.locator('[data-testid="validation-valid"]').textContent();
    expect(validText).toContain('无效'); // Chinese UI

    // 5. Verify error count
    const errorCount = await page.locator('[data-testid="validation-error-count"]').textContent();
    expect(errorCount).toBe('1');

    // 6. Verify warning count
    const warningCount = await page.locator('[data-testid="validation-warning-count"]').textContent();
    expect(warningCount).toBe('0');

    // 7. Verify circular_dependency error actionable element exists
    await expect(page.locator('[data-testid="error-actionable-circular-dependency"]')).toBeVisible();
  });

  test('should provide complete ValidationResult matching Fixture v1.0 expectations', async ({ page }) => {
    // Select and run validation
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    // Get the full JSON result
    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    // Verify ValidationResult structure
    expect(result).toHaveProperty('valid');
    expect(result).toHaveProperty('errors');
    expect(result).toHaveProperty('warnings');

    // Verify validation failed
    expect(result.valid).toBe(false);

    // Verify errors array
    expect(Array.isArray(result.errors)).toBe(true);
    expect(result.errors).toHaveLength(1);

    // Verify error object structure
    const error = result.errors[0];
    expect(error).toHaveProperty('code');
    expect(error).toHaveProperty('message');
    expect(error).toHaveProperty('severity');
    expect(error).toHaveProperty('node_ids');
    expect(error).toHaveProperty('context');

    // Verify error values
    expect(error.code).toBe('CIRCULAR_DEPENDENCY');
    expect(error.severity).toBe('error');
    expect(Array.isArray(error.node_ids)).toBe(true);
    expect(error.node_ids.length).toBeGreaterThan(0);
  });

  test('should satisfy Context field contract for cycle_path (zero defensive checks principle)', async ({ page }) => {
    // Select and run validation
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    // Get full result and extract context from it
    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');
    const context = result.errors[0].context;

    // ⭐ Critical: Context Contract Validation
    // Frontend can directly use these fields without defensive checks

    // Contract 1: cycle_path must be defined
    expect(context.cycle_path).toBeDefined();
    expect(context.cycle_path).not.toBeNull();

    // Contract 2: cycle_path must have at least 3 nodes (start + middle + start)
    expect(context.cycle_path.length).toBeGreaterThanOrEqual(3);

    // Contract 3: cycle_path first and last elements must be the same (cycle property)
    const firstNode = context.cycle_path[0];
    const lastNode = context.cycle_path[context.cycle_path.length - 1];
    expect(firstNode).toBe(lastNode);

    // Contract 4: cycle_path should be an array of strings (node IDs)
    expect(Array.isArray(context.cycle_path)).toBe(true);
    context.cycle_path.forEach((nodeId: any) => {
      expect(typeof nodeId).toBe('string');
    });
  });

  test('should match expected_validation_result from Fixture v1.0', async ({ page }) => {
    // This test verifies complete alignment with the fixture's expected result
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(false);
    expect(result.errors).toHaveLength(1);
    expect(result.warnings).toHaveLength(0);

    const error = result.errors[0];
    expect(error.code).toBe('CIRCULAR_DEPENDENCY');
    expect(error.severity).toBe('error');

    // node_ids should contain all nodes in the cycle
    expect(error.node_ids).toEqual(expect.arrayContaining(['node-1', 'node-2', 'node-3']));

    // context.cycle_path should show the complete cycle
    expect(error.context.cycle_path).toEqual(['node-1', 'node-2', 'node-3', 'node-1']);
  });

  test('should complete validation within P0 performance requirements', async ({ page }) => {
    // P0 requirement from Fixture v1.0: tests must complete in < 5 seconds

    const startTime = Date.now();

    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    const endTime = Date.now();
    const duration = endTime - startTime;

    // Verify execution time is under 5 seconds (P0 CI gate requirement)
    expect(duration).toBeLessThan(5000);
  });
});
