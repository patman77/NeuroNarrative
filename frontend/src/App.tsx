import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import axios from "axios";
import { EventTimeline } from "./components/EventTimeline";
import { PhenomenaPanel } from "./components/PhenomenaPanel";
import { SessionNarrative } from "./components/SessionNarrative";
import { TranscriptTimeline } from "./components/TranscriptTimeline";
import { RuleSelector } from "./components/RuleSelector";
import { UploadPanel } from "./components/UploadPanel";
import { SignalPreview } from "./components/SignalPreview";
import type { ParsedGsrResult } from "./utils/gsrParser";
import { parseGsrCsv } from "./utils/gsrParser";
import "./styles.css";
import { logEvent } from "./utils/logger";
import { animateScroll } from "./utils/smoothScroll";

/** Breathing room under a clicked row when the page scrolls the charts into view. */
const REVEAL_BOTTOM_MARGIN_PX = 12;

/** Seconds either side of a phenomenon whose speech goes in its tooltip. Three is enough to
    catch the cue that provoked a deflection without pulling in the next exercise. */
const DEFAULT_TRANSCRIPT_WINDOW_SEC = 3;
const MAX_TRANSCRIPT_WINDOW_SEC = 60;
/** A native tooltip is not a reading surface; past this it stops being glanceable. */
const MAX_EXCERPT_CHARS = 400;

/**
 * What was said around `timeSec`, for the marker tooltip.
 *
 * A word counts when it *overlaps* the window rather than starting inside it, so a long word
 * spanning the moment is not dropped. Returns null when nothing was said — which is the common
 * case and worth stating in the tooltip, since these sessions are mostly silent by design.
 */
function excerptAround(
  transcript: TranscriptWord[],
  timeSec: number,
  windowSec: number
): string | null {
  if (!transcript.length) return null;
  const from = timeSec - windowSec;
  const to = timeSec + windowSec;
  const words: string[] = [];
  for (const word of transcript) {
    if (word.start == null || word.end == null) continue;
    if (word.end < from || word.start > to) continue;
    const text = word.text.trim();
    if (text) words.push(text);
  }
  if (!words.length) return null;
  const joined = words.join(" ");
  return joined.length > MAX_EXCERPT_CHARS
    ? `${joined.slice(0, MAX_EXCERPT_CHARS - 1).trimEnd()}…`
    : joined;
}

export interface TranscriptWord {
  text: string;
  start: number | null;
  end: number | null;
}

export interface HealthResponse {
  status: string;
  summarizer_enabled: boolean;
  summarizer_status: string;
}

export interface SummarizedEvent {
  event_id: string;
  time_sec: number;
  rule: string;
  delta_kohm?: number;
  delta_z?: number;
  summary?: string | null;
  transcript_excerpt?: string | null;
  score?: number | null;
}

/** One MindWalking phenomenon. `kind` is the manual's own notation — see docs/mindwalking-domain.md. */
export interface Phenomenon {
  id: string;
  kind: string;
  t_start: number;
  t_end: number;
  amplitude_lp?: number | null;
  amplitude_a?: number | null;
  confidence: number;
  stimulus_locked?: boolean | null;
  utterance_id?: string | null;
  detector: string;
  evidence: Record<string, unknown>;
}

export interface SessionMetrics {
  lpb: number;
  lp_min: number;
  lp_max: number;
  lpd_mean: number;
  lpd_track: Array<{ time_sec: number; lpd: number }>;
  a_unit_lp: number;
  a_unit_calibrated: boolean;
  counts: Record<string, number>;
  zone_min?: string | null;
  zone_max?: string | null;
  level_description: string;
  unmasked_duration_sec: number;
}

/** Which panel the pointer is in. The two charts are separate sources, not one "plot": the
    detail chart must not scroll itself out from under the pointer, but a hover in the overview
    is exactly when the detail chart *should* travel to that moment. */
export type HoverSource = "plot" | "overview" | "phenomena" | "narrative";

export interface HoverTarget {
  timeSec: number;
  source: HoverSource;
  /** End of the hovered span, when there is one. A narrative section covers minutes, so the
      phenomenon "at" it is the first one inside it — not whichever happens to be nearest its
      start, which is often nothing at all. */
  endSec?: number;
}

export interface SeekOptions {
  /** The element that was clicked. The page scrolls the charts into view on a seek, and without
      knowing where the click came from it scrolled the clicked row off the bottom of the
      window — you jumped to a moment and lost the row you jumped from. */
  origin?: HTMLElement | null;
  /** End of the span the click refers to. A narrative section covers minutes, and the plots
      shade that range so it is clear where it begins and ends. */
  endSec?: number;
}

export type SeekHandler = (timeSec: number, options?: SeekOptions) => void;

/** A moment, or a range, marked in both plots. Set by a click and outlives the pointer, unlike
    `hover` — which is why it is separate state rather than a pinned `HoverTarget`. */
export interface PlotSelection {
  timeSec: number;
  endSec?: number;
}

/** A vertical marking in the timeline plots. */
export interface TimelineMarker {
  id: string;
  timeSec: number;
  kind: string;
  label: string;
  /** Magnitude in A-units, for the bubble labels. Null when uncalibrated or not applicable —
      the bubble then shows the kind alone rather than a made-up number. */
  amplitudeA?: number | null;
}

export interface NarrativeSection {
  start_sec: number;
  end_sec: number;
  label: string;
  procedure?: string | null;
  title: string;
  summary: string;
  highlights: string[];
  lp_start?: number | null;
  lp_end?: number | null;
  lp_delta?: number | null;
  word_count: number;
  phenomena_counts: Record<string, number>;
}

export interface ProtocolSegment {
  procedure: string;
  label: string;
  start: number;
  end: number;
  children: ProtocolSegment[];
}

export interface AnalysisResponse {
  recording_id?: string;
  events: SummarizedEvent[];
  phenomena?: Phenomenon[];
  session_metrics?: SessionMetrics;
  calibration?: { a_unit_lp: number; a_unit_calibrated: boolean; lp_offset: number | null; zones_available: boolean };
  artefacts?: { masked_fraction: number; spans: Array<{ start_sec: number; end_sec: number; reason: string }> };
  protocol?: ProtocolSegment[];
  narrative?: NarrativeSection[];
  narrative_markdown?: string;
  channel?: {
    strategy: string;
    resolution_lp: number;
    quantised: boolean;
    notes: string[];
    tags?: Array<{ time_sec: number; tag: string }>;
  };
  gsr_metadata: { sampling_rate_hz: number; duration_sec: number };
  audio_metadata: { sampling_rate_hz: number; duration_sec: number };
  transcript: TranscriptWord[];
}

interface AnalysisJob {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  progress: number;
  result: AnalysisResponse | null;
  error: string | null;
}

interface AnalysisProgress {
  stage: string;
  fraction: number;
}

const POLL_INTERVAL_MS = 1000;

const STAGE_LABELS: Record<string, string> = {
  uploading: "Uploading files",
  starting: "Starting analysis",
  queued: "Queued",
  parsing: "Reading GSR data",
  detecting: "Detecting events",
  transcribing: "Transcribing audio",
  summarising: "Summarising events",
  done: "Finishing up"
};

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? ""
});

// Whole-page zoom, Acrobat/browser style: Cmd/Ctrl +, Cmd/Ctrl −, Cmd/Ctrl 0.
// The desktop shell is a WKWebView with no built-in page zoom, so the app provides
// its own via the CSS `zoom` property on the document root. Persisted per browser.
const PAGE_ZOOM_KEY = "neuronarrative.pageZoom";
const PAGE_ZOOM_STEP = 1.1;
const PAGE_ZOOM_MIN = 0.5;
const PAGE_ZOOM_MAX = 3;

/**
 * How the plot and the two lists share the window.
 *
 * `stacked` keeps the familiar top-to-bottom order and pins the charts to the top of the window,
 * so they stay on screen while you read down a list. `split` gives the plot its own column beside
 * the lists on a wide window, so nothing has to be pinned at all.
 *
 * Neither is right for every screen — which is why it is a switch and not a decision baked into
 * the CSS. Persisted, because it is a property of the monitor you are sitting at.
 */
export type WorkspaceLayout = "stacked" | "split";
const LAYOUT_KEY = "neuronarrative.layout";

interface PageZoom {
  percent: number;
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
}

function usePageZoom(): PageZoom {
  const [zoom, setZoom] = useState<number>(() => {
    const stored = Number(localStorage.getItem(PAGE_ZOOM_KEY));
    return stored >= PAGE_ZOOM_MIN && stored <= PAGE_ZOOM_MAX ? stored : 1;
  });

  useEffect(() => {
    document.documentElement.style.setProperty("zoom", String(zoom));
    localStorage.setItem(PAGE_ZOOM_KEY, String(zoom));
  }, [zoom]);

  const clampZoom = (value: number) => Math.min(Math.max(value, PAGE_ZOOM_MIN), PAGE_ZOOM_MAX);
  const zoomIn = useCallback(() => setZoom((z) => clampZoom(z * PAGE_ZOOM_STEP)), []);
  const zoomOut = useCallback(() => setZoom((z) => clampZoom(z / PAGE_ZOOM_STEP)), []);
  const reset = useCallback(() => setZoom(1), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      // Shift is allowed: Cmd+Shift+= is how "+" is typed on many layouts.
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
          reset();
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomIn, zoomOut, reset]);

  return { percent: Math.round(zoom * 100), zoomIn, zoomOut, reset };
}

function App() {
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [wavFile, setWavFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [gsrPreview, setGsrPreview] = useState<ParsedGsrResult | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [isParsingCsv, setIsParsingCsv] = useState<boolean>(false);
  const latestParseId = useRef(0);
  const seekRequestRef = useRef<((time: number) => void) | null>(null);
  // A seek requested while the preview is collapsed. `SignalPreview` owns the only real seek
  // function and publishes it into `seekRequestRef` on mount, so without this a click on an
  // event or phenomenon would silently do nothing whenever the preview happened to be closed.
  const pendingSeekRef = useRef<number | null>(null);
  const previewAnchorRef = useRef<HTMLDivElement | null>(null);
  // The row a pending seek came from, so the deferred reveal can still keep it on screen.
  const pendingOriginRef = useRef<HTMLElement | null>(null);
  const revealCancelRef = useRef<(() => void) | null>(null);
  // The charts inside the preview, published by SignalPreview the way `seekRequestRef` is.
  // Null whenever the preview is collapsed, which is why `revealPlot` still needs the anchor.
  const plotSectionRef = useRef<HTMLElement | null>(null);
  const [ruleset, setRuleset] = useState<string>("default");
  const [preWindow, setPreWindow] = useState<number>(5);
  const [postWindow, setPostWindow] = useState<number>(7);
  // The operator's own calibration numbers. Both optional, and their absence is meaningful:
  // without lpOffset no charge zone is named at all, because a solo electrode reads a whole
  // session as Kampfzone. See docs/phenomena-detection-design.md §4.
  // Lifted out of PhenomenaPanel: the filter chips also control which markers the timeline
  // draws, so the plot and the list have to read the same set.
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set(["T"]));
  // The moment the pointer is over, and which panel it came from. The source matters: a panel
  // must not auto-scroll itself in response to its own hover, or the row under the cursor
  // slides away as you read it.
  const [hover, setHover] = useState<HoverTarget | null>(null);
  // What was last clicked. The plots keep marking it after the pointer has moved away, so the
  // moment you jumped to stays identifiable while you read the row that produced it.
  const [selection, setSelection] = useState<PlotSelection | null>(null);
  const [lpOffset, setLpOffset] = useState<string>("");
  const [aUnitLp, setAUnitLp] = useState<string>("");
  const [previewVisible, setPreviewVisible] = useState<boolean>(false);
  const [hasPreviewed, setHasPreviewed] = useState<boolean>(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  // Measured by SignalPreview and handed to CSS. The stacked layout pins the charts by sticking
  // the whole card at a *negative* top offset — the setup above the charts scrolls out of view
  // and the charts stop at the window edge — and the lists below are then capped to whatever the
  // window has left, rather than to a fixed fraction of it that ignores the pinned plot.
  const [plotMetrics, setPlotMetrics] = useState({ offsetPx: 0, heightPx: 0 });
  // How much speech either side of a marker its tooltip carries. Adjustable, because the right
  // amount depends on the passage: a dense stretch needs a tight window to stay specific, and
  // around a silent one you have to reach further to find anything at all.
  const [transcriptWindowSec, setTranscriptWindowSec] = useState(DEFAULT_TRANSCRIPT_WINDOW_SEC);
  const [layout, setLayout] = useState<WorkspaceLayout>(() =>
    localStorage.getItem(LAYOUT_KEY) === "split" ? "split" : "stacked"
  );
  const pageZoom = usePageZoom();

  useEffect(() => {
    localStorage.setItem(LAYOUT_KEY, layout);
  }, [layout]);

  useEffect(() => {
    let cancelled = false;
    let timerId: ReturnType<typeof setTimeout>;

    const check = () => {
      apiClient.get<HealthResponse>("/api/health").then((response) => {
        if (!cancelled) {
          setBackendOnline(true);
          setHealth(response.data);
          timerId = setTimeout(check, 30_000);
        }
      }).catch(() => {
        if (!cancelled) {
          setBackendOnline(false);
          timerId = setTimeout(check, 5_000);
        }
      });
    };

    check();
    return () => {
      cancelled = true;
      clearTimeout(timerId);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
      }
    };
  }, [audioUrl]);

  const handleCsvChange = useCallback(async (file: File | null) => {
    setCsvFile(file);
    setGsrPreview(null);
    setPreviewVisible(false);
    setHasPreviewed(false);
    const parseId = latestParseId.current + 1;
    latestParseId.current = parseId;
    if (!file) {
      logEvent("CSV cleared");
      setParseError(null);
      setIsParsingCsv(false);
      return;
    }
    let parseSucceeded = false;
    try {
      setIsParsingCsv(true);
      logEvent("CSV selected", {
        name: file.name,
        size: file.size,
        type: file.type || "unknown"
      });
      const parsed = await parseGsrCsv(file);
      if (latestParseId.current !== parseId) {
        return;
      }
      setGsrPreview(parsed);
      setParseError(null);
      parseSucceeded = true;
      logEvent("CSV parsed successfully", {
        field: parsed.sourceColumn,
        samples: parsed.samples.length,
        samplingRateHz: parsed.samplingRateHz,
        duration: parsed.endTimeSec - parsed.startTimeSec
      });
    } catch (error) {
      if (latestParseId.current !== parseId) {
        return;
      }
      const message = error instanceof Error ? error.message : "Unable to parse CSV export.";
      setParseError(message);
      logEvent("CSV parsing failed", { message });
    } finally {
      if (latestParseId.current === parseId) {
        setIsParsingCsv(false);
        logEvent("CSV parsing finished", { success: parseSucceeded });
      }
    }
  }, []);

  const handleWavChange = useCallback((file: File | null) => {
    setWavFile(file);
    setPreviewVisible(false);
    setHasPreviewed(false);
    setAudioUrl((previous) => {
      if (previous) {
        URL.revokeObjectURL(previous);
      }
      return file ? URL.createObjectURL(file) : null;
    });
    if (file) {
      logEvent("WAV selected", {
        name: file.name,
        size: file.size,
        type: file.type || "audio/wav"
      });
    } else {
      logEvent("WAV cleared");
    }
  }, []);

  const previewDisabled = !csvFile || !wavFile || !!parseError || !gsrPreview;

  useEffect(() => {
    if (!previewDisabled && csvFile && wavFile && gsrPreview) {
      logEvent("Preview button enabled", {
        csvName: csvFile.name,
        wavName: wavFile.name,
        samples: gsrPreview.samples.length
      });
    }
  }, [previewDisabled, csvFile, wavFile, gsrPreview]);

  const handlePreviewClick = useCallback(() => {
    if (previewDisabled) {
      logEvent("Preview click ignored", {
        csvReady: Boolean(csvFile),
        wavReady: Boolean(wavFile),
        parseErrorPresent: Boolean(parseError),
        previewParsed: Boolean(gsrPreview)
      });
      return;
    }
    setPreviewVisible(true);
    setHasPreviewed(true);
    logEvent("Preview staged", {
      csvName: csvFile?.name ?? null,
      wavName: wavFile?.name ?? null
    });
  }, [previewDisabled, csvFile, wavFile, gsrPreview, parseError]);

  /** Jump the player to `time`, opening the preview first if it is not mounted.

      WaveSurfer's `seekTo` moves the playback head, so pressing play afterwards resumes from
      the clicked moment rather than from wherever the head happened to be. */
  const revealPlot = useCallback((origin?: HTMLElement | null) => {
    // The charts, not the top of the preview card. The card opens with the gauge, the metrics
    // and the waveform — some 700 px of header — so anchoring on it scrolled the charts to the
    // middle of the window and pushed the clicked row far below the fold. What the click is
    // about is the trace, so that is what has to be on screen.
    const plot = plotSectionRef.current ?? previewAnchorRef.current;
    if (!plot) return;

    const plotTop = plot.getBoundingClientRect().top + window.scrollY;
    let target = plotTop;
    if (origin?.isConnected) {
      const rowBottom = origin.getBoundingClientRect().bottom + window.scrollY;
      // Land with the clicked row just above the bottom edge. When the row is too far down for
      // both to fit, `plotTop` wins and the charts are shown whole — but only the charts have
      // to fit now, not the entire preview card, so in practice both are visible.
      target = Math.min(plotTop, rowBottom - window.innerHeight + REVEAL_BOTTOM_MARGIN_PX);
    }

    revealCancelRef.current?.();
    revealCancelRef.current = animateScroll(null, { top: Math.max(0, target) });
  }, []);

  const handleSeek = useCallback<SeekHandler>(
    (time, options) => {
      setSelection({ timeSec: time, endSec: options?.endSec });
      if (seekRequestRef.current) {
        seekRequestRef.current(time);
        revealPlot(options?.origin);
        return;
      }
      pendingSeekRef.current = time;
      pendingOriginRef.current = options?.origin ?? null;
      setPreviewVisible(true);
    },
    [revealPlot]
  );

  // Flush a seek that was requested before the preview existed. `seekRequestRef` is a ref, so
  // its assignment does not re-render; poll across a few frames instead of guessing a delay.
  useEffect(() => {
    if (!previewVisible || pendingSeekRef.current === null) return;
    let frames = 0;
    let raf = 0;
    const flush = () => {
      const time = pendingSeekRef.current;
      if (time === null) return;
      if (seekRequestRef.current) {
        seekRequestRef.current(time);
        pendingSeekRef.current = null;
        revealPlot(pendingOriginRef.current);
        pendingOriginRef.current = null;
        return;
      }
      if (frames++ < 60) raf = requestAnimationFrame(flush);
      else {
        pendingSeekRef.current = null;
        pendingOriginRef.current = null;
      }
    };
    raf = requestAnimationFrame(flush);
    return () => cancelAnimationFrame(raf);
  }, [previewVisible, gsrPreview, revealPlot]);

  const analyzeMutation = useMutation<AnalysisResponse, unknown, void>({
    mutationFn: async () => {
      if (!csvFile || !wavFile) {
        throw new Error("Please provide both CSV and WAV files.");
      }
      logEvent("Analysis requested", {
        csvName: csvFile.name,
        wavName: wavFile.name,
        ruleset,
        preWindow,
        postWindow
      });
      setProgress({ stage: "uploading", fraction: 0 });
      const formData = new FormData();
      formData.append("gsr", csvFile);
      formData.append("audio", wavFile);
      const uploadResponse = await apiClient.post("/api/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });

      const { csv_path, wav_path } = uploadResponse.data;
      const payload = {
        csv_path,
        wav_path,
        ruleset_name: ruleset,
        pre_event_window_sec: preWindow,
        post_event_window_sec: postWindow,
        lp_offset: lpOffset.trim() === "" ? null : Number(lpOffset),
        a_unit_lp: aUnitLp.trim() === "" ? null : Number(aUnitLp)
      };

      // Analysis runs as a background job: transcribing a long recording takes minutes,
      // far longer than the webview allows a single request to stay open.
      const { data: created } = await apiClient.post<{ job_id: string }>("/api/analyze", payload);
      setProgress({ stage: "starting", fraction: 0 });

      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        const { data: job } = await apiClient.get<AnalysisJob>(`/api/analyze/${created.job_id}`);
        setProgress({ stage: job.stage, fraction: job.progress });
        if (job.status === "done" && job.result) {
          return job.result;
        }
        if (job.status === "error") {
          throw new Error(job.error ?? "Analysis failed.");
        }
      }
    },
    onSuccess: (data) => {
      setProgress(null);
      logEvent("Analysis completed", {
        events: data.events.length,
        audioDuration: data.audio_metadata.duration_sec,
        gsrDuration: data.gsr_metadata.duration_sec
      });
    },
    onError: (error) => {
      setProgress(null);
      logEvent("Analysis failed", {
        message: error instanceof Error ? error.message : String(error)
      });
    }
  });

  const timelineEvents = useMemo(() => analyzeMutation.data?.events ?? [], [analyzeMutation.data]);
  const transcript = useMemo(() => analyzeMutation.data?.transcript ?? [], [analyzeMutation.data]);

  // `undefined` when there is no catalogue at all, so the charts can fall back to the legacy
  // event list. An *empty array* means "every kind is filtered out" and must draw nothing —
  // conflating the two made "None" fall through to the event markers instead of clearing them.
  const timelineMarkers = useMemo<TimelineMarker[] | undefined>(() => {
    const phenomena = analyzeMutation.data?.phenomena ?? [];
    if (!phenomena.length) return undefined;
    const words = analyzeMutation.data?.transcript ?? [];
    return phenomena
      .filter((p) => !hiddenKinds.has(p.kind))
      .map((p) => {
        const excerpt = excerptAround(words, p.t_start, transcriptWindowSec);
        // The tooltip is the one place the signal and the speech meet directly: you point at a
        // deflection and read what was being said when it happened. "Nothing was said" is a real
        // answer here, not a gap — a solo session is quiet most of the time.
        const spoken = words.length
          ? excerpt ?? `no speech within ±${transcriptWindowSec} s`
          : "no transcript";
        return {
          id: p.id,
          timeSec: p.t_start,
          kind: p.kind,
          label: `${p.kind} @ ${p.t_start.toFixed(1)}s\n±${transcriptWindowSec} s: ${spoken}`,
          amplitudeA: p.amplitude_a ?? null
        };
      });
  }, [analyzeMutation.data, hiddenKinds, transcriptWindowSec]);

  const toggleKind = useCallback((kind: string) => {
    setHiddenKinds((previous) => {
      const next = new Set(previous);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);

  const analyzeDisabled = previewDisabled;

  const handleAnalyzeClick = useCallback(() => {
    if (!hasPreviewed && !previewDisabled) {
      setPreviewVisible(true);
      setHasPreviewed(true);
      logEvent("Preview auto-staged before analysis", {
        csvName: csvFile?.name ?? null,
        wavName: wavFile?.name ?? null
      });
    }
    analyzeMutation.mutate();
  }, [hasPreviewed, previewDisabled, csvFile, wavFile, analyzeMutation]);

  const previewButtonTitle = !csvFile
    ? "Load a GSR CSV file first"
    : !wavFile
    ? "Load a WAV audio file"
    : isParsingCsv
    ? "Parsing CSV…"
    : parseError
    ? "Fix the CSV error first"
    : !gsrPreview
    ? "Waiting for CSV to parse"
    : undefined;

  const analyzeButtonTitle = previewDisabled ? previewButtonTitle : undefined;

  const backendPillClass =
    backendOnline === null ? "status-pill status-checking" :
    backendOnline ? "status-pill status-online" : "status-pill status-offline";

  const backendPillLabel =
    backendOnline === null ? "Checking backend…" :
    backendOnline ? "Backend online" : "Backend offline";

  const analyzeError = analyzeMutation.isError
    ? (analyzeMutation.error instanceof Error
        ? analyzeMutation.error.message
        : "Analysis failed. Please retry.")
    : null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>NeuroNarrative</h1>
          <p>Align biosignals with conversation to surface emotion-linked summaries.</p>
        </div>
        <div className="app-header-actions">
          <div className="page-zoom-controls" title="Page zoom (⌘+ / ⌘− / ⌘0)">
            <button type="button" onClick={pageZoom.zoomOut} className="page-zoom-button" aria-label="Zoom page out">
              −
            </button>
            <button type="button" onClick={pageZoom.reset} className="page-zoom-level" aria-label="Reset page zoom">
              {pageZoom.percent}%
            </button>
            <button type="button" onClick={pageZoom.zoomIn} className="page-zoom-button" aria-label="Zoom page in">
              +
            </button>
          </div>
          <button
            type="button"
            className="layout-toggle"
            onClick={() => setLayout(layout === "stacked" ? "split" : "stacked")}
            aria-pressed={layout === "split"}
            title={
              layout === "stacked"
                ? "Charts are pinned to the top while the lists scroll. Switch to a side-by-side column layout."
                : "Charts sit in their own column beside the lists. Switch back to the stacked layout."
            }
          >
            {layout === "stacked" ? "Layout: stacked" : "Layout: split"}
          </button>
          <span className={backendPillClass} title={backendOnline === false ? "Start: cd backend && uvicorn app.main:app --reload" : undefined}>
            {backendPillLabel}
          </span>
          <button onClick={handlePreviewClick} disabled={previewDisabled} title={previewButtonTitle}>
            Preview
          </button>
          <button
            onClick={handleAnalyzeClick}
            disabled={analyzeMutation.isPending || analyzeDisabled}
            title={analyzeButtonTitle}
          >
            {analyzeMutation.isPending
              ? progress
                ? `${Math.round(progress.fraction * 100)}%`
                : "Analyzing…"
              : "Analyze session"}
          </button>
        </div>
      </header>

      <main className="app-main">
        {analyzeMutation.isPending && progress && (
          <div className="progress-banner" role="status" aria-live="polite">
            <div className="progress-header">
              <span>{STAGE_LABELS[progress.stage] ?? progress.stage}</span>
              <span>{Math.round(progress.fraction * 100)}%</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${Math.max(2, progress.fraction * 100)}%` }} />
            </div>
            <p className="muted">
              Long recordings take a few minutes to transcribe. You can leave this window open.
            </p>
          </div>
        )}

        {analyzeError && (
          <div className="error-banner" role="alert">
            <strong>Analysis failed:</strong> {analyzeError}
            {backendOnline === false && (
              <span> – The backend is not running. Start it with: <code>cd backend &amp;&amp; uvicorn app.main:app --reload</code></span>
            )}
          </div>
        )}

        <section className="app-grid">
          <UploadPanel
            onCsvChange={handleCsvChange}
            onWavChange={handleWavChange}
            csvName={csvFile?.name}
            wavName={wavFile?.name}
            parseError={parseError}
          />
          <RuleSelector
            ruleset={ruleset}
            onRulesetChange={setRuleset}
            lpOffset={lpOffset}
            aUnitLp={aUnitLp}
            onLpOffsetChange={setLpOffset}
            onAUnitLpChange={setAUnitLp}
            preWindow={preWindow}
            postWindow={postWindow}
            onPreWindowChange={setPreWindow}
            onPostWindowChange={setPostWindow}
          />
        </section>

        {/* The plot and the lists are read against each other, so they are one region with two
            arrangements rather than two independent sections. `workspace-{layout}` is the only
            thing that differs between them — all the geometry lives in CSS. */}
        <div
          className={`workspace workspace-${layout}`}
          style={
            {
              "--plot-offset": `${plotMetrics.offsetPx}px`,
              "--plot-height": `${plotMetrics.heightPx}px`
            } as React.CSSProperties
          }
        >
        <div className="workspace-plot">
        {/* Scroll anchor: clicking a row jumps the player *and* brings the plot into view. */}
        <div ref={previewAnchorRef} />

        {previewVisible && gsrPreview ? (
          <SignalPreview
            data={gsrPreview}
            audioUrl={audioUrl}
            audioFileName={wavFile?.name ?? null}
            csvFileName={csvFile?.name ?? null}
            events={timelineEvents}
            markers={timelineMarkers}
            hover={hover}
            onHover={setHover}
            selection={selection}
            seekRef={seekRequestRef}
            plotSectionRef={plotSectionRef}
            onPlotMetrics={setPlotMetrics}
            transcriptWindowSec={transcriptWindowSec}
            maxTranscriptWindowSec={MAX_TRANSCRIPT_WINDOW_SEC}
            onTranscriptWindowChange={setTranscriptWindowSec}
          />
        ) : (
          <section className="card preview-placeholder">
            <h2>Signal preview</h2>
            {parseError ? (
              <p className="error-text">{parseError}</p>
            ) : isParsingCsv ? (
              <p className="muted">Parsing CSV export…</p>
            ) : (
              <>
                <p className="muted">
                  Upload both files and click <strong>Preview</strong> to inspect the biosignal playback before running the
                  analysis.
                </p>
                <div className="preview-actions">
                  <button onClick={handlePreviewClick} disabled={previewDisabled}>
                    Preview
                  </button>
                </div>
              </>
            )}
          </section>
        )}
        </div>

        {/*
          Phenomena and events sit side by side, each scrolling independently. Stacked, a
          54-minute session ran to hundreds of rows and the page became unusably tall — and the
          two lists are read against each other, so they need to be visible at the same time.
          In the split layout they share the right-hand column and stack instead, because half a
          half is not enough width for a row.
        */}
        <div className="analysis-columns">
          {/* Rendered unconditionally: a conditional column would leave the grid half empty
              and the split would stop being 50/50. The panel has its own empty state. */}
          <section className="card analysis-column">
            <PhenomenaPanel
              recordingId={analyzeMutation.data?.recording_id ?? ""}
              phenomena={analyzeMutation.data?.phenomena ?? []}
              metrics={analyzeMutation.data?.session_metrics}
              protocol={analyzeMutation.data?.protocol}
              artefacts={analyzeMutation.data?.artefacts}
              hiddenKinds={hiddenKinds}
              onToggleKind={toggleKind}
              onSetHiddenKinds={setHiddenKinds}
              hover={hover}
              onHover={setHover}
              onSeek={handleSeek}
            />
          </section>

          {/* The narrative replaces the per-event one-liners here: a session reads as a
              sequence of themed stretches, not as 350 isolated moments. The raw event list is
              still below, where its exports and per-event detail live. */}
          <section className="card analysis-column">
            <SessionNarrative
              sections={analyzeMutation.data?.narrative ?? []}
              markdown={analyzeMutation.data?.narrative_markdown}
              hover={hover}
              onHover={setHover}
              onSeek={handleSeek}
            />
          </section>
        </div>
        </div>

        <section className="card">
          <EventTimeline
            events={timelineEvents}
            isLoading={analyzeMutation.isPending}
            audioDuration={analyzeMutation.data?.audio_metadata.duration_sec}
            onSeek={handleSeek}
            summarizerEnabled={health?.summarizer_enabled ?? true}
            summarizerStatus={health?.summarizer_status}
          />
        </section>

        <section className="card">
          <TranscriptTimeline transcript={transcript} onSeek={handleSeek} />
        </section>
      </main>
    </div>
  );
}

export default App;
