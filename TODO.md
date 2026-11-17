# TODO

Outstanding work on BabelGrade, ordered by priority. P0–P2 are done; a few
optional items remain. Verification recipe at the bottom.

## Done

- **P0 — repo hygiene & lint.** `ruff.toml` at the root (`app/` strict,
  `tests/`/`scripts/`/`mockups/`/`mock-hybrid/` relaxed), dead zones removed,
  `ruff check .` 100 % green.
- **P1 — robustness.** Private GitHub remote (`origin` → `main`), in-repo
  smoke suite, orphan cache removed.
- **P2.7 — `app/stats.py`.** `db.stats_for_assignment` + `db.stats_for_student`
  extracted into a dedicated module (one-way `db ← stats ← routes`; no
  re-export from `db.py` — that would be a circular import). `db.py` −264 lines.
- **P2.8 — async job E2E with a mocked LLM.** The three long
  endpoints (`/api/analyze`, `/api/evaluate`, `/api/analyses/{id}/run-ai`) are
  covered end-to-end *without* a real LLM via `tests/mock_llm_server.py`
  (stdlib OpenAI-compatible mock) and `tests/test_p2_mock_llm_e2e.py` (37
  checks: enqueue→run→finalize, proof-matrix persistence, deterministic
  attestation, aware-mode last-AI-wins, SSE ordering).
- **P2.9 — developer docs.** `docs/architecture.md` (module map, import
  direction, the three-endpoint lifecycle, conventions, recipes), wired into
  the in-app Docs view.
- **P2.10 — OCR rewrite + word-selection annotation.** OCR is now LLM-direct
  (per-line boxes 0..1000, no tesseract pipeline); Annoter v5 selects word
  ranges in the transcript with auto-crop.

## Open (optional / long-term)

1. **Process supervisor.** `run.sh` currently runs as a
   foreground/background task; a `systemd` unit (or `s6` on this host) with
   `Restart=always` + a stable log file would remove the manual-restart step
   and the "stale uvicorn log" pitfall.
2. **CI for the live Playwright suites.** Today CI runs only the hermetic
   in-process suites (see `.github/workflows/ci.yml`). A headless-Chromium CI
   job that boots the server against the mocked LLM would cover the UI
   E2E without real credentials.

## Verification recipe

Before closing any item:

- `ruff check .` stays 100 % green (`ruff.toml`).
- `python3 -m py_compile app/*.py` (and the touched test/script files).
- Server health: `curl -s localhost:8090/api/health`.
- Hermetic suites: `tests/test_multiuser_smoke.py`, `tests/test_media_ownership.py`,
  `tests/test_p2_mock_llm_e2e.py`, `tests/test_roster_import.py`,
  `tests/test_p0_state_i18n_js.py`, `python -m pytest tests/test_ocr_resnap.py -q`.
- Live Playwright suites (server up on :8090, `tests/.credentials` present):
  `tests/test_smoke_assignments.py`, `tests/test_p4_filters.py`,
  `tests/test_p5_filters.py`, `tests/test_p7_eval_exit.py`.
- One commit per item, explicit message.
