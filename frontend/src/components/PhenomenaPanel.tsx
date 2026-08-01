import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import type { Phenomenon, ProtocolSegment, SessionMetrics } from "../App";
import { logEvent } from "../utils/logger";

/**
 * The MindWalking phenomenon catalogue for a session.
 *
 * Two presentation rules come straight from the manuals and should not be "simplified":
 *
 * - Ranking is **"Größte Ladung zuerst"** — largest discharge first. That is the order the
 *   session leader works in.
 * - An uncalibrated A-magnitude is never printed as if it were the device's own reading. The
 *   manual is explicit that comparing a BE against an A needs the sensitivity calibration, so
 *   without it the panel says so rather than showing a confident "3A".
 */

type Verdict = "confirmed" | "rejected" | "reclassified" | "missed";

interface StoredLabel {
  phenomenon_id: string;
  verdict: Verdict;
  kind?: string | null;
  t_start?: number | null;
  note?: string;
}

interface Props {
  recordingId: string;
  phenomena: Phenomenon[];
  metrics?: SessionMetrics;
  protocol?: ProtocolSegment[];
  artefacts?: { masked_fraction: number; spans: Array<{ start_sec: number; end_sec: number; reason: string }> };
  onSeek?: (timeSec: number) => void;
}

const KIND_LABEL: Record<string, string> = {
  A: "Ausschlag",
  T: "Ticken",
  BE: "Blitzentladung",
  LPA_slow: "Langsame Entladung",
  X: "Kein Ausschlag",
  KVZ: "Kommunikationsverzögerung",
  KB: "Körperbewegung",
  SN: "Schmutzige Nadel",
  FN: "Freie Nadel"
};

const KIND_HINT: Record<string, string> = {
  A: "A fall of the needle — something became available.",
  T: "The smallest deflection. Below the manual's 0.5 A reliability floor.",
  BE: "A fast fall that did not come back: the standing charge dropped. Marks an important statement.",
  LPA_slow: "The level crept down over tens of seconds rather than snapping.",
  X: "An instruction that produced no deflection where one was expected.",
  KVZ: "The signal moved while nothing was said.",
  KB: "Body movement — mechanical, not mental. Excluded from the other detectors."
};

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function chargeRank(p: Phenomenon): number {
  const magnitude = p.amplitude_a ?? Math.abs(p.amplitude_lp ?? 0);
  return (p.kind === "T" ? 0.25 : 1) * Math.abs(magnitude);
}

export function PhenomenaPanel({ recordingId, phenomena, metrics, protocol, artefacts, onSeek }: Props) {
  const [order, setOrder] = useState<"charge" | "time">("charge");
  const [hidden, setHidden] = useState<Set<string>>(new Set(["T"]));
  const [labels, setLabels] = useState<Record<string, Verdict>>({});
  const [labelError, setLabelError] = useState<string | null>(null);

  // Labels are the whole point of this panel: nothing past stage 4 of the detection design can
  // be measured without them, so reviewing has to be one click and has to persist.
  useEffect(() => {
    if (!recordingId) return;
    let cancelled = false;
    axios
      .get<{ labels: StoredLabel[] }>(`/api/labels/${recordingId}`)
      .then(({ data }) => {
        if (cancelled) return;
        const next: Record<string, Verdict> = {};
        for (const label of data.labels) next[label.phenomenon_id] = label.verdict;
        setLabels(next);
      })
      .catch((error) => {
        if (!cancelled) logEvent("labels.load-failed", { error: String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [recordingId]);

  const setVerdict = useCallback(
    async (phenomenonId: string, verdict: Verdict) => {
      if (!recordingId) return;
      const previous = labels[phenomenonId];
      const clearing = previous === verdict;
      // Optimistic: annotation is a rhythm, and waiting for a round trip per click breaks it.
      setLabels((current) => {
        const next = { ...current };
        if (clearing) delete next[phenomenonId];
        else next[phenomenonId] = verdict;
        return next;
      });
      setLabelError(null);
      try {
        if (clearing) {
          await axios.delete(`/api/labels/${recordingId}/${phenomenonId}`);
        } else {
          await axios.put(`/api/labels/${recordingId}`, {
            phenomenon_id: phenomenonId,
            verdict
          });
        }
      } catch (error) {
        // Put it back rather than leaving the UI claiming something was saved when it was not.
        setLabels((current) => {
          const next = { ...current };
          if (previous) next[phenomenonId] = previous;
          else delete next[phenomenonId];
          return next;
        });
        setLabelError("Could not save that label — it has been reverted.");
        logEvent("labels.save-failed", { error: String(error) });
      }
    },
    [labels, recordingId]
  );

  const kinds = useMemo(
    () => Array.from(new Set(phenomena.map((p) => p.kind))).sort(),
    [phenomena]
  );

  const visible = useMemo(() => {
    const filtered = phenomena.filter((p) => !hidden.has(p.kind));
    return order === "charge"
      ? [...filtered].sort((a, b) => chargeRank(b) - chargeRank(a))
      : [...filtered].sort((a, b) => a.t_start - b.t_start);
  }, [phenomena, hidden, order]);

  const segmentAt = (timeSec: number): ProtocolSegment | null => {
    const walk = (nodes: ProtocolSegment[]): ProtocolSegment | null => {
      for (const node of nodes) {
        if (timeSec >= node.start && timeSec <= node.end) {
          return walk(node.children) ?? node;
        }
      }
      return null;
    };
    return protocol ? walk(protocol) : null;
  };

  if (!phenomena.length) {
    return (
      <section className="phenomena-panel">
        <h3 className="section-title">Session phenomena</h3>
        <p className="section-description">Nothing detected in this recording.</p>
      </section>
    );
  }

  const toggle = (kind: string) => {
    setHidden((previous) => {
      const next = new Set(previous);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };

  return (
    <section className="phenomena-panel">
      <h3 className="section-title">Session phenomena</h3>

      {metrics && (
        <div className="phenomena-metrics">
          <div>
            <span className="metric-label">LPB</span>
            <span className="metric-value">{metrics.lpb.toFixed(2)} LP</span>
          </div>
          <div>
            <span className="metric-label">LPD</span>
            <span className="metric-value">{metrics.lpd_mean.toFixed(1)} A/min</span>
          </div>
          <div>
            <span className="metric-label">Level</span>
            <span className="metric-value" title={metrics.level_description}>
              {metrics.zone_min && metrics.zone_max
                ? metrics.zone_min === metrics.zone_max
                  ? metrics.zone_min
                  : `${metrics.zone_min} – ${metrics.zone_max}`
                : `LP ${metrics.lp_min.toFixed(2)}–${metrics.lp_max.toFixed(2)}`}
            </span>
          </div>
        </div>
      )}

      {metrics && !metrics.a_unit_calibrated && (
        <p className="phenomena-caveat">
          A-magnitudes are <strong>uncalibrated</strong>: one scale division is estimated at{" "}
          {metrics.a_unit_lp.toFixed(3)} LP rather than measured by a Dosendruck. Comparing a BE
          against an A needs that calibration, so treat the ordering as indicative.
          {!metrics.zone_min && " No charge zone is named, because no solo-electrode offset was given."}
        </p>
      )}

      {artefacts && artefacts.spans.length > 0 && (
        <p className="phenomena-caveat">
          {(artefacts.masked_fraction * 100).toFixed(2)}% of the recording is masked as artefact
          ({artefacts.spans.length} span{artefacts.spans.length === 1 ? "" : "s"}), and no
          phenomenon is reported inside those.
        </p>
      )}

      {labelError && <p className="phenomena-caveat">{labelError}</p>}

      {recordingId && (
        <p className="section-description">
          Reviewed <strong>{Object.keys(labels).length}</strong> of {phenomena.length}. Confirming
          or rejecting a detection is what makes precision and recall measurable at all — nothing
          here is validated against ground truth until you do.
        </p>
      )}

      <div className="phenomena-controls">
        <div className="phenomena-filters">
          {kinds.map((kind) => (
            <button
              key={kind}
              type="button"
              className={hidden.has(kind) ? "kind-chip kind-chip-off" : "kind-chip"}
              aria-pressed={!hidden.has(kind)}
              title={KIND_HINT[kind] ?? kind}
              onClick={() => toggle(kind)}
            >
              {kind} <span className="kind-count">{phenomena.filter((p) => p.kind === kind).length}</span>
            </button>
          ))}
        </div>
        <button type="button" className="zoom-button" onClick={() => setOrder(order === "charge" ? "time" : "charge")}>
          {order === "charge" ? "Größte Ladung zuerst" : "In time order"}
        </button>
      </div>

      <ul className="phenomena-list">
        {visible.slice(0, 200).map((p) => {
          const segment = segmentAt(p.t_start);
          return (
            <li
              key={p.id}
              className="phenomenon-row"
              // The whole row seeks. Keyboard users get the same via the time button below, so
              // the row itself stays a plain <li> rather than nesting the verdict buttons
              // inside an interactive element.
              onClick={() => onSeek?.(p.t_start)}
            >
              <button
                type="button"
                className="phenomenon-time"
                title="Jump the player here"
                onClick={(event) => {
                  event.stopPropagation();
                  onSeek?.(p.t_start);
                }}
              >
                {formatTime(p.t_start)}
              </button>
              <span className={`phenomenon-kind kind-${p.kind.toLowerCase()}`} title={KIND_HINT[p.kind] ?? ""}>
                {p.kind}
              </span>
              <span className="phenomenon-name">{KIND_LABEL[p.kind] ?? p.kind}</span>
              <span className="phenomenon-magnitude">
                {p.amplitude_a != null ? `${p.amplitude_a.toFixed(1)}A` : ""}
                {p.amplitude_lp != null && (
                  <span className="phenomenon-lp"> {p.amplitude_lp >= 0 ? "+" : ""}{p.amplitude_lp.toFixed(3)} LP</span>
                )}
              </span>
              {segment && <span className="phenomenon-segment">{segment.label}</span>}
              {p.stimulus_locked === false && (
                <span
                  className="phenomenon-unlocked"
                  title="No utterance ended in the 1–6 s before this. In a solo session that usually just means you were working quietly, so it lowers confidence rather than excluding it."
                >
                  unlocked
                </span>
              )}
              {recordingId && (
                <span className="phenomenon-verdict">
                  <button
                    type="button"
                    className={labels[p.id] === "confirmed" ? "verdict-button verdict-yes" : "verdict-button"}
                    aria-pressed={labels[p.id] === "confirmed"}
                    title="This is real. Click again to clear."
                    onClick={(event) => {
                      event.stopPropagation();
                      setVerdict(p.id, "confirmed");
                    }}
                  >
                    ✓
                  </button>
                  <button
                    type="button"
                    className={labels[p.id] === "rejected" ? "verdict-button verdict-no" : "verdict-button"}
                    aria-pressed={labels[p.id] === "rejected"}
                    title="This is not real. Click again to clear."
                    onClick={(event) => {
                      event.stopPropagation();
                      setVerdict(p.id, "rejected");
                    }}
                  >
                    ✗
                  </button>
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {visible.length > 200 && (
        <p className="section-description">Showing the first 200 of {visible.length}.</p>
      )}
    </section>
  );
}
