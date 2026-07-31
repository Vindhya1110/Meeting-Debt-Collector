"""
All LLM calls go through this file, split across two providers:

  Groq (provider="groq")        — fast, low-latency. Used for everything on the
                                   live/frequent path: extraction, resolution,
                                   agenda matching (every ~30s chunk), and nudge/
                                   reassignment message generation (must not
                                   block the watch-loop thread).
  Featherless (default)         — used for one-shot, end-of-meeting generation
                                   where its slower serverless latency doesn't
                                   hurt: MoM, pattern report, pre-brief.

Both are OpenAI-compatible, so one client class handles both via base_url.

Note: Featherless's exact spec model IDs (meta-llama/Meta-Llama-3.1-70B-Instruct
and meta-llama/Llama-3.1-8B-Instruct) are gated behind HuggingFace org
verification on this account. Defaults here point at unsloth's un-gated
mirrors of the exact same weights instead.
"""
import os
import json
from openai import OpenAI
from mock_mode import MOCK_RESPONSES

MOCK = os.getenv("MOCK_MODE", "false").lower() == "true"

_featherless_client = OpenAI(
    base_url=os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"),
    api_key=os.getenv("FEATHERLESS_API_KEY", ""),
)
_groq_client = OpenAI(
    base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    api_key=os.getenv("GROQ_API_KEY", ""),
)

MODEL_MAIN = os.getenv("FEATHERLESS_MODEL_MAIN", "unsloth/Meta-Llama-3.1-70B-Instruct")
MODEL_FAST = os.getenv("FEATHERLESS_MODEL_FAST", "unsloth/Meta-Llama-3.1-8B-Instruct")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def call(system: str, user: str, model: str = None,
         temperature: float = 0.1, max_tokens: int = 2000,
         expect_json: bool = True, provider: str = "featherless") -> str:
    """
    Core LLM call. Returns raw string content.
    Caller is responsible for JSON parsing.
    provider: "groq" (fast path) or "featherless" (default, one-shot path).
    """
    if MOCK:
        return MOCK_RESPONSES.get("default", "{}")

    if provider == "groq":
        client = _groq_client
        m = model or GROQ_MODEL
    else:
        client = _featherless_client
        m = model or MODEL_MAIN

    kwargs = dict(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if expect_json:
        kwargs["response_format"] = {"type": "json_object"}

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def call_fast(system: str, user: str,
              temperature: float = 0.7, max_tokens: int = 300,
              expect_json: bool = False, provider: str = "featherless") -> str:
    """Use the fast/small model for simple text generation."""
    if provider == "groq":
        return call(system, user, model=GROQ_MODEL,
                    temperature=temperature, max_tokens=max_tokens,
                    expect_json=expect_json, provider="groq")
    return call(system, user, model=MODEL_FAST,
                temperature=temperature, max_tokens=max_tokens,
                expect_json=expect_json, provider="featherless")


def parse_json(raw: str):
    """Safe JSON parse — strips markdown fences if present, unwraps single-key objects."""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed
    return []


def parse_json_list(raw: str, preferred_key: str = None) -> list:
    """Like parse_json, but always returns a list — unwrapping {"key": [...]} shapes."""
    parsed = parse_json(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if preferred_key and preferred_key in parsed:
            return parsed[preferred_key]
        for v in parsed.values():
            if isinstance(v, list):
                return v
    return []
