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

test('analysis columns: side by side and scrollable at real window widths', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Both columns render before any analysis, so the 50/50 split never degenerates into one
  // panel occupying half the grid with the other half empty.
  await expect(page.locator('.analysis-column')).toHaveCount(2);

  // Regression: the stacking breakpoint was originally 1100px, which is wider than the desktop
  // window. That collapsed the layout to a single column *and* dropped the height cap, so the
  // feature was absent exactly where it was meant to be used. Check the widths that matter.
  for (const width of [900, 1024, 1280, 1500]) {
    await page.setViewportSize({ width, height: 900 });
    const boxes = await page.locator('.analysis-column').evaluateAll((els) =>
      els.map((el) => el.getBoundingClientRect())
    );
    expect(Math.abs(boxes[0].y - boxes[1].y), `stacked at ${width}px`).toBeLessThan(5);
    expect(Math.abs(boxes[0].width - boxes[1].width), `uneven at ${width}px`).toBeLessThan(5);
  }

  // Only a genuinely narrow window stacks them.
  await page.setViewportSize({ width: 600, height: 900 });
  const stacked = await page.locator('.analysis-column').evaluateAll((els) =>
    els.map((el) => el.getBoundingClientRect())
  );
  expect(stacked[1].y).toBeGreaterThan(stacked[0].y);
});

test('analysis columns bound their height', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 700 });
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const height = (await page.locator('.analysis-column').first().boundingBox())?.height ?? 0;
  // 70vh, with box-sizing:border-box so the card padding is not added on top of it — without
  // that the column measured 690px in a 900px viewport and the cap was meaningless.
  expect(height).toBeLessThanOrEqual(700 * 0.7 + 2);
});

// The lists themselves only exist once an analysis has produced rows, so their scrolling is not
// asserted here — this suite runs against the dev server with no backend. Verified manually
// against a real analysis at a 520px viewport: both `.phenomena-list` and `.timeline-list`
// reported scrollHeight > clientHeight with overflow-y: auto.

test('clicking the overview chart moves the playback head', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const inputs = page.locator('input[type="file"]');
  await inputs.nth(0).setInputFiles(CSV_PATH);
  await page.waitForTimeout(1500);
  await inputs.nth(1).setInputFiles(WAV_PATH);
  await page.waitForTimeout(400);
  await page.getByRole('banner').getByRole('button', { name: 'Preview' }).click();
  await page.waitForTimeout(800);

  await expect(page.locator('.signal-preview')).toBeVisible();

  const before = await page.locator('text.gauge-value').textContent();
  await page.locator('.overview-chart').click({ position: { x: 320, y: 20 } });
  await page.waitForTimeout(400);
  const after = await page.locator('text.gauge-value').textContent();

  // The gauge tracks the playback head, so a seek that lands somewhere else changes the reading.
  expect(after).not.toBe(before);
});

// NOTE: the "seek while the preview is collapsed" path — where `handleSeek` opens the preview and
// flushes the pending seek once `SignalPreview` publishes its seek function — is deliberately not
// covered here. Exercising it needs phenomenon or event rows, which only exist after a real
// backend analysis, and this suite runs against the dev server alone.

test('detected events and transcript are scrollable, resizable panes', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Before an analysis both sections show empty states, so assert the mechanism instead: a pane
  // must carry both a resize handle and its own scrolling, since CSS `resize` is ignored unless
  // `overflow` is something other than `visible`.
  const css = await page.evaluate(() => {
    const probe = document.createElement('div');
    probe.className = 'resizable-pane';
    document.body.appendChild(probe);
    const style = getComputedStyle(probe);
    const result = { resize: style.resize, overflowY: style.overflowY };
    probe.remove();
    return result;
  });

  expect(css.resize).toBe('vertical');
  expect(css.overflowY).toBe('auto');
});
