"""L0 conditioning: map an arbitrary GSR export onto a canonical continuous LP channel.

`LP` (Ladungspegel) is the MindWalking charge level, 1.0–6.5, and it is the scale the whole
method is defined on: the 0.05 device granularity, "3A" deflections, the four charge zones.
It is *log* resistance — measured on the reference recordings,
``ln R[kOhm] = 1.0157 * LP - 1.0045`` (r^2 = 0.988), i.e. roughly x2.76 per LP unit.

Analysing raw kOhm therefore makes every threshold depend on where in the session it lands: the
same physiological event produces ~15x the kOhm delta at LP 5.5 that it does at LP 2.5. Everything
downstream works on LP for that reason.

See `docs/mindwalking-domain.md` §1 and §4, and `docs/phenomena-detection-design.md` §2.

This module is the *single* place channel selection happens. `frontend/src/utils/gsrParser.ts`
implements the same resolution order for the live preview; `tests/test_conditioning.py` and the
frontend's parser test both check the shared golden fixture in `tests/fixtures/` so the two cannot
drift apart again unnoticed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ln R[kOhm] = SLOPE * LP + INTERCEPT, fitted across the reference recordings. Used only when a
# recording gives us no way to fit its own constants (i.e. no Baseline column to anchor against).
NOMINAL_LN_R_SLOPE = 1.0157
NOMINAL_LN_R_INTERCEPT = -1.0045

# The device's own smallest quoted unit, and the step the auto-tracking Baseline column moves in.
LP_DEVICE_STEP = 0.05

LP_MIN = 1.0
LP_MAX = 6.5

# Matches `time_ms`, `Time(msec)`, `t millis` — but not `timestamp`, where the "ms" is
# preceded by a letter. Longest alternative first so `msec` is not shadowed by `ms`.
_MS_COLUMN_RE = re.compile(r"(^|[^a-z])(milliseconds?|millis|msec|ms)([^a-z]|$)", re.IGNORECASE)


class ChannelResolutionError(ValueError):
    """The export carries no channel we can turn into a charge level."""


@dataclass(frozen=True)
class ChannelResolution:
    """The canonical signal, plus how we arrived at it."""

    time_sec: np.ndarray
    lp: np.ndarray
    strategy: str
    resolution_lp: float
    """Smallest LP step actually representable in the source data. 0.05 means the Baseline
    staircase; ~1e-4 means the raw ADC channel."""
    source_columns: dict[str, str]
    notes: list[str] = field(default_factory=list)
    measured_resistance_kohm: np.ndarray | None = None
    """The device's own resistance column, when the export has one. Preferred over reconstructing
    it from LP: the nominal calibration is an average across recordings and is ~0.3 LP off on any
    individual device, which would show as a visibly wrong kOhm reading."""

    @property
    def quantised(self) -> bool:
        """True when the source is the coarse 0.05 staircase rather than a continuous channel."""
        return self.resolution_lp >= LP_DEVICE_STEP / 2

    def resistance_kohm(self) -> np.ndarray:
        """Resistance for display: measured where available, else reconstructed from LP."""
        if self.measured_resistance_kohm is not None:
            return self.measured_resistance_kohm
        return np.exp(NOMINAL_LN_R_SLOPE * self.lp + NOMINAL_LN_R_INTERCEPT)


def _find_column(columns: Sequence[str], *needles: str) -> str | None:
    """First column whose lowercased name contains any needle. Order of `columns` decides ties."""
    for column in columns:
        lowered = str(column).strip().lower()
        if any(needle in lowered for needle in needles):
            return str(column)
    return None


def time_divisor(times: pd.Series, column_name: str) -> float:
    """Decide whether the time column is seconds or milliseconds.

    The sample *interval* is the reliable signal, not the maximum. The old "max > 1000 means
    milliseconds" rule silently compressed any recording longer than ~16.7 minutes logged in
    seconds: a 30-minute session became 1.8 seconds, wrecking event timing and the min-gap rule.
    Biosignal exports are sampled at 1 Hz or faster, so a median step of >= 1 unit cannot be
    seconds.
    """
    if _MS_COLUMN_RE.search(column_name):
        return 1000.0

    steps = times.diff().dropna()
    steps = steps[steps > 0]
    if steps.empty:
        return 1.0

    median_step = float(steps.median())
    if median_step >= 1.0:
        logger.info("Time column %r looks like milliseconds (median step %.3f)", column_name, median_step)
        return 1000.0
    return 1.0


def _observed_resolution(values: np.ndarray) -> float:
    """Smallest step the data actually moves in — the practical quantisation of the channel."""
    steps = np.abs(np.diff(np.unique(values)))
    steps = steps[steps > 0]
    if steps.size == 0:
        return 0.0
    return float(np.median(steps))


def _fit_linear(x: np.ndarray, y: np.ndarray) -> tuple[float, float] | None:
    """Least-squares `y = a*x + b`, or None if `x` does not vary enough to constrain it."""
    if x.size < 2 or np.unique(x).size < 2:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    if not np.isfinite(slope) or not np.isfinite(intercept) or slope == 0:
        return None
    return float(slope), float(intercept)


def resolve_lp(df: pd.DataFrame) -> ChannelResolution:
    """Resolve an export to a continuous LP channel.

    Resolution order, best first (`docs/phenomena-detection-design.md` §2.1):

    1. ``Data(16 bit)`` + ``Baseline`` — fit ``Data = k*LP + c`` against the Baseline staircase and
       invert. Preferred: the raw ADC channel is linear in LP at ~1e-4 LP, ~500x finer than
       Baseline, and this makes no assumption about the device's resistance calibration.
    2. ``Resistance`` + ``Baseline`` — fit ``ln R = a*LP + b`` for *this* recording, then invert.
    3. ``Resistance`` alone — same inversion with the nominal constants.
    4. ``Conductance`` alone — reciprocate to resistance, then as (3).
    5. ``Baseline`` alone — already LP, but quantised to 0.05. Flagged.
    """
    columns = [str(c) for c in df.columns]

    time_column = _find_column(columns, "time")
    if time_column is None:
        raise ChannelResolutionError("CSV must contain a time column")

    times = pd.to_numeric(df[time_column], errors="coerce").astype(float)
    time_sec = (times / time_divisor(times, time_column)).to_numpy()

    baseline_column = _find_column(columns, "baseline")
    data_column = _find_column(columns, "data(16", "data (16", "16 bit", "16bit")
    if data_column is None:
        # A bare "data" column is only the ADC channel when a Baseline sits beside it; otherwise
        # it is somebody's generic value column and strategy 3/4 should handle it instead.
        data_column = _find_column(columns, "data") if baseline_column else None
    resistance_column = _find_column(columns, "resistance", "ohm")
    conductance_column = _find_column(columns, "conductance", "siemens")

    def numeric(column: str) -> np.ndarray:
        return pd.to_numeric(df[column], errors="coerce").astype(float).to_numpy()

    baseline = numeric(baseline_column) if baseline_column else None
    measured_resistance = numeric(resistance_column) if resistance_column else None
    notes: list[str] = []

    # --- 1. raw ADC anchored on the baseline staircase -------------------------------------
    if data_column is not None and baseline is not None:
        raw = numeric(data_column)
        valid = np.isfinite(raw) & np.isfinite(baseline)
        fit = _fit_linear(baseline[valid], raw[valid]) if valid.any() else None
        if fit is not None:
            k, c = fit
            lp = (raw - c) / k
            residual = float(np.nanmax(np.abs(lp[valid] - baseline[valid]))) if valid.any() else 0.0
            # The staircase quantises Baseline to 0.05, so a correct fit disagrees with it by at
            # most about half a step plus the within-window needle travel. Much more than that
            # means `data` is not the ADC channel and we should fall through.
            if residual <= 3 * LP_DEVICE_STEP:
                notes.append(
                    f"LP from {data_column!r} anchored on {baseline_column!r} "
                    f"(Data = {k:.1f}*LP + {c:.1f}, max |LP - Baseline| = {residual:.4f})"
                )
                return ChannelResolution(
                    time_sec=time_sec,
                    lp=lp,
                    strategy="data+baseline",
                    resolution_lp=abs(1.0 / k),
                    source_columns={"time": time_column, "data": data_column, "baseline": baseline_column},
                    notes=notes,
                    measured_resistance_kohm=measured_resistance,
                )
            notes.append(
                f"ignored {data_column!r}: fit against {baseline_column!r} is off by "
                f"{residual:.3f} LP, so it is not the raw charge channel"
            )

    # --- 2/3/4. resistance (or conductance) via the log relationship ------------------------
    resistance: np.ndarray | None = None
    resistance_source: str | None = None
    if measured_resistance is not None:
        resistance = measured_resistance
        resistance_source = resistance_column
    elif conductance_column is not None:
        conductance = numeric(conductance_column)
        with np.errstate(divide="ignore", invalid="ignore"):
            resistance = np.where(conductance > 0, 1.0e3 / conductance, np.nan)
        resistance_source = conductance_column
        notes.append(f"derived resistance from {conductance_column!r} (assumed microsiemens)")

    if resistance is not None:
        with np.errstate(divide="ignore", invalid="ignore"):
            ln_r = np.where(resistance > 0, np.log(resistance), np.nan)

        slope, intercept = NOMINAL_LN_R_SLOPE, NOMINAL_LN_R_INTERCEPT
        strategy = "resistance-nominal"
        if baseline is not None:
            valid = np.isfinite(ln_r) & np.isfinite(baseline)
            fit = _fit_linear(baseline[valid], ln_r[valid]) if valid.any() else None
            if fit is not None:
                slope, intercept = fit
                strategy = "resistance+baseline"
                notes.append(
                    f"LP from {resistance_source!r} using this recording's own fit "
                    f"(ln R = {slope:.4f}*LP + {intercept:.4f})"
                )
        if strategy == "resistance-nominal":
            notes.append(
                f"LP from {resistance_source!r} using the nominal calibration "
                f"(ln R = {NOMINAL_LN_R_SLOPE}*LP {NOMINAL_LN_R_INTERCEPT:+}); "
                "no Baseline column to fit against"
            )

        lp = (ln_r - intercept) / slope
        source = {"time": time_column, "resistance": str(resistance_source)}
        if baseline_column and strategy == "resistance+baseline":
            source["baseline"] = baseline_column
        return ChannelResolution(
            time_sec=time_sec,
            lp=lp,
            strategy=strategy,
            resolution_lp=_observed_resolution(lp[np.isfinite(lp)]),
            source_columns=source,
            notes=notes,
            measured_resistance_kohm=measured_resistance,
        )

    # --- 5. the baseline staircase on its own ----------------------------------------------
    if baseline is not None:
        notes.append(
            f"LP read directly from {baseline_column!r}; this column is quantised to "
            f"{LP_DEVICE_STEP} LP, so fine deflections are not recoverable"
        )
        return ChannelResolution(
            time_sec=time_sec,
            lp=baseline,
            strategy="baseline",
            resolution_lp=max(_observed_resolution(baseline[np.isfinite(baseline)]), LP_DEVICE_STEP),
            source_columns={"time": time_column, "baseline": baseline_column},
            notes=notes,
        )

    raise ChannelResolutionError(
        "CSV must contain a charge channel: Data(16 bit)+Baseline, Resistance, "
        "Conductance, or Baseline"
    )


def conditioned_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, ChannelResolution]:
    """`resolve_lp` plus the housekeeping every caller needs: drop bad rows, sort by time.

    Returns a frame with `time_sec`, `lp` and `resistance_kohm` (the latter derived from LP, so it
    is consistent with it by construction rather than being a second independent reading).
    """
    resolution = resolve_lp(df)

    frame = pd.DataFrame(
        {
            "time_sec": resolution.time_sec,
            "lp": resolution.lp,
            "resistance_kohm": resolution.resistance_kohm(),
        }
    )
    frame = frame[np.isfinite(frame["time_sec"]) & np.isfinite(frame["lp"])]
    if frame.empty:
        raise ChannelResolutionError("CSV contains no usable samples")
    return frame.sort_values("time_sec").reset_index(drop=True), resolution
