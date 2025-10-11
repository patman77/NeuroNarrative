interface UploadPanelProps {
  onCsvChange: (file: File | null) => void;
  onWavChange: (file: File | null) => void;
}

export function UploadPanel({ onCsvChange, onWavChange }: UploadPanelProps) {
  return (
    <div className="card">
      <h2>Session uploads</h2>
      <p className="muted">Provide a GSR CSV export and the synchronized WAV recording. The files stay on this machine.</p>
      <div className="field-list">
        <label className="file-field">
          <span>Galvanic skin response CSV</span>
          <input type="file" accept=".csv" onChange={(event) => onCsvChange(event.target.files?.[0] ?? null)} />
        </label>
        <label className="file-field">
          <span>Aligned audio WAV</span>
          <input type="file" accept="audio/wav" onChange={(event) => onWavChange(event.target.files?.[0] ?? null)} />
        </label>
      </div>
    </div>
  );
}
