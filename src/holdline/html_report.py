"""Self-contained HTML reports: one file, no network requests, opens anywhere (CI artifacts, email,
air-gapped machines). Two pages: a run report (optionally with the gate against a baseline) and a
judge-calibration report.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
from typing import Optional

from . import __version__
from .checks import outcome_of, tool_arguments

# -- design tokens ------------------------------------------------------------------------
# Light only. Status colours mark state and always travel with an icon and a word; text stays in
# ink. Trace kinds use the first three categorical slots (validated all-pairs for colour vision
# deficiency); aqua is under 3:1 on white, so every kind badge carries its name.
_CSS = """
:root{color-scheme:light;--bg:#f7f7f5;--surface:#fff;--surface-2:#fafaf9;--line:#e8e6e1;--line-2:#f1f0ec;
--ink:#16161a;--ink-2:#52514e;--ink-3:#8a8984;--good:#0ca30c;--bad:#d03b3b;--warn:#fab219;
--good-bg:#edf7ed;--bad-bg:#fcefee;--warn-bg:#fef6e2;--blue:#2a78d6;--blue-soft:#cde2fb;--blue-mid:#86b6ef;
--orange:#eb6834;--aqua:#1baf7a;--neutral:#e4e2dc;--radius:12px;
--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.55 Inter,ui-sans-serif,-apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
.num{font-variant-numeric:tabular-nums}
code,pre,.mono{font-family:var(--mono);font-size:12.5px}
a{color:inherit}
.top{position:sticky;top:0;z-index:5;background:rgba(247,247,245,.86);backdrop-filter:saturate(1.4) blur(10px);
-webkit-backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line)}
.top .in{max-width:1120px;margin:0 auto;padding:0 24px;height:52px;display:flex;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:8px;font-weight:600;letter-spacing:-.01em}
.crumbs{color:var(--ink-3);font-size:13px;display:flex;gap:8px;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.crumbs b{color:var(--ink-2);font-weight:500}
.top .sp{flex:1}
.ver{font-size:12px;color:var(--ink-3);border:1px solid var(--line);border-radius:99px;padding:2px 9px;background:var(--surface)}
main{max-width:1120px;margin:0 auto;padding:32px 24px 72px}
h1{font-size:28px;line-height:1.2;letter-spacing:-.02em;margin:0 0 10px;font-weight:650}
h1 .vs{color:var(--ink-3);font-weight:500}
h2{font-size:16px;letter-spacing:-.01em;margin:0;font-weight:620}
.sec{margin-top:36px}
.sec-h{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.sec-h p{margin:0;color:var(--ink-3);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;color:var(--ink-2);background:var(--surface);
border:1px solid var(--line);border-radius:99px;padding:3px 10px;white-space:nowrap}
.chip .k{color:var(--ink-3)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.verdict{margin-top:24px;display:grid;grid-template-columns:auto 1fr;gap:16px;padding:20px 22px;position:relative;overflow:hidden}
.verdict:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--good)}
.verdict.fail:before{background:var(--bad)}
.v-icon{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--good-bg);color:var(--good)}
.verdict.fail .v-icon{background:var(--bad-bg);color:var(--bad)}
.v-title{font-size:18px;font-weight:650;letter-spacing:-.01em;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.badge{font-size:11.5px;font-weight:650;letter-spacing:.04em;color:#fff;background:var(--good);border-radius:6px;padding:2px 8px}
.verdict.fail .badge{background:var(--bad)}
.v-sub{color:var(--ink-2);margin-top:2px}
.v-list{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:6px}
.v-list li{display:flex;gap:8px;align-items:flex-start}
.v-list svg{flex:none;margin-top:3px}
.i-bad{color:var(--bad)}.i-warn{color:#c98500}.i-good{color:var(--good)}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:24px}
.kpi{padding:16px 18px;min-height:118px;display:flex;flex-direction:column;gap:6px}
.kpi .lab{font-size:12.5px;color:var(--ink-2);display:flex;justify-content:space-between;gap:8px}
.kpi .lab span{color:var(--ink-3)}
.kpi .val{font-size:28px;font-weight:650;letter-spacing:-.02em;line-height:1.1}
.kpi .foot{font-size:12px;color:var(--ink-3);margin-top:auto;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.delta{display:inline-flex;align-items:center;gap:3px;color:var(--ink-2);font-weight:550}
.delta .g{font-size:10px}.delta.up .g{color:var(--good)}.delta.down .g{color:var(--bad)}
.track{position:relative;height:8px;border-radius:99px;background:var(--line-2);margin:4px 0 2px}
.track .rng{position:absolute;top:0;bottom:0;border-radius:99px;background:var(--blue-soft)}
.track .pt{position:absolute;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;
background:var(--blue);box-shadow:0 0 0 2px var(--surface)}
.track .fill{position:absolute;left:0;top:0;bottom:0;border-radius:99px;background:var(--blue)}
.track .base{position:absolute;top:-4px;bottom:-4px;width:2px;margin-left:-1px;background:var(--ink);border-radius:1px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.meters{padding:6px 18px 10px}
.meter{display:grid;grid-template-columns:minmax(110px,170px) 1fr 62px;align-items:center;gap:14px;padding:9px 0;
border-bottom:1px solid var(--line-2)}
.meter:last-child{border-bottom:0}
.meter .nm{font-size:13px;color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meter .pc{text-align:right;font-size:13px;font-weight:550}
.legend{display:flex;gap:14px;font-size:12px;color:var(--ink-3);padding:10px 18px;border-top:1px solid var(--line-2);flex-wrap:wrap}
.legend i{display:inline-block;vertical-align:-1px;margin-right:5px}
.sw{width:10px;height:10px;border-radius:3px;background:var(--blue)}
.sw-base{width:2px;height:12px;background:var(--ink);border-radius:1px}
table.t{width:100%;border-collapse:collapse;font-size:13.5px}
.t th{text-align:left;font-weight:550;color:var(--ink-3);font-size:12.5px;padding:10px 18px;border-bottom:1px solid var(--line)}
.t td{padding:10px 18px;border-bottom:1px solid var(--line-2)}
.t tr:last-child td{border-bottom:0}
.t td.r,.t th.r{text-align:right}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.seg{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:3px;gap:2px;flex-wrap:wrap}
.seg button{font:inherit;font-size:13px;border:0;background:none;color:var(--ink-2);padding:5px 11px;border-radius:7px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--ink);color:#fff}
.seg button .n{opacity:.6;margin-left:4px}
.search{flex:1;min-width:180px;position:relative}
.search input{width:100%;font:inherit;font-size:13.5px;padding:8px 12px 8px 34px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink)}
.search input:focus{outline:2px solid var(--blue-soft);border-color:var(--blue-mid)}
.search svg{position:absolute;left:11px;top:50%;margin-top:-7px;color:var(--ink-3)}
.btn{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--surface);color:var(--ink-2);border-radius:10px;padding:7px 12px;cursor:pointer}
.btn:hover,.seg button:hover:not([aria-pressed=true]){background:var(--surface-2);color:var(--ink)}
.cases{overflow:hidden}
.case{border-bottom:1px solid var(--line-2)}
.case:last-child{border-bottom:0}
.case>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:22px minmax(0,1fr) auto auto 16px;
gap:12px;align-items:center;padding:13px 18px}
.case>summary::-webkit-details-marker{display:none}
.case>summary:hover{background:var(--surface-2)}
.case[open]>summary{background:var(--surface-2);border-bottom:1px solid var(--line-2)}
.cid{font-family:var(--mono);font-size:13px;font-weight:550;color:var(--ink)}
.cmeta{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:3px}
.tag{font-size:11.5px;color:var(--ink-2);background:var(--line-2);border-radius:6px;padding:1px 7px}
.tag.must{background:#fff;border:1px solid var(--line);color:var(--ink)}
.flag{font-size:11.5px;font-weight:600;border-radius:6px;padding:1px 7px;display:inline-flex;gap:4px;align-items:center}
.flag.broke{background:var(--bad-bg);color:var(--ink)}.flag.broke:before{content:"";width:6px;height:6px;border-radius:50%;background:var(--bad)}
.flag.fixed{background:var(--good-bg);color:var(--ink)}.flag.fixed:before{content:"";width:6px;height:6px;border-radius:50%;background:var(--good)}
.dots{display:flex;gap:4px;align-items:center}
.dots i{width:9px;height:9px;border-radius:50%;background:var(--good)}
.dots i.x{background:var(--bad)}
.dots .lbl{font-size:12.5px;color:var(--ink-2);margin-left:6px;font-weight:550}
.oc{font-size:12px;color:var(--ink-2);border:1px solid var(--line);border-radius:6px;padding:1px 8px;background:var(--surface)}
.chev{color:var(--ink-3);transition:transform .15s}
.case[open] .chev{transform:rotate(90deg)}
.cbody{padding:16px 18px 20px;display:grid;gap:16px}
.io{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.box{border:1px solid var(--line-2);border-radius:10px;background:var(--surface-2);min-width:0}
.box h4{margin:0;font-size:12px;font-weight:600;color:var(--ink-3);padding:8px 12px;border-bottom:1px solid var(--line-2)}
.box pre{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;max-height:260px;overflow:auto;color:var(--ink)}
.rg{border:1px solid var(--line);border-radius:10px;overflow:hidden}
.rg-h{display:flex;align-items:center;gap:8px;padding:10px 14px;background:var(--surface-2);border-bottom:1px solid var(--line-2);font-size:13px;font-weight:550;flex-wrap:wrap}
.rg-h .ms{margin-left:auto;color:var(--ink-3);font-weight:400;font-size:12.5px}
.checks{padding:12px 14px 4px;display:grid;gap:6px}
.chk{display:flex;gap:8px;align-items:flex-start;font-size:13px}
.chk svg{flex:none;margin-top:3px}
.chk .d{color:var(--ink-2)}
.passed{display:flex;flex-wrap:wrap;gap:6px;padding:4px 14px 10px}
.passed span{font-size:12px;color:var(--ink-2);display:inline-flex;gap:4px;align-items:center}
.tl{list-style:none;margin:0;padding:8px 14px 14px 14px;position:relative}
.tl-t{font-size:12px;font-weight:600;color:var(--ink-3);padding:8px 14px 0}
.st{position:relative;padding:8px 0 8px 26px}
.st:before{content:"";position:absolute;left:7px;top:0;bottom:0;width:2px;background:var(--line)}
.st:first-child:before{top:16px}.st:last-child:before{bottom:calc(100% - 16px)}
.st .nd{position:absolute;left:2px;top:12px;width:12px;height:12px;border-radius:50%;background:var(--surface);border:3px solid var(--blue)}
.st.k-llm .nd{border-color:var(--orange)}.st.k-decision .nd{border-color:var(--aqua)}
.st.k-other .nd{border-color:var(--ink-3)}.st.err .nd{border-color:var(--bad);background:var(--bad)}
.sh{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.kind{font-size:11px;font-weight:600;letter-spacing:.02em;border-radius:5px;padding:1px 6px;color:var(--ink);background:var(--line-2)}
.k-tool .kind{box-shadow:inset 3px 0 0 var(--blue)}.k-llm .kind{box-shadow:inset 3px 0 0 var(--orange)}
.k-decision .kind{box-shadow:inset 3px 0 0 var(--aqua)}
.sh code{font-weight:600;font-size:13px}
.sh .ms{margin-left:auto;font-size:12px;color:var(--ink-3)}
.st pre{margin:6px 0 0;background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:7px 10px;
white-space:pre-wrap;word-break:break-word;max-height:180px;overflow:auto}
.st .errm{margin-top:6px;font-size:12.5px;display:flex;gap:6px;align-items:flex-start}
.st details summary{font-size:12px;color:var(--ink-3);cursor:pointer;margin-top:4px}
.empty{padding:28px;text-align:center;color:var(--ink-3)}
.cm{display:grid;grid-template-columns:auto 1fr 1fr;gap:6px;padding:16px 18px}
.cm .h{font-size:12px;color:var(--ink-3);display:flex;align-items:center;justify-content:center;text-align:center}
.cm .rh{justify-content:flex-start}
.cell{border-radius:10px;padding:14px;min-height:84px;display:flex;flex-direction:column;justify-content:space-between;border:1px solid transparent}
.cell b{font-size:24px;font-weight:650;letter-spacing:-.02em}
.cell span{font-size:12px;color:var(--ink-2)}
.cell.fp{border-color:var(--bad);box-shadow:inset 0 0 0 1px var(--bad)}
.div{padding:14px 18px 6px}
.drow{display:grid;grid-template-columns:minmax(80px,140px) 1fr 70px;gap:12px;align-items:center;padding:8px 0}
.dtrack{position:relative;height:16px}
.dtrack .ax{position:absolute;left:50%;top:-4px;bottom:-4px;width:1px;background:var(--ink-3)}
.dtrack .bar{position:absolute;top:2px;bottom:2px;border-radius:4px}
.bar.len{background:#e34948}.bar.har{background:var(--blue)}
.dscale{display:grid;grid-template-columns:minmax(80px,140px) 1fr 70px;gap:12px;font-size:11.5px;color:var(--ink-3);padding-bottom:8px}
.dscale div:nth-child(2){display:flex;justify-content:space-between;white-space:nowrap;gap:8px}
.note{display:flex;gap:8px;align-items:flex-start;padding:12px 18px;border-top:1px solid var(--line-2);font-size:13px}
.note svg{margin-top:3px}
footer{margin-top:48px;padding-top:18px;border-top:1px solid var(--line);color:var(--ink-3);font-size:12.5px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
[hidden]{display:none!important}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.two,.io{grid-template-columns:1fr}}
@media(max-width:560px){main{padding:22px 16px 56px}.top .in{padding:0 16px}h1{font-size:22px}
.kpi .val{font-size:24px}.kpi{min-height:0;padding:14px}
.case>summary{grid-template-columns:20px minmax(0,1fr) 16px;padding:12px 14px}
.case>summary .dots,.case>summary .oc{grid-column:2}
.meter{grid-template-columns:1fr 54px;gap:4px 10px}.meter .track{grid-column:1/-1;grid-row:2}
.cbody{padding:14px}.verdict{padding:16px;gap:12px}.crumbs .hide-sm{display:none}
.t th,.t td{padding:8px 10px;font-size:12.5px}.t .hs{display:none}.sec-h p{flex-basis:100%}}
@media print{.top{position:static}.toolbar{display:none}.case{break-inside:avoid}}
"""

_JS = """
(function(){
var q=document.getElementById('q');if(!q)return;
var btns=[].slice.call(document.querySelectorAll('[data-filter]'));var f='all';
var cases=[].slice.call(document.querySelectorAll('.case'));var empty=document.getElementById('empty');
function apply(){var s=q.value.trim().toLowerCase(),n=0;cases.forEach(function(el){
var ok=(f==='all'||el.getAttribute('data-'+f)==='1')&&(!s||el.getAttribute('data-search').indexOf(s)>=0);
el.hidden=!ok;if(ok)n++;});empty.hidden=n>0;}
btns.forEach(function(b){b.addEventListener('click',function(){f=b.getAttribute('data-filter');
btns.forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});apply();});});
q.addEventListener('input',apply);
var ex=document.getElementById('expand');ex.addEventListener('click',function(){
var vis=cases.filter(function(c){return !c.hidden});var open=vis.some(function(c){return !c.open});
vis.forEach(function(c){c.open=open});ex.textContent=open?'Collapse all':'Expand all';});
document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus();}});
})();
"""

# -- icons (inline SVG, currentColor) --------------------------------------------------------
_LOGO = ("<svg width='22' height='22' viewBox='0 0 22 22' aria-hidden='true'><rect width='22' height='22' rx='6' "
         "fill='#16161a'/><path d='M5 13.5h12' stroke='#fff' stroke-width='2' stroke-linecap='round'/>"
         "<circle cx='11' cy='13.5' r='3' fill='#16161a' stroke='#fff' stroke-width='2'/>"
         "<path d='M5 8h4' stroke='#fff' stroke-opacity='.45' stroke-width='2' stroke-linecap='round'/></svg>")


def _icon(name: str, size: int = 14) -> str:
    paths = {
        "check": "<path d='M3.5 8.5l3 3 6-7' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/>",
        "x": "<path d='M4.5 4.5l7 7M11.5 4.5l-7 7' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round'/>",
        "alert": "<path d='M8 2.5l6 11H2z' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linejoin='round'/><path d='M8 6.5v3' stroke='currentColor' stroke-width='1.6' stroke-linecap='round'/><circle cx='8' cy='11.6' r='.9' fill='currentColor'/>",
        "chev": "<path d='M6 3.5l4.5 4.5L6 12.5' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/>",
        "search": "<circle cx='7' cy='7' r='4.5' fill='none' stroke='currentColor' stroke-width='1.6'/><path d='M10.5 10.5L14 14' stroke='currentColor' stroke-width='1.6' stroke-linecap='round'/>",
        "flaky": "<path d='M2 9c2-4 4 2 6-2s4 2 6-2' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round'/>",
    }
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 16 16' aria-hidden='true'>{paths[name]}</svg>")


def _status_icon(state: str) -> str:
    if state == "pass":
        return f"<span class='i-good' title='passed every run'>{_icon('check', 16)}</span>"
    if state == "flaky":
        return f"<span class='i-warn' title='passed some runs'>{_icon('flaky', 16)}</span>"
    return f"<span class='i-bad' title='failed every run'>{_icon('x', 16)}</span>"


# -- helpers --------------------------------------------------------------------------------
def _e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _pct(v, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _pretty(obj, limit: int = 4000) -> str:
    if isinstance(obj, str):
        text = obj
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def _ms(v: float) -> str:
    return f"{v:.1f} ms" if v < 10 else f"{v:,.0f} ms"


def _delta(cur, base, pct: bool = True, higher_is_better: bool = True, unit: str = "") -> str:
    if cur is None or base is None:
        return ""
    d = cur - base
    if abs(d) < 1e-12:
        return "<span class='delta'>no change</span>"
    good = (d > 0) == higher_is_better
    txt = f"{abs(d) * 100:.1f} pts" if pct else f"{abs(d):.4g}{unit}"
    glyph = "&#9650;" if d > 0 else "&#9660;"
    return f"<span class='delta {'up' if good else 'down'}'><span class='g'>{glyph}</span>{_e(txt)}</span>"


def _interval(est: float, lo: float, hi: float, base: Optional[float] = None) -> str:
    left, right = _clamp(lo) * 100, _clamp(hi) * 100
    tip = f"estimate {est * 100:.1f}%, 95% interval {lo * 100:.1f}% to {hi * 100:.1f}%"
    b = f"<span class='base' style='left:{_clamp(base) * 100:.2f}%' title='baseline {base * 100:.1f}%'></span>" if base is not None else ""
    return (f"<div class='track' title='{_e(tip)}' role='img' aria-label='{_e(tip)}'>"
            f"<span class='rng' style='left:{left:.2f}%;width:{max(right - left, 0.8):.2f}%'></span>{b}"
            f"<span class='pt' style='left:{_clamp(est) * 100:.2f}%'></span></div>")


def _fill(v: float, base: Optional[float] = None, label: str = "") -> str:
    tip = f"{label} {v * 100:.1f}%".strip() + (f" (baseline {base * 100:.1f}%)" if base is not None else "")
    b = f"<span class='base' style='left:{_clamp(base) * 100:.2f}%'></span>" if base is not None else ""
    return (f"<div class='track' title='{_e(tip)}' role='img' aria-label='{_e(tip)}'>"
            f"<span class='fill' style='width:{max(_clamp(v) * 100, 0.0):.2f}%'></span>{b}</div>")


def _page(title: str, crumbs: list, body: str, script: bool = False) -> str:
    crumb_html = " ".join(
        f"<b>{_e(c)}</b>" if i == len(crumbs) - 1 else f"<span class='hide-sm'>{_e(c)} <span>/</span></span>"
        for i, c in enumerate(crumbs))
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
            f"<header class='top'><div class='in'><div class='brand'>{_LOGO}holdline</div>"
            f"<div class='crumbs'><span>/</span> {crumb_html}</div><div class='sp'></div>"
            f"<span class='ver'>v{_e(__version__)}</span></div></header>"
            f"<main>{body}<footer><span>Generated by holdline {_e(__version__)} on {now}</span>"
            "<span>Self-contained report: no network requests</span></footer></main>"
            + (f"<script>{_JS}</script>" if script else "") + "</body></html>")


# -- run report -----------------------------------------------------------------------------
def _verdict(gate_result, run, baseline) -> str:
    failed = not gate_result.passed
    title = "Gate failed" if failed else "Gate passed"
    if baseline is not None and gate_result.delta:
        d = gate_result.delta
        sub = (f"<b>{_e(run.meta.get('label'))}</b> vs baseline <b>{_e(baseline.meta.get('label'))}</b> "
               f"on {gate_result.paired_cases} paired cases. Pass rate {d['estimate'] * 100:+.1f} pts "
               f"(95% CI {d['ci'][0] * 100:+.1f} to {d['ci'][1] * 100:+.1f}), "
               f"{len(gate_result.regressions)} broke, {len(gate_result.fixes)} fixed, "
               f"McNemar p = {gate_result.mcnemar_p:.3g}.")
    else:
        sub = "Absolute rules only: no baseline was given."
    items = [f"<li><span class='i-bad'>{_icon('x')}</span><span>{_e(r)}</span></li>" for r in gate_result.reasons]
    items += [f"<li><span class='i-warn'>{_icon('alert')}</span><span>{_e(w)}</span></li>"
              for w in gate_result.warnings]
    if not items:
        items = [f"<li><span class='i-good'>{_icon('check')}</span><span>No rule was broken.</span></li>"]
    return (f"<section class='panel verdict {'fail' if failed else 'pass'}'>"
            f"<div class='v-icon'>{_icon('x' if failed else 'check', 20)}</div><div>"
            f"<div class='v-title'>{title}<span class='badge'>{gate_result.verdict}</span></div>"
            f"<div class='v-sub'>{sub}</div><ul class='v-list'>{''.join(items)}</ul></div></section>")


def _kpis(run, baseline) -> str:
    s = run.summary
    k = s["repeats"]
    bs = baseline.summary if baseline is not None else None
    vs = f"vs {_e(baseline.meta.get('label'))}" if bs else ""
    lo, hi = s["pass_rate_ci"]
    tiles = [
        ("Pass rate", "", _pct(s["pass_rate"]), _interval(s["pass_rate"], lo, hi, bs["pass_rate"] if bs else None),
         (_delta(s["pass_rate"], bs["pass_rate"]) + f" {vs}" if bs else f"95% CI {_pct(lo)} to {_pct(hi)}")),
        (f"pass^{k}", f"all {k} runs pass" if k > 1 else "single run", _pct(s.get(f"pass^{k}")),
         _fill(s.get(f"pass^{k}") or 0.0, bs.get(f"pass^{k}") if bs else None, f"pass^{k}"),
         (_delta(s.get(f"pass^{k}"), bs.get(f"pass^{k}")) + f" {vs}" if bs else "reliability across repeats")),
    ]
    if s["withheld_when_should"] is not None:
        tiles.append(("Held back when it should", "", _pct(s["withheld_when_should"]),
                      _fill(s["withheld_when_should"], bs["withheld_when_should"] if bs else None),
                      (_delta(s["withheld_when_should"], bs["withheld_when_should"]) + f" {vs}" if bs
                       else "abstained or escalated on cases it must not answer")))
    if s["answered_when_should"] is not None:
        tiles.append(("Answered when it should", "", _pct(s["answered_when_should"]),
                      _fill(s["answered_when_should"], bs["answered_when_should"] if bs else None),
                      (_delta(s["answered_when_should"], bs["answered_when_should"]) + f" {vs}" if bs
                       else "did not over-refuse answerable cases")))
    tiles.append(("Flaky cases", "", str(len(s["flaky_cases"])), "",
                  "passed some repeats, failed others" if k > 1 else "needs repeats &gt; 1 to measure"))
    tiles.append(("Must-pass failures", "", str(len(s["must_pass_failed"])), "",
                  _e(", ".join(s["must_pass_failed"])) if s["must_pass_failed"] else "none"))
    lat = s["latency_ms"]
    tiles.append(("Latency p95", f"p50 {_ms(lat['p50'])}", _ms(lat["p95"]), "",
                  (_delta(lat["p95"], bs["latency_ms"]["p95"], pct=False, higher_is_better=False, unit=" ms")
                   + " " + vs) if bs else f"mean {_ms(lat['mean'])}"))
    if s["tokens"] or s["cost"]:
        tiles.append(("Tokens / cost", "", f"{s['tokens']:,}", "", f"cost {s['cost']:.4f}"))
    else:
        tiles.append(("Runs with errors", "", str(s["errors"]), "", f"of {s['runs']} runs"))
    out = []
    for lab, aside, val, viz, foot in tiles[:8]:
        out.append(f"<div class='panel kpi'><div class='lab'>{_e(lab)}<span>{_e(aside)}</span></div>"
                   f"<div class='val num'>{_e(val)}</div>{viz}<div class='foot num'>{foot}</div></div>")
    return f"<section class='kpis'>{''.join(out)}</section>"


def _meters(title: str, desc: str, rows: list, base_rows: Optional[dict]) -> str:
    if not rows:
        return ""
    body = "".join(
        f"<div class='meter'><div class='nm' title='{_e(n)}'>{_e(n)}</div>"
        f"{_fill(v, base_rows.get(n) if base_rows else None, n)}<div class='pc num'>{_pct(v)}</div></div>"
        for n, v in rows)
    legend = ("<div class='legend'><span><i class='sw'></i>candidate</span>"
              "<span><i class='sw-base'></i>baseline</span></div>") if base_rows else ""
    return (f"<div><div class='sec-h'><h2>{_e(title)}</h2><p>{_e(desc)}</p></div>"
            f"<div class='panel'><div class='meters'>{body}</div>{legend}</div></div>")


def _metrics_table(gate_result) -> str:
    rows = []
    for m in gate_result.metrics:
        is_pct = m["metric"].startswith(("pass", "held", "answered", "check:"))
        fmt = (lambda v: _pct(v)) if is_pct else (lambda v: "n/a" if v is None else f"{v:.4g}")
        higher = not m["metric"].startswith(("p95", "cost"))
        rows.append(f"<tr><td>{_e(m['metric'])}</td><td class='r num'>{_e(fmt(m.get('baseline')))}</td>"
                    f"<td class='r num'>{_e(fmt(m.get('candidate')))}</td>"
                    f"<td class='r num'>{_delta(m.get('candidate'), m.get('baseline'), is_pct, higher) or 'n/a'}</td></tr>")
    return ("<section class='sec'><div class='sec-h'><h2>All metrics</h2><p>Table view of every number the "
            "gate compared</p></div><div class='panel' style='overflow-x:auto'><table class='t'><tr><th>Metric</th>"
            "<th class='r'>Baseline</th><th class='r'>Candidate</th><th class='r'>Change</th></tr>"
            f"{''.join(rows)}</table></div></section>")


def _timeline(trace) -> str:
    if not trace.steps:
        return "<div class='tl-t'>Trace</div><div class='empty' style='padding:14px'>No steps recorded</div>"
    items = []
    for st in trace.steps:
        args = tool_arguments(st.input) if st.kind == "tool" else st.input
        arg_html = "" if args in (None, {}, [], "") else f"<pre>{_e(_pretty(args, 1500))}</pre>"
        out_html = ("" if st.output in (None, "", {}, []) else
                    f"<details><summary>output</summary><pre>{_e(_pretty(st.output, 2000))}</pre></details>")
        err_html = (f"<div class='errm'><span class='i-bad'>{_icon('x', 13)}</span>{_e(st.error)}</div>"
                    if st.error else "")
        extra = []
        if st.tokens:
            extra.append(f"{st.tokens:,} tok")
        if st.ms:
            extra.append(f"{st.ms:.1f} ms")
        kind = st.kind if st.kind in ("tool", "llm", "decision") else "other"
        items.append(f"<li class='st k-{kind}{' err' if st.error else ''}'><span class='nd'></span>"
                     f"<div class='sh'><span class='kind'>{_e(st.kind)}</span><code>{_e(st.name)}</code>"
                     f"<span class='ms num'>{_e(' · '.join(extra))}</span></div>{arg_html}{err_html}{out_html}</li>")
    return f"<div class='tl-t'>Trace · {len(trace.steps)} steps</div><ol class='tl'>{''.join(items)}</ol>"


def _case(case, rs, flags: dict) -> str:
    n_ok = sum(r.passed for r in rs)
    state = "pass" if n_ok == len(rs) else "fail" if n_ok == 0 else "flaky"
    tags = "".join(f"<span class='tag'>{_e(t)}</span>" for t in case.tags)
    if case.must_pass:
        tags += "<span class='tag must'>must pass</span>"
    if flags.get("regressed"):
        tags += "<span class='flag broke'>broke vs baseline</span>"
    if flags.get("fixed"):
        tags += "<span class='flag fixed'>fixed vs baseline</span>"
    dots = "".join(f"<i class='{'' if r.passed else 'x'}' title='run {r.repeat + 1}: {'pass' if r.passed else 'fail'}'></i>"
                   for r in rs)
    outcomes = sorted({outcome_of(r.trace) for r in rs})
    groups: dict = {}
    for r in rs:
        key = (r.passed, tuple((c.check, c.detail) for c in r.failed_checks), tuple(r.trace.tool_names()))
        groups.setdefault(key, []).append(r)
    blocks = []
    for (passed, _, _), grp in groups.items():
        r = grp[0]
        nums = [g.repeat + 1 for g in grp]
        which = ("Run" if len(rs) == 1 else f"All {len(rs)} runs" if len(grp) == len(rs)
                 else ("Run " if len(nums) == 1 else "Runs ") + ", ".join(map(str, nums)))
        head_icon = f"<span class='i-good'>{_icon('check')}</span>" if passed else f"<span class='i-bad'>{_icon('x')}</span>"
        failed = "".join(f"<div class='chk'><span class='i-bad'>{_icon('x', 13)}</span><span><b>{_e(c.check)}</b>"
                         f"{' <span class=d>' + _e(c.detail) + '</span>' if c.detail else ''}</span></div>"
                         for c in r.failed_checks)
        ok = "".join(f"<span><span class='i-good'>{_icon('check', 12)}</span>{_e(c.check)}</span>"
                     for c in r.checks if c.passed)
        blocks.append(f"<div class='rg'><div class='rg-h'>{head_icon}{_e(which)} "
                      f"{'passed' if passed else 'failed'}<span class='ms num'>{r.trace.ms:.1f} ms · outcome "
                      f"{_e(outcome_of(r.trace))}</span></div>"
                      + (f"<div class='checks'>{failed}</div>" if failed else "")
                      + (f"<div class='passed'>{ok}</div>" if ok else "")
                      + _timeline(r.trace)
                      + f"<div style='padding:0 14px 14px'><div class='box'><h4>Final output</h4>"
                        f"<pre>{_e(_pretty(r.trace.output))}</pre></div></div></div>")
    search = " ".join([case.id] + list(case.tags) + outcomes).lower()
    attrs = (f"data-failing='{int(state != 'pass')}' data-flaky='{int(state == 'flaky')}' "
             f"data-must='{int(case.must_pass)}' data-regressed='{int(bool(flags.get('regressed')))}' "
             f"data-search='{_e(search)}'")
    return (f"<details class='case' {attrs}><summary>{_status_icon(state)}"
            f"<div style='min-width:0'><div class='cid'>{_e(case.id)}</div><div class='cmeta'>{tags}</div></div>"
            f"<div class='dots'>{dots}<span class='lbl num'>{n_ok}/{len(rs)}</span></div>"
            f"<span class='oc'>{_e(', '.join(outcomes))}</span><span class='chev'>{_icon('chev')}</span></summary>"
            f"<div class='cbody'><div class='io'><div class='box'><h4>Input</h4><pre>{_e(_pretty(case.input))}</pre></div>"
            f"<div class='box'><h4>Expected</h4><pre>{_e(_pretty(case.expected) if case.expected else 'nothing beyond running without error')}</pre></div></div>"
            f"{''.join(blocks)}</div></details>")


def run_html(run, gate_result=None, baseline=None) -> str:
    s = run.summary
    k = s["repeats"]
    m = run.meta
    bs = baseline.summary if baseline is not None else None
    title_vs = f" <span class='vs'>vs {_e(baseline.meta.get('label'))}</span>" if baseline is not None else ""
    chips = [("suite", m.get("suite")), ("cases", s["cases"]), ("repeats", k), ("runs", s["runs"]),
             ("git", m.get("git_sha") or "n/a"), ("started", (m.get("started") or "").replace("T", " ")),
             ("took", f"{m.get('seconds', 0)} s"), ("python", m.get("python"))]
    head = (f"<h1>{_e(m.get('label'))}{title_vs}</h1><div class='chips'>"
            + "".join(f"<span class='chip'><span class='k'>{_e(a)}</span>{_e(b)}</span>" for a, b in chips if b is not None)
            + "</div>")
    body = [head]
    if gate_result is not None:
        body.append(_verdict(gate_result, run, baseline))
    body.append(_kpis(run, baseline))

    checks = [(n, v) for n, v in s["checks"].items()]
    tags = [(t, v) for t, v in s["tags"].items()]
    meters = (_meters("Checks", "Share of runs where each check passed", checks, bs["checks"] if bs else None)
              + _meters("By tag", "Mean case pass rate per tag", tags, bs["tags"] if bs else None))
    if meters:
        body.append(f"<section class='sec two'>{meters}</section>")

    regressed = set(gate_result.regressions) if gate_result is not None else set()
    fixed = set(gate_result.fixes) if gate_result is not None else set()
    by_case = run.by_case()
    states = {c.id: sum(r.passed for r in by_case[c.id]) for c in run.cases}
    n_fail = sum(1 for c in run.cases if states[c.id] < len(by_case[c.id]))
    n_flaky = len(s["flaky_cases"])
    n_must = sum(1 for c in run.cases if c.must_pass)
    filters = [("all", "All", len(run.cases)), ("failing", "Failing", n_fail), ("flaky", "Flaky", n_flaky)]
    if gate_result is not None and baseline is not None:
        filters.append(("regressed", "Broke vs baseline", len(regressed)))
    if n_must:
        filters.append(("must", "Must pass", n_must))
    seg = "".join(f"<button type='button' data-filter='{key}' aria-pressed='{'true' if key == 'all' else 'false'}'>"
                  f"{_e(lab)}<span class='n num'>{n}</span></button>" for key, lab, n in filters)
    items = "".join(_case(c, by_case[c.id], {"regressed": c.id in regressed, "fixed": c.id in fixed})
                    for c in run.cases)
    body.append("<section class='sec'><div class='sec-h'><h2>Cases</h2><p>Click a case for its checks and "
                "full trace. Press / to search.</p></div>"
                f"<div class='toolbar'><div class='seg' role='group' aria-label='Filter cases'>{seg}</div>"
                f"<label class='search'>{_icon('search')}<input id='q' type='search' placeholder='Search cases, tags, outcomes' "
                "aria-label='Search cases'></label><button type='button' class='btn' id='expand'>Expand all</button></div>"
                f"<div class='panel cases'>{items}<div class='empty' id='empty' hidden>No cases match.</div></div></section>")
    if gate_result is not None and baseline is not None and gate_result.metrics:
        body.append(_metrics_table(gate_result))
    crumbs = [m.get("suite") or "suite", m.get("label") or "run"]
    return _page(f"holdline · {m.get('label')}", crumbs, "".join(body), script=True)


# -- calibration report ------------------------------------------------------------------------
def _seq_shade(n: int, total: int) -> str:
    # one-hue sequential ramp (blue), light to dark by share of items
    ramp = ["#f1f0ec", "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef"]
    share = n / total if total else 0
    return ramp[min(len(ramp) - 1, int(share * 2 * (len(ramp) - 1) + 0.999))] if n else ramp[0]


def calibration_html(rep: dict, label: str = "judge") -> str:
    o = rep["overall"]
    fit = rep["fit_to_gate"]
    th = rep.get("thresholds", {})
    title = "Judge is fit to gate releases" if fit else "Judge is not fit to gate releases"
    reasons = rep["reasons"] or ["Every calibration rule passed."]
    icon = "check" if fit else "x"
    cls = "i-good" if fit else "i-bad"
    lis = "".join(f"<li><span class='{cls}'>{_icon(icon)}</span><span>{_e(r)}</span></li>" for r in reasons)
    body = [f"<h1>{_e(label)} <span class='vs'>calibration</span></h1><div class='chips'>"
            f"<span class='chip'><span class='k'>labelled items</span>{o['n']}</span>"
            f"<span class='chip'><span class='k'>min kappa</span>{_e(th.get('min_kappa'))}</span>"
            f"<span class='chip'><span class='k'>max false-pass</span>{_e(th.get('max_false_pass'))}</span>"
            f"<span class='chip'><span class='k'>min items</span>{_e(th.get('min_n'))}</span></div>",
            f"<section class='panel verdict {'pass' if fit else 'fail'}'><div class='v-icon'>{_icon(icon, 20)}</div><div>"
            f"<div class='v-title'>{title}<span class='badge'>{'FIT' if fit else 'NOT FIT'}</span></div>"
            "<div class='v-sub'>Compared with human labels on the same items. A judge gates releases only if it "
            "agrees well beyond chance, rarely passes what a human failed, and is not lenient on some kinds of case "
            f"while harsh on others.</div><ul class='v-list'>{lis}</ul></div></section>"]

    kappa, ci = o["kappa"], o["kappa_ci"]
    kviz = _interval(_clamp(kappa or 0), _clamp(ci[0]), _clamp(ci[1])) if ci else ""
    bias = o["bias"] or 0.0
    lean = "lenient" if bias > 0 else "harsh" if bias < 0 else "neutral"
    tiles = [("Cohen's kappa", o["kappa_band"], "n/a" if kappa is None else f"{kappa:.2f}", kviz,
              f"95% CI {ci[0]:.2f} to {ci[1]:.2f}" if ci else "interval needs 2+ items"),
             ("Raw agreement", "", _pct(o["agreement"]), _fill(o["agreement"] or 0.0), "same verdict as the human"),
             ("False-pass rate", "", _pct(o["false_pass_rate"]), _fill(o["false_pass_rate"] or 0.0),
              "judge PASS where the human said FAIL"),
             ("Bias", lean, f"{bias:+.2f}", "",
              "the average hides a split by group: see Bias by group" if rep["sign_reversal"]
              else "share judged PASS minus share humans passed")]
    body.append("<section class='kpis'>" + "".join(
        f"<div class='panel kpi'><div class='lab'>{_e(a)}<span>{_e(b)}</span></div><div class='val num'>{_e(v)}</div>"
        f"{viz}<div class='foot'>{_e(f)}</div></div>" for a, b, v, viz, f in tiles) + "</section>")

    cm, n = o["confusion"], o["n"]

    def cell(count, label_, extra=""):
        return (f"<div class='cell {extra}' style='background:{_seq_shade(count, n)}'><b class='num'>{count}</b>"
                f"<span>{_e(label_)}</span></div>")

    matrix = ("<div class='panel'><div class='cm'><div></div><div class='h'>Judge PASS</div><div class='h'>Judge FAIL</div>"
              f"<div class='h rh'>Human PASS</div>{cell(cm['tp'], 'agree: pass')}{cell(cm['fn'], 'false fail')}"
              f"<div class='h rh'>Human FAIL</div>{cell(cm['fp'], 'false pass: lets bad output through', 'fp')}"
              f"{cell(cm['tn'], 'agree: fail')}</div><div class='legend'><span>Shade = share of items</span>"
              "<span>Outlined: the costly error for a release gate</span></div></div>")
    groups = rep.get("groups") or {}
    if groups:
        span = max([0.25] + [abs(g["bias"] or 0) for g in groups.values()])
        rows = []
        for g, b in groups.items():
            v = b["bias"] or 0.0
            w = abs(v) / span * 50
            pos = f"left:50%;width:{w:.2f}%" if v > 0 else f"left:{50 - w:.2f}%;width:{w:.2f}%"
            bar = f"<span class='bar {'len' if v > 0 else 'har'}' style='{pos}'></span>" if v else ""
            tip = f"{g}: bias {v:+.2f}, n={b['n']}, agreement {_pct(b['agreement'])}"
            rows.append(f"<div class='drow'><div class='nm mono' title='{_e(tip)}'>{_e(g)} "
                        f"<span style='color:var(--ink-3)'>n={b['n']}</span></div>"
                        f"<div class='dtrack' title='{_e(tip)}' role='img' aria-label='{_e(tip)}'><span class='ax'></span>{bar}</div>"
                        f"<div class='pc num' style='text-align:right'>{v:+.2f}</div></div>")
        rev = ("<div class='note'><span class='i-bad'>" + _icon("alert") +
               "</span><span><b>Sign reversal:</b> lenient on " + _e(", ".join(rep["lenient_groups"])) +
               ", harsh on " + _e(", ".join(rep["harsh_groups"])) + ". One threshold cannot fix both.</span></div>"
               if rep["sign_reversal"] else "")
        diverging = (f"<div class='panel'><div class='div'><div class='dscale'><div></div><div><span>&#9664; harsh</span><span>lenient &#9654;</span></div><div></div></div>"
                     f"{''.join(rows)}</div><div class='legend'><span><i class='sw' style='background:var(--blue)'></i>harsh</span>"
                     f"<span><i class='sw' style='background:#e34948'></i>lenient</span><span>scale &#177;{span:.2f}</span></div>{rev}</div>")
    else:
        diverging = ("<div class='panel'><div class='empty'>Add a <code>group</code> (or <code>difficulty</code>) field "
                     "to each label to see whether the judge's bias changes across kinds of case.</div></div>")
    body.append("<section class='sec two'>"
                f"<div><div class='sec-h'><h2>Confusion matrix</h2><p>{n} items</p></div>{matrix}</div>"
                f"<div><div class='sec-h'><h2>Bias by group</h2><p>Judge pass share minus human pass share. Harsh fails what humans pass; lenient passes what humans fail</p></div>{diverging}</div>"
                "</section>")

    if groups:
        trs = "".join(f"<tr><td class='mono'>{_e(g)}</td><td class='r num'>{b['n']}</td><td class='r num hs'>{_pct(b['agreement'])}</td>"
                      f"<td class='r num'>{'n/a' if b['kappa'] is None else format(b['kappa'], '.2f')}</td>"
                      f"<td class='r num'>{(b['bias'] or 0):+.2f}</td><td class='r num'>{_pct(b['false_pass_rate'])}</td></tr>"
                      for g, b in groups.items())
        body.append("<section class='sec'><div class='sec-h'><h2>Per group</h2><p>Table view</p></div>"
                    "<div class='panel' style='overflow-x:auto'><table class='t'><tr><th>Group</th><th class='r'>Items</th>"
                    "<th class='r hs'>Agreement</th><th class='r'>Kappa</th><th class='r'>Bias</th><th class='r'>False-pass</th></tr>"
                    f"{trs}</table></div></section>")
    if "threshold" in rep:
        t = rep["threshold"]
        body.append("<section class='sec'><div class='sec-h'><h2>Score threshold</h2><p>Chosen on one half of the "
                    "labels, checked on the other</p></div><div class='kpis' style='margin-top:0'>"
                    f"<div class='panel kpi'><div class='lab'>Best threshold</div><div class='val num'>{t['threshold']}</div>"
                    "<div class='foot'>judge score at or above passes</div></div>"
                    f"<div class='panel kpi'><div class='lab'>Kappa, fit half<span>n={t['n_fit']}</span></div>"
                    f"<div class='val num'>{t['kappa_fit_half']:.2f}</div><div class='foot'>optimistic by construction</div></div>"
                    f"<div class='panel kpi'><div class='lab'>Kappa, held-out half<span>n={t['n_held_out']}</span></div>"
                    f"<div class='val num'>{'n/a' if t['kappa_held_out_half'] is None else format(t['kappa_held_out_half'], '.2f')}</div>"
                    "<div class='foot'>the number to trust</div></div></div></section>")
    return _page(f"holdline · {label} calibration", ["calibration", label], "".join(body))
