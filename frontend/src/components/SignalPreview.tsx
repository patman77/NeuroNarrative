import { useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import type { ParsedGsrResult, ParsedGsrSample } from "../utils/gsrParser";
import { logEvent } from "../utils/logger";
import type { SummarizedEvent } from "../App";
import type { HoverTarget, PlotSelection, TimelineMarker } from "../App";
import { animateScroll } from "../utils/smoothScroll";
import { KIND_BADGE, kindColor } from "../utils/phenomenaVisuals";

interface SignalPreviewProps {
  data: ParsedGsrResult;
  audioUrl: string | null;
  audioFileName?: string | null;
  csvFileName?: string | null;
  events?: SummarizedEvent[];
  markers?: TimelineMarker[];
  hover?: HoverTarget | null;
  onHover?: (hover: HoverTarget | null) => void;
  selection?: PlotSelection | null;
  seekRef?: React.MutableRefObject<((time: number) => void) | null>;
  /** Published so the page can scroll the charts into view without guessing at their offset. */
  plotSectionRef?: React.MutableRefObject<HTMLElement | null>;
  /** How the card is built, so the stacked layout can pin the charts without reordering it.
      `offsetPx` is the setup above them (gauge, metrics, waveform); `heightPx` is the charts. */
  onPlotMetrics?: (metrics: { offsetPx: number; heightPx: number }) => void;
  /** Seconds of speech either side of a marker in its tooltip. The excerpt itself is built in
      App, which holds the transcript; this component only owns the control. */
  transcriptWindowSec?: number;
  maxTranscriptWindowSec?: number;
  onTranscriptWindowChange?: (seconds: number) => void;
}

/** The moment or range the other panels are pointing at, drawn on both charts.
 *
 * `pinned` distinguishes a click from a hover: a hover is a light touch that follows the pointer,
 * a click is a decision that has to stay legible after the pointer has moved on. */
export interface PlotHighlight {
  timeSec: number;
  endSec?: number;
  pinned: boolean;
}

/** Violet, deliberately outside the phenomenon palette in `phenomenaVisuals.ts` and away from
    the red playhead: it marks *where you are pointing*, which is neither a phenomenon nor the
    playback position. */
const HIGHLIGHT_COLOUR = "#7c3aed";

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

    const lp = lower.lp + (upper.lp - lower.lp) * clampedRatio;

    return {
      timeSec,
      lp,
      value: lp,
      rawValue: lp,
      // Baseline is a step function (it only moves when the device re-centres its window), so
      // take the lower sample's rather than interpolating across a step.
      baseline: lower.baseline,
      resistance: lower.resistance !== undefined && upper.resistance !== undefined
        ? lower.resistance + (upper.resistance - lower.resistance) * clampedRatio
        : lower.resistance ?? upper.resistance
    };
  }, [samples, timeSec]);
}

/**
 * The gauge shows the charge level (LP), which is what the parser now resolves directly.
 *
 * This used to reconstruct a needle position by walking every prior sample to find where the
 * current Baseline step began, then offsetting by `resistanceDelta * -0.5` — a linear kOhm→gauge
 * factor that cannot be right, since resistance is exponential in LP and the same 0.4 LP movement
 * spans ~1.9 kOhm low in the range and ~28 kOhm high in it. It was also O(n) per sample. The
 * resolver computes true continuous LP once, so none of that is needed.
 */
function calculateGaugePosition(sample: ParsedGsrSample): number {
  return clamp(sample.lp, DISPLAY_MIN, DISPLAY_MAX);
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

interface HighlightLayerProps {
  highlight?: PlotHighlight | null;
  /** Time (in the same absolute seconds as the samples) to an x coordinate, already clamped. */
  toX: (timeSec: number) => number;
  top: number;
  bottom: number;
  /** Recording start, so labels read the same as the x-axis ticks. */
  originSec: number;
  compact?: boolean;
}

/** The shaded span, drawn *behind* the trace so it never obscures the signal it describes. */
function HighlightBand({ highlight, toX, top, bottom, originSec, compact }: HighlightLayerProps) {
  if (!highlight || highlight.endSec == null || highlight.endSec <= highlight.timeSec) return null;
  const x1 = toX(highlight.timeSec);
  const x2 = toX(highlight.endSec);
  const width = Math.max(1, x2 - x1);
  const label = `${formatTime(highlight.timeSec - originSec)}–${formatTime(highlight.endSec - originSec)}`;
  return (
    <g pointerEvents="none">
      <rect
        x={x1}
        y={top}
        width={width}
        height={bottom - top}
        fill={HIGHLIGHT_COLOUR}
        opacity={highlight.pinned ? 0.16 : 0.11}
      />
      {/* Both edges drawn: the band alone leaves the exact end ambiguous once it is clipped by
          the viewport, and "from when to when" is the whole point of showing it. */}
      <line x1={x1} y1={top} x2={x1} y2={bottom} stroke={HIGHLIGHT_COLOUR} strokeWidth={1.5} opacity={0.75} />
      <line x1={x2} y1={top} x2={x2} y2={bottom} stroke={HIGHLIGHT_COLOUR} strokeWidth={1.5} opacity={0.75} />
      {/* Anchored to the left edge rather than centred: in the zoomed detail chart a section is
          usually wider than the viewport, and a centred label sits off screen. `compact` is the
          overview, where the top strip already carries the marker diamonds. */}
      {!compact && width > 58 && (
        <text x={x1 + 6} y={top + 11} fontSize="10" fontWeight={600} fill={HIGHLIGHT_COLOUR}>
          {label}
        </text>
      )}
    </g>
  );
}

/* --- Speech bubbles --------------------------------------------------------
 *
 * A dashed vertical line says *that* something was detected; the bubble says *what*. They appear
 * for what is being pointed at — every filtered phenomenon inside a hovered narrative section, or
 * the single one under the pointer in the list — and never for the whole catalogue, which on a
 * 54-minute session would be several hundred labels and no signal left to read.
 */

const BUBBLE_HEIGHT = 15;
const BUBBLE_LANE_GAP = 3;
/** Horizontal clearance between two bubbles in the same lane. Below ~4 px they read as one pill. */
const BUBBLE_X_GAP = 4;
const BUBBLE_CHAR_PX = 6;
const BUBBLE_PAD_PX = 10;
/** Enough to describe a busy section; past this the labels are the noise, not the signal. */
const MAX_BUBBLES = 60;

interface BubbleItem {
  id: string;
  timeSec: number;
  kind: string;
  amplitudeA?: number | null;
}

interface PlacedBubble extends BubbleItem {
  x: number;
  y: number;
  width: number;
  text: string;
  /** Where the phenomenon actually is, which is not where the bubble ended up. */
  anchorX: number;
}

function bubbleText(item: BubbleItem, compact: boolean): string {
  const badge = KIND_BADGE[item.kind] ?? item.kind;
  // The overview holds the whole session in 860 px, so magnitudes there would collide into a
  // single wall of pills. The kind alone still answers "what is in this stretch".
  if (compact || item.amplitudeA == null) return badge;
  return `${badge} ${item.amplitudeA.toFixed(1)}A`;
}

/**
 * Lay bubbles out in lanes so none overlaps another.
 *
 * Greedy first-fit by time: each bubble goes in the topmost lane whose last bubble has already
 * ended, so a sparse stretch stays on one line and a burst stacks. Anything that would need a
 * lane past `maxLanes` is dropped and counted rather than drawn over its neighbour — an
 * unreadable pile of overlapping labels is worse than an honest "+7 more".
 */
function packBubbles(
  items: BubbleItem[],
  options: {
    toX: (timeSec: number) => number;
    minX: number;
    maxX: number;
    top: number;
    maxLanes: number;
    compact: boolean;
  }
): { placed: PlacedBubble[]; dropped: number } {
  const { toX, minX, maxX, top, maxLanes, compact } = options;
  const laneEnds: number[] = [];
  const placed: PlacedBubble[] = [];
  let dropped = 0;

  for (const item of [...items].sort((a, b) => a.timeSec - b.timeSec)) {
    const text = bubbleText(item, compact);
    const width = Math.max(20, text.length * BUBBLE_CHAR_PX + BUBBLE_PAD_PX);
    const anchorX = toX(item.timeSec);
    // Centred on the phenomenon, then pushed inside the plot area — a bubble half off the left
    // edge is a bubble you cannot read.
    const x = clamp(anchorX - width / 2, minX, Math.max(minX, maxX - width));

    let lane = laneEnds.findIndex((end) => x >= end + BUBBLE_X_GAP);
    if (lane === -1) {
      if (laneEnds.length >= maxLanes) {
        dropped += 1;
        continue;
      }
      lane = laneEnds.length;
      laneEnds.push(0);
    }
    laneEnds[lane] = x + width;
    placed.push({
      ...item,
      text,
      width,
      anchorX,
      x,
      y: top + lane * (BUBBLE_HEIGHT + BUBBLE_LANE_GAP)
    });
  }

  return { placed, dropped };
}

interface BubbleLayerProps {
  items: BubbleItem[];
  toX: (timeSec: number) => number;
  minX: number;
  maxX: number;
  top: number;
  maxLanes: number;
  compact?: boolean;
}

function BubbleLayer({ items, toX, minX, maxX, top, maxLanes, compact }: BubbleLayerProps) {
  const { placed, dropped } = useMemo(
    () => packBubbles(items.slice(0, MAX_BUBBLES), { toX, minX, maxX, top, maxLanes, compact: Boolean(compact) }),
    // `toX` is rebuilt every render; the geometry it closes over is in the other dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, minX, maxX, top, maxLanes, compact]
  );
  if (!items.length) return null;
  const hidden = dropped + Math.max(0, items.length - MAX_BUBBLES);

  return (
    <g className="plot-bubbles" pointerEvents="none">
      {placed.map((bubble) => {
        const colour = kindColor(bubble.kind);
        return (
          <g key={bubble.id}>
            {/* The bubble was pushed sideways to avoid its neighbours, so say which line it
                belongs to. Without this a shifted label points at the wrong phenomenon. */}
            <line
              x1={bubble.x + bubble.width / 2}
              y1={bubble.y + BUBBLE_HEIGHT}
              x2={bubble.anchorX}
              y2={bubble.y + BUBBLE_HEIGHT + BUBBLE_LANE_GAP + 2}
              stroke={colour}
              strokeWidth={1}
              opacity={0.65}
            />
            <rect
              x={bubble.x}
              y={bubble.y}
              width={bubble.width}
              height={BUBBLE_HEIGHT}
              rx={4}
              fill={colour}
              opacity={0.95}
            />
            <text
              x={bubble.x + bubble.width / 2}
              y={bubble.y + BUBBLE_HEIGHT / 2}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize="9.5"
              fontWeight={600}
              fill="#ffffff"
            >
              {bubble.text}
            </text>
          </g>
        );
      })}
      {hidden > 0 && (
        <text x={maxX} y={top + BUBBLE_HEIGHT / 2} textAnchor="end" dominantBaseline="central" fontSize="9.5" fill={HIGHLIGHT_COLOUR}>
          +{hidden} more
        </text>
      )}
    </g>
  );
}

/** Says what the bubbles are, in the two words it takes. Without it a row of coloured pills
    appearing over the trace is just an unexplained change.
 *
 * Always rendered, and merely hidden when nothing is being pointed at: appearing and
 * disappearing moved the charts 12 px down and back every time the pointer entered a row, and a
 * plot that jumps under the cursor is worse than a line of permanently reserved space. */
function BubbleLegend({ text, compact }: { text: string | null; compact?: boolean }) {
  return (
    <p className="plot-legend" aria-hidden={text ? undefined : true} data-active={text ? "yes" : "no"}>
      <span className="plot-legend-pill">{compact ? "kind" : "kind · size"}</span>
      <span>
        labels {text ?? ""}, coloured to match the filter chips
        {compact && " — magnitudes are in the detail view below"}.
      </span>
    </p>
  );
}

/** The pointed-at moment, drawn on top of everything so it is findable at any zoom. */
function HighlightCursor({ highlight, toX, top, bottom }: HighlightLayerProps) {
  if (!highlight) return null;
  const x = toX(highlight.timeSec);
  return (
    <g pointerEvents="none">
      <line
        x1={x}
        y1={top}
        x2={x}
        y2={bottom}
        stroke={HIGHLIGHT_COLOUR}
        strokeWidth={highlight.pinned ? 2.5 : 2}
        opacity={0.95}
      />
      {/* A downward wedge at the top edge. The dashed phenomenon lines all look alike at a
          glance; this says which one you are on without having to compare dash weights. */}
      <polygon points={`${x - 7},${top - 10} ${x + 7},${top - 10} ${x},${top}`} fill={HIGHLIGHT_COLOUR} />
    </g>
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
  markers?: TimelineMarker[];
  onHover?: (hover: HoverTarget | null) => void;
  highlight?: PlotHighlight | null;
  bubbles?: BubbleItem[];
}

function SignalChart({
  samples,
  currentTime,
  currentValue,
  min,
  max,
  pxPerSecond,
  events,
  markers,
  onHover,
  highlight,
  bubbles
}: SignalChartProps) {
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

  // Markers come from the phenomenon catalogue and are already filtered by the kind chips, so
  // toggling a chip removes its vertical markings here. Falls back to the legacy event list when
  // no analysis has produced phenomena yet.
  const visibleMarkers = useMemo<TimelineMarker[]>(() => {
    // `markers === undefined` means no catalogue; an empty array means everything is filtered
    // out and nothing should be drawn.
    const source: TimelineMarker[] = markers
      ? markers
      : (events ?? []).map((ev) => ({
          id: ev.event_id,
          timeSec: ev.time_sec,
          kind: "A",
          label: `${ev.rule} @ ${ev.time_sec.toFixed(1)}s`
        }));
    return source.filter((m) => m.timeSec >= startTime && m.timeSec <= endTime);
  }, [markers, events, startTime, endTime]);

  const highlightTime = highlight?.timeSec ?? null;
  const toX = (t: number) =>
    clamp(leftPadding + ((t - startTime) / duration) * width, leftPadding, width + leftPadding);

  const bubbleItems = useMemo(
    () => (bubbles ?? []).filter((b) => b.timeSec >= startTime && b.timeSec <= endTime),
    [bubbles, startTime, endTime]
  );

  return (
    <div className="signal-chart" ref={containerRef}>
      <svg width={totalWidth} height={chartHeight} role="img" aria-label="GSR timeline">
        <rect x={0} y={0} width={totalWidth} height={chartHeight} fill="#f7fafc" />

        {/* Behind the trace and the markers: the span is context, not content. */}
        <HighlightBand
          highlight={highlight}
          toX={toX}
          top={topPadding}
          bottom={chartHeight - bottomPadding}
          originSec={startTime}
        />

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

        {/* Vertical markings, one per phenomenon, coloured by kind so they read against the
            filter chips. Hovering one drives the other two panels. */}
        {visibleMarkers.map((marker) => {
          const ex = leftPadding + ((marker.timeSec - startTime) / duration) * width;
          const colour = kindColor(marker.kind);
          const active = highlightTime != null && Math.abs(highlightTime - marker.timeSec) < 0.75;
          return (
            <g
              key={marker.id}
              onMouseEnter={() => onHover?.({ timeSec: marker.timeSec, source: "plot" })}
              style={{ cursor: "pointer" }}
            >
              {/* Invisible wide hit area: a 2px dashed line is very hard to hover. */}
              <rect x={ex - 6} y={topPadding - 12} width={12} height={chartHeight - bottomPadding - topPadding + 12} fill="transparent" />
              <line
                x1={ex}
                y1={topPadding}
                x2={ex}
                y2={chartHeight - bottomPadding}
                stroke={colour}
                strokeWidth={active ? 3 : 2}
                strokeDasharray="4 3"
                opacity={active ? 1 : 0.8}
              />
              <polygon
                points={`${ex},${topPadding} ${ex - 6},${topPadding - 9} ${ex + 6},${topPadding - 9}`}
                fill={colour}
                opacity={active ? 1 : 0.9}
              />
              <title>{marker.label}</title>
            </g>
          );
        })}

        {/* Current position indicator */}
        <line x1={indicatorX} y1={indicatorYTop} x2={indicatorX} y2={indicatorYBottom} stroke="#f44336" strokeWidth={2} strokeDasharray="6 6" />
        <circle cx={indicatorX} cy={currentY} r={5} fill="#f44336" stroke="#fff" strokeWidth={2} />

        {/* Below the band's own range label when there is a band, so the two do not collide. */}
        <BubbleLayer
          items={bubbleItems}
          toX={toX}
          minX={leftPadding}
          maxX={width + leftPadding}
          top={topPadding + (highlight?.endSec != null ? 16 : 2)}
          maxLanes={5}
        />

        <HighlightCursor
          highlight={highlight}
          toX={toX}
          top={topPadding}
          bottom={chartHeight - bottomPadding}
          originSec={startTime}
        />
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
  markers?: TimelineMarker[];
  onHover?: (hover: HoverTarget | null) => void;
  highlight?: PlotHighlight | null;
  bubbles?: BubbleItem[];
}

function OverviewChart({
  samples,
  currentTime,
  min,
  max,
  onSeek,
  events,
  markers,
  onHover,
  highlight,
  bubbles
}: OverviewChartProps) {
  // The overview was a fixed 920 px SVG. Once the page stopped being capped at 1200 px that left
  // dead space on both sides of a wide window, and in the split layout it overflowed its column
  // and the end of the recording was simply clipped off. It has to follow its container.
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [chartWidth, setChartWidth] = useState(920);
  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const measure = () => {
      // The whole session has to stay legible, so there is a floor; the container scrolls if the
      // window is narrower than that.
      const style = getComputedStyle(node);
      const inner =
        node.clientWidth - parseFloat(style.paddingLeft || "0") - parseFloat(style.paddingRight || "0");
      setChartWidth(Math.max(600, Math.round(inner)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
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

  const visibleMarkers = useMemo<TimelineMarker[]>(() => {
    // `markers === undefined` means no catalogue; an empty array means everything is filtered
    // out and nothing should be drawn.
    const source: TimelineMarker[] = markers
      ? markers
      : (events ?? []).map((ev) => ({
          id: ev.event_id,
          timeSec: ev.time_sec,
          kind: "A",
          label: `${ev.rule} @ ${ev.time_sec.toFixed(1)}s`
        }));
    return source.filter((m) => m.timeSec >= startTime && m.timeSec <= endTime);
  }, [markers, events, startTime, endTime]);

  const toX = (t: number) =>
    clamp(
      leftPadding + ((t - startTime) / duration) * usableWidth,
      leftPadding,
      usableWidth + leftPadding
    );

  const bubbleItems = useMemo(
    () => (bubbles ?? []).filter((b) => b.timeSec >= startTime && b.timeSec <= endTime),
    [bubbles, startTime, endTime]
  );

  return (
    <div className="overview-chart" ref={wrapRef}>
      <svg
        width={chartWidth}
        height={chartHeight}
        role="img"
        aria-label="Full GSR overview - click to navigate"
        onClick={handleClick}
        style={{ cursor: 'pointer' }}
      >
        <rect x={0} y={0} width={chartWidth} height={chartHeight} fill="#f0f4f7" />

        {/* The overview is where a narrative section's span is actually legible: the whole
            session is on screen, so the shaded band shows the proportion of the sitting it
            covers rather than just a stretch wider than the viewport. */}
        <HighlightBand
          highlight={highlight}
          toX={toX}
          top={topPadding}
          bottom={chartHeight - bottomPadding}
          originSec={startTime}
          compact
        />

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

        {/* Markings, coloured by kind and filtered by the chips in the phenomena panel. */}
        {visibleMarkers.map((marker) => {
          const ex = clamp(
            leftPadding + ((marker.timeSec - startTime) / duration) * usableWidth,
            leftPadding,
            usableWidth + leftPadding
          );
          const diamondSize = 5;
          const dy = topPadding + diamondSize;
          const colour = kindColor(marker.kind);
          return (
            <g
              key={marker.id}
              onMouseEnter={() => onHover?.({ timeSec: marker.timeSec, source: "overview" })}
              style={{ cursor: "pointer" }}
            >
              <rect x={ex - 5} y={topPadding} width={10} height={chartHeight - bottomPadding - topPadding} fill="transparent" />
              <line x1={ex} y1={topPadding} x2={ex} y2={chartHeight - bottomPadding} stroke={colour} strokeWidth={2} opacity={0.8} />
              <polygon
                points={`${ex},${dy - diamondSize} ${ex + diamondSize},${dy} ${ex},${dy + diamondSize} ${ex - diamondSize},${dy}`}
                fill={colour}
                opacity={0.9}
              />
              <title>{marker.label}</title>
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

        {/* Clear of the marker diamonds, which sit at the very top of the plot area. Only two
            lanes fit in a 120 px chart, which is why the overview labels carry the kind alone. */}
        <BubbleLayer
          items={bubbleItems}
          toX={toX}
          minX={leftPadding}
          maxX={usableWidth + leftPadding}
          top={topPadding + 13}
          maxLanes={2}
          compact
        />

        <HighlightCursor
          highlight={highlight}
          toX={toX}
          top={topPadding}
          bottom={chartHeight - bottomPadding}
          originSec={startTime}
        />
      </svg>
    </div>
  );
}

export function SignalPreview({
  data,
  audioUrl,
  audioFileName,
  csvFileName,
  events,
  markers,
  hover,
  onHover,
  selection,
  seekRef,
  plotSectionRef,
  onPlotMetrics,
  transcriptWindowSec,
  maxTranscriptWindowSec = 60,
  onTranscriptWindowChange
}: SignalPreviewProps) {
  const cardRef = useRef<HTMLElement | null>(null);
  const plotStackRef = useRef<HTMLDivElement | null>(null);
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
    ? calculateGaugePosition(currentSample)
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

  // A hover anywhere but the detail chart itself travels the detail chart to that moment — the
  // phenomena list, the narrative, and the overview, where a marker you point at is often far
  // outside the zoomed window. Hovers whose source is `plot` are the detail chart's own markers
  // and are ignored, or it would drag itself out from under the pointer.
  useEffect(() => {
    if (!hover || hover.source === "plot") return;
    // The scroll container is the chart itself (`.signal-chart` carries overflow-x: auto);
    // the wrapper around it does not scroll, so scrolling that is a silent no-op.
    const wrap = detailWrapRef.current?.querySelector<HTMLElement>(".signal-chart") ?? null;
    if (!wrap) return;
    const relative = hover.timeSec - data.startTimeSec;
    const x = DETAIL_LEFT_PADDING + relative * pxPerSecond;

    // Already comfortably on screen: leave it alone. Re-centring something you can see is motion
    // for its own sake, and at a shallow zoom every marker in the overview would be a jump. The
    // margin keeps a moment sitting right against an edge from counting as visible.
    const margin = Math.min(wrap.clientWidth * 0.15, 120);
    if (x >= wrap.scrollLeft + margin && x <= wrap.scrollLeft + wrap.clientWidth - margin) return;

    const target = x - wrap.clientWidth / 2;
    const clamped = Math.max(0, Math.min(target, wrap.scrollWidth - wrap.clientWidth));
    // The shared easing: accelerates, decelerates, capped at 2 s however far the jump.
    return animateScroll(wrap, { left: clamped });
  }, [hover, pxPerSecond, data.startTimeSec]);

  // A live hover wins over the last click: the pointer is the more immediate intent, and the
  // click stays marked again as soon as the pointer leaves.
  const highlight = useMemo<PlotHighlight | null>(() => {
    if (hover) return { timeSec: hover.timeSec, endSec: hover.endSec, pinned: false };
    if (selection) return { timeSec: selection.timeSec, endSec: selection.endSec, pinned: true };
    return null;
  }, [hover, selection]);

  // Measure the card so the stacked layout can pin the charts alone while leaving the card in its
  // natural order — gauge and waveform first, as they have always been. Both numbers move: the
  // waveform appears when audio loads, the file-name lines wrap, the zoom controls reflow.
  useEffect(() => {
    if (!onPlotMetrics) return;
    const card = cardRef.current;
    const stack = plotStackRef.current;
    if (!card || !stack) return;
    const measure = () => {
      const offsetPx = stack.getBoundingClientRect().top - card.getBoundingClientRect().top;
      onPlotMetrics({ offsetPx: Math.max(0, Math.round(offsetPx)), heightPx: Math.round(stack.offsetHeight) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(card);
    observer.observe(stack);
    return () => observer.disconnect();
  }, [onPlotMetrics]);

  // What the bubbles label. `markers` has already been filtered by the kind chips, so a hidden
  // kind is silent here too — the labels and the vertical markings always agree about what is
  // being shown. Pointing at a span labels everything inside it; pointing at a single moment
  // labels the one phenomenon it refers to, and nothing when it refers to none (a click in the
  // legacy event list lands on a time with no phenomenon at all).
  const bubbleSource = useMemo<BubbleItem[]>(() => {
    if (!highlight || !markers?.length) return [];
    const toItem = (m: TimelineMarker): BubbleItem => ({
      id: m.id,
      timeSec: m.timeSec,
      kind: m.kind,
      amplitudeA: m.amplitudeA
    });

    if (highlight.endSec != null && highlight.endSec > highlight.timeSec) {
      return markers
        .filter((m) => m.timeSec >= highlight.timeSec && m.timeSec < highlight.endSec!)
        .map(toItem);
    }

    let best: TimelineMarker | null = null;
    let bestDistance = Infinity;
    for (const marker of markers) {
      const distance = Math.abs(marker.timeSec - highlight.timeSec);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = marker;
      }
    }
    // Tight, because a hovered row hands over that phenomenon's exact start. Anything looser
    // would label a neighbour and quietly claim it was what you pointed at.
    return best && bestDistance <= 0.5 ? [toItem(best)] : [];
  }, [highlight, markers]);

  const bubbleLegend =
    bubbleSource.length === 0
      ? null
      : bubbleSource.length === 1
      ? "the phenomenon you are pointing at"
      : `the ${bubbleSource.length} phenomena in the span you are pointing at`;

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
    <section className="signal-preview card" ref={cardRef}>
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
          <div>
            <span className="metric-label">Channel</span>
            <span className="metric-value" title={data.notes.join("\n")}>
              {data.sourceColumn}
              {data.quantised ? " (0.05 steps)" : ""}
            </span>
          </div>
        </div>
      </div>

      {/* The two charts are one unit. The stacked layout pins *this* while the setup above it —
          gauge, metrics, waveform, file names — scrolls away, which it does by offsetting the
          sticky card rather than by reordering anything: the card reads top to bottom the way it
          always has. See `--plot-offset` in styles.css. */}
      <div className="plot-stack" ref={plotStackRef}>
      <div className="overview-section" ref={(node) => { if (plotSectionRef) plotSectionRef.current = node; }}>
        <h3 className="section-title">Full Recording Overview</h3>
        <p className="section-description">
          Click anywhere on the timeline below to jump to that point. The red line shows your current position.
          {events && events.length > 0 && ` Orange markers show the ${events.length} detected event(s).`}
        </p>
        <BubbleLegend text={bubbleLegend} compact />
        <OverviewChart
          samples={data.samples}
          currentTime={currentTime + data.startTimeSec}
          min={chartMin}
          max={chartMax}
          onSeek={seekTo}
          events={events}
          markers={markers}
          onHover={onHover}
          highlight={highlight}
          bubbles={bubbleSource}
        />
      </div>

      <div className="detail-chart-section">
        <h3 className="section-title">Detail View (Zoomed)</h3>
        <p className="section-description">
          This view shows a zoomed-in portion of the signal that follows the current playback position.
        </p>
        <BubbleLegend text={bubbleLegend} />
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
          {/* Sits with the charts because that is where its effect is visible — the tooltip you
              get by resting on a marker, in both charts. */}
          {transcriptWindowSec != null && onTranscriptWindowChange && (
            <label
              className="transcript-window"
              title="Seconds of speech either side of a marker, shown in the tooltip when you rest the pointer on it. Widen it around a silent stretch; narrow it in a dense one to stay specific."
            >
              Transcript ±
              <input
                type="number"
                min={0}
                max={maxTranscriptWindowSec}
                step={1}
                value={transcriptWindowSec}
                aria-label="Transcript window in seconds"
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (!Number.isFinite(value)) return;
                  onTranscriptWindowChange(clamp(Math.round(value), 0, maxTranscriptWindowSec));
                }}
              />
              s
            </label>
          )}
        </div>
        <div className="detail-chart-scroller" ref={detailWrapRef}>
          <SignalChart
            samples={data.samples}
            currentTime={currentTime + data.startTimeSec}
            currentValue={currentValue}
            min={detailMin}
            max={detailMax}
            pxPerSecond={pxPerSecond}
            events={events}
            markers={markers}
            onHover={onHover}
            highlight={highlight}
            bubbles={bubbleSource}
          />
        </div>
      </div>
      </div>

    </section>
  );
}
