import requests
import sys
import time

def test_api():
    base_url = "http://localhost:8000/api"
    
    # 1. Upload
    print("Uploading files...")
    files = {
        'gsr': ('test_gsr.csv', open('test_gsr.csv', 'rb'), 'text/csv'),
        'audio': ('test_audio.wav', open('test_audio.wav', 'rb'), 'audio/wav')
    }
    try:
        r = requests.post(f"{base_url}/upload", files=files)
        r.raise_for_status()
        upload_data = r.json()
        print("Upload successful:", upload_data)
    except Exception as e:
        print(f"Upload failed: {e}")
        if 'r' in locals():
            print(r.text)
        sys.exit(1)

    # 2. Analyze
    print("Analysis requested...")
    payload = {
        "csv_path": upload_data['csv_path'],
        "wav_path": upload_data['wav_path'],
        "ruleset_name": "default",
        "pre_event_window_sec": 5,
        "post_event_window_sec": 7
    }
    
    # Analysis runs as a background job; poll until it settles.
    try:
        r = requests.post(f"{base_url}/analyze", json=payload)
        r.raise_for_status()
        job_id = r.json()["job_id"]

        while True:
            time.sleep(1)
            status = requests.get(f"{base_url}/analyze/{job_id}")
            status.raise_for_status()
            job = status.json()
            print(f"  {job['stage']}: {job['progress'] * 100:.0f}%", end="\r")
            if job["status"] == "done":
                break
            if job["status"] == "error":
                raise RuntimeError(job["error"])

        analysis_data = job["result"]
        print("\nAnalysis successful!")
        print(f"Events found: {len(analysis_data.get('events', []))}")
        print("Metadata:", analysis_data.get('gsr_metadata'))
    except Exception as e:
        print(f"Analysis failed: {e}")
        if 'r' in locals():
            print(r.text)
        sys.exit(1)

if __name__ == "__main__":
    test_api()
