# TODO — suite de la revue code + refactoring (état au 2026-10-16)

Contexte : revue code + split de `create_app()` terminés (commits `98810d2` →
`60653ef`). `app/` ruff-clean, 65 routes, tests live verts. Ce qui reste,
classé par priorité. Détail technique : `references/git-and-hygiene.md` du skill
`elt-assessor-app` (Hermes).

**État 2026-10-18 (après Annoter word-selection) :** P0, P1.5 + P1.6, P2.7,
P2.9 + P2.10 terminés ; **OCR LLM-direct (2026-10-17) livré et commité**
(`7f72844` + screenshots `29f3c4e`) : pipeline tesseract+polish remplacé par
transcription directe par le LLM vision (boxes de lignes 0..1000, markers
`[X:word]`/`[TAPE]`/`[FR]`/`[?]`), Annoter v4 vue double (photo +
transcript). **Annoter v5 : sélection par mots (2026-10-18)** — backend :
`words` Whisper persistées dans `transcript_json` (jobs.py, commit `193e1b2`)
+ spans `{page,start_word,end_word}` avec derivation `start_line/end_line`
(`app/routes_annotate.py` `_page_words` = tokenisation `split(" ")` qui doit
rester BYTE-IDENTIQUE au frontend `anPageWords()`) ; UI : mots cliquables
(`.an-w`, 1er+dernier mot, drag hover), crop photo sur bbox des lignes
couvertes (4 masques `.an-crop`, le `<img>` est re-parenté avant destruction
de l'ancien wrapper `.an-croph` — bug corrigé 2026-10-18), quote serveur
écrit/oral (mots avec fallback segments pour les legacy), i18n `annot.cropSel`
+ hint ×4 langues. Tests : `tests/test_word_selection.py` 12/12 (écrit +
oral fallback + 390px, teardown annotation). Suites live + in-process toutes
vertes (2026-10-18 : 25 suites, cf. baseline). Le reste : **P1.4 (remote
git — décision tibo : où pousser)** et P2.8 (systemd/s6 supervisor).

## P0 — ✅ TERMINÉ (2026-10-16)

1. **Config ruff** ✅ `ruff.toml` à la racine : `app/` strict (E4/E7/E9/F),
   `tests/` + `scripts/` relâchés (E401/E402/E701/E702). `ruff check .` 100 %
   vert partout + anti-régression (commit `6384309`).
2. **Zones mortes à la racine** ✅ **supprimées définitivement** (décision
   tibo 2026-10-16) : `mock-dual-mode/` + `mock-eval-mode/`, `crop_*.jpg`
   `conv_*.jpg` `derive_bands.py`, `scripts/gen_media.py` `gen_media_en.py`
   `photo_gen.py` + `media_content*.py` (commit `729157f`). Gardés :
   `probe_llm.py`, `scripts/gen_fixtures.py` (fixture 40 élèves encore
   référencé par la DB live), `tests/` complets.
3. **Auto-fix restant** ✅ `ruff check . --fix` (22 imports inutilisés) + 3
   fixes manuels E702/E741 (`probe_llm.py`, `gen_fixtures.py`,
   `test_p3_ergo.py`). Revalidation : p4 22/22, p5 29/29, p7 18/18, p3 25/25,
   multiuser smoke + media ownership ALL PASS (commit `c84ff16`).

## P1 — robustitude

4. **Remote git + push** : ⏳ EN ATTENTE DE DÉCISION TIBO (choix du 2026-10-16 :
   « décision plus tard »). Le repo est local-only (`git remote -v` = vide).
   À décider : GitHub privé vs repo bare sur le NAS Syno (juliesbook).
   Sans remote, la sécurité du repo ne protège que contre l'erreur de code,
   pas contre la panne disque.
5. **Smoke suite dans le repo** ✅ `tests/test_smoke_assignments.py` (25
   checks, re-création de l'ancien `/tmp/elt_asgn/smoke.py` périmé par le
   gate d'auth) : login helper `tibo`/`****`, create via modal
   (champ `#asg-target` caché derrière le lvl carousel → set via JS,
   pills `data-pv`), edit prefill, delete UI (confirm auto-accept),
   ad-hoc entry, 390px overflow, teardown propre. Commit `78a1253`.
6. **Suppression du cache orphelin** ✅ `./~/.cache/` (142 Mo) supprimé le
   2026-10-16 après vérification : aucune référence dans le code
   (`app/whisper.py` → `/home/tibo/.cache/huggingface/hub`, le vrai cache,
   toujours intact), gitignored.

## P2 — optionnel / long terme

7. **`app/stats.py`** ✅ (2026-10-16, commit `715e46c`) : `db.stats_for_assignment`
   + `db.stats_for_student` extraits dans un module dédié `app/stats.py`
   (sens unique `db ← stats ← routes`, **pas** de re-export depuis db.py —
   un re-export créerait une importation circulaire `db↔stats`). Les 2 route
   files appellent désormais `stats.stats_for_assignment/…student` (variable
   locale renommée `data`/`agg` car `stats` = le module). `db.py` -264 l.
   E2E live vérifié (stats assign 48 = 38 eval / 2 classes / 4 critères,
   stats élève 128 = 4 points codes R/L/S/W, 404 inconnu, p6_ststats 9/9,
   smoke 25/25).
8. **Superviseur du serveur** : `run.sh` tourne en tâche d'agent (session
   terminal). Un service systemd (ou s6 sur cette VM) avec
   `Restart=always` + log file stable éviterait les restarts manuels et le
   piège "log uvicorn stale" documenté dans le skill.
9. **Test E2E LLM mocké** ✅ (2026-10-17, commit `P2.9`) : les 3 endpoints longs
   (`/api/analyze`, `/api/evaluate`, `/api/analyses/{id}/run-ai`) couverts de bout
   en bout SANS vrai LLM. `tests/mock_llm_server.py` = serveur OpenAI-compatible
   stdlib (127.0.0.1) : `POST /v1/chat/completions` (SSE stream + non-stream) et
   `GET /v1/models` ; il **construit** une réponse conforme au schéma exact de
   l'app en repérant les critères dans le prompt (« Criteria:\n- <c> : … »), avec
   verbatim quote + un marqueur (FRESH-B1 vs CONFIRMED-B1) pour distinguer blind
   vs aware. `tests/test_p2_mock_llm_e2e.py` (in-process, temp DB, `ELT_LLM_BASE`
   pointé vers le mock AVANT import de l'app, lifespan via `TestClient` context
   manager) : 37 checks — enqueue→claim→run→finalize→done, matrice persistée
   (1 entry/critère, ordre exact, evidence partout), attestation déterministe
   (A2+A2+B1+B2=21→B1), raw_markdown, evaluate→skeleton vide (pas de LLM),
   run-ai aware (matrice prof non touchée, ai_matrix remplie, last-AI-wins,
   ai_mode, marqueur CONFIRMED-B1), SSE `/api/analyze/stream` (meta→phase*→token*
   →result→done, ordre vérifié), jobs counts/get/cancel(409)/404. `STREAM_PRE_DELAY`
   sur le mock fait que le subscriber attache au live stream (comme en prod où le
   vrai LLM tient ~100 s) plutôt qu'au chemin late-subscriber DB-rebuild.
10. **Doc "dev" de la nouvelle structure** ✅ (2026-10-16) : `docs/architecture.md`
    (slug `architecture`, catégorie dev, 1er sous-onglet de la section Dev) —
    module map (table + flowchart mermaid UI→routes→domain→I/O, direction
    d'import unidirectionnelle), séquence des 3 endpoints longs, conventions
    à préserver (owner scoping, proof-matrix, media ownership, last-AI-wins,
    déléguation document-level, shadowing i18n/`stats`, forward migration),
    recette "ajout endpoint" + "ajout doc in-app" + baseline de vérification.
    Wiring : `DOCS_INDEX` (docs_catalog.py) + `docs.tab.architecture` ×4
    langues + ternaire de labels sub-tabs (`paintDocsSubtabs`). README :
    file map resynchronisée avec le split (routes_*/stats/media/config/
    docs_catalog). `tests/test_p1_devdocs.py` mis à jour (15 checks, 4
    sous-onglets dev).

## Vérifier avant de clôturer chaque item
- `ruff check .` reste 100 % vert (app/ + tests/ + scripts/, ruff.toml en place)
- `python3 -m py_compile app/*.py`
- serveur : `curl -s localhost:8090/api/health`
- suites (Playwright via `/tmp/elt_dm/venv/bin/python3`, serveur live :8090,
  login `tibo`/`****`) : `tests/test_smoke_assignments.py`,
  `tests/test_p4_filters.py`, `tests/test_p5_filters.py`,
  `tests/test_p7_eval_exit.py`
- suites in-process (venv hermes, temp DB) : `tests/test_multiuser_smoke.py`,
  `tests/test_media_ownership.py`, `tests/test_p2_mock_llm_e2e.py` (mock LLM,
  37 checks, ~2 s)
- commit par item, message explicite (convention du projet).
