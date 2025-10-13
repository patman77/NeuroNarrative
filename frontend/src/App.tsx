import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import axios from "axios";
import { EventTimeline } from "./components/EventTimeline";
import { RuleSelector } from "./components/RuleSelector";
import { UploadPanel } from "./components/UploadPanel";
import { SignalPreview } from "./components/SignalPreview";
import type { ParsedGsrResult } from "./utils/gsrParser";
import { parseGsrCsv } from "./utils/gsrParser";
import "./styles.css";
import { logEvent } from "./utils/logger";

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
}

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
  const [ruleset, setRuleset] = useState<string>("default");
  const [preWindow, setPreWindow] = useState<number>(5);
  const [postWindow, setPostWindow] = useState<number>(7);
  const [previewVisible, setPreviewVisible] = useState<boolean>(false);
  const [hasPreviewed, setHasPreviewed] = useState<boolean>(false);

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

  // Auto-show preview when both files are ready
  useEffect(() => {
    if (!previewDisabled && csvFile && wavFile && gsrPreview && !hasPreviewed) {
      setPreviewVisible(true);
      setHasPreviewed(true);
      logEvent("Preview auto-shown", {
        csvName: csvFile.name,
        wavName: wavFile.name
      });
    }
  }, [previewDisabled, csvFile, wavFile, gsrPreview, hasPreviewed]);

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
      const analyzeResponse = await apiClient.post<AnalysisResponse>("/api/analyze", payload);
      return analyzeResponse.data;
    },
    onSuccess: (data) => {
      logEvent("Analysis completed", {
        events: data.events.length,
        audioDuration: data.audio_metadata.duration_sec,
        gsrDuration: data.gsr_metadata.duration_sec
      });
    },
    onError: (error) => {
      logEvent("Analysis failed", {
        message: error instanceof Error ? error.message : String(error)
      });
    }
  });

  const timelineEvents = useMemo(() => analyzeMutation.data?.events ?? [], [analyzeMutation.data]);
  const analyzeDisabled = previewDisabled || !hasPreviewed;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>NeuroNarrative</h1>
          <p>Align biosignals with conversation to surface emotion-linked summaries.</p>
        </div>
        <div className="app-header-actions">
          <button 
            onClick={handlePreviewClick} 
            disabled={previewDisabled}
            title={previewDisabled ? "Upload both CSV and WAV files to enable preview" : "Show signal preview"}
          >
            Preview
          </button>
          <button onClick={() => analyzeMutation.mutate()} disabled={analyzeMutation.isPending || analyzeDisabled}>
            {analyzeMutation.isPending ? "Analyzing…" : "Analyze session"}
          </button>
        </div>
      </header>

      <main className="app-main">
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
          />
          {analyzeMutation.isError && (
            <p className="error-text">
              {analyzeMutation.error instanceof Error
                ? analyzeMutation.error.message
                : "Analysis failed. Please retry."}
            </p>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
