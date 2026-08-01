import Papa from "papaparse";

/**
 * L0 conditioning for the live preview.
 *
 * This mirrors `backend/app/services/phenomena/conditioning.py` step for step. The two used to
 * disagree — this parser scored `/baseline/` highest and drew the 0.05-quantised staircase, while
 * the backend analysed `Resistance(kOhm)` — so the preview and the analysis were showing
 * different signals from the same file. `tests/fixtures/mindwalker_export.csv` is checked by both
 * test suites to keep them in step.
 *
 * The canonical channel is LP (Ladungspegel), the MindWalking charge level, 1.0-6.5. It is log
 * resistance: `ln R[kOhm] = 1.0157 * LP - 1.0045`. See docs/mindwalking-domain.md §1 and §4.
 */

export type LpStrategy =
  | "data+baseline"
  | "resistance+baseline"
  | "resistance-nominal"
  | "conductance"
  | "baseline";

export interface ParsedGsrSample {
  timeSec: number;
  /** Charge level. The canonical signal — charts and the gauge both read this. */
  lp: number;
  /** Alias of `lp`, kept so the chart code reads naturally. */
  value: number;
  rawValue: number;
  baseline?: number;
  resistance?: number;
}

export interface ParsedGsrResult {
  samples: ParsedGsrSample[];
  samplingRateHz: number | null;
  sourceColumn: string;
  strategy: LpStrategy;
  /** Smallest LP step representable in the source. 0.05 = the Baseline staircase. */
  resolutionLp: number;
  quantised: boolean;
  notes: string[];
  minValue: number;
  maxValue: number;
  startTimeSec: number;
  endTimeSec: number;
  hasBaseline: boolean;
  hasResistance: boolean;
  baselineColumn?: string;
  resistanceColumn?: string;
}

export const NOMINAL_LN_R_SLOPE = 1.0157;
export const NOMINAL_LN_R_INTERCEPT = -1.0045;
export const LP_DEVICE_STEP = 0.05;

const NUMERIC_REGEX = /-?\d+(?:[.,]\d+)?/;
// `time_ms`, `Time(msec)`, `t millis` — but not `timestamp`, where "ms" follows a letter.
const MS_COLUMN_REGEX = /(^|[^a-z])(milliseconds?|millis|msec|ms)([^a-z]|$)/i;

function normalizeField(field: string): string {
  return field.trim().toLowerCase();
}

function sanitizeNumber(value: unknown): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value).trim();
  if (!text || !NUMERIC_REGEX.test(text)) {
    return null;
  }
  const parsed = Number.parseFloat(text.replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

function findColumn(fields: string[], ...needles: string[]): string | undefined {
  return fields.find((field) => {
    const norm = normalizeField(field);
    return needles.some((needle) => norm.includes(needle));
  });
}

function columnValues(rows: Record<string, unknown>[], field: string): Array<number | null> {
  return rows.map((row) => sanitizeNumber(row[field]));
}

/** Least-squares `y = a*x + b`, or null when x does not vary enough to constrain it. */
function fitLinear(x: number[], y: number[]): { slope: number; intercept: number } | null {
  const n = x.length;
  if (n < 2) return null;
  if (new Set(x).size < 2) return null;

  let sx = 0;
  let sy = 0;
  for (let i = 0; i < n; i += 1) {
    sx += x[i];
    sy += y[i];
  }
  const mx = sx / n;
  const my = sy / n;

  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i += 1) {
    const dx = x[i] - mx;
    num += dx * (y[i] - my);
    den += dx * dx;
  }
  if (den === 0) return null;

  const slope = num / den;
  if (!Number.isFinite(slope) || slope === 0) return null;
  const intercept = my - slope * mx;
  if (!Number.isFinite(intercept)) return null;
  return { slope, intercept };
}

/** Smallest step the data actually moves in — the practical quantisation of a channel. */
function observedResolution(values: number[]): number {
  const unique = Array.from(new Set(values.filter((v) => Number.isFinite(v)))).sort((a, b) => a - b);
  const steps: number[] = [];
  for (let i = 1; i < unique.length; i += 1) {
    const step = unique[i] - unique[i - 1];
    if (step > 0) steps.push(step);
  }
  if (!steps.length) return 0;
  steps.sort((a, b) => a - b);
  return steps[Math.floor(steps.length / 2)];
}

function determineTimeScaling(timeField: string, timeValues: number[]): number {
  if (MS_COLUMN_REGEX.test(normalizeField(timeField))) {
    return 1000;
  }
  const diffs: number[] = [];
  for (let i = 1; i < timeValues.length; i += 1) {
    const diff = timeValues[i] - timeValues[i - 1];
    if (Number.isFinite(diff) && diff > 0) diffs.push(diff);
  }
  if (!diffs.length) return 1;
  diffs.sort((a, b) => a - b);
  const medianStep = diffs[Math.floor(diffs.length / 2)];
  // Biosignal exports run at 1 Hz or faster, so a median step of >= 1 unit cannot be seconds.
  return medianStep >= 1 ? 1000 : 1;
}

interface LpResolution {
  lp: Array<number | null>;
  strategy: LpStrategy;
  resolutionLp: number;
  sourceColumn: string;
  notes: string[];
}

/**
 * Resolve an export to LP. Order, best first:
 *   1. Data(16 bit) + Baseline — fit `Data = k*LP + c` and invert (~1e-4 LP resolution)
 *   2. Resistance + Baseline   — fit `ln R = a*LP + b` for this recording and invert
 *   3. Resistance              — same inversion with the nominal constants
 *   4. Conductance             — reciprocate to resistance, then as (3)
 *   5. Baseline                — already LP, but quantised to 0.05
 */
function resolveLp(fields: string[], rows: Record<string, unknown>[]): LpResolution {
  const baselineField = findColumn(fields, "baseline");
  const resistanceField = findColumn(fields, "resistance", "ohm");
  const conductanceField = findColumn(fields, "conductance", "siemens");
  // A bare `data` column only means the ADC channel when a Baseline sits beside it to anchor it.
  const dataField =
    findColumn(fields, "data(16", "data (16", "16 bit", "16bit") ??
    (baselineField ? findColumn(fields, "data") : undefined);

  const baseline = baselineField ? columnValues(rows, baselineField) : null;
  const notes: string[] = [];

  // --- 1. raw ADC anchored on the baseline staircase ---------------------------------------
  if (dataField && baseline) {
    const raw = columnValues(rows, dataField);
    const fx: number[] = [];
    const fy: number[] = [];
    for (let i = 0; i < rows.length; i += 1) {
      const b = baseline[i];
      const d = raw[i];
      if (b !== null && d !== null) {
        fx.push(b);
        fy.push(d);
      }
    }
    const fit = fitLinear(fx, fy);
    if (fit) {
      const lp = raw.map((d) => (d === null ? null : (d - fit.intercept) / fit.slope));
      let residual = 0;
      for (let i = 0; i < rows.length; i += 1) {
        const b = baseline[i];
        const v = lp[i];
        if (b !== null && v !== null) residual = Math.max(residual, Math.abs(v - b));
      }
      // A correct fit disagrees with the 0.05-quantised staircase by at most about half a step
      // plus the within-window needle travel. Far more than that means `data` is something else.
      if (residual <= 3 * LP_DEVICE_STEP) {
        notes.push(
          `LP from "${dataField}" anchored on "${baselineField}" ` +
            `(Data = ${fit.slope.toFixed(1)}*LP + ${fit.intercept.toFixed(1)}, ` +
            `max |LP - Baseline| = ${residual.toFixed(4)})`
        );
        return {
          lp,
          strategy: "data+baseline",
          resolutionLp: Math.abs(1 / fit.slope),
          sourceColumn: dataField,
          notes
        };
      }
      notes.push(
        `ignored "${dataField}": fit against "${baselineField}" is off by ` +
          `${residual.toFixed(3)} LP, so it is not the raw charge channel`
      );
    }
  }

  // --- 2/3/4. resistance (or conductance) via the log relationship --------------------------
  let resistance: Array<number | null> | null = null;
  let resistanceSource: string | undefined;
  if (resistanceField) {
    resistance = columnValues(rows, resistanceField);
    resistanceSource = resistanceField;
  } else if (conductanceField) {
    resistance = columnValues(rows, conductanceField).map((g) =>
      g !== null && g > 0 ? 1e3 / g : null
    );
    resistanceSource = conductanceField;
    notes.push(`derived resistance from "${conductanceField}" (assumed microsiemens)`);
  }

  if (resistance && resistanceSource) {
    const lnR = resistance.map((r) => (r !== null && r > 0 ? Math.log(r) : null));

    let slope = NOMINAL_LN_R_SLOPE;
    let intercept = NOMINAL_LN_R_INTERCEPT;
    let strategy: LpStrategy = conductanceField && !resistanceField ? "conductance" : "resistance-nominal";

    if (baseline) {
      const fx: number[] = [];
      const fy: number[] = [];
      for (let i = 0; i < rows.length; i += 1) {
        const b = baseline[i];
        const v = lnR[i];
        if (b !== null && v !== null) {
          fx.push(b);
          fy.push(v);
        }
      }
      const fit = fitLinear(fx, fy);
      if (fit) {
        slope = fit.slope;
        intercept = fit.intercept;
        strategy = "resistance+baseline";
        notes.push(
          `LP from "${resistanceSource}" using this recording's own fit ` +
            `(ln R = ${slope.toFixed(4)}*LP + ${intercept.toFixed(4)})`
        );
      }
    }
    if (strategy !== "resistance+baseline") {
      notes.push(
        `LP from "${resistanceSource}" using the nominal calibration; ` +
          "no Baseline column to fit against"
      );
    }

    const lp = lnR.map((v) => (v === null ? null : (v - intercept) / slope));
    return {
      lp,
      strategy,
      resolutionLp: observedResolution(lp.filter((v): v is number => v !== null)),
      sourceColumn: resistanceSource,
      notes
    };
  }

  // --- 5. the baseline staircase on its own -------------------------------------------------
  if (baseline && baselineField) {
    notes.push(
      `LP read directly from "${baselineField}"; this column is quantised to ` +
        `${LP_DEVICE_STEP} LP, so fine deflections are not recoverable`
    );
    return {
      lp: baseline,
      strategy: "baseline",
      resolutionLp: Math.max(
        observedResolution(baseline.filter((v): v is number => v !== null)),
        LP_DEVICE_STEP
      ),
      sourceColumn: baselineField,
      notes
    };
  }

  throw new Error(
    "The CSV export needs a charge channel: Data(16 bit)+Baseline, Resistance, Conductance, or Baseline."
  );
}

export async function parseGsrCsv(file: File): Promise<ParsedGsrResult> {
  return new Promise((resolve, reject) => {
    Papa.parse<Record<string, unknown>>(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
        try {
          if (results.errors.length) {
            reject(new Error(results.errors[0].message));
            return;
          }

          const fields = results.meta.fields ?? [];
          if (!fields.length) {
            reject(new Error("CSV export is missing a header row."));
            return;
          }

          const timeField = fields.find((field) => normalizeField(field).includes("time"));
          if (!timeField) {
            reject(new Error("CSV export must contain a time column."));
            return;
          }

          const rows = results.data.filter((row) =>
            Object.values(row).some((value) => value !== null && String(value ?? "").trim() !== "")
          );
          if (!rows.length) {
            reject(new Error("The CSV export does not contain any samples."));
            return;
          }

          const rawTimes = columnValues(rows, timeField);
          const finiteTimes = rawTimes.filter((v): v is number => v !== null);
          if (!finiteTimes.length) {
            reject(new Error("The time column does not contain numeric values."));
            return;
          }

          const resolution = resolveLp(fields, rows);
          const timeScale = determineTimeScaling(timeField, finiteTimes);

          const baselineField = findColumn(fields, "baseline");
          const resistanceField = findColumn(fields, "resistance", "ohm");
          const baseline = baselineField ? columnValues(rows, baselineField) : null;
          const resistance = resistanceField ? columnValues(rows, resistanceField) : null;

          const samples: ParsedGsrSample[] = [];
          for (let i = 0; i < rows.length; i += 1) {
            const rawTime = rawTimes[i];
            const lp = resolution.lp[i];
            if (rawTime === null || lp === null || !Number.isFinite(lp)) {
              continue;
            }
            const sample: ParsedGsrSample = {
              timeSec: rawTime / timeScale,
              lp,
              value: lp,
              rawValue: lp
            };
            const b = baseline?.[i];
            if (b !== null && b !== undefined) sample.baseline = b;
            const r = resistance?.[i];
            if (r !== null && r !== undefined) sample.resistance = r;
            samples.push(sample);
          }

          if (!samples.length) {
            reject(new Error("No usable samples were found in the CSV export."));
            return;
          }

          samples.sort((a, b) => a.timeSec - b.timeSec);

          let minValue = Infinity;
          let maxValue = -Infinity;
          for (const sample of samples) {
            if (sample.lp < minValue) minValue = sample.lp;
            if (sample.lp > maxValue) maxValue = sample.lp;
          }

          const startTimeSec = samples[0].timeSec;
          const endTimeSec = samples[samples.length - 1].timeSec;
          const diffs: number[] = [];
          for (let i = 1; i < samples.length; i += 1) {
            diffs.push(samples[i].timeSec - samples[i - 1].timeSec);
          }
          const avgDiff = diffs.length
            ? diffs.reduce((acc, value) => acc + value, 0) / diffs.length
            : null;

          resolve({
            samples,
            samplingRateHz: avgDiff && avgDiff > 0 ? 1 / avgDiff : null,
            sourceColumn: resolution.sourceColumn,
            strategy: resolution.strategy,
            resolutionLp: resolution.resolutionLp,
            quantised: resolution.resolutionLp >= LP_DEVICE_STEP / 2,
            notes: resolution.notes,
            minValue,
            maxValue,
            startTimeSec,
            endTimeSec,
            hasBaseline: Boolean(baselineField),
            hasResistance: Boolean(resistanceField),
            baselineColumn: baselineField,
            resistanceColumn: resistanceField
          });
        } catch (err) {
          reject(err instanceof Error ? err : new Error(String(err)));
        }
      },
      error: (error) => {
        reject(error);
      }
    });
  });
}
