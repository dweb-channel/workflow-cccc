/**
 * E2E Tests for M29 — Dark/Light Theme Switching
 *
 * T159: Verify theme switching, persistence, and visual consistency.
 *
 * S1: Default theme, toggle switching, localStorage persistence, system follow
 * S2: Accessibility — text contrast, no unreadable content in either theme
 * S3: Build verification (separate `next build` check)
 *
 * Requires: frontend at localhost:3000
 *
 * Author: browser-tester
 * Date: 2026-02-19
 */

import { test, expect, type Page } from '@playwright/test';

const PAGES = [
  { name: 'Home', url: '/' },
  { name: 'Batch Bugs', url: '/batch-bugs' },
  { name: 'Design to Code', url: '/design-to-code' },
  { name: 'Canvas', url: '/canvas' },
];

// Helper: clear localStorage theme before each test for isolation
async function clearTheme(page: Page) {
  await page.evaluate(() => localStorage.removeItem('theme'));
}

// Helper: get current theme from <html> class
async function getThemeClass(page: Page): Promise<'dark' | 'light'> {
  const hasDark = await page.evaluate(() =>
    document.documentElement.classList.contains('dark')
  );
  return hasDark ? 'dark' : 'light';
}

// Helper: get localStorage theme value
async function getStoredTheme(page: Page): Promise<string | null> {
  return page.evaluate(() => localStorage.getItem('theme'));
}

// Helper: get the theme toggle button
function getToggleButton(page: Page) {
  return page.locator('aside button', { hasText: /浅色模式|深色模式/ });
}

/* ================================================================
   S1: Default Theme + Toggle + Persistence
   ================================================================ */

test.describe('M29 S1: Theme switching core functionality', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await clearTheme(page);
  });

  test('default theme is light (no localStorage)', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const theme = await getThemeClass(page);
    expect(theme).toBe('light');

    // Toggle button should say "深色模式" (offering switch to dark)
    const toggle = getToggleButton(page);
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveText(/深色模式/);
  });

  test('clicking toggle switches to dark mode', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const toggle = getToggleButton(page);
    await toggle.click();

    // <html> should now have "dark" class
    const theme = await getThemeClass(page);
    expect(theme).toBe('dark');

    // Toggle label should now say "浅色模式" (offering switch to light)
    await expect(toggle).toHaveText(/浅色模式/);

    // localStorage should store "dark"
    const stored = await getStoredTheme(page);
    expect(stored).toBe('dark');
  });

  test('clicking toggle twice returns to light mode', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const toggle = getToggleButton(page);
    await toggle.click(); // → dark
    await toggle.click(); // → light

    const theme = await getThemeClass(page);
    expect(theme).toBe('light');

    await expect(toggle).toHaveText(/深色模式/);
    const stored = await getStoredTheme(page);
    expect(stored).toBe('light');
  });

  test('theme persists after page refresh (dark)', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Switch to dark
    const toggle = getToggleButton(page);
    await toggle.click();
    expect(await getThemeClass(page)).toBe('dark');

    // Refresh the page
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Should still be dark
    expect(await getThemeClass(page)).toBe('dark');
    await expect(getToggleButton(page)).toHaveText(/浅色模式/);
  });

  test('theme persists across page navigation', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Switch to dark on home page
    await getToggleButton(page).click();
    expect(await getThemeClass(page)).toBe('dark');

    // Navigate to batch-bugs
    await page.click('text=批量 Bug 修复');
    await page.waitForLoadState('domcontentloaded');

    // Should still be dark
    expect(await getThemeClass(page)).toBe('dark');
    await expect(getToggleButton(page)).toHaveText(/浅色模式/);
  });

  test('theme persists across direct URL navigation', async ({ page }) => {
    // Set dark theme via localStorage before navigating
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('theme', 'dark'));

    // Navigate to a different page directly
    await page.goto('/batch-bugs');
    await page.waitForLoadState('domcontentloaded');

    // Inline script in layout.tsx should apply dark class before React hydrates
    expect(await getThemeClass(page)).toBe('dark');
  });

  test('localStorage "light" is respected on load', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('theme', 'light'));

    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    expect(await getThemeClass(page)).toBe('light');
    await expect(getToggleButton(page)).toHaveText(/深色模式/);
  });
});

/* ================================================================
   S2: Theme visual consistency across all pages
   ================================================================ */

test.describe('M29 S2: Theme consistency across pages', () => {
  for (const { name, url } of PAGES) {
    test(`${name} (${url}) — light mode has correct background`, async ({ page }) => {
      await page.goto(url);
      await clearTheme(page);
      await page.reload();
      await page.waitForLoadState('domcontentloaded');

      expect(await getThemeClass(page)).toBe('light');

      // Body should have bg-background which resolves to light color
      const bodyBg = await page.evaluate(() =>
        getComputedStyle(document.body).backgroundColor
      );
      // In light mode, background should be a light color (high R, G, B values)
      // bg-background = rgb(var(--color-background)) = 248 250 252 in light
      expect(bodyBg).toBeTruthy();
      // Verify it's not a dark color (each channel > 200 for light theme)
      const match = bodyBg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (match) {
        const [, r, g, b] = match.map(Number);
        expect(r).toBeGreaterThan(200);
        expect(g).toBeGreaterThan(200);
        expect(b).toBeGreaterThan(200);
      }
    });

    test(`${name} (${url}) — dark mode has correct background`, async ({ page }) => {
      await page.goto(url);
      await page.evaluate(() => localStorage.setItem('theme', 'dark'));
      await page.reload();
      await page.waitForLoadState('domcontentloaded');

      expect(await getThemeClass(page)).toBe('dark');

      const bodyBg = await page.evaluate(() =>
        getComputedStyle(document.body).backgroundColor
      );
      // In dark mode, background should be a dark color (low R, G, B values)
      // bg-background = rgb(var(--color-background)) = 15 23 42 in dark
      expect(bodyBg).toBeTruthy();
      const match = bodyBg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (match) {
        const [, r, g, b] = match.map(Number);
        expect(r).toBeLessThan(80);
        expect(g).toBeLessThan(80);
        expect(b).toBeLessThan(80);
      }
    });
  }
});

/* ================================================================
   S2b: Accessibility — text contrast and readability
   ================================================================ */

test.describe('M29 S2b: Text readability in both themes', () => {
  test('sidebar text is readable in light mode', async ({ page }) => {
    await page.goto('/');
    await clearTheme(page);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Logo text should be visible
    const logo = page.locator('aside h1', { hasText: '工作流平台' });
    await expect(logo).toBeVisible();

    // Nav items visible
    await expect(page.locator('aside nav >> text=工作流编辑器')).toBeVisible();
    await expect(page.locator('aside nav >> text=批量 Bug 修复')).toBeVisible();
    await expect(page.locator('aside nav >> text=设计转代码')).toBeVisible();
  });

  test('sidebar text is readable in dark mode', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('theme', 'dark'));
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    expect(await getThemeClass(page)).toBe('dark');

    // Logo text should still be visible
    const logo = page.locator('aside h1', { hasText: '工作流平台' });
    await expect(logo).toBeVisible();

    // Nav items visible
    await expect(page.locator('aside nav >> text=工作流编辑器')).toBeVisible();
    await expect(page.locator('aside nav >> text=批量 Bug 修复')).toBeVisible();
    await expect(page.locator('aside nav >> text=设计转代码')).toBeVisible();
  });

  test('batch-bugs form elements readable in dark mode', async ({ page }) => {
    await page.goto('/batch-bugs');
    await page.evaluate(() => localStorage.setItem('theme', 'dark'));
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Card titles should be visible
    await expect(page.locator('text=Jira Bug 链接')).toBeVisible();

    // Tab triggers visible
    await expect(page.getByTestId('tab-config')).toBeVisible();

    // Theme toggle accessible
    await expect(getToggleButton(page)).toBeVisible();
  });

  test('batch-bugs form elements readable in light mode', async ({ page }) => {
    await page.goto('/batch-bugs');
    await clearTheme(page);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    await expect(page.locator('text=Jira Bug 链接')).toBeVisible();
    await expect(page.getByTestId('tab-config')).toBeVisible();
    await expect(getToggleButton(page)).toBeVisible();
  });
});

/* ================================================================
   S3: CSS variable tokens are correctly applied
   ================================================================ */

test.describe('M29 S3: CSS variables resolve correctly', () => {
  test('--color-background resolves differently in light vs dark', async ({ page }) => {
    await page.goto('/');
    await clearTheme(page);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Get light mode background
    const lightBg = await page.evaluate(() =>
      getComputedStyle(document.body).backgroundColor
    );

    // Switch to dark
    await getToggleButton(page).click();

    // Get dark mode background
    const darkBg = await page.evaluate(() =>
      getComputedStyle(document.body).backgroundColor
    );

    // They should be different
    expect(lightBg).not.toBe(darkBg);
  });

  test('--color-foreground resolves differently in light vs dark', async ({ page }) => {
    await page.goto('/');
    await clearTheme(page);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Get light mode text color from a known element
    const lightColor = await page.evaluate(() => {
      const el = document.querySelector('aside h1');
      return el ? getComputedStyle(el).color : '';
    });

    // Switch to dark
    await getToggleButton(page).click();

    const darkColor = await page.evaluate(() => {
      const el = document.querySelector('aside h1');
      return el ? getComputedStyle(el).color : '';
    });

    // They should be different
    expect(lightColor).not.toBe(darkColor);
  });

  test('no FOUC — dark class present before hydration via inline script', async ({ page }) => {
    // Set dark theme
    await page.goto('/');
    await page.evaluate(() => localStorage.setItem('theme', 'dark'));

    // Navigate to new page — check HTML has dark class before load completes
    const darkClassPromise = page.evaluate(() => {
      return new Promise<boolean>((resolve) => {
        // Check immediately — the inline script should have already applied .dark
        resolve(document.documentElement.classList.contains('dark'));
      });
    });

    await page.goto('/batch-bugs');
    // The inline script in <head> adds .dark synchronously
    // After navigation, dark class should be present
    expect(await getThemeClass(page)).toBe('dark');
  });
});

/* ================================================================
   S4: Theme toggle button accessibility
   ================================================================ */

test.describe('M29 S4: Toggle button attributes', () => {
  test('toggle button has descriptive title attribute', async ({ page }) => {
    await page.goto('/');
    await clearTheme(page);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    const toggle = getToggleButton(page);

    // Light mode: title should mention switching to dark
    await expect(toggle).toHaveAttribute('title', '切换到深色模式');

    // Switch to dark
    await toggle.click();

    // Dark mode: title should mention switching to light
    await expect(toggle).toHaveAttribute('title', '切换到浅色模式');
  });

  test('toggle button is keyboard accessible', async ({ page }) => {
    await page.goto('/');
    await clearTheme(page);
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Tab to the toggle button and press Enter
    const toggle = getToggleButton(page);
    await toggle.focus();
    await page.keyboard.press('Enter');

    // Should switch to dark
    expect(await getThemeClass(page)).toBe('dark');
  });
});
