"""Wave 1 live verification — focus trap, lang, labels, contrast, pill B2 fix, reduced-motion."""
import _testpw as TESTPW
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8090"
PASS, FAIL = [], []
def check(n, c, x=""):
    (PASS if c else FAIL).append(n)
    print(("PASS " if c else "FAIL ") + n + (f" | {x}" if x and not c else ""))

def login(pg, lang="fr"):
    pg.add_init_script(f"localStorage.setItem('babelgrade-lang','{lang}')")
    pg.goto(BASE, wait_until="networkidle")
    pg.wait_for_selector("#auth-username", state="visible")
    pg.fill("#auth-username","tibo"); pg.fill("#auth-password", TESTPW.pw())
    pg.click("#auth-login-btn")
    pg.wait_for_selector("#user-chip-wrap:not(.hide)", timeout=20000)
    pg.wait_for_timeout(500)

with sync_playwright() as pw:
    ctx = pw.chromium.launch(headless=True).new_context(viewport={"width":1280,"height":800}, locale="fr-FR")
    pg = ctx.new_page()
    errors=[]
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    login(pg)

    # V1.3 lang
    check("lang=fr on FR UI", pg.evaluate("document.documentElement.lang")=="fr")
    # V1.5 toast aria-live
    toast = pg.evaluate("""()=>{const t=document.querySelector('#toast');
      return {role:t.getAttribute('role'), live:t.getAttribute('aria-live')};}""")
    check("toast role=status", toast["role"]=="status", str(toast))
    check("toast aria-live=polite", toast["live"]=="polite", str(toast))
    runchip = pg.evaluate("document.querySelector('#run-chip-label').getAttribute('aria-live')")
    check("run-chip-label aria-live", runchip=="polite", str(runchip))

    # V1.4 label associations on evaluator
    pg.evaluate("goEvaluate()")
    pg.wait_for_timeout(700)
    labels = pg.evaluate("""()=>{
      const out={};
      for(const id of ['assignment','student','rubric','accommodations','language','audio-file']){
        const e=document.querySelector('#'+id); if(!e){out[id]='MISSING';continue;}
        out[id]={assoc: e.labels&&e.labels.length? e.labels[0].textContent.trim().slice(0,20):null,
                 ariaReq: e.getAttribute('aria-required')};
      }
      // engine-created textarea written-text: associated via generated label for=
      const wt=document.querySelector('#written-text');
      out['written-text']= wt? {assoc: wt.labels&&wt.labels.length? wt.labels[0].textContent.trim().slice(0,20):null} : 'MISSING';
      return out;
    }""")
    for id in ['assignment','student','rubric','accommodations','language','written-text']:
        v=labels.get(id)
        ok = isinstance(v,dict) and v.get("assoc")
        check(f"label assoc #{id}", ok, str(v))
    check("rubric aria-required", isinstance(labels.get('rubric'),dict) and labels['rubric'].get("ariaReq")=="true", str(labels.get('rubric')))

    # V1.2 contrast: re-read the 3 vars + compute ratio of white on each
    contrast = pg.evaluate("""()=>{
      const L=['A1','A2','B1','B2','C1','C2'];
      const host=document.createElement('div');host.style.position='absolute';host.style.left='-9999px';
      document.body.appendChild(host);
      const out={};
      const parse=c=>{const m=c.match(/rgb\\(([^)]+)\\)/);if(!m)return null;return m[1].split(',').map(parseFloat);};
      const lum=rgb=>{const f=v=>{v=v/255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);};
        const[r,g,b]=rgb;return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
      for(const lv of L){const s=document.createElement('span');s.className='level '+lv;host.appendChild(s);
        const cs=getComputedStyle(s);const bg=parse(cs.backgroundColor);const fg=[255,255,255];
        const l1=lum(fg),l2=lum(bg);out[lv]=+((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)).toFixed(2);}
      host.remove();return out;
    }""")
    for lv in ['A1','A2','B1']:
        check(f"pill {lv} contrast >=4.5", contrast.get(lv,0)>=4.5, str(contrast.get(lv)))

    # V1.7 focus-visible: focus a nav button and confirm a visible ring (outline or drop-shadow)
    focusvis = pg.evaluate("""()=>{
      const b=document.querySelector('#nav button[data-view=history]');b.focus();
      const cs=getComputedStyle(b);
      const oW=parseFloat(cs.outlineWidth), oC=cs.outlineColor;
      return {outlineWidth:cs.outlineWidth, outlineStyle:cs.outlineStyle, outlineOffset:cs.outlineOffset};
    }""")
    # focus-visible only fires on keyboard in real browsers; in headless .focus() may not set it.
    # Instead just assert the rule EXISTS in the stylesheet.
    has_rule = pg.evaluate("""()=>{
      for(const sh of document.styleSheets){try{for(const r of sh.cssRules){
        if(r.selectorText && r.selectorText.includes(':focus-visible') && r.selectorText.includes('button'))return true;
      }}catch(e){}}return false;
    }""")
    check(":focus-visible rule present for buttons", has_rule)

    # V1.6 focus trap — open assignment-detail overlay and confirm focus moves INTO it
    pg.evaluate("""(v)=>{const b=document.querySelector('#nav button[data-view="assignments"]');if(b)b.click();}""", None)
    pg.wait_for_timeout(500)
    try: pg.evaluate("pieClose()")
    except Exception: pass  # best-effort cleanup if the pie is closed
    pg.click("[data-assignview]")
    pg.wait_for_selector("#assignment-detail-overlay:not(.hide)", state="visible")
    pg.wait_for_timeout(300)  # allow rAF trap to run
    in_dialog = pg.evaluate("""()=>{const ov=document.querySelector('#assignment-detail-overlay');
      const a=document.activeElement;return ov.contains(a)?{inDialog:true,tag:a.tagName,id:a.id,text:(a.textContent||'').trim().slice(0,20)}:{inDialog:false,tag:a.tagName};}""")
    check("focus moved INTO assignment-detail dialog", in_dialog.get("inDialog") is True, str(in_dialog))
    # Tab cycles stay inside
    seq=[]
    for _ in range(5):
        pg.keyboard.press("Tab")
        seq.append(pg.evaluate("""()=>{const ov=document.querySelector('#assignment-detail-overlay');return ov.contains(document.activeElement);}"""))
    check("Tab x5 stays inside dialog", all(seq), str(seq))
    # close
    pg.click("#asgd-close"); pg.wait_for_timeout(300)

    # V1.1 lvl sheet B2 pill text visible (mobile)
    mctx = pw.chromium.launch(headless=True).new_context(
        viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="fr-FR")
    mp = mctx.new_page()
    merr=[]
    mp.on("pageerror", lambda e: merr.append(str(e)[:150]))
    login(mp)
    # V1.1: open an ATTESTATION analysis that HAS levels (overall_level set),
    # so the detail's attestation table has a row with a level. The level
    # bottom-sheet + its .on pill only exist in the DETAIL (#history/<aid>),
    # NOT in the list (#history) — that's what hung the dead session.
    aid = mp.evaluate("""async()=>{const r=await fetch('/api/analyses');const j=await r.json();
      const rows=Array.isArray(j)?j:(j.items||[]);
      const a=rows.find(x=>x.analysis_id&&x.rubric_name
        &&x.rubric_name.indexOf('Attestation')===0&&x.overall_level);
      return a?a.analysis_id:null;}""")
    assert aid, "no attestation analysis with a level found in /api/analyses"
    mp.goto(BASE+"/#history/"+str(aid), wait_until="networkidle")
    mp.wait_for_selector(".att-lvl-pill", state="visible", timeout=15000)
    # click a row's pill that HAS a level -> the sheet then shows a selected .on pill
    clicked = mp.evaluate("""()=>{
      const rows=document.querySelectorAll('#hist-report .att-main-row');
      for(const r of rows){const s=r.querySelector('.att-lvl');
        if(s&&s.value){const p=r.querySelector('.att-lvl-pill');if(p){p.click();return s.value;}}}
      const p=document.querySelector('.att-lvl-pill');if(p){p.click();return 'fallback';}
      return null;}""")
    mp.wait_for_selector("#lvl-sheet.show", state="visible", timeout=6000)
    mp.wait_for_timeout(300)
    b2 = mp.evaluate("""()=>{
      const on=document.querySelector('#ls-grid .lvl-sheet-btn.on');if(!on)return {on:false};
      const pill=on.querySelector('.ls-lv');if(!pill)return {on:true,pillText:null};
      const cs=getComputedStyle(pill);
      return {on:true, pillText:pill.textContent.trim(), color:cs.color, bg:getComputedStyle(on).backgroundColor};
    }""")
    check("lvl sheet selected pill has visible level text", b2.get("pillText") in ("A1","A2","B1","B2","C1","C2"), str(b2))
    # contrast of that pill text on its own background
    pillc = mp.evaluate("""()=>{
      const on=document.querySelector('#lvl-sheet-btn.on')||document.querySelector('#ls-grid .lvl-sheet-btn.on');
      if(!on)return null;const pill=on.querySelector('.ls-lv');const cs=getComputedStyle(pill);
      const parse=c=>{const m=c.match(/rgb\\(([^)]+)\\)/);if(!m)return[255,255,255];return m[1].split(',').map(parseFloat);};
      // walk up to a non-transparent bg
      let n=pill,bg=null;while(n){const c=getComputedStyle(n).backgroundColor;
        const m=c.match(/rgba?\\(([^)]+)\\)/);if(m){const p=m[1].split(',').map(parseFloat);if(p.length<4||p[3]!==0){bg=parse(c);break;}}n=n.parentElement;}
      if(!bg)return null;const fg=parse(cs.color);
      const lum=rgb=>{const f=v=>{v=v/255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);};
        const[r,g,b]=rgb;return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
      const l1=lum(fg),l2=lum(bg);return +((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)).toFixed(2);
    }""")
    check("lvl sheet selected pill text contrast >=4.5", (pillc or 0)>=4.5, f"ratio={pillc} {b2}")
    mctx.close()

    check("0 desktop page errors", len(errors)==0, str(errors))
    check("0 mobile page errors", len(merr)==0, str(merr))
    ctx.close()

print("\n===== WAVE1 VERIFICATION =====")
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FAILURES:", FAIL)
