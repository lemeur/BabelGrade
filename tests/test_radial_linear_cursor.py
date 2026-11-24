"""Radial menu LINEAR CURSOR (tibo 2026-11-24) — live E2E, desktop 1280 FR.

Proves the new single-cursor wheel/arrow model in rCycle():
  FORWARD:  rien → S(v) → S(v,0) → … → S(v,dernier) → S(v+1,0) → …
  BACKWARD: symétrique — S(v,i) → S(v,i-1) ; S(v,0) → S(v-1,dernier) ;
            S(v) (verbe sans item, atteint au clic) → S(v-1,dernier).

The forward wrap S(v,dernier) → S(v+1,0) is THE fix: with the old rCycle,
the arrows inside a sub-menu could only cycle its L1 items and never
advanced to the next verb — the user was stuck. P8 semantics preserved:
1st press = verb + sub-crown (no item), 2nd press = 1st item.

Run:  /tmp/bg_venv/bin/python tests/test_radial_linear_cursor.py
      (server live on :8090, tests/.credentials present)
"""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []

def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))

# FR labels (as asserted in test_p8_home.py)
EV = ["Sur sujet", "Directe", "Historique"]
AN = ["Progression d’un élève", "Résultats sur un sujet", "Grilles"]
PR = ["Classe / élèves", "Importer une classe (photos)", "Sujet"]

def sel_state(pg):
    return pg.evaluate("""() => ({
      sel: RST.sel,
      l0: [...document.querySelectorAll('#rg-0 .sector')]
          .sort((a,b)=>+a.dataset.idx-+b.dataset.idx)
          .map(s=>s.getAttribute('aria-selected')),
      l1: [...document.querySelectorAll('#rg-1 .sector')]
          .sort((a,b)=>+a.dataset.idx-+b.dataset.idx)
          .map(s=>({sel:s.getAttribute('aria-selected'),
                    t:(s.getAttribute('aria-label')||'').trim()})),
    })""")

def press(pg, key):
    pg.keyboard.press(key)
    pg.wait_for_timeout(250)

with sync_playwright() as pw:
    ctx = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"]) \
           .new_context(viewport={"width": 1280, "height": 800}, locale="fr-FR")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.add_init_script("localStorage.setItem('babelgrade-lang','fr')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username", "tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)

    pg.evaluate("navGo('home',null,{})")
    pg.wait_for_timeout(900)   # laisse finir le fan-out

    s = sel_state(pg)
    check("boot: menu open, rien sélectionné (sel=[null])",
          pg.evaluate("RST.open") and s["sel"] == [None], str(s["sel"]))

    # ---- FORWARD from rien ----
    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F1: ArrowDown → S(0) Évaluer, sous-couronne ouverte SANS item",
          s["sel"] == [0, None]
          and s["l0"] == ["true", "false", "false"]
          and [i["t"] for i in s["l1"]] == EV
          and all(i["sel"] == "false" for i in s["l1"]), str(s))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F2: 2e ArrowDown → S(0,0) 'Sur sujet' (1er item)",
          s["sel"] == [0, 0] and s["l1"][0]["sel"] == "true"
          and s["l1"][0]["t"] == "Sur sujet", str(s["sel"]))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F3: ArrowDown → S(0,1) 'Directe'",
          s["sel"] == [0, 1] and s["l1"][1]["sel"] == "true", str(s["sel"]))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F4: ArrowDown → S(0,2) 'Historique' (dernier item d'Évaluer)",
          s["sel"] == [0, 2] and s["l1"][2]["sel"] == "true", str(s["sel"]))

    # ---- THE FIX: forward wrap to the next verb + its 1st item ----
    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F5 (LE FIX): S(0,dernier)+ArrowDown → S(1,0) Analyser + 'Progression d’un élève'",
          s["sel"] == [1, 0]
          and s["l0"] == ["false", "true", "false"]
          and s["l1"][0]["sel"] == "true" and s["l1"][0]["t"] == "Progression d’un élève",
          str(s))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F6: → S(1,1) 'Résultats sur un sujet'",
          s["sel"] == [1, 1] and s["l1"][1]["t"] == "Résultats sur un sujet", str(s["sel"]))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F7: → S(1,2) 'Grilles' (dernier item d'Analyser)",
          s["sel"] == [1, 2] and s["l1"][2]["t"] == "Grilles", str(s["sel"]))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("F8: 2e wrap → S(2,0) Préparer + 'Classe / élèves'",
          s["sel"] == [2, 0]
          and s["l0"] == ["false", "false", "true"]
          and s["l1"][0]["t"] == "Classe / élèves", str(s))

    # ---- BACKWARD (symétrique) ----
    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B1: S(2,0)+ArrowUp → S(1,2) 'Grilles' (dernier item du verbe précédent)",
          s["sel"] == [1, 2] and s["l0"][1] == "true" and s["l1"][2]["sel"] == "true", str(s))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B2: → S(1,1)", s["sel"] == [1, 1], str(s["sel"]))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B3: → S(1,0)", s["sel"] == [1, 0], str(s["sel"]))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B4: wrap arrière → S(0,2) 'Historique' (dernier item d'Évaluer)",
          s["sel"] == [0, 2] and s["l1"][2]["t"] == "Historique", str(s))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B5: S(0,2)+ArrowUp → S(0,1)", s["sel"] == [0, 1], str(s["sel"]))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B6: S(0,1)+ArrowUp → S(0,0)", s["sel"] == [0, 0], str(s["sel"]))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("B7: wrap arrière depuis S(0,0) → S(2,2) 'Sujet' (verbe précédent, dernier item)",
          s["sel"] == [2, 2] and s["l0"][2] == "true" and s["l1"][2]["t"] == "Sujet", str(s))

    # ---- S(v) sans item (verbe atteint au clic) ----
    pg.evaluate("rPick(0,1)")   # clic sur Analyser → L1 ouverte sans item
    pg.wait_for_timeout(400)
    s = sel_state(pg)
    check("C1: clic verbe → S(1) sans item (L1 ouverte, rien de sélectionné)",
          s["sel"] == [1, None] and all(i["sel"] == "false" for i in s["l1"]), str(s))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("C2: S(1)+ArrowDown → S(1,0)", s["sel"] == [1, 0], str(s["sel"]))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("C3: S(1,0)+ArrowUp → S(0,2) 'Historique' (retour au verbe précédent)",
          s["sel"] == [0, 2], str(s))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("C4: S(0,2)+ArrowUp → S(0,1) (rétrograde dans le même verbe)",
          s["sel"] == [0, 1], str(s["sel"]))

    # ---- BACKWARD from rien ----
    pg.evaluate("pieClose()")
    pg.wait_for_timeout(400)
    pg.click("#home-reopen")
    pg.wait_for_timeout(600)
    s = sel_state(pg)
    check("D0: réouverture → rien sélectionné", s["sel"] == [None], str(s["sel"]))

    press(pg, "ArrowUp")
    s = sel_state(pg)
    check("D1: ArrowUp depuis rien → S(2) Préparer (verbe dernier), L1 sans item",
          s["sel"] == [2, None]
          and s["l0"] == ["false", "false", "true"]
          and [i["t"] for i in s["l1"]] == PR, str(s))

    press(pg, "ArrowDown")
    s = sel_state(pg)
    check("D2: puis ArrowDown → S(2,0) 'Classe / élèves'",
          s["sel"] == [2, 0] and s["l1"][0]["sel"] == "true", str(s["sel"]))

    # ---- wheel = même modèle (deltaY>0 → +1) ----
    pg.evaluate("pieClose()")
    pg.wait_for_timeout(400)
    pg.click("#home-reopen")
    pg.wait_for_timeout(600)
    pg.mouse.move(640, 450)
    pg.mouse.wheel(0, 120)
    pg.wait_for_timeout(250)
    s = sel_state(pg)
    check("E1: molette ↓ depuis rien → S(0) (même modèle que les flèches)",
          s["sel"] == [0, None], str(s["sel"]))

    # ---- Enter exécute la feuille après un wrap (S(1,0) → #students) ----
    press(pg, "ArrowDown")     # S(0,0)
    press(pg, "ArrowDown")     # S(0,1)
    press(pg, "ArrowDown")     # S(0,2)
    press(pg, "ArrowDown")     # S(1,0) 'Progression d’un élève'
    s = sel_state(pg)
    check("F9: 4 Appuis depuis S(0) → S(1,0) via le wrap", s["sel"] == [1, 0], str(s["sel"]))
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(500)
    post = pg.evaluate("""() => ({open: document.getElementById('pie-wrap').classList.contains('open'),
      hash: location.hash})""")
    check("F10: Enter sur S(1,0) 'Progression d’un élève' → #students, menu fermé",
          post["open"] is False and post["hash"] == "#students", str(post))

    check("0 page errors", len(errors) == 0, str(errors))
    ctx.close()

print("=" * 40)
print(f"=== {len(PASS)} PASS / {len(FAIL)} FAIL ===")
if FAIL:
    print("FAILED:", FAIL)
    raise SystemExit(1)
