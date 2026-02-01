/**
 * P1 E2E Test: Dangling Node Detection
 *
 * Phase 1A - API Contract Validation
 * Author: browser-tester
 * Date: 2026-01-31
 *
 * Test Scope:
 * - ValidationResult API contract verification
 * - NO_INCOMING_EDGE / NO_OUTGOING_EDGE warning code validation
 * - Context field contract validation (connection_suggestions - optional)
 * - Warning vs Error distinction
 *
 * Not in Scope (Phase 1B - awaiting design):
 * - Connection suggestion UI interactions
 * - Edge creation workflows
 */

import { test, expect } from '@playwright/test';

test.describe('P1 - Dangling Node Detection', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000/test-harness');
  });

  test('should detect dangling node and return warning (not error)', async ({ page }) => {
    // 1. Select dangling_node fixture
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');

    // 2. Run validation
    await page.click('[data-testid="run-validation"]');

    // 3. Wait for results
    await page.waitForSelector('[data-testid="validation-result"]', {
      state: 'visible',
      timeout: 5000
    });

    // 4. Verify validation status shows VALID (warnings don't block validity)
    const validText = await page.locator('[data-testid="validation-valid"]').textContent();
    expect(validText).toContain('有效'); // Should be VALID despite warnings

    // 5. Verify error count is 0
    const errorCount = await page.locator('[data-testid="validation-error-count"]').textContent();
    expect(errorCount).toBe('0');

    // 6. Verify warning count > 0
    const warningCount = await page.locator('[data-testid="validation-warning-count"]').textContent();
    expect(parseInt(warningCount || '0')).toBeGreaterThan(0);
  });

  test('should provide complete ValidationResult with warnings', async ({ page }) => {
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    // Verify ValidationResult structure
    expect(result).toHaveProperty('valid');
    expect(result).toHaveProperty('errors');
    expect(result).toHaveProperty('warnings');

    // Critical: valid should be TRUE (warnings don't block validity)
    expect(result.valid).toBe(true);

    // Should have no errors
    expect(result.errors).toHaveLength(0);

    // Should have warnings
    expect(Array.isArray(result.warnings)).toBe(true);
    expect(result.warnings.length).toBeGreaterThan(0);

    // Verify warning structure
    const warning = result.warnings.find((w: any) =>
      w.code === 'NO_INCOMING_EDGE' || w.code === 'NO_OUTGOING_EDGE'
    );
    expect(warning).toBeDefined();
    expect(warning).toHaveProperty('code');
    expect(warning).toHaveProperty('message');
    expect(warning).toHaveProperty('severity');
    expect(warning.severity).toBe('warning'); // Not 'error'
    expect(warning).toHaveProperty('node_ids');
  });

  test('should satisfy Context field contract for dangling nodes', async ({ page }) => {
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    const warning = result.warnings.find((w: any) =>
      w.code === 'NO_INCOMING_EDGE' || w.code === 'NO_OUTGOING_EDGE'
    );

    // ⭐ Context Contract Validation for Dangling Nodes

    // Contract 1: node_ids should be defined and contain single node
    expect(warning.node_ids).toBeDefined();
    expect(Array.isArray(warning.node_ids)).toBe(true);
    expect(warning.node_ids.length).toBeGreaterThan(0);

    // Contract 2: connection_suggestions is OPTIONAL
    // If present, it should be an array
    if (warning.context?.connection_suggestions) {
      expect(Array.isArray(warning.context.connection_suggestions)).toBe(true);
    }
  });

  test('should match expected_validation_result from Fixture v1.0', async ({ page }) => {
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
    // Validator produces 3 warnings: NO_OUTGOING_EDGE(node-2), NO_INCOMING_EDGE(node-3), NO_OUTGOING_EDGE(node-3)
    expect(result.warnings).toHaveLength(3);

    // Verify node-3 has warnings (both NO_INCOMING_EDGE and NO_OUTGOING_EDGE)
    const node3Warnings = result.warnings.filter((w: any) =>
      w.node_ids.includes('node-3')
    );
    expect(node3Warnings.length).toBe(2);

    // Verify node-2 has NO_OUTGOING_EDGE warning
    const node2Warning = result.warnings.find((w: any) =>
      w.node_ids.includes('node-2') && w.code === 'NO_OUTGOING_EDGE'
    );
    expect(node2Warning).toBeDefined();
    expect(node2Warning.severity).toBe('warning');
  });

  test('should demonstrate warning vs error distinction', async ({ page }) => {
    // 1. Test dangling_node (warning) - should be VALID
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    let resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    let result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(true); // Valid despite warnings
    expect(result.errors).toHaveLength(0);
    expect(result.warnings.length).toBeGreaterThan(0);

    // 2. Test circular_dependency (error) - should be INVALID
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(false); // Invalid due to errors
    expect(result.errors.length).toBeGreaterThan(0);
  });

  test('should complete validation within acceptable time', async ({ page }) => {
    const startTime = Date.now();

    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    const endTime = Date.now();
    const duration = endTime - startTime;

    expect(duration).toBeLessThan(10000); // 10 seconds for P1
  });
});
