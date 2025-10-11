from __future__ import annotations

import json
from typing import Any

import httpx

from ..core.config import Settings

SYSTEM_PROMPT = """You are a careful summarizer.\n- Work ONLY with the provided transcript excerpt.\n- Output 1 sentence, <= 20 words.\n- Keep numbers and proper nouns exact.\n- No speculation. No new facts.\n- If excerpt is too short or unclear, output: NONE\nReturn JSON: {\"summary\": \"<string or 'NONE'>\"}\n"""


async def summarize_with_local_llm(text: str, settings: Settings) -> str | None:
    cleaned = text.strip()
    if len(cleaned.split()) < 6:
        return None

    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "system": SYSTEM_PROMPT,
        "prompt": (
            "Transcript (timestamps removed):\n" """\n{cleaned}\n"""\nSummarize as one short sentence (<= 20 words). If unclear or mostly fillers, output: NONE"
        ),
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_predict": 128,
        },
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(settings.ollama_url, json=payload)
        response.raise_for_status()
        data = response.json()
        result = data.get("response", "").strip()

    try:
        parsed = json.loads(result)
        return parsed.get("summary")
    except json.JSONDecodeError:
        if not result:
            return None
        first_line = result.splitlines()[0].strip().strip('"')
        words = first_line.split()
        return " ".join(words[:20]) if words else None
