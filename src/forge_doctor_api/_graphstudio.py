"""Forge Graph Studio — local-first, read-only graph explorer.

A zero-dependency stdlib server (``http.server`` on 127.0.0.1) plus a
single-file HTML/canvas frontend embedded below. No Node, no CDN, no
build step — the whole app ships as Python package source.

GET-only by design: exploring a graph can never modify the project
(§4.4). ``serve()`` never opens a browser unless asked; ``--no-browser``
prints the URL for SSH port-forwarding.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

STUDIO_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Forge Graph Studio</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0d1117;--panel:#161b22;--fg:#e6edf3;--dim:#8b949e;--line:#30363d;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:13px/1.4 ui-monospace,Consolas,monospace;display:grid;
grid-template-columns:220px 1fr 280px;grid-template-rows:44px 1fr 26px;height:100vh}
header{grid-column:1/4;display:flex;gap:12px;align-items:center;padding:0 12px;
background:var(--panel);border-bottom:1px solid var(--line)}
header b{color:var(--acc)}select,input{background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:4px;padding:4px 6px}
#side,#insp{background:var(--panel);padding:10px;overflow:auto}
#side{border-right:1px solid var(--line)}#insp{border-left:1px solid var(--line)}
#wrap{position:relative;overflow:hidden}canvas{display:block;width:100%;height:100%;cursor:grab}
footer{grid-column:1/4;background:var(--panel);border-top:1px solid var(--line);
display:flex;gap:16px;padding:4px 12px;color:var(--dim)}
.k{word-break:break-all}.dim{color:var(--dim)}h4{margin:10px 0 4px;color:var(--dim);
text-transform:uppercase;font-size:11px;letter-spacing:.05em}
label.f{display:block;margin:2px 0;cursor:pointer}
#insp .pill{display:inline-block;border:1px solid var(--line);border-radius:10px;
padding:0 8px;margin:1px 2px;font-size:11px}
.ev{color:var(--acc);font-size:11px;word-break:break-all}
#err{display:none;position:absolute;top:8px;left:8px;right:8px;z-index:6;
background:#5a1e1e;border:1px solid #f78166;border-radius:4px;
padding:6px 8px;color:#ffdcd0}
#notice{display:none;position:absolute;top:36px;left:8px;right:190px;z-index:5;
background:#3a2e14;border:1px solid #e3b341;border-radius:4px;
padding:4px 8px;color:#ffd977}
#crumbs{position:absolute;left:8px;bottom:6px;z-index:4;color:var(--dim);
font-size:11px;background:rgba(13,17,23,.75);padding:1px 6px;border-radius:4px}
#mmap{position:absolute;right:8px;top:8px;z-index:4;border:1px solid var(--line);
background:rgba(13,17,23,.85);width:170px;height:110px}
.mb{background:var(--bg);color:var(--fg);border:1px solid var(--line);
border-radius:4px;padding:1px 7px;margin:1px 2px;cursor:pointer;font-size:11px}
.nlink{color:var(--acc);cursor:pointer;margin-right:4px}
</style></head>
<body>
<header><b>FORGE GRAPH STUDIO</b>
<select id="gsel"></select>
<select id="mode" title="scale mode"><option value="overview">overview</option>
<option value="explore">explore</option><option value="full">full</option></select>
<select id="lod" title="level of detail"><option value="auto">lod:auto</option>
<option value="fine">lod:fine</option><option value="coarse">lod:coarse</option></select>
<input id="q" placeholder="search… (/)" size="16">
<span id="meta" class="dim"></span></header>
<div id="side"><h4>Explore</h4><div id="expl" class="dim"></div>
<h4>Communities</h4><div id="comms" class="dim"></div>
<h4>Layers</h4><div id="layers"></div>
<h4>Edge kinds</h4><div id="ekinds"></div>
<h4>Legend</h4><div id="legend" class="dim"></div></div>
<div id="wrap"><canvas id="cv"></canvas><div id="err"></div>
<div id="notice"></div><canvas id="mmap" width="170" height="110"></canvas>
<div id="crumbs"></div></div>
<div id="insp"><h4>Inspector</h4><div id="ibody" class="dim">select a node or edge</div></div>
<footer><span id="stats"></span><span id="prov"></span>
<span class="dim">scroll=zoom · drag=pan · dblclick=drill/expand · /=search ·
n=nbhd · x=expand · p=path · f=fit · m=mode · e=export · d=diff · s=snap · esc=reset</span></footer>
<script>
// lf-0021 force-layout tuning: bounded forces + annealing so the sim converges.
// lf-0022 scale modes (overview / explore / full), time-sliced layout,
// seeded PRNG (no unseeded randomness), tiered honest rendering.
const LINK_D=120,SPRING_K=0.02,GRAVITY=0.001,DAMP=0.85,SPMAX=50,
REP=2000,FCAP=60,BH_N=500,THETA=0.9,ALPHA_DECAY=0.985,ALPHA_MIN=0.005,
SMIN=0.02,SMAX=8,CHUNK=512,OV_MIN=2000,CLUST_MAX=250,LPA_ROUNDS=25,COMP_LPA=40,
EXPL_MAX=2500,EDGE_DRAW_MAX=12000,ARROW_MAX=1500,LABEL_MAX=300,PATH_MAX_DEPTH=12,
BLAST_CAP=800,NEI_CAP=50,DRILL_TOP=25,TICK_SMALL=8000;
let G={nodes:[],edges:[],byId:new Map(),adj:new Map(),out:new Map()},
view={x:0,y:0,s:1},sel=null,hover=null,kindsOn={},ekindsOn={},PAL={},
running=false,gen=0,alpha=1,rafId=0,resets=0,settled=false,lticks=0,
mode='full',R={nodes:[],edges:[]},clusters=null,clusterMap=null,aggEdges=[],
explore={seeds:new Set(),depth:2,cap:25,extra:new Set()},
crumbs=[],pathA=null,pathB=null,pathHi=null,pathEdges=null,blastHi=null,blastInfo=null,
searchHits=null,focusSet=null,diffRef=null,drawDiffColors=null,curId=null,jobSeq=0,
drawMeta={nodes:0,edges:0,edgesOk:0,labels:0},simPos=null,lastMini=null,lod='auto',
neiShow=NEI_CAP,FULL_BUDGET=10000,SIM_MS=8,_seed=1;
const cv=document.getElementById('cv'),cx=cv.getContext('2d');
const KCOLORS=['#58a6ff','#f78166','#7ee787','#ffa657','#d2a8ff','#76e3ea','#ff9bce','#e3b341'];
const ESTYLE={observed:[],declared:[6,3],inferred:[3,4],planned:[2,4],desired:[8,3],unknown:[1,5]};
function pal(k){if(!(k in PAL))PAL[k]=KCOLORS[Object.keys(PAL).length%KCOLORS.length];return PAL[k]}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,
c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
// lf-0022: all layout randomness goes through a seeded PRNG (mulberry32) —
// the same graph id reproduces the same layout; nothing unseeded is used.
function srand(s){let h=2166136261;s=String(s);
for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}
_seed=(h>>>0)||1}
function rand(){_seed|=0;_seed=(_seed+0x6D2B79F5)|0;
let t=Math.imul(_seed^(_seed>>>15),1|_seed);
t=(t+Math.imul(t^(t>>>7),61|t))^t;return((t^(t>>>14))>>>0)/4294967296}
function nowMs(){const p=typeof performance!=='undefined'&&performance.now;
return p?performance.now():Date.now()}
function showErr(m){const e=document.getElementById('err');
e.textContent='⚠ '+m;e.style.display='block'}
// lf-0022: no silent truncation — every cap surfaces in #notice or the footer.
function setNotice(t){const n=document.getElementById('notice');
n.textContent=t||'';n.style.display=t?'block':'none'}
async function loadGraphs(){try{const r=await fetch('/api/graphs');const d=await r.json();
const s=document.getElementById('gsel');s.innerHTML='';
d.graphs.forEach(g=>{const o=document.createElement('option');o.value=g.graph_id;
o.textContent=`${g.provider_id} · ${g.graph_id}`+
` (${g.node_count}/${g.edge_count})`;s.appendChild(o)});
if(d.graphs.length)loadGraph(d.graphs[0].graph_id);
s.onchange=e=>loadGraph(e.target.value)}catch(e){showErr('graph list failed: '+e)}}
async function loadGraph(id){try{
const r=await fetch('/api/graph/'+encodeURIComponent(id));
const d=await r.json();
curId=id;sel=null;hover=null;resets=0;simPos=null;lticks=0;
pathA=null;pathB=null;pathHi=null;pathEdges=null;blastHi=null;blastInfo=null;
searchHits=null;focusSet=null;diffRef=null;drawDiffColors=null;crumbs=[];
clusters=null;clusterMap=null;aggEdges=[];neiShow=NEI_CAP;
explore={seeds:new Set(),depth:2,cap:25,extra:new Set()};
// lf-0022: positions come from a stream seeded by the graph id — a reload of
// the same graph reproduces the same starting layout.
srand('g:'+id);
G.nodes=(d.nodes||[]).map(n=>({...n,x:rand()*600-300,y:rand()*600-300,vx:0,vy:0,deg:0}));
G.byId=new Map(G.nodes.map(n=>[n.id,n]));
// dangling edges are dropped BEFORE degree is counted (deg must describe the
// graph that is actually drawn).
G.edges=(d.edges||[]).filter(e=>G.byId.has(e.source)&&G.byId.has(e.target));
G.edges.forEach(e=>{G.byId.get(e.source).deg++;G.byId.get(e.target).deg++});
// indexed adjacency once per load (lf-0022): undirected adj (sorted by -deg,
// id — deterministic caps) + directed out for blast/analysis.
G.adj=new Map();G.out=new Map();
const bump=(m,a,b)=>{let l=m.get(a);if(!l){l=[];m.set(a,l)}l.push(b)};
G.edges.forEach(e=>{bump(G.adj,e.source,e.target);bump(G.adj,e.target,e.source);
bump(G.out,e.source,e.target)});
G.adj.forEach(l=>l.sort((a,b)=>{const db=G.byId.get(b).deg,da=G.byId.get(a).deg;
return db-da||(a<b?-1:a>b?1:0)}));
kindsOn={};G.nodes.forEach(n=>kindsOn[n.kind]=true);
ekindsOn={};G.edges.forEach(e=>ekindsOn[e.kind]=true);
// lf-0022: mode persisted per graph; default overview past OV_MIN nodes.
const p=loadPrefs();
explore.depth=p.depth||2;explore.cap=p.cap||25;
lod=(p.lod==='fine'||p.lod==='coarse')?p.lod:'auto';
mode=(p.mode==='overview'||p.mode==='explore'||p.mode==='full')?p.mode:
(G.nodes.length>OV_MIN?'overview':'full');
document.getElementById('mode').value=mode;
document.getElementById('lod').value=lod;
sidePanel();explPanel();commsPanel();renderCrumbs();inspect();
document.getElementById('meta').textContent=
`${d.descriptor.provider_id} · ${d.descriptor.domain} · ${d.descriptor.generated_at||''}`;
document.getElementById('prov').textContent=
(d.descriptor.limitations||[]).join(' | ').slice(0,120);
// lf-0021: bump the generation so any RAF chain a previous graph scheduled
// stops on its next frame, and really cancel the pending callback.
if(rafId)cancelAnimationFrame(rafId);rafId=0;
running=true;settled=false;alpha=1;const g=++gen;
buildRender();fitToView();tick(g)}catch(e){showErr('load failed: '+e)}}
function topDegId(){let b=null,bd=-1;
G.nodes.forEach(n=>{if(n.deg>bd){bd=n.deg;b=n.id}});return b}
function savePrefs(){try{localStorage.setItem('fgs:'+curId,
JSON.stringify({mode,depth:explore.depth,cap:explore.cap,lod}))}catch(e){}}
function loadPrefs(){try{
return JSON.parse(localStorage.getItem('fgs:'+curId)||'null')||{}}catch(e){return{}}}
function sidePanel(){const L=document.getElementById('layers'),E=document.getElementById('ekinds');
L.innerHTML='';E.innerHTML='';
Object.keys(kindsOn).sort().forEach(k=>{L.innerHTML+=
`<label class="f"><input type="checkbox" checked data-k="${esc(k)}">`+
` <span style="color:${pal(k)}">●</span> ${esc(k)}</label>`});
Object.keys(ekindsOn).sort().forEach(k=>{E.innerHTML+=
`<label class="f"><input type="checkbox" checked data-ek="${esc(k)}"> ${esc(k)}</label>`});
L.querySelectorAll('input').forEach(i=>i.onchange=e=>{
kindsOn[e.target.dataset.k]=e.target.checked;buildRender();reheat(0.3);draw()});
E.querySelectorAll('input').forEach(i=>i.onchange=e=>{
ekindsOn[e.target.dataset.ek]=e.target.checked;buildRender();reheat(0.3);draw()});
document.getElementById('legend').innerHTML=
Object.keys(ESTYLE).map(s=>`<div>─ ${s}</div>`).join('')}
// ---- lf-0022: scale modes ---------------------------------------------------
// The sim always works on R = the render set (drawables). G keeps the full
// data: search, inspector, diff and analysis see the whole graph.
function explPanel(){const e=document.getElementById('expl');if(!e)return;
let h='';
if(mode==='explore'){h=`seeds ${explore.seeds.size} · shown ${R.nodes.length}/${G.nodes.length}<br>
depth <button class="mb" data-ea="d-">−</button>${explore.depth}`+
`<button class="mb" data-ea="d+">+</button>
cap <button class="mb" data-ea="c-">−</button>${explore.cap}`+
`<button class="mb" data-ea="c+">+</button><br>
<button class="mb" data-ea="exp">expand sel (x)</button>
<button class="mb" data-ea="re">reseed sel</button>`}
else if(mode==='overview'){
h=`${clusters?clusters.length:0} clusters — dbl-click a cluster to drill in`}
else{h=`budget <button class="mb" data-ea="b-">−</button>${FULL_BUDGET}`+
`<button class="mb" data-ea="b+">+</button>
<br>shown ${R.nodes.length}/${G.nodes.length}`}
e.innerHTML=h;
e.querySelectorAll('button').forEach(b=>b.onclick=()=>{const a=b.dataset.ea;
if(a==='exp'&&sel&&!sel.cluster){expandNode(sel.id);return}
if(a==='re'&&sel&&!sel.cluster){explore.seeds=new Set([sel.id]);explore.extra=new Set()}
else if(a==='d-')explore.depth=Math.max(1,explore.depth-1);
else if(a==='d+')explore.depth=Math.min(5,explore.depth+1);
else if(a==='c-')explore.cap=Math.max(1,explore.cap-5);
else if(a==='c+')explore.cap=Math.min(200,explore.cap+5);
else if(a==='b-')FULL_BUDGET=Math.max(500,FULL_BUDGET-5000);
else if(a==='b+')FULL_BUDGET=Math.min(50000,FULL_BUDGET+5000);
savePrefs();buildRender();explPanel();fitToView();reheat(0.4);draw()})}
function commsPanel(){const e=document.getElementById('comms');if(!e)return;
if(!clusters){e.innerHTML='<span class="dim">— overview computes them</span>';return}
const top=clusters.slice().sort((a,b)=>(b.size-a.size)||(a.id<b.id?-1:1)).slice(0,8);
e.innerHTML=`${clusters.length} communities<br>`+
top.map(c=>`<a class="nlink" data-c="${c.id}">${esc(c.id)}·${c.size}</a>`).join(' ');
e.querySelectorAll('a').forEach(a=>a.onclick=()=>{
const c=clusters.find(x=>x.id===a.dataset.c);if(!c)return;
if(mode!=='overview')setMode('overview');sel=c;centerOn(c);inspect();draw()})}
function renderCrumbs(){const c=document.getElementById('crumbs');if(!c)return;
if(!crumbs.length){c.innerHTML=`<span class="dim">${esc(mode)}</span>`;return}
c.innerHTML=crumbs.map((k,i)=>`<a class="nlink" data-ci="${i}">${esc(k.label)}</a>`).join(' › ');
c.querySelectorAll('a').forEach(a=>a.onclick=()=>crumbGo(+a.dataset.ci))}
function pushCrumb(label,act){if(!crumbs.length)crumbs=[{label:mode,act:{m:mode}}];
crumbs.push({label,act});renderCrumbs()}
function crumbGo(i){const a=crumbs[i]&&crumbs[i].act;if(!a)return;
crumbs=crumbs.slice(0,i+1);
if(a.m==='explore'){explore.seeds=new Set(a.seeds||[]);
explore.depth=a.depth||1;explore.extra=new Set()}
setMode(a.m,true)}
// lf-0022 Overview rollup — deterministic clustering, same input → same
// clusters: connected components (BFS in node order) → synchronous label
// propagation inside components > COMP_LPA (tie → lowest label index) →
// while more than CLUST_MAX the smallest cluster merges into its edge-most-
// connected neighbour, or into a shared "rest" bucket when isolated.
function computeClusters(){
const n=G.nodes.length,idx=new Map(G.nodes.map((x,i)=>[x.id,i])),
comp=new Array(n).fill(-1),comps=[];
G.nodes.forEach((nd,i)=>{if(comp[i]>=0)return;const ci=comps.length,members=[i],q=[i];
comp[i]=ci;
while(q.length){const u=q.pop();(G.adj.get(G.nodes[u].id)||[]).forEach(v=>{
const vi=idx.get(v);if(vi!==undefined&&comp[vi]<0){comp[vi]=ci;q.push(vi);members.push(vi)}})}
comps.push(members)});
const label=new Array(n);
comps.forEach(members=>{if(members.length<=COMP_LPA)return;
members.forEach(i=>label[i]=i);
for(let r=0;r<LPA_ROUNDS;r++){let changed=false;const next=label.slice();
members.forEach(i=>{const cnt=new Map();
(G.adj.get(G.nodes[i].id)||[]).forEach(v=>{const vi=idx.get(v);
if(comp[vi]===comp[i])cnt.set(label[vi],(cnt.get(label[vi])||0)+1)});
let best=label[i],bc=-1;
cnt.forEach((c,L)=>{if(c>bc||(c===bc&&L<best)){best=L;bc=c}});
if(best!==label[i]){next[i]=best;changed=true}});
members.forEach(i=>label[i]=next[i]);
if(!changed)break}});
const big=new Set();comps.forEach((m,ci)=>{if(m.length>COMP_LPA)big.add(ci)});
const groups=new Map();
G.nodes.forEach((nd,i)=>{const k=big.has(comp[i])?'l'+label[i]:'k'+comp[i];
let g=groups.get(k);if(!g){g=[];groups.set(k,g)}g.push(i)});
let list=[...groups.values()].map(mix=>{const hist={};
mix.forEach(i=>{const k=G.nodes[i].kind;hist[k]=(hist[k]||0)+1});
const tk=Object.keys(hist).sort((a,b)=>(hist[b]-hist[a])||(a<b?-1:1))[0];
return{mix,hist,kind:tk,size:mix.length,ix:mix[0]}});
list.sort((a,b)=>(a.ix-b.ix));
list.forEach((c,i)=>{c.id='cl'+i});
const assign=new Map();list.forEach(c=>c.mix.forEach(i=>assign.set(G.nodes[i].id,c)));
let rest=null;
while(list.length>CLUST_MAX){
list.sort((a,b)=>(a.size-b.size)||(a.id<b.id?-1:1));
const s=list[0],tally=new Map();
s.mix.forEach(i=>{(G.adj.get(G.nodes[i].id)||[]).forEach(v=>{
const t=assign.get(v);if(t&&t!==s)tally.set(t,(tally.get(t)||0)+1)})});
let dst=null,bw=0;
tally.forEach((w,t)=>{if(w>bw||(w===bw&&dst&&t.id<dst.id)){bw=w;dst=t}});
if(!dst){if(!rest){rest={id:'crest',mix:[],hist:{},kind:'rest',size:0,ix:s.ix,rest:true};
list.push(rest)}dst=rest}
dst.mix=dst.mix.concat(s.mix);dst.size=dst.mix.length;dst.ix=Math.min(dst.ix,s.ix);
Object.keys(s.hist).forEach(k=>dst.hist[k]=(dst.hist[k]||0)+s.hist[k]);
dst.kind=Object.keys(dst.hist).sort((a,b)=>(dst.hist[b]-dst.hist[a])||(a<b?-1:1))[0];
s.mix.forEach(i=>assign.set(G.nodes[i].id,dst));
list.splice(list.indexOf(s),1)}
clusters=list.map(c=>{c.cluster=true;c.label=(c.rest?'small/isolated':c.kind)+' ×'+c.size;
c.x=0;c.y=0;c.vx=0;c.vy=0;c.deg=0;c.selfE=0;
c.members=c.mix.map(i=>G.nodes[i].id);return c});
// seeded positions — deterministic per graph + cluster id, stable across
// recompute and reload.
clusters.forEach(c=>{srand('pos:'+curId+':'+c.id);c.x=rand()*800-400;c.y=rand()*800-400});
srand('g:'+curId);
clusterMap=new Map();clusters.forEach(c=>c.mix.forEach(i=>clusterMap.set(G.nodes[i].id,c.id)));
const byCl=new Map(clusters.map(c=>[c.id,c])),ce=new Map();
G.edges.forEach(e=>{const A=assign.get(e.source),B=assign.get(e.target);
if(!A||!B)return;
if(A===B){A.selfE++;return}
const k=A.id<B.id?A.id+'|'+B.id:B.id+'|'+A.id;let a=ce.get(k);
if(!a){a={s:A.id,t:B.id,count:0,kinds:{}};ce.set(k,a)}
a.count++;a.kinds[e.kind]=(a.kinds[e.kind]||0)+1});
aggEdges=[...ce.entries()].sort((a,b)=>(a[0]<b[0]?-1:1)).map(([k,a],i)=>({
id:'ce'+i,source:a.s,target:a.t,
kind:Object.keys(a.kinds).sort((x,y)=>(a.kinds[y]-a.kinds[x])||(x<y?-1:1))[0],
weight:a.count,kinds:a.kinds,agg:true,epistemic_state:'inferred',
provenance:'cluster-rollup'}));
aggEdges.forEach(e=>{const a=byCl.get(e.source),b=byCl.get(e.target);
if(a)a.deg+=e.weight;if(b)b.deg+=e.weight})}
function qVal(){return (document.getElementById('q').value||'').toLowerCase()}
function matchQ(n){return ((n.label||'')+' '+n.id).toLowerCase().includes(qVal())}
function passNode(n){return kindsOn[n.kind]&&matchQ(n)&&(!focusSet||focusSet.has(n.id))}
// lf-0022 Explore: seeds + bounded progressive expansion — depth cap, per-node
// neighbour cap (first `cap` by -deg then id — deterministic), total bound
// EXPL_MAX with a visible notice.
function exploreSet(){const out=[],seen=new Set();
[...explore.seeds].sort().forEach(id=>{if(G.byId.has(id)&&!seen.has(id)){seen.add(id);out.push(id)}});
let fr=out.slice();
for(let d=0;d<explore.depth&&fr.length&&out.length<EXPL_MAX;d++){const nx=[];
fr.forEach(id=>{(G.adj.get(id)||[]).slice(0,explore.cap).forEach(m=>{
if(!seen.has(m)&&out.length<EXPL_MAX){seen.add(m);out.push(m);nx.push(m)}})});
fr=nx}
explore.extra.forEach(id=>{(G.adj.get(id)||[]).slice(0,explore.cap).forEach(m=>{
if(!seen.has(m)&&out.length<EXPL_MAX){seen.add(m);out.push(m)}})});
return out}
function buildRender(){
// canonical drawable index: real nodes; overview adds cluster ids so
// attract/pick/draw resolve every drawable through G.byId.
G.byId=new Map(G.nodes.map(n=>[n.id,n]));
const qv=qVal();setNotice('');
if(mode==='overview'){
if(!clusters)computeClusters();
clusters.forEach(c=>{c.vis=Object.keys(c.hist).some(k=>kindsOn[k]);
if(c.vis&&(qv||focusSet))c.vis=c.mix.some(i=>{const n=G.nodes[i];
return(!qv||((n.label||'')+' '+n.id).toLowerCase().includes(qv))&&
(!focusSet||focusSet.has(n.id))});
if(c.vis)G.byId.set(c.id,c)});
R.nodes=clusters.filter(c=>c.vis);R.edges=aggEdges}
else if(mode==='explore'){
let ids=exploreSet();
if(ids.length>EXPL_MAX){ids=ids.slice(0,EXPL_MAX);
setNotice(`explore capped at ${EXPL_MAX} nodes — narrow seeds/depth/cap`)}
R.nodes=ids.map(id=>G.byId.get(id)).filter(passNode);
const inR=new Set(R.nodes.map(n=>n.id));
R.edges=G.edges.filter(e=>inR.has(e.source)&&inR.has(e.target))}
else{
const all=G.nodes.filter(passNode);
const ids=all.slice(0,FULL_BUDGET).map(n=>n.id),inR=new Set(ids);
R.nodes=ids.map(id=>G.byId.get(id));
const ein=G.edges.filter(e=>inR.has(e.source)&&inR.has(e.target)&&ekindsOn[e.kind]);
const eb=Math.max(0,FULL_BUDGET*3-R.nodes.length);
R.edges=ein.slice(0,eb);
if(all.length>R.nodes.length||ein.length>R.edges.length)
setNotice(`Truncated — showing ${R.nodes.length}/${all.length} nodes, `+
`${R.edges.length}/${ein.length} edges · refine filters/search`)}
R.byId=new Map(R.nodes.map(n=>[n.id,n]))}
function setMode(m,keep){mode=m;
const ms=document.getElementById('mode');if(ms)ms.value=m;
if(m==='explore'&&!explore.seeds.size){const t=topDegId();if(t)explore.seeds=new Set([t])}
if(!keep)crumbs=[{label:m,act:{m}}];
buildRender();explPanel();commsPanel();renderCrumbs();savePrefs();fitToView();reheat(0.5);inspect();draw()}
function expandNode(id){if(!G.byId.has(id))return;
if(mode!=='explore'){ // crumb base must record where we came FROM
pushCrumb(id,{m:'explore',seeds:[id],depth:1});
explore.seeds=new Set([id]);explore.depth=1;mode='explore';
const ms=document.getElementById('mode');if(ms)ms.value=mode}
else{explore.extra.add(id);
pushCrumb(id,{m:'explore',seeds:[...explore.seeds],depth:explore.depth})}
buildRender();explPanel();savePrefs();reheat(0.3);draw()}
function drill(c){const ids=c.mix.slice().sort((a,b)=>{
const da=G.nodes[a].deg,db=G.nodes[b].deg;return db-da||(a-b)}).slice(0,DRILL_TOP)
.map(i=>G.nodes[i].id);
pushCrumb(c.id,{m:'explore',seeds:ids,depth:1}); // base crumb = overview, then this
mode='explore';
explore.seeds=new Set(ids);explore.depth=1;explore.extra=new Set();
const ms=document.getElementById('mode');if(ms)ms.value=mode;
buildRender();explPanel();savePrefs();fitToView();reheat(0.6);draw()}
// lf-0021: repulsion acts along the UNIT vector between a pair — the old code
// divided by the squared distance (dx/d with d=|dx|²), which is neither unit
// nor stable. Small graphs stay exact O(N²); large graphs aggregate far cells
// through a Barnes–Hut quadtree (O(N log N) instead of ~4,5M pairs at 3k).
// lf-0022: both paths are resumable — {i,j}/{bi,aj} cursors in `s` let a slice
// stop mid-phase (SIM_MS per frame) and continue next RAF with zero re-do.
function repulsePair(ns,s,deadline){let n=0;
for(;s.i<ns.length;s.i++,s.j=s.i+1)for(;s.j<ns.length;s.j++){
if(++n>=CHUNK){n=0;if(nowMs()>=deadline)return false}
const a=ns[s.i],b=ns[s.j];let dx=a.x-b.x,dy=a.y-b.y;
if(!dx&&!dy){dx=rand()-0.5;dy=rand()-0.5}
const dist=Math.hypot(dx,dy)||1e-9,f=Math.min(REP/(dist*dist+40),FCAP)*alpha;
a.vx+=dx/dist*f;a.vy+=dy/dist*f;b.vx-=dx/dist*f;b.vy-=dy/dist*f}
return true}
const mkc=(x,y,s)=>({x,y,s,sx:0,sy:0,c:0,k:null,n:null});
const bq=(c,a)=>(a.x>=c.x+c.s/2?1:0)|(a.y>=c.y+c.s/2?2:0);
function bhIns(c,a){c.sx+=a.x;c.sy+=a.y;c.c++;
if(c.s<=1e-4){c.n=a;return}
if(!c.k){
if(c.n){const o=c.n;c.n=null;
c.k=[mkc(c.x,c.y,c.s/2),mkc(c.x+c.s/2,c.y,c.s/2),
mkc(c.x,c.y+c.s/2,c.s/2),mkc(c.x+c.s/2,c.y+c.s/2,c.s/2)];
bhIns(c.k[bq(c,o)],o)}
else{c.n=a;return}}
bhIns(c.k[bq(c,a)],a)}
function bhApply(c,a){if(!c.c)return;
if(!c.k&&c.n===a)return;
let dx=a.x-c.sx/c.c,dy=a.y-c.sy/c.c;
if(!dx&&!dy){dx=rand()-0.5;dy=rand()-0.5}
const dist=Math.hypot(dx,dy)||1e-9;
if(c.k&&c.s/dist>THETA){for(const k of c.k)bhApply(k,a);return}
const f=Math.min(REP/(dist*dist+40),FCAP)*c.c*alpha;
a.vx+=dx/dist*f;a.vy+=dy/dist*f}
function repulseBH(ns,s,deadline){
if(!s.bh){let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
for(const a of ns){if(a.x<x0)x0=a.x;if(a.x>x1)x1=a.x;if(a.y<y0)y0=a.y;if(a.y>y1)y1=a.y}
s.bh=mkc(x0,y0,Math.max(x1-x0,y1-y0,1));s.bi=0;s.aj=0}
let n=0;
for(;s.bi<ns.length;s.bi++){
if(++n>=CHUNK){n=0;if(nowMs()>=deadline)return false}
bhIns(s.bh,ns[s.bi])}
for(;s.aj<ns.length;s.aj++){
if(++n>=CHUNK){n=0;if(nowMs()>=deadline)return false}
bhApply(s.bh,ns[s.aj])}
return true}
// lf-0021: linear spring — the old kick scaled the unit vector by the spring
// force AND by d/120, i.e. ≈dx·(d-120)/6000 — quadratic in distance, and it
// diverged to Infinity in <10 ticks on hub topologies.
function attract(s,deadline){const E=R.edges;let n=0;
for(;s.ei<E.length;s.ei++){
if(++n>=CHUNK){n=0;if(nowMs()>=deadline)return false}
const e=E[s.ei],a=G.byId.get(e.source),b=G.byId.get(e.target);
if(!a||!b)continue;
const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1e-9,
f=(d-LINK_D)*SPRING_K*alpha;
a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f}
return true}
// lf-0022: one logical tick is a resumable state machine — live filter →
// repulsion → springs → integrate — each phase chunked at CHUNK ops so a
// frame never exceeds ~SIM_MS of force work (UI stays responsive).
function stepSlice(s,deadline){const N=R.nodes;
if(s.phase==='live'){
const e=Math.min(s.i+CHUNK,N.length);
for(;s.i<e;s.i++){const a=N[s.i];
if([a.x,a.y,a.vx,a.vy].every(Number.isFinite))s.live.push(a);
else{a.x=rand()*600-300;a.y=rand()*600-300;a.vx=0;a.vy=0;resets++}}
if(s.i>=N.length){s.phase='rep';s.i=0;s.j=1;s.bh=null;s.bi=0;s.aj=0;s.ei=0}
return false}
if(s.phase==='rep'){
if(s.live.length>BH_N){if(repulseBH(s.live,s,deadline))s.phase='att'}
else if(repulsePair(s.live,s,deadline))s.phase='att'
return false}
if(s.phase==='att'){if(attract(s,deadline)){s.phase='int';s.i=0}return false}
const e=Math.min(s.i+CHUNK,N.length);
for(;s.i<e;s.i++){const a=N[s.i];
a.vx-=a.x*GRAVITY*alpha;a.vy-=a.y*GRAVITY*alpha;
a.vx*=DAMP;a.vy*=DAMP;
const sp=Math.hypot(a.vx,a.vy);
if(sp>SPMAX){a.vx*=SPMAX/sp;a.vy*=SPMAX/sp}
a.x+=a.vx;a.y+=a.vy;
if(![a.x,a.y,a.vx,a.vy].every(Number.isFinite)){
a.x=rand()*600-300;a.y=rand()*600-300;a.vx=0;a.vy=0;resets++}
if(Math.abs(a.vx)+Math.abs(a.vy)>0.1)s.moving++}
return s.i>=N.length}
// rough op estimate of one logical tick — decides whether it runs whole in
// this frame (small: cheap either way) or yields mid-phase at the deadline.
function tickEst(){const N=R.nodes.length,E=R.edges.length;
return (N>BH_N?N*14*Math.log2(N+2):N*N/2)+E+N}
function tick(g){if(g!==gen||!running)return;try{
// a node mutated mid-tick (poisoned state, an in-flight drag) re-enters here —
// re-validate the live snapshot before forces resume, so one bad node can
// never smear NaN across its partners inside a suspended tick.
if(simPos&&simPos.live)for(const a of simPos.live){
if(![a.x,a.y,a.vx,a.vy].every(Number.isFinite)){
a.x=rand()*600-300;a.y=rand()*600-300;a.vx=0;a.vy=0;resets++}}
const deadline=nowMs()+SIM_MS;
let guard=0,stop=false;
while(guard++<400){
if(!simPos)simPos={phase:'live',i:0,j:1,live:[],moving:0,bh:null,bi:0,aj:0,ei:0,
small:tickEst()<=TICK_SMALL};
if(stepSlice(simPos,simPos.small?Infinity:deadline)){ // logical tick done
const moving=simPos.moving;simPos=null;lticks++;
if(moving>0&&alpha>ALPHA_MIN){alpha*=ALPHA_DECAY}
else{settled=true;stop=true;break}}
if(nowMs()>=deadline)break}
draw();
if(!stop)rafId=requestAnimationFrame(()=>{rafId=0;tick(g)})}
catch(e){running=false;showErr('layout stopped: '+(e&&e.message||e))}}
// lf-0022: re-enter the sim after the render set changed — positions persist
// (same node objects), so a low alpha re-settles instead of restarting.
function reheat(a){if(!R.nodes.length)return;
running=true;settled=false;simPos=null;alpha=Math.max(alpha,a||0.4);
if(!rafId)rafId=requestAnimationFrame(()=>{rafId=0;tick(gen)})}
// lf-0021: fit the camera to the finite-node bounding box (initial view,
// Escape reset, window resize, search hits). Zoom stays inside [SMIN,SMAX].
function fitToNodes(ns){const r=cv.getBoundingClientRect();
let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,c=0;
ns.forEach(n=>{if(!Number.isFinite(n.x)||!Number.isFinite(n.y))return;
if(n.x<x0)x0=n.x;if(n.x>x1)x1=n.x;if(n.y<y0)y0=n.y;if(n.y>y1)y1=n.y;c++});
if(!c){view={x:0,y:0,s:1};return}
const bw=Math.max(x1-x0,1),bh=Math.max(y1-y0,1);
view.s=Math.min(SMAX,Math.max(SMIN,Math.min(r.width/bw,r.height/bh)*0.9));
view.x=-((x0+x1)/2)*view.s;view.y=-((y0+y1)/2)*view.s}
function fitToView(){fitToNodes(R.nodes)}
function centerOn(n){view.x=-n.x*view.s;view.y=-n.y*view.s}
function zoomC(f){const ns=Math.min(SMAX,Math.max(SMIN,view.s*f)),
g=view.s?ns/view.s:1;view.x*=g;view.y*=g;view.s=ns;draw()}
if(typeof window!=='undefined')window.onresize=()=>{fitToView();draw()};
function toS(x,y){const r=cv.getBoundingClientRect();
return[(x*view.s)+r.width/2+view.x,(y*view.s)+r.height/2+view.y]}
function nrad(n){return n.cluster?Math.min(5+Math.sqrt(n.size)*1.8,30):4+Math.min(n.deg,12)}
// lf-0022 tiered rendering — auto by dataset size, overridable via lod:
// · labels only when zoomed in (view.s≥0.6) or ≤LABEL_MAX visible nodes
// · edges batched per dash-style into one stroke; arrowheads skipped past
//   ARROW_MAX drawn segments
// · eligible edges past EDGE_DRAW_MAX (auto) get a deterministic k-stride
//   decimation — the footer always reports "drawn of eligible" (no silent drop)
function edgeStride(eligible){if(lod==='fine')return 1;
const lim=lod==='coarse'?3000:EDGE_DRAW_MAX;
return eligible>lim?Math.ceil(eligible/lim):1}
function draw(){const r=cv.getBoundingClientRect();
// realloc only on an integer change — comparing against a fractional
// r.width*devicePixelRatio re-allocated the canvas every frame.
const cw=Math.round(r.width*devicePixelRatio),ch=Math.round(r.height*devicePixelRatio);
if(cv.width!==cw||cv.height!==ch){cv.width=cw;cv.height=ch}
cx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
cx.clearRect(0,0,r.width,r.height);
const eok=e=>e.kinds?Object.keys(e.kinds).some(k=>ekindsOn[k]):ekindsOn[e.kind];
const E=R.edges;let eligible=0;
E.forEach(e=>{if(eok(e))eligible++});
const stride=edgeStride(eligible);
const buckets={},segs=[];let drawn=0;
for(let i=0;i<E.length;i++){const e=E[i];if(!eok(e))continue;
const special=e===sel||(pathEdges&&pathEdges.has(e));
if(stride>1&&i%stride&&!special)continue;
const a=G.byId.get(e.source),b=G.byId.get(e.target);if(!a||!b)continue;
if(![a.x,a.y,b.x,b.y].every(Number.isFinite))continue;
const[x1,y1]=toS(a.x,a.y),[x2,y2]=toS(b.x,b.y);
drawn++;segs.push([x1,y1,x2,y2,e]);
if(special)continue;
const k=e.epistemic_state||'unknown';(buckets[k]=buckets[k]||[]).push([x1,y1,x2,y2])}
for(const k in buckets){cx.strokeStyle='#444c56';cx.lineWidth=1;
cx.setLineDash(ESTYLE[k]||ESTYLE.unknown);cx.beginPath();
buckets[k].forEach(s=>{cx.moveTo(s[0],s[1]);cx.lineTo(s[2],s[3])});cx.stroke()}
cx.setLineDash([]);
if(segs.length<=ARROW_MAX)segs.forEach(s=>{
const an=Math.atan2(s[3]-s[1],s[2]-s[0]);cx.beginPath();cx.fillStyle='#444c56';
cx.moveTo(s[2],s[3]);cx.lineTo(s[2]-8*Math.cos(an-0.5),s[3]-8*Math.sin(an-0.5));
cx.lineTo(s[2]-8*Math.cos(an+0.5),s[3]-8*Math.sin(an+0.5));cx.fill()});
segs.forEach(s=>{const e=s[4];if(!(e===sel||(pathEdges&&pathEdges.has(e))))return;
cx.strokeStyle=e===sel?'#f0f6fc':'#7ee787';cx.lineWidth=2;cx.setLineDash([]);
cx.beginPath();cx.moveTo(s[0],s[1]);cx.lineTo(s[2],s[3]);cx.stroke()});
const vc=R.nodes.length,doLabels=view.s>=0.6||vc<=LABEL_MAX;
let labels=0;
R.nodes.forEach(n=>{if(![n.x,n.y].every(Number.isFinite))return;
const[x,y]=toS(n.x,n.y),rad=nrad(n);
cx.beginPath();cx.arc(x,y,rad,0,7);
const dcol=drawDiffColors&&DC[drawDiffColors[n.id]];
cx.fillStyle=n===sel?'#f0f6fc':(n===hover?'#fff':(dcol||pal(n.kind)));cx.fill();
if(n.cluster){cx.strokeStyle='#8b949e';cx.lineWidth=1;cx.stroke();
if(rad>11){cx.fillStyle='#0d1117';cx.font='9px monospace';
cx.fillText(n.size>999?(n.size/1000).toFixed(1)+'k':n.size,x-8,y+3);labels++}}
if(n===sel){cx.strokeStyle='#58a6ff';cx.lineWidth=2;cx.stroke()}
if(pathHi&&pathHi.has(n.id)){cx.strokeStyle='#7ee787';cx.lineWidth=2;cx.stroke()}
if(blastHi&&blastHi.has(n.id)){cx.strokeStyle='#ffa657';cx.lineWidth=1.5;cx.stroke()}
if(searchHits&&searchHits.has(n.id)){cx.strokeStyle='#e3b341';cx.lineWidth=2;cx.stroke()}
if(doLabels||n===sel||n===hover||n.deg>6){cx.fillStyle='#8b949e';cx.font='10px monospace';
cx.fillText((n.label||n.id).slice(0,24),x+rad+2,y+3);labels++}});
drawMeta.nodes=vc;drawMeta.edgesOk=eligible;drawMeta.edges=drawn;drawMeta.labels=labels;
document.getElementById('stats').textContent=
`${mode} · ${vc} nodes · ${eligible} edges · ${drawn} drawn`+
(stride>1?` (dec ×${stride})`:'')+(resets?` · ${resets} resets`:'')+
(searchHits?` · ${searchHits.size} hits`:'');
drawMini()}
// lf-0022 minimap — decimated dots + viewport rect; click centres the camera.
function drawMini(){const mm=document.getElementById('mmap');
if(!mm||typeof mm.getContext!=='function')return;const mc=mm.getContext('2d');if(!mc)return;
const W=mm.width,H=mm.height;mc.clearRect(0,0,W,H);
let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,c=0;
R.nodes.forEach(n=>{if(!Number.isFinite(n.x)||!Number.isFinite(n.y))return;
if(n.x<x0)x0=n.x;if(n.x>x1)x1=n.x;if(n.y<y0)y0=n.y;if(n.y>y1)y1=n.y;c++});
lastMini=null;if(!c)return;
const k=Math.min(W/Math.max(x1-x0,1),H/Math.max(y1-y0,1))*0.9,
ox=(W-(x1-x0)*k)/2-x0*k,oy=(H-(y1-y0)*k)/2-y0*k;
lastMini={k,ox,oy};
const st=Math.max(1,Math.ceil(R.nodes.length/1500));mc.fillStyle='#8b949e';
R.nodes.forEach((n,i)=>{if(i%st||!Number.isFinite(n.x))return;
mc.fillRect(n.x*k+ox,n.y*k+oy,1.6,1.6)});
const r=cv.getBoundingClientRect(),
wx0=(-r.width/2-view.x)/view.s,wy0=(-r.height/2-view.y)/view.s;
mc.strokeStyle='#58a6ff';
mc.strokeRect(wx0*k+ox,wy0*k+oy,(r.width/view.s)*k,(r.height/view.s)*k)}
const mmap=document.getElementById('mmap');
if(mmap)mmap.onmousedown=e=>{if(!lastMini)return;const r=mmap.getBoundingClientRect();
const wx=(e.clientX-r.left-lastMini.ox)/lastMini.k,
wy=(e.clientY-r.top-lastMini.oy)/lastMini.k;
view.x=-wx*view.s;view.y=-wy*view.s;draw()};
cv.onwheel=e=>{e.preventDefault();const r=cv.getBoundingClientRect();
const mx=e.clientX-r.left-r.width/2,my=e.clientY-r.top-r.height/2;
const f=e.deltaY<0?1.15:0.87,
ns=Math.min(SMAX,Math.max(SMIN,view.s*f)),g=view.s?ns/view.s:1;
view.x=(view.x-mx)*g+mx;view.y=(view.y-my)*g+my;view.s=ns;draw()};
let drag=null;cv.onmousedown=e=>{const p=pick(e);drag={e,node:p.node,mx:view.x,my:view.y}};
cv.onmousemove=e=>{if(drag){const r=cv.getBoundingClientRect();
if(drag.node){drag.node.x=(e.clientX-r.left-r.width/2-view.x)/view.s;
drag.node.y=(e.clientY-r.top-r.height/2-view.y)/view.s}else{
view.x=drag.mx+e.clientX-drag.e.clientX;view.y=drag.my+e.clientY-drag.e.clientY}
draw()}else{const p=pick(e);hover=p.node;draw()}};
cv.onmouseup=e=>{const p=pick(e);
if(!drag||(Math.abs(e.clientX-drag.e.clientX)<4&&Math.abs(e.clientY-drag.e.clientY)<4)){
sel=p.node||p.edge||null;neiShow=NEI_CAP;inspect()}
drag=null;draw()};
cv.ondblclick=e=>{const p=pick(e);
if(p.node&&p.node.cluster)drill(p.node);
else if(p.node)expandNode(p.node.id)};
function pick(e){const r=cv.getBoundingClientRect();
const wx=(e.clientX-r.left-r.width/2-view.x)/view.s,
wy=(e.clientY-r.top-r.height/2-view.y)/view.s;
for(let i=R.nodes.length-1;i>=0;i--){const n=R.nodes[i];
if(Math.hypot(n.x-wx,n.y-wy)<nrad(n)/view.s+6/view.s+2)return{node:n}}
for(const ed of R.edges){const a=G.byId.get(ed.source),
b=G.byId.get(ed.target);if(!a||!b)continue;
const L2=(b.x-a.x)**2+(b.y-a.y)**2||1;
const t=Math.max(0,Math.min(1,((wx-a.x)*(b.x-a.x)+(wy-a.y)*(b.y-a.y))/L2));
if(Math.hypot(wx-(a.x+t*(b.x-a.x)),wy-(a.y+t*(b.y-a.y)))<6/view.s)return{edge:ed}}
return{}}
// ---- lf-0022 inspector: node / cluster / edge / aggregate + actions ---------
function inspect(){const b=document.getElementById('ibody');if(!sel){
b.innerHTML='<span class="dim">select a node or edge</span>';return}
let h='<button class="mb" data-act="x" style="float:right">×</button>';
if(sel.cluster){const c=sel;
h+=`<div class="k"><b>${esc(c.id)}</b> <span class="pill">cluster ×${c.size}</span></div>
<h4>Kinds</h4>${Object.entries(c.hist).sort((a,b)=>b[1]-a[1])
.map(([k,v])=>`<span class="pill" style="color:${pal(k)}">${esc(k)} ${v}</span>`).join('')}
<div class="dim">${c.selfE||0} internal edges collapsed</div>
<h4>Members</h4>${c.members.slice(0,12)
.map(id=>`<a class="nlink" data-nid="${esc(id)}">${esc(id)}</a>`).join(' ')}${c.size>12?' …':''}
<h4>Actions</h4><button class="mb" data-act="drill">drill in (explore)</button>`}
else if(sel.source===undefined){const n=sel,
nbs=G.adj.get(n.id)||[],outd=(G.out.get(n.id)||[]).length;
h+=`<div class="k"><b>${esc(n.label||n.id)}</b></div>
<div class="k dim">${esc(n.id)}</div>
<span class="pill">${esc(n.kind)}</span><span class="pill">${esc(n.epistemic_state)}</span>
<span class="pill">${esc(n.source_provider||'')}</span>
<div class="dim">deg ${n.deg} (out ${outd} · in ${n.deg-outd})</div>
<h4>Attributes</h4><div class="k">${esc(JSON.stringify(n.attributes||{}))}</div>
<h4>Evidence</h4>${(n.evidence_refs||[]).map(e=>`<div class="ev">${esc(e)}</div>`)
.join('')||'<span class="dim">none</span>'}
<h4>Neighbors (${nbs.length})</h4>${nbs.slice(0,neiShow)
.map(id=>`<a class="nlink" data-nid="${esc(id)}">${esc(id)}</a>`).join(' ')}
${nbs.length>neiShow?`<a class="nlink" data-act="more">more +${NEI_CAP}`+
` (${nbs.length-neiShow} left)</a>`:''}
<h4>Actions</h4><button class="mb" data-act="pa">path A</button>
<button class="mb" data-act="pb">path B</button>
<button class="mb" data-act="blast">blast</button>
<button class="mb" data-act="foc">focus nbhd</button>
<button class="mb" data-act="exp">explore here</button>`}
else{const e=sel;
if(e.agg){h+=`<div class="k"><b>aggregated ×${e.weight}</b></div>
<div class="k dim">${esc(e.source)} → ${esc(e.target)}</div>
<span class="pill">top: ${esc(e.kind)}</span><span class="pill">${esc(e.provenance)}</span>
<h4>Kinds</h4>${Object.entries(e.kinds)
.map(([k,v])=>`<span class="pill">${esc(k)} ${v}</span>`).join('')}`}
else{h+=`<div class="k"><b>${esc(e.kind)}</b></div>
<div class="k dim">${esc(e.source)} → ${esc(e.target)}</div>
<span class="pill">${esc(e.epistemic_state)}</span>`+
`<span class="pill">${esc(e.provenance||'')}</span>
${e.confidence!=null?`<span class="pill">conf ${e.confidence}</span>`:''}
<h4>Attributes</h4><div class="k">${esc(JSON.stringify(e.attributes||{}))}</div>
<h4>Evidence</h4>${(e.evidence_refs||[]).map(x=>`<div class="ev">${esc(x)}</div>`)
.join('')||'<span class="dim">none</span>'}
<h4>Temporal</h4><div class="k">${Object.keys(e.temporal||{}).length?
esc(JSON.stringify(e.temporal)):'none'}</div>`}}
if(blastInfo)h+=`<h4>Blast</h4><div class="dim">${esc(blastInfo.seed)}: `+
`${blastInfo.size} reachable ≤${blastInfo.depth} hops</div>`+
`<button class="mb" data-act="blf">filter to blast</button>`;
if(focusSet)h+=`<div><button class="mb" data-act="unf">`+
`clear focus (${focusSet.size})</button></div>`;
b.innerHTML=h;
wireInsp(b)}
function wireInsp(b){
b.querySelectorAll('[data-nid]').forEach(a=>a.onclick=()=>{
const n=G.byId.get(a.dataset.nid);if(n){sel=n;neiShow=NEI_CAP;inspect();draw()}});
b.querySelectorAll('[data-act]').forEach(x=>x.onclick=()=>{const a=x.dataset.act;
if(a==='x'){sel=null;neiShow=NEI_CAP}
else if(a==='more'){neiShow+=NEI_CAP}
else if(a==='drill'&&sel&&sel.cluster){drill(sel);return}
else if(a==='pa'&&sel){pathA=sel.id;if(pathB)runPath()}
else if(a==='pb'&&sel){pathB=sel.id;if(pathA)runPath()}
else if(a==='blast'&&sel){blast(sel.id)}
else if(a==='foc'&&sel){focusSet=neighbors(sel.id);buildRender();reheat(0.3)}
else if(a==='blf'&&blastHi){focusSet=new Set(blastHi);buildRender();reheat(0.3)}
else if(a==='unf'){focusSet=null;buildRender();reheat(0.3)}
else if(a==='exp'&&sel){expandNode(sel.id);return}
inspect();draw()})}
// ---- lf-0022 navigation: search, analysis -----------------------------------
const qi=document.getElementById('q');let qT=0;
qi.oninput=()=>{searchHits=null;
if(typeof setTimeout==='function'){clearTimeout(qT);
qT=setTimeout(()=>{buildRender();reheat(0.2);draw()},150)}
else{buildRender();reheat(0.2);draw()}};
qi.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();runSearch()}
else if(e.key==='Escape'){e.preventDefault();qi.value='';runSearch()}};
// Enter: every match highlighted and the camera framed on the result set.
function runSearch(){buildRender();const qv=qVal();searchHits=null;
if(qv){const total=G.nodes.filter(matchQ).length;
searchHits=new Set(R.nodes.map(n=>n.id));
document.getElementById('prov').textContent=
`${searchHits.size} shown of ${total} matches`;
if(searchHits.size)fitToNodes(R.nodes);else setNotice(`no matches for "${qv}"`)}
draw()}
function neighbors(seed){const seen=new Set([seed]);let fr=[seed];
for(let d=0;d<2&&fr.length;d++){const nx=[];fr.forEach(id=>{
(G.adj.get(id)||[]).forEach(m=>{if(!seen.has(m)){seen.add(m);nx.push(m)}})});fr=nx}
return seen}
// lf-0022 analysis — all bounded; a newer request supersedes (jobSeq) and a
// miss reports the bound instead of hanging or lying.
function shortestPath(a,b){if(a===b)return[a];
const prev=new Map([[a,null]]);let fr=[a],d=0;
while(fr.length&&d<PATH_MAX_DEPTH&&!prev.has(b)){const nx=[];
for(const u of fr){for(const v of (G.adj.get(u)||[])){
if(!prev.has(v)){prev.set(v,u);nx.push(v)}}}
fr=nx;d++}
if(!prev.has(b))return null;
const p=[];for(let c=b;c;c=prev.get(c))p.push(c);return p.reverse()}
function runPath(){jobSeq++;const j=jobSeq;pathHi=null;pathEdges=null;
if(!pathA||!pathB){inspect();draw();return}
const p=shortestPath(pathA,pathB);
if(j!==jobSeq)return;
if(!p){document.getElementById('prov').textContent=
`no path ≤${PATH_MAX_DEPTH} hops ${pathA}→${pathB}`;inspect();draw();return}
pathHi=new Set(p);
const pos=new Map(p.map((id,i)=>[id,i]));pathEdges=new Set();
G.edges.forEach(e=>{const i=pos.get(e.source),k=pos.get(e.target);
if(i!==undefined&&k!==undefined&&Math.abs(i-k)===1)pathEdges.add(e)});
document.getElementById('prov').textContent=
`path ${pathA} → ${pathB}: ${p.length} nodes`;inspect();draw()}
function blast(id){jobSeq++;const j=jobSeq;
const out=new Set([id]);let fr=[id],d=0;
while(fr.length&&d<6&&out.size<BLAST_CAP){const nx=[];
for(const u of fr){for(const v of (G.out.get(u)||[])){
if(!out.has(v)){out.add(v);nx.push(v);if(out.size>=BLAST_CAP)break}}
if(out.size>=BLAST_CAP)break}
fr=nx;d++}
if(j!==jobSeq)return;
blastHi=out;blastInfo={seed:id,size:out.size,depth:d};
document.getElementById('prov').textContent=
`blast ${id}: ${out.size} reachable ≤${d} hops`;inspect();draw()}
// --- premium interactions (Cycle 4): export / diff / snapshot ---
async function exportVisible(){let vids;
if(mode==='overview'){vids=new Set();R.nodes.forEach(c=>c.members.forEach(id=>vids.add(id)))}
else vids=new Set(R.nodes.map(n=>n.id));
const doc={exported_at:new Date().toISOString(),mode,
nodes:G.nodes.filter(n=>vids.has(n.id)).map(n=>({id:n.id,kind:n.kind,label:n.label,
epistemic_state:n.epistemic_state,attributes:n.attributes,evidence_refs:n.evidence_refs})),
edges:G.edges.filter(e=>vids.has(e.source)&&vids.has(e.target)&&ekindsOn[e.kind])};
const a=document.createElement('a');a.href=URL.createObjectURL(
new Blob([JSON.stringify(doc,null,1)],{type:'application/json'}));
a.download='forge-graph-subgraph.json';a.click()}
async function diffMode(){try{const r=await fetch('/api/graphs');const d=await r.json();
if(d.graphs.length<2){document.getElementById('prov').textContent=
'diff needs ≥2 graphs loaded';return}
const other=d.graphs.map(g=>g.graph_id).find(id=>id!==curId)||d.graphs[0].graph_id;
const rr=await fetch('/api/graph/'+encodeURIComponent(other));const o=await rr.json();
const on={};(o.nodes||[]).forEach(n=>on[n.id]=n);
const oe={};(o.edges||[]).forEach(e=>oe[e.source+'>'+e.target+':'+e.kind]=1);
const eadded=G.edges.filter(e=>!oe[e.source+'>'+e.target+':'+e.kind]).length;
let added=0,removed=0,changed=0;const cls={};
G.nodes.forEach(n=>{if(!on[n.id]){cls[n.id]='added';added++}else if(
JSON.stringify(on[n.id].attributes)!==JSON.stringify(n.attributes)||
on[n.id].epistemic_state!==n.epistemic_state){cls[n.id]='changed';changed++}else cls[n.id]='same'});
removed=(o.nodes||[]).filter(n=>!G.byId.has(n.id)).length;
diffRef={other,cls};
drawDiffColors=cls;
document.getElementById('prov').textContent=
`diff vs ${other}: +${added} ~${changed} −${removed} nodes · +${eadded} edges (esc clears)`;
draw()}catch(e){showErr('diff failed: '+e)}}
const DC={added:'#7ee787',removed:'#f78166',changed:'#ffa657',same:null};
function snapshotSave(){try{localStorage.setItem('forge-graph-snap',
JSON.stringify({graph:curId,view,q:document.getElementById('q').value,
kinds:kindsOn,ekinds:ekindsOn,mode,lod,depth:explore.depth,cap:explore.cap,when:Date.now()}));
document.getElementById('prov').textContent='snapshot saved (s restores)'}catch(e){}}
function snapshotLoad(){try{const s=JSON.parse(localStorage.getItem('forge-graph-snap')||'null');
if(!s)return;view=s.view;document.getElementById('q').value=s.q||'';
Object.assign(kindsOn,s.kinds||{});Object.assign(ekindsOn,s.ekinds||{});
if(s.depth)explore.depth=s.depth;if(s.cap)explore.cap=s.cap;
if(s.lod)lod=s.lod;if(s.mode&&s.mode!==mode){setMode(s.mode);return}
buildRender();draw()}catch(e){}}
document.getElementById('mode').onchange=e=>setMode(e.target.value);
document.getElementById('lod').onchange=e=>{lod=e.target.value;savePrefs();draw()};
document.onkeydown=e=>{
const tg=e.target&&e.target.tagName;
if(tg==='INPUT'||tg==='SELECT'||tg==='TEXTAREA'){
if(e.key==='Escape'&&e.target.blur)e.target.blur();return}
if(e.key==='Escape'){sel=null;focusSet=null;diffRef=null;drawDiffColors=null;
searchHits=null;pathHi=null;pathEdges=null;blastHi=null;blastInfo=null;neiShow=NEI_CAP;
setNotice('');buildRender();reheat(0.3);fitToView();inspect();draw()}
else if(e.key==='n'&&sel&&sel.id!==undefined&&!sel.cluster){
focusSet=focusSet?null:neighbors(sel.id);buildRender();reheat(0.3);inspect();draw()}
else if(e.key==='x'&&sel&&!sel.cluster)expandNode(sel.id)
else if(e.key==='e')exportVisible()
else if(e.key==='d')diffMode()
else if(e.key==='s'){localStorage.getItem('forge-graph-snap')?snapshotLoad():snapshotSave()}
else if(e.key==='f'){fitToView();draw()}
else if(e.key==='/'){e.preventDefault();qi.focus&&qi.focus()}
else if(e.key==='+'||e.key==='='){zoomC(1.2)}
else if(e.key==='-'||e.key==='_'){zoomC(0.84)}
else if(e.key==='p'&&sel&&!sel.cluster){
if(!pathA)pathA=sel.id;else if(!pathB)pathB=sel.id;runPath()}
else if(e.key==='m'){setMode(mode==='overview'?'explore':mode==='explore'?'full':'overview')}
else if(e.key==='ArrowLeft'){view.x+=80;draw()}
else if(e.key==='ArrowRight'){view.x-=80;draw()}
else if(e.key==='ArrowUp'){view.y+=80;draw()}
else if(e.key==='ArrowDown'){view.y-=80;draw()}};
loadGraphs();
</script></body></html>
"""


def _handler(views: dict[str, dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    class StudioHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, doc: object) -> None:
            self._send(code, json.dumps(doc, default=str).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path == "/":
                self._send(200, STUDIO_HTML.encode(), "text/html; charset=utf-8")
                return
            if path == "/api/health":
                self._json(200, {"status": "ok", "graphs": len(views)})
                return
            if path == "/api/graphs":
                self._json(200, {"graphs": [v["descriptor"] for v in views.values()]})
                return
            if path.startswith("/api/graph/"):
                gid = path[len("/api/graph/") :]
                view = views.get(gid)
                if view is None:
                    self._json(404, {"error": f"unknown graph {gid!r}"})
                    return
                self._json(200, view)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # read-only by design (§4.4)
            self._json(405, {"error": "Graph Studio is read-only"})

        do_PUT = do_DELETE = do_PATCH = do_POST

    return StudioHandler


def serve(
    views: list[dict[str, Any]],
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    out: Any = None,
) -> int:
    """Serve the studio until Ctrl+C. ``views`` are ForgeGraphView dicts.

    Binds loopback only — never exposes graphs on the network. With
    ``open_browser=False`` (``--no-browser``, remote/SSH) the URL is
    printed for port-forwarding instead.
    """
    out = out or __import__("sys").stdout
    by_id = {v["descriptor"]["graph_id"]: v for v in views}
    httpd = ThreadingHTTPServer((host, port), _handler(by_id))
    bound = httpd.server_address[1]
    url = f"http://{host}:{bound}/"
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
        print(f"Graph Studio → {url}  (Ctrl+C to stop)", file=out)
    else:
        print(f"Graph Studio listening on {url}", file=out)
        print(f"  remote? forward with: ssh -L {bound}:127.0.0.1:{bound} <host>", file=out)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def graph_studio_enabled(
    root: Path | str | None = None,
    *,
    state_rel: str = ".forge/install",
    user_state_rel: str = "~/.forge/install",
) -> bool:
    """Was Graph Studio declined at install time?

    ``components.json`` under the forge's state dir records the optional-
    component selection (``graph_studio: false``). Absence means the
    default — enabled — so checkouts and pre-component installs keep
    working.
    """
    import json

    candidates: list[Path] = []
    if root:
        candidates.append(Path(root) / state_rel / "components.json")
    candidates.append(Path(user_state_rel).expanduser() / "components.json")
    for p in candidates:
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "graph_studio" in doc:
            return bool(doc["graph_studio"])
    return True


def open_studio(
    views: list[Any],
    *,
    open_browser: bool = True,
    port: int = 0,
    out: Any = None,
) -> int:
    """Entry for ``graph ui``: accept views or view objects, then serve."""
    docs = [v.to_dict() if hasattr(v, "to_dict") else v for v in views]
    if not docs:
        print(
            "no graphs available — produce one first (see `graph build`/`graph` docs)",
            file=out,
        )
        return 2
    return serve(docs, open_browser=open_browser, port=port, out=out)
