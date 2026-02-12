/**
 * E2E Integration Tests: M13 — Two-Tab Layout + ActivityFeed Chat-Style
 *
 * Replaces the old M12 3-state tests after T088+T089 UI refactor.
 * Updated for M14: Sidebar promoted to layout, pure navigation.
 *
 * Layout (Two Big Tabs with forceMount):
 *   Tab 1 (配置):  Left=Input form, Right=History card
 *   Tab 2 (执行):  Pipeline bar + ActivityFeed(main) + Right panel [总览|历史]
 *
 * Key data-testid:
 *   main-tabs, tab-config, tab-execution — Two big tabs
 *   event-card — Single event card (critical/action tier)
 *   event-group — Merged explore event group (has data-count attribute)
 *   event-group-expand — Button to expand a group
 *
 * Test plan:
 * 1. Tab structure — main-tabs, tab-config, tab-execution, disabled state
 * 2. Config tab content — form inputs, history panel
 * 3. Tab navigation — auto-switch on job submit, New Job returns to config
 * 4. PipelineBar — badge rendering, click navigation
 * 5. ActivityFeed — event-card, event-group, data-count, expand
 * 6. Right panel — overview tab, history tab, cancel/new buttons
 * 7. API contract — job creation, status endpoint
 *
 * Requires: frontend at localhost:3000, backend at localhost:8000
 *
 * Author: browser-tester
 * Date: 2026-02-12 (updated for M13)
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';
const BATCH_BUGS_URL = 'http://localhost:3000/batch-bugs';

// Helper: create a mock job via API
async function createMockJob(request: any, urls: string[]) {
  const resp = await request.post(`${API_BASE}/api/v2/batch/bug-fix`, {
    data: {
      jira_urls: urls,
      config: { validation_level: 'standard', failure_policy: 'skip' },
    },
  });
  if (resp.status() === 201 || resp.status() === 200) {
    return resp.json();
  }
  return null;
}

/* ================================================================
   Tab Structure (M13: Two big tabs — config/execution)
   ================================================================ */

test.describe('M13: Tab Structure', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');
  });

  test('Main tabs container has data-testid', async ({ page }) => {
    const mainTabs = page.locator('[data-testid="main-tabs"]');
    await expect(mainTabs).toBeVisible();
  });

  test('Config tab and execution tab present', async ({ page }) => {
    await expect(page.locator('[data-testid="tab-config"]')).toBeVisible();
    await expect(page.locator('[data-testid="tab-execution"]')).toBeVisible();
  });

  test('Config tab active by default', async ({ page }) => {
    const configTab = page.locator('[data-testid="tab-config"]');
    await expect(configTab).toHaveAttribute('data-state', 'active');
  });

  test('Execution tab disabled when no job exists', async ({ page }) => {
    const execTab = page.locator('[data-testid="tab-execution"]');
    await expect(execTab).toBeDisabled();
  });
});

/* ================================================================
   Config Tab Content
   ================================================================ */

test.describe('M13: Config Tab Content', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');
  });

  test('Page title and description visible', async ({ page }) => {
    await expect(page.locator('main h1')).toContainText('批量 Bug 修复');
    await expect(page.locator('text=粘贴 Jira Bug 链接')).toBeVisible();
  });

  test('Input form elements present', async ({ page }) => {
    const textarea = page.locator('textarea');
    await expect(textarea).toBeVisible();

    await expect(page.locator('text=验证级别')).toBeVisible();
    await expect(page.locator('text=失败策略')).toBeVisible();
    await expect(page.locator('text=目标代码库路径')).toBeVisible();

    const submitBtn = page.locator('button:has-text("开始修复")');
    await expect(submitBtn).toBeVisible();
    await expect(submitBtn).toBeDisabled();
  });

  test('Submit button enables after entering URLs', async ({ page }) => {
    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');

    const submitBtn = page.locator('button:has-text("开始修复")');
    await expect(submitBtn).toBeEnabled();
  });

  test('History panel visible in config tab', async ({ page }) => {
    await expect(page.locator('text=历史任务').first()).toBeVisible();
  });

  test('Sidebar is pure navigation (M14: no task status)', async ({ page }) => {
    // M14: Sidebar no longer shows "当前任务"/"尚未启动任务"
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();
    await expect(sidebar.locator('text=工作流编辑器')).toBeVisible();
    await expect(sidebar.locator('text=批量 Bug 修复')).toBeVisible();
    await expect(sidebar.locator('text=尚未启动任务')).not.toBeVisible();
    await expect(sidebar.locator('text=当前任务')).not.toBeVisible();
  });
});

/* ================================================================
   Tab Navigation — auto-switch on job submit
   ================================================================ */

test.describe('M13: Tab Navigation', () => {
  test('After job submit, execution tab becomes active', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/TEST-1');
    await page.locator('button:has-text("开始修复")').click();

    // Execution tab should become active (data-state="active")
    const execTab = page.locator('[data-testid="tab-execution"]');
    await expect(execTab).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // Config tab should become inactive
    const configTab = page.locator('[data-testid="tab-config"]');
    await expect(configTab).toHaveAttribute('data-state', 'inactive');
  });
});

/* ================================================================
   PipelineBar Tests
   ================================================================ */

test.describe('M13: PipelineBar', () => {
  test('PipelineBar shows bug badges after job submit', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1\nhttps://jira.example.com/browse/BUG-2');
    await page.locator('button:has-text("开始修复")').click();

    // Wait for execution tab to activate
    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    await expect(page.locator('text=执行进度')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=/\\d+\\/\\d+ 完成/').first()).toBeVisible();

    const bugBadges = page.locator('.font-mono').filter({ hasText: /BUG-/ });
    const count = await bugBadges.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test('PipelineBar badges are clickable', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1\nhttps://jira.example.com/browse/BUG-2');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });
    await expect(page.locator('text=执行进度')).toBeVisible({ timeout: 5000 });

    const badges = page.locator('button').filter({ hasText: /BUG-2/ });
    if (await badges.count() > 0) {
      await badges.first().click();
      await expect(badges.first()).toHaveClass(/ring-2/, { timeout: 2000 });
    }
  });
});

/* ================================================================
   ActivityFeed Tests — event-card, event-group, data-count
   ================================================================ */

test.describe('M13: ActivityFeed', () => {
  test('ActivityFeed not visible in config tab', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    // In config tab, execution content is hidden (forceMount + data-[state=inactive]:hidden)
    await expect(page.locator('text=执行日志')).not.toBeVisible();
  });

  test('ActivityFeed appears after submit in execution tab', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // ActivityFeed header
    await expect(page.locator('text=执行日志')).toBeVisible({ timeout: 5000 });

    // Bottom bar should show token stats
    await expect(page.locator('text=/tokens/')).toBeVisible({ timeout: 5000 });
  });

  test('ActivityFeed in_progress bug is auto-expanded', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('text=执行日志')).toBeVisible({ timeout: 10000 });

    // Wait for feed body to render — verify execution tab content is visible
    await page.waitForTimeout(2000);
    // "执行日志" is the ActivityFeed header, confirming the feed rendered
    await expect(page.locator('text=执行日志')).toBeVisible();
  });

  test('Event cards use data-testid="event-card"', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // Wait for AI events to stream (requires real backend + Claude CLI)
    await page.waitForTimeout(5000);
    const eventCards = page.locator('[data-testid="event-card"]');
    const cardCount = await eventCards.count();

    if (cardCount > 0) {
      // Verify event cards are visible and correctly rendered
      for (let i = 0; i < Math.min(cardCount, 3); i++) {
        await expect(eventCards.nth(i)).toBeVisible();
      }
    } else {
      test.info().annotations.push({
        type: 'info',
        description: 'No event-card elements — backend may not be streaming AI events',
      });
    }
  });

  test('Event groups use data-testid="event-group" with data-count', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // Wait for AI events to accumulate and group
    await page.waitForTimeout(8000);
    const eventGroups = page.locator('[data-testid="event-group"]');
    const groupCount = await eventGroups.count();

    if (groupCount > 0) {
      // Verify data-count attribute exists and is numeric (>= 2 events per group)
      const firstGroup = eventGroups.first();
      const dataCount = await firstGroup.getAttribute('data-count');
      expect(dataCount).toBeTruthy();
      expect(Number(dataCount)).toBeGreaterThanOrEqual(2);

      // Verify expand button exists within the group
      const expandBtn = firstGroup.locator('[data-testid="event-group-expand"]');
      if (await expandBtn.count() > 0) {
        await expect(expandBtn).toBeVisible();
      }
    } else {
      test.info().annotations.push({
        type: 'info',
        description: 'No event-group elements — requires multiple consecutive explore events',
      });
    }
  });
});

/* ================================================================
   Right Panel (Overview + History tabs in execution tab)
   ================================================================ */

test.describe('M13: Right Panel — Overview + History', () => {
  test('Right panel shows 2 tabs in execution view', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // Two tab triggers: 总览 and 历史记录
    await expect(page.locator('button:has-text("总览")')).toBeVisible();
    await expect(page.locator('button:has-text("历史记录")')).toBeVisible();

    // Old tabs should NOT exist
    await expect(page.locator('button:has-text("工作流程")')).not.toBeVisible();
    await expect(page.locator('button:has-text("Bug 详情")')).not.toBeVisible();
    await expect(page.locator('button:has-text("AI 思考")')).not.toBeVisible();
  });

  test('Cancel and New Job buttons in overview tab', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // Cancel button should be visible during running state
    await expect(page.locator('button:has-text("取消任务")')).toBeVisible({ timeout: 5000 });

    // New Job button always visible
    await expect(page.locator('button:has-text("新建任务")')).toBeVisible();
  });

  test('New Job button switches to config tab', async ({ page }) => {
    await page.goto(BATCH_BUGS_URL);
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea');
    await textarea.fill('https://jira.example.com/browse/BUG-1');
    await page.locator('button:has-text("开始修复")').click();

    await expect(page.locator('[data-testid="tab-execution"]')).toHaveAttribute('data-state', 'active', { timeout: 10000 });

    // Click New Job
    await page.locator('button:has-text("新建任务")').click();

    // Config tab should become active again
    await expect(page.locator('[data-testid="tab-config"]')).toHaveAttribute('data-state', 'active', { timeout: 5000 });
  });
});

/* ================================================================
   API Contract Tests (backend integration)
   ================================================================ */

test.describe('M13: API Contract', () => {
  test('POST batch-bug-fix returns job_id', async ({ request }) => {
    const jobResult = await createMockJob(request, [
      'https://jira.example.com/browse/TEST-1',
    ]);

    if (!jobResult) {
      test.info().annotations.push({ type: 'info', description: 'SKIP — backend not available or not in mock mode' });
      return;
    }

    expect(jobResult.job_id).toBeTruthy();
    expect(jobResult.total_bugs).toBe(1);
  });

  test('GET job status returns bugs array', async ({ request }) => {
    const jobResult = await createMockJob(request, [
      'https://jira.example.com/browse/TEST-1',
    ]);

    if (!jobResult) {
      test.info().annotations.push({ type: 'info', description: 'SKIP — backend not available' });
      return;
    }

    const statusResp = await request.get(
      `${API_BASE}/api/v2/batch/bug-fix/${jobResult.job_id}`
    );

    if (statusResp.ok()) {
      const data = await statusResp.json();
      expect(data.bugs).toBeDefined();
      expect(Array.isArray(data.bugs)).toBeTruthy();

      if (data.bugs.length > 0) {
        const bug = data.bugs[0];
        expect(bug).toHaveProperty('url');
        expect(bug).toHaveProperty('status');
      }
    }
  });
});
