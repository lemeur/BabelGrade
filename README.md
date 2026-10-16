# ELT Assessor

Web app that turns a student submission (written copy or oral recording) into a
**CEFR rubric mapping with verbatim evidence** — an objective evidence extractor
that lowers the teacher's cognitive load without replacing their judgment.

## Architecture

- **Backend**: FastAPI (`app/`), SQLite persistence (`data/elt_assessor.db`).
- **LLM**: the local SGLang OpenAI-compatible endpoint serving `qwen38-27b`
  (text + vision). Configured via env `ELT_LLM_BASE` / `ELT_LLM_MODEL`
  (defaults `http://127.0.0.1:8078/v1` / `qwen38-27b`).
- **Oral pipeline**: audio → local offline Whisper (faster-whisper `base`,
  cached) → timestamped transcript + word timings → fluency metrics
  (WPM, pauses, hesitation tokens) → LLM analysis of transcript + timestamps.
  The model cannot hear audio; phonological notes are transcript-based and
  always timestamped for the teacher to verify.
- **Frontend**: single page, vanilla JS (`static/index.html`), SSE live
  streaming of the model's reasoning/output.
- **Async job queue** (`app/jobs.py`): long LLM/Whisper work is offloaded to a
  background scheduler (an `asyncio.Task` inside the same uvicorn process,
  **no external runner / broker**). A persisted `jobs` table (SQLite) survives
  restarts; on boot `recover_orphans()` re-queues anything left `running`.
  The three long endpoints (`/api/analyze`, `/api/evaluate`,
  `/api/analyses/{id}/run-ai`) return a **job handle** `{job_id, follow_url}`,
  and progress streams via SSE at `GET /api/jobs/{id}/events`
  (`meta → phase* → token* → result → done|cancelled|error`). `max_workers`
  1–4, hot-adjustable. See [`docs/async-jobs.md`](docs/async-jobs.md) for the
  full architecture, state machine, and annotated screenshots.

## Run

```bash
./run.sh                 # http://<host>:8090
HOST=0.0.0.0 PORT=8090 ./run.sh
```

The app is **multi-user** (2026-10-14): PBKDF2 logins, every owned table is
scoped to its owner. On first boot the very first account is created from
`ELT_INITIAL_LOGIN` / `ELT_INITIAL_PASSWORD` (open registration is closed
after that). Log in from the app; data ownership is enforced on every
endpoint and on the media file server.

## What it does

1. **Analyze** — open the evaluator form (header "✏️ Évaluer" button, or the
   "Évaluer sans sujet" button in the Assignments view). Pick written/oral,
   a rubric, and a student. **The default rubrics are the official LVA/LVB
   attestation grids** ("Grille d'évaluation pour attestation en langues
   vivantes", B.O. 2014):
   - *Attestation LVA/LVB — Compréhension* (3 critères, applies to written
     AND oral comprehension)
   - *Attestation LVA/LVB — Expression écrite* (4 critères)
   - *Attestation LVA/LVB — Expression orale* (4 critères)
   Each criterion embeds the full official A1→C2 descriptors, and the
   recommended level must be one of **A1, A2, B1, B2, C1, C2** exactly.
   Legacy presets (Bac écrit/oral, BTS, generic CEFR) remain available for
   non-attestation work, plus a custom editor.
   Optionally set a **target level** (A1–C2, the level expected for the
   candidate): the model still assesses the demonstrated level objectively
   from the evidence, then reports `versus_target` (meets / below / above).
   Paste the student's text **and/or** attach the **page photo(s) of the copy**
   — the two are mutually exclusive: photos alone are enough (the model reads
   them directly, no transcription needed; max 20 photos, 25 MB each, in
   reading order). When both are given, the model treats the photos as the
   ground truth. It analyzes the whole submission as one continuous text;
   evidence may cite the page number. For oral, drop an audio recording.
   Add optional **task context**: the task instruction (the assignment given
   to the student) and/or the source document they worked from. Each can be
   **pasted text, photo(s) of the printed material (read directly by the
   vision model — no OCR copy-paste needed), a PDF upload** (text layer
   extracted with PyMuPDF; scanned PDFs rendered to images for vision), or,
   for the source document only, an audio file (transcribed locally with
   Whisper first). Priority when several forms are given: text > audio > PDF
   > photos for the document; the instruction PDF/photos are merged into the
   instruction. The model uses the context to judge the work against the task
   — e.g. word-count requirements, questions that had to be answered, or the
   document to react to — and the context is stored with the submission
   (files kept in `data/uploads/` and re-downloadable) and shown in the
   report.
  Add optional **evaluation instructions** ("what to check in this work"):
  typed text and/or a PDF upload (e.g. "the student must have understood the
  ironic tone of the text"). The model checks every requested point one by
  one and, in the criterion justifications and student feedback, states
  whether it is met / partially met / missing with verbatim evidence; the
  instructions only affect the content/task assessment and feedback, never
  the demonstrated language level. Persisted as `eval_notes` on the
  submission and shown in the report and history.
  **Assignments vs submissions (2026-09; renamed from "Tasks" 2026-10-05):**
  the "work to be assessed" is a separate entity from the student's
  production. An **assignment** (Assignments view,
  `GET/POST/PUT/DELETE /api/assignments`) stores the instruction, the source
  document, the target level and the evaluation instructions, plus the
  uploaded media (kept in `data/uploads/`, referenced by filename, reusable
  for every student). A **submission** links to an assignment via
  `assignment_id` — or is ad-hoc, using the inline context fields of the
  evaluator form as before.
  Selecting an assignment in the evaluator form pre-fills it and the server
  sends the assignment's stored materials; the **target level can be
  overridden per submission** (an advanced or behind student), and the
  teacher can add **accommodations** for that student (e.g. "dyslexia: weight
  spelling errors lightly") which the model must state it applied —
  accommodations affect content/feedback, never the demonstrated level.
  "💾 Save as assignment" turns the current form context (incl. uploads) into
  a reusable assignment. Assignments carry an **exercise type** (skill:
  comprehension/expression) + **kind** (written/oral) used to auto-pick a
  matching rubric. Deleting an assignment unlinks its submissions (they keep
  their context snapshot); deleting a student/submission with cascade removes
  their analyses too. History shows the assignment name per submission.
  Assignments have a **stats view** (per-assignment aggregates + optional
  AI-generated insight, stored and re-openable).
  Students carry an optional **classroom** field — suggested code
  `YYYY/YY-SCHOOL-CLASS` (e.g. `26/27-LMY-2G1`). The Students view lets you
  edit a name or classroom in place, **purge every student whose classroom
  starts with a prefix** (e.g. `25/26` to drop a whole academic year — preview
  first; by default their submissions keep their analyses but lose the student
  name, and the confirmation dialog offers to delete the submissions, analyses
  and their stored files too via a "Delete their submissions & analyses too"
  checkbox that is checked by default), and
  **export/import the roster as CSV** (`GET/POST /api/students/csv`; import is
  idempotent: rows match by id, else by name+classroom, so re-imports update
  instead of duplicating). The Students view also links straight to a student's
  submission history, and the History view can be filtered by student and/or
  classroom prefix (e.g. `26/27-LMY`). A "⚙ Data" menu in the header lets you
  export/import the roster as CSV and reset the database (type `RESET` to
  confirm; optionally also wipes stored files).
2. The model returns a structured JSON report: executive summary, strong
   points (quoted), recurring error patterns (quoted/timestamped), a
   **Proof Matrix** mapping each rubric criterion to a suggested CEFR level
   with evidence, and a draft student feedback (1 success + 1 target).
3. **Attestation synthesis (grille officielle)** — for attestation rubrics
   the report includes a dedicated card: per-criterion level (editable
   dropdowns, A1–C2) → **score /120** (official point scale
   A1=1, A2=3, B1=5, B2=10, C1=20, C2=30) → **attestation level**,
   recomputed deterministically client-side as the teacher edits levels.
   Official thresholds: comprehension A1≥3 / A2≥9 / B1≥15 / B2≥30 / C1≥60 /
   C2≥90; expression A1≥4 / A2≥12 / B1≥20 / B2≥40 / C1≥80 / C2=120.
   The "note sur 20" conversion tables (Première/Termine × LVA/LVB) are shown
   as a reference only (`/api/note-bands`) — the attestation always comes
   from the /120 score, never from the /20 note.
4. **History (Évaluations)** — all submissions/analyses stored in SQLite,
   re-openable; attestation is recomputed on load from the stored matrix. The
   table shows the date, student, classroom, **assignment**, **rubric** and
   the demonstrated level; clicking a row selects it (highlighted) and loads
   the full detail panel below — its header repeats title / student / date /
   assignment / rubric / target / level so the update is unambiguous (a
   "vs target" chip appears when the result differs from the target). Clicking
   the selected row again (or the ✕ / Esc) closes it; rows are
   keyboard-operable (Tab to focus, Enter/Space to open). List filters
   (name + type/level/assignment, combined AND) are collapsed behind a
   "🔍 Filtres" toggle on every viewport.
5. **Rubrics** — presets (attestation grids protected from deletion) + custom
   editor. Each row also has a **Détail** button that opens the official
   matrix below the list (like the reference PDF document): one row per
   criterion × one column per CEFR level (C2→A1), each cell showing the
   level's point value (C2=30 · C1=20 · B2=10 · B1=5 · A2=3 · A1=1) plus
   the level descriptor. The editor form itself stays hidden until a row
   is opened with **Modifier**; **Annuler** closes it without saving.
   Per-student **level-evolution stats** are available from the Students view
   ("Stats": CEFR trajectory across that student's analyses).
6. **Students** — roster with submission counts.
7. **Assignments** — reusable assessment contexts (instruction, document,
   target level, exercise type, evaluation instructions + media) that
   submissions link to. The **Assignments** view's "New assignment" form is a
   modal that accepts the same media as the evaluator form: instruction PDF /
   instruction photos, source-document PDF / audio / photos, and an
   evaluation-instructions PDF (all optional). The same modal edits existing
   assignments (text fields + replacing/removing the 6 file slots). Each row
   has 👁 Details / ▶ Use in evaluator / ✎ edit / ✕ delete, plus a **stats**
   button (aggregates + optional AI insight, see item 1).
8. **Tasks (queue)** — the background job queue view: everything running in
   the background (Whisper transcription, document extraction, AI analysis,
   re-analysis) with live progress, cancel and a hot-adjustable worker count.

## Interface (single-page, FR/EN/ES/DE)

The evaluator form is organised into four numbered cards so the flow reads
top to bottom: **1 · What are we assessing?** (the assignment + its
instruction / source document), **2 · Student & target level** (student +
per-student accommodations + target level), **3 · The student's work**
(written/oral, text or copy photos, audio), **4 · Evaluation settings**
(rubric + evaluation instructions), then the **Save as assignment** /
**Analyze submission** actions. Selecting an assignment shows a compact
assignment card (name, level badge, content badges, collapsible preview,
view / clear buttons) instead of greyed-out fields; the target level is an
explicit **inherited-from-assignment / override** toggle, so it's always
clear whether the level comes from the assignment or was set for this
student. The default target is **"No target (assess only)"** (the model
reports the demonstrated level without a reference point) rather than a
pre-selected B2. On success a toast reports the elapsed time and result, and
the report scrolls into view.
The UI ships in **French, English, Spanish and German**: a flag menu in the
header switches every label client-side and the choice is remembered in
`localStorage`.
Two analysis loops coexist ("IA d'abord / IA après"): run the AI first and
then adjust criterion by criterion, or grade every criterion yourself and ask
the AI for a second opinion (blind or aware of your levels), compare, and
decide — the last AI opinion is kept so you can revert to it.
Written submissions can be **annotated** ("Annoter"): the app interleaves the
AI's line-by-line reading between the OCR'd handwritten lines of each page
photo, with red strike-through detection and editable annotations per line.
The in-app **Docs** view renders the project documentation (this README, the
user guide, the async-jobs architecture) with Mermaid diagrams.

## Safety rails (from the assessment spec)

- No level is suggested without at least one verbatim quote / timestamp
  (the backend warns when a criterion mapping lacks evidence).
- All levels are *recommendations*; the UI says so and nothing is auto-graded.
  The attestation score/level are **editable by the teacher** and recompute
  instantly — they stay suggestions until the teacher confirms.
- Recurrent errors are flagged; isolated slips are not over-penalised (prompt
  rule + "recurring" framing in the report).
- Oral: WPM / pause / hesitation counts are computed deterministically from
  ASR timings, not from the model's impression.
- Reasoning budget: the LLM call caps extended reasoning (`thinking_budget`)
  so the structured JSON reply is never truncated; `max_tokens=10000`.

## Files

```
app/main.py        FastAPI app factory + routes + upload handling
app/assess.py      prompts, fluency metrics, JSON parse/validate
app/llm_client.py  SGLang/OpenAI client (stream + non-stream + JSON extract)
app/whisper.py     offline faster-whisper wrapper (cached model)
app/db.py          SQLite (rubrics, students, submissions, analyses, jobs,
                   annotations, media-ownership cache) + forward migration
app/rubrics.py     rubric presets (LVA/LVB attestation, Bac, BTS, CEFR) +
                   note/20 conversion tables
app/auth.py        multi-user auth (PBKDF2, owner scoping via contextvar)
app/jobs.py        async job queue (scheduler, workers, SSE event streams)
app/ocr.py         hybrid OCR (tesseract line boxes + LLM polish) for "Annoter"
app/imaging.py     image enhancement for OCR of student copy photos
static/index.html  single-page UI (FR/EN/ES/DE i18n, vanilla JS)
docs/async-jobs.md async job queue — architecture, states, flows, screenshots
docs/userguide.md  user guide (teacher-facing, FR)
tests/             Playwright + API E2E suites (p0–p7, media, multiuser, i18n)
run.sh             launcher
```
