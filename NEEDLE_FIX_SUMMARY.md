# Needle Calculation Fix - Summary

## Date: October 20, 2025

## Issue Description
The gauge needle was displaying incorrectly due to baseline interpolation causing floating-point comparison failures in the reference resistance lookup.

## Root Cause Analysis

### Primary Issue: Baseline Interpolation
1. **Baseline was being interpolated linearly** between samples
   - When baseline changed from 5 to 4.95, intermediate values like 4.975 were calculated
   - These interpolated values didn't match any actual sample baselines
   
2. **Reference resistance lookup failed**
   - The `calculateGaugePosition` function searched for samples with matching baseline values
   - Interpolated baseline values (e.g., 4.975) never matched actual sample values (5 or 4.95)
   - This caused the reference resistance to be incorrect or undefined
   
3. **Result: Incorrect needle positioning**
   - Needle pointed to wrong positions
   - Didn't respond correctly to resistance changes
   - Could point to the opposite side of the gauge

## Solutions Implemented

### Fix 1: Baseline as Step Function
**File:** `frontend/src/components/SignalPreview.tsx` (Lines 107-108)

**Change:**
```typescript
// BEFORE:
baseline: lower.baseline !== undefined && upper.baseline !== undefined
  ? lower.baseline + (upper.baseline - lower.baseline) * clampedRatio
  : lower.baseline ?? upper.baseline,

// AFTER:
// Baseline is a step function (changes only on normalize), so use lower sample's baseline
baseline: lower.baseline,
```

**Rationale:**
- Baseline only changes when user presses "normalize" button
- It should jump to new values instantly, not transition smoothly
- This eliminates floating-point comparison issues

### Fix 2: Improved Reference Resistance Lookup
**File:** `frontend/src/components/SignalPreview.tsx` (Lines 134-161)

**Changes:**
- Rewrote lookup logic with forward iteration (clearer than backward)
- Added explicit checks for undefined baseline/resistance values
- Handles baseline periods that oscillate (baseline changes back and forth)
- Finds the most recent baseline change point correctly

**Key Logic:**
```typescript
// Look through samples up to current time
for (let i = 0; i < samples.length; i++) {
  const s = samples[i];
  
  // Only look at samples up to current time
  if (s.timeSec > sample.timeSec) break;
  
  // Check if this sample has valid baseline and resistance
  if (s.baseline === undefined || s.resistance === undefined) continue;
  
  // Check if this is the start of a baseline period
  if (s.baseline === sample.baseline) {
    if (i === 0 || samples[i - 1].baseline !== sample.baseline) {
      // Found baseline change point
      referenceResistance = s.resistance;
    }
  }
}
```

### Fix 3: Explicit Clamping
**File:** `frontend/src/components/SignalPreview.tsx` (Lines 176, 181)

**Change:**
```typescript
// Ensure needle stays within valid range
return clamp(position, DISPLAY_MIN, DISPLAY_MAX);
```

**Rationale:**
- Prevents needle from going outside 1-6.5 range
- Even if resistance changes dramatically, needle stays visible

## Expected Behavior After Fix

✅ **Baseline as center position**
- When baseline = 5, needle centers at 5 on the gauge
- When baseline changes to 4.95, needle immediately moves to 4.95

✅ **Correct directional movement**
- Resistance DECREASES → needle moves RIGHT (higher gauge value)
- Resistance INCREASES → needle moves LEFT (lower gauge value)

✅ **Proper scaling**
- 1 kΩ resistance change ≈ 0.5 gauge units of needle movement
- Formula: `needlePosition = baseline + (currentResistance - referenceResistance) * (-0.5)`

✅ **Range enforcement**
- Needle stays within 1-6.5 range at all times
- Values are explicitly clamped

✅ **Stable reference tracking**
- Reference resistance correctly tracks baseline periods
- Handles baseline changes (user pressing "normalize")
- Handles baseline oscillations (back and forth changes)

## Testing Results

- ✅ TypeScript compilation successful
- ✅ Production build successful
- ✅ No errors or warnings
- 🔄 Ready for user testing with actual CSV data

## How to Test

1. Upload a CSV file with baseline and resistance columns
2. Play the session
3. Verify needle behavior:
   - Needle should center at the baseline value
   - When resistance decreases, needle should move right
   - When resistance increases, needle should move left
   - When baseline changes (user presses normalize), needle should jump to new baseline
4. Check that the orange baseline marker aligns with expected position

## Technical Details

### Gauge Specifications
- **Range:** 1.0 to 6.5
- **Scale markers:** 2 rectangles = 0.15 units (as per original design)
- **Resistance scale factor:** -0.5 (1 kΩ change ≈ 0.5 gauge units)
- **Direction:** Negative scale ensures resistance decrease = rightward movement

### Data Format
- **Time column:** Time in milliseconds or seconds
- **Baseline column:** Normalized gauge position (1-6.5 range)
- **Resistance column:** Absolute resistance measurements (kΩ)

### Algorithm
1. Parse CSV to extract baseline and resistance values
2. For each time point, get current sample via interpolation
   - Baseline uses step function (no interpolation)
   - Resistance uses linear interpolation
3. Find reference resistance for current baseline period
   - Search forward through samples up to current time
   - Find most recent point where baseline changed to current value
   - Use resistance at that point as reference
4. Calculate needle position:
   - `needlePosition = baseline + (currentResistance - referenceResistance) * (-0.5)`
5. Clamp to valid range (1-6.5)

## Files Modified

1. `frontend/src/components/SignalPreview.tsx`
   - Fixed `useInterpolatedSample` function (baseline interpolation)
   - Rewrote `calculateGaugePosition` function (reference resistance lookup)
   - Added explicit clamping

## Commit Information

**Commit:** 26d395a  
**Branch:** fix-gauge-needle-position  
**PR:** #15  
**Status:** ✅ Pushed to GitHub

## Next Steps

1. User should test with actual CSV files
2. Verify needle displays correctly in all scenarios
3. If behavior is correct, PR can be merged to main branch

## Additional Notes

### Potential Future Improvements
- Add configurable resistance scale factor (currently hardcoded to -0.5)
- Add visual indicator for baseline changes
- Add tooltip showing resistance delta from baseline
- Support for multiple simultaneous baseline tracks

### Known Limitations
- Scale factor (-0.5) is calibrated for typical GSR ranges (50-60 kΩ)
- May need adjustment for different sensor types or resistance ranges
- Assumes CSV data is pre-sorted by time

## Support

For issues or questions:
- GitHub PR: https://github.com/patman77/NeuroNarrative/pull/15
- Repository: https://github.com/patman77/NeuroNarrative

---

**Important GitHub Advisory:**  
To access private repositories, please ensure you've granted permissions to the [GitHub App](https://github.com/apps/abacusai/installations/select_target).
