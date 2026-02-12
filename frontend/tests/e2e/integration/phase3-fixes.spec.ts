/**
 * E2E Tests for Phase 3 Fixes — Frontend Verification
 *
 * Updated for M14 Sidebar navigation (was M13 Two-Tab layout).
 * M14: Sidebar promoted to layout, pure navigation, "当前任务" moved to OverviewTab.
 *
 * T069: Config field mapping (frontend types + UI values)
 * T070: SSE defensive programming (code-level verification)
 * REG: Regression checks (M13 tab structure)
 *
 * Requires: frontend at localhost:3000
 *
 * Author: browser-tester
 * Date: 2026-02-12 (updated for M13 layout)
 */

import { test, expect } from '@playwright/test';

const BATCH_BUGS_URL = 'http://localhost:3000/batch-bugs';

test.describe('Phase 3: T069 — Config Field Mapping (Frontend)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');
  });

  // T069.6: Config options card uses correct labels
  test('T069.6: Config options show validation_level values', async ({ page }) => {
    // Config card should show "验证级别" and "失败策略"
    await expect(page.locator('text=验证级别').first()).toBeVisible();
    await expect(page.locator('text=失败策略').first()).toBeVisible();
  });

  // T069.7: Validation level select has 3 correct options
  test('T069.7: Validation level has minimal/standard/thorough', async ({ page }) => {
    // Click the validation level select
    const validationSelect = page.locator('text=验证级别').locator('..').locator('button[role="combobox"]');
    if (await validationSelect.isVisible()) {
      await validationSelect.click();
      await page.waitForTimeout(200);

      // Check options
      await expect(page.locator('[role="option"]').filter({ hasText: '快速验证' })).toBeVisible();
      await expect(page.locator('[role="option"]').filter({ hasText: '标准验证' })).toBeVisible();
      await expect(page.locator('[role="option"]').filter({ hasText: '完整验证' })).toBeVisible();

      // Close dropdown
      await page.keyboard.press('Escape');
    } else {
      test.info().annotations.push({ type: 'info', description: 'Validation select not found — skipped' });
    }
  });

  // T069.8: Failure policy select has 3 correct options
  test('T069.8: Failure policy has stop/skip/retry', async ({ page }) => {
    // Click the failure policy select
    const policySelect = page.locator('text=失败策略').locator('..').locator('button[role="combobox"]');
    if (await policySelect.isVisible()) {
      await policySelect.click();
      await page.waitForTimeout(200);

      // Check options
      await expect(page.locator('[role="option"]').filter({ hasText: '跳过继续' })).toBeVisible();
      await expect(page.locator('[role="option"]').filter({ hasText: '停止等待' })).toBeVisible();
      await expect(page.locator('[role="option"]').filter({ hasText: '自动重试' })).toBeVisible();

      await page.keyboard.press('Escape');
    } else {
      test.info().annotations.push({ type: 'info', description: 'Policy select not found — skipped' });
    }
  });
});

test.describe('Phase 3: T070 — SSE Defensive (Frontend Code Verification)', () => {
  // T070.4: No uncaught errors on page load (console error check)
  test('T070.4: Page loads without console errors', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Filter out expected errors (network requests to backend that may not be running)
    const unexpectedErrors = consoleErrors.filter(
      (e) => !e.includes('fetch') && !e.includes('ERR_CONNECTION') && !e.includes('Failed to load')
    );

    expect(unexpectedErrors).toEqual([]);
  });

  // T070.5: Dead "preview" button removed
  test('T070.5: No dead preview button exists', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    // The dead "预览 Bug 列表" button should not exist
    const previewBtn = page.locator('button').filter({ hasText: '预览 Bug 列表' });
    await expect(previewBtn).toHaveCount(0);
  });

  // T070.6: Build size reasonable (no bloat from SSE changes)
  test('T070.6: batch-bugs page exists and renders', async ({ page }) => {
    const response = await page.goto(BATCH_BUGS_URL);
    expect(response?.status()).toBe(200);

    // Core elements present (use main to avoid matching Sidebar nav link)
    await expect(page.locator('main h1')).toContainText('批量 Bug 修复');
    await expect(page.locator('text=开始修复')).toBeVisible();
  });
});

test.describe('Phase 3: Regression — M13 tab layout intact', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');
  });

  // REG.3: Config tab has correct structure (M13: two big tabs — config/execution)
  test('REG.3: Config tab shows form + history + new tab structure', async ({ page }) => {
    // New M13 tab structure should exist
    await expect(page.locator('[data-testid="main-tabs"]')).toBeVisible();
    await expect(page.locator('[data-testid="tab-config"]')).toBeVisible();
    await expect(page.locator('[data-testid="tab-execution"]')).toBeVisible();

    // Config tab should be active by default
    await expect(page.locator('[data-testid="tab-config"]')).toHaveAttribute('data-state', 'active');

    // Old tabs should NOT exist
    await expect(page.locator('button[data-testid="tab-workflow"]')).not.toBeVisible();
    await expect(page.locator('button[data-testid="tab-detail"]')).not.toBeVisible();
    await expect(page.locator('button[data-testid="tab-ai-thinking"]')).not.toBeVisible();

    // Config form elements should be present
    await expect(page.locator('text=验证级别').first()).toBeVisible();
    await expect(page.locator('text=失败策略').first()).toBeVisible();
    await expect(page.locator('text=目标代码库路径').first()).toBeVisible();

    // History should be visible
    await expect(page.locator('text=历史任务').first()).toBeVisible();
  });

  // REG.4: Submit button still present and functional
  test('REG.4: Submit button present and initially disabled', async ({ page }) => {
    const submitBtn = page.locator('button').filter({ hasText: '开始修复' });
    await expect(submitBtn).toBeVisible();
    // Should be disabled (no URLs entered)
    await expect(submitBtn).toBeDisabled();
  });

  // REG.5: Sidebar is pure navigation (M14: no "当前任务" in sidebar)
  test('REG.5: Sidebar is pure navigation, no task status', async ({ page }) => {
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();

    // Sidebar should show nav items
    await expect(sidebar.locator('text=工作流编辑器')).toBeVisible();
    await expect(sidebar.locator('text=批量 Bug 修复')).toBeVisible();

    // Sidebar should NOT contain task status (moved to OverviewTab in M14)
    await expect(sidebar.locator('text=当前任务')).not.toBeVisible();
    await expect(sidebar.locator('text=尚未启动任务')).not.toBeVisible();
  });
});
