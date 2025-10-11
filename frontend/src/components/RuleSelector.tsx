interface RuleSelectorProps {
  ruleset: string;
  onRulesetChange: (rule: string) => void;
  preWindow: number;
  postWindow: number;
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
      </div>
    </div>
  );
}
