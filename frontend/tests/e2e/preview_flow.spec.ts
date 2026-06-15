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
  const previewBtn = page.locator('header button').first();
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

  const previewBtn = page.locator('header button').first();
  await expect(previewBtn).toBeEnabled({ timeout: 5000 });
  await previewBtn.click();
  await page.waitForTimeout(800);

  await expect(page.locator('.signal-preview')).toBeVisible();
  await expect(page.locator('.gauge-panel')).toBeVisible();
  await expect(page.locator('.overview-chart')).toBeVisible();
});
