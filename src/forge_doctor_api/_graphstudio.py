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
</style></head>
<body>
<header><b>FORGE GRAPH STUDIO</b>
<select id="gsel"></select>
<input id="q" placeholder="search…" size="20">
<span id="meta" class="dim"></span></header>
<div id="side"><h4>Layers</h4><div id="layers"></div>
<h4>Edge kinds</h4><div id="ekinds"></div>
<h4>Legend</h4><div id="legend" class="dim"></div></div>
<div id="wrap"><canvas id="cv"></canvas></div>
<div id="insp"><h4>Inspector</h4><div id="ibody" class="dim">select a node or edge</div></div>
<footer><span id="stats"></span><span id="prov"></span>
<span class="dim">scroll=zoom · drag=pan · click=inspect · n=neighbors ·
e=export · d=diff · s=snapshot · esc=reset</span></footer>
<script>
let G={nodes:[],edges:[]},L={},view={x:0,y:0,s:1},sel=null,hover=null,
kindsOn={},ekindsOn={},PAL={},running=true;
const cv=document.getElementById('cv'),cx=cv.getContext('2d');
const KCOLORS=['#58a6ff','#f78166','#7ee787','#ffa657','#d2a8ff','#76e3ea','#ff9bce','#e3b341'];
const ESTYLE={observed:[],declared:[6,3],inferred:[3,4],planned:[2,4],desired:[8,3],unknown:[1,5]};
function pal(k){if(!(k in PAL))PAL[k]=KCOLORS[Object.keys(PAL).length%KCOLORS.length];return PAL[k]}
async function loadGraphs(){const r=await fetch('/api/graphs');const d=await r.json();
const s=document.getElementById('gsel');s.innerHTML='';
d.graphs.forEach(g=>{const o=document.createElement('option');o.value=g.graph_id;
o.textContent=`${g.provider_id} · ${g.graph_id}`+
` (${g.node_count}/${g.edge_count})`;s.appendChild(o)});
if(d.graphs.length)loadGraph(d.graphs[0].graph_id);
s.onchange=e=>loadGraph(e.target.value)}
async function loadGraph(id){const r=await fetch('/api/graph/'+encodeURIComponent(id));
const d=await r.json();sel=null;L={};
G.nodes=(d.nodes||[]).map(n=>({...n,x:Math.random()*600-300,y:Math.random()*600-300,vx:0,vy:0,deg:0}));
G.edges=(d.edges||[]);
const byId={};G.nodes.forEach(n=>{byId[n.id]=n});
G.edges.forEach(e=>{if(byId[e.source])byId[e.source].deg++;if(byId[e.target])byId[e.target].deg++});
G.edges=G.edges.filter(e=>byId[e.source]&&byId[e.target]);
kindsOn={};G.nodes.forEach(n=>kindsOn[n.kind]=true);
ekindsOn={};G.edges.forEach(e=>ekindsOn[e.kind]=true);
sidePanel();document.getElementById('meta').textContent=
`${d.descriptor.provider_id} · ${d.descriptor.domain} · ${d.descriptor.generated_at||''}`;
document.getElementById('prov').textContent=
(d.descriptor.limitations||[]).join(' | ').slice(0,120);
running=true;tick()}
function sidePanel(){const L=document.getElementById('layers'),E=document.getElementById('ekinds');
L.innerHTML='';E.innerHTML='';
Object.keys(kindsOn).sort().forEach(k=>{L.innerHTML+=
`<label class="f"><input type="checkbox" checked data-k="${k}">`+
` <span style="color:${pal(k)}">●</span> ${k}</label>`});
Object.keys(ekindsOn).sort().forEach(k=>{E.innerHTML+=
`<label class="f"><input type="checkbox" checked data-ek="${k}"> ${k}</label>`});
L.querySelectorAll('input').forEach(i=>i.onchange=e=>{kindsOn[e.target.dataset.k]=e.target.checked});
E.querySelectorAll('input').forEach(i=>i.onchange=e=>{ekindsOn[e.target.dataset.ek]=e.target.checked});
document.getElementById('legend').innerHTML=
Object.keys(ESTYLE).map(s=>`<div>─ ${s}</div>`).join('')}
function tick(){let n=0;const byId={};G.nodes.forEach(x=>byId[x.id]=x);
for(let i=0;i<G.nodes.length;i++)for(let j=i+1;j<G.nodes.length;j++){
const a=G.nodes[i],b=G.nodes[j];let dx=a.x-b.x,dy=a.y-b.y,d=dx*dx+dy*dy+40;
const f=Math.min(2000/d,40);a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f}
G.edges.forEach(e=>{const a=byId[e.source],b=byId[e.target];
const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-120)*0.02;
a.vx+=dx/d*f*d/120;a.vy+=dy/d*f*d/120;b.vx-=dx/d*f*d/120;b.vy-=dy/d*f*d/120});
G.nodes.forEach(a=>{a.vx-=a.x*0.001;a.vy-=a.y*0.001;a.vx*=0.85;a.vy*=0.85;
a.x+=a.vx;a.y+=a.vy;if(Math.abs(a.vx)+Math.abs(a.vy)>0.1)n++});
draw();if(n>0&&running)requestAnimationFrame(tick)}
function toS(x,y){const r=cv.getBoundingClientRect();
return[(x*view.s)+r.width/2+view.x,(y*view.s)+r.height/2+view.y]}
function draw(){const r=cv.getBoundingClientRect();
if(cv.width!==r.width*devicePixelRatio){cv.width=r.width*devicePixelRatio;
cv.height=r.height*devicePixelRatio}
cx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);
cx.clearRect(0,0,r.width,r.height);
const q=(document.getElementById('q').value||'').toLowerCase();
const vis={};let vc=0,ec=0;
G.nodes.forEach(n=>{const s=(n.label||'')+' '+n.id;
vis[n.id]=kindsOn[n.kind]&&(!q||s.toLowerCase().includes(q))&&
(!focusSet||focusSet.has(n.id));
if(vis[n.id])vc++});
G.edges.forEach(e=>{if(!vis[e.source]||!vis[e.target]||!ekindsOn[e.kind])return;ec++;
const a=G.nodes.find(n=>n.id===e.source),b=G.nodes.find(n=>n.id===e.target);
const[x1,y1]=toS(a.x,a.y),[x2,y2]=toS(b.x,b.y);
cx.strokeStyle=e===sel?'#f0f6fc':'#444c56';cx.lineWidth=e===sel?2:1;
cx.setLineDash(ESTYLE[e.epistemic_state]||ESTYLE.unknown);
cx.beginPath();cx.moveTo(x1,y1);cx.lineTo(x2,y2);cx.stroke();
// arrowhead
const an=Math.atan2(y2-y1,x2-x1);cx.setLineDash([]);cx.beginPath();
cx.moveTo(x2,y2);cx.lineTo(x2-8*Math.cos(an-0.5),y2-8*Math.sin(an-0.5));
cx.lineTo(x2-8*Math.cos(an+0.5),y2-8*Math.sin(an+0.5));cx.fillStyle=cx.strokeStyle;cx.fill()});
cx.setLineDash([]);
G.nodes.forEach(n=>{if(!vis[n.id])return;const[x,y]=toS(n.x,n.y);
const rad=4+Math.min(n.deg,12);
cx.beginPath();cx.arc(x,y,rad,0,7);
const dcol=drawDiffColors&&DC[drawDiffColors[n.id]];
cx.fillStyle=n===sel?'#f0f6fc':(n===hover?'#fff':(dcol||pal(n.kind)));cx.fill();
if(n===sel){cx.strokeStyle='#58a6ff';cx.lineWidth=2;cx.stroke()}
if(view.s>0.5||n.deg>4){cx.fillStyle='#8b949e';cx.font='10px monospace';
cx.fillText((n.label||n.id).slice(0,24),x+rad+2,y+3)}});
document.getElementById('stats').textContent=`${vc} nodes · ${ec} edges visible`}
cv.onwheel=e=>{e.preventDefault();const r=cv.getBoundingClientRect();
const mx=e.clientX-r.left-r.width/2,my=e.clientY-r.top-r.height/2;
const f=e.deltaY<0?1.15:0.87;view.x=(view.x-mx)*f+mx;view.y=(view.y-my)*f+my;
view.s*=f;draw()};
let drag=null;cv.onmousedown=e=>{const p=pick(e);drag={e,node:p.node,mx:view.x,my:view.y}};
cv.onmousemove=e=>{if(drag){const r=cv.getBoundingClientRect();
if(drag.node){drag.node.x=(e.clientX-r.left-r.width/2-view.x)/view.s;
drag.node.y=(e.clientY-r.top-r.height/2-view.y)/view.s}else{
view.x=drag.mx+e.clientX-drag.e.clientX;view.y=drag.my+e.clientY-drag.e.clientY}
draw()}else{const p=pick(e);hover=p.node;draw()}};
cv.onmouseup=e=>{const p=pick(e);
if(!drag||(Math.abs(e.clientX-drag.e.clientX)<4&&Math.abs(e.clientY-drag.e.clientY)<4)){
sel=p.node||p.edge||null;inspect()}
drag=null;draw()};
function pick(e){const r=cv.getBoundingClientRect();
const wx=(e.clientX-r.left-r.width/2-view.x)/view.s,
wy=(e.clientY-r.top-r.height/2-view.y)/view.s;
for(const n of G.nodes)if(Math.hypot(n.x-wx,n.y-wy)<12/view.s+4)return{node:n};
for(const ed of G.edges){const a=G.nodes.find(n=>n.id===ed.source),
b=G.nodes.find(n=>n.id===ed.target);if(!a||!b)continue;
const L2=(b.x-a.x)**2+(b.y-a.y)**2||1;
const t=Math.max(0,Math.min(1,((wx-a.x)*(b.x-a.x)+(wy-a.y)*(b.y-a.y))/L2));
if(Math.hypot(wx-(a.x+t*(b.x-a.x)),wy-(a.y+t*(b.y-a.y)))<6/view.s)return{edge:ed}}
return{}}
function inspect(){const b=document.getElementById('ibody');if(!sel){
b.innerHTML='<span class="dim">select a node or edge</span>';return}
let h='';
if(sel.kind&&sel.label!==undefined&&!sel.source){
h=`<div class="k"><b>${sel.label||sel.id}</b></div>
<span class="pill">${sel.kind}</span><span class="pill">${sel.epistemic_state}</span>
<span class="pill">${sel.source_provider||''}</span>
<h4>Attributes</h4><div class="k">${JSON.stringify(sel.attributes||{},null,1)}</div>
<h4>Evidence</h4>${(sel.evidence_refs||[]).map(e=>`<div class="ev">${e}</div>`)
.join('')||'<span class="dim">none</span>'}
<h4>Edges (${G.edges.filter(e=>e.source===sel.id||e.target===sel.id).length})</h4>`;
}else{h=`<div class="k"><b>${sel.kind}</b></div>
<div class="k dim">${sel.source} → ${sel.target}</div>
<span class="pill">${sel.epistemic_state}</span><span class="pill">${sel.provenance||''}</span>
${sel.confidence!=null?`<span class="pill">conf ${sel.confidence}</span>`:''}
<h4>Evidence</h4>${(sel.evidence_refs||[]).map(e=>`<div class="ev">${e}</div>`)
.join('')||'<span class="dim">none</span>'}
<h4>Temporal</h4><div class="k">${Object.keys(sel.temporal||{}).length?
JSON.stringify(sel.temporal):'none'}</div>`}
b.innerHTML=h}
document.getElementById('q').oninput=draw;
// --- premium interactions (Cycle 4): neighbors / export / diff / snapshot ---
let focusSet=null; // BFS subgraph when 'n' pressed
function neighbors(seed){const adj={};G.edges.forEach(e=>{
(adj[e.source]=adj[e.source]||new Set()).add(e.target);
(adj[e.target]=adj[e.target]||new Set()).add(e.source)});
const seen=new Set([seed]);let fr=[seed];
for(let d=0;d<2&&fr.length;d++){const nx=[];fr.forEach(id=>{
(adj[id]||[]).forEach(m=>{if(!seen.has(m)){seen.add(m);nx.push(m)}})});fr=nx}
return seen}
async function exportVisible(){const q=(document.getElementById('q').value||'').toLowerCase();
const vis={};G.nodes.forEach(n=>{const s=(n.label||'')+' '+n.id;
vis[n.id]=kindsOn[n.kind]&&(!q||s.toLowerCase().includes(q))&&(!focusSet||focusSet.has(n.id))});
const doc={exported_at:new Date().toISOString(),
nodes:G.nodes.filter(n=>vis[n.id]).map(n=>({id:n.id,kind:n.kind,label:n.label,
epistemic_state:n.epistemic_state,attributes:n.attributes,evidence_refs:n.evidence_refs})),
edges:G.edges.filter(e=>vis[e.source]&&vis[e.target]&&ekindsOn[e.kind])};
const a=document.createElement('a');a.href=URL.createObjectURL(
new Blob([JSON.stringify(doc,null,1)],{type:'application/json'}));
a.download='forge-graph-subgraph.json';a.click()}
let diffRef=null;
async function diffMode(){const r=await fetch('/api/graphs');const d=await r.json();
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
removed=(o.nodes||[]).filter(n=>!G.nodes.find(x=>x.id===n.id)).length;
diffRef={other,cls};
drawDiffColors=cls;
document.getElementById('prov').textContent=
`diff vs ${other}: +${added} ~${changed} −${removed} nodes · +${eadded} edges (esc clears)`;
draw()}
let drawDiffColors=null;
const DC={added:'#7ee787',removed:'#f78166',changed:'#ffa657',same:null};
let curId=null;
const _loadGraph=loadGraph;
loadGraph=async function(id){curId=id;diffRef=null;drawDiffColors=null;
await _loadGraph(id)}
function snapshotSave(){try{localStorage.setItem('forge-graph-snap',
JSON.stringify({graph:curId,view,q:document.getElementById('q').value,
kinds:kindsOn,ekinds:ekindsOn,when:Date.now()}));
document.getElementById('prov').textContent='snapshot saved (s restores)'}catch(e){}}
function snapshotLoad(){try{const s=JSON.parse(localStorage.getItem('forge-graph-snap')||'null');
if(!s)return;view=s.view;document.getElementById('q').value=s.q||'';
Object.assign(kindsOn,s.kinds||{});Object.assign(ekindsOn,s.ekinds||{});draw()}catch(e){}}
document.onkeydown=e=>{
if(e.key==='Escape'){view={x:0,y:0,s:1};sel=null;focusSet=null;diffRef=null;
drawDiffColors=null;inspect();draw()}
else if(e.key==='n'&&sel&&sel.id!==undefined){focusSet=focusSet?null:neighbors(sel.id);draw()}
else if(e.key==='e')exportVisible()
else if(e.key==='d')diffMode()
else if(e.key==='s'){localStorage.getItem('forge-graph-snap')?snapshotLoad():snapshotSave()}};
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
                gid = path[len("/api/graph/"):]
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
