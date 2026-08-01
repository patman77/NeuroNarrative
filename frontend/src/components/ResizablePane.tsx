import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A scrollable pane the operator can drag taller or shorter.
 *
 * Uses the native CSS `resize` handle rather than a hand-rolled drag: it is one line, it is
 * accessible, and it behaves the way the rest of the OS does. `resize` only works on an element
 * whose `overflow` is not `visible`, which is why the scrolling and the handle live on the same
 * element.
 *
 * The height persists per `storageKey`. Without that, a long session means re-dragging the same
 * pane after every analysis, which is exactly the annoyance this is meant to remove.
 */

interface Props {
  storageKey: string;
  defaultHeight: number;
  minHeight?: number;
  children: React.ReactNode;
}

const STORAGE_PREFIX = "neuronarrative.paneHeight.";

function readStored(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + key);
    const parsed = raw ? Number(raw) : NaN;
    // Guard the stored value: a corrupt or absurd entry would otherwise make the pane unusable
    // with no obvious way for the user to recover it.
    return Number.isFinite(parsed) && parsed >= 80 && parsed <= 4000 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function ResizablePane({ storageKey, defaultHeight, minHeight = 120, children }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [height] = useState(() => readStored(storageKey, defaultHeight));

  const persist = useCallback(
    (value: number) => {
      try {
        window.localStorage.setItem(STORAGE_PREFIX + storageKey, String(Math.round(value)));
      } catch {
        // A full or blocked localStorage must not break resizing itself.
      }
    },
    [storageKey]
  );

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    // The native handle does not fire an event, so observe the box instead.
    const observer = new ResizeObserver(() => persist(element.getBoundingClientRect().height));
    observer.observe(element);
    return () => observer.disconnect();
  }, [persist]);

  return (
    <div
      ref={ref}
      className="resizable-pane"
      style={{ height, minHeight }}
      title="Drag the bottom-right corner to resize"
    >
      {children}
    </div>
  );
}
