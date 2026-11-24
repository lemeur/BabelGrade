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
  direction, the three-endpoint lifecycle, conventions, recipes), published on
  the GitHub Pages docs site (the in-app Docs view was removed in 2026-11).
- **P2.10 — OCR rewrite + word-selection annotation.** OCR is now LLM-direct
  (per-line boxes 0..1000, no tesseract pipeline); Annoter v5 selects word
  ranges in the transcript with auto-crop.

## Open

### Priority — validate on real student work, then harden the ASR/OCR

1. **Test on real student productions & improve OCR / transcription.** Run the
   pipeline on genuine copies (handwritten, printed, low-quality scans, blue
   grid paper, photos with errors in the student's work) and harden both the
   LLM-direct OCR and the Whisper transcription. **Key constraint:** the
   student's *own* errors (spelling, grammar, missing words) are signal, not
   noise — neither OCR nor transcription may "correct" them. The verbatim
   evidence the Proof Matrix quotes must match what the student actually
   wrote, so a faithful (if messy) transcript beats a clean (but altered) one.
   Track regressions with the `scripts/check_word_box_accuracy.py` /
   `probe_word_boxes.py` word-box probes and the `data/ocr_test/` fixtures.

### UX / a11y audit (2026-11-23) — plan to review 2026-11-24

Full report: `docs/ux-audit-2026-11-23.md` (internal — **not** wired into the
public GitHub Pages build; screenshots in `docs/ux-audit-1123-assets/`).
Prism: potentially 3 concurrent sessions (mobile photo + criterion-by-criterion
validation, desktop management/stats/exports).

- **Wave 1 (P0 bugs + a11y, low effort):** B2 level pill renders EMPTY in the
  mobile level bottom-sheet when the current level is B2
  (`.lvl-sheet-btn.on .ls-lv{color:var(--acc)}` overrides `.level.B2`
  white-on-blue → blue-on-blue); level-pill contrast A1 3.30 / A2 3.74 /
  B1 2.77 < AA 4.5 (fix: `--lvl-a1 #15803d`, `--lvl-a2 #0f766e`,
  `--lvl-b1 #0369a1`); modal focus not trapped / not initialized (WCAG 2.4.3);
  `<html lang>` stuck at `en` under FR/ES/DE UI; 0 `aria-live` (toasts
  silent); 132 of 430 buttons without accessible name; `outline:none` kills
  focus visibility on nav + radial sectors; evaluator selects (`#assignment`,
  `#student`, `#rubric`…) have no associated `<label for>`; required fields
  signalled by colour-only asterisk.
- **Wave 2 (a11y structural):** keyboard on the home radial menu (L0 sectors
  `tabindex=-1` → boot screen unreachable by keyboard); `th scope`/caption on
  tables; `prefers-reduced-motion` (21 transitions + 7 animations, none
  honoured).
- **Wave 3 (desktop ergonomics):** the two near-identical "Analyze with AI" /
  "Evaluate first" CTAs; 5 icon-only row actions on assignments; wizard
  stepper vs all-visible-forms mismatch (recommended: relabel as overview
  with ✓/●/○, no next/back); opaque "Simplifié"/"Données" buttons; Whisper
  pill shown for written tasks; Sujets table nits.
- **Wave 4 (mobile ergonomics — design decision):** criterion-by-criterion
  eval forces landscape (full-screen rotate hint in portrait) — decide
  whether to add a native portrait layout (1 criterion, 3×2 level grid);
  photo inputs lack `capture="environment"`; evaluator primary CTA stuck in
  the header on mobile (no sticky action bar at the bottom); detail page
  length (essentials not sticky on mobile).
- **Wave 5 (concurrency for 3 simultaneous users):** SQLite journal_mode is
  `delete` (→ **WAL** in `init_db` + 3-client load test); LLM job queue
  `MAX_WORKERS=1` (→ 3–4 after proving SGLang concurrent capacity); UI for
  "position in queue" on the run chip + Jobs view.

### Product features (not yet started)

2. **Share corrections & feedback with students via a secure link.** A
   read-only, time-limited, token-authenticated URL for a given analysis so a
   teacher can send a student their report (level, justifications, verbatim
   evidence, draft feedback) without giving them an app login. Must respect
   the per-owner scoping and not leak other students' work.
3. **Group work submissions.** Allow a submission to belong to a *group* of
   students (not just one); grade the group artifact, and decide how per-member
   attribution / levels are shown on the attestation.
4. **Improvement plan with pedagogical resources.** For each student, generate
   a personalised progression plan that maps weak criteria to concrete
   activities from a managed resource library, so the student can work on
   improving specific skills.
5. **Collaborative correction across teachers.** Split an assignment's copies
   among several teachers for review, and support cross-evaluation (a second
   teacher grades the same submission; reconcile the two Proof Matrices).

### Infrastructure (optional / long-term)

6. **Process supervisor.** `run.sh` currently runs as a
   foreground/background task; a `systemd` unit (or `s6` on this host) with
   `Restart=always` + a stable log file would remove the manual-restart step
   and the "stale uvicorn log" pitfall.
7. **CI for the live Playwright suites.** Today CI runs only the hermetic
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
