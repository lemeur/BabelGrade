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

### UX / a11y audit (2026-11-23) — 5-wave plan (V1 + V2 + V3 + V4 + V5 shipped 2026-11-24)

Full report: `docs/ux-audit-2026-11-23.md` (internal — **not** wired into the
public GitHub Pages build; screenshots in `docs/ux-audit-1123-assets/`).
Prism: potentially 3 concurrent sessions (mobile photo + criterion-by-criterion
validation, desktop management/stats/exports).

- ✅ **Wave 1 (P0 bugs + a11y, low effort) — SHIPPED 2026-11-24, commit `af33fe0`:**
  all 8 items fixed in `static/index.html` + `tests/test_a11y_wave1.py`
  (**22/22 PASS** live). Fixed: B2 level pill empty in the mobile bottom-sheet
  (removed `.lvl-sheet-btn.on .ls-lv{color:var(--acc)}`); level-pill contrast
  A1/A2/B1 → `#15803d`/`#0f766e`/`#0369a1` (now AA); modal focus trap
  (`FOCUS_TRAP` helper + MutationObserver on the 7 overlays, Tab cycling +
  focus restore on close); `<html lang>` follows the UI language;
  `role=status`/`aria-live` on `#toast` + `#run-chip-label`; `<label for>` on
  the 7 evaluator fields + `aria-required` on `#rubric`; global
  `:focus-visible` rings (incl. radial sectors/centre, replacing the invisible
  `outline:none`); required fields now also signalled textually via
  `aria-describedby="req-note"` (the i18n `.reqNote`, which gained
  `id="req-note"`); bonus Wave-2 item: `@media (prefers-reduced-motion)` kills
  all animations/transitions.
- **Wave 2 (a11y structural) — SHIPPED 2026-11-24, commit `7b0da2e`:**
  A5 keyboard on the home radial menu: `#pie-center` is `tabindex=0` (the
  entry point), `openMenu()` focuses it, `pieClose()` restores focus to
  `#home-reopen`; the active crown `#rg-N` gets `role=menu` and its sectors
  `aria-selected` mirroring `.selected` **per level** (a selected L0 verb
  stays `aria-selected=true` when its L1 sub-crown becomes the active level —
  the in-place cycle branch and `rBuildLevel` both set it unconditionally).
  The global keydown handler (arrows/Enter/Escape → `rCycle`/`rExecute`/
  `pieClose`) was already there; the gap was that nothing was focusable at
  boot. A3: `a11y.{close,zoomIn,zoomOut,removePhoto,clearSel}` i18n keys ×4 +
  `applyI18n` now sets `[data-i18n-aria]→aria-label` and `[data-i18n-title]
  →title`; wired onto the 8 icon-only buttons (close ×5, annoter zoom ×2,
  remove-photo, clear-sel). A7: `scope="col"` on all 49 `<thead><th>` +
  `<caption>` (first child) on the 6 key tables (hist/assignments/students/
  jobs/roster + JS `.stat-table`, the last embedding `t('stat.criterion')`
  directly since `applyI18n` doesn't re-run on innerHTML re-render); the
  `tbody` row-header `<th class=rub-det-crit>` correctly left unscoped.
  Tests: `tests/test_a11y_wave2.py` (**13/13 PASS** live FR) ; `test_p8_home.py`
  still **57/57** (radial engine regression baseline). ~~A8
  `prefers-reduced-motion`~~ — ✅ already done as a Wave-1 bonus (commit
  `af33fe0`, `@media (prefers-reduced-motion: reduce)` in the global CSS).
- **Wave 3 (desktop ergonomics) — SHIPPED 2026-11-24 (commit pending):** D1 the two
  near-identical AI CTAs are differentiated (`#run` solid + `#run-eval` ghost,
  both with i18n tooltips `an.runTip`/`an.runEvalTip` ×4); D2 the 5 icon-only
  row actions on the Sujets table now sit in ONE regular row (td keeps
  table-cell display, `white-space:nowrap`, 34px buttons) with `a11y.*`
  aria-labels ×4; D3 the 4-step stepper is an HONEST SUMMARY (option b) —
  chips report completion ○ empty / ✓ filled / ● current via CSS `::before`
  marks (textContent stays clean), scroll-spy `.on` stays position-only, and
  a change-driven completion sync repaints on any field change (bubbling
  `change`/`input` on `#view-analyze` + rAF-debounced MutationObserver for the
  mode-field engine DOM); D4 « ◂ Simplifié » + « ⚙ Données » tooltips
  (`home.advBackTip`/`nav.dataTip` ×4) + the Whisper pill is muted on the
  written channel (`.badge.muted`, `syncWhisperPill()` from the Mode toggle +
  boot — the health() poll only toggles the class); D5 Sujets nits: DEPUIS
  nowrap, PRODUCTIONS count no longer clipped (hover affordance instead of
  overflow), resource badges uniform "icon + text" via `RES_ICON` ×4 i18n.
  Tests: `tests/test_ux_wave3.py` (**25/25 PASS** live E2E desktop 1280 FR) +
  P1/P8/wave1/wave2/linear-cursor/p0/p6 re-confirmed. **V3 side-fix (nav):**
  `_navTypedTo()` called `_evaluatorEnter()`/`openStudentStats()`/`_ststatsEnter()`
  DIRECTLY, bypassing `navApplyView()` → the home radial menu stayed OPEN over
  the evaluator/ststats after a typed hash (backdrop intercepted every click —
  this was the P1-wizard blocker from the previous session). Now `navApplyView`
  (evaluator) / `pieClose()` up front (ststats, stack entry stays `{students}`
  so back = students list). Proven by `test_p1_wizard.py` (21/21) + p6/p0 + a
  typed-deep-link probe (evaluator closes radial, home re-opens it, ststats
  closes it, back → home with radial). **i18n-test pitfall:** `RES_ICON` reuses
  7 `td.*` keys as object keys → `test_p0_state_i18n_js.py` now counts key
  DEFINITIONS within the I18N slice only (whole-file counts would over-count
  consumer usages).
- **Wave 4 (mobile ergonomics) — SHIPPED 2026-11-24:** M1 decision = ADD the
  native portrait layout (tibo's "valider sur le vif" use: one hand holds the
  phone, the other taps a level). M1/V4.1: criterion-by-criterion eval now
  renders a NATIVE portrait layout on a coarse-pointer phone held portrait —
  1 criterion full-screen, the 6 levels A1..C2 as one 3×2 grid of big tappable
  buttons (`#eval.ev-port .ev-port-grid .ev-lvl-btn[data-pick]`), the entered
  level's descriptor in a compact scrollable panel below (`.ev-port-desc`),
  `eval.pdEmpty` i18n ×4. `evPort()` (coarse + portrait) is the 3rd render mode
  alongside `evWide()` (≥900px scale) and the 3-col; the forced-rotate hint is
  now suppressed when `evPort()` (it effectively never shows), and the resize +
  `orientationchange` handler re-renders on a genuine mode crossing (`_evWasMode`
  port|wide|cols). Landscape phones (<900px) keep the 3-col layout, desktops the
  6-wide scale. M2: `capture="environment"` on the copy/instruction/doc photo
  inputs (camera-first; some browsers drop the gallery option — accepted, copies
  are live-shot in class; source docs can also be PDF/text). M3: `.card.an-actions`
  sticky-bottom on the evaluator form under 760px (CTAs one thumb away at any
  scroll position). M4: detail-page essentials sticky — the `.att-ess`
  attestation band is now sticky under the header on mobile. **M4 root cause
  (the real bug):** `overflow-x:hidden` on `body` made body the vertical scroll
  container and silently KILLED `position:sticky` for both the header and the
  band; moved to `html` only. Plus the header height is VIEW-DEPENDENT (mobile
  home 59px, nav views 86px after flex-wrap reflow, desktop detail 103px), so a
  hardcoded sticky `top` was wrong in at least one view → new `syncHdrH()`
  publishes the measured header height as `--hdr-h` on `:root` (called from
  `navApplyView` home/evaluator/main branches + `bootApp`, plus a
  `ResizeObserver` on the header), and `.att-ess{top:var(--hdr-h,59px)}`. The
  band is card-bounded (pins under the header while the attestation card is on
  screen, then scrolls with it — matches desktop `.att-ess`). M4 also folds the
  long oral transcript behind a `<details open>` card (open by default = nothing
  hidden, just foldable on mobile; consistent with the copy-text `<details>`
  card). Tests: `tests/test_ux_wave4.py` (16/16 PASS live mobile 390 portrait +
  landscape 844 + desktop 1280 FR) + `tests/test_p7_eval_exit.py` REWRITTEN for
  the native portrait (P1–P4 now assert hint-off + 6-button grid + grid-pick +
  save-persists; landscape/desktop exit-bar/discard/back-swipe semantics
  unchanged → 18/18 PASS). Regression re-confirmed: P8 57/57, linear-cursor
  27/27, wave1/2, wave3 25/25, P1-wizard, P6-ststats, P2-mobile, P0-i18n 4×4,
  grid-i18n, WAL 4/4. **P7 pitfall (resume 2026-11-24):** the `/api/analyses`
  list is newest-first, so an in-flight `queued` attestation (no level yet, no
  `.att-card`) can sit at the top — `find_target` must filter
  `status==='done' && overall_level` or `open_eval` times out on the missing
  card.
- **Wave 5 (concurrency for 3 simultaneous users) — SHIPPED 2026-11-24:**
  C1: SQLite `journal_mode=WAL` in `init_db` (persistent) + `busy_timeout=5000`
  per connection — proven by `tests/test_wal_concurrency.py` (4 readers +
  3 heavy writers: **0 reader lock errors + ~3.4-4.8× read throughput** vs
  `delete`, **4/4 PASS**). C2: LLM job queue `MAX_WORKERS` 1 → **3**
  (`DEFAULT_MAX_WORKERS`, `BABELGRADE_MAX_WORKERS` env override 1..4,
  priority env > DB > default) — proven safe by a live 3-parallel SGLang
  probe (~1.6× wall-clock speedup vs serial: SGLang batches). C3: queue
  position ("n°X") on the Jobs view pills, the follow card, the SSE `meta`
  events and the header run chip — `db.job_queue_positions()` + `queue_pos`
  on `job_list`/`GET /api/jobs/{id}`; `jobs.qpos` i18n key ×4.
  Tests: `tests/test_v5_queue_position.py` (hermetic, 10/10 PASS) +
  `tests/test_v5_queue_position_ui.py` (live E2E, 2 real analyses, FR).
  ⚠️ Playwright `request.post` pitfall: `data=` sends a JSON body (right for
  `set_job_settings(payload: dict)`) but `form=` is required for Form-param
  endpoints like `/api/analyze` (a `data=` there 422s "valid rubric_id
  required" — the Form fields arrive empty).

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
