interface UploadPanelProps {
  onCsvChange: (file: File | null) => void;
  onWavChange: (file: File | null) => void;
  csvName?: string | null;
  wavName?: string | null;
  parseError?: string | null;
}

export function UploadPanel({ onCsvChange, onWavChange, csvName, wavName, parseError }: UploadPanelProps) {
  return (
    <div className="card">
      <h2>Session uploads</h2>
      <p className="muted">Provide a GSR CSV export and the synchronized WAV recording. The files stay on this machine.</p>
      <div className="field-list">
        <label className="file-field">
          <span>Galvanic skin response CSV</span>
          <input type="file" accept=".csv" onChange={(event) => onCsvChange(event.target.files?.[0] ?? null)} />
          <span className="file-name">{csvName ?? "No file selected"}</span>
        </label>
        <label className="file-field">
          <span>Aligned audio WAV</span>
          <input type="file" accept="audio/wav" onChange={(event) => onWavChange(event.target.files?.[0] ?? null)} />
          <span className="file-name">{wavName ?? "No file selected"}</span>
        </label>
      </div>
      {parseError && <p className="error-text">{parseError}</p>}
    </div>
  );
}
