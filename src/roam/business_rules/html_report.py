"""HTML 可视化报告 — 规则列表 + SVG 向量图谱，自包含零外部依赖"""

from __future__ import annotations

import json
import sqlite3

COLORS = {
    "validation": "#e74c3c", "authorization": "#e67e22", "workflow": "#2ecc71",
    "calculation": "#3498db", "data_integrity": "#9b59b6", "process": "#1abc9c",
    "configuration": "#95a5a6", "integration": "#f39c12",
}

EDGE_COLORS = {
    "same_field": "#ff6b6b", "same_flow": "#48dbfb", "conflicts_with": "#feca57",
}


def generate(db_path: str, output_path: str = "business-rules.html") -> str:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rules = [dict(r) for r in conn.execute(
            "SELECT * FROM business_rules ORDER BY source_file, source_line"
        ).fetchall()]
        edges = [dict(e) for e in conn.execute("""
            SELECT bre.edge_type, br1.rule_id AS source, br2.rule_id AS target
            FROM business_rule_edges bre
            JOIN business_rules br1 ON bre.source_rule_id = br1.id
            JOIN business_rules br2 ON bre.target_rule_id = br2.id
        """).fetchall()]

    graph: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        s, t, et = e["source"], e["target"], e["edge_type"]
        graph.setdefault(s, []).append((t, et))
        graph.setdefault(t, []).append((s, et))

    # 预构建 JS 数据
    rules_js = json.dumps([
        {"rule_id": r["rule_id"], "rule_type": r["rule_type"], "domain": r["domain"],
         "flow": r["flow"] or "", "description": r["description"], "severity": r["severity"],
         "source_file": r["source_file"], "source_line": r["source_line"], "hash": r["hash"],
         "merge_with": r.get("merge_with"), "extraction": r.get("extraction", ""),
         "params": json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]}
        for r in rules
    ], ensure_ascii=False)

    graph_js = json.dumps(
        {rid: [[t, et] for t, et in nbs] for rid, nbs in graph.items()},
        ensure_ascii=False
    )

    colors_js = json.dumps(COLORS)
    edge_colors_js = json.dumps(EDGE_COLORS)

    type_bar = _render_type_bar(rules)
    type_opts = _render_type_options(rules)
    rule_cards = _render_rule_cards(rules)

    html = _HTML_TEMPLATE.format(
        n_rules=len(rules), n_edges=len(edges),
        type_bar=type_bar, type_opts=type_opts, rule_cards=rule_cards,
        rules_js=rules_js, graph_js=graph_js,
        colors_js=colors_js, edge_colors_js=edge_colors_js,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Business Rule Graph</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font:14px/1.5 system-ui,sans-serif; background:#1a1a2e; color:#e0e0e0; }}
header {{ background:#16213e; padding:16px 24px; display:flex; justify-content:space-between; align-items:center; }}
header h1 {{ font-size:18px; color:#00d4ff; }}
.stats {{ color:#888; font-size:13px; }}
main {{ display:flex; height:calc(100vh - 60px); }}
.panel {{ overflow-y:auto; }}
.left {{ width:320px; min-width:320px; background:#16213e; border-right:1px solid #0f3460; padding:16px; }}
.right {{ flex:1; display:flex; flex-direction:column; }}
.graph-area {{ flex:1; position:relative; background:#111; }}
.graph-area svg {{ width:100%; height:100%; }}
.detail {{ background:#0f3460; border-radius:8px; padding:20px; margin:16px; max-height:300px; overflow-y:auto; }}
.detail h2 {{ color:#00d4ff; margin-bottom:12px; font-size:14px; word-break:break-all; }}
.detail dl {{ display:grid; grid-template-columns:90px 1fr; gap:6px; font-size:13px; }}
.detail dt {{ color:#888; }}
.rule-card {{ background:#0f3460; border-radius:6px; padding:10px; margin-bottom:8px; cursor:pointer; border-left:4px solid #555; }}
.rule-card:hover {{ background:#1a3a6e; }}
.rule-card.active {{ background:#1a5276; border-color:#00d4ff; }}
.rule-id {{ font-size:11px; color:#888; word-break:break-all; }}
.rule-desc {{ margin:4px 0; }}
.tag {{ display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; margin-right:4px; }}
.filter-bar {{ margin-bottom:12px; }}
.filter-bar select {{ background:#0f3460; color:#e0e0e0; border:1px solid #333; border-radius:4px; padding:4px 8px; width:100%; }}
.summary {{ background:#0f3460; border-radius:8px; padding:16px; margin-bottom:16px; }}
.summary h3 {{ margin-bottom:8px; }}
.bar {{ display:flex; height:20px; border-radius:3px; overflow:hidden; margin-bottom:4px; }}
.bar-seg {{ font-size:10px; line-height:20px; text-align:center; color:#fff; }}
.legend {{ position:absolute; top:10px; right:10px; background:rgba(22,33,62,0.9); border-radius:6px; padding:8px 12px; font-size:11px; }}
.legend-item {{ display:flex; align-items:center; margin:4px 0; }}
.legend-line {{ width:20px; height:2px; margin-right:6px; border-radius:1px; }}
.node-label {{ font-size:9px; fill:#ccc; pointer-events:none; }}
</style>
</head>
<body>
<header>
  <h1>Business Rule Graph</h1>
  <span class="stats">{n_rules} rules &middot; {n_edges} edges</span>
</header>
<main>
<div class="panel left">
  <div class="summary">
    <h3>按类型</h3>
    <div class="bar">{type_bar}</div>
  </div>
  <div class="filter-bar">
    <select id="typeFilter" onchange="filter()">
      <option value="">全部类型</option>
      {type_opts}
    </select>
  </div>
  <div id="ruleList">{rule_cards}</div>
</div>
<div class="panel right">
  <div class="graph-area" id="graphArea">
    <svg id="graphSvg"></svg>
    <div class="legend">
      <div class="legend-item"><span class="legend-line" style="background:#ff6b6b"></span> same_field</div>
      <div class="legend-item"><span class="legend-line" style="background:#48dbfb"></span> same_flow</div>
      <div class="legend-item"><span class="legend-line" style="background:#feca57"></span> conflicts_with</div>
      <div class="legend-item" style="margin-top:6px;color:#888" id="graphStats"></div>
    </div>
  </div>
  <div class="detail" id="detailPanel">
    <p style="color:#888">点击左侧规则查看详情与关系图谱</p>
  </div>
</div>
</main>
<script>
var allRules = {rules_js};
var graphData = {graph_js};
var ruleMap = {{}};
allRules.forEach(function(r) {{ ruleMap[r.rule_id] = r; }});
var colorMap = {colors_js};
var edgeColorMap = {edge_colors_js};
var svgNS = "http://www.w3.org/2000/svg";

function showDetail(ruleId) {{
  document.querySelectorAll('.rule-card').forEach(function(c) {{ c.classList.remove('active'); }});
  try {{ document.getElementById('card-' + CSS.escape(ruleId)).classList.add('active'); }} catch(e) {{}}

  var r = ruleMap[ruleId];
  if (!r) return;

  var html = '<h2>' + r.rule_id + '</h2><dl>' +
    '<dt>类型</dt><dd><span class="tag" style="background:' + (colorMap[r.rule_type]||'#555') + '">' + r.rule_type + '</span></dd>' +
    '<dt>业务域</dt><dd>' + (r.domain || '-') + '</dd>' +
    '<dt>流程</dt><dd>' + (r.flow || '-') + '</dd>' +
    '<dt>描述</dt><dd>' + (r.description || '-') + '</dd>' +
    '<dt>严重度</dt><dd>' + (r.severity || '-') + '</dd>' +
    '<dt>位置</dt><dd>' + r.source_file + ':' + r.source_line + '</dd>' +
    '<dt>提取方式</dt><dd>' + (r.extraction || '-') + '</dd>' +
    '<dt>Hash</dt><dd>' + r.hash + '</dd>';
  if (r.merge_with) html += '<dt>已合并到</dt><dd>' + r.merge_with + '</dd>';
  html += '</dl>';
  document.getElementById('detailPanel').innerHTML = html;
  drawGraph(ruleId);
}}

function drawGraph(rootId) {{
  var svg = document.getElementById('graphSvg');
  svg.innerHTML = '';

  var nodeIds = [rootId];
  var edgeList = [];
  var seen = {{}}; seen[rootId] = true;
  var queue = [rootId];

  while (queue.length > 0 && nodeIds.length < 60) {{
    var cur = queue.shift();
    var edges = graphData[cur] || [];
    for (var i = 0; i < edges.length; i++) {{
      var nb = edges[i][0], et = edges[i][1];
      edgeList.push({{source:cur, target:nb, type:et}});
      if (!seen[nb] && nodeIds.length < 60) {{ seen[nb] = true; nodeIds.push(nb); queue.push(nb); }}
    }}
  }}

  document.getElementById('graphStats').textContent = nodeIds.length + ' nodes, ' + edgeList.length + ' edges';
  if (nodeIds.length === 0) return;

  var W = svg.parentElement.clientWidth - 10;
  var H = svg.parentElement.clientHeight - 10;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);

  var cx = W/2, cy = H/2, r = Math.min(W,H)/2 - 40;
  var positions = {{}};
  nodeIds.forEach(function(id, i) {{
    var angle = 2 * Math.PI * i / nodeIds.length;
    positions[id] = {{x: cx + r * 0.8 * Math.cos(angle), y: cy + r * 0.8 * Math.sin(angle), vx:0, vy:0}};
  }});

  for (var iter = 0; iter < 50; iter++) {{
    for (var i = 0; i < nodeIds.length; i++) {{
      for (var j = i+1; j < nodeIds.length; j++) {{
        var a = positions[nodeIds[i]], b = positions[nodeIds[j]];
        var dx = a.x - b.x, dy = a.y - b.y, dist = Math.sqrt(dx*dx+dy*dy)||1;
        var force = 2000/(dist*dist), fx = dx/dist*force, fy = dy/dist*force;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }}
    }}
    edgeList.forEach(function(e) {{
      var a = positions[e.source], b = positions[e.target];
      if (!a || !b) return;
      var dx = b.x-a.x, dy = b.y-a.y, dist = Math.sqrt(dx*dx+dy*dy)||1;
      var force = dist*0.01, fx = dx/dist*force, fy = dy/dist*force;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }});
    nodeIds.forEach(function(id) {{
      var p = positions[id];
      p.vx += (cx-p.x)*0.001; p.vy += (cy-p.y)*0.001;
    }});
    nodeIds.forEach(function(id) {{
      var p = positions[id];
      p.x += p.vx*0.3; p.y += p.vy*0.3; p.vx *= 0.85; p.vy *= 0.85;
      p.x = Math.max(30, Math.min(W-30, p.x));
      p.y = Math.max(30, Math.min(H-30, p.y));
    }});
  }}

  edgeList.forEach(function(e) {{
    var a=positions[e.source], b=positions[e.target];
    if(!a||!b) return;
    var line = document.createElementNS(svgNS,'line');
    line.setAttribute('x1',a.x); line.setAttribute('y1',a.y);
    line.setAttribute('x2',b.x); line.setAttribute('y2',b.y);
    line.setAttribute('stroke',edgeColorMap[e.type]||'#555');
    line.setAttribute('stroke-width',e.type==='conflicts_with'?'2':'1');
    line.setAttribute('opacity','0.6');
    svg.appendChild(line);
  }});

  nodeIds.forEach(function(id) {{
    var p=positions[id], rule=ruleMap[id];
    var color=colorMap[rule?rule.rule_type:'']||'#555', isRoot=id===rootId;
    var circle=document.createElementNS(svgNS,'circle');
    circle.setAttribute('cx',p.x); circle.setAttribute('cy',p.y);
    circle.setAttribute('r',isRoot?'10':'6');
    circle.setAttribute('fill',color);
    circle.setAttribute('stroke',isRoot?'#00d4ff':'#333');
    circle.setAttribute('stroke-width',isRoot?'2':'1');
    circle.setAttribute('cursor','pointer');
    circle.addEventListener('click',function(){{showDetail(id);}});
    svg.appendChild(circle);

    var label=document.createElementNS(svgNS,'text');
    label.setAttribute('x',p.x+(isRoot?14:9)); label.setAttribute('y',p.y+4);
    label.setAttribute('class','node-label');
    label.textContent=(rule?rule.description:id).substring(0,24);
    svg.appendChild(label);
  }});
}}

function filter() {{
  var t = document.getElementById('typeFilter').value;
  document.querySelectorAll('.rule-card').forEach(function(c) {{
    c.style.display = !t || c.dataset.type === t ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


def _render_type_bar(rules: list[dict]) -> str:
    total = len(rules) or 1
    by_type: dict[str, int] = {}
    for r in rules:
        rt = r["rule_type"]
        by_type[rt] = by_type.get(rt, 0) + 1
    segs = []
    for rt, count in sorted(by_type.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        color = COLORS.get(rt, "#555")
        segs.append(
            f'<div class="bar-seg" style="width:{pct:.1f}%;background:{color}" '
            f'title="{rt}:{count}">{rt[:4]}</div>'
        )
    return "\n".join(segs)


def _render_type_options(rules: list[dict]) -> str:
    seen: set[str] = set()
    opts = []
    for r in rules:
        if r["rule_type"] not in seen:
            seen.add(r["rule_type"])
            opts.append(f'<option value="{r["rule_type"]}">{r["rule_type"]}</option>')
    return "\n".join(opts)


def _render_rule_cards(rules: list[dict]) -> str:
    cards = []
    for r in rules:
        color = COLORS.get(r["rule_type"], "#555")
        hid = _safe_html_id(r["rule_id"])
        sid = r["rule_id"].replace("\\", "\\\\").replace("'", "\\'")
        cards.append(
            f'<div class="rule-card" id="card-{hid}" data-type="{r["rule_type"]}" '
            f'onclick="showDetail(\'{sid}\')" style="border-left-color:{color}">'
            f'<div class="rule-id">{r["rule_id"][:60]}</div>'
            f'<div class="rule-desc">{r["description"][:50]}</div>'
            f'<span class="tag" style="background:{color}">{r["rule_type"]}</span>'
            f'<span class="tag" style="background:#333">{r.get("domain","")[:8]}</span>'
            f'</div>'
        )
    return "\n".join(cards)


def _safe_html_id(s: str) -> str:
    import re
    return re.sub(r'[^a-zA-Z0-9_.:-]', '_', s)
