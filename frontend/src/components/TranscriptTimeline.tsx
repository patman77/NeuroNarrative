import type { TranscriptWord } from "../App";

interface TranscriptTimelineProps {
  transcript: TranscriptWord[];
  onSeek?: (time: number) => void;
}

function formatTime(sec: number): string {
  if (!Number.isFinite(sec)) return "—";
  const mins = Math.floor(sec / 60);
  const secs = (sec % 60).toFixed(1).padStart(4, "0");
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

const WORDS_PER_LINE = 10;

export function TranscriptTimeline({ transcript, onSeek }: TranscriptTimelineProps) {
  if (transcript.length === 0) {
    return (
      <div className="card">
        <h2>Transcript</h2>
        <div className="transcript-timeline">
          <p className="muted">No transcript available. Run analysis with Whisper installed to see transcription.</p>
        </div>
      </div>
    );
  }

  const lines: TranscriptWord[][] = [];
  for (let i = 0; i < transcript.length; i += WORDS_PER_LINE) {
    lines.push(transcript.slice(i, i + WORDS_PER_LINE));
  }

  return (
    <div className="card">
      <h2>Transcript</h2>
      <div className="transcript-timeline">
        {lines.map((lineWords, lineIdx) => (
          <div key={lineIdx} className="transcript-line">
            {lineWords.map((word, wordIdx) => {
              const hasTime = word.start !== null && Number.isFinite(word.start);
              return (
                <span
                  key={wordIdx}
                  className="transcript-word"
                  title={hasTime ? formatTime(word.start as number) : undefined}
                  onClick={hasTime && onSeek ? () => onSeek(word.start as number) : undefined}
                  style={!hasTime ? { cursor: "default" } : undefined}
                >
                  {word.text}{" "}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
