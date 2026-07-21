"""HTML 可视化报告 — 自包含，零外部依赖"""
from __future__ import annotations

import json
import sqlite3

COLORS = {
    "validation":     "#e74c3c",
    "authorization":  "#e67e22",
    "workflow":       "#2ecc71",
    "calculation":    "#3498db",
    "data_integrity": "#9b59b6",
    "process":        "#1abc9c",
    "configuration":  "#95a5a6",
    "integration":    "#f39c12",
}


def generate(db_path: str, output_path: str = "business-rules.html") -> str:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rules = [dict(r) for r in conn.execute("SELECT * FROM business_rules").fetchall()]
        edges = [dict(e) for e in conn.execute("""
            SELECT bre.edge_type, br1.rule_id AS source, br2.rule_id AS target
            FROM business_rule_edges bre
            JOIN business_rules br1 ON bre.source_rule_id = br1.id
            JOIN business_rules br2 ON bre.target_rule_id = br2.id
        """).fetchall()]

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Business Rule Graph</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font:14px/1.5 system-ui,sans-serif; background:#1a1a2e; color:#e0e0e0; }}
header {{ background:#16213e; padding:16px 24px; display:flex; justify-content:space-between; }}
header h1 {{ font-size:18px; color:#00d4ff; }}
.stats {{ color:#888; font-size:13px; }}
main {{ display:flex; height:calc(100vh - 60px); }}
.panel {{ overflow-y:auto; padding:16px; }}
.left {{ width:320px; background:#16213e; border-right:1px solid #0f3460; }}
.right {{ flex:1; padding:0; }}
.rule-card {{ background:#0f3460; border-radius:6px; padding:10px; margin-bottom:8px; cursor:pointer; border-left:4px solid #555; }}
.rule-card:hover {{ background:#1a3a6e; }}
.rule-card.active {{ background:#1a5276; border-color:#00d4ff; }}
.rule-id {{ font-size:11px; color:#888; word-break:break-all; }}
.rule-desc {{ margin:4px 0; }}
.tag {{ display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; margin-right:4px; }}
.detail {{ background:#0f3460; border-radius:8px; padding:20px; margin:16px; }}
.detail h2 {{ color:#00d4ff; margin-bottom:12px; }}
.detail dl {{ display:grid; grid-template-columns:100px 1fr; gap:8px; }}
.detail dt {{ color:#888; }}
.filter-bar {{ margin-bottom:12px; }}
.filter-bar select,input {{ background:#0f3460; color:#e0e0e0; border:1px solid #333; border-radius:4px; padding:4px 8px; margin-right:6px; }}
.summary {{ background:#0f3460; border-radius:8px; padding:16px; margin-bottom:16px; }}
.summary h3 {{ margin-bottom:8px; }}
.bar {{ display:flex; height:20px; border-radius:3px; overflow:hidden; margin-bottom:4px; }}
.bar-seg {{ font-size:10px; line-height:20px; text-align:center; color:#fff; }}
</style>
</head>
<body>
<header>
  <h1>Business Rule Graph</h1>
  <span class="stats">{len(rules)} rules · {len(edges)} edges</span>
</header>
<main>
<div class="panel left">
  <div class="summary">
    <h3>按类型</h3>
    <div class="bar">
""" + _render_type_bar(rules) + f"""
    </div>
  </div>
  <div class="filter-bar">
    <select id="typeFilter" onchange="filter()">
      <option value="">全部类型</option>
""" + _render_type_options(rules) + f"""
    </select>
  </div>
  <div id="ruleList">
""" + _render_rule_cards(rules) + f"""
  </div>
</div>
<div class="panel right" id="detailPanel">
  <div class="detail"><p style="color:#888">点击左侧规则查看详情</p></div>
</div>
</main>
<script>
function showDetail(ruleId) {{
  document.querySelectorAll('.rule-card').forEach(c => c.classList.remove('active'));
  document.getElementById('card-' + CSS.escape(ruleId))?.classList.add('active');
  var rules = {json.dumps([{'rule_id':r['rule_id'],'rule_type':r['rule_type'],'domain':r['domain'],
    'flow':r['flow'] or '','description':r['description'],'severity':r['severity'],
    'source_file':r['source_file'],'source_line':r['source_line'],'hash':r['hash'],
    'merge_with':r.get('merge_with'),'extraction':r.get('extraction',''),
    'params':json.loads(r['params']) if isinstance(r['params'],str) else r['params']}
    for r in rules], ensure_ascii=False)};
  var r = rules.find(x => x.rule_id === ruleId);
  if (!r) return;
  var html = '<div class="detail"><h2>' + r.rule_id + '</h2><dl>' +
    '<dt>类型</dt><dd><span class="tag" style="background:' + colorMap[r.rule_type] + '">' + r.rule_type + '</span></dd>' +
    '<dt>业务域</dt><dd>' + (r.domain || '-') + '</dd>' +
    '<dt>流程</dt><dd>' + (r.flow || '-') + '</dd>' +
    '<dt>描述</dt><dd>' + (r.description || '-') + '</dd>' +
    '<dt>严重度</dt><dd>' + (r.severity || '-') + '</dd>' +
    '<dt>位置</dt><dd>' + r.source_file + ':' + r.source_line + '</dd>' +
    '<dt>提取方式</dt><dd>' + (r.extraction || '-') + '</dd>' +
    '<dt>Hash</dt><dd>' + r.hash + '</dd>';
  if (r.merge_with) html += '<dt>已合并到</dt><dd>' + r.merge_with + '</dd>';
  if (r.params && Object.keys(r.params).length) html += '<dt>参数</dt><dd>' + JSON.stringify(r.params) + '</dd>';
  html += '</dl></div>';
  document.getElementById('detailPanel').innerHTML = html;
}}
var colorMap = {json.dumps(COLORS)};
function filter() {{
  var t = document.getElementById('typeFilter').value;
  document.querySelectorAll('.rule-card').forEach(c => {{
    c.style.display = !t || c.dataset.type === t ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def _render_type_bar(rules: list[dict]) -> str:
    total = len(rules) or 1
    by_type = {}
    for r in rules:
        rt = r["rule_type"]
        by_type[rt] = by_type.get(rt, 0) + 1
    segs = []
    for rt, count in sorted(by_type.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        color = COLORS.get(rt, "#555")
        segs.append(f'<div class="bar-seg" style="width:{pct:.1f}%;background:{color}" title="{rt}:{count}">{rt[:4]}</div>')
    return "\n".join(segs)


def _render_type_options(rules: list[dict]) -> str:
    seen = set()
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
        safe_id = r["rule_id"].replace("'", "\\'").replace('"', '&quot;')
        cards.append(f"""<div class="rule-card" id="card-{_safe_html_id(r['rule_id'])}"
     data-type="{r['rule_type']}" onclick="showDetail('{safe_id}')"
     style="border-left-color:{color}">
  <div class="rule-id">{r['rule_id'][:60]}</div>
  <div class="rule-desc">{r['description'][:50]}</div>
  <span class="tag" style="background:{color}">{r['rule_type']}</span>
  <span class="tag" style="background:#333">{r.get('domain','')[:8]}</span>
</div>""")
    return "\n".join(cards)


def _safe_html_id(s: str) -> str:
    import re
    return re.sub(r'[^a-zA-Z0-9_.:-]', '_', s)
