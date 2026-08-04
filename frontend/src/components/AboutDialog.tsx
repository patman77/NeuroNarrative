import { useEffect, useRef } from "react";
import { APP_VERSION, AUTHOR, BUILD_DATE, BUILD_YEAR, IS_DEV_BUILD } from "../buildInfo";

/**
 * About box: which build this is, and who it belongs to.
 *
 * A native `<dialog>` rather than a hand-rolled overlay — it brings the backdrop, focus
 * trapping, Escape-to-close and the top layer with it, none of which are worth reimplementing.
 * `showModal()` has to be called imperatively, hence the ref and the effect: React has no
 * declarative prop for it.
 */

interface Props {
  open: boolean;
  onClose: () => void;
  /** What the backend reports, when it is reachable. Null while offline or still checking. */
  summarizerStatus?: string | null;
  backendOnline?: boolean | null;
}

export function AboutDialog({ open, onClose, summarizerStatus, backendOnline }: Props) {
  const ref = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      className="about-dialog"
      ref={ref}
      // Fires for Escape as well as close(), so the parent's state cannot drift out of step
      // with whether the dialog is actually showing.
      onClose={onClose}
      // A click on the backdrop lands on the dialog element itself, not on its contents.
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      aria-labelledby="about-title"
    >
      <div className="about-body">
        <h2 id="about-title">NeuroNarrative</h2>
        <p className="about-tagline">
          Aligns GSR recordings with the spoken session, finds the physiologically significant
          moments and writes them up. Everything runs on this machine — no recording is uploaded.
        </p>

        <dl className="about-facts">
          <dt>Version</dt>
          <dd>
            {APP_VERSION}
            {IS_DEV_BUILD && <span className="about-badge">unreleased build</span>}
          </dd>
          <dt>Built</dt>
          <dd>{BUILD_DATE}</dd>
          {backendOnline != null && (
            <>
              <dt>Backend</dt>
              <dd>{backendOnline ? "online" : "offline"}</dd>
            </>
          )}
          {summarizerStatus && (
            <>
              <dt>Summariser</dt>
              <dd>{summarizerStatus}</dd>
            </>
          )}
        </dl>

        <p className="about-copyright">
          © {BUILD_YEAR} {AUTHOR}. All rights reserved.
        </p>

        <div className="about-actions">
          <button type="button" onClick={onClose} autoFocus>
            Close
          </button>
        </div>
      </div>
    </dialog>
  );
}
