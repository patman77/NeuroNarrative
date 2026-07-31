import { test, expect } from '@playwright/test';
import path from 'path';

// Paths to test fixtures at the repo root
// __dirname = frontend/tests/e2e, so ../../.. reaches repo root (NeuroNarrative/)
const CSV_PATH = path.resolve(__dirname, '../../../test_gsr.csv');
const WAV_PATH = path.resolve(__dirname, '../../../test_audio.wav');

test('page loads with NeuroNarrative heading', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toContainText('NeuroNarrative');
});

test('Preview button is disabled until both files loaded', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const previewBtn = page.getByRole('banner').getByRole('button', { name: 'Preview' });
  await expect(previewBtn).toBeDisabled();
});

test('full preview flow: upload → preview → gauge + charts render', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const inputs = page.locator('input[type="file"]');
  await inputs.nth(0).setInputFiles(CSV_PATH);
  await page.waitForTimeout(1500);
  await inputs.nth(1).setInputFiles(WAV_PATH);
  await page.waitForTimeout(400);

  const previewBtn = page.getByRole('banner').getByRole('button', { name: 'Preview' });
  await expect(previewBtn).toBeEnabled({ timeout: 5000 });
  await previewBtn.click();
  await page.waitForTimeout(800);

  await expect(page.locator('.signal-preview')).toBeVisible();
  await expect(page.locator('.gauge-panel')).toBeVisible();
  await expect(page.locator('.overview-chart')).toBeVisible();
});

test('zoom shortcuts: buttons and keys drive the detail chart', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const inputs = page.locator('input[type="file"]');
  await inputs.nth(0).setInputFiles(CSV_PATH);
  await page.waitForTimeout(1500);
  await inputs.nth(1).setInputFiles(WAV_PATH);
  await page.waitForTimeout(400);
  await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
  await page.waitForTimeout(800);

  const zoomLevel = page.locator('.zoom-level');
  await expect(zoomLevel).toHaveText('100%');

  await page.getByTitle('Zoom in (+)').click();
  await expect(zoomLevel).toHaveText('150%');

  await page.keyboard.press('-');
  await expect(zoomLevel).toHaveText('100%');

  // Fit width shrinks px/s so the whole recording fits the container.
  await page.keyboard.press('w');
  const fitted = await zoomLevel.textContent();
  expect(parseInt(fitted ?? '100', 10)).toBeLessThan(100);

  // Fit height toggles; 0 restores the original view.
  await page.keyboard.press('h');
  await expect(page.getByTitle('Fit signal range to height (H)')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('0');
  await expect(zoomLevel).toHaveText('100%');
  await expect(page.getByTitle('Fit signal range to height (H)')).toHaveAttribute('aria-pressed', 'false');
});

test('page zoom: header control and Cmd/Ctrl shortcuts', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const level = page.locator('.page-zoom-level');
  await expect(level).toHaveText('100%');

  await page.keyboard.press('ControlOrMeta+=');
  await expect(level).toHaveText('110%');

  await page.keyboard.press('ControlOrMeta+-');
  await expect(level).toHaveText('100%');

  await page.locator('.page-zoom-button').last().click();
  await expect(level).toHaveText('110%');

  await page.keyboard.press('ControlOrMeta+0');
  await expect(level).toHaveText('100%');

  const zoom = await page.evaluate(() => document.documentElement.style.getPropertyValue('zoom'));
  expect(zoom).toBe('1');
});
