import { useState } from "react";

interface UploadPanelProps {
  onCsvChange: (file: File | null) => void;
  onWavChange: (file: File | null) => void;
  csvName?: string | null;
  wavName?: string | null;
  parseError?: string | null;
}

export function UploadPanel({ onCsvChange, onWavChange, csvName, wavName, parseError }: UploadPanelProps) {
  const [isDraggingCsv, setIsDraggingCsv] = useState(false);
  const [isDraggingWav, setIsDraggingWav] = useState(false);

  const handleCsvDragOver = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDraggingCsv(true);
  };

  const handleCsvDragLeave = () => {
    setIsDraggingCsv(false);
  };

  const handleCsvDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDraggingCsv(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      alert("Please drop a .csv file.");
      return;
    }
    onCsvChange(file);
  };

  const handleWavDragOver = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDraggingWav(true);
  };

  const handleWavDragLeave = () => {
    setIsDraggingWav(false);
  };

  const handleWavDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setIsDraggingWav(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".wav")) {
      alert("Please drop a .wav file.");
      return;
    }
    onWavChange(file);
  };

  return (
    <div className="card">
      <h2>Session uploads</h2>
      <p className="muted">Provide a GSR CSV export and the synchronized WAV recording. The files stay on this machine.</p>
      <div className="field-list">
        <label
          className={`file-field${isDraggingCsv ? " file-field--dragging" : ""}`}
          onDragOver={handleCsvDragOver}
          onDragLeave={handleCsvDragLeave}
          onDrop={handleCsvDrop}
        >
          <span>Galvanic skin response CSV</span>
          {/*
            The MIME types are load-bearing, not decoration. In the desktop shell WKWebView
            reports only `_acceptedMIMETypes()` to pywebview's open-panel delegate, and an
            extension-only accept list yields an *empty* array — so `.csv` alone produced no
            filter at all and the dialog listed every file. `text/csv` maps to the
            `public.comma-separated-values-text` UTI, which is what actually narrows the panel.
            The bare `.csv` still matters for browsers and for Windows/Linux.

            `application/vnd.ms-excel` is deliberately absent: macOS maps it to
            `com.microsoft.excel.xls`, which would let .xls files through.
          */}
          <input
            type="file"
            accept=".csv,text/csv,text/comma-separated-values"
            onChange={(event) => onCsvChange(event.target.files?.[0] ?? null)}
          />
          <span className="file-name">{csvName ?? "No file selected — drag &amp; drop or click to browse"}</span>
        </label>
        <label
          className={`file-field${isDraggingWav ? " file-field--dragging" : ""}`}
          onDragOver={handleWavDragOver}
          onDragLeave={handleWavDragLeave}
          onDrop={handleWavDrop}
        >
          <span>Aligned audio WAV</span>
          <input type="file" accept=".wav,audio/wav,audio/x-wav,audio/wave" onChange={(event) => onWavChange(event.target.files?.[0] ?? null)} />
          <span className="file-name">{wavName ?? "No file selected — drag &amp; drop or click to browse"}</span>
        </label>
      </div>
      {parseError && <p className="error-text">{parseError}</p>}
    </div>
  );
}
