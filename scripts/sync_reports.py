#!/usr/bin/env python3
"""
sync_reports.py
自动检测新研究报告 → 生成 HTML → 更新 blog.html → 推送 GitHub
"""
import os, re, subprocess, json
from datetime import datetime
from pathlib import Path

REPORTS_DIR  = "/Users/adam/WorkBuddy/Claw/db_research_reports"
SITE_DIR     = "/Users/adam/WorkBuddy/20260324123505"
OUTPUT_DIR   = os.path.join(SITE_DIR, "reports")
BLOG_HTML    = os.path.join(SITE_DIR, "blog.html")
INDEX_HTML   = os.path.join(SITE_DIR, "index.html")
STATE_FILE   = os.path.join(SITE_DIR, ".workbuddy", "report_state.json")
GIT_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GIT_REPO     = f"https://ColdZoo:{GIT_TOKEN}@github.com/ColdZoo/coldzoo.github.io.git"
GIT_BRANCH   = "gh-pages"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)


# ──────────────────────────────────────────────
# 1. 读取上次状态（已处理过的文件列表）
# ──────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"processed": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ──────────────────────────────────────────────
# 2. Markdown → HTML 转换（完整版）
# ──────────────────────────────────────────────
def inline(text: str) -> str:
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text

def md_to_html(md: str) -> str:
    lines = md.split('\n')
    html_parts = []
    in_table = in_ul = in_code = False
    code_buf = []
    for line in lines:
        if line.strip().startswith('```'):
            if in_code:
                html_parts.append('<pre><code>' + '\n'.join(code_buf) + '</code></pre>')
                code_buf = []; in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line.replace('<','&lt;').replace('>','&gt;'))
            continue
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
                in_table = True
                html_parts.append('<div class="table-wrap"><table>')
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if all(re.match(r'^[-:]+$', c.strip()) or c.strip() == '' for c in cells):
                continue
            tag = 'th' if not any('<td>' in p for p in html_parts[-3:]) else 'td'
            row = ''.join(f'<{tag}>{inline(c)}</{tag}>' for c in cells)
            html_parts.append(f'<tr>{row}</tr>')
            continue
        else:
            if in_table:
                html_parts.append('</table></div>')
                in_table = False
        if line.strip().startswith(('- ', '* ')):
            if not in_ul: in_ul = True; html_parts.append('<ul>')
            html_parts.append(f'<li>{inline(line.strip()[2:])}</li>')
            continue
        else:
            if in_ul: html_parts.append('</ul>'); in_ul = False
        ol = re.match(r'^\d+\.\s+(.*)', line.strip())
        if ol:
            html_parts.append(f'<li>{inline(ol.group(1))}</li>')
            continue
        h = re.match(r'^(#{1,4})\s+(.*)', line)
        if h:
            lv = len(h.group(1))
            html_parts.append(f'<h{lv}>{inline(h.group(2))}</h{lv}>')
            continue
        if re.match(r'^---+$', line.strip()):
            html_parts.append('<hr/>')
            continue
        if not line.strip():
            html_parts.append('<br/>')
            continue
        html_parts.append(f'<p>{inline(line)}</p>')
    if in_ul: html_parts.append('</ul>')
    if in_table: html_parts.append('</table></div>')
    return '\n'.join(html_parts)


# ──────────────────────────────────────────────
# 3. 解析报告文件名 → 元数据
# ──────────────────────────────────────────────
def parse_filename(fname: str):
    """
    report_2026-03-27.md            → date=2026-03-27, suffix=''
    report_2026-03-16_supplement.md → date=2026-03-16, suffix='_supplement'
    parquet-gpu-optimization.md    → date=2026-03-27, suffix='_translation'
    返回 (date_str, suffix, html_name, title, tags)
    """
    # 标准格式：report_YYYY-MM-DD[...].md
    m = re.match(r'report_(\d{4}-\d{2}-\d{2})(.*?)\.md$', fname)
    if m:
        date_str = m.group(1)
        suffix   = m.group(2)
        html_name = f"report-{date_str}{suffix.replace('_','-')}.html"
        title = f"数据库研究论文追踪报告 · {date_str}" + (" 补充" if "supplement" in suffix else "")
        return date_str, suffix, html_name, title

    # 翻译/独立文章格式：使用当前日期作为 date
    # 使用文件名本身（去掉 .md）作为 html_name 和 title
    base_name = fname[:-3]  # remove .md
    today = datetime.now().strftime("%Y-%m-%d")
    html_name = f"{base_name}.html"
    title = base_name.replace('-', ' ').replace('_', ' ').title()
    return today, '_translation', html_name, title

def detect_tags(md_content: str) -> list:
    """扫描正文关键词自动打标签"""
    lower = md_content.lower()
    tags = []
    has_encoding = any(k in lower for k in ['encoding', 'compression', 'codec', 'parquet', 'fastlane', 'columnar'])
    has_gpu      = any(k in lower for k in ['gpu', 'cuda', 'nvme', 'simd', 'hardware acceleration'])
    if has_encoding and has_gpu:
        tags.append('<span class="tag tag-combined">编码 + GPU</span>')
    elif has_encoding:
        tags.append('<span class="tag tag-encoding">数据编码</span>')
    elif has_gpu:
        tags.append('<span class="tag tag-gpu">GPU 加速</span>')
    else:
        tags.append('<span class="tag tag-default">日常追踪</span>')
    return tags

def extract_excerpt(md_content: str, max_chars=100) -> str:
    """从 Markdown 提取第一段有意义的文字作为摘要"""
    for line in md_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('|') or line.startswith('-') or line.startswith('*'):
            continue
        text = re.sub(r'[#*`\[\]()]', '', line)[:max_chars]
        if len(text) > 20:
            return text + '……'
    return '数据库研究论文每日追踪……'

def extract_first_title(md_content: str) -> str:
    """提取第一篇论文标题（用于博客列表展示）"""
    for line in md_content.split('\n'):
        m = re.match(r'^#{1,3}\s+(.+)', line)
        if m:
            t = m.group(1).strip()
            if len(t) > 5 and '报告' not in t and '追踪' not in t and '摘要' not in t:
                return t
    return None


# ──────────────────────────────────────────────
# 4. 生成单篇文章 HTML
# ──────────────────────────────────────────────
ARTICLE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title} · 蔡政</title>
  <style>
    :root {{
      --bg-base:#f2f1f6; --bg-card:rgba(255,255,255,0.72);
      --glass-border:rgba(255,255,255,0.6);
      --glass-shadow:0 8px 32px rgba(60,60,100,0.10),0 1.5px 4px rgba(60,60,100,0.06);
      --color-primary:#5b6cf9; --color-text:#1c1c1e;
      --color-text-secondary:#48484a; --color-text-muted:#8e8e93;
      --font-sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Helvetica Neue","PingFang SC",sans-serif;
      --font-mono:"SF Mono","Menlo","Monaco","Consolas",monospace;
    }}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:var(--font-sans);background:var(--bg-base);color:var(--color-text);-webkit-font-smoothing:antialiased;}}
    .menubar{{position:sticky;top:0;z-index:100;height:48px;background:rgba(242,241,246,0.88);backdrop-filter:blur(24px) saturate(1.8);border-bottom:1px solid rgba(0,0,0,0.07);display:flex;align-items:center;padding:0 20px;gap:16px;}}
    .menubar .logo{{font-size:15px;font-weight:700;color:var(--color-text);text-decoration:none;}}
    .menubar .menu-item{{font-size:13px;font-weight:500;padding:4px 10px;border-radius:6px;color:var(--color-text);text-decoration:none;transition:background 0.15s;}}
    .menubar .menu-item:hover{{background:rgba(0,0,0,0.07);}}
    .menubar .spacer{{flex:1;}}
    .menubar-time{{font-size:13px;font-weight:500;color:var(--color-text-secondary);}}
    .back-bar{{max-width:720px;margin:0 auto;padding:20px 24px 0;}}
    .back-link{{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--color-primary);text-decoration:none;padding:6px 12px;border-radius:8px;background:rgba(91,108,249,0.07);transition:all 0.15s;}}
    .back-link:hover{{background:rgba(91,108,249,0.13);}}
    .article-wrap{{max-width:720px;margin:0 auto;padding:20px 24px 100px;}}
    .article-header{{margin-bottom:36px;}}
    .article-tags{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;}}
    .tag{{font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;border:1px solid transparent;}}
    .tag-encoding{{background:rgba(91,108,249,0.1);color:#5b6cf9;border-color:rgba(91,108,249,0.18);}}
    .tag-gpu{{background:rgba(255,159,10,0.1);color:#b56200;border-color:rgba(255,159,10,0.2);}}
    .tag-combined{{background:rgba(167,139,250,0.12);color:#6741d9;border-color:rgba(167,139,250,0.2);}}
    .tag-default{{background:rgba(0,0,0,0.05);color:#8e8e93;border-color:rgba(0,0,0,0.08);}}
    .article-title{{font-size:34px;font-weight:700;letter-spacing:-0.8px;line-height:1.2;margin-bottom:12px;}}
    .article-meta{{font-size:13px;color:var(--color-text-muted);}}
    .article-body{{background:var(--bg-card);border:1px solid var(--glass-border);border-radius:18px;box-shadow:var(--glass-shadow);backdrop-filter:blur(20px);padding:32px 36px;}}
    .article-body h1{{font-size:26px;font-weight:700;letter-spacing:-0.5px;margin:28px 0 12px;padding-bottom:8px;border-bottom:1px solid rgba(0,0,0,0.06);}}
    .article-body h1:first-child{{margin-top:0;}}
    .article-body h2{{font-size:20px;font-weight:700;margin:24px 0 10px;}}
    .article-body h3{{font-size:16px;font-weight:700;margin:20px 0 8px;color:var(--color-primary);}}
    .article-body h4{{font-size:14px;font-weight:700;margin:16px 0 6px;}}
    .article-body p{{font-size:15px;line-height:1.75;color:var(--color-text-secondary);margin-bottom:10px;}}
    .article-body ul{{padding-left:20px;margin-bottom:12px;}}
    .article-body li{{font-size:14px;line-height:1.7;color:var(--color-text-secondary);margin-bottom:4px;}}
    .article-body strong{{color:var(--color-text);font-weight:700;}}
    .article-body em{{color:var(--color-primary);font-style:normal;font-weight:500;}}
    .article-body code{{font-family:var(--font-mono);font-size:12px;background:rgba(0,0,0,0.05);border-radius:4px;padding:1px 5px;}}
    .article-body pre{{background:rgba(28,28,30,0.9);border-radius:12px;padding:20px;margin:16px 0;overflow-x:auto;}}
    .article-body pre code{{color:#e5e5ea;background:none;font-size:13px;line-height:1.6;}}
    .article-body hr{{border:none;border-top:1px solid rgba(0,0,0,0.07);margin:24px 0;}}
    .article-body br{{display:block;margin:4px 0;content:"";}}
    .article-body a{{color:var(--color-primary);text-decoration:none;font-weight:500;}}
    .article-body a:hover{{text-decoration:underline;}}
    .table-wrap{{overflow-x:auto;margin:16px 0;}}
    .article-body table{{width:100%;border-collapse:collapse;font-size:13px;}}
    .article-body th{{background:rgba(91,108,249,0.07);font-weight:700;text-align:left;padding:8px 12px;border-bottom:2px solid rgba(91,108,249,0.15);}}
    .article-body td{{padding:8px 12px;border-bottom:1px solid rgba(0,0,0,0.06);color:var(--color-text-secondary);vertical-align:top;}}
    .article-body tr:last-child td{{border-bottom:none;}}
  </style>
</head>
<body>
<nav class="menubar">
  <a href="../index.html" class="logo"> 蔡政</a>
  <a href="../blog.html" class="menu-item">← 研究笔记</a>
  <span class="spacer"></span>
  <span class="menubar-time" id="menubar-time"></span>
</nav>
<div class="back-bar"><a href="../blog.html" class="back-link">← 返回列表</a></div>
<div class="article-wrap">
  <div class="article-header">
    <div class="article-tags">{tags}</div>
    <h1 class="article-title">{title}</h1>
    <div class="article-meta">📅 {date} &nbsp;·&nbsp; 数据库研究论文追踪</div>
  </div>
  <div class="article-body">{body}</div>
</div>
<script>
  function updateTime() {{
    const now = new Date();
    const h = String(now.getHours()).padStart(2,'0');
    const m = String(now.getMinutes()).padStart(2,'0');
    const days = ['周日','周一','周二','周三','周四','周五','周六'];
    document.getElementById('menubar-time').textContent = days[now.getDay()] + ' ' + h + ':' + m;
  }}
  updateTime(); setInterval(updateTime, 60000);
</script>
</body>
</html>'''


# ──────────────────────────────────────────────
# 5. 扫描所有报告文件并生成 HTML
# ──────────────────────────────────────────────
def build_all_reports():
    """扫描 REPORTS_DIR，返回所有报告的元信息列表（按日期降序）"""
    state = load_state()
    processed = set(state["processed"])
    new_count = 0
    all_reports = []

    md_files = sorted(
        [f for f in os.listdir(REPORTS_DIR) if re.match(r'report_\d{4}-\d{2}-\d{2}.*\.md$', f)],
        reverse=True  # 最新在前
    )

    for fname in md_files:
        parsed = parse_filename(fname)
        if not parsed:
            continue
        date_str, suffix, html_name, title = parsed
        md_path   = os.path.join(REPORTS_DIR, fname)
        html_path = os.path.join(OUTPUT_DIR, html_name)

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # 提取信息
        tags     = detect_tags(md_content)
        excerpt  = extract_excerpt(md_content)
        paper_title = extract_first_title(md_content)
        display_title = paper_title if paper_title else title

        all_reports.append({
            "fname":    fname,
            "date":     date_str,
            "suffix":   suffix,
            "html":     html_name,
            "title":    title,
            "display":  display_title,
            "tags":     tags,
            "excerpt":  excerpt,
        })

        # 只转换新文件（或强制重建）
        if fname not in processed or not os.path.exists(html_path):
            body = md_to_html(md_content)
            tags_html = ''.join(tags)
            html = ARTICLE_TEMPLATE.format(
                title=title, date=date_str,
                tags=tags_html, body=body
            )
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"  ✅ 生成: {html_name}")
            new_count += 1
            processed.add(fname)

    save_state({"processed": list(processed)})
    return all_reports, new_count


# ──────────────────────────────────────────────
# 6. 重建 blog.html
# ──────────────────────────────────────────────
BLOG_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>研究笔记 · 蔡政</title>
  <style>
    :root {{
      --bg-base:#f2f1f6;--bg-card:rgba(255,255,255,0.72);
      --glass-border:rgba(255,255,255,0.6);
      --glass-shadow:0 8px 32px rgba(60,60,100,0.10),0 1.5px 4px rgba(60,60,100,0.06);
      --color-primary:#5b6cf9;--color-text:#1c1c1e;
      --color-text-secondary:#48484a;--color-text-muted:#8e8e93;
      --font-sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Helvetica Neue","PingFang SC",sans-serif;
    }}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:var(--font-sans);background:var(--bg-base);color:var(--color-text);-webkit-font-smoothing:antialiased;}}
    /* Menu Bar */
    .menubar{{position:sticky;top:0;z-index:100;height:48px;background:rgba(242,241,246,0.88);backdrop-filter:blur(24px) saturate(1.8);border-bottom:1px solid rgba(0,0,0,0.07);display:flex;align-items:center;padding:0 20px;gap:16px;}}
    .menubar .logo{{font-size:15px;font-weight:700;color:var(--color-text);text-decoration:none;}}
    .menubar .menu-item{{font-size:13px;font-weight:500;padding:4px 10px;border-radius:6px;color:var(--color-text);text-decoration:none;transition:background 0.15s;}}
    .menubar .menu-item:hover{{background:rgba(0,0,0,0.07);}}
    .menubar .spacer{{flex:1;}}
    .menubar-time{{font-size:13px;font-weight:500;color:var(--color-text-secondary);}}
    /* Layout */
    .page-wrap{{max-width:860px;margin:0 auto;padding:40px 24px 120px;}}
    .page-header{{margin-bottom:36px;}}
    .page-header h1{{font-size:40px;font-weight:700;letter-spacing:-1px;margin-bottom:10px;}}
    .page-header p{{font-size:15px;color:var(--color-text-secondary);line-height:1.6;}}
    /* 筛选栏 */
    .filter-bar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:28px;}}
    .filter-btn{{font-size:12px;font-weight:600;padding:5px 14px;border-radius:20px;border:1px solid transparent;cursor:pointer;transition:all 0.15s;background:rgba(255,255,255,0.6);color:var(--color-text-muted);border-color:rgba(0,0,0,0.08);}}
    .filter-btn:hover,.filter-btn.active{{background:var(--color-primary);color:#fff;border-color:var(--color-primary);}}
    /* 报告列表 */
    .report-list{{display:flex;flex-direction:column;gap:12px;}}
    .report-card{{background:var(--bg-card);border:1px solid var(--glass-border);border-radius:16px;box-shadow:var(--glass-shadow);backdrop-filter:blur(20px);padding:20px 24px;text-decoration:none;color:inherit;display:flex;align-items:center;gap:16px;transition:transform 0.15s,box-shadow 0.15s;}}
    .report-card:hover{{transform:translateX(4px);box-shadow:0 12px 40px rgba(60,60,100,0.14);}}
    .report-card .card-left{{flex:1;}}
    .card-tags{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;}}
    .tag{{font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px;border:1px solid transparent;}}
    .tag-encoding{{background:rgba(91,108,249,0.1);color:#5b6cf9;border-color:rgba(91,108,249,0.18);}}
    .tag-gpu{{background:rgba(255,159,10,0.1);color:#b56200;border-color:rgba(255,159,10,0.2);}}
    .tag-combined{{background:rgba(167,139,250,0.12);color:#6741d9;border-color:rgba(167,139,250,0.2);}}
    .tag-default{{background:rgba(0,0,0,0.05);color:#8e8e93;border-color:rgba(0,0,0,0.08);}}
    .card-title{{font-size:16px;font-weight:700;margin-bottom:4px;color:var(--color-text);}}
    .card-excerpt{{font-size:13px;color:var(--color-text-muted);line-height:1.5;}}
    .card-date{{font-size:12px;color:var(--color-text-muted);white-space:nowrap;}}
    .card-arrow{{font-size:18px;color:var(--color-primary);opacity:0.5;transition:opacity 0.15s;}}
    .report-card:hover .card-arrow{{opacity:1;}}
    /* 统计条 */
    .stats-bar{{display:flex;gap:20px;margin-bottom:24px;}}
    .stat-item{{text-align:center;}}
    .stat-num{{font-size:28px;font-weight:700;background:linear-gradient(135deg,#5b6cf9,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
    .stat-label{{font-size:12px;color:var(--color-text-muted);margin-top:2px;}}
  </style>
</head>
<body>
<nav class="menubar">
  <a href="index.html" class="logo"> 蔡政</a>
  <a href="index.html" class="menu-item">← 返回主页</a>
  <span class="spacer"></span>
  <span class="menubar-time" id="menubar-time"></span>
</nav>
<div class="page-wrap">
  <div class="page-header">
    <h1>🔬 研究笔记</h1>
    <p>每日追踪 VLDB & SIGMOD 最新论文，聚焦数据编码 / GPU 加速方向</p>
  </div>
  <div class="stats-bar">
    <div class="stat-item"><div class="stat-num">{total}</div><div class="stat-label">篇报告</div></div>
    <div class="stat-item"><div class="stat-num">{last_date}</div><div class="stat-label">最新更新</div></div>
  </div>
  <div class="filter-bar">
    <button class="filter-btn active" onclick="filterReports(this,'all')">全部</button>
    <button class="filter-btn" onclick="filterReports(this,'encoding')">数据编码</button>
    <button class="filter-btn" onclick="filterReports(this,'gpu')">GPU 加速</button>
    <button class="filter-btn" onclick="filterReports(this,'combined')">编码 + GPU</button>
  </div>
  <div class="report-list" id="report-list">
{cards}
  </div>
</div>
<script>
  function updateTime() {{
    const now = new Date();
    const h = String(now.getHours()).padStart(2,'0');
    const m = String(now.getMinutes()).padStart(2,'0');
    const days = ['周日','周一','周二','周三','周四','周五','周六'];
    document.getElementById('menubar-time').textContent = days[now.getDay()] + ' ' + h + ':' + m;
  }}
  updateTime(); setInterval(updateTime, 60000);

  function filterReports(btn, type) {{
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.report-card').forEach(card => {{
      if (type === 'all') {{ card.style.display = ''; return; }}
      const hasTag = card.querySelector('.tag-' + type);
      card.style.display = hasTag ? '' : 'none';
    }});
  }}
</script>
</body>
</html>'''

def build_card(report):
    tags_html = ''.join(report["tags"])
    return f'''    <a href="reports/{report["html"]}" class="report-card" data-date="{report["date"]}">
      <div class="card-left">
        <div class="card-tags">{tags_html}</div>
        <div class="card-title">{report["display"]}</div>
        <div class="card-excerpt">{report["excerpt"]}</div>
      </div>
      <div class="card-date">{report["date"]}</div>
      <div class="card-arrow">→</div>
    </a>'''

def rebuild_blog_html(all_reports):
    cards = '\n'.join(build_card(r) for r in all_reports)
    last_date = all_reports[0]["date"] if all_reports else "N/A"
    html = BLOG_TEMPLATE.format(
        total=len(all_reports),
        last_date=last_date,
        cards=cards
    )
    with open(BLOG_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✅ blog.html 已更新 ({len(all_reports)} 篇)")


# ──────────────────────────────────────────────
# 7. 更新主页博客板块（取最新 3 篇）
# ──────────────────────────────────────────────
def update_index_blog(all_reports):
    if not os.path.exists(INDEX_HTML):
        return
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()

    # 生成最新 3 篇的 blog-item HTML
    top3 = all_reports[:3]
    items = []
    for r in top3:
        tag_label = ""
        for tag in r["tags"]:
            m = re.search(r'>([^<]+)</span>', tag)
            if m:
                tag_label = m.group(1)
                break
        items.append(f'''    <a href="reports/{r["html"]}" class="blog-item">
      <div>
        <div class="blog-meta">
          <span class="blog-category">{tag_label}</span>
          <span class="blog-date">{r["date"]}</span>
        </div>
        <div class="blog-title">{r["display"]}</div>
        <div class="blog-excerpt">{r["excerpt"]}</div>
      </div>
      <span class="blog-arrow">→</span>
    </a>''')

    new_list = '  <div class="blog-list">\n' + '\n'.join(items) + f'\n  </div>\n  <div style="margin-top:20px;text-align:center;">\n    <a href="blog.html" class="btn-secondary" style="display:inline-flex;align-items:center;gap:6px;">查看全部研究笔记 ({len(all_reports)} 篇) →</a>\n  </div>'

    # 替换 blog-list 区域
    new_content = re.sub(
        r'<div class="blog-list">.*?</div>\s*(?:<div[^>]*btn-secondary[^>]*>.*?</div>)?',
        new_list,
        content,
        flags=re.DOTALL
    )
    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"  ✅ index.html 博客板块已更新（最新 {len(top3)} 篇）")


# ──────────────────────────────────────────────
# 8. Git 推送
# ──────────────────────────────────────────────
def git_push(new_count, total):
    os.chdir(SITE_DIR)
    subprocess.run(['git', 'checkout', GIT_BRANCH], capture_output=True)
    subprocess.run(['git', 'add', '-A'], capture_output=True)
    
    # 检查是否有变动
    result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
    if result.returncode == 0:
        print("  ℹ️  没有新内容，跳过推送")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    msg = f"Auto: sync {new_count} new report(s) [{today}] (total {total})"
    subprocess.run(['git', 'commit', '-m', msg], capture_output=True)
    
    # 设置带 token 的 remote
    subprocess.run(['git', 'remote', 'set-url', 'origin', GIT_REPO], capture_output=True)
    result = subprocess.run(['git', 'push', 'origin', GIT_BRANCH], capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"  ✅ 已推送到 GitHub gh-pages 分支")
        return True
    else:
        print(f"  ❌ 推送失败: {result.stderr}")
        return False


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────
if __name__ == '__main__':
    print(f"\n{'='*50}")
    print(f"  DB Reports Sync  [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"{'='*50}")

    print("\n📄 扫描报告文件...")
    all_reports, new_count = build_all_reports()
    print(f"  共 {len(all_reports)} 篇报告，新增 {new_count} 篇")

    if new_count > 0 or True:  # 总是重建列表以确保一致性
        print("\n📝 重建 blog.html...")
        rebuild_blog_html(all_reports)

        print("\n🏠 更新主页博客板块...")
        update_index_blog(all_reports)

        print("\n🚀 推送到 GitHub...")
        git_push(new_count, len(all_reports))
    else:
        print("\n✅ 没有新文章，无需更新")

    print(f"\n✨ 同步完成！网站: https://coldzoo.github.io/\n")
