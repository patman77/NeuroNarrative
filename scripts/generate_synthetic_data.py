import numpy as np
import pandas as pd
import soundfile as sf
import os

def generate_data():
    # 1. Generate Synthetic GSR (CSV)
    # 10 Hz sampling rate, 60 seconds
    sr_gsr = 10
    duration = 60
    t = np.arange(0, duration, 1/sr_gsr)
    
    # Baseline 3.0 kOhm
    resistance = 3.0 + np.random.normal(0, 0.05, size=len(t))
    
    # Add a few peaks (events)
    # Event at 10s
    resistance[100:120] += np.linspace(0, 1.5, 20)
    resistance[120:150] -= np.linspace(0, 1.5, 30)
    
    # Event at 30s
    resistance[300:320] += np.linspace(0, 2.0, 20)
    resistance[320:350] -= np.linspace(0, 2.0, 30)

    df = pd.DataFrame({
        'time': t,
        'resistance': resistance
    })
    
    csv_path = 'test_gsr.csv'
    df.to_csv(csv_path, index=False)
    print(f"Generated {csv_path}")

    # 2. Generate Synthetic Audio (WAV)
    # 16kHz, mono
    sr_audio = 16000
    t_audio = np.arange(0, duration, 1/sr_audio)
    # Simple sine wave
    audio = 0.5 * np.sin(2 * np.pi * 440 * t_audio)
    
    wav_path = 'test_audio.wav'
    sf.write(wav_path, audio, sr_audio)
    print(f"Generated {wav_path}")

if __name__ == "__main__":
    generate_data()
