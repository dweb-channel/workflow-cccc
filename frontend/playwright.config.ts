import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright Configuration for E2E Validation Tests
 *
 * Phase 1 TDD Implementation
 * Author: browser-tester
 * Date: 2026-01-31
 *
 * Test Coverage:
 * - P0 validation scenarios (circular_dependency, missing_field_reference, invalid_node_config)
 * - P1 validation scenarios (dangling_node, jump_reference)
 * - ValidationResult API verification
 * - Context contract validation
 */
export default defineConfig({
  testDir: './tests/e2e',

  /**
   * P0 Performance Requirements (from Fixture v1.0):
   * - P0 tests must complete in < 5 seconds for CI gates
   * - Single test timeout: 30 seconds (conservative for dev)
   * - Assertion timeout: 5 seconds
   */
  timeout: 30000,
  expect: {
    timeout: 5000
  },

  /**
   * Parallel execution for faster CI
   */
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,

  /**
   * Reporters for CI integration
   */
  reporter: [
    ['html'],
    ['junit', { outputFile: 'test-results/junit.xml' }],
    ['list'],
  ],

  /**
   * Shared settings for all tests
   */
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  /**
   * Browser configurations
   *
   * Phase 1: Chromium only (cross-browser in Phase 2)
   * Phase 2: Firefox, Safari for full compatibility testing
   */
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        baseURL: 'http://localhost:3000',
      },
    },

    // Phase 2: Cross-browser testing
    // Uncomment when implementing Task #3
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },
  ],

  /**
   * Dev server configuration
   *
   * Automatically starts Next.js dev server before tests
   * Reuses existing server in dev, starts fresh in CI
   */
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
    timeout: 120000, // 2 minutes for dev server startup
  },
});
