/**
 * Scroll animation with acceleration and deceleration.
 *
 * `scrollIntoView({ behavior: "smooth" })` is not usable here: its duration is chosen by the
 * browser and grows with distance, so jumping across a 54-minute timeline could take many
 * seconds — long enough that a second hover arrives mid-flight and the panels disagree about
 * where they are. This caps every move at `MAX_DURATION_MS` and eases in and out, so a short
 * hop feels instant and a long one still lands within a predictable window.
 */

const MAX_DURATION_MS = 2000;
const MIN_DURATION_MS = 180;
/** Below this, jump. Animating a few pixels reads as a glitch rather than a movement. */
const NEGLIGIBLE_PX = 2;

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/** Duration grows with distance but is clamped, so long jumps stay within ~2 s. */
function durationFor(distance: number): number {
  return Math.min(MAX_DURATION_MS, Math.max(MIN_DURATION_MS, Math.abs(distance) * 1.2));
}

export interface ScrollTarget {
  top?: number;
  left?: number;
}

type Cancel = () => void;

/**
 * Animate `element` (or the window, when given `null`) to a scroll offset.
 *
 * Returns a cancel function. Callers should cancel the previous animation before starting a new
 * one — overlapping animations on the same element fight each other and the element judders.
 */
export function animateScroll(element: HTMLElement | null, target: ScrollTarget): Cancel {
  const scroller = element;
  const startTop = scroller ? scroller.scrollTop : window.scrollY;
  const startLeft = scroller ? scroller.scrollLeft : window.scrollX;
  const endTop = target.top ?? startTop;
  const endLeft = target.left ?? startLeft;

  const deltaTop = endTop - startTop;
  const deltaLeft = endLeft - startLeft;
  const distance = Math.max(Math.abs(deltaTop), Math.abs(deltaLeft));

  if (distance < NEGLIGIBLE_PX) {
    return () => undefined;
  }

  const duration = durationFor(distance);
  const started = performance.now();
  let frame = 0;
  let cancelled = false;

  const step = (now: number) => {
    if (cancelled) return;
    const elapsed = now - started;
    const progress = Math.min(1, elapsed / duration);
    const eased = easeInOutCubic(progress);
    const top = startTop + deltaTop * eased;
    const left = startLeft + deltaLeft * eased;

    if (scroller) {
      scroller.scrollTop = top;
      scroller.scrollLeft = left;
    } else {
      window.scrollTo(left, top);
    }

    if (progress < 1) frame = requestAnimationFrame(step);
  };

  frame = requestAnimationFrame(step);
  return () => {
    cancelled = true;
    cancelAnimationFrame(frame);
  };
}

/** Scroll `child` into the middle of its scrollable `container`, vertically.
 *
 * Measured with `getBoundingClientRect` rather than `offsetTop`. `offsetTop` is relative to the
 * nearest *positioned* ancestor, and these lists are not positioned — so it returned an offset
 * measured from somewhere further up the tree and the container scrolled to the wrong place
 * entirely. The row was highlighted correctly the whole time; it just was not on screen, which
 * looks identical to nothing being highlighted.
 */
export function scrollChildIntoView(container: HTMLElement | null, child: HTMLElement | null): Cancel {
  if (!container || !child) return () => undefined;
  const containerRect = container.getBoundingClientRect();
  const childRect = child.getBoundingClientRect();
  const offsetWithinContainer = childRect.top - containerRect.top + container.scrollTop;
  const target = offsetWithinContainer - container.clientHeight / 2 + childRect.height / 2;
  const clamped = Math.max(0, Math.min(target, container.scrollHeight - container.clientHeight));
  return animateScroll(container, { top: clamped });
}
