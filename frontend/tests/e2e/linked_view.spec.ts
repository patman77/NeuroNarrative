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

/** How many phenomena the padded fixture spreads across the recording. */
const PADDED_PHENOMENA = 27;
const PADDED_KINDS = ['BE', 'A', 'KB'];

/** The captured result, padded out to a realistic session's worth of rows.
 *
 * The copies are spread across the recording and given magnitudes rather than repeating the
 * captured timestamps: the bubble layout is about what happens when several phenomena fall close
 * together in *time*, and three rows stacked on one instant would never exercise it. */
function analysisResult() {
  const result = JSON.parse(JSON.stringify(CAPTURED));
  const duration = result.gsr_metadata.duration_sec;
  const base = result.phenomena[0];
  result.phenomena = Array.from({ length: PADDED_PHENOMENA }, (_, i) => {
    const kind = PADDED_KINDS[i % PADDED_KINDS.length];
    const tStart = ((i + 0.5) * duration) / (PADDED_PHENOMENA + 1);
    return {
      ...base,
      id: `p-${i}`,
      kind,
      t_start: tStart,
      t_end: tStart + 0.4,
      // KB is a body movement, which has no A-magnitude — so the fixture also covers the
      // bubble that has only a kind to show.
      amplitude_a: kind === 'KB' ? null : Number((0.5 + (i % 9) * 0.4).toFixed(1))
    };
  });

  const events = [...result.events];
  for (let copy = 1; copy <= 4; copy++) {
    for (const e of result.events) {
      events.push({ ...e, event_id: `${e.event_id}-c${copy}` });
    }
  }
  result.events = events;

  // Three sections spanning the recording, so a narrative span is a real range to shade.
  const narrativeBase = result.narrative[0];
  result.narrative = [0, 1, 2].map((i) => ({
    ...narrativeBase,
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

  // Concretely: the charts land near the top of the window rather than floating in the middle of
  // it with the preview card's header above them. Asserted on the charts rather than on the
  // gauge being off-screen, because the stacked layout pins the card at a negative offset — the
  // gauge is scrolled out by the sticky rule, not by the page scroll the reveal performed.
  expect(geometry.chart.top).toBeLessThan(geometry.vh / 3);
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

/** The phenomena the padded fixture puts inside a given third of the recording. */
function phenomenaInThird(index: number): number {
  const duration = CAPTURED.gsr_metadata.duration_sec;
  const from = (duration / 3) * index;
  const to = (duration / 3) * (index + 1);
  let count = 0;
  for (let i = 0; i < PADDED_PHENOMENA; i++) {
    const t = ((i + 0.5) * duration) / (PADDED_PHENOMENA + 1);
    if (t >= from && t < to) count++;
  }
  return count;
}

test('hovering a narrative section highlights every phenomenon inside it', async ({ page }) => {
  await runAnalysis(page);

  const section = page.locator('.narrative-section').nth(1);
  await section.scrollIntoViewIfNeeded();
  await section.hover();
  await page.waitForTimeout(400);

  // Not just the first one. A section covers minutes and holds a whole cluster; highlighting one
  // representative row said the section was about that single moment.
  const expected = phenomenaInThird(1);
  expect(expected).toBeGreaterThan(1);
  await expect(page.locator('.phenomenon-row-active')).toHaveCount(expected);
});

test('a hovered section labels its phenomena with non-overlapping bubbles', async ({ page }) => {
  await runAnalysis(page);

  const section = page.locator('.narrative-section').nth(1);
  await section.scrollIntoViewIfNeeded();
  await section.hover();
  await page.waitForTimeout(400);

  await expect(page.locator('.plot-legend').first()).toBeVisible();

  const boxes = await page.locator('.signal-chart .plot-bubbles rect').evaluateAll((nodes) =>
    nodes.map((n) => ({
      x: Number(n.getAttribute('x')),
      y: Number(n.getAttribute('y')),
      w: Number(n.getAttribute('width')),
      h: Number(n.getAttribute('height'))
    }))
  );
  // The detail chart is wide enough at the default zoom to label the whole section.
  expect(boxes.length).toBe(phenomenaInThird(1));

  // The requirement is literal: no bubble may cover another. Lane packing is what buys this, so
  // a regression here means labels drawn on top of each other and none of them readable.
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      const overlaps =
        a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
      expect(overlaps, `bubbles ${i} and ${j} overlap`).toBe(false);
    }
  }
});

test('hovering one phenomenon labels only that one', async ({ page }) => {
  await runAnalysis(page);

  await page.locator('.phenomenon-row').first().hover();
  await page.waitForTimeout(400);

  await expect(page.locator('.signal-chart .plot-bubbles rect')).toHaveCount(1);
  await expect(page.locator('.overview-chart .plot-bubbles rect')).toHaveCount(1);
});

test('the layout switch moves the plot into its own column and is remembered', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await runAnalysis(page);

  const toggle = page.getByRole('button', { name: /^Layout:/ });
  await expect(toggle).toHaveText('Layout: stacked');

  // Stacked: the plot is pinned, so bringing the lists fully into view must not take it off
  // screen. Scroll to where the workspace ends — past that the plot has left its own region and
  // is meant to scroll away like anything else.
  await page.evaluate(() => {
    const el = document.querySelector('.workspace')!;
    const bottom = el.getBoundingClientRect().bottom + window.scrollY;
    window.scrollTo(0, bottom - window.innerHeight);
  });
  await page.waitForTimeout(300);
  const pinned = await page.evaluate(() => {
    const c = document.querySelector('.overview-chart svg')!.getBoundingClientRect();
    return { top: c.top, bottom: c.bottom, vh: window.innerHeight };
  });
  expect(pinned.top).toBeGreaterThanOrEqual(0);
  expect(pinned.bottom).toBeLessThanOrEqual(pinned.vh);

  await toggle.click();
  await expect(toggle).toHaveText('Layout: split');

  // Split: plot column on the left, both lists to its right, and the overview no longer overflows
  // the narrower column — it follows its container rather than being a fixed 920 px.
  const split = await page.evaluate(() => {
    const plot = document.querySelector('.workspace-plot')!.getBoundingClientRect();
    const lists = document.querySelector('.analysis-columns')!.getBoundingClientRect();
    const chart = document.querySelector('.overview-chart')!;
    const svg = chart.querySelector('svg')!.getBoundingClientRect();
    return {
      plotRight: plot.right,
      listsLeft: lists.left,
      chartWidth: chart.getBoundingClientRect().width,
      svgWidth: svg.width
    };
  });
  expect(split.plotRight).toBeLessThanOrEqual(split.listsLeft + 1);
  expect(split.svgWidth).toBeLessThanOrEqual(split.chartWidth);

  // The choice is a property of the monitor you are sitting at, so it survives a reload.
  await page.reload();
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('button', { name: /^Layout:/ })).toHaveText('Layout: split');
});
