import type { SummarizedEvent } from "../App";

interface EventTimelineProps {
  events: SummarizedEvent[];
  isLoading: boolean;
  audioDuration?: number;
}

export function EventTimeline({ events, isLoading, audioDuration }: EventTimelineProps) {
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
        {audioDuration && <span className="muted">Audio duration: {audioDuration.toFixed(1)} s</span>}
      </div>
      <ul className="timeline-list">
        {events.map((event) => (
          <li key={event.event_id}>
            <div className="timeline-row">
              <strong>t = {event.time_sec.toFixed(2)}s · rule {event.rule}</strong>
              <span className="muted">
                ΔkΩ {event.delta_kohm?.toFixed(2) ?? "—"} · z {event.delta_z?.toFixed(2) ?? "—"}
              </span>
            </div>
            {event.summary ? (
              <p className="summary-bubble">{event.summary}</p>
            ) : (
              <p className="muted">No summary available. Provide a transcript or enable the local LLM.</p>
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
