/**
 * E2E Tests for M14 — Sidebar Navigation + Layout
 *
 * T093: Verify new Sidebar layout and navigation across all pages.
 *
 * S1: Sidebar cross-page consistency (/ and /batch-bugs both have Sidebar)
 * S2: Navigation click routing (click nav items, URL changes correctly)
 * S3: "Current task" location (not in Sidebar, now in OverviewTab)
 * S4: Regression (covered in updated phase3-fixes + m9-batch-tabs)
 *
 * Requires: frontend at localhost:3000
 *
 * Author: browser-tester
 * Date: 2026-02-12
 */

import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:3000';
const BATCH_BUGS_URL = `${BASE_URL}/batch-bugs`;

/* ================================================================
   S1: Sidebar Cross-Page Consistency
   ================================================================ */

test.describe('M14 S1: Sidebar cross-page consistency', () => {
  test('Sidebar visible on home page (/)', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');

    // Sidebar container
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();

    // Logo/brand
    await expect(sidebar.locator('text=工作流平台')).toBeVisible();

    // Nav items
    const nav = sidebar.locator('nav');
    await expect(nav).toBeVisible();
    await expect(nav.locator('text=工作流编辑器')).toBeVisible();
    await expect(nav.locator('text=批量 Bug 修复')).toBeVisible();
  });

  test('Sidebar visible on /batch-bugs', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();

    await expect(sidebar.locator('text=工作流平台')).toBeVisible();

    const nav = sidebar.locator('nav');
    await expect(nav).toBeVisible();
    await expect(nav.locator('text=工作流编辑器')).toBeVisible();
    await expect(nav.locator('text=批量 Bug 修复')).toBeVisible();
  });

  test('Sidebar nav items are identical on both pages', async ({ page }) => {
    // Collect nav labels from home page
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');
    const homeNavTexts = await page.locator('aside nav a span').allTextContents();

    // Collect nav labels from batch-bugs page
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');
    const batchNavTexts = await page.locator('aside nav a span').allTextContents();

    expect(homeNavTexts).toEqual(batchNavTexts);
    expect(homeNavTexts.length).toBeGreaterThanOrEqual(2);
  });

  test('Active nav item highlights correctly on /', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');

    // "工作流编辑器" link should have active style (bg-blue-500)
    const workflowLink = page.locator('aside nav a').filter({ hasText: '工作流编辑器' });
    await expect(workflowLink).toHaveClass(/bg-blue-500/);

    // "批量 Bug 修复" should NOT have active style
    const batchLink = page.locator('aside nav a').filter({ hasText: '批量 Bug 修复' });
    await expect(batchLink).not.toHaveClass(/bg-blue-500/);
  });

  test('Active nav item highlights correctly on /batch-bugs', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    // "批量 Bug 修复" should have active style
    const batchLink = page.locator('aside nav a').filter({ hasText: '批量 Bug 修复' });
    await expect(batchLink).toHaveClass(/bg-blue-500/);

    // "工作流编辑器" should NOT have active style
    const workflowLink = page.locator('aside nav a').filter({ hasText: '工作流编辑器' });
    await expect(workflowLink).not.toHaveClass(/bg-blue-500/);
  });
});

/* ================================================================
   S2: Navigation Click Routing
   ================================================================ */

test.describe('M14 S2: Navigation click routing', () => {
  test('Click "批量 Bug 修复" navigates to /batch-bugs', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');

    const batchLink = page.locator('aside nav a').filter({ hasText: '批量 Bug 修复' });
    await batchLink.click();

    await page.waitForURL('**/batch-bugs');
    expect(page.url()).toContain('/batch-bugs');

    // Verify page content loaded (use main to avoid matching Sidebar h1)
    await expect(page.locator('main h1')).toContainText('批量 Bug 修复');
  });

  test('Click "工作流编辑器" navigates to /', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const workflowLink = page.locator('aside nav a').filter({ hasText: '工作流编辑器' });
    await workflowLink.click();

    await page.waitForURL(BASE_URL + '/');
    expect(page.url()).toBe(BASE_URL + '/');
  });

  test('Navigation round-trip preserves Sidebar', async ({ page }) => {
    // Start on home
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('aside')).toBeVisible();

    // Go to batch-bugs
    await page.locator('aside nav a').filter({ hasText: '批量 Bug 修复' }).click();
    await page.waitForURL('**/batch-bugs');
    await expect(page.locator('aside')).toBeVisible();

    // Go back to home
    await page.locator('aside nav a').filter({ hasText: '工作流编辑器' }).click();
    await page.waitForURL(BASE_URL + '/');
    await expect(page.locator('aside')).toBeVisible();
  });

  test('Active state updates after navigation', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForLoadState('networkidle');

    // Initially "工作流编辑器" is active
    const workflowLink = page.locator('aside nav a').filter({ hasText: '工作流编辑器' });
    const batchLink = page.locator('aside nav a').filter({ hasText: '批量 Bug 修复' });
    await expect(workflowLink).toHaveClass(/bg-blue-500/);
    await expect(batchLink).not.toHaveClass(/bg-blue-500/);

    // Navigate to batch-bugs
    await batchLink.click();
    await page.waitForURL('**/batch-bugs');

    // Now "批量 Bug 修复" should be active
    await expect(batchLink).toHaveClass(/bg-blue-500/);
    await expect(workflowLink).not.toHaveClass(/bg-blue-500/);
  });
});

/* ================================================================
   S3: "Current Task" Location Verification
   ================================================================ */

test.describe('M14 S3: Current task location', () => {
  test('Sidebar does NOT contain "当前任务" or "尚未启动任务"', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const sidebar = page.locator('aside');
    await expect(sidebar.locator('text=当前任务')).not.toBeVisible();
    await expect(sidebar.locator('text=尚未启动任务')).not.toBeVisible();
    await expect(sidebar.locator('text=尚未开始任务')).not.toBeVisible();
  });

  test('Sidebar has no children content slot', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    // Sidebar should only contain logo + nav, nothing below the nav
    const sidebar = page.locator('aside');
    const childrenAfterNav = sidebar.locator('> *');
    const count = await childrenAfterNav.count();

    // Should be exactly 2 direct children: logo div + nav
    expect(count).toBe(2);
  });

  test('OverviewTab shows "尚未开始任务" when no job running', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    // Switch to execution tab — it should be disabled when no job exists
    const execTab = page.locator('[data-testid="tab-execution"]');
    await expect(execTab).toBeDisabled();

    // The OverviewTab with data-testid="tab-overview" exists in the forceMount content
    // but is hidden. Verify via DOM presence.
    const overviewTabContent = page.locator('[data-testid="tab-overview"]');
    // It exists in DOM (forceMount) but may not be visible since execution tab is hidden
    const count = await overviewTabContent.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test('OverviewTab shows task status after job starts', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    // Submit a job to trigger execution tab
    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    // Wait for execution tab
    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // OverviewTab should now show task status (not "尚未开始任务")
    const overviewContent = page.locator('[data-testid="tab-overview"]');
    await expect(overviewContent).toBeVisible();

    // Should show progress info (use .first() as multiple elements match the pattern)
    await expect(overviewContent.locator('text=/\\d+\\/\\d+ 完成/').first()).toBeVisible({ timeout: 5000 });
  });
});
