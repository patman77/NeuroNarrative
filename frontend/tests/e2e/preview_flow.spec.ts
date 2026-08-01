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

// The golden fixture is real mindwalker export rows, and `backend/tests/test_conditioning.py`
// asserts the *same* file resolves to strategy "data+baseline" with LP ~6.006 at t=0. Checking
// it from the browser side too is what keeps the two parsers from drifting apart again: they
// used to pick different columns from this exact schema (Baseline here, Resistance(kOhm) there).
const MINDWALKER_CSV = path.resolve(__dirname, '../../../tests/fixtures/mindwalker_export.csv');

test('channel resolution: a real mindwalker export uses the raw ADC channel', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const inputs = page.locator('input[type="file"]');
  await inputs.nth(0).setInputFiles(MINDWALKER_CSV);
  await page.waitForTimeout(1200);
  await inputs.nth(1).setInputFiles(WAV_PATH);
  await page.waitForTimeout(400);

  const previewBtn = page.getByRole('banner').getByRole('button', { name: 'Preview' });
  await expect(previewBtn).toBeEnabled({ timeout: 5000 });
  await previewBtn.click();
  await page.waitForTimeout(800);

  // Resolved from Data(16 bit), not the quantised Baseline column.
  const channel = page.locator('.metric-label', { hasText: 'Channel' }).locator('..');
  await expect(channel).toContainText('Data(16 bit)');
  await expect(channel).not.toContainText('0.05 steps');

  // The gauge reads a charge level near LP 6.0 — the value the backend's conditioning test
  // asserts for the same fixture — rather than 213 (raw kΩ) or a divide-by-10 rescaling of it.
  await expect(page.locator('.gauge-panel')).toBeVisible();
  // `textContent`, not `innerText`: the reading is an SVG <text>, not an HTMLElement.
  const reading = parseFloat(
    ((await page.locator('text.gauge-value').textContent()) ?? '').replace(',', '.')
  );
  expect(reading).toBeGreaterThan(4.0);
  expect(reading).toBeLessThanOrEqual(6.5);

  // And the resistance metric still shows the device's own reading in kΩ, not a reconstruction.
  await expect(page.locator('.metric-label', { hasText: 'Resistance' }).locator('..')).toContainText(
    'kΩ'
  );
});

test('file dialog filters: the CSV input declares MIME types, not just an extension', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const inputs = page.locator('input[type="file"]');

  // The extension alone is not enough. In the desktop shell WKWebView hands pywebview only
  // `_acceptedMIMETypes()`, which is empty for an extension-only accept list — so `.csv` on its
  // own produced no filter and the open panel listed every file on the machine.
  const csvAccept = (await inputs.nth(0).getAttribute('accept')) ?? '';
  expect(csvAccept).toContain('.csv');
  expect(csvAccept).toContain('text/csv');
  // Would map to com.microsoft.excel.xls and let spreadsheets through.
  expect(csvAccept).not.toContain('vnd.ms-excel');

  const wavAccept = (await inputs.nth(1).getAttribute('accept')) ?? '';
  expect(wavAccept).toContain('.wav');
  expect(wavAccept).toContain('audio/wav');
});
