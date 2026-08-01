import { useEffect, useMemo, useRef } from "react";
import type { HoverTarget, NarrativeSection } from "../App";
import { scrollChildIntoView } from "../utils/smoothScroll";

/**
 * The session narrative: a time-segmented, thematic account of the sitting.
 *
 * Every heading's time range is real — section boundaries come from the BK3 protocol cues
 * actually spoken and the charge levels from the measured signal. The language model only wrote
 * the prose inside boundaries it did not get to choose. That is why clicking a heading is
 * meaningful: it seeks to a moment that exists, rather than to an estimate.
 */

interface Props {
  sections: NarrativeSection[];
  markdown?: string;
  hover: HoverTarget | null;
  onHover: (hover: HoverTarget | null) => void;
  onSeek?: (timeSec: number) => void;
}

function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function download(markdown: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "sitzungsbericht.md";
  link.click();
  URL.revokeObjectURL(url);
}

export function SessionNarrative({ sections, markdown, hover, onHover, onSeek }: Props) {
  const listRef = useRef<HTMLOListElement | null>(null);
  const rowRefs = useRef<Map<string, HTMLLIElement>>(new Map());

  const sectionKey = (section: NarrativeSection) => `${section.start_sec}-${section.label}`;

  // The section *containing* the hovered moment — sections tile the session without gaps, so
  // this is exact rather than a nearest-neighbour guess.
  const highlightedKey = useMemo(() => {
    if (!hover || hover.source === "narrative") return null;
    const match = sections.find((s) => s.start_sec <= hover.timeSec && hover.timeSec < s.end_sec);
    return match ? sectionKey(match) : null;
  }, [hover, sections]);

  useEffect(() => {
    if (!highlightedKey) return;
    return scrollChildIntoView(listRef.current, rowRefs.current.get(highlightedKey) ?? null);
  }, [highlightedKey]);

  if (!sections.length) {
    return (
      <div className="narrative">
        <div className="timeline-header">
          <h2>Session narrative</h2>
        </div>
        <p className="muted">
          No narrative yet. It is built from the protocol instructions in the transcript, so it
          needs an analysis with audio.
        </p>
      </div>
    );
  }

  return (
    <div className="narrative">
      <div className="timeline-header">
        <h2>Session narrative</h2>
        {markdown && (
          <button className="btn-small" onClick={() => download(markdown)} title="Download as Markdown">
            Download report
          </button>
        )}
      </div>
      <p className="section-description">
        Times come from the spoken protocol cues and the measured signal — not from the summariser.
        Click a section to jump there.
      </p>

      <ol className="narrative-list" ref={listRef} onMouseLeave={() => onHover(null)}>
        {sections.map((section) => {
          const counts = Object.entries(section.phenomena_counts).sort();
          const range = `${formatClock(section.start_sec)}–${formatClock(section.end_sec)}`;
          // Without a transcript the title falls back to the section label, which *is* the time
          // range — printing both renders it twice.
          const heading = section.title === range ? "" : section.title;
          return (
            <li
              key={sectionKey(section)}
              ref={(node) => {
                if (node) rowRefs.current.set(sectionKey(section), node);
                else rowRefs.current.delete(sectionKey(section));
              }}
              className={
                highlightedKey === sectionKey(section)
                  ? "narrative-section narrative-section-active"
                  : "narrative-section"
              }
              onMouseEnter={() =>
                onHover({ timeSec: section.start_sec, endSec: section.end_sec, source: "narrative" })
              }
              onClick={onSeek ? () => onSeek(section.start_sec) : undefined}
            >
              <div className="narrative-heading">
                <button
                  type="button"
                  className="narrative-time"
                  title="Jump the player here"
                  onClick={(event) => {
                    event.stopPropagation();
                    onSeek?.(section.start_sec);
                  }}
                >
                  {range}
                </button>
                {heading && <span className="narrative-title">{heading}</span>}
                {section.procedure && <span className="narrative-procedure">{section.procedure}</span>}
              </div>

              {section.summary && <p className="narrative-summary">{section.summary}</p>}

              {section.highlights.length > 0 && (
                <ul className="narrative-highlights">
                  {section.highlights.map((highlight, index) => (
                    <li key={index}>{highlight}</li>
                  ))}
                </ul>
              )}

              <div className="narrative-facts">
                {section.lp_start != null && section.lp_end != null && (
                  <span
                    title="Charge level at the start and end of this section, read from the signal"
                    className={
                      (section.lp_delta ?? 0) < 0 ? "narrative-lp narrative-lp-down" : "narrative-lp"
                    }
                  >
                    LP {section.lp_start.toFixed(2)} → {section.lp_end.toFixed(2)}
                    {section.lp_delta != null && ` (${section.lp_delta >= 0 ? "+" : ""}${section.lp_delta.toFixed(2)})`}
                  </span>
                )}
                {counts.map(([kind, count]) => (
                  <span key={kind} className="narrative-count">
                    {count}× {kind}
                  </span>
                ))}
                {section.word_count === 0 && <span className="narrative-count">silent</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
