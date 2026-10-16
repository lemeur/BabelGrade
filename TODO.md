# TODO — suite de la revue code + refactoring (état au 2026-10-16)

Contexte : revue code + split de `create_app()` terminés (commits `98810d2` →
`60653ef`). `app/` ruff-clean, 65 routes, tests live verts. Ce qui reste,
classé par priorité. Détail technique : `references/git-and-hygiene.md` du skill
`elt-assessor-app` (Hermes).

## P0 — quick wins (~1 h, zéro risque fonctionnel)

1. **Config ruff** (`ruff.toml` à la racine) : `app/` strict (défauts actuels),
   `tests/` + `scripts/` relâchés (`ignore = ["E702"]` au moins, ~103 findings
   de style actuels dont 29 auto-fixables). Objectif : `ruff check .` 100 %
   vert partout + anti-régression. Commande :
   `ruff check app/ tests/ scripts/` après pour vérifier.
2. **Zones mortes à la racine** (à confirmer avec tibo avant deletion) :
   - `mock-dual-mode/` + `mock-eval-mode/` (protos d'oct 2026-10-02, obsolètes)
   - `crop_*.jpg` `conv_*.jpg` `derive_bands.py` (artefacts one-shot de la
     dérive des tables note/20, 2026-09-22)
   - `scripts/gen_media.py` `gen_media_en.py` `photo_gen.py` (générateurs de
     fixtures one-shot)
   - Option : dossier `archive/` (git-ignored ou commité selon valeur
     historique) plutôt que `rm`.
3. **Auto-fix restant** : `ruff check tests/ scripts/ --fix` (après config,
   29 corrections auto ; relancer les 3 Playwright verts pour valider).

## P1 — robustitude (~2-3 h)

4. **Remote git + push** : le repo est local-only (`git remote -v` = vide).
   Ajouter un remote (GitHub privé, ou repo bare sur un NAS) et pousser.
   Sans remote, la sécurité du repo ne protège que contre l'erreur de code,
   pas contre la panne disque. Décision tibo : où pousser.
5. **Smoke suite dans le repo** : `/tmp/elt_asgn/smoke.py` (25 checks UI
   Assignments/Evaluations) date d'AVANT le gate d'auth (oct 2026-10-06) et
   est périmé (`#auth-gate` bloque le clic) ; /tmp disparaît au reboot.
   Recréer `tests/test_smoke_assignments.py` avec le pattern login
   (`tibo`/`****`, helper `login(pg)` de `tests/test_p5_filters.py`)
   + teardown des lignes créées.
6. **Suppression du cache orphelin** `./~/.cache/` (142 Mo, créé le
   2026-09-19 par un `~` non expansé) : `app/whisper.py` pointe vers
   `/home/tibo/.cache/huggingface/hub` (vrai cache) — vérifier qu'aucun autre
   chemin ne pointe dans `./~/` puis `rm -rf ./~`. Gitignored déjà.

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
- `ruff check app/` reste clean
- `python3 -m py_compile app/*.py`
- serveur : `curl -s localhost:8090/api/health`
- suites : `tests/test_media_ownership.py`, `tests/test_multiuser_smoke.py`,
  `tests/test_p4_filters.py`, `tests/test_p5_filters.py`, `tests/test_p7_eval_exit.py`
- commit par item, message explicite (convention du projet).
