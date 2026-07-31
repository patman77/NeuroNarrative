import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import type { ParsedGsrResult, ParsedGsrSample } from "../utils/gsrParser";
import { logEvent } from "../utils/logger";
import type { SummarizedEvent } from "../App";

interface SignalPreviewProps {
  data: ParsedGsrResult;
  audioUrl: string | null;
  audioFileName?: string | null;
  csvFileName?: string | null;
  events?: SummarizedEvent[];
  seekRef?: React.MutableRefObject<((time: number) => void) | null>;
}

const DISPLAY_MIN = 1;
const DISPLAY_MAX = 6.5;

// Detail-chart zoom. 100% = the original hardcoded density of 80 px per second.
const DEFAULT_PX_PER_SECOND = 80;
const MIN_PX_PER_SECOND = 0.05; // lets a multi-hour recording still fit the container
const MAX_PX_PER_SECOND = 800;
const ZOOM_STEP = 1.5;
const DETAIL_LEFT_PADDING = 60;
const DETAIL_RIGHT_PADDING = 10;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) {
    return "00:00";
  }
  const safe = Math.max(0, seconds);
  const mins = Math.floor(safe / 60);
  const secs = Math.floor(safe % 60);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

interface ChartPoint {
  x: number;
  y: number;
}

// Smooth curve through the measurement points using monotone cubic interpolation
// (Fritsch–Carlson, the same scheme as d3's curveMonotoneX). The GSR readings are
// quantized, so straight segments between samples render as a jagged staircase once
// zoomed in; a monotone spline rounds the corners without overshooting — the curve
// still passes exactly through every measurement point and never invents extrema.
function monotonePath(points: ChartPoint[]): string {
  if (!points.length) {
    return "";
  }
  if (points.length < 3) {
    return points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
      .join(" ");
  }
  const n = points.length;
  const dx: number[] = new Array(n - 1);
  const slope: number[] = new Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    dx[i] = points[i + 1].x - points[i].x;
    slope[i] = (points[i + 1].y - points[i].y) / (dx[i] || 1e-9);
  }
  const tangent: number[] = new Array(n);
  tangent[0] = slope[0];
  tangent[n - 1] = slope[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (slope[i - 1] * slope[i] <= 0) {
      // Local extremum: flat tangent keeps the curve inside the data.
      tangent[i] = 0;
    } else {
      const w1 = 2 * dx[i] + dx[i - 1];
      const w2 = dx[i] + 2 * dx[i - 1];
      tangent[i] = (w1 + w2) / (w1 / slope[i - 1] + w2 / slope[i]);
    }
  }
  const commands = [`M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`];
  for (let i = 0; i < n - 1; i++) {
    const third = dx[i] / 3;
    const c1x = points[i].x + third;
    const c1y = points[i].y + tangent[i] * third;
    const c2x = points[i + 1].x - third;
    const c2y = points[i + 1].y - tangent[i + 1] * third;
    commands.push(
      `C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ` +
        `${points[i + 1].x.toFixed(2)} ${points[i + 1].y.toFixed(2)}`
    );
  }
  return commands.join(" ");
}

// A zoomed-out chart puts many samples on every pixel; emitting them all builds a
// megabytes-long path for detail nobody can see. Collapse each pixel column to its
// min and max sample (in time order), which keeps spikes visible. Below the
// threshold the samples pass through untouched, so zoomed-in views keep every point.
function decimateToColumns(
  samples: ParsedGsrSample[],
  startTime: number,
  duration: number,
  columns: number
): ParsedGsrSample[] {
  const cols = Math.max(1, Math.floor(columns));
  if (samples.length <= cols * 2) {
    return samples;
  }
  const columnOf = (timeSec: number) =>
    Math.min(cols - 1, Math.floor(((timeSec - startTime) / duration) * cols));

  const kept: ParsedGsrSample[] = [];
  let current = columnOf(samples[0].timeSec);
  let lowest = samples[0];
  let highest = samples[0];

  const flush = () => {
    const [first, second] =
      lowest.timeSec <= highest.timeSec ? [lowest, highest] : [highest, lowest];
    kept.push(first);
    if (second !== first) {
      kept.push(second);
    }
  };

  for (const sample of samples) {
    const column = columnOf(sample.timeSec);
    if (column !== current) {
      flush();
      current = column;
      lowest = sample;
      highest = sample;
      continue;
    }
    if (sample.value < lowest.value) lowest = sample;
    if (sample.value > highest.value) highest = sample;
  }
  flush();
  return kept;
}

function useInterpolatedValue(samples: ParsedGsrSample[], timeSec: number): number {
  return useMemo(() => {
    if (!samples.length) {
      return 0;
    }
    if (timeSec <= samples[0].timeSec) {
      return samples[0].value;
    }
    if (timeSec >= samples[samples.length - 1].timeSec) {
      return samples[samples.length - 1].value;
    }

    let left = 0;
    let right = samples.length - 1;
    while (left <= right) {
      const mid = Math.floor((left + right) / 2);
      if (samples[mid].timeSec === timeSec) {
        return samples[mid].value;
      }
      if (samples[mid].timeSec < timeSec) {
        left = mid + 1;
      } else {
        right = mid - 1;
      }
    }

    const lowerIndex = Math.max(0, right);
    const upperIndex = Math.min(samples.length - 1, left);
    const lower = samples[lowerIndex];
    const upper = samples[upperIndex];
    if (upper.timeSec === lower.timeSec) {
      return lower.value;
    }
    const ratio = (timeSec - lower.timeSec) / (upper.timeSec - lower.timeSec);
    return lower.value + (upper.value - lower.value) * clamp(ratio, 0, 1);
  }, [samples, timeSec]);
}

function useInterpolatedSample(samples: ParsedGsrSample[], timeSec: number): ParsedGsrSample | null {
  return useMemo(() => {
    if (!samples.length) {
      return null;
    }
    if (timeSec <= samples[0].timeSec) {
      return samples[0];
    }
    if (timeSec >= samples[samples.length - 1].timeSec) {
      return samples[samples.length - 1];
    }

    let left = 0;
    let right = samples.length - 1;
    while (left <= right) {
      const mid = Math.floor((left + right) / 2);
      if (samples[mid].timeSec === timeSec) {
        return samples[mid];
      }
      if (samples[mid].timeSec < timeSec) {
        left = mid + 1;
      } else {
        right = mid - 1;
      }
    }

    const lowerIndex = Math.max(0, right);
    const upperIndex = Math.min(samples.length - 1, left);
    const lower = samples[lowerIndex];
    const upper = samples[upperIndex];
    if (upper.timeSec === lower.timeSec) {
      return lower;
    }
    const ratio = (timeSec - lower.timeSec) / (upper.timeSec - lower.timeSec);
    const clampedRatio = clamp(ratio, 0, 1);

    return {
      timeSec,
      value: lower.value + (upper.value - lower.value) * clampedRatio,
      rawValue: lower.rawValue + (upper.rawValue - lower.rawValue) * clampedRatio,
      // Baseline is a step function (changes only on normalize), so use lower sample's baseline
      baseline: lower.baseline,
      // Resistance is continuous, so interpolate it
      resistance: lower.resistance !== undefined && upper.resistance !== undefined
        ? lower.resistance + (upper.resistance - lower.resistance) * clampedRatio
        : lower.resistance ?? upper.resistance
    };
  }, [samples, timeSec]);
}

// Calculate gauge position from baseline and resistance
// Baseline represents the normalized center position (1-6.5 range)
// Resistance decrease → needle moves RIGHT (higher gauge value)
// Resistance increase → needle moves LEFT (lower gauge value)
function calculateGaugePosition(
  sample: ParsedGsrSample,
  samples: ParsedGsrSample[],
  hasBaseline: boolean,
  hasResistance: boolean
): number {
  // If we have baseline, use it as the primary gauge position
  if (hasBaseline && sample.baseline !== undefined) {
    if (hasResistance && sample.resistance !== undefined) {
      // Find the reference resistance for the current baseline period
      // This is the resistance value when the current baseline was first established
      let referenceResistance: number | undefined = undefined;

      // Look through samples up to current time to find the most recent baseline change point
      for (let i = 0; i < samples.length; i++) {
        const s = samples[i];

        // Only look at samples up to current time
        if (s.timeSec > sample.timeSec) {
          break;
        }

        // Check if this sample has a valid baseline and resistance
        if (s.baseline === undefined || s.resistance === undefined) {
          continue;
        }

        // Check if this is the start of a baseline period matching current baseline
        if (s.baseline === sample.baseline) {
          // Is this the start of a new baseline period?
          if (i === 0 || samples[i - 1].baseline !== sample.baseline) {
            // Found baseline change point - use resistance at this point as reference
            referenceResistance = s.resistance;
            // Don't break - keep looking for more recent changes (in case baseline oscillates)
          } else if (referenceResistance === undefined) {
            // We're in the middle of a baseline period and haven't found the start yet
            // This can happen if earlier samples are missing baseline data
            referenceResistance = s.resistance;
          }
        }
      }

      // If we found a reference resistance, calculate the needle position
      if (referenceResistance !== undefined) {
        // Calculate resistance change in kOhm
        const resistanceDelta = sample.resistance - referenceResistance;

        // Convert resistance change to gauge units
        // Negative scale: decrease resistance → move right (increase gauge value)
        // Scale factor: 1 kOhm change ≈ 0.5 gauge units
        const RESISTANCE_TO_GAUGE_SCALE = -0.5;
        const gaugeAdjustment = resistanceDelta * RESISTANCE_TO_GAUGE_SCALE;

        // Calculate final position and clamp to valid range
        const position = sample.baseline + gaugeAdjustment;
        return clamp(position, DISPLAY_MIN, DISPLAY_MAX);
      }
    }

    // If no resistance data or couldn't find reference, just use baseline
    return clamp(sample.baseline, DISPLAY_MIN, DISPLAY_MAX);
  }

  // Fallback to the original value
  return sample.value;
}

function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end = polarToCartesian(cx, cy, r, startAngle);
  const largeArcFlag = endAngle - startAngle <= Math.PI ? "0" : "1";
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`;
}

function polarToCartesian(cx: number, cy: number, r: number, angle: number) {
  return {
    x: cx + r * Math.cos(angle),
    y: cy + r * Math.sin(angle)
  };
}

interface GaugeProps {
  value: number;
  min: number;
  max: number;
  baseline?: number;
}

function Gauge({ value, min, max, baseline }: GaugeProps) {
  const width = 320;
  const height = 200;
  const cx = width / 2;
  const cy = height * 0.9;
  const radius = Math.min(cx, cy) - 20;
  const clamped = clamp(value, min, max);
  const ratio = (clamped - min) / (max - min || 1);
  const startAngle = Math.PI;
  const endAngle = 2 * Math.PI;  // Fixed: use 2π for top semicircle instead of 0 for bottom semicircle
  const pointerAngle = startAngle + (endAngle - startAngle) * ratio;
  const pointerInner = polarToCartesian(cx, cy, radius * 0.2, pointerAngle);
  const pointerTip = polarToCartesian(cx, cy, radius, pointerAngle);

  // Calculate baseline marker position if provided
  let baselineAngle: number | null = null;
  if (baseline !== undefined) {
    const clampedBaseline = clamp(baseline, min, max);
    const baselineRatio = (clampedBaseline - min) / (max - min || 1);
    baselineAngle = startAngle + (endAngle - startAngle) * baselineRatio;
  }

  const ticks = Array.from({ length: 6 }, (_, index) => {
    const tickRatio = index / 5;
    const angle = startAngle + (endAngle - startAngle) * tickRatio;
    const inner = polarToCartesian(cx, cy, radius - 10, angle);
    const outer = polarToCartesian(cx, cy, radius, angle);
    const label = (min + (max - min) * tickRatio).toFixed(1);
    const labelPoint = polarToCartesian(cx, cy, radius + 16, angle);
    return { inner, outer, label, labelPoint };
  });

  // Create gauge arc segments with baseline marker
  const gaugeSegments = [];
  if (baselineAngle !== null) {
    // Create segments with gap at baseline position
    const gapSize = 0.05; // Size of the gap in radians
    const beforeBaselineStart = startAngle;
    const beforeBaselineEnd = baselineAngle - gapSize;
    const afterBaselineStart = baselineAngle + gapSize;
    const afterBaselineEnd = endAngle;

    if (beforeBaselineEnd > beforeBaselineStart) {
      gaugeSegments.push({
        path: describeArc(cx, cy, radius, beforeBaselineStart, beforeBaselineEnd),
        key: 'before-baseline'
      });
    }
    if (afterBaselineEnd > afterBaselineStart) {
      gaugeSegments.push({
        path: describeArc(cx, cy, radius, afterBaselineStart, afterBaselineEnd),
        key: 'after-baseline'
      });
    }
  } else {
    // No baseline, draw full arc
    gaugeSegments.push({
      path: describeArc(cx, cy, radius, startAngle, endAngle),
      key: 'full-arc'
    });
  }

  // Calculate gradient coordinates to span the entire gauge arc (left to right)
  const gradientStart = polarToCartesian(cx, cy, radius, startAngle);
  const gradientEnd = polarToCartesian(cx, cy, radius, endAngle);

  return (
    <svg className="gauge" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Current GSR ${clamped.toFixed(2)}`}>
      <defs>
        <linearGradient
          id="gaugeGradient"
          x1={gradientStart.x}
          y1={gradientStart.y}
          x2={gradientEnd.x}
          y2={gradientEnd.y}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#1f9bcf" />
          <stop offset="100%" stopColor="#26c2a6" />
        </linearGradient>
      </defs>
      {gaugeSegments.map((segment) => (
        <path key={segment.key} d={segment.path} fill="none" stroke="url(#gaugeGradient)" strokeWidth={14} />
      ))}
      {baselineAngle !== null && (
        <g>
          {/* Baseline marker line */}
          <line
            x1={polarToCartesian(cx, cy, radius - 18, baselineAngle).x}
            y1={polarToCartesian(cx, cy, radius - 18, baselineAngle).y}
            x2={polarToCartesian(cx, cy, radius + 5, baselineAngle).x}
            y2={polarToCartesian(cx, cy, radius + 5, baselineAngle).y}
            stroke="#ff9800"
            strokeWidth={3}
            strokeLinecap="round"
          />
        </g>
      )}
      {ticks.map((tick) => (
        <g key={tick.label}>
          <line x1={tick.inner.x} y1={tick.inner.y} x2={tick.outer.x} y2={tick.outer.y} stroke="#0f3a47" strokeWidth={2} />
          <text x={tick.labelPoint.x} y={tick.labelPoint.y} textAnchor="middle" dominantBaseline="middle" className="gauge-tick">
            {tick.label}
          </text>
        </g>
      ))}
      <circle cx={cx} cy={cy} r={10} fill="#0f3a47" />
      <line x1={pointerInner.x} y1={pointerInner.y} x2={pointerTip.x} y2={pointerTip.y} stroke="#f44336" strokeWidth={4} strokeLinecap="round" />
      <text x={cx} y={height * 0.4} textAnchor="middle" className="gauge-value">
        {clamped.toFixed(2)}
      </text>
    </svg>
  );
}

interface SignalChartProps {
  samples: ParsedGsrSample[];
  currentTime: number;
  currentValue: number;
  min: number;
  max: number;
  pxPerSecond: number;
  events?: SummarizedEvent[];
}

function SignalChart({ samples, currentTime, currentValue, min, max, pxPerSecond, events }: SignalChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartHeight = 220;
  const topPadding = 16;
  const bottomPadding = 40;
  const leftPadding = DETAIL_LEFT_PADDING;
  const rightPadding = DETAIL_RIGHT_PADDING;
  const usableHeight = chartHeight - topPadding - bottomPadding;
  const startTime = samples[0].timeSec;
  const endTime = samples[samples.length - 1].timeSec;
  const duration = Math.max(endTime - startTime, 0.001);
  const width = Math.max(200, Math.round(duration * pxPerSecond));
  const totalWidth = width + leftPadding + rightPadding;

  const path = useMemo(() => {
    if (!samples.length) {
      return "";
    }
    const points = decimateToColumns(samples, startTime, duration, width).map((sample) => ({
      x: leftPadding + ((sample.timeSec - startTime) / duration) * width,
      y: topPadding + (1 - clamp((sample.value - min) / (max - min || 1), 0, 1)) * usableHeight,
    }));
    return monotonePath(points);
  }, [samples, duration, width, min, max, startTime, usableHeight, topPadding, leftPadding]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const indicatorPosition = leftPadding + ((currentTime - startTime) / duration) * width;
    if (!Number.isFinite(indicatorPosition)) {
      return;
    }
    const safePosition = clamp(indicatorPosition, leftPadding, width + leftPadding);
    const padding = container.clientWidth * 0.4;
    const target = Math.max(0, safePosition - padding);
    container.scrollTo({ left: target, behavior: "auto" });
  }, [currentTime, duration, startTime, width, leftPadding]);

  const indicatorX = clamp(leftPadding + ((currentTime - startTime) / duration) * width, leftPadding, width + leftPadding);
  const indicatorYTop = topPadding;
  const indicatorYBottom = chartHeight - bottomPadding;

  const currentRatio = (currentValue - min) / (max - min || 1);
  const currentY = topPadding + (1 - clamp(currentRatio, 0, 1)) * usableHeight;

  // Generate Y-axis ticks
  const yTicks = useMemo(() => {
    const numTicks = 5;
    return Array.from({ length: numTicks }, (_, i) => {
      const ratio = i / (numTicks - 1);
      const value = min + (max - min) * ratio;
      const y = topPadding + (1 - ratio) * usableHeight;
      return { y, value: value.toFixed(1) };
    });
  }, [min, max, topPadding, usableHeight]);

  // Generate X-axis ticks — pick interval so labels never overlap at any zoom level
  const xTicks = useMemo(() => {
    const minPxPerLabel = 55;
    const minIntervalSec = minPxPerLabel / (width / duration);
    const niceIntervals = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200];
    const tickInterval = niceIntervals.find((i) => i >= minIntervalSec) ?? niceIntervals[niceIntervals.length - 1];
    const ticks: { x: number; label: string }[] = [];
    for (let t = 0; t <= duration; t += tickInterval) {
      const x = leftPadding + (t / duration) * width;
      ticks.push({ x, label: formatTime(t) });
    }
    return ticks;
  }, [duration, width, leftPadding]);

  // Filter events within the chart range
  const visibleEvents = useMemo(() => {
    if (!events?.length) return [];
    return events.filter((ev) => ev.time_sec >= startTime && ev.time_sec <= endTime);
  }, [events, startTime, endTime]);

  return (
    <div className="signal-chart" ref={containerRef}>
      <svg width={totalWidth} height={chartHeight} role="img" aria-label="GSR timeline">
        <rect x={0} y={0} width={totalWidth} height={chartHeight} fill="#f7fafc" />

        {/* Y-axis */}
        <line x1={leftPadding} y1={topPadding} x2={leftPadding} y2={chartHeight - bottomPadding} stroke="#333" strokeWidth={1} />
        {yTicks.map((tick, i) => (
          <g key={i}>
            <line x1={leftPadding - 5} y1={tick.y} x2={leftPadding} y2={tick.y} stroke="#333" strokeWidth={1} />
            <text x={leftPadding - 10} y={tick.y} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="#333">
              {tick.value}
            </text>
            <line x1={leftPadding} y1={tick.y} x2={width + leftPadding} y2={tick.y} stroke="#e0e0e0" strokeWidth={1} strokeDasharray="2 2" />
          </g>
        ))}

        {/* X-axis */}
        <line x1={leftPadding} y1={chartHeight - bottomPadding} x2={width + leftPadding} y2={chartHeight - bottomPadding} stroke="#333" strokeWidth={1} />
        {xTicks.map((tick, i) => (
          <g key={i}>
            <line x1={tick.x} y1={chartHeight - bottomPadding} x2={tick.x} y2={chartHeight - bottomPadding + 5} stroke="#333" strokeWidth={1} />
            <text x={tick.x} y={chartHeight - bottomPadding + 18} textAnchor="middle" fontSize="10" fill="#333">
              {tick.label}
            </text>
          </g>
        ))}

        {/* Signal path */}
        <path d={path} fill="none" stroke="#0f6f8f" strokeWidth={2} strokeLinecap="round" />

        {/* Event bubbles — vertical dashed lines with triangle markers */}
        {visibleEvents.map((ev) => {
          const ex = leftPadding + ((ev.time_sec - startTime) / duration) * width;
          const triangleSize = 6;
          const tx = ex;
          const ty = topPadding;
          return (
            <g key={ev.event_id}>
              <line
                x1={ex}
                y1={topPadding}
                x2={ex}
                y2={chartHeight - bottomPadding}
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="4 3"
                opacity={0.85}
              />
              {/* Triangle pointing down: tip at top of chart area */}
              <polygon
                points={`${tx},${ty} ${tx - triangleSize},${ty - triangleSize * 1.5} ${tx + triangleSize},${ty - triangleSize * 1.5}`}
                fill="#f59e0b"
                opacity={0.9}
              />
              <title>{`Event ${ev.event_id}: ${ev.rule} @ ${ev.time_sec.toFixed(1)}s`}</title>
            </g>
          );
        })}

        {/* Current position indicator */}
        <line x1={indicatorX} y1={indicatorYTop} x2={indicatorX} y2={indicatorYBottom} stroke="#f44336" strokeWidth={2} strokeDasharray="6 6" />
        <circle cx={indicatorX} cy={currentY} r={5} fill="#f44336" stroke="#fff" strokeWidth={2} />
      </svg>
    </div>
  );
}

interface OverviewChartProps {
  samples: ParsedGsrSample[];
  currentTime: number;
  min: number;
  max: number;
  onSeek: (time: number) => void;
  events?: SummarizedEvent[];
}

function OverviewChart({ samples, currentTime, min, max, onSeek, events }: OverviewChartProps) {
  const chartWidth = 920;
  const chartHeight = 120;
  const topPadding = 10;
  const bottomPadding = 30;
  const leftPadding = 60;
  const rightPadding = 10;
  const usableHeight = chartHeight - topPadding - bottomPadding;
  const usableWidth = chartWidth - leftPadding - rightPadding;
  const startTime = samples[0]?.timeSec ?? 0;
  const endTime = samples[samples.length - 1]?.timeSec ?? 0;
  const duration = Math.max(endTime - startTime, 0.001);

  const path = useMemo(() => {
    if (!samples.length) {
      return "";
    }
    const points = decimateToColumns(samples, startTime, duration, usableWidth).map((sample) => ({
      x: leftPadding + ((sample.timeSec - startTime) / duration) * usableWidth,
      y: topPadding + (1 - clamp((sample.value - min) / (max - min || 1), 0, 1)) * usableHeight,
    }));
    return monotonePath(points);
  }, [samples, duration, usableWidth, min, max, startTime, usableHeight, topPadding, leftPadding]);

  const indicatorX = clamp(leftPadding + ((currentTime - startTime) / duration) * usableWidth, leftPadding, usableWidth + leftPadding);

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const relativeX = clamp(x - leftPadding, 0, usableWidth);
    const clickedTime = startTime + (relativeX / usableWidth) * duration;
    onSeek(clickedTime);
  };

  // Generate Y-axis ticks
  const yTicks = useMemo(() => {
    const numTicks = 3;
    return Array.from({ length: numTicks }, (_, i) => {
      const ratio = i / (numTicks - 1);
      const value = min + (max - min) * ratio;
      const y = topPadding + (1 - ratio) * usableHeight;
      return { y, value: value.toFixed(1) };
    });
  }, [min, max, topPadding, usableHeight]);

  // Generate X-axis ticks — pick interval so labels never overlap
  const xTicks = useMemo(() => {
    const minPxPerLabel = 55; // minimum pixels between tick labels
    const maxTicks = Math.max(2, Math.floor(usableWidth / minPxPerLabel));
    const minIntervalSec = duration / maxTicks;
    const niceIntervals = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200];
    const tickInterval = niceIntervals.find((i) => i >= minIntervalSec) ?? niceIntervals[niceIntervals.length - 1];
    const ticks: { x: number; label: string }[] = [];
    for (let t = 0; t <= duration; t += tickInterval) {
      const x = leftPadding + (t / duration) * usableWidth;
      ticks.push({ x, label: formatTime(t) });
    }
    return ticks;
  }, [duration, usableWidth, leftPadding]);

  // Filter events within the chart range
  const visibleEvents = useMemo(() => {
    if (!events?.length) return [];
    return events.filter((ev) => ev.time_sec >= startTime && ev.time_sec <= endTime);
  }, [events, startTime, endTime]);

  return (
    <div className="overview-chart">
      <svg
        width={chartWidth}
        height={chartHeight}
        role="img"
        aria-label="Full GSR overview - click to navigate"
        onClick={handleClick}
        style={{ cursor: 'pointer' }}
      >
        <rect x={0} y={0} width={chartWidth} height={chartHeight} fill="#f0f4f7" />

        {/* Y-axis */}
        <line x1={leftPadding} y1={topPadding} x2={leftPadding} y2={chartHeight - bottomPadding} stroke="#333" strokeWidth={1} />
        {yTicks.map((tick, i) => (
          <g key={i}>
            <line x1={leftPadding - 5} y1={tick.y} x2={leftPadding} y2={tick.y} stroke="#333" strokeWidth={1} />
            <text x={leftPadding - 10} y={tick.y} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="#333">
              {tick.value}
            </text>
            <line x1={leftPadding} y1={tick.y} x2={usableWidth + leftPadding} y2={tick.y} stroke="#d0d0d0" strokeWidth={1} strokeDasharray="2 2" />
          </g>
        ))}

        {/* X-axis */}
        <line x1={leftPadding} y1={chartHeight - bottomPadding} x2={usableWidth + leftPadding} y2={chartHeight - bottomPadding} stroke="#333" strokeWidth={1} />
        {xTicks.map((tick, i) => (
          <g key={i}>
            <line x1={tick.x} y1={chartHeight - bottomPadding} x2={tick.x} y2={chartHeight - bottomPadding + 5} stroke="#333" strokeWidth={1} />
            <text x={tick.x} y={chartHeight - bottomPadding + 18} textAnchor="middle" fontSize="10" fill="#333">
              {tick.label}
            </text>
          </g>
        ))}

        {/* Signal path */}
        <path d={path} fill="none" stroke="#0f6f8f" strokeWidth={1.5} strokeLinecap="round" />

        {/* Event bubbles — vertical lines + diamond markers */}
        {visibleEvents.map((ev) => {
          const ex = clamp(leftPadding + ((ev.time_sec - startTime) / duration) * usableWidth, leftPadding, usableWidth + leftPadding);
          const diamondSize = 5;
          const dy = topPadding + diamondSize;
          return (
            <g key={ev.event_id}>
              <line
                x1={ex}
                y1={topPadding}
                x2={ex}
                y2={chartHeight - bottomPadding}
                stroke="#f59e0b"
                strokeWidth={2}
                opacity={0.8}
              />
              {/* Diamond shape */}
              <polygon
                points={`${ex},${dy - diamondSize} ${ex + diamondSize},${dy} ${ex},${dy + diamondSize} ${ex - diamondSize},${dy}`}
                fill="#f59e0b"
                opacity={0.9}
              />
              <title>{`Event ${ev.event_id}: ${ev.rule} @ ${ev.time_sec.toFixed(1)}s`}</title>
            </g>
          );
        })}

        {/* Current position indicator bar */}
        <line
          x1={indicatorX}
          y1={topPadding}
          x2={indicatorX}
          y2={chartHeight - bottomPadding}
          stroke="#f44336"
          strokeWidth={3}
          opacity={0.7}
        />
      </svg>
    </div>
  );
}

export function SignalPreview({ data, audioUrl, audioFileName, csvFileName, events, seekRef }: SignalPreviewProps) {
  const waveformRef = useRef<HTMLDivElement | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const detailWrapRef = useRef<HTMLDivElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioDuration, setAudioDuration] = useState<number | null>(null);
  const [pxPerSecond, setPxPerSecond] = useState(DEFAULT_PX_PER_SECOND);
  const [fitHeight, setFitHeight] = useState(false);

  const gaugeMin = DISPLAY_MIN;
  const gaugeMax = DISPLAY_MAX;
  const chartMin = Math.min(gaugeMin, data.minValue);
  const chartMax = Math.max(gaugeMax, data.maxValue);
  const clampedRangeMin = clamp(data.minValue, gaugeMin, gaugeMax);
  const clampedRangeMax = clamp(data.maxValue, gaugeMin, gaugeMax);

  const effectiveDuration = audioDuration ?? data.endTimeSec - data.startTimeSec;

  const currentSample = useInterpolatedSample(data.samples, currentTime + data.startTimeSec);
  const currentValue = useInterpolatedValue(data.samples, currentTime + data.startTimeSec);

  // Calculate the gauge position using baseline and resistance if available
  const gaugeValue = currentSample
    ? calculateGaugePosition(currentSample, data.samples, data.hasBaseline, data.hasResistance)
    : currentValue;

  const displayValue = clamp(gaugeValue, gaugeMin, gaugeMax);
  const currentBaseline = currentSample?.baseline;

  useEffect(() => {
    if (!audioUrl || !waveformRef.current) {
      // No audio — just reset state and log
      wsRef.current?.destroy();
      wsRef.current = null;
      setCurrentTime(0);
      setIsPlaying(false);
      setAudioDuration(null);
      logEvent("Preview data refreshed", {
        csvColumn: data.sourceColumn,
        sampleCount: data.samples.length,
        audioAvailable: Boolean(audioUrl)
      });
      return;
    }

    // Destroy previous WaveSurfer instance before creating a new one
    wsRef.current?.destroy();
    setCurrentTime(0);
    setIsPlaying(false);
    setAudioDuration(null);

    const ws = WaveSurfer.create({
      container: waveformRef.current,
      waveColor: "rgba(56, 189, 248, 0.6)",
      progressColor: "rgba(59, 130, 246, 0.9)",
      cursorColor: "#f44336",
      height: 64,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      url: audioUrl,
    });

    ws.on("ready", () => {
      setAudioDuration(ws.getDuration());
      logEvent("Audio metadata loaded", { duration: ws.getDuration() });
    });
    ws.on("play", () => {
      setIsPlaying(true);
      logEvent("Audio playback started");
    });
    ws.on("pause", () => {
      setIsPlaying(false);
      logEvent("Audio playback paused", { currentTime: ws.getCurrentTime() });
    });
    ws.on("finish", () => {
      setIsPlaying(false);
      setCurrentTime(ws.getDuration());
      logEvent("Audio playback ended");
    });
    ws.on("audioprocess", (time: number) => {
      setCurrentTime(time);
    });
    ws.on("seeking", (time: number) => {
      setCurrentTime(time);
    });

    wsRef.current = ws;

    logEvent("Preview data refreshed", {
      csvColumn: data.sourceColumn,
      sampleCount: data.samples.length,
      audioAvailable: true
    });

    return () => {
      ws.destroy();
      wsRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl, data.sourceColumn, data.startTimeSec, data.endTimeSec]);

  const seekTo = (time: number) => {
    const ws = wsRef.current;
    if (!ws) return;
    const relativeTime = time - data.startTimeSec;
    const clampedTime = clamp(relativeTime, 0, effectiveDuration);
    ws.seekTo(clampedTime / effectiveDuration);
    setCurrentTime(clampedTime);
    logEvent("Seeked to time", { time: clampedTime });
  };

  // Expose seekTo via seekRef
  useEffect(() => {
    if (seekRef) seekRef.current = seekTo;
  });

  const togglePlayback = () => {
    const ws = wsRef.current;
    if (!ws) return;
    if (isPlaying) {
      ws.pause();
      logEvent("Playback toggle", { action: "pause", currentTime: ws.getCurrentTime() });
    } else {
      ws.play();
      logEvent("Playback toggle", { action: "play" });
    }
  };

  const jumpToBeginning = () => {
    seekTo(data.startTimeSec);
  };

  const jumpToEnd = () => {
    seekTo(data.endTimeSec);
  };

  const skipForward = () => {
    seekTo(currentTime + data.startTimeSec + 10);
  };

  const skipBackward = () => {
    seekTo(currentTime + data.startTimeSec - 10);
  };

  const jumpToTime = (seconds: number) => {
    seekTo(seconds + data.startTimeSec);
  };

  const jumpToQuarter = () => {
    const quarterTime = effectiveDuration * 0.25;
    jumpToTime(quarterTime);
  };

  const jumpToHalf = () => {
    const halfTime = effectiveDuration * 0.5;
    jumpToTime(halfTime);
  };

  const jumpToThreeQuarters = () => {
    const threeQuarterTime = effectiveDuration * 0.75;
    jumpToTime(threeQuarterTime);
  };

  // --- Detail-chart zoom -------------------------------------------------
  // Horizontal zoom is px/s on the time axis; "fit height" swaps the fixed
  // gauge-based y-range for the data's own range so the trace fills the chart.

  const dataDuration = Math.max(data.endTimeSec - data.startTimeSec, 0.001);

  const fitWidthPxPerSecond = () => {
    const available =
      (detailWrapRef.current?.clientWidth ?? 780) - DETAIL_LEFT_PADDING - DETAIL_RIGHT_PADDING;
    return clamp(available / dataDuration, MIN_PX_PER_SECOND, MAX_PX_PER_SECOND);
  };

  const zoomIn = () =>
    setPxPerSecond((p) => clamp(p * ZOOM_STEP, MIN_PX_PER_SECOND, MAX_PX_PER_SECOND));
  const zoomOut = () =>
    setPxPerSecond((p) => clamp(p / ZOOM_STEP, MIN_PX_PER_SECOND, MAX_PX_PER_SECOND));
  const zoomOriginal = () => {
    setPxPerSecond(DEFAULT_PX_PER_SECOND);
    setFitHeight(false);
  };
  const fitToWidth = () => setPxPerSecond(fitWidthPxPerSecond());
  const fitToHeight = () => setFitHeight((f) => !f);
  const fitPage = () => {
    setPxPerSecond(fitWidthPxPerSecond());
    setFitHeight(true);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      switch (e.key) {
        case "+":
        case "=":
          zoomIn();
          break;
        case "-":
        case "_":
          zoomOut();
          break;
        case "0":
          zoomOriginal();
          break;
        case "w":
        case "W":
          fitToWidth();
          break;
        case "h":
        case "H":
          fitToHeight();
          break;
        case "f":
        case "F":
          fitPage();
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Fit-height uses the data's own range with a small margin; a flat signal
  // gets a fixed band so the divide never degenerates.
  const yMargin = Math.max((data.maxValue - data.minValue) * 0.05, 0.05);
  const detailMin = fitHeight ? data.minValue - yMargin : chartMin;
  const detailMax = fitHeight ? data.maxValue + yMargin : chartMax;
  const zoomPercent = Math.round((pxPerSecond / DEFAULT_PX_PER_SECOND) * 100);

  return (
    <section className="signal-preview card">
      <div className="signal-preview-header">
        <div>
          <h2>Session preview</h2>
          <p className="muted">
            Showing column <strong>{data.sourceColumn}</strong> ({data.samples.length} samples @
            {" "}
            {data.samplingRateHz ? `${data.samplingRateHz.toFixed(1)} Hz` : "unknown rate"})
          </p>
          {csvFileName && <p className="muted small">CSV: {csvFileName}</p>}
          {audioFileName && <p className="muted small">Audio: {audioFileName}</p>}
        </div>
        {audioUrl ? (
          <div className="waveform-container">
            <div ref={waveformRef} className="waveform" />
            <div className="playback-controls">
              <button type="button" onClick={togglePlayback} className="playback-button">
                {isPlaying ? "Pause" : "Play"}
              </button>
              <span className="playback-time">
                {formatTime(currentTime)} / {formatTime(effectiveDuration ?? 0)}
              </span>
            </div>
          </div>
        ) : (
          <p className="muted">Add a WAV file to enable playback.</p>
        )}
      </div>

      {audioUrl && (
        <div className="navigation-controls">
          <button type="button" onClick={jumpToBeginning} className="nav-button" title="Jump to beginning">
            Start
          </button>
          <button type="button" onClick={skipBackward} className="nav-button" title="Skip backward 10s">
            -10s
          </button>
          <button type="button" onClick={skipForward} className="nav-button" title="Skip forward 10s">
            +10s
          </button>
          <button type="button" onClick={jumpToQuarter} className="nav-button" title="Jump to 25%">
            25%
          </button>
          <button type="button" onClick={jumpToHalf} className="nav-button" title="Jump to 50%">
            50%
          </button>
          <button type="button" onClick={jumpToThreeQuarters} className="nav-button" title="Jump to 75%">
            75%
          </button>
          <button type="button" onClick={jumpToEnd} className="nav-button" title="Jump to end">
            End
          </button>
        </div>
      )}

      <div className="gauge-panel">
        <Gauge value={displayValue} min={gaugeMin} max={gaugeMax} baseline={currentBaseline} />
        <div className="gauge-metrics">
          <div>
            <span className="metric-label">Current</span>
            <span className="metric-value">{displayValue.toFixed(2)}</span>
          </div>
          <div>
            <span className="metric-label">Range</span>
            <span className="metric-value">
              {clampedRangeMin.toFixed(1)} – {clampedRangeMax.toFixed(1)}
            </span>
          </div>
          {currentBaseline !== undefined && (
            <div>
              <span className="metric-label">Baseline</span>
              <span className="metric-value">{currentBaseline.toFixed(2)}</span>
            </div>
          )}
          {currentSample?.resistance !== undefined && (
            <div>
              <span className="metric-label">Resistance</span>
              <span className="metric-value">{currentSample.resistance.toFixed(2)} kΩ</span>
            </div>
          )}
          {data.scalingFactor !== 1 && (
            <div>
              <span className="metric-label">Scale</span>
              <span className="metric-value">÷ {data.scalingFactor}</span>
            </div>
          )}
        </div>
      </div>

      <div className="overview-section">
        <h3 className="section-title">Full Recording Overview</h3>
        <p className="section-description">
          Click anywhere on the timeline below to jump to that point. The red line shows your current position.
          {events && events.length > 0 && ` Orange markers show the ${events.length} detected event(s).`}
        </p>
        <OverviewChart
          samples={data.samples}
          currentTime={currentTime + data.startTimeSec}
          min={chartMin}
          max={chartMax}
          onSeek={seekTo}
          events={events}
        />
      </div>

      <div className="detail-chart-section">
        <h3 className="section-title">Detail View (Zoomed)</h3>
        <p className="section-description">
          This view shows a zoomed-in portion of the signal that follows the current playback position.
        </p>
        <div className="zoom-controls">
          <button type="button" onClick={zoomOut} className="nav-button zoom-button" title="Zoom out (-)">
            −
          </button>
          <span className="zoom-level" title="Zoom level relative to the default 80 px/s">
            {zoomPercent}%
          </span>
          <button type="button" onClick={zoomIn} className="nav-button zoom-button" title="Zoom in (+)">
            +
          </button>
          <button type="button" onClick={zoomOriginal} className="nav-button" title="Original size (0)">
            1:1
          </button>
          <button type="button" onClick={fitToWidth} className="nav-button" title="Fit whole recording to width (W)">
            Fit width
          </button>
          <button
            type="button"
            onClick={fitToHeight}
            className={`nav-button${fitHeight ? " nav-button-active" : ""}`}
            aria-pressed={fitHeight}
            title="Fit signal range to height (H)"
          >
            Fit height
          </button>
          <button type="button" onClick={fitPage} className="nav-button" title="Fit entire recording (F)">
            Fit page
          </button>
        </div>
        <div ref={detailWrapRef}>
          <SignalChart
            samples={data.samples}
            currentTime={currentTime + data.startTimeSec}
            currentValue={currentValue}
            min={detailMin}
            max={detailMax}
            pxPerSecond={pxPerSecond}
            events={events}
          />
        </div>
      </div>

    </section>
  );
}
