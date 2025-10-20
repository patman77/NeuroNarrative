import Papa from "papaparse";

export interface ParsedGsrSample {
  timeSec: number;
  value: number;
  rawValue: number;
  baseline?: number;
  resistance?: number;
}

export interface ParsedGsrResult {
  samples: ParsedGsrSample[];
  samplingRateHz: number | null;
  sourceColumn: string;
  scalingFactor: number;
  minValue: number;
  maxValue: number;
  startTimeSec: number;
  endTimeSec: number;
  hasBaseline: boolean;
  hasResistance: boolean;
  baselineColumn?: string;
  resistanceColumn?: string;
}

const FIELD_PRIORITY: Array<{ match: RegExp; bonus: number }> = [
  { match: /baseline/, bonus: 0.4 },
  { match: /resistance/, bonus: 0.25 },
  { match: /conductance/, bonus: 0.2 },
  { match: /data/, bonus: 0.15 },
  { match: /value/, bonus: 0.1 }
];

const NUMERIC_REGEX = /-?\d+(?:[\.,]\d+)?/;

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
  const normalized = text.replace(",", ".");
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function chooseValueField(fields: string[], rows: Record<string, unknown>[]): {
  field: string;
  divisor: number;
  min: number;
  max: number;
} {
  const candidates = fields.filter((field) => {
    const norm = normalizeField(field);
    return FIELD_PRIORITY.some(({ match }) => match.test(norm));
  });

  const fallbackNumeric = fields.filter((field) => {
    const norm = normalizeField(field);
    return norm !== "" && !norm.includes("time");
  });

  const fieldsToConsider = candidates.length ? candidates : fallbackNumeric;

  if (!fieldsToConsider.length) {
    throw new Error("The CSV export does not contain any numeric signal columns.");
  }

  let best = {
    field: fieldsToConsider[0],
    divisor: 1,
    min: Number.POSITIVE_INFINITY,
    max: Number.NEGATIVE_INFINITY,
    score: Number.NEGATIVE_INFINITY
  };

  for (const field of fieldsToConsider) {
    const values: number[] = [];
    for (const row of rows) {
      const numeric = sanitizeNumber(row[field]);
      if (numeric !== null) {
        values.push(numeric);
      }
    }

    if (!values.length) {
      continue;
    }

    const sorted = [...values].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];

    let divisor = 1;
    let adjustedMedian = median;
    let iterations = 0;
    while (adjustedMedian > 20 && iterations < 6) {
      adjustedMedian /= 10;
      divisor *= 10;
      iterations += 1;
    }

    const scaledValues = values.map((value) => value / divisor);
    const withinRange = scaledValues.filter((value) => value >= 0.5 && value <= 10).length;
    const spread = Math.max(...scaledValues) - Math.min(...scaledValues);
    const norm = normalizeField(field);
    const priorityBonus = FIELD_PRIORITY.find(({ match }) => match.test(norm))?.bonus ?? 0.05;

    const rangeScore = withinRange / scaledValues.length;
    const variabilityScore = spread > 0 ? Math.min(spread / 5, 1) : -0.2;
    const score = rangeScore * 0.6 + variabilityScore * 0.25 + priorityBonus;

    if (score > best.score) {
      best = {
        field,
        divisor,
        min: Math.min(...scaledValues),
        max: Math.max(...scaledValues),
        score
      };
    }
  }

  if (best.score === Number.NEGATIVE_INFINITY) {
    throw new Error("Unable to infer a usable signal column from the CSV export.");
  }

  return {
    field: best.field,
    divisor: best.divisor,
    min: best.min,
    max: best.max
  };
}

function determineTimeScaling(timeField: string, timeValues: number[]): number {
  if (!timeValues.length) {
    return 1;
  }
  const normalizedField = normalizeField(timeField);
  if (normalizedField.includes("ms") || normalizedField.includes("msec")) {
    return 1000;
  }
  const diffs: number[] = [];
  for (let i = 1; i < timeValues.length; i += 1) {
    const diff = timeValues[i] - timeValues[i - 1];
    if (Number.isFinite(diff)) {
      diffs.push(Math.abs(diff));
    }
  }
  if (!diffs.length) {
    return 1;
  }
  const avgDiff = diffs.reduce((acc, value) => acc + value, 0) / diffs.length;
  return avgDiff >= 1 ? 1000 : 1;
}

export async function parseGsrCsv(file: File): Promise<ParsedGsrResult> {
  return new Promise((resolve, reject) => {
    Papa.parse<Record<string, unknown>>(file, {
      header: true,
      skipEmptyLines: true,
      complete: (results) => {
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

        const timeValues: number[] = [];
        for (const row of rows) {
          const numeric = sanitizeNumber(row[timeField]);
          if (numeric !== null) {
            timeValues.push(numeric);
          }
        }

        if (!timeValues.length) {
          reject(new Error("The time column does not contain numeric values."));
          return;
        }

        // Find baseline and resistance columns
        const baselineField = fields.find((field) => normalizeField(field).includes("baseline"));
        const resistanceField = fields.find((field) => normalizeField(field).includes("resistance"));

        const { field: valueField, divisor, min, max } = chooseValueField(fields, rows);
        const timeScale = determineTimeScaling(timeField, timeValues);

        const samples: ParsedGsrSample[] = [];
        for (const row of rows) {
          const rawTime = sanitizeNumber(row[timeField]);
          const rawValue = sanitizeNumber(row[valueField]);
          if (rawTime === null || rawValue === null) {
            continue;
          }
          const timeSec = rawTime / timeScale;
          const scaledValue = rawValue / divisor;
          
          const sample: ParsedGsrSample = {
            timeSec,
            value: scaledValue,
            rawValue: rawValue
          };

          // Add baseline and resistance if available
          if (baselineField) {
            const baselineValue = sanitizeNumber(row[baselineField]);
            if (baselineValue !== null) {
              sample.baseline = baselineValue;
            }
          }

          if (resistanceField) {
            const resistanceValue = sanitizeNumber(row[resistanceField]);
            if (resistanceValue !== null) {
              sample.resistance = resistanceValue;
            }
          }

          samples.push(sample);
        }

        if (!samples.length) {
          reject(new Error("No usable samples were found in the CSV export."));
          return;
        }

        samples.sort((a, b) => a.timeSec - b.timeSec);

        const startTimeSec = samples[0].timeSec;
        const endTimeSec = samples[samples.length - 1].timeSec;
        const diffs: number[] = [];
        for (let i = 1; i < samples.length; i += 1) {
          diffs.push(samples[i].timeSec - samples[i - 1].timeSec);
        }
        const avgDiff = diffs.length
          ? diffs.reduce((acc, value) => acc + value, 0) / diffs.length
          : null;
        const samplingRateHz = avgDiff && avgDiff > 0 ? 1 / avgDiff : null;

        resolve({
          samples,
          samplingRateHz,
          sourceColumn: valueField,
          scalingFactor: divisor,
          minValue: min,
          maxValue: max,
          startTimeSec,
          endTimeSec,
          hasBaseline: Boolean(baselineField),
          hasResistance: Boolean(resistanceField),
          baselineColumn: baselineField,
          resistanceColumn: resistanceField
        });
      },
      error: (error) => {
        reject(error);
      }
    });
  });
}
