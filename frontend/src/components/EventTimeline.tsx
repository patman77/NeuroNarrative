import type { SummarizedEvent } from "../App";

interface EventTimelineProps {
  events: SummarizedEvent[];
  isLoading: boolean;
  audioDuration?: number;
  onSeek?: (time: number) => void;
  /** From /api/health, so a missing summary can name its real cause. */
  summarizerEnabled?: boolean;
  summarizerStatus?: string;
}

function formatTimeSec(sec: number): string {
  if (!Number.isFinite(sec)) return "—";
  const mins = Math.floor(sec / 60);
  const secs = (sec % 60).toFixed(1).padStart(4, "0");
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportCsv(events: SummarizedEvent[]) {
  const header = "event_id,time_sec,rule,delta_kohm,delta_z,score,summary";
  const rows = events.map((ev) => {
    const escapeCsv = (val: string | number | null | undefined) => {
      if (val === null || val === undefined) return "";
      const str = String(val);
      if (str.includes(",") || str.includes('"') || str.includes("\n")) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };
    return [
      escapeCsv(ev.event_id),
      escapeCsv(ev.time_sec),
      escapeCsv(ev.rule),
      escapeCsv(ev.delta_kohm),
      escapeCsv(ev.delta_z),
      escapeCsv(ev.score),
      escapeCsv(ev.summary),
    ].join(",");
  });
  downloadBlob([header, ...rows].join("\n"), "neuronarrative_events.csv", "text/csv");
}

function exportJson(events: SummarizedEvent[]) {
  downloadBlob(JSON.stringify(events, null, 2), "neuronarrative_events.json", "application/json");
}

function formatSrtTime(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.round((sec - Math.floor(sec)) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
}

function exportSrt(events: SummarizedEvent[]) {
  const lines = events.map((ev, i) => {
    const start = formatSrtTime(ev.time_sec);
    const end = formatSrtTime(ev.time_sec + 7);
    const delta = ev.delta_kohm !== null && ev.delta_kohm !== undefined
      ? ` ΔkΩ: ${ev.delta_kohm >= 0 ? "+" : ""}${ev.delta_kohm.toFixed(2)}`
      : "";
    return `${i + 1}\n${start} --> ${end}\n[Event: ${ev.rule}]${delta}`;
  });
  downloadBlob(lines.join("\n\n") + "\n", "events.srt", "text/srt");
}

function ScoreBadge({ score }: { score?: number | null }) {
  if (score === null || score === undefined) return null;
  const clamped = Math.max(0, Math.min(1, score));
  const pct = Math.round(clamped * 100);
  const hue = Math.round(clamped * 120); // 0 = red, 120 = green
  return (
    <span
      className="event-score"
      title={`Score: ${score.toFixed(3)}`}
      style={{ background: `hsl(${hue}, 70%, 25%)`, borderColor: `hsl(${hue}, 70%, 45%)` }}
    >
      {pct}%
    </span>
  );
}

function DeltaKohm({ value }: { value?: number | null }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const sign = value >= 0 ? "+" : "";
  // Negative delta = resistance drop = arousal increase → good signal (green)
  // Positive delta = resistance rise → less arousal (red)
  const colorClass = value <= 0 ? "delta-positive" : "delta-negative";
  return (
    <span className={`delta-kohm ${colorClass}`}>
      {sign}{value.toFixed(2)} kΩ
    </span>
  );
}

export function EventTimeline({
  events,
  isLoading,
  audioDuration,
  onSeek,
  summarizerEnabled = true,
  summarizerStatus,
}: EventTimelineProps) {
  if (isLoading) {
    return <div className="muted">Analyzing session…</div>;
  }

  if (!events.length) {
    return <div className="muted">No events detected yet. Upload files and run an analysis.</div>;
  }

  return (
    <div className="timeline">
      <div className="timeline-header">
        <h2>Detected events</h2>
        {audioDuration !== undefined && (
          <span className="muted">Audio duration: {audioDuration.toFixed(1)} s</span>
        )}
      </div>

      {/* Export bar */}
      <div className="export-bar">
        <span className="muted" style={{ fontSize: "0.85rem" }}>{events.length} event{events.length !== 1 ? "s" : ""}</span>
        <button className="btn-small" onClick={() => exportCsv(events)} title="Download events as CSV">
          Download CSV
        </button>
        <button className="btn-small" onClick={() => exportJson(events)} title="Download events as JSON">
          Download JSON
        </button>
        <button className="btn-small" onClick={() => exportSrt(events)} title="Download events as SRT subtitles">
          Download SRT
        </button>
        <button className="btn-small" onClick={() => window.print()} title="Print or save as PDF">
          Save as PDF
        </button>
      </div>

      <ul className="timeline-list">
        {events.map((event) => (
          <li
            key={event.event_id}
            className="timeline-event-card"
            // The whole card seeks, summary text included — the summary is usually what you are
            // reading when you decide you want to hear that moment.
            onClick={onSeek ? () => onSeek(event.time_sec) : undefined}
          >
            <div className="timeline-row">
              <div className="timeline-row-left">
                <span className="event-badge">{event.rule}</span>
                <span className="event-time">{formatTimeSec(event.time_sec)}</span>
              </div>
              <div className="timeline-row-right">
                <ScoreBadge score={event.score} />
                <span className="muted" style={{ fontSize: "0.8rem" }}>
                  <DeltaKohm value={event.delta_kohm} />
                  {event.delta_z !== null && event.delta_z !== undefined && (
                    <> &nbsp; z {event.delta_z.toFixed(2)}</>
                  )}
                </span>
                {onSeek && (
                  <button
                    className="btn-small btn-jump"
                    onClick={(clickEvent) => {
                      clickEvent.stopPropagation();
                      onSeek(event.time_sec);
                    }}
                    title={`Jump to ${formatTimeSec(event.time_sec)}`}
                  >
                    Jump to
                  </button>
                )}
              </div>
            </div>
            {event.summary ? (
              <p className="summary-bubble">{event.summary}</p>
            ) : (
              // Distinguish the two very different reasons a summary is missing. The old
              // single message blamed the setup even when the setup was fine and the
              // recording was simply silent around this event.
              <p className="muted">
                {event.transcript_excerpt
                  ? "Too little was said here to summarise."
                  : "No speech near this event."}
                {summarizerStatus && !summarizerEnabled && ` Summariser off: ${summarizerStatus}.`}
              </p>
            )}
            {event.transcript_excerpt && (
              <details>
                <summary>Show verbatim excerpt</summary>
                <p>{event.transcript_excerpt}</p>
              </details>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
