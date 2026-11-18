# BabelGrade

[![CI](https://github.com/lemeur/BabelGrade/actions/workflows/ci.yml/badge.svg)](https://github.com/lemeur/BabelGrade/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Turn a student's written copy or oral recording into a CEFR attestation with
verbatim evidence.** BabelGrade is a teacher-facing, **international** web app
that maps every criterion of a CEFR attestation grid to a recommended level
(A1–C2) — and shows *why*: each recommendation is backed by verbatim quotes
(or timestamps) from the student's own work. It ships with the official
**French LVA/LVB** attestation grids as presets (the app's only France-specific
part — see [Custom rubrics](#custom-rubrics)), but the framework, the UI and
the whole workflow are language-neutral: the UI is localised in
**EN / FR / ES / DE**, and any grid can be defined as a custom rubric.

It is an objective **evidence extractor**: it lowers the teacher's cognitive
load, never replaces their judgment. Nothing is auto-graded — every level
stays editable and recomputes instantly.

<p align="center">
  <img src="docs/readme/radial-menu.gif" alt="Home radial menu" width="300">
  <img src="docs/readme/mobile-level-picker.png" alt="Mobile criterion grading" width="300">
</p>

<p align="center">
  Home: a single radial menu (tap a verb, fan out, pick) · Mobile: grade every
  criterion with a bottom-sheet level picker
</p>

---

## What it does

1. **Analyze a submission** — paste the student's text *and/or* attach photos
   of the copy (the vision model reads them directly — no OCR copy-paste),
   or drop an oral audio recording. Optionally attach the task instruction
   and/or the source document (text, photos, PDF, or audio).
2. **Get a Proof Matrix** — every rubric criterion gets a suggested CEFR
   level, a justification, and verbatim evidence. No level without a quote.
3. **Attestation synthesis** — on the official attestation grids (LVA/LVB
   presets), per-criterion levels (A1–C2) are converted to a deterministic
   **score /120** and an attestation level, recomputed live as the teacher
   edits.
4. **Annotate the copy** — select a word range in the OCR'd transcript: the
   photo auto-crops to it, the teacher drops a marker (sticker, level, note)
   that the AI reads as context for its next run.
5. **Annotate the oral** — the transcript is word-timestamped; select a range,
   the player seeks to it, and markers carry time ranges.
6. **Dual AI loop** — "AI first" (grade from the AI report) or "teacher
   first" (grade yourself, then ask the AI for a blind or *aware* second
   opinion that confirms or refutes each criterion with evidence).
7. **Roster photo import** — import a class + its students from roster
   photos, with a review step before anything is committed.

### Screenshots

<details>
<summary><b>AI analysis report</b> — Proof Matrix with justifications + verbatim evidence, AI column (✓/≠), attestation /120, AI feedback card</summary>

![AI analysis report](docs/readme/ai-analysis-report-full.png)

</details>

<details>
<summary><b>Written copy annotation</b> — photo ↔ OCR dual pane, word-range selection with auto-crop, marker panel (sticker · level · note)</summary>

![OCR annotation](docs/readme/ocr-annotation.png)

</details>

<details>
<summary><b>Oral annotation</b> — synced audio player + timestamped transcript, range selection, marker panel</summary>

![Oral annotation](docs/readme/oral-annotation.png)

</details>

---

## How it works

- **Backend** — FastAPI (`app/`), SQLite persistence (`data/babelgrade.db`).
  Multi-user: PBKDF2 logins, every owned table scoped to its owner.
- **LLM** — a local OpenAI-compatible endpoint (by default SGLang serving
  `qwen38-27b`, text + vision). The model *cannot hear audio*; oral
  submissions go through offline **faster-whisper** first (timestamped
  transcript + word timings), and fluency metrics (WPM, pauses, hesitation
  tokens) are computed deterministically from the ASR timings.
- **Async job queue** — long LLM/Whisper work is offloaded to an in-process
  background scheduler (`app/jobs.py`, no external broker). The queue
  survives restarts; progress streams over SSE. See
  [docs/async-jobs.md](docs/async-jobs.md).
- **Frontend** — a single vanilla-JS page (`static/index.html`), localised
  in **EN / FR / ES / DE**, with a simplified "home" mode driven by an
  animated radial menu.

## Custom rubrics

BabelGrade works with **any** CEFR rubric, not only the French presets:

- **Presets (shared):** the official French LVA/LVB attestation grids
  (comprehension, written expression, oral expression) are bundled as
  shared rubrics with the official A1→C2 criterion descriptors, the
  deterministic /120 scoring and the attestation thresholds. They ship
  in their original French wording — that is data, not UI: every screen
  around them is in the language the teacher has chosen.
- **Custom rubrics (per owner):** teachers can create their own rubric with
  any criteria, any level scale and any wording, in whatever language they
  prefer. A custom rubric is private to its owner and can be used on any
  assignment, in any of the four UI languages.

## Quick start

```bash
pip install -r requirements.txt
./run.sh                 # http://<host>:8090
HOST=0.0.0.0 PORT=8090 ./run.sh
```

Configuration (env vars, all optional):

| Variable | Default | Purpose |
|---|---|---|
| `BABELGRADE_LLM_BASE` | `http://127.0.0.1:8078/v1` | OpenAI-compatible LLM endpoint |
| `BABELGRADE_LLM_MODEL` | `qwen38-27b` | Model name |
| `BABELGRADE_LLM_API_KEY` | *(empty)* | API key |
| `BABELGRADE_INITIAL_LOGIN` | `tibo` | first-boot account (registration stays open only for this) |
| `BABELGRADE_INITIAL_PASSWORD` | *(empty)* | first-boot password |
| `BABELGRADE_DB_PATH` | `data/babelgrade.db` | SQLite path (tests use a throwaway DB) |
| `BABELGRADE_WHISPER_CACHE` | `~/.cache/huggingface/hub` | faster-whisper model cache (`download_root`) |

Requires Python 3.11+, uvicorn, faster-whisper, PyMuPDF. The Whisper model is
cached locally and the app runs fully offline (all Hugging Face downloads are
disabled at import time). The LLM endpoint must be reachable — BabelGrade has
no LLM fallback.

## Security model

- **Multi-user, per-owner scoping.** PBKDF2-HMAC-SHA256 (per-user salt +
  application pepper) password hashes; session cookie auth. Every owned
  table (students, assignments, submissions, analyses, annotations, jobs,
  custom rubrics) is scoped to its owner on every read and write, enforced
  by a FastAPI dependency that injects the current owner.
- **Media ownership.** `/api/files` serves a file *only* to its owner;
  foreign, unknown, and untracked files all 404 identically so no filename
  enumeration is possible.
- **Registration is closed by default.** Accounts can only be registered at
  first boot (via the initial-login env vars); the app refuses to stay in
  "registration open" afterwards.
- **Nothing leaves the machine.** No external API calls at all: the LLM is a
  local OpenAI-compatible endpoint and the ASR model runs offline.
- **Evidence before level.** The backend warns when a criterion mapping
  lacks a verbatim quote; recurring errors are flagged, isolated slips are
  not over-penalised; per-student accommodations may change content and
  feedback but never the demonstrated level.

## Testing

The suite is split into two classes:

**Hermetic, in-process suites** (throwaway SQLite DB, in-process OpenAI
mock server, no live server, no LLM, no Whisper model) — these run in CI
and can be run anywhere the dependencies install:

```bash
python tests/test_multiuser_smoke.py     # auth gate, owner scoping, isolation
python tests/test_media_ownership.py     # media-ownership 404 matrix
python tests/test_p2_mock_llm_e2e.py    # full job pipeline against a mocked LLM
python tests/test_roster_import.py      # roster photo import E2E (mocked LLM)
python tests/test_ui_language_prompt.py # prompt-builder unit checks
python tests/test_p0_state_i18n_js.py   # i18n 4-lang balance + node --check
python -m pytest tests/test_ocr_resnap.py -q   # OCR resnap alignment units
```

**Live Playwright suites** drive the real UI against a running server on
`127.0.0.1:8090` (they read the live-server credentials from
`tests/.credentials`, which is gitignored by design). See
[CONTRIBUTING.md](CONTRIBUTING.md#running-tests) for the local recipe.

CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs ruff,
byte-compilation and every hermetic suite on Python 3.11 and 3.13.

## Repository layout

```
app/main.py            FastAPI factory + auth gate + include_router (no routes)
app/routes_*.py        route modules (auth, rubrics, students, assignments,
                       analyze, evaluate, jobs, analyses, annotate, files,
                       docs, admin, health, roster)
app/assess.py          prompts, fluency metrics, JSON parse/validate
app/llm_client.py      OpenAI-compatible client (stream + JSON extract)
app/whisper.py         offline faster-whisper wrapper (cached model)
app/db.py              SQLite + forward migration
app/stats.py           assignment + per-student stats
app/rubrics.py         LVA/LVB attestation presets + /20 conversion tables
app/auth.py            multi-user auth (PBKDF2, owner scoping)
app/jobs.py            async job queue (scheduler, workers, SSE)
app/media.py           upload staging + PDF/scan/doc-audio extraction
app/ocr.py             LLM-direct OCR for the annoter (per-line boxes 0..1000)
app/imaging.py         image enhancement for copy-photo OCR
app/config.py          paths + upload limits
static/index.html      single-page UI (EN/FR/ES/DE)
docs/                  user guide, architecture, async-jobs (in-app Docs view)
tests/                 hermetic + Playwright E2E suites, mock LLM server
scripts/               dev probes and screenshot generators
mockups/               standalone UI prototypes (radial menu, hybrid annoter)
.github/workflows/     CI (lint + hermetic suites, Python 3.11/3.13)
run.sh                 launcher
```

## Development

Short guide: see [CONTRIBUTING.md](CONTRIBUTING.md). Module map, import
direction rules and the "add an endpoint" recipe:
[docs/architecture.md](docs/architecture.md). Outstanding work: [TODO.md](TODO.md).

## Built with AI

> **This project is vibe-coded.** The codebase was produced by an LLM
> (Hermes Agent) working with **Qwen3.8-27b** — the same local SGLang model
> the app uses at runtime to assess student work. Feature design, UI
> iterations, OCR pipeline, and the whole E2E test suite were co-authored in
> conversation, with the app itself running on the same VM. It stands as a
> working example of a non-trivial, multi-user, production-shaped web app
> built conversationally on a local 27B model.

## License

[MIT](LICENSE) © 2026 BabelGrade contributors
