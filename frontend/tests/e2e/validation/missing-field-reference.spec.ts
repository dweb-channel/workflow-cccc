/**
 * P0 E2E Test: Missing Field Reference Detection
 *
 * Phase 1A - API Contract Validation
 * Author: browser-tester
 * Date: 2026-01-31
 *
 * Test Scope:
 * - ValidationResult API contract verification
 * - MISSING_FIELD_REFERENCE error code validation
 * - Context field contract validation (available_fields, field, upstream_node_ids)
 * - Zero defensive checks principle verification
 *
 * Not in Scope (Phase 1B - awaiting design):
 * - Field picker UI interaction
 * - Field selection and application
 * - User repair workflows
 */

import { test, expect } from '@playwright/test';

test.describe('P0 - Missing Field Reference Detection', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000/test-harness');
  });

  test('should detect missing field reference and return valid ValidationResult', async ({ page }) => {
    // 1. Select missing_field_reference fixture
    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');

    // 2. Run validation
    await page.click('[data-testid="run-validation"]');

    // 3. Wait for results (P0: < 5 seconds)
    await page.waitForSelector('[data-testid="validation-result"]', {
      state: 'visible',
      timeout: 5000
    });

    // 4. Verify validation status shows invalid
    const validText = await page.locator('[data-testid="validation-valid"]').textContent();
    expect(validText).toContain('无效');

    // 5. Verify error count
    const errorCount = await page.locator('[data-testid="validation-error-count"]').textContent();
    expect(errorCount).toBe('1');

    // 6. Verify missing_field_reference error actionable element exists
    await expect(page.locator('[data-testid="error-actionable-missing-field-reference"]')).toBeVisible();
  });

  test('should provide complete ValidationResult structure', async ({ page }) => {
    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');
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

    expect(result.valid).toBe(false);
    expect(result.errors).toHaveLength(1);

    // Verify error structure
    const error = result.errors[0];
    expect(error.code).toBe('MISSING_FIELD_REFERENCE');
    expect(error.severity).toBe('error');
    expect(error).toHaveProperty('message');
    expect(error).toHaveProperty('node_ids');
    expect(error).toHaveProperty('context');
  });

  test('should satisfy Context field contract for available_fields (zero defensive checks principle)', async ({ page }) => {
    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    // Get context from the full validation result JSON
    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');
    const context = result.errors[0].context;

    // ⭐ Critical: Context Contract Validation
    // Frontend can directly use these fields without defensive checks

    // Contract 1: field must be defined (the missing field)
    expect(context.field).toBeDefined();
    expect(typeof context.field).toBe('string');
    expect(context.field.length).toBeGreaterThan(0);

    // Contract 2: available_fields must be defined and non-empty
    // This is THE KEY contract - frontend never needs to check if empty!
    expect(context.available_fields).toBeDefined();
    expect(Array.isArray(context.available_fields)).toBe(true);
    expect(context.available_fields.length).toBeGreaterThan(0); // GUARANTEED NON-EMPTY

    // Contract 3: available_fields should be array of strings
    context.available_fields.forEach((field: any) => {
      expect(typeof field).toBe('string');
    });

    // Contract 4: upstream_node_ids must be defined
    expect(context.upstream_node_ids).toBeDefined();
    expect(Array.isArray(context.upstream_node_ids)).toBe(true);
  });

  test('should match expected_validation_result from Fixture v1.0', async ({ page }) => {
    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(false);
    expect(result.errors).toHaveLength(1);

    // Validator also produces NO_OUTGOING_EDGE warning for node-2 (no outgoing edges)
    expect(result.warnings.length).toBeGreaterThanOrEqual(1);

    const error = result.errors[0];
    expect(error.code).toBe('MISSING_FIELD_REFERENCE');
    expect(error.severity).toBe('error');
    expect(error.node_ids).toContain('node-2');

    // Verify context: field is the missing reference
    expect(error.context.field).toBe('node-1.user_email');

    // available_fields comes from INITIAL_FIELDS (run_id, request) since
    // data_source node uses output_schema not output_field
    expect(error.context.available_fields).toBeDefined();
    expect(error.context.available_fields.length).toBeGreaterThan(0);
    expect(error.context.available_fields).toEqual(
      expect.arrayContaining(['request', 'run_id'])
    );

    expect(error.context.upstream_node_ids).toContain('node-1');
  });

  test('should demonstrate zero defensive checks can be used in frontend', async ({ page }) => {
    // This test explicitly verifies that frontend code can use context fields
    // WITHOUT any null checks or empty array checks
    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');
    const error = result.errors[0];

    // ✅ CORRECT: Direct usage without defensive checks
    // This is GUARANTEED to work because of the context contract
    const field = error.context.field; // No "?" operator needed
    const availableFields = error.context.available_fields; // No "|| []" needed
    const firstField = availableFields[0]; // No ".length > 0" check needed

    expect(field).toBeDefined();
    expect(availableFields.length).toBeGreaterThan(0);
    expect(firstField).toBeDefined();
  });

  test('should complete validation within P0 performance requirements', async ({ page }) => {
    const startTime = Date.now();

    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    const endTime = Date.now();
    const duration = endTime - startTime;

    expect(duration).toBeLessThan(5000); // P0: < 5 seconds
  });
});
