"""Mock OpenAI-compatible LLM server for the BabelGrade E2E test (P2.9).

A tiny stdlib HTTP server that mimics just enough of the SGLang OpenAI
endpoint that ``app/llm_client.py`` talks to:

    POST /v1/chat/completions   -> SSE stream (stream=True) or single JSON
    GET  /v1/models             -> model list (used by /api/health)

It does NOT call any model. Instead, for each chat completion it builds a
deterministic, well-formed response from the request:

* ``analyze`` / ``run_ai``: a JSON object that matches the exact schema the
  app demands (``executive_summary`` / ``overall_level`` / ``rubric_mapping``
  (one entry per criterion, in order, exact names) / ``student_feedback`` /
  ...), with a verbatim evidence quote.
* ``stats_ai``: a class-insight object carrying ``class_level``.

The mock learns the criteria by parsing the prompt the app sends (the user
message embeds "RUBRIC: <name>\\nCriteria:\\n- <criterion>: ..."). A request that
is neither of the known kinds returns a plain JSON object that deliberately
fails the app's schema check — this lets the test prove the job queue marks
such jobs as *parsed=False* yet still ``done`` (the graceful-raw path).

Run standalone (for manual poking):

    python3 tests/mock_llm_server.py [port]

The E2E test (``test_p2_mock_llm_e2e.py``) instead boots it in-process via
``MockLLMServer``.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def user_text_of(body: dict) -> str:
    """Flatten the user message (which may be a multimodal list) to text."""
    for m in body.get("messages", []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list):
            return " ".join(
                part.get("text", "") for part in c if isinstance(part, dict)
            )
        return c if isinstance(c, str) else ""
    return ""


def criteria_from_prompt(text: str) -> list[str]:
    """Extract the ordered criterion names the app embedded in the prompt.

    The app renders them as a block::

        RUBRIC: <name> (mode: <kind>)
        Criteria:
        - <criterion 1>: <description>
        - <criterion 2>: <description>
        ...

    We collect the consecutive "- <name>: ..." lines that follow the first
    "Criteria:" line and stop at the first non-bullet line (or a bullet
    without a ":"). Line-based rather than terminator-based, so it also
    works on a bare prompt with no trailing block.
    """
    lines = text.splitlines()
    crits = []
    seen = False
    for line in lines:
        stripped = line.strip()
        if not seen:
            if "Criteria:" in stripped:
                seen = True
            continue
        if stripped.startswith("- "):
            name = stripped[2:].split(":", 1)[0].strip()
            if name:
                crits.append(name)
        else:
            break  # first non-bullet line ends the criteria block
    return crits


def _verdict_marker(text: str) -> str:
    """Deterministic discriminator the test uses to tell the two analyze
    responses apart (blind first pass vs aware re-run)."""
    return "CONFIRMED-B1" if "REVIEW mode" in text else "FRESH-B1"


def build_analyze_response(text: str, level_map: dict[str, str]) -> dict:
    crits = criteria_from_prompt(text) or ["Criterion"]
    mapping = []
    for name in crits:
        lvl = level_map.get(name, "B1")
        mapping.append({
            "criterion": name,
            "suggested_level": lvl,
            "justification": f"Mock: {name} assessed at {lvl} "
                             f"({_verdict_marker(text)}).",
            "evidence": ["the student's work demonstrates the expected range"],
        })
    return {
        "executive_summary": (
            "Mock executive summary: the candidate shows a consistent "
            f"{level_map.get(crits[0], 'B1')} performance overall. "
            f"[{_verdict_marker(text)}]"),
        "overall_level": "B1",
        "versus_target": "meets",
        "confidence": "high",
        "strong_points": [{
            "quote": "the student's work demonstrates the expected range",
            "type": "lexis", "level": "B1",
            "note": "mock evidence",
        }],
        "areas_for_improvement": [],
        "rubric_mapping": mapping,
        "student_feedback": {
            "key_success": "consistent use of target-level structures",
            "target_area": "morphological agreement in complex clauses",
            "comment": "Mock: keep building on your strong control.",
        },
    }


def build_stats_response() -> dict:
    return {
        "class_level": "B1",
        "executive_summary": "Mock class insight: the class sits at B1.",
        "distribution": "mock",
        "strengths": ["mock strength"],
        "weaknesses": ["mock weakness"],
    }


def build_roster_response() -> dict:
    """Deterministic roster-extraction reply for the roster_import job
    (2026-11-08): class identity + 3 students + 1 warning."""
    return {
        "class_name": "2G1",
        "school_name": "Lycée Mock Jean-Jaurès",
        "students": [
            {"first_name": "Léa", "last_name": "Martin"},
            {"first_name": "Noah", "last_name": "Bernard"},
            {"first_name": "Chloé", "last_name": "DUPONT"},
        ],
        "warnings": ["Ligne 3: lettre illisible (corrigée « DUPONT »)"],
    }


# Levels to assign per criterion name (default B1). The test overrides a few to
# exercise a non-default attestation path.
DEFAULT_LEVELS = {}

# Seconds to sleep BEFORE the first SSE chunk of a streamed completion. Set by
# the E2E test (>0) so the job's in-memory stream is deterministically live
# while a subscriber attaches — mirroring production, where the real LLM keeps
# the stream open for ~100 s, so the subscriber always catches the live log
# (meta -> phase* -> token* -> result -> done) rather than the late-subscriber
# DB-rebuild path (meta -> result -> done).
STREAM_PRE_DELAY = 0.0

# Seconds the mock holds a roster-extraction reply (2026-11-08): set by the
# roster test so the job stays in-flight long enough to make the 409
# in-flight guard + the early-commit 409 deterministic.
ROSTER_DELAY = 0.0


class _Handler(BaseHTTPRequestHandler):
    # silence the default per-request stderr logging
    def log_message(self, *a):  # noqa: A003
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, chunks, usage, finish_reason):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if STREAM_PRE_DELAY > 0:
            # Hold the stream open (job still "running") so a live subscriber
            # attaches to the in-memory log rather than the DB-rebuild path.
            time.sleep(STREAM_PRE_DELAY)
        i = 0
        for chunk in chunks:
            i += 1
            fr = finish_reason if i == len(chunks) else None
            payload = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "mock-llm",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": chunk},
                    "finish_reason": fr,
                }],
            }
            self.wfile.write(
                ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()
            )
            self.wfile.flush()
            time.sleep(0.002)  # pace a few chunks so the stream is non-trivial
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/").endswith("/v1/models") or self.path == "/v1/models":
            self._send_json({"data": [{"id": "mock-llm", "object": "model"}]})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        if not self.path.rstrip("/").endswith("/v1/chat/completions"):
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "bad json"}, 400)
            return
        text = user_text_of(body)
        stream = bool(body.get("stream"))

        # decide what to return from the prompt content
        roster_req = "student-roster sheet" in text
        stats_req = "CLASS'S LEVEL" in text or "WHOLE CLASS" in text
        # fall back: if no criteria were parsed, still answer with a JSON
        # object that will NOT satisfy the analyze schema (raw-raw path).
        crits = criteria_from_prompt(text)
        if roster_req:
            if ROSTER_DELAY > 0:
                time.sleep(ROSTER_DELAY)
            full = json.dumps(build_roster_response(), ensure_ascii=False)
        elif stats_req:
            full = json.dumps(build_stats_response(), ensure_ascii=False)
        elif crits:
            full = json.dumps(build_analyze_response(text, DEFAULT_LEVELS),
                              ensure_ascii=False)
        else:
            full = json.dumps({"unexpected": "no criteria parsed"},
                              ensure_ascii=False)

        if not stream:
            self._send_json({
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "mock-llm",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": full},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                          "total_tokens": 15},
            })
            return

        # stream the JSON in a few chunks (mid-token splits are fine — the
        # client reassembles the full text before parsing)
        n = max(1, len(full) // 40)
        step = max(1, -(-len(full) // n))  # ceil
        chunks = [full[i:i + step] for i in range(0, len(full), step)]
        self._send_sse(chunks, {"total_tokens": 15}, "stop")


class MockLLMServer:
    """In-process mock LLM. ``.base_url`` is the OpenAI base to point
    ``BABELGRADE_LLM_BASE`` at (ends in ``/v1``)."""

    def __init__(self):
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self._port}/v1"
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8901
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"mock LLM on http://127.0.0.1:{port}/v1", flush=True)
    httpd.serve_forever()
