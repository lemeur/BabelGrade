"""LLM client for the BabelGrade.

Targets the SGLang OpenAI-compatible endpoint that serves qwen38-27b.
- chat_json: non-streaming call, best-effort JSON extraction
- stream_chat: server-sent-events generator for live UI display
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BABELGRADE_LLM_BASE", "http://127.0.0.1:8078/v1")
MODEL = os.environ.get("BABELGRADE_LLM_MODEL", "qwen38-27b")
API_KEY = os.environ.get("BABELGRADE_LLM_API_KEY", "")

_TIMEOUT = 600
_MAX_RETRIES = 3


def _post(path: str, body: dict, timeout: int = _TIMEOUT) -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post_stream(path: str, body: dict, timeout: int = _TIMEOUT):
    """Yield raw SSE lines. Caller closes the response."""
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(
        BASE_URL + path, data=json.dumps(body).encode(), headers=headers, method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def extract_json(text: str):
    """Best-effort: pull the first JSON object/array out of a model reply."""
    if not text:
        return None
    text = text.strip()
    # strip code fences if present
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    candidates = [m.group(1).strip()] if m else []
    candidates.append(text)
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception:
            pass
    # brace/bracket balancing scan
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cand.find(opener)
        depth = 0
        for i in range(start, len(cand)):
            ch = cand[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cand[start:i + 1])
                    except Exception:
                        break
        cand = text  # next candidate uses original text
    return None


def chat(messages: list[dict], *, temperature: float = 0.1,
         max_tokens: int = 2000, timeout: int = _TIMEOUT,
         thinking_budget: int | None = None) -> dict:
    """Non-streaming chat. Returns {content, usage, raw, truncated}.

    thinking_budget: optional cap on the model's reasoning tokens (SGLang
    `thinking_budget`). Keeps structured-output tasks from spending the whole
    token cap on extended reasoning."""
    body = {"model": MODEL, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": False}
    if thinking_budget is not None:
        body["thinking_budget"] = thinking_budget
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            data = _post("/chat/completions", body, timeout=timeout)
            choice = data["choices"][0]
            return {"content": choice["message"].get("content") or "",
                    "usage": data.get("usage") or {}, "raw": data,
                    "truncated": choice.get("finish_reason") == "length"}
        except urllib.error.HTTPError as e:
            last_err = e
            if 400 <= e.code < 500:
                break  # do not retry client errors
        except Exception as e:
            last_err = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM call failed: {last_err}")


def stream_chat(messages: list[dict], *, temperature: float = 0.1,
                max_tokens: int = 2000, timeout: int = _TIMEOUT,
                thinking_budget: int | None = None,
                truncated: dict | None = None):
    """Generator yielding text deltas from an SSE chat completion.

    thinking_budget: optional cap on the model's reasoning tokens (SGLang).
    truncated: optional dict — set to {"truncated": bool} when the stream ends
    (True when finish_reason == "length")."""
    body = {"model": MODEL, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": True}
    if thinking_budget is not None:
        body["thinking_budget"] = thinking_budget
    resp = _post_stream("/chat/completions", body, timeout=timeout)
    finish_reason: str | None = None
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choice = (data.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            piece = delta.get("content")
            if piece:
                yield piece
    finally:
        if truncated is not None:
            truncated["truncated"] = finish_reason == "length"
        try:
            resp.close()
        except Exception:
            pass


def health() -> dict:
    try:
        with urllib.request.urlopen(BASE_URL.rstrip("/v1") + "/v1/models", timeout=8) as r:
            models = json.load(r).get("data", [])
        return {"ok": True, "model": MODEL,
                "models": [m.get("id") for m in models], "base_url": BASE_URL}
    except Exception as e:
        return {"ok": False, "error": str(e), "base_url": BASE_URL}
