# TODO — suite de la revue code + refactoring (état au 2026-10-16)

Contexte : revue code + split de `create_app()` terminés (commits `98810d2` →
`60653ef`). `app/` ruff-clean, 65 routes, tests live verts. Ce qui reste,
classé par priorité. Détail technique : `references/git-and-hygiene.md` du skill
`elt-assessor-app` (Hermes).

**État 2026-10-16 (après la session « Reprenons le projet elt-assessor ») :**
P0 terminé (3 commits : ruff.toml / zones mortes / auto-fix), P1.5 + P1.6
terminés. Il ne reste que **P1.4 (remote git — décision tibo : où pousser)**
et le P2 optionnel.

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

7. **`app/stats.py`** : `db.stats_for_assignment` (152 l) + `stats_for_student`
   (106 l) méritent un module dédié SI les vues stats grossissent. Sinon
   laisser dans db.py (facteur d'éclatement, pas de bug).
8. **Superviseur du serveur** : `run.sh` tourne en tâche d'agent (session
   terminal). Un service systemd (ou s6 sur cette VM) avec
   `Restart=always` + log file stable éviterait les restarts manuels et le
   piège "log uvicorn stale" documenté dans le skill.
9. **Test E2E LLM mocké** : les 3 endpoints longs (`/api/analyze`,
   `/api/evaluate`, `/api/analyses/{id}/run-ai`) ne sont couverts que
   manuellement (~100-130 s chacun avec le vrai qwen38). Un test qui pointe
   `ELT_LLM_BASE` vers un serveur mock OpenAI-compatible validerait la
   file de jobs de bout en bout sans LLM.
10. **Doc "dev" de la nouvelle structure** : la vue Docs in-app (catégorie
    "dev") pourrait gagner un `docs/dev.md` décrivant la découpe
    main.py → routes_*.py/media.py/config.py (schéma mermaid des modules),
    pour qu'un futur contributeur (ou le futur Zia) s'y reprenne sans
    re-découvrir.

## Vérifier avant de clôturer chaque item
- `ruff check .` reste 100 % vert (app/ + tests/ + scripts/, ruff.toml en place)
- `python3 -m py_compile app/*.py`
- serveur : `curl -s localhost:8090/api/health`
- suites (Playwright via `/tmp/elt_dm/venv/bin/python3`, serveur live :8090,
  login `tibo`/`****`) : `tests/test_smoke_assignments.py`,
  `tests/test_p4_filters.py`, `tests/test_p5_filters.py`,
  `tests/test_p7_eval_exit.py`
- suites in-process (venv hermes, temp DB) : `tests/test_multiuser_smoke.py`,
  `tests/test_media_ownership.py`
- commit par item, message explicite (convention du projet).
