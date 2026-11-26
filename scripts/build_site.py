#!/usr/bin/env python3
"""Build the BabelGrade GitHub Pages site into site/.

The app no longer ships the docs (in-app Docs view was removed in favour of
this site, 2026-11). Everything the site needs lives in the repo:
  docs/userguide.md, docs/architecture.md, docs/async-jobs.md,
  README.md (dev docs)  -> markdown pages
  docs/assets/**                            -> images
  docs/onepager-fr/**                       -> one-pager (interactive HTML + PDF)
  static/logo.svg + favicon.png             -> branding

Run from the repo root:  python3 scripts/build_site.py
Needs: python-markdown (extensions: tables, fenced_code) — available in the
hermes venv; any env with `pip install markdown` works.

Output: site/  (GitHub Pages root) — push main and Pages deploys the folder.
The site is PUBLIC: only add content to docs/ that you are happy publishing
(the app itself stays behind its login).
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"

DEV_DOCS = {
    "architecture": ROOT / "docs" / "architecture.md",
    "async-jobs": ROOT / "docs" / "async-jobs.md",
    "readme": ROOT / "README.md",
}
USER_DOC = ROOT / "docs" / "userguide.md"
ONEPAGER_SRC = ROOT / "docs" / "onepager-fr"
ASSETS_SRC = ROOT / "docs" / "assets"

try:
    import markdown  # type: ignore
    from markdown.extensions.toc import TocExtension
except ImportError:
    sys.exit("python-markdown missing: pip install markdown (hermes venv has it)")

CSS = """
:root{--bg:#f4f6f9;--panel:#fff;--ink:#1c2430;--muted:#64748b;--line:#e2e8f0;
 --acc:#2563eb;--acc-soft:#eff6ff;--ok:#16a34a;--err:#dc2626}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.hd{max-width:1060px;margin:0 auto;display:flex;align-items:center;gap:14px;
 flex-wrap:wrap;padding:10px 20px}
.hd .logo{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
.hd .logo img{height:34px;width:auto}
.hd .logo b{font-size:17px;letter-spacing:.2px}
.hd nav{display:flex;gap:2px;flex-wrap:wrap;margin-left:auto}
.hd nav a{padding:7px 12px;border-radius:8px;text-decoration:none;color:var(--muted);
 font-size:14px;font-weight:600}
.hd nav a:hover{color:var(--acc);background:var(--acc-soft)}
.hd nav a.on{color:var(--acc);background:var(--acc-soft)}
.hd nav a.ext::after{content:" ↗";font-size:12px}
main{max-width:1060px;margin:0 auto;padding:30px 20px 60px}
.hero{background:linear-gradient(135deg,var(--acc-soft),#fff 70%);border:1px solid var(--line);
 border-radius:18px;padding:44px 36px;margin-bottom:28px;text-align:center}
.hero img{height:84px;margin-bottom:18px}
.hero h1{font-size:34px;margin:0 0 10px}
.hero p.sub{font-size:17px;color:var(--ink);margin:0 auto 6px;max-width:680px}
.hero p.sub.en{color:var(--muted);font-size:14.5px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;
 text-decoration:none;color:var(--ink);display:block;transition:transform .12s,border-color .12s}
.card:hover{transform:translateY(-2px);border-color:var(--acc)}
.card .ico{font-size:26px}
.card h3{margin:10px 0 6px;font-size:16.5px}
.card p{margin:0;color:var(--muted);font-size:13.5px}
.card.ext-link::after{content:" ↗";color:var(--acc);font-weight:700}
.md{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:34px 38px}
.md h1{font-size:27px;border-bottom:2px solid var(--acc-soft);padding-bottom:9px;margin:26px 0 14px}
.md h1:first-child{margin-top:0}
.md h2{font-size:21px;margin:26px 0 10px}
.md h3{font-size:17px;margin:20px 0 8px}
.md p{margin:10px 0}
.md a{color:var(--acc)}
.md blockquote{border-left:4px solid var(--acc-soft);background:var(--acc-soft);margin:12px 0;
 padding:8px 14px;border-radius:0 8px 8px 0;color:#475569}
.md code{font:13px/1.5 ui-monospace,Menlo,monospace;background:#f1f5f9;
 border:1px solid var(--line);border-radius:5px;padding:1px 5px}
.md pre{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px 14px;overflow-x:auto;
 margin:12px 0;font:13px/1.6 ui-monospace,Menlo,monospace}
.md pre code{background:none;border:none;color:inherit;padding:0}
.md ul,.md ol{padding-left:24px;margin:10px 0}
.md li{margin:4px 0}
.md table{border-collapse:collapse;margin:14px 0;width:100%;font-size:14px;display:block;overflow-x:auto}
.md th,.md td{border:1px solid var(--line);padding:7px 10px;text-align:left}
.md th{background:#f8fafc}
.md tr:nth-child(even) td{background:#fafafa}
.md img{max-width:100%;border:1px solid var(--line);border-radius:10px;margin:10px 0}
.md hr{border:none;border-top:1px solid var(--line);margin:20px 0}
.md .mermaid{background:#fff;border:1px solid var(--line);border-radius:10px;
 padding:14px;margin:14px 0;text-align:center;overflow-x:auto}
/* ---- document layout: sticky TOC sidebar + scroll-spy (user guide) ---- */
html{scroll-behavior:smooth}
.md h2,.md h3{scroll-margin-top:84px}
.doc{display:grid;grid-template-columns:252px minmax(0,1fr);gap:26px;align-items:start}
.doc-toc{position:sticky;top:74px;max-height:calc(100vh - 96px);overflow:auto;
 background:var(--panel);border:1px solid var(--line);border-radius:14px;
 padding:14px 10px}
.doc-toc-head{font-weight:700;font-size:11.5px;letter-spacing:.5px;
 text-transform:uppercase;color:var(--muted);margin:2px 8px 8px}
.doc-toc .toc ul{list-style:none;padding:0;margin:0}
.doc-toc .toc a{display:block;padding:5px 10px;border-radius:7px;color:var(--muted);
 font-size:13.5px;font-weight:500;text-decoration:none;border-left:2px solid transparent;
 margin:1px 0}
.doc-toc .toc a:hover{color:var(--acc);background:var(--acc-soft)}
.doc-toc .toc a.on{color:var(--acc);background:var(--acc-soft);
 border-left-color:var(--acc);font-weight:650}
.doc-toc .toc li ul{margin:1px 0 1px 8px;padding-left:6px}
.doc-toc .toc li li a{padding:4px 10px 4px 20px;font-size:12.5px}
footer{max-width:1060px;margin:0 auto;padding:0 20px 40px;color:var(--muted);
 font-size:13px;text-align:center}
footer a{color:var(--acc);text-decoration:none}
@media(max-width:880px){
 .doc{grid-template-columns:1fr;gap:16px}
 .doc-toc{position:static;max-height:300px}}
@media(max-width:640px){
 .md{padding:20px 16px}.hero{padding:30px 18px}.hero h1{font-size:27px}}
"""

HEAD = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="icon" type="image/png" href="favicon.png">
<link rel="stylesheet" href="site.css">
{mermaid}
</head>
<body>
<header>
  <div class="hd">
    <a class="logo" href="./"><img src="logo.svg" alt=""><b>BabelGrade</b></a>
    <nav>
      <a href="./" {on_home}>Accueil</a>
      <a href="userguide.html" {on_guide}>Guide utilisateur</a>
      <a href="onepager/onepager.html" {on_one}>One-pager</a>
      <a href="architecture.html" {on_arch}>Architecture</a>
      <a href="async-jobs.html" {on_async}>Async jobs</a>
      <a href="readme.html" {on_readme}>README</a>
      <a class="ext" href="https://github.com/lemeur/BabelGrade">GitHub</a>
    </nav>
  </div>
</header>
<main>
{body}
</main>
<footer>BabelGrade — évaluation CEFR 100 % locale · <a href="https://github.com/lemeur/BabelGrade">dépôt GitHub</a> · licence MIT</footer>
{mermaid_run}
</body>
</html>
"""

MERMAID_TAG = ""
MERMAID_RUN = """<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });
document.querySelectorAll("pre > code.language-mermaid").forEach(function (code) {
  var div = document.createElement("div");
  div.className = "mermaid";
  div.textContent = code.textContent;
  code.parentElement.replaceWith(div);
});
mermaid.run({ querySelector: ".mermaid", suppressErrors: true });
</script>
"""

# Scroll-spy: highlight the TOC entry of the section in view (user guide only).
# Robust approach: on scroll, the active section is the last heading whose top
# has crossed above the band-top line; if none, the first section.
SCROLL_SPY = """<script>
(function () {
  var links = document.querySelectorAll('.doc-toc .toc a[href^="#"]');
  if (!links.length) return;
  var pairs = [];
  links.forEach(function (a) {
    var el = document.getElementById(a.getAttribute('href').slice(1));
    if (el) pairs.push({ el: el, a: a });
  });
  if (!pairs.length) return;
  var BAND_TOP = 120;  // px from viewport top: a heading above this line is "current"
  var activeA = null;
  function update() {
    var cur = null;
    for (var i = 0; i < pairs.length; i++) {
      var top = pairs[i].el.getBoundingClientRect().top;
      if (top <= BAND_TOP) cur = pairs[i];  // last heading above the band
    }
    if (!cur) cur = pairs[0];  // at the very top, the first section is active
    if (cur.a === activeA) return;
    if (activeA) activeA.classList.remove('on');
    activeA = cur.a;
    activeA.classList.add('on');
    var toc = activeA.closest('.doc-toc');
    if (toc && activeA.offsetTop > toc.scrollTop + 60) {
      toc.scrollTo({ top: activeA.offsetTop - 80, behavior: 'smooth' });
    }
  }
  window.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update, { passive: true });
  update();
})();
</script>
"""


def md_to_body(md: str, toc: bool = False) -> tuple[str, bool, str]:
    """markdown -> HTML; returns (body_html, has_mermaid, toc_html).

    When toc=True, h2/h3 are given stable ids and a <div class="toc"> is
    extracted out of the body (it lands in the sidebar)."""
    has_mermaid = bool(re.search(r"^```mermaid", md, re.M))
    exts: list = ["tables", "fenced_code"]
    toc_html = ""
    if toc:
        mdo = markdown.Markdown(extensions=exts + [TocExtension(permalink=False, toc_depth=2)])
        html = mdo.convert(md)
        toc_html = mdo.toc  # the extension stores the <div class="toc"> here
        # the H1 entry wraps the whole h2 list in a nested <ul>; unwrap it so
        # the sidebar starts flat at the first section
        if toc_html:
            h1m = re.search(r'<h1[^>]+id="([^"]+)"', html)
            if h1m:
                unwrapped = re.sub(
                    r'<li>\s*<a href="#' + re.escape(h1m.group(1)) + r'">.*?</a>\s*<ul>\s*(.*?)\s*</ul>\s*</li>',
                    r'\1', toc_html, count=1, flags=re.S)
                toc_html = unwrapped if unwrapped != toc_html else re.sub(
                    r'<li>\s*<a href="#' + re.escape(h1m.group(1)) + r'">.*?</a>\s*</li>\s*',
                    '', toc_html, count=1, flags=re.S)
    else:
        html = markdown.markdown(md, extensions=exts)
    # repo-relative links -> site-relative
    html = html.replace('src="docs/readme/', 'src="readme/')
    html = html.replace('href="docs/readme/', 'href="readme/')
    for src, dst in (("docs/userguide.md", "userguide.html"),
                     ("docs/architecture.md", "architecture.html"),
                     ("docs/async-jobs.md", "async-jobs.html"),
                     ("docs/onepager-fr/onepager.html", "onepager/onepager.html"),
                     ("docs/onepager-fr/onepager.pdf", "onepager/onepager.pdf"),
                     ("README.md", "readme.html"),
                     ("TODO.md", "https://github.com/lemeur/BabelGrade/blob/main/TODO.md"),
                     ("requirements.txt", "https://github.com/lemeur/BabelGrade/blob/main/requirements.txt"),
                     ("LICENSE", "https://github.com/lemeur/BabelGrade/blob/main/LICENSE"),
                     ("CONTRIBUTING.md", "https://github.com/lemeur/BabelGrade/blob/main/CONTRIBUTING.md"),
                     (".github/workflows/ci.yml", "https://github.com/lemeur/BabelGrade/blob/main/.github/workflows/ci.yml"),
                     ("src=\"static/logo.png\"", "src=\"logo.svg\"")):
        html = html.replace(src, dst)
    return html, has_mermaid, toc_html


def on(flag: bool) -> str:
    return 'class="on"' if flag else ""


def page(title: str, body: str, has_mermaid: bool, lang: str = "fr", active: str = "") -> str:
    flags = {"home": active == "home", "guide": active == "guide",
             "one": active == "one", "arch": active == "arch",
             "async": active == "async", "readme": active == "readme"}
    return HEAD.format(
        lang=lang,
        title=title,
        mermaid=MERMAID_TAG if has_mermaid else "",
        body=body,
        mermaid_run=MERMAID_RUN if has_mermaid else "",
        on_home=on(flags["home"]), on_guide=on(flags["guide"]),
        on_one=on(flags["one"]), on_arch=on(flags["arch"]),
        on_async=on(flags["async"]),
        on_readme=on(flags["readme"]),
    )


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    (OUT / "site.css").write_text(CSS, encoding="utf-8")
    shutil.copy2(ROOT / "static" / "logo.svg", OUT / "logo.svg")
    shutil.copy2(ROOT / "static" / "favicon.png", OUT / "favicon.png")
    shutil.copytree(ASSETS_SRC, OUT / "assets")
    shutil.copytree(ROOT / "docs" / "readme", OUT / "readme")   # README screenshots
    shutil.copytree(ONEPAGER_SRC, OUT / "onepager")

    # --- landing page
    landing = """
<div class="hero">
  <img src="logo.svg" alt="">
  <h1>BabelGrade</h1>
  <p class="sub">Évaluation CEFR 100&nbsp;% locale&nbsp;: une copie manuscrite ou un enregistrement
  oral devient une attestation LVA/LVB /120, avec l'aide optionnelle d'agents IA
  qui tournent sur votre machine. Aucune donnée d'élève ne quitte votre environnement.</p>
  <p class="sub en">100% local CEFR assessment: a handwritten copy or an oral recording becomes a
  LVA/LVB /120 attestation, with optional AI agents that all run on your machine.</p>
</div>
<div class="cards">
  <a class="card" href="userguide.html"><span class="ico">📖</span>
    <h3>Guide utilisateur</h3><p>Manuel de l'enseignant : sujets, évaluations, grilles, élèves, tâches.</p></a>
  <a class="card" href="onepager/onepager.html"><span class="ico">🗒️</span>
    <h3>One-pager interactif</h3><p>La synthèse du projet en une page A4 (HTML + PDF).</p></a>
  <a class="card ext-link" href="https://github.com/lemeur/BabelGrade"><span class="ico">🐙</span>
    <h3>Dépôt GitHub</h3><p>Code source, CI, issues — licence MIT.</p></a>
  <a class="card" href="architecture.html"><span class="ico">🧩</span>
    <h3>Documentation développeurs</h3><p>Architecture, jobs asynchrones, README technique.</p></a>
</div>
"""
    (OUT / "index.html").write_text(
        page("BabelGrade — évaluation CEFR locale", landing, False, active="home"), encoding="utf-8")

    # --- user guide (document layout: sticky TOC sidebar + scroll-spy)
    md = USER_DOC.read_text(encoding="utf-8")
    html, mm, toc_html = md_to_body(md, toc=True)
    if toc_html:
        toc_side = (f'<aside class="doc-toc"><div class="doc-toc-head">Sommaire</div>'
                    f'{toc_html}</aside>')
    else:
        toc_side = ""
    body = (f'<div class="doc">\n{toc_side}\n'
            f'<div class="md">\n{html}</div>\n</div>'
            f'{SCROLL_SPY}')
    (OUT / "userguide.html").write_text(
        page("Guide utilisateur — BabelGrade", body, mm, active="guide"),
        encoding="utf-8")

    # --- dev docs (English source docs -> lang en)
    for slug, src in DEV_DOCS.items():
        md = src.read_text(encoding="utf-8")
        html, mm, _ = md_to_body(md)
        title = re.match(r"^#\s+(.+)$", md, re.M)
        title = f"{title.group(1).strip()} — BabelGrade" if title else f"{slug} — BabelGrade"
        (OUT / f"{slug}.html").write_text(
            page(title, f'<div class="md">\n{html}</div>', mm, lang="en", active=slug),
            encoding="utf-8")

    n_img = len(list((OUT / "assets").iterdir()))
    print(f"site/ built: {sum(1 for _ in OUT.iterdir())} top-level entries, "
          f"{n_img} images in assets/, one-pager in onepager/")


if __name__ == "__main__":
    build()
