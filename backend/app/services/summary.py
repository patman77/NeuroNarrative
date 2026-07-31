from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..core.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a careful summarizer.\n- Work ONLY with the provided transcript excerpt.\n- Write the summary in the SAME LANGUAGE as the excerpt. German excerpt -> German summary.\n- Output 1 sentence, <= 20 words.\n- Keep numbers and proper nouns exact.\n- No speculation. No new facts.\n- Excerpts are fragments cut out of a longer session; an incomplete sentence is still worth summarising. Paraphrase what is there.\n- Output NONE only when the excerpt carries no content at all (pure filler, or unintelligible).\nReturn JSON: {\"summary\": \"<string or 'NONE'>\"}\n"""


def _tags_url(generate_url: str) -> str:
    """Derive Ollama's model-list endpoint from the configured generate endpoint."""
    return generate_url.rsplit("/api/", 1)[0] + "/api/tags"


def probe_summarizer(settings: Settings, timeout: float = 3.0) -> tuple[bool, str, str]:
    """Check Ollama and pick a model that actually exists.

    Returns (available, model_to_use, human readable status). The configured model name is
    frequently wrong — a tag like `qwen2.5:7b-instruct-q4_K_M` looks plausible but Ollama
    may only have `qwen2.5:7b` pulled, and asking for a missing model just fails per event
    with no clue why. Preferring a same-family tag keeps summaries working instead.
    """
    try:
        response = httpx.get(_tags_url(settings.ollama_url), timeout=timeout)
        response.raise_for_status()
        installed = [m["name"] for m in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return False, settings.ollama_model, f"Ollama unreachable at {settings.ollama_url} ({exc})"

    if not installed:
        return False, settings.ollama_model, "Ollama is running but has no models pulled"

    wanted = settings.ollama_model
    if wanted in installed:
        return True, wanted, f"using {wanted}"

    family = wanted.split(":", 1)[0]
    same_family = [name for name in installed if name.split(":", 1)[0] == family]
    chosen = same_family[0] if same_family else installed[0]
    return (
        True,
        chosen,
        f"configured model {wanted!r} is not installed; using {chosen!r} instead "
        f"(available: {', '.join(installed)})",
    )


async def summarize_with_local_llm(
    text: str, settings: Settings, resolved_model: str | None = None
) -> str | None:
    cleaned = text.strip()
    if len(cleaned.split()) < settings.summary_min_words:
        return None

    payload: dict[str, Any] = {
        "model": resolved_model or settings.ollama_model,
        "system": SYSTEM_PROMPT,
        "prompt": (
            "Transcript (timestamps removed):\n"
            f"\"\"\"\n{cleaned}\n\"\"\"\n"
            "Summarize as one short sentence (<= 20 words). If unclear or mostly fillers, output: NONE"
        ),
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_predict": 128,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(settings.ollama_url, json=payload)
            response.raise_for_status()
            data = response.json()
            result = data.get("response", "").strip()
    except (httpx.HTTPError, ValueError) as exc:
        # A missing or failing Ollama must not fail the whole analysis: events and
        # transcripts are still useful without summaries.
        logger.warning("Summarisation unavailable (%s): %s", type(exc).__name__, exc)
        return None

    try:
        parsed = json.loads(result)
        return parsed.get("summary")
    except json.JSONDecodeError:
        if not result:
            return None
        first_line = result.splitlines()[0].strip().strip('"')
        words = first_line.split()
        return " ".join(words[:20]) if words else None
