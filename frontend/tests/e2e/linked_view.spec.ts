import { test, expect, Page } from '@playwright/test';
import path from 'path';
import fs from 'fs';

/**
 * The linked view: clicking a row seeks *and* repositions the page, and the plots mark what the
 * other panels are pointing at.
 *
 * The analysis is stubbed from a response captured from the real backend
 * (`fixtures/analysis_result.json`), so these run without one and without waiting minutes for
 * transcription. The rows are multiplied to make the columns tall — the whole point of the
 * scroll rule is what happens when the clicked row is far below the charts, and the synthetic
 * 60-second fixture only produces three phenomena.
 */

const CSV_PATH = path.resolve(__dirname, '../../../test_gsr.csv');
const WAV_PATH = path.resolve(__dirname, '../../../test_audio.wav');
const CAPTURED = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, 'fixtures/analysis_result.json'), 'utf-8')
);

/** The captured result, padded out to a realistic session's worth of rows. */
function analysisResult() {
  const result = JSON.parse(JSON.stringify(CAPTURED));
  const phenomena = [...result.phenomena];
  for (let copy = 1; copy <= 8; copy++) {
    for (const p of result.phenomena) {
      phenomena.push({ ...p, id: `${p.id}-c${copy}`, t_start: p.t_start, t_end: p.t_end });
    }
  }
  result.phenomena = phenomena;

  const events = [...result.events];
  for (let copy = 1; copy <= 4; copy++) {
    for (const e of result.events) {
      events.push({ ...e, event_id: `${e.event_id}-c${copy}` });
    }
  }
  result.events = events;

  // Three sections spanning the recording, so a narrative span is a real range to shade.
  const duration = result.gsr_metadata.duration_sec;
  const base = result.narrative[0];
  result.narrative = [0, 1, 2].map((i) => ({
    ...base,
    start_sec: (duration / 3) * i,
    end_sec: (duration / 3) * (i + 1),
    label: `Abschnitt ${i + 1}`,
    title: `Abschnitt ${i + 1}`
  }));
  return result;
}

async function stubBackend(page: Page) {
  const result = analysisResult();
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { status: 'ok', summarizer_enabled: false, summarizer_status: 'off' } })
  );
  await page.route('**/api/upload', (route) =>
    route.fulfill({ json: { csv_path: '/staged/gsr.csv', wav_path: '/staged/audio.wav' } })
  );
  // Order matters: this pattern does not match `/api/analyze/<job>`, which is handled below.
  await page.route('**/api/analyze', (route) => route.fulfill({ status: 202, json: { job_id: 'job-1' } }));
  await page.route('**/api/analyze/*', (route) =>
    route.fulfill({
      json: { job_id: 'job-1', status: 'done', stage: 'done', progress: 1, result, error: null }
    })
  );
  await page.route('**/api/labels/**', (route) =>
    route.fulfill({ json: { recording_id: 'rec', labels: [], summary: {} } })
  );
}

async function runAnalysis(page: Page) {
  await stubBackend(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const inputs = page.locator('input[type="file"]');
  await inputs.nth(0).setInputFiles(CSV_PATH);
  await page.waitForTimeout(1200);
  await inputs.nth(1).setInputFiles(WAV_PATH);
  await page.waitForTimeout(400);

  await page.getByRole('banner').getByRole('button', { name: 'Analyze session' }).click();
  await expect(page.locator('.phenomenon-row').first()).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.overview-chart')).toBeVisible();
}

test('clicking a row brings the charts into view without scrolling the row away', async ({ page }) => {
  // Measured: the two charts and their headings occupy ~1080 px, so a window shorter than that
  // cannot show the charts and the first row together and the charts win — see the test below.
  await page.setViewportSize({ width: 1440, height: 1200 });
  await runAnalysis(page);

  // Start below the fold, where you are when you have been reading the list.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(300);

  const row = page.locator('.phenomenon-row').first();
  await row.click();
  // The reveal animation is capped at 2 s (utils/smoothScroll.ts).
  await page.waitForTimeout(2400);

  const geometry = await page.evaluate(() => {
    const r = document.querySelector('.phenomenon-row')!.getBoundingClientRect();
    const chart = document.querySelector('.overview-chart svg')!.getBoundingClientRect();
    const gauge = document.querySelector('.gauge-panel')!.getBoundingClientRect();
    return {
      vh: window.innerHeight,
      row: { top: r.top, bottom: r.bottom },
      chart: { top: chart.top, bottom: chart.bottom },
      gaugeTop: gauge.top
    };
  });

  // The charts are what the click was about, so they must be on screen and whole.
  expect(geometry.chart.top).toBeGreaterThanOrEqual(0);
  expect(geometry.chart.bottom).toBeLessThanOrEqual(geometry.vh);

  // And the clicked row must still be readable. The regression this guards: anchoring the scroll
  // on the top of the preview card put ~700 px of gauge, metrics and waveform above the charts,
  // so the row you clicked ended up far below the fold.
  expect(geometry.row.top).toBeGreaterThanOrEqual(0);
  expect(geometry.row.bottom).toBeLessThanOrEqual(geometry.vh + 1);

  // Concretely: the page did not scroll back up to the head of the preview card.
  expect(geometry.gaugeTop).toBeLessThan(0);
});

test('when the charts and the row cannot both fit, the charts win', async ({ page }) => {
  // A short window: the two charts alone are most of it.
  await page.setViewportSize({ width: 1280, height: 720 });
  await runAnalysis(page);

  const row = page.locator('.phenomenon-row').last();
  await row.scrollIntoViewIfNeeded();
  await row.click();
  await page.waitForTimeout(2400);

  const chart = await page.evaluate(() => {
    const c = document.querySelector('.overview-chart svg')!.getBoundingClientRect();
    return { top: c.top, bottom: c.bottom, vh: window.innerHeight };
  });
  // Showing half a trace would answer nothing; the row is the thing you can scroll back to.
  expect(chart.top).toBeGreaterThanOrEqual(0);
  expect(chart.bottom).toBeLessThanOrEqual(chart.vh);
});

test('a click leaves the moment marked in both charts', async ({ page }) => {
  await runAnalysis(page);

  const markedBefore = await page.locator('.overview-chart line[stroke="#7c3aed"]').count();
  expect(markedBefore).toBe(0);

  await page.locator('.phenomenon-row').first().click();
  await page.waitForTimeout(300);

  // Both charts, and it survives the pointer moving away — that is what makes it a selection
  // rather than a hover.
  await page.mouse.move(5, 5);
  await page.waitForTimeout(200);
  await expect(page.locator('.overview-chart line[stroke="#7c3aed"]')).toHaveCount(1);
  await expect(page.locator('.signal-chart line[stroke="#7c3aed"]')).toHaveCount(1);
});

test('a narrative section shades its whole span in both charts', async ({ page }) => {
  await runAnalysis(page);

  const section = page.locator('.narrative-section').nth(1);
  await section.scrollIntoViewIfNeeded();
  await section.hover();
  await page.waitForTimeout(300);

  // A section covers minutes: a single line at its start does not answer "from when to when".
  const band = page.locator('.overview-chart rect[fill="#7c3aed"]');
  await expect(band).toHaveCount(1);
  await expect(page.locator('.signal-chart rect[fill="#7c3aed"]')).toHaveCount(1);

  // The band spans a third of the recording, so it is a visible proportion of the overview.
  const width = await band.evaluate((el) => Number(el.getAttribute('width')));
  expect(width).toBeGreaterThan(100);
});
