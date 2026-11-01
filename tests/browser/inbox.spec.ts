import { test, expect } from '@playwright/test';

test('refresh, filter, inspect, mark seen, snooze and reload', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Synthetic scenario').selectOption('standard');
  await page.getByRole('button', { name: 'Refresh inbox' }).click();
  await expect(page.locator('#notice')).toContainText('fictional');
  await page.locator('#reason').selectOption('NEW_FEEDBACK');
  await page.getByRole('button', { name: 'Keep the last successful cache on network failure' }).click();
  await page.locator('#seen').click();
  await expect(page.locator('#detail-body')).not.toContainText('New feedback from sample-reviewer');
  await page.locator('#snooze').click();
  await expect(page.locator('#unsnooze')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.reload();
  await page.getByRole('button', { name: 'Snoozed', exact: true }).click();
  await page.getByRole('button', { name: 'Keep the last successful cache on network failure' }).click();
  await page.locator('#unsnooze').click();
  await expect(page.locator('#unsnooze')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.locator('.preferences summary').click();
  await page.locator('#pinned-repo').fill('example-workspace/toolkit');
  await page.getByRole('button', { name: 'Save preferences' }).click();
  await page.reload();
  await page.locator('.preferences summary').click();
  await expect(page.locator('#pinned-repo')).toHaveValue('example-workspace/toolkit');
});

test('mobile rendering escapes untrusted text and blocks unsafe links', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/state', async route => {
    const response = await route.fetch();
    const state = await response.json();
    const row = state.rows[0];
    row.sources.pr.data.title = '<img src=x onerror=window.injected=1>' + 'long'.repeat(50);
    row.sources.threads = { observed_at: new Date().toISOString(), data: [{resolved:false,path:'file.ts',line:2,body:'<script>window.injected=1</script>',url:'javascript:alert(1)'}] };
    await route.fulfill({ json: state });
  });
  await page.goto('/');
  await page.getByRole('button', { name: /^<img src=x/ }).click();
  await expect(page.locator('#detail-body')).toContainText('link unavailable');
  await expect(page.locator('img')).toHaveCount(0);
  expect(await page.evaluate(() => 'injected' in window)).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Switch color theme' }).click();
});
