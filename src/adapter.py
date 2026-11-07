"""Provider-agnostic ModelAdapter.

One contract for every provider:  complete(prompt) -> text  /  complete_json(prompt) -> parsed.
Swapping provider or model is one argument — the pipeline never changes.

Providers:
    claude  — Anthropic SDK (tested)
    gemini  — google-genai SDK (free tier; tested on gemini-3.8-flash)
    openai  — stub; drop in a key + impl to enable

JSON is enforced by prompt + robust extraction, which is portable across
providers and SDK versions. Each provider's native structured-output mode is a
later hardening, not required for correctness here.
"""
from __future__ import annotations

import json
import os
import re

_DEFAULT_MODEL = {
    "claude": "claude-sonnet-5-5",
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-5",
}


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if v and not os.environ.get(k):
                os.environ[k] = v


def _extract_json(text: str):
    """Pull the first JSON value out of a model reply (handles ``` fences / prose)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # fall back: first balanced [...] or {...}
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = t.find(open_c), t.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    raise ValueError("No JSON found in model reply:\n" + text[:500])


class ModelAdapter:
    def __init__(self, provider: str = "claude", model: str | None = None,
                 max_tokens: int = 8192, thinking: bool = False,
                 api_key: str | None = None, base_url: str | None = None):
        load_dotenv()
        self.provider = provider
        self.model = model or _DEFAULT_MODEL.get(provider)
        self.max_tokens = max_tokens
        self.thinking = thinking
        # api_key/base_url: optional per-call overrides (e.g. a key typed into the
        # UI). Held in memory only — never written to disk, never logged.
        self.api_key = api_key or None
        self.base_url = base_url or None
        self._client = None
        self.last_usage = {}

    # ---- providers -------------------------------------------------------
    def _complete_claude(self, prompt: str, system: str | None) -> str:
        if self._client is None:
            from anthropic import Anthropic
            kw = {}
            if self.api_key:
                kw["api_key"] = self.api_key
            if self.base_url:
                kw["base_url"] = self.base_url
            self._client = Anthropic(**kw)
        kwargs = dict(model=self.model, max_tokens=self.max_tokens,
                      messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        r = self._client.messages.create(**kwargs)
        self.last_usage = {"in": r.usage.input_tokens, "out": r.usage.output_tokens}
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

    def _complete_gemini(self, prompt: str, system: str | None) -> str:
        if self._client is None:
            from google import genai
            key = self.api_key or os.environ.get("GOOGLE_API_KEY")
            if not key:
                raise RuntimeError("No Gemini key: set GOOGLE_API_KEY or pass a key in.")
            self._client = genai.Client(api_key=key)
        contents = (system + "\n\n" + prompt) if system else prompt
        r = self._client.models.generate_content(model=self.model, contents=contents)
        u = getattr(r, "usage_metadata", None)
        self.last_usage = {"in": getattr(u, "prompt_token_count", None),
                           "out": getattr(u, "candidates_token_count", None)} if u else {}
        return r.text

    def _complete_openai(self, prompt: str, system: str | None) -> str:
        raise NotImplementedError(
            "OpenAI provider is a stub. Add OPENAI_API_KEY and implement "
            "_complete_openai with the official openai SDK to enable.")

    # ---- public API ------------------------------------------------------
    def complete(self, prompt: str, system: str | None = None) -> str:
        fn = getattr(self, f"_complete_{self.provider}", None)
        if fn is None:
            raise ValueError(f"Unknown provider: {self.provider}")
        return fn(prompt, system)

    def complete_json(self, prompt: str, system: str | None = None):
        return _extract_json(self.complete(prompt, system))

    def __repr__(self):
        return f"ModelAdapter(provider={self.provider!r}, model={self.model!r})"


if __name__ == "__main__":
    # smoke test (costs a fraction of a cent)
    a = ModelAdapter()
    print(a)
    out = a.complete_json('Return JSON: {"ok": true}. Only JSON.')
    print("reply:", out, "| usage:", getattr(a, "last_usage", None))
