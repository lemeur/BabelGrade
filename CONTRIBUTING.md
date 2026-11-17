# Contributing to BabelGrade

Thanks for improving BabelGrade. This is a short map of the repo and how to
run things locally. The app is a FastAPI backend + a single-page vanilla-JS
front end, plus an offline LLM/Whisper pipeline.

## Prerequisites

- Python **3.11+**
- Node (only needed for the i18n state test, which shells out to `node --check`)
- An OpenAI-compatible LLM endpoint with **vision** (by default SGLang serving
  `qwen38-27b`). Audio is handled by offline Whisper, never by the LLM.
- faster-whisper (installs from `requirements.txt`; the model is fetched into
  the Hugging Face cache on first use, then runs offline).

## Running the app

```bash
pip install -r requirements.txt
./run.sh                 # serves on http://127.0.0.1:8090
```

The LLM endpoint is configured via `BABELGRADE_LLM_BASE` /
`BABELGRADE_LLM_MODEL` (see the table in the README). On the first boot the
`BABELGRADE_INITIAL_LOGIN` account is created and registration stays open only
for that account.

> **Backend `.py` edits need a restart.** `run.sh` starts uvicorn *without*
> `--reload`, so any change to `app/*.py` is not live until the server is
> restarted. The front end (`static/index.html`) is served fresh on each
> browser load — just hard-refresh.

### Safe server kill / relaunch

```bash
# stop the running server (the [.] stops pgrep matching its own shell)
P=$(pgrep -f 'uvicorn app[.]main'); [ -n "$P" ] && kill "$P"

# relaunch in the background
cd /path/to/babelgrade && ./run.sh &
curl -s localhost:8090/api/health
```

## Running tests

The suite splits into two classes.

### Hermetic / in-process suites (no live server, no LLM, no Whisper)

These are the fast, safe, CI-run tests. Run them straight:

```bash
python tests/test_multiuser_smoke.py
python tests/test_media_ownership.py
python tests/test_p2_mock_llm_e2e.py
python tests/test_roster_import.py
python tests/test_ui_language_prompt.py
python tests/test_p0_state_i18n_js.py        # needs node
python -m pytest tests/test_ocr_resnap.py -q
```

`tests/conftest.py` puts the project root on `sys.path`, so these import the
real app in-process against a throwaway SQLite DB. `tests/mock_llm_server.py`
is a stdlib OpenAI-compatible mock the pipeline tests point at — no real model.

### Live Playwright suites

The `test_p0_*` … `test_p8_*` files drive the real UI in Chromium against a
running server on `127.0.0.1:8090`. They read the live login from
`tests/.credentials` (gitignored). To run them:

1. Start the server (`./run.sh &`).
2. Create `tests/.credentials` with the live-server login used by the suites.
3. Run with a Playwright-enabled interpreter:
   `python -m playwright install chromium` once, then `python tests/test_p0_*.py`.

These are intentionally not in CI: they need a live server and real credentials.

## Linting

```bash
ruff check .            # app/ strict; tests/ + scripts/ + mockups/ relaxed
ruff check . --fix      # auto-fix unused imports etc.
```

`app/` is held to the strict rule set; `tests/`, `scripts/`, `mockups/` and
`mock-hybrid/` relax `E401`/`E402`/`E701`/`E702` (compact test one-liners and
multi-imports are noise to reformat there).

## Conventions worth preserving

These are load-bearing; breaking them causes subtle regressions. The full
list, with rationale and recipes, lives in [docs/architecture.md](docs/architecture.md):

- **Import direction is one-way:** `db → stats → routes`. `stats.py` must not
  re-export from `db.py` (that creates a circular import).
- **Owner scoping is enforced on every request** via the auth dependency;
  every owned table carries an `owner_id`.
- **Proof Matrix invariant:** no suggested level without at least one verbatim
  quote / timestamp.
- **Media ownership:** `/api/files` serves a file only to its owner.
- **i18n:** every key is defined exactly 4× (FR/EN/ES/DE). After editing the
  UI, run `tests/test_p0_state_i18n_js.py`.
- **Forward migration:** the schema is additive at startup — add missing
  columns in `init_db`, don't write manual migrations.
- **`routes_annotate` is mounted before `routes_analyses`** in `main.py` so
  `GET /api/submissions/{id}.ocr` is not swallowed by the integer-parsing
  `/api/submissions/{id}` route.

## Commit style

One commit per verified chunk, with a concise, imperative message describing
what changed and why. Keep the tree `ruff`-clean and keep the hermetic suites
green before you commit.
