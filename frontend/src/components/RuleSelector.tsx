interface RuleSelectorProps {
  ruleset: string;
  onRulesetChange: (rule: string) => void;
  preWindow: number;
  postWindow: number;
  lpOffset: string;
  aUnitLp: string;
  onLpOffsetChange: (value: string) => void;
  onAUnitLpChange: (value: string) => void;
  onPreWindowChange: (value: number) => void;
  onPostWindowChange: (value: number) => void;
}

const RULESET_OPTIONS = [
  { id: "default", label: "Balanced" },
  { id: "sensitive", label: "Sensitive" },
  { id: "strict", label: "Strict" }
];

export function RuleSelector({
  ruleset,
  onRulesetChange,
  preWindow,
  postWindow,
  lpOffset,
  aUnitLp,
  onLpOffsetChange,
  onAUnitLpChange,
  onPreWindowChange,
  onPostWindowChange
}: RuleSelectorProps) {
  return (
    <div className="card">
      <h2>Detection rules</h2>
      <p className="muted">
        Choose how aggressively NeuroNarrative should flag physiological events and define the context windows.
      </p>
      <div className="field-list">
        <label>
          <span>Ruleset preset</span>
          <select value={ruleset} onChange={(event) => onRulesetChange(event.target.value)}>
            {RULESET_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <div className="grid">
          <label>
            <span>Pre-event window (s)</span>
            <input
              type="number"
              min={0}
              step={0.5}
              value={preWindow}
              onChange={(event) => onPreWindowChange(Number(event.target.value))}
            />
          </label>
          <label>
            <span>Post-event window (s)</span>
            <input
              type="number"
              min={0}
              step={0.5}
              value={postWindow}
              onChange={(event) => onPostWindowChange(Number(event.target.value))}
            />
          </label>
        </div>

        {/*
          The operator's own calibration numbers, both optional and both meaningful by their
          absence. Without the offset no charge zone is named at all, because a single-hand solo
          electrode reads a whole session as Kampfzone; without the A-unit every magnitude is
          flagged as an estimate. See docs/phenomena-detection-design.md §4.
        */}
        <div className="calibration-fields">
          <label>
            <span title="Solo-electrode offset in LP, measured at session start as 'Dif.'. Leave empty and no charge zone is named.">
              Solo offset (LP)
            </span>
            <input
              type="number"
              step={0.05}
              placeholder="none"
              value={lpOffset}
              onChange={(event) => onLpOffsetChange(event.target.value)}
            />
          </label>
          <label>
            <span title="One scale division (1A) in LP, from the Dosendruck calibration. Leave empty for an estimated scale.">
              A-unit (LP)
            </span>
            <input
              type="number"
              min={0}
              step={0.005}
              placeholder="estimated"
              value={aUnitLp}
              onChange={(event) => onAUnitLpChange(event.target.value)}
            />
          </label>
        </div>
      </div>
    </div>
  );
}
