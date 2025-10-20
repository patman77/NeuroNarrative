import { useEffect, useMemo, useRef, useState } from "react";
import type { ParsedGsrResult, ParsedGsrSample } from "../utils/gsrParser";
import { logEvent } from "../utils/logger";

interface SignalPreviewProps {
  data: ParsedGsrResult;
  audioUrl: string | null;
  audioFileName?: string | null;
  csvFileName?: string | null;
}

const DISPLAY_MIN = 1;
const DISPLAY_MAX = 6.5;

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

  return (
    <svg className="gauge" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Current GSR ${clamped.toFixed(2)}`}>
      <defs>
        <linearGradient id="gaugeGradient" x1="0" x2="1" y1="0" y2="0">
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
}

function SignalChart({ samples, currentTime, currentValue, min, max }: SignalChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pxPerSecond = 80;
  const chartHeight = 220;
  const topPadding = 16;
  const bottomPadding = 24;
  const usableHeight = chartHeight - topPadding - bottomPadding;
  const startTime = samples[0].timeSec;
  const endTime = samples[samples.length - 1].timeSec;
  const duration = Math.max(endTime - startTime, 0.001);
  const width = Math.max(720, Math.round(duration * pxPerSecond));

  const path = useMemo(() => {
    if (!samples.length) {
      return "";
    }
    const pathCommands: string[] = [];
    samples.forEach((sample, index) => {
      const x = ((sample.timeSec - startTime) / duration) * width;
      const ratio = (sample.value - min) / (max - min || 1);
      const clampedRatio = clamp(ratio, 0, 1);
      const y = topPadding + (1 - clampedRatio) * usableHeight;
      pathCommands.push(`${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`);
    });
    return pathCommands.join(" ");
  }, [samples, duration, width, min, max, startTime, usableHeight, topPadding]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const indicatorPosition = ((currentTime - startTime) / duration) * width;
    if (!Number.isFinite(indicatorPosition)) {
      return;
    }
    const safePosition = clamp(indicatorPosition, 0, width);
    const padding = container.clientWidth * 0.4;
    const target = Math.max(0, safePosition - padding);
    container.scrollTo({ left: target, behavior: "auto" });
  }, [currentTime, duration, startTime, width]);

  const indicatorX = clamp(((currentTime - startTime) / duration) * width, 0, width);
  const indicatorYTop = topPadding;
  const indicatorYBottom = chartHeight - bottomPadding + 12;

  const currentRatio = (currentValue - min) / (max - min || 1);
  const currentY = topPadding + (1 - clamp(currentRatio, 0, 1)) * usableHeight;

  return (
    <div className="signal-chart" ref={containerRef}>
      <svg width={width} height={chartHeight} role="img" aria-label="GSR timeline">
        <rect x={0} y={0} width={width} height={chartHeight} fill="#f7fafc" />
        <path d={path} fill="none" stroke="#0f6f8f" strokeWidth={2} strokeLinecap="round" />
        <line x1={indicatorX} y1={indicatorYTop} x2={indicatorX} y2={indicatorYBottom} stroke="#f44336" strokeWidth={2} strokeDasharray="6 6" />
        <circle cx={indicatorX} cy={currentY} r={5} fill="#f44336" stroke="#fff" strokeWidth={2} />
      </svg>
    </div>
  );
}

export function SignalPreview({ data, audioUrl, audioFileName, csvFileName }: SignalPreviewProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioDuration, setAudioDuration] = useState<number | null>(null);

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
    setCurrentTime(0);
    setIsPlaying(false);
    setAudioDuration(null);
    logEvent("Preview data refreshed", {
      csvColumn: data.sourceColumn,
      sampleCount: data.samples.length,
      audioAvailable: Boolean(audioUrl)
    });
  }, [audioUrl, data.sourceColumn, data.startTimeSec, data.endTimeSec]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    const handleLoaded = () => {
      setAudioDuration(audio.duration);
      logEvent("Audio metadata loaded", {
        duration: audio.duration,
        readyState: audio.readyState
      });
    };
    const handlePlay = () => {
      setIsPlaying(true);
      logEvent("Audio playback started");
    };
    const handlePause = () => {
      setIsPlaying(false);
      logEvent("Audio playback paused", { currentTime: audio.currentTime });
    };
    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(audio.duration || 0);
      logEvent("Audio playback ended");
    };
    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
    };

    audio.addEventListener("loadedmetadata", handleLoaded);
    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("timeupdate", handleTimeUpdate);

    return () => {
      audio.removeEventListener("loadedmetadata", handleLoaded);
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("timeupdate", handleTimeUpdate);
    };
  }, [audioUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !isPlaying) {
      return undefined;
    }
    let rafId: number;
    const update = () => {
      setCurrentTime(audio.currentTime);
      rafId = requestAnimationFrame(update);
    };
    rafId = requestAnimationFrame(update);
    return () => cancelAnimationFrame(rafId);
  }, [isPlaying]);

  const togglePlayback = () => {
    const audio = audioRef.current;
    if (!audio) {
      logEvent("Playback toggle ignored", { audioAvailable: false });
      return;
    }
    if (audio.paused) {
      logEvent("Playback toggle", { action: "play" });
      audio.play().catch((error) => {
        setIsPlaying(false);
        logEvent("Audio playback failed to start", {
          message: error instanceof Error ? error.message : String(error)
        });
      });
    } else {
      logEvent("Playback toggle", { action: "pause", currentTime: audio.currentTime });
      audio.pause();
    }
  };

  const progress = effectiveDuration ? Math.min(currentTime / effectiveDuration, 1) : 0;

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
          <div className="playback-controls">
            <button type="button" onClick={togglePlayback} className="playback-button">
              {isPlaying ? "Pause" : "Play"}
            </button>
            <div className="playback-timeline">
              <div className="playback-progress" style={{ width: `${progress * 100}%` }} />
            </div>
            <span className="playback-time">
              {formatTime(currentTime)} / {formatTime(effectiveDuration ?? 0)}
            </span>
          </div>
        ) : (
          <p className="muted">Add a WAV file to enable playback.</p>
        )}
      </div>

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

      <SignalChart
        samples={data.samples}
        currentTime={currentTime + data.startTimeSec}
        currentValue={currentValue}
        min={chartMin}
        max={chartMax}
      />

      {audioUrl && <audio ref={audioRef} src={audioUrl} preload="metadata" hidden />} 
    </section>
  );
}
