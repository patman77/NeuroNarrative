import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import axios from "axios";
import { EventTimeline } from "./components/EventTimeline";
import { TranscriptTimeline } from "./components/TranscriptTimeline";
import { RuleSelector } from "./components/RuleSelector";
import { UploadPanel } from "./components/UploadPanel";
import { SignalPreview } from "./components/SignalPreview";
import type { ParsedGsrResult } from "./utils/gsrParser";
import { parseGsrCsv } from "./utils/gsrParser";
import "./styles.css";
import { logEvent } from "./utils/logger";

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

export interface AnalysisResponse {
  events: SummarizedEvent[];
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

function App() {
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [wavFile, setWavFile] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [gsrPreview, setGsrPreview] = useState<ParsedGsrResult | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [isParsingCsv, setIsParsingCsv] = useState<boolean>(false);
  const latestParseId = useRef(0);
  const seekRequestRef = useRef<((time: number) => void) | null>(null);
  const [ruleset, setRuleset] = useState<string>("default");
  const [preWindow, setPreWindow] = useState<number>(5);
  const [postWindow, setPostWindow] = useState<number>(7);
  const [previewVisible, setPreviewVisible] = useState<boolean>(false);
  const [hasPreviewed, setHasPreviewed] = useState<boolean>(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);

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
        post_event_window_sec: postWindow
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
            preWindow={preWindow}
            postWindow={postWindow}
            onPreWindowChange={setPreWindow}
            onPostWindowChange={setPostWindow}
          />
        </section>

        {previewVisible && gsrPreview ? (
          <SignalPreview
            data={gsrPreview}
            audioUrl={audioUrl}
            audioFileName={wavFile?.name ?? null}
            csvFileName={csvFile?.name ?? null}
            events={timelineEvents}
            seekRef={seekRequestRef}
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

        <section className="card">
          <EventTimeline
            events={timelineEvents}
            isLoading={analyzeMutation.isPending}
            audioDuration={analyzeMutation.data?.audio_metadata.duration_sec}
            onSeek={(time) => { seekRequestRef.current?.(time); }}
            summarizerEnabled={health?.summarizer_enabled ?? true}
            summarizerStatus={health?.summarizer_status}
          />
        </section>

        <section className="card">
          <TranscriptTimeline
            transcript={transcript}
            onSeek={(time) => seekRequestRef.current?.(time)}
          />
        </section>
      </main>
    </div>
  );
}

export default App;
