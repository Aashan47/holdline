"""Self-contained HTML reports, built as a small single-page app: one file, no network requests,
opens anywhere (CI artifacts, email, air-gapped machines).

Two apps share one shell (sidebar, views, hash routing):

- the run report: Overview, Cases (master-detail, one link per case), Compare, Run info;
- the judge-calibration report: Overview, Groups, Disagreements, Settings.

Python renders every view; a few lines of JavaScript route between them, filter, and move the
selection. Without JavaScript every view is shown in order, so nothing is lost.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
from typing import Optional
from urllib.parse import quote

from . import __version__
from .checks import outcome_of, tool_arguments

# -- design tokens ----------------------------------------------------------------------------
# Light only. Status colours mark state and always travel with an icon and a word; text stays in
# ink. Trace kinds use the first three categorical slots (validated all-pairs for colour vision
# deficiency); aqua is under 3:1 on white, so every kind badge carries its name.
_CSS = """
:root{color-scheme:light;--bg:#f5f6f8;--surface:#fff;--surface-2:#f9fafb;--line:#e3e5ea;--line-2:#eef0f3;
--ink:#14161b;--ink-2:#4b5160;--ink-3:#8a90a0;--accent:#2a78d6;--accent-soft:#eaf1fc;--accent-mid:#86b6ef;
--good:#0ca30c;--good-bg:#e9f6e9;--bad:#d03b3b;--bad-bg:#fbeaea;--warn:#fab219;--warn-bg:#fef5de;
--orange:#eb6834;--aqua:#1baf7a;--side:248px;
--sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI Variable","Segoe UI",system-ui,Roboto,sans-serif;
--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.5 var(--sans);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.num{font-variant-numeric:tabular-nums}
code,pre,.mono{font-family:var(--mono);font-size:12.5px}
a{color:inherit;text-decoration:none}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
.app{display:grid;grid-template-columns:var(--side) minmax(0,1fr);min-height:100%;background:linear-gradient(90deg,var(--surface) calc(var(--side) - 1px),var(--line) calc(var(--side) - 1px),var(--line) var(--side),transparent var(--side))}

/* sidebar */
.side{position:sticky;top:0;height:100vh;background:var(--surface);border-right:1px solid var(--line);
display:flex;flex-direction:column;padding:18px 14px 16px;gap:18px;overflow:auto}
.brand{display:flex;align-items:center;gap:9px;font-weight:650;font-size:15px;letter-spacing:-.01em;padding:0 6px}
.runbox{padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--surface-2)}
.runbox .k{font-size:12px;color:var(--ink-3)}
.runbox .n{font-weight:600;font-size:14px;line-height:1.3;margin-top:2px;word-break:break-word}
.runbox .vs{font-size:12.5px;color:var(--ink-2);margin-top:2px;word-break:break-word}
.vpill{display:inline-flex;align-items:center;gap:6px;margin-top:10px;font-size:12.5px;font-weight:600;
padding:3px 10px 3px 8px;border-radius:99px;background:var(--good-bg);color:var(--ink)}
.vpill.fail{background:var(--bad-bg)}
.vpill i{width:8px;height:8px;border-radius:50%;background:var(--good)}.vpill.fail i{background:var(--bad)}
.nav{display:flex;flex-direction:column;gap:2px}
.nav a{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:8px;color:var(--ink-2);font-weight:500}
.nav a svg{color:var(--ink-3)}
.nav a:hover{background:var(--surface-2);color:var(--ink)}
.nav a.on{background:var(--accent-soft);color:var(--ink)}
.nav a.on svg{color:var(--accent)}
.nav .c{margin-left:auto;font-size:12px;color:var(--ink-3);font-weight:500}
.side .foot{margin-top:auto;font-size:12px;color:var(--ink-3);padding:0 6px;line-height:1.6}

/* main */
.main{min-width:0;padding:28px 36px 64px}
.view{max-width:1180px;margin:0 auto}
.js .view:not(.on){display:none}
.nojs .view+.view{margin-top:56px;padding-top:28px;border-top:1px solid var(--line)}
.vh{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.vh h1{font-size:22px;line-height:1.25;letter-spacing:-.015em;margin:0;font-weight:650}
.vh p{margin:4px 0 0;color:var(--ink-2);max-width:70ch}
h2{font-size:15px;margin:0;font-weight:620;letter-spacing:-.005em}
.sh{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 0 10px;flex-wrap:wrap}
.sh p{margin:0;color:var(--ink-3);font-size:12.5px}
.blk{margin-top:28px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:14px}

/* verdict */
.verdict{display:grid;grid-template-columns:auto minmax(0,1fr);gap:16px;padding:20px 22px;position:relative;overflow:hidden}
.verdict:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--good)}
.verdict.fail:before{background:var(--bad)}
.vi{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--good-bg);color:var(--good)}
.verdict.fail .vi{background:var(--bad-bg);color:var(--bad)}
.vt{font-size:18px;font-weight:650;letter-spacing:-.01em}
.vs2{color:var(--ink-2);margin-top:3px;max-width:90ch}
.vl{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:6px}
.vl li{display:flex;gap:8px;align-items:flex-start}
.vl svg{flex:none;margin-top:3px}
.i-bad{color:var(--bad)}.i-warn{color:#c98500}.i-good{color:var(--good)}

/* stat bar */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));margin-top:16px;overflow:hidden}
.stat{padding:16px 18px;border-right:1px solid var(--line-2);border-bottom:1px solid var(--line-2);margin:0 -1px -1px 0;
display:flex;flex-direction:column;gap:5px;min-height:116px}
.stat .l{font-size:12.5px;color:var(--ink-2)}
.stat .v{font-size:26px;font-weight:650;letter-spacing:-.02em;line-height:1.1}
.stat .f{font-size:12px;color:var(--ink-3);margin-top:auto}
.delta{display:inline-flex;align-items:center;gap:3px;color:var(--ink-2);font-weight:550}
.delta .g{font-size:10px}.delta.up .g{color:var(--good)}.delta.down .g{color:var(--bad)}
.track{position:relative;height:8px;border-radius:99px;background:var(--line-2);margin:4px 0 2px}
.track .rng{position:absolute;top:0;bottom:0;border-radius:99px;background:#cde2fb}
.track .pt{position:absolute;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 2px var(--surface)}
.track .fill{position:absolute;left:0;top:0;bottom:0;border-radius:99px;background:var(--accent)}
.track .base{position:absolute;top:-4px;bottom:-4px;width:2px;margin-left:-1px;background:var(--ink);border-radius:1px}

/* case map */
.map{padding:16px 18px 12px}
.cells{display:grid;grid-template-columns:repeat(auto-fill,18px);gap:6px}
.cell{width:18px;height:18px;border-radius:4px;background:var(--good);display:block;position:relative}
.cell.fail{background:var(--bad)}.cell.flaky{background:var(--warn)}
.cell.broke{box-shadow:0 0 0 2px var(--surface),0 0 0 3.5px var(--ink)}
.cell.fixed:after{content:"";position:absolute;inset:6px;border-radius:50%;background:var(--surface)}
.cell:hover{transform:scale(1.18)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--ink-2);padding:10px 18px;border-top:1px solid var(--line-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:10px;height:10px;border-radius:3px;background:var(--accent);display:inline-block}
.sw.good{background:var(--good)}.sw.bad{background:var(--bad)}.sw.warn{background:var(--warn)}
.sw.ring{background:var(--surface);box-shadow:0 0 0 1.5px var(--ink)}
.sw.base{width:2px;height:12px;background:var(--ink);border-radius:1px}

/* meters */
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.meters{padding:6px 18px 8px}
.meter{display:grid;grid-template-columns:minmax(100px,170px) 1fr 58px;align-items:center;gap:14px;padding:9px 0;border-bottom:1px solid var(--line-2)}
.meter:last-child{border-bottom:0}
.meter .nm{font-size:13px;color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meter .pc{text-align:right;font-size:13px;font-weight:550}

/* attention list */
.att a{display:grid;grid-template-columns:18px minmax(160px,300px) minmax(0,1fr) auto auto;gap:12px;align-items:center;
padding:11px 18px;border-bottom:1px solid var(--line-2)}
.att a:last-child{border-bottom:0}
.att a:hover{background:var(--surface-2)}
.att .id{font-family:var(--mono);font-size:12.5px;font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.att .why{color:var(--ink-2);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.att .runs{font-size:12.5px;color:var(--ink-2);text-align:right}
.att .more{display:block;padding:11px 18px;color:var(--accent);font-weight:550}

/* tables */
table.t{width:100%;border-collapse:collapse;font-size:13.5px}
.t th{text-align:left;font-weight:550;color:var(--ink-3);font-size:12.5px;padding:10px 18px;border-bottom:1px solid var(--line)}
.t td{padding:10px 18px;border-bottom:1px solid var(--line-2);vertical-align:top}
.t tr:last-child td{border-bottom:0}
.t .r{text-align:right}
.t a.lnk{font-family:var(--mono);font-size:12.5px;font-weight:550}
.t a.lnk:hover{color:var(--accent)}
.t .why{color:var(--ink-2)}
dl.kv{display:grid;grid-template-columns:minmax(120px,200px) 1fr;margin:0;padding:6px 18px}
dl.kv dt{color:var(--ink-3);padding:10px 0;border-bottom:1px solid var(--line-2)}
dl.kv dd{margin:0;padding:10px 0;border-bottom:1px solid var(--line-2);word-break:break-word}
dl.kv dt:nth-last-of-type(1),dl.kv dd:last-of-type{border-bottom:0}

/* cases: toolbar, list, detail */
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.seg{display:inline-flex;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:3px;gap:2px;flex-wrap:wrap}
.seg button{border:0;background:none;color:var(--ink-2);padding:5px 11px;border-radius:7px;cursor:pointer;font-size:13px}
.seg button[aria-pressed=true]{background:var(--ink);color:#fff}
.seg button .n{opacity:.6;margin-left:5px}
.seg button:hover:not([aria-pressed=true]){background:var(--surface-2);color:var(--ink)}
.search{flex:1;min-width:200px;position:relative}
.search input{width:100%;font:inherit;font-size:13.5px;padding:8px 12px 8px 34px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink)}
.search input:focus{outline:2px solid #cde2fb;border-color:var(--accent-mid)}
.search svg{position:absolute;left:11px;top:50%;margin-top:-7px;color:var(--ink-3)}
.kbd{font-family:var(--mono);font-size:11px;color:var(--ink-3);border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:0 5px;background:var(--surface)}
.hint{font-size:12px;color:var(--ink-3);display:flex;gap:6px;align-items:center}
.split{display:grid;grid-template-columns:minmax(260px,360px) minmax(0,1fr);gap:16px;align-items:start}
.list{overflow:hidden;position:sticky;top:16px;max-height:calc(100vh - 32px);display:flex;flex-direction:column}
.list .rows{overflow:auto}
.lh{padding:10px 14px;border-bottom:1px solid var(--line-2);font-size:12.5px;color:var(--ink-3);display:flex;justify-content:space-between}
.row{display:grid;grid-template-columns:18px minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line-2);position:relative}
.row:last-child{border-bottom:0}
.row:hover{background:var(--surface-2)}
.row.on{background:var(--accent-soft)}
.row.on:before{content:"";position:absolute;left:0;top:6px;bottom:6px;width:3px;border-radius:0 3px 3px 0;background:var(--accent)}
.row .id{font-family:var(--mono);font-size:12.5px;font-weight:550;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .sub{font-size:12px;color:var(--ink-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dots{display:flex;gap:3px;align-items:center}
.dots i{width:8px;height:8px;border-radius:50%;background:var(--good)}
.dots i.x{background:var(--bad)}
.empty{padding:36px 20px;text-align:center;color:var(--ink-2)}
.empty b{display:block;color:var(--ink);font-size:14px;margin-bottom:4px}
.empty button{margin-top:12px}
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink-2);border-radius:9px;padding:6px 12px;cursor:pointer;font-size:13px}
.btn:hover{background:var(--surface-2);color:var(--ink)}
.detail{padding:20px 22px 22px;min-width:0}
.js .detail:not(.on){display:none}
.nojs .detail+.detail{border-top:1px solid var(--line)}
.dh{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.dh h2{font-family:var(--mono);font-size:15px;font-weight:600;word-break:break-all}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.tag{font-size:11.5px;color:var(--ink-2);background:var(--line-2);border-radius:6px;padding:1px 7px}
.tag.must{background:var(--surface);border:1px solid var(--line);color:var(--ink)}
.flag{font-size:11.5px;font-weight:600;border-radius:6px;padding:1px 7px;display:inline-flex;gap:5px;align-items:center;color:var(--ink)}
.flag:before{content:"";width:6px;height:6px;border-radius:50%}
.flag.broke{background:var(--bad-bg)}.flag.broke:before{background:var(--bad)}
.flag.fixed{background:var(--good-bg)}.flag.fixed:before{background:var(--good)}
.score{text-align:right}
.score .big{font-size:20px;font-weight:650}
.score .s{font-size:12px;color:var(--ink-3)}
.back{display:none}
.io{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
.box{border:1px solid var(--line-2);border-radius:10px;background:var(--surface-2);min-width:0}
.box h3{margin:0;font-size:12px;font-weight:600;color:var(--ink-3);padding:8px 12px;border-bottom:1px solid var(--line-2)}
.box pre{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;max-height:240px;overflow:auto}
.rg{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:14px}
.rgh{display:flex;align-items:center;gap:8px;padding:10px 14px;background:var(--surface-2);border-bottom:1px solid var(--line-2);font-weight:550;flex-wrap:wrap}
.rgh .m{margin-left:auto;color:var(--ink-3);font-weight:400;font-size:12.5px}
.checks{padding:12px 14px 2px;display:grid;gap:6px}
.chk{display:flex;gap:8px;align-items:flex-start;font-size:13px}
.chk svg{flex:none;margin-top:3px}
.chk .d{color:var(--ink-2)}
.passed{display:flex;flex-wrap:wrap;gap:4px 12px;padding:6px 14px 10px}
.passed span{font-size:12px;color:var(--ink-2);display:inline-flex;gap:4px;align-items:center}
.tlh{font-size:12px;font-weight:600;color:var(--ink-3);padding:8px 14px 0}
.tl{list-style:none;margin:0;padding:6px 14px 12px}
.st{position:relative;padding:8px 0 8px 26px}
.st:before{content:"";position:absolute;left:7px;top:0;bottom:0;width:2px;background:var(--line)}
.st:first-child:before{top:16px}.st:last-child:before{bottom:calc(100% - 16px)}
.st:only-child:before{display:none}
.st .nd{position:absolute;left:2px;top:12px;width:12px;height:12px;border-radius:50%;background:var(--surface);border:3px solid var(--accent)}
.st.k-llm .nd{border-color:var(--orange)}.st.k-decision .nd{border-color:var(--aqua)}
.st.k-other .nd{border-color:var(--ink-3)}.st.err .nd{border-color:var(--bad);background:var(--bad)}
.sr{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.kind{font-size:11px;font-weight:600;border-radius:5px;padding:1px 6px 1px 8px;color:var(--ink);background:var(--line-2)}
.k-tool .kind{box-shadow:inset 3px 0 0 var(--accent)}.k-llm .kind{box-shadow:inset 3px 0 0 var(--orange)}
.k-decision .kind{box-shadow:inset 3px 0 0 var(--aqua)}
.sr code{font-weight:600;font-size:13px}
.sr .m{margin-left:auto;font-size:12px;color:var(--ink-3)}
.st pre{margin:6px 0 0;background:var(--surface-2);border:1px solid var(--line-2);border-radius:8px;padding:7px 10px;white-space:pre-wrap;word-break:break-word;max-height:180px;overflow:auto}
.st .errm{margin-top:6px;font-size:12.5px;display:flex;gap:6px;align-items:flex-start}
.st details summary{font-size:12px;color:var(--ink-3);cursor:pointer;margin-top:4px}
.outbox{padding:0 14px 14px}

/* calibration */
.cm{display:grid;grid-template-columns:auto 1fr 1fr;gap:6px;padding:16px 18px}
.cm .h{font-size:12px;color:var(--ink-3);display:flex;align-items:center;justify-content:center;text-align:center}
.cm .rh{justify-content:flex-start;padding-right:6px}
.cmc{border-radius:10px;padding:14px;min-height:84px;display:flex;flex-direction:column;justify-content:space-between;border:1px solid transparent}
.cmc b{font-size:24px;font-weight:650}
.cmc span{font-size:12px;color:var(--ink-2)}
.cmc.fp{border-color:var(--bad);box-shadow:inset 0 0 0 1px var(--bad)}
.div{padding:14px 18px 6px}
.drow,.dscale{display:grid;grid-template-columns:minmax(80px,150px) 1fr 64px;gap:12px;align-items:center}
.drow{padding:8px 0}
.dscale{font-size:11.5px;color:var(--ink-3);padding-bottom:8px}
.dscale div:nth-child(2){display:flex;justify-content:space-between;white-space:nowrap;gap:8px}
.dtrack{position:relative;height:16px}
.dtrack .ax{position:absolute;left:50%;top:-4px;bottom:-4px;width:1px;background:var(--ink-3)}
.dtrack .bar{position:absolute;top:2px;bottom:2px;border-radius:4px}
.bar.len{background:#e34948}.bar.har{background:var(--accent)}
.note{display:flex;gap:8px;align-items:flex-start;padding:12px 18px;border-top:1px solid var(--line-2);font-size:13px}
.note svg{margin-top:3px}
.verdict-chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600}
.verdict-chip:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--good)}
.verdict-chip.f:before{background:var(--bad)}

/* responsive */
@media(max-width:1100px){.two{grid-template-columns:1fr}}
@media(max-width:860px){
.app{grid-template-columns:1fr;background:none}
.side{position:sticky;top:0;z-index:10;height:auto;flex-direction:row;flex-wrap:wrap;align-items:center;gap:8px 12px;
padding:10px 16px;border-right:0;border-bottom:1px solid var(--line)}
.runbox,.side .foot{display:none}
.nav{flex-direction:row;overflow-x:auto;width:100%;gap:4px;scrollbar-width:none}
.nav a{white-space:nowrap;padding:6px 10px}
.side .vpill{margin:0 0 0 auto}
.main{padding:20px 16px 56px}
.split{grid-template-columns:1fr}
.list{position:static;max-height:none}
.js .split.has-sel .list{display:none}
.js .split:not(.has-sel) .detailwrap{display:none}
.back{display:inline-flex;margin-bottom:12px}
.io{grid-template-columns:1fr}
.hint{display:none}
.score{text-align:left;display:flex;gap:6px;align-items:baseline}.score .big{font-size:15px}.dh{gap:6px}
.att a{grid-template-columns:18px minmax(0,1fr) auto;grid-template-areas:'i id r' '. why why';gap:2px 10px}
.att a>:nth-child(1){grid-area:i}.att .id{grid-area:id}.att .why{grid-area:why;white-space:normal}.att .runs{grid-area:r}.att .fl{display:none}}
@media(max-width:560px){.vh h1{font-size:19px}.stat{min-height:0;padding:14px}.stat .v{font-size:22px}
.meter{grid-template-columns:1fr 54px;gap:4px 10px}.meter .track{grid-column:1/-1;grid-row:2}
.detail{padding:16px}.verdict{padding:16px;gap:12px}.t th,.t td{padding:8px 10px;font-size:12.5px}.t .hs{display:none}
dl.kv{grid-template-columns:1fr}dl.kv dt{border-bottom:0;padding-bottom:0}}
@media print{.side{display:none}.app{display:block}.js .view{display:block!important}.toolbar{display:none}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

_JS = r"""
(function(){
document.documentElement.className='js';
var views=[].slice.call(document.querySelectorAll('.view'));
var navs=[].slice.call(document.querySelectorAll('.nav a'));
var rows=[].slice.call(document.querySelectorAll('.row'));
var details={};[].slice.call(document.querySelectorAll('.detail')).forEach(function(d){details[d.getAttribute('data-id')]=d;});
var split=document.querySelector('.split');var q=document.getElementById('q');var filt='all';
var empty=document.getElementById('empty');var shown=document.getElementById('shown');
var wide=function(){return window.matchMedia('(min-width:861px)').matches;};
function show(v){views.forEach(function(x){x.classList.toggle('on',x.id==='v-'+v);});
navs.forEach(function(a){a.classList.toggle('on',a.getAttribute('data-v')===v);});}
function visible(){return rows.filter(function(r){return !r.hidden;});}
function select(id,scroll){var hit=null;rows.forEach(function(r){var on=r.getAttribute('data-id')===id;r.classList.toggle('on',on);if(on)hit=r;});
Object.keys(details).forEach(function(k){details[k].classList.toggle('on',k===id);});
if(split)split.classList.toggle('has-sel',!!(id&&details[id]));
if(hit&&scroll)hit.scrollIntoView({block:'nearest'});}
function route(){var h=decodeURIComponent(location.hash.replace(/^#\/?/,''));var parts=h.split('/');var v=parts.shift()||'overview';
if(!document.getElementById('v-'+v))v='overview';show(v);
if(v==='cases'){var id=parts.join('/');if(!id&&wide()){var f=visible().filter(function(r){return r.getAttribute('data-state')!=='pass';})[0]||visible()[0];
if(f){history.replaceState(null,'','#/cases/'+encodeURIComponent(f.getAttribute('data-id')));id=f.getAttribute('data-id');}}
select(id,true);}if(v!=='cases'||!parts.length)window.scrollTo(0,0);}
function apply(){if(!q)return;var s=q.value.trim().toLowerCase(),n=0;rows.forEach(function(r){
var ok=(filt==='all'||r.getAttribute('data-'+filt)==='1')&&(!s||r.getAttribute('data-search').indexOf(s)>=0);r.hidden=!ok;if(ok)n++;});
if(empty)empty.hidden=n>0;if(shown)shown.textContent=n;}
[].slice.call(document.querySelectorAll('[data-filter]')).forEach(function(b,_,all){b.addEventListener('click',function(){
filt=b.getAttribute('data-filter');all.forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});apply();});});
var clr=document.getElementById('clear');if(clr)clr.addEventListener('click',function(){q.value='';var a=document.querySelector('[data-filter=all]');if(a)a.click();apply();});
if(q)q.addEventListener('input',apply);
document.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey)return;var t=e.target.tagName;
if(e.key==='/'&&t!=='INPUT'&&q){e.preventDefault();location.hash='#/cases';q.focus();return;}
if(t==='INPUT'){if(e.key==='Escape')q.blur();return;}
if((e.key==='j'||e.key==='k')&&document.getElementById('v-cases').classList.contains('on')){var vis=visible();if(!vis.length)return;
var i=vis.findIndex(function(r){return r.classList.contains('on');});i=e.key==='j'?Math.min(vis.length-1,i+1):Math.max(0,i-1);
location.hash='#/cases/'+encodeURIComponent(vis[i].getAttribute('data-id'));}
if(e.key==='Escape'&&!wide()&&split&&split.classList.contains('has-sel')){location.hash='#/cases';}});
window.addEventListener('hashchange',route);route();
})();
"""

# -- icons (inline SVG, currentColor) --------------------------------------------------------------
_LOGO = ("<svg width='22' height='22' viewBox='0 0 22 22' aria-hidden='true'><rect width='22' height='22' rx='6' "
         "fill='#14161b'/><path d='M5 13.5h12' stroke='#fff' stroke-width='2' stroke-linecap='round'/>"
         "<circle cx='11' cy='13.5' r='3' fill='#14161b' stroke='#fff' stroke-width='2'/>"
         "<path d='M5 8h4' stroke='#fff' stroke-opacity='.45' stroke-width='2' stroke-linecap='round'/></svg>")

_P = {
    "check": "<path d='M3.5 8.5l3 3 6-7' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/>",
    "x": "<path d='M4.5 4.5l7 7M11.5 4.5l-7 7' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round'/>",
    "alert": "<path d='M8 2.5l6 11H2z' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linejoin='round'/><path d='M8 6.5v3' stroke='currentColor' stroke-width='1.6' stroke-linecap='round'/><circle cx='8' cy='11.6' r='.9' fill='currentColor'/>",
    "search": "<circle cx='7' cy='7' r='4.5' fill='none' stroke='currentColor' stroke-width='1.6'/><path d='M10.5 10.5L14 14' stroke='currentColor' stroke-width='1.6' stroke-linecap='round'/>",
    "flaky": "<path d='M2 9c2-4 4 2 6-2s4 2 6-2' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round'/>",
    "overview": "<rect x='2' y='2' width='5' height='5' rx='1.2' fill='none' stroke='currentColor' stroke-width='1.5'/><rect x='9' y='2' width='5' height='5' rx='1.2' fill='none' stroke='currentColor' stroke-width='1.5'/><rect x='2' y='9' width='5' height='5' rx='1.2' fill='none' stroke='currentColor' stroke-width='1.5'/><rect x='9' y='9' width='5' height='5' rx='1.2' fill='none' stroke='currentColor' stroke-width='1.5'/>",
    "cases": "<path d='M5.5 4h8M5.5 8h8M5.5 12h8' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/><circle cx='2.5' cy='4' r='1' fill='currentColor'/><circle cx='2.5' cy='8' r='1' fill='currentColor'/><circle cx='2.5' cy='12' r='1' fill='currentColor'/>",
    "compare": "<path d='M2.5 5h10l-2.5-2.5M13.5 11h-10L6 13.5' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/>",
    "info": "<circle cx='8' cy='8' r='6' fill='none' stroke='currentColor' stroke-width='1.5'/><path d='M8 7.2v4' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/><circle cx='8' cy='4.9' r='.9' fill='currentColor'/>",
    "groups": "<path d='M2 13V9M6 13V5M10 13V7M14 13V3' stroke='currentColor' stroke-width='1.6' stroke-linecap='round'/>",
    "split": "<path d='M8 2v12M3 5l-1.5 3L3 11M13 5l1.5 3L13 11' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/>",
    "back": "<path d='M10 3.5L5.5 8l4.5 4.5' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/>",
}


def _icon(name: str, size: int = 14) -> str:
    return f"<svg width='{size}' height='{size}' viewBox='0 0 16 16' aria-hidden='true'>{_P[name]}</svg>"


# -- small helpers ------------------------------------------------------------------------------------
def _e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _pct(v, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _ms(v: float) -> str:
    return f"{v:.1f} ms" if v < 10 else f"{v:,.0f} ms"


def _pretty(obj, limit: int = 4000) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def _href(view: str, cid: Optional[str] = None) -> str:
    return f"#/{view}" + (f"/{quote(str(cid), safe='')}" if cid is not None else "")


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
    b = (f"<span class='base' style='left:{_clamp(base) * 100:.2f}%' title='baseline {base * 100:.1f}%'></span>"
         if base is not None else "")
    return (f"<div class='track' title='{_e(tip)}' role='img' aria-label='{_e(tip)}'>"
            f"<span class='rng' style='left:{left:.2f}%;width:{max(right - left, 0.8):.2f}%'></span>{b}"
            f"<span class='pt' style='left:{_clamp(est) * 100:.2f}%'></span></div>")


def _fill(v: float, base: Optional[float] = None, label: str = "") -> str:
    tip = f"{label} {v * 100:.1f}%".strip() + (f" (baseline {base * 100:.1f}%)" if base is not None else "")
    b = f"<span class='base' style='left:{_clamp(base) * 100:.2f}%'></span>" if base is not None else ""
    return (f"<div class='track' title='{_e(tip)}' role='img' aria-label='{_e(tip)}'>"
            f"<span class='fill' style='width:{_clamp(v) * 100:.2f}%'></span>{b}</div>")


def _stat(label: str, value: str, viz: str = "", foot: str = "") -> str:
    return (f"<div class='stat'><div class='l'>{_e(label)}</div><div class='v num'>{_e(value)}</div>"
            f"{viz}<div class='f num'>{foot}</div></div>")


def _shell(title: str, side_head: str, nav: list, views: str, note: str) -> str:
    """nav: [(view, label, icon, count or None)]"""
    nav_html = "".join(
        f"<a href='#/{v}' data-v='{v}'>{_icon(ic, 15)}<span>{_e(lab)}</span>"
        + (f"<span class='c num'>{_e(c)}</span>" if c is not None else "") + "</a>"
        for v, lab, ic, c in nav)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return ("<!doctype html><html lang='en' class='nojs'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(title)}</title><style>{_CSS}</style></head><body><div class='app'>"
            f"<aside class='side'><div class='brand'>{_LOGO}holdline</div>{side_head}"
            f"<nav class='nav' aria-label='Report'>{nav_html}</nav>"
            f"<div class='foot'>{_e(note)}<br>Generated {now}<br>holdline {_e(__version__)}</div></aside>"
            f"<main class='main'>{views}</main></div><script>{_JS}</script></body></html>")


def _view(vid: str, title: str, sub: str, body: str, actions: str = "") -> str:
    return (f"<section class='view' id='v-{vid}'><div class='vh'><div><h1>{_e(title)}</h1>"
            + (f"<p>{sub}</p>" if sub else "") + f"</div>{actions}</div>{body}</section>")


# -- run report ------------------------------------------------------------------------------------
def _case_state(rs: list) -> str:
    n_ok = sum(r.passed for r in rs)
    return "pass" if rs and n_ok == len(rs) else "fail" if n_ok == 0 else "flaky"


def _status_icon(state: str, size: int = 15) -> str:
    if state == "pass":
        return f"<span class='i-good' title='passed every run'>{_icon('check', size)}</span>"
    if state == "flaky":
        return f"<span class='i-warn' title='passed some runs, failed others'>{_icon('flaky', size)}</span>"
    return f"<span class='i-bad' title='failed every run'>{_icon('x', size)}</span>"


def _first_failure(rs: list) -> str:
    for r in rs:
        for c in r.failed_checks:
            return f"{c.check}: {c.detail}" if c.detail else c.check
    return ""


def _verdict(gate_result, run, baseline) -> str:
    failed = not gate_result.passed
    n_rules = len(gate_result.reasons)
    title = (f"Gate failed: {n_rules} rule{'s' if n_rules != 1 else ''} broken" if failed
             else "Gate passed")
    if baseline is not None and gate_result.delta:
        d = gate_result.delta
        sub = (f"Compared with <b>{_e(baseline.meta.get('label'))}</b> on {gate_result.paired_cases} paired "
               f"cases: pass rate {d['estimate'] * 100:+.1f} pts (95% CI {d['ci'][0] * 100:+.1f} to "
               f"{d['ci'][1] * 100:+.1f}), {len(gate_result.regressions)} broke and {len(gate_result.fixes)} "
               f"fixed (McNemar p = {gate_result.mcnemar_p:.3g}).")
    else:
        sub = "No baseline was given, so only the absolute rules were applied."
    items = [f"<li><span class='i-bad'>{_icon('x')}</span><span>{_e(r)}</span></li>" for r in gate_result.reasons]
    items += [f"<li><span class='i-warn'>{_icon('alert')}</span><span>{_e(w)}</span></li>" for w in gate_result.warnings]
    if not items:
        items = [f"<li><span class='i-good'>{_icon('check')}</span><span>No rule was broken.</span></li>"]
    return (f"<div class='panel verdict {'fail' if failed else 'pass'}'><div class='vi'>{_icon('x' if failed else 'check', 20)}</div>"
            f"<div><div class='vt'>{_e(title)}</div><div class='vs2'>{sub}</div><ul class='vl'>{''.join(items)}</ul></div></div>")


def _stats_bar(run, baseline) -> str:
    s = run.summary
    k = s["repeats"]
    bs = baseline.summary if baseline is not None else None
    lo, hi = s["pass_rate_ci"]
    cells = [_stat("Pass rate", _pct(s["pass_rate"]),
                   _interval(s["pass_rate"], lo, hi, bs["pass_rate"] if bs else None),
                   (_delta(s["pass_rate"], bs["pass_rate"]) + " vs baseline") if bs else f"95% CI {_pct(lo)} to {_pct(hi)}")]
    pk = s.get(f"pass^{k}")
    cells.append(_stat(f"pass^{k}" if k > 1 else "Reliability", _pct(pk), _fill(pk or 0.0, bs.get(f"pass^{k}") if bs else None),
                       (_delta(pk, bs.get(f"pass^{k}")) + " vs baseline") if bs else
                       (f"all {k} runs of a case pass" if k > 1 else "run with -k 3 to measure")))
    if s["withheld_when_should"] is not None:
        cells.append(_stat("Held back when it should", _pct(s["withheld_when_should"]),
                           _fill(s["withheld_when_should"], bs["withheld_when_should"] if bs else None),
                           (_delta(s["withheld_when_should"], bs["withheld_when_should"]) + " vs baseline") if bs
                           else "abstained or escalated"))
    if s["answered_when_should"] is not None:
        cells.append(_stat("Answered when it should", _pct(s["answered_when_should"]),
                           _fill(s["answered_when_should"], bs["answered_when_should"] if bs else None),
                           (_delta(s["answered_when_should"], bs["answered_when_should"]) + " vs baseline") if bs
                           else "no over-refusal"))
    cells.append(_stat("Flaky cases", str(len(s["flaky_cases"])), "",
                       "passed some runs, failed others" if k > 1 else "needs repeats to measure"))
    lat = s["latency_ms"]
    cells.append(_stat("p95 latency", _ms(lat["p95"]), "",
                       (_delta(lat["p95"], bs["latency_ms"]["p95"], pct=False, higher_is_better=False, unit=" ms")
                        + " vs baseline") if bs else f"median {_ms(lat['p50'])}"))
    return f"<div class='panel stats'>{''.join(cells)}</div>"


def _case_map(run, by_case, regressed, fixed) -> str:
    cells = []
    for c in run.cases:
        rs = by_case[c.id]
        st = _case_state(rs)
        n_ok = sum(r.passed for r in rs)
        cls = {"pass": "", "fail": "fail", "flaky": "flaky"}[st]
        extra = " broke" if c.id in regressed else " fixed" if c.id in fixed else ""
        tip = f"{c.id}: {n_ok}/{len(rs)} runs passed" + (", broke vs baseline" if extra == " broke" else
                                                         ", fixed vs baseline" if extra == " fixed" else "")
        cells.append(f"<a class='cell {cls}{extra}' href='{_href('cases', c.id)}' title='{_e(tip)}' aria-label='{_e(tip)}'></a>")
    leg = ["<span><i class='sw good'></i>passed every run</span>", "<span><i class='sw bad'></i>failed every run</span>",
           "<span><i class='sw warn'></i>flaky</span>"]
    if regressed or fixed:
        leg.append("<span><i class='sw ring'></i>broke vs baseline</span>")
    return ("<div class='blk'><div class='sh'><h2>Case map</h2><p>One square per case. Select one to open it</p></div>"
            f"<div class='panel'><div class='map'><div class='cells'>{''.join(cells)}</div></div>"
            f"<div class='legend'>{''.join(leg)}</div></div></div>")


def _meters(title: str, desc: str, rows: list, base_rows: Optional[dict]) -> str:
    if not rows:
        return ""
    body = "".join(
        f"<div class='meter'><div class='nm' title='{_e(n)}'>{_e(n)}</div>"
        f"{_fill(v, base_rows.get(n) if base_rows else None, n)}<div class='pc num'>{_pct(v)}</div></div>"
        for n, v in rows)
    legend = ("<div class='legend'><span><i class='sw'></i>this run</span><span><i class='sw base'></i>baseline</span></div>"
              if base_rows else "")
    return (f"<div><div class='sh'><h2>{_e(title)}</h2><p>{_e(desc)}</p></div>"
            f"<div class='panel'><div class='meters'>{body}</div>{legend}</div></div>")


def _attention(run, by_case, regressed) -> str:
    bad = [c for c in run.cases if _case_state(by_case[c.id]) != "pass"]
    if not bad:
        k = run.summary["repeats"]
        return ("<div class='blk'><div class='panel empty'><b>Every case passed"
                + (f" in all {k} runs" if k > 1 else "") + ".</b>Nothing needs attention.</div></div>")
    bad.sort(key=lambda c: (c.id not in regressed, not c.must_pass, sum(r.passed for r in by_case[c.id])))
    rows = []
    for c in bad[:8]:
        rs = by_case[c.id]
        flags = ("<span class='flag broke'>broke</span>" if c.id in regressed else "") + \
                ("<span class='tag must'>must pass</span>" if c.must_pass else "")
        rows.append(f"<a href='{_href('cases', c.id)}'>{_status_icon(_case_state(rs), 13)}<span class='id'>{_e(c.id)}</span>"
                    f"<span class='why'>{_e(_first_failure(rs))}</span><span class='fl tags' style='margin:0'>{flags}</span>"
                    f"<span class='runs num'>{sum(r.passed for r in rs)}/{len(rs)} runs</span></a>")
    if len(bad) > 8:
        rows.append(f"<a class='more' href='#/cases'>Show all {len(bad)} failing cases</a>")
    return ("<div class='blk'><div class='sh'><h2>Needs attention</h2><p>Failing and flaky cases, regressions first</p></div>"
            f"<div class='panel att'>{''.join(rows)}</div></div>")


def _timeline(trace) -> str:
    if not trace.steps:
        return "<div class='tlh'>Trace</div><div class='empty' style='padding:14px'>No steps recorded for this run.</div>"
    items = []
    for st in trace.steps:
        args = tool_arguments(st.input) if st.kind == "tool" else st.input
        arg_html = "" if args in (None, {}, [], "") else f"<pre>{_e(_pretty(args, 1500))}</pre>"
        out_html = ("" if st.output in (None, "", {}, []) else
                    f"<details><summary>Output</summary><pre>{_e(_pretty(st.output, 2000))}</pre></details>")
        err_html = f"<div class='errm'><span class='i-bad'>{_icon('x', 13)}</span>{_e(st.error)}</div>" if st.error else ""
        meta = []
        if st.tokens:
            meta.append(f"{st.tokens:,} tokens")
        if st.ms:
            meta.append(_ms(st.ms))
        kind = st.kind if st.kind in ("tool", "llm", "decision") else "other"
        items.append(f"<li class='st k-{kind}{' err' if st.error else ''}'><span class='nd'></span>"
                     f"<div class='sr'><span class='kind'>{_e(st.kind)}</span><code>{_e(st.name)}</code>"
                     f"<span class='m num'>{_e(', '.join(meta))}</span></div>{arg_html}{err_html}{out_html}</li>")
    return f"<div class='tlh'>Trace, {len(trace.steps)} steps</div><ol class='tl'>{''.join(items)}</ol>"


def _detail(case, rs, regressed: bool, fixed: bool) -> str:
    n_ok = sum(r.passed for r in rs)
    tags = "".join(f"<span class='tag'>{_e(t)}</span>" for t in case.tags)
    if case.must_pass:
        tags += "<span class='tag must'>must pass</span>"
    if regressed:
        tags += "<span class='flag broke'>broke vs baseline</span>"
    if fixed:
        tags += "<span class='flag fixed'>fixed vs baseline</span>"
    groups: dict = {}
    for r in rs:
        key = (r.passed, tuple((c.check, c.detail) for c in r.failed_checks), tuple(r.trace.tool_names()))
        groups.setdefault(key, []).append(r)
    blocks = []
    for (passed, _, _), grp in groups.items():
        r = grp[0]
        nums = [g.repeat + 1 for g in grp]
        which = ("This run" if len(rs) == 1 else f"All {len(rs)} runs" if len(grp) == len(rs)
                 else ("Run " if len(nums) == 1 else "Runs ") + ", ".join(map(str, nums)))
        icon = f"<span class='i-good'>{_icon('check')}</span>" if passed else f"<span class='i-bad'>{_icon('x')}</span>"
        failed = "".join(
            f"<div class='chk'><span class='i-bad'>{_icon('x', 13)}</span><span><b>{_e(c.check)}</b>"
            + (f" <span class='d'>{_e(c.detail)}</span>" if c.detail else "") + "</span></div>"
            for c in r.failed_checks)
        ok = "".join(f"<span><span class='i-good'>{_icon('check', 12)}</span>{_e(c.check)}</span>" for c in r.checks if c.passed)
        blocks.append(f"<div class='rg'><div class='rgh'>{icon}{_e(which)} {'passed' if passed else 'failed'}"
                      f"<span class='m num'>{_ms(r.trace.ms)}, outcome {_e(outcome_of(r.trace))}</span></div>"
                      + (f"<div class='checks'>{failed}</div>" if failed else "")
                      + (f"<div class='passed'>{ok}</div>" if ok else "")
                      + _timeline(r.trace)
                      + f"<div class='outbox'><div class='box'><h3>Final output</h3><pre>{_e(_pretty(r.trace.output))}</pre></div></div></div>")
    expected = _pretty(case.expected) if case.expected else "Nothing beyond running without an error."
    return (f"<article class='panel detail' data-id='{_e(case.id)}'>"
            f"<a class='btn back' href='#/cases'>{_icon('back', 13)}&nbsp;All cases</a>"
            f"<div class='dh'><div style='min-width:0'><h2>{_e(case.id)}</h2><div class='tags'>{tags}</div></div>"
            f"<div class='score'><div class='big num'>{n_ok}/{len(rs)}</div><div class='s'>runs passed</div></div></div>"
            f"<div class='io'><div class='box'><h3>Input</h3><pre>{_e(_pretty(case.input))}</pre></div>"
            f"<div class='box'><h3>Expected</h3><pre>{_e(expected)}</pre></div></div>"
            f"{''.join(blocks)}</article>")


def _cases_view(run, by_case, regressed, fixed, has_baseline: bool) -> str:
    s = run.summary
    states = {c.id: _case_state(by_case[c.id]) for c in run.cases}
    n_fail = sum(1 for v in states.values() if v != "pass")
    filters = [("all", "All", len(run.cases)), ("failing", "Failing", n_fail), ("flaky", "Flaky", len(s["flaky_cases"]))]
    if has_baseline:
        filters.append(("regressed", "Broke", len(regressed)))
    n_must = sum(1 for c in run.cases if c.must_pass)
    if n_must:
        filters.append(("must", "Must pass", n_must))
    seg = "".join(f"<button type='button' data-filter='{key}' aria-pressed='{'true' if key == 'all' else 'false'}'>"
                  f"{_e(lab)}<span class='n num'>{n}</span></button>" for key, lab, n in filters)
    rows, details = [], []
    for c in run.cases:
        rs = by_case[c.id]
        st = states[c.id]
        dots = "".join(f"<i class='{'' if r.passed else 'x'}'></i>" for r in rs)
        sub = _first_failure(rs) or ", ".join(c.tags) or "passed"
        search = " ".join([c.id] + list(c.tags) + sorted({outcome_of(r.trace) for r in rs})).lower()
        rows.append(f"<a class='row' href='{_href('cases', c.id)}' data-id='{_e(c.id)}' data-state='{st}' "
                    f"data-failing='{int(st != 'pass')}' data-flaky='{int(st == 'flaky')}' data-must='{int(c.must_pass)}' "
                    f"data-regressed='{int(c.id in regressed)}' data-search='{_e(search)}'>{_status_icon(st, 14)}"
                    f"<div style='min-width:0'><div class='id'>{_e(c.id)}</div><div class='sub'>{_e(sub)}</div></div>"
                    f"<div class='dots' title='{sum(r.passed for r in rs)}/{len(rs)} runs passed'>{dots}</div></a>")
        details.append(_detail(c, rs, c.id in regressed, c.id in fixed))
    toolbar = (f"<div class='toolbar'><div class='seg' role='group' aria-label='Filter cases'>{seg}</div>"
               f"<label class='search'>{_icon('search')}<input id='q' type='search' placeholder='Search by case, tag or outcome' "
               "aria-label='Search cases'></label><span class='hint'><span class='kbd'>/</span>search "
               "<span class='kbd'>j</span><span class='kbd'>k</span>move</span></div>")
    body = (toolbar + "<div class='split'><div class='panel list'><div class='lh'><span><span id='shown' class='num'>"
            f"{len(run.cases)}</span> cases</span><span>runs</span></div><div class='rows'>{''.join(rows)}</div>"
            "<div class='empty' id='empty' hidden><b>No cases match.</b>Try another filter or search term."
            "<br><button type='button' class='btn' id='clear'>Clear filters</button></div></div>"
            f"<div class='detailwrap'>{''.join(details)}</div></div>")
    return _view("cases", "Cases", "Each case with its checks and the full trace of every run.", body)


def _compare_view(gate_result, baseline) -> str:
    if gate_result is None or baseline is None or not gate_result.metrics:
        return _view("compare", "Compare", "", "<div class='panel empty'><b>No baseline in this report.</b>"
                     "Run <code>holdline gate --baseline base.json --candidate this.json --html report.html</code> "
                     "to compare two runs case by case.</div>")
    rows = []
    for m in gate_result.metrics:
        is_pct = m["metric"].startswith(("pass", "held", "answered", "check:"))
        fmt = (lambda v: _pct(v)) if is_pct else (lambda v: "n/a" if v is None else f"{v:.4g}")
        higher = not m["metric"].startswith(("p95", "cost"))
        rows.append(f"<tr><td>{_e(m['metric'])}</td><td class='r num'>{_e(fmt(m.get('baseline')))}</td>"
                    f"<td class='r num'>{_e(fmt(m.get('candidate')))}</td>"
                    f"<td class='r num'>{_delta(m.get('candidate'), m.get('baseline'), is_pct, higher) or 'n/a'}</td></tr>")

    def case_list(ids, empty_txt):
        if not ids:
            return f"<div class='empty' style='padding:20px'>{_e(empty_txt)}</div>"
        return "<table class='t'>" + "".join(
            f"<tr><td><a class='lnk' href='{_href('cases', i)}'>{_e(i)}</a></td></tr>" for i in ids) + "</table>"

    body = ("<div class='panel' style='overflow-x:auto'><table class='t'><tr><th>Metric</th>"
            f"<th class='r'>Baseline</th><th class='r'>This run</th><th class='r'>Change</th></tr>{''.join(rows)}</table></div>"
            "<div class='blk two'>"
            f"<div><div class='sh'><h2>Broke</h2><p>Passed in the baseline, fail now</p></div><div class='panel'>"
            f"{case_list(gate_result.regressions, 'No case broke.')}</div></div>"
            f"<div><div class='sh'><h2>Fixed</h2><p>Failed in the baseline, pass now</p></div><div class='panel'>"
            f"{case_list(gate_result.fixes, 'No case was fixed.')}</div></div></div>")
    return _view("compare", "Compare", f"This run against <b>{_e(baseline.meta.get('label'))}</b>, case by case.", body)


def _info_view(run, baseline) -> str:
    m = run.meta
    s = run.summary

    def dl(meta, summ):
        rows = [("Label", meta.get("label")), ("Suite", meta.get("suite")), ("Suite file", meta.get("suite_path")),
                ("Target", meta.get("target")), ("Cases", summ["cases"]), ("Repeats per case", summ["repeats"]),
                ("Runs", summ["runs"]), ("Runs with errors", summ["errors"]), ("Started", meta.get("started")),
                ("Duration", f"{meta.get('seconds', 0)} s"), ("Git commit", meta.get("git_sha") or "n/a"),
                ("Python", meta.get("python")), ("holdline", meta.get("holdline"))]
        return "<dl class='kv'>" + "".join(f"<dt>{_e(a)}</dt><dd>{_e(b)}</dd>" for a, b in rows if b is not None) + "</dl>"

    body = f"<div class='sh'><h2>This run</h2></div><div class='panel'>{dl(m, s)}</div>"
    if baseline is not None:
        body += f"<div class='blk'><div class='sh'><h2>Baseline</h2></div><div class='panel'>{dl(baseline.meta, baseline.summary)}</div></div>"
    return _view("info", "Run info", "Where these numbers came from.", body)


def run_html(run, gate_result=None, baseline=None) -> str:
    s = run.summary
    by_case = run.by_case()
    regressed = set(gate_result.regressions) if gate_result is not None else set()
    fixed = set(gate_result.fixes) if gate_result is not None else set()
    has_base = gate_result is not None and baseline is not None

    overview = []
    if gate_result is not None:
        overview.append(_verdict(gate_result, run, baseline))
    overview.append(_stats_bar(run, baseline))
    overview.append(_case_map(run, by_case, regressed, fixed))
    overview.append(_attention(run, by_case, regressed))
    meters = (_meters("Checks", "Share of runs where each check passed", list(s["checks"].items()),
                      baseline.summary["checks"] if has_base else None)
              + _meters("By tag", "Mean case pass rate per tag", list(s["tags"].items()),
                        baseline.summary["tags"] if has_base else None))
    if meters:
        overview.append(f"<div class='blk two'>{meters}</div>")
    k = s["repeats"]
    sub = (f"{s['cases']} cases on <b>{_e(run.meta.get('suite'))}</b>, {k} run{'s' if k != 1 else ''} each.")
    views = (_view("overview", run.meta.get("label") or "Run", sub, "".join(overview))
             + _cases_view(run, by_case, regressed, fixed, has_base)
             + _compare_view(gate_result, baseline) + _info_view(run, baseline))

    side = (f"<div class='runbox'><div class='k'>Run</div><div class='n'>{_e(run.meta.get('label'))}</div>"
            + (f"<div class='vs'>vs {_e(baseline.meta.get('label'))}</div>" if baseline is not None else "")
            + (f"<div class='vpill {'' if gate_result.passed else 'fail'}'><i></i>Gate {'passed' if gate_result.passed else 'failed'}</div>"
               if gate_result is not None else "") + "</div>")
    n_bad = sum(1 for c in run.cases if _case_state(by_case[c.id]) != "pass")
    nav = [("overview", "Overview", "overview", None), ("cases", "Cases", "cases", f"{n_bad} failing" if n_bad else len(run.cases)),
           ("compare", "Compare", "compare", len(regressed) if has_base else None), ("info", "Run info", "info", None)]
    return _shell(f"holdline · {run.meta.get('label')}", side, nav, views, run.meta.get("suite") or "")


# -- calibration report -------------------------------------------------------------------------------
def _seq_shade(n: int, total: int) -> str:
    ramp = ["#f1f2f4", "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef"]  # one-hue sequential (blue)
    share = n / total if total else 0
    return ramp[min(len(ramp) - 1, int(share * 2 * (len(ramp) - 1) + 0.999))] if n else ramp[0]


def calibration_html(rep: dict, label: str = "judge", items: Optional[list] = None) -> str:
    o = rep["overall"]
    fit = rep["fit_to_gate"]
    th = rep.get("thresholds", {})
    icon = "check" if fit else "x"
    cls = "i-good" if fit else "i-bad"
    reasons = rep["reasons"] or ["Every calibration rule passed."]
    lis = "".join(f"<li><span class='{cls}'>{_icon(icon)}</span><span>{_e(r)}</span></li>" for r in reasons)
    verdict = (f"<div class='panel verdict {'pass' if fit else 'fail'}'><div class='vi'>{_icon(icon, 20)}</div><div>"
               f"<div class='vt'>{'Fit to gate releases' if fit else 'Not fit to gate releases'}</div>"
               "<div class='vs2'>A judge may grade release-gating cases only if it agrees with humans well beyond chance, "
               "rarely passes what a human failed, and is not lenient on some kinds of case while harsh on others.</div>"
               f"<ul class='vl'>{lis}</ul></div></div>")

    kappa, ci = o["kappa"], o["kappa_ci"]
    bias = o["bias"] or 0.0
    lean = "lenient" if bias > 0 else "harsh" if bias < 0 else "neutral"
    stats = ("<div class='panel stats'>"
             + _stat("Cohen's kappa", "n/a" if kappa is None else f"{kappa:.2f}",
                     _interval(_clamp(kappa or 0), _clamp(ci[0]), _clamp(ci[1])) if ci else "",
                     (f"95% CI {ci[0]:.2f} to {ci[1]:.2f}, {_e(o['kappa_band'])}" if ci else "needs 2 or more items"))
             + _stat("Raw agreement", _pct(o["agreement"]), _fill(o["agreement"] or 0.0), "same verdict as the human")
             + _stat("False-pass rate", _pct(o["false_pass_rate"]), _fill(o["false_pass_rate"] or 0.0),
                     "judge passed what a human failed")
             + _stat("Bias", f"{bias:+.2f}", "",
                     f"{lean}; the average hides a split by group" if rep["sign_reversal"] else f"{lean} overall")
             + "</div>")

    cm, n = o["confusion"], o["n"]

    def cell(count, text, extra=""):
        return f"<div class='cmc {extra}' style='background:{_seq_shade(count, n)}'><b class='num'>{count}</b><span>{_e(text)}</span></div>"

    matrix = ("<div><div class='sh'><h2>Confusion matrix</h2><p>" + str(n) + " labelled items</p></div><div class='panel'><div class='cm'>"
              "<div></div><div class='h'>Judge pass</div><div class='h'>Judge fail</div>"
              f"<div class='h rh'>Human pass</div>{cell(cm['tp'], 'agree: pass')}{cell(cm['fn'], 'false fail')}"
              f"<div class='h rh'>Human fail</div>{cell(cm['fp'], 'false pass: lets bad output through', 'fp')}{cell(cm['tn'], 'agree: fail')}"
              "</div><div class='legend'><span>Shade shows the share of items</span><span>Outlined: the costly error for a release gate</span></div></div></div>")

    groups = rep.get("groups") or {}
    if groups:
        span = max([0.25] + [abs(g["bias"] or 0) for g in groups.values()])
        drows = []
        for g, b in groups.items():
            v = b["bias"] or 0.0
            w = abs(v) / span * 50
            pos = f"left:50%;width:{w:.2f}%" if v > 0 else f"left:{50 - w:.2f}%;width:{w:.2f}%"
            bar = f"<span class='bar {'len' if v > 0 else 'har'}' style='{pos}'></span>" if v else ""
            tip = f"{g}: bias {v:+.2f}, {b['n']} items, agreement {_pct(b['agreement'])}"
            drows.append(f"<div class='drow'><div class='mono' title='{_e(tip)}' style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{_e(g)}</div>"
                         f"<div class='dtrack' title='{_e(tip)}' role='img' aria-label='{_e(tip)}'><span class='ax'></span>{bar}</div>"
                         f"<div class='num' style='text-align:right'>{v:+.2f}</div></div>")
        rev = (f"<div class='note'><span class='i-bad'>{_icon('alert')}</span><span><b>Bias changes sign.</b> Lenient on "
               f"{_e(', '.join(rep['lenient_groups']))}, harsh on {_e(', '.join(rep['harsh_groups']))}. One threshold cannot fix both.</span></div>"
               if rep["sign_reversal"] else "")
        diverging = ("<div><div class='sh'><h2>Bias by group</h2><p>Judge pass share minus human pass share</p></div><div class='panel'>"
                     "<div class='div'><div class='dscale'><div></div><div><span>&#9664; harsh</span><span>lenient &#9654;</span></div><div></div></div>"
                     f"{''.join(drows)}</div><div class='legend'><span><i class='sw' style='background:var(--accent)'></i>harsh: fails what humans pass</span>"
                     f"<span><i class='sw' style='background:#e34948'></i>lenient: passes what humans fail</span></div>{rev}</div></div>")
    else:
        diverging = ("<div><div class='sh'><h2>Bias by group</h2></div><div class='panel empty'><b>No groups in these labels.</b>"
                     "Add a <code>group</code> field to each label to see whether the judge's bias changes across kinds of case.</div></div>")
    overview = verdict + stats + f"<div class='blk two'>{matrix}{diverging}</div>"
    if "threshold" in rep:
        t = rep["threshold"]
        held = "n/a" if t["kappa_held_out_half"] is None else f"{t['kappa_held_out_half']:.2f}"
        overview += ("<div class='blk'><div class='sh'><h2>Score threshold</h2><p>Chosen on one half of the labels, checked on the other</p></div>"
                     "<div class='panel stats'>" + _stat("Best threshold", str(t["threshold"]), "", "a score at or above this passes")
                     + _stat("Kappa on the tuning half", f"{t['kappa_fit_half']:.2f}", "", f"{t['n_fit']} items, optimistic by construction")
                     + _stat("Kappa on the held-out half", held, "", f"{t['n_held_out']} items, the number to trust") + "</div></div>")

    if groups:
        trs = "".join(f"<tr><td class='mono'>{_e(g)}</td><td class='r num'>{b['n']}</td><td class='r num hs'>{_pct(b['agreement'])}</td>"
                      f"<td class='r num'>{'n/a' if b['kappa'] is None else format(b['kappa'], '.2f')}</td>"
                      f"<td class='r num'>{(b['bias'] or 0):+.2f}</td><td class='r num'>{_pct(b['false_pass_rate'])}</td></tr>"
                      for g, b in groups.items())
        gbody = ("<div class='panel' style='overflow-x:auto'><table class='t'><tr><th>Group</th><th class='r'>Items</th>"
                 "<th class='r hs'>Agreement</th><th class='r'>Kappa</th><th class='r'>Bias</th><th class='r'>False-pass</th></tr>"
                 f"{trs}</table></div>")
    else:
        gbody = "<div class='panel empty'><b>No groups in these labels.</b>Add a <code>group</code> field to each label.</div>"

    disagree = []
    if items:
        from .judge import as_bool
        for it in items:
            h, j = as_bool(it["human"]), as_bool(it["judge"])
            if h != j:
                disagree.append((it.get("id", ""), it.get("group", it.get("difficulty", "")), h, j, it.get("judge_score")))
    if items is None:
        dbody = "<div class='panel empty'><b>Labels were not included in this report.</b>Generate it with <code>holdline calibrate --html</code>.</div>"
    elif not disagree:
        dbody = "<div class='panel empty'><b>The judge agreed with the human on every item.</b></div>"
    else:
        disagree.sort(key=lambda d: (d[3] is False, str(d[1]), str(d[0])))  # false passes first
        trs = "".join(
            f"<tr><td class='mono'>{_e(i)}</td><td class='hs'>{_e(g)}</td>"
            f"<td><span class='verdict-chip {'' if h else 'f'}'>{'pass' if h else 'fail'}</span></td>"
            f"<td><span class='verdict-chip {'' if j else 'f'}'>{'pass' if j else 'fail'}</span></td>"
            f"<td>{'false pass' if j else 'false fail'}</td></tr>" for i, g, h, j, _ in disagree)
        dbody = ("<div class='panel' style='overflow-x:auto'><table class='t'><tr><th>Item</th><th class='hs'>Group</th><th>Human</th>"
                 f"<th>Judge</th><th>Error</th></tr>{trs}</table></div>")

    sbody = ("<div class='panel'><dl class='kv'>"
             + "".join(f"<dt>{_e(a)}</dt><dd>{_e(b)}</dd>" for a, b in (
                 ("Judge", label), ("Labelled items", n), ("Minimum items", th.get("min_n")),
                 ("Minimum kappa (lower bound)", th.get("min_kappa")), ("Maximum false-pass rate", th.get("max_false_pass"))))
             + "</dl></div>")
    views = (_view("overview", f"{label} calibration", f"Compared with human labels on {n} items.", overview)
             + _view("groups", "Groups", "How the judge does on each kind of case.", gbody)
             + _view("disagreements", "Disagreements", "Every item where the judge and the human differed, false passes first.", dbody)
             + _view("settings", "Settings", "The rules this judge was held to.", sbody))
    side = (f"<div class='runbox'><div class='k'>Judge</div><div class='n'>{_e(label)}</div>"
            f"<div class='vpill {'' if fit else 'fail'}'><i></i>{'Fit to gate' if fit else 'Not fit to gate'}</div></div>")
    nav = [("overview", "Overview", "overview", None), ("groups", "Groups", "groups", len(groups) or None),
           ("disagreements", "Disagreements", "split", len(disagree) if items is not None else None),
           ("settings", "Settings", "info", None)]
    return _shell(f"holdline · {label} calibration", side, nav, views, "Judge calibration")
