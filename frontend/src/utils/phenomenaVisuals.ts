/**
 * Colours and labels shared between the phenomena list and the timeline markers.
 *
 * They have to agree: the filter chips in the list toggle the markers in the plot, so a `BE`
 * marker that is not the same colour as its `BE` chip makes the connection invisible.
 */

export const KIND_COLOR: Record<string, string> = {
  A: "#3b82f6",
  T: "#64748b",
  BE: "#f59e0b",
  LPA_slow: "#a855f7",
  X: "#ef4444",
  KVZ: "#06b6d4",
  KB: "#6b7280",
  SN: "#ec4899",
  FN: "#22c55e"
};

export const KIND_LABEL: Record<string, string> = {
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

/** Short badge text. `LPA_slow` is our internal discriminator; the manual says `LPA`. */
export const KIND_BADGE: Record<string, string> = { LPA_slow: "LPA" };

export function kindColor(kind: string): string {
  return KIND_COLOR[kind] ?? "#f59e0b";
}
