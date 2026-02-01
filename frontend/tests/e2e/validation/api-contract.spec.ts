/**
 * E2E Test: ValidationResult API Contract
 *
 * Phase 1A - Core API Validation
 * Author: browser-tester
 * Date: 2026-01-31
 *
 * Test Scope:
 * - ValidationResult interface contract verification
 * - Field presence and type validation
 * - Structure consistency across all error types
 * - SSOT principle verification (Fixture v1.0 alignment)
 *
 * This test ensures that the ValidationResult API is stable and consistent,
 * allowing frontend developers to use it with zero defensive checks.
 */

import { test, expect } from '@playwright/test';

test.describe('ValidationResult API Contract', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000/test-harness');
  });

  test('should always return ValidationResult with required fields', async ({ page }) => {
    // Test with multiple fixtures to ensure consistency
    const fixtures = ['circular_dependency', 'missing_field_reference', 'dangling_node'];

    for (const fixtureId of fixtures) {
      await page.selectOption('[data-testid="fixture-selector"]', fixtureId);
      await page.click('[data-testid="run-validation"]');
      await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

      // Force details open (avoid toggle on re-runs)
      await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
      await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

      const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
      const result = JSON.parse(resultText || '{}');

      // ⭐ API Contract: These fields must ALWAYS be present
      expect(result).toHaveProperty('valid');
      expect(result).toHaveProperty('errors');
      expect(result).toHaveProperty('warnings');

      // Type validation
      expect(typeof result.valid).toBe('boolean');
      expect(Array.isArray(result.errors)).toBe(true);
      expect(Array.isArray(result.warnings)).toBe(true);
    }
  });

  test('should return consistent error object structure', async ({ page }) => {
    // Test with an error scenario
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    expect(result.errors.length).toBeGreaterThan(0);
    const error = result.errors[0];

    // ⭐ Error Object Contract
    expect(error).toHaveProperty('code');
    expect(error).toHaveProperty('message');
    expect(error).toHaveProperty('severity');
    expect(error).toHaveProperty('node_ids');
    expect(error).toHaveProperty('context');

    // Type validation
    expect(typeof error.code).toBe('string');
    expect(typeof error.message).toBe('string');
    expect(typeof error.severity).toBe('string');
    expect(Array.isArray(error.node_ids)).toBe(true);
    expect(typeof error.context).toBe('object');
    expect(error.context).not.toBeNull();

    // Severity must be 'error' for errors
    expect(error.severity).toBe('error');

    // node_ids must always be plural (array), never singular
    expect(error.node_ids.length).toBeGreaterThan(0);
  });

  test('should return consistent warning object structure', async ({ page }) => {
    // Test with a warning scenario
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    // Force details open (avoid toggle on re-runs)
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    const result = JSON.parse(resultText || '{}');

    expect(result.warnings.length).toBeGreaterThan(0);
    const warning = result.warnings[0];

    // ⭐ Warning Object Contract (same structure as Error)
    expect(warning).toHaveProperty('code');
    expect(warning).toHaveProperty('message');
    expect(warning).toHaveProperty('severity');
    expect(warning).toHaveProperty('node_ids');
    expect(warning).toHaveProperty('context');

    // Severity must be 'warning' for warnings
    expect(warning.severity).toBe('warning');

    // node_ids must always be array
    expect(Array.isArray(warning.node_ids)).toBe(true);
  });

  test('should ensure valid field correctly reflects presence of errors', async ({ page }) => {
    // Test 1: Scenario with errors should be invalid
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    let resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    let result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);

    // Test 2: Scenario with only warnings should be valid
    await page.selectOption('[data-testid="fixture-selector"]', 'dangling_node');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    result = JSON.parse(resultText || '{}');

    expect(result.valid).toBe(true); // Valid despite warnings
    expect(result.errors).toHaveLength(0);
    expect(result.warnings.length).toBeGreaterThan(0);

    // ⭐ API Contract: valid = (errors.length === 0)
  });

  test('should provide error codes that match Fixture v1.0 specifications', async ({ page }) => {
    const expectedErrorCodes = {
      'circular_dependency': 'CIRCULAR_DEPENDENCY',
      'missing_field_reference': 'MISSING_FIELD_REFERENCE',
      // 'invalid_node_config': 'INVALID_NODE_CONFIG', // TODO: implement in Phase 2
    };

    for (const [fixtureId, expectedCode] of Object.entries(expectedErrorCodes)) {
      await page.selectOption('[data-testid="fixture-selector"]', fixtureId);
      await page.click('[data-testid="run-validation"]');
      await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

      const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
      const result = JSON.parse(resultText || '{}');

      expect(result.errors[0].code).toBe(expectedCode);
    }
  });

  test('should guarantee context field completeness per error type', async ({ page }) => {
    // ⭐ This test verifies the zero defensive checks principle

    // Test 1: CIRCULAR_DEPENDENCY context
    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    let resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    let result = JSON.parse(resultText || '{}');
    let error = result.errors[0];

    // cycle_path must be defined and complete
    expect(error.context.cycle_path).toBeDefined();
    expect(error.context.cycle_path.length).toBeGreaterThanOrEqual(3);

    // Test 2: MISSING_FIELD_REFERENCE context
    await page.selectOption('[data-testid="fixture-selector"]', 'missing_field_reference');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
    await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
    await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

    resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
    result = JSON.parse(resultText || '{}');
    error = result.errors[0];

    // available_fields must be defined and non-empty
    expect(error.context.available_fields).toBeDefined();
    expect(error.context.available_fields.length).toBeGreaterThan(0);

    // field and upstream_node_ids must be defined
    expect(error.context.field).toBeDefined();
    expect(error.context.upstream_node_ids).toBeDefined();
  });

  test('should maintain API stability across multiple validations', async ({ page }) => {
    // Run the same fixture multiple times to ensure consistency
    const fixtureId = 'circular_dependency';
    const iterations = 3;
    const results = [];

    for (let i = 0; i < iterations; i++) {
      await page.selectOption('[data-testid="fixture-selector"]', fixtureId);
      await page.click('[data-testid="run-validation"]');
      await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });
      await page.locator('details').first().evaluate((el) => (el as HTMLDetailsElement).open = true);
      await page.waitForSelector('[data-testid="validation-result-json"]', { state: 'visible' });

      const resultText = await page.locator('[data-testid="validation-result-json"]').textContent();
      const result = JSON.parse(resultText || '{}');
      results.push(result);
    }

    // All results should be identical
    for (let i = 1; i < iterations; i++) {
      expect(results[i].valid).toBe(results[0].valid);
      expect(results[i].errors.length).toBe(results[0].errors.length);
      expect(results[i].warnings.length).toBe(results[0].warnings.length);
      expect(results[i].errors[0].code).toBe(results[0].errors[0].code);
    }
  });

  test('should return validation results in acceptable time', async ({ page }) => {
    // API should be fast enough for real-time validation
    const startTime = Date.now();

    await page.selectOption('[data-testid="fixture-selector"]', 'circular_dependency');
    await page.click('[data-testid="run-validation"]');
    await page.waitForSelector('[data-testid="validation-result"]', { state: 'visible' });

    const endTime = Date.now();
    const duration = endTime - startTime;

    // Should complete quickly for good UX
    expect(duration).toBeLessThan(1000); // 1 second for API response
  });
});
