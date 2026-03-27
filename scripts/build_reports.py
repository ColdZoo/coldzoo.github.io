#!/usr/bin/env python3
"""把所有 markdown 报告转换为 HTML 页面"""
import os, re

REPORTS_DIR = "/Users/adam/WorkBuddy/Claw/db_research_reports"
OUTPUT_DIR  = "/Users/adam/WorkBuddy/20260324123505/reports"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def md_to_html(md: str) -> str:
    """极简 Markdown → HTML 转换"""
    lines = md.split('\n')
    html_parts = []
    in_table = False
    in_ul = False
    in_code = False
    code_buf = []

    for line in lines:
        # 代码块
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

        # 表格
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
                in_table = True
                html_parts.append('<div class="table-wrap"><table>')
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if all(set(c.replace('-','').replace(':','').strip()) == set() or c.strip() in ('','---','----') or re.match(r'^[-:]+$', c.strip()) for c in cells):
                continue
            tag = 'th' if not any('<td>' in p for p in html_parts[-3:]) else 'td'
            row = ''.join(f'<{tag}>{inline(c)}</{tag}>' for c in cells)
            html_parts.append(f'<tr>{row}</tr>')
            continue
        else:
            if in_table:
                html_parts.append('</table></div>')
                in_table = False

        # 无序列表
        if line.strip().startswith(('- ', '* ')):
            if not in_ul:
                in_ul = True
                html_parts.append('<ul>')
            html_parts.append(f'<li>{inline(line.strip()[2:])}</li>')
            continue
        else:
            if in_ul:
                html_parts.append('</ul>')
                in_ul = False

        # 有序列表
        ol_match = re.match(r'^\d+\.\s+(.*)', line.strip())
        if ol_match:
            html_parts.append(f'<li>{inline(ol_match.group(1))}</li>')
            continue

        # 标题
        h_match = re.match(r'^(#{1,4})\s+(.*)', line)
        if h_match:
            level = len(h_match.group(1))
            html_parts.append(f'<h{level}>{inline(h_match.group(2))}</h{level}>')
            continue

        # 水平线
        if re.match(r'^---+$', line.strip()):
            html_parts.append('<hr/>')
            continue

        # 空行
        if not line.strip():
            html_parts.append('<br/>')
            continue

        html_parts.append(f'<p>{inline(line)}</p>')

    if in_ul: html_parts.append('</ul>')
    if in_table: html_parts.append('</table></div>')
    return '\n'.join(html_parts)

def inline(text: str) -> str:
    """行内格式：加粗、斜体、代码、链接"""
    # links
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', text)
    # bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    # italic
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    # inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text

HTML_TEMPLATE = '''<!DOCTYPE html>
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
      --gradient-accent:linear-gradient(135deg,#5b6cf9 0%,#a78bfa 100%);
      --color-primary:#5b6cf9; --color-text:#1c1c1e;
      --color-text-secondary:#48484a; --color-text-muted:#8e8e93;
      --font-sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Helvetica Neue","PingFang SC",sans-serif;
      --font-mono:"SF Mono","Menlo","Monaco","Consolas",monospace;
    }}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    html{{scroll-behavior:smooth;}}
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
    .tag{{font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;}}
    .tag-encoding{{background:rgba(91,108,249,0.1);color:#5b6cf9;border:1px solid rgba(91,108,249,0.18);}}
    .tag-gpu{{background:rgba(255,159,10,0.1);color:#b56200;border:1px solid rgba(255,159,10,0.2);}}
    .tag-combined{{background:rgba(167,139,250,0.12);color:#6741d9;border:1px solid rgba(167,139,250,0.2);}}
    .article-title{{font-size:34px;font-weight:700;letter-spacing:-0.8px;line-height:1.2;margin-bottom:12px;}}
    .article-meta{{font-size:13px;color:var(--color-text-muted);}}

    .article-body{{
      background:var(--bg-card);border:1px solid var(--glass-border);
      border-radius:18px;box-shadow:var(--glass-shadow);
      backdrop-filter:blur(20px);padding:32px 36px;
    }}
    .article-body h1{{font-size:26px;font-weight:700;letter-spacing:-0.5px;margin:28px 0 12px;padding-bottom:8px;border-bottom:1px solid rgba(0,0,0,0.06);}}
    .article-body h1:first-child{{margin-top:0;}}
    .article-body h2{{font-size:20px;font-weight:700;margin:24px 0 10px;color:var(--color-text);}}
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
    .article-body th{{background:rgba(91,108,249,0.07);font-weight:700;text-align:left;padding:8px 12px;border-bottom:2px solid rgba(91,108,249,0.15);color:var(--color-text);}}
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

<div class="back-bar">
  <a href="../blog.html" class="back-link">← 返回列表</a>
</div>

<div class="article-wrap">
  <div class="article-header">
    <div class="article-tags">{tags}</div>
    <h1 class="article-title">{title}</h1>
    <div class="article-meta">📅 {date} &nbsp;·&nbsp; 数据库研究论文追踪</div>
  </div>
  <div class="article-body">
    {body}
  </div>
</div>

<script>
  function updateTime() {{
    const now = new Date();
    const h = now.getHours().toString().padStart(2,'0');
    const m = now.getMinutes().toString().padStart(2,'0');
    const days = ['周日','周一','周二','周三','周四','周五','周六'];
    document.getElementById('menubar-time').textContent = `${{days[now.getDay()]}} ${{h}}:${{m}}`;
  }}
  updateTime(); setInterval(updateTime, 60000);
</script>
</body>
</html>'''

# 文件映射
files = {
    "report_2026-03-16.md": ("report-2026-03-16.html", "2026-03-16", "数据库研究论文追踪报告 · 2026-03-16",
        ['<span class="tag tag-encoding">数据编码</span>', '<span class="tag tag-gpu">GPU 加速</span>']),
    "report_2026-03-16_supplement.md": ("report-2026-03-16-supplement.html", "2026-03-16 补充", "数据库研究论文追踪报告 · 2026-03-16 补充",
        ['<span class="tag tag-combined">编码 + GPU</span>']),
    "report_2026-03-17.md": ("report-2026-03-17.html", "2026-03-17", "数据库研究论文追踪报告 · 2026-03-17",
        ['<span class="tag tag-encoding">数据编码</span>', '<span class="tag tag-gpu">GPU 加速</span>']),
    "report_2026-03-18.md": ("report-2026-03-18.html", "2026-03-18", "数据库研究论文追踪报告 · 2026-03-18", []),
    "report_2026-03-19.md": ("report-2026-03-19.html", "2026-03-19", "数据库研究论文追踪报告 · 2026-03-19", []),
    "report_2026-03-20.md": ("report-2026-03-20.html", "2026-03-20", "数据库研究论文追踪报告 · 2026-03-20",
        ['<span class="tag tag-encoding">数据编码</span>', '<span class="tag tag-gpu">GPU 加速</span>']),
    "report_2026-03-21.md": ("report-2026-03-21.html", "2026-03-21", "数据库研究论文追踪报告 · 2026-03-21", []),
    "report_2026-03-22.md": ("report-2026-03-22.html", "2026-03-22", "数据库研究论文追踪报告 · 2026-03-22", []),
    "report_2026-03-23.md": ("report-2026-03-23.html", "2026-03-23", "数据库研究论文追踪报告 · 2026-03-23",
        ['<span class="tag tag-combined">编码 + GPU</span>']),
    "report_2026-03-26.md": ("report-2026-03-26.html", "2026-03-26", "数据库研究论文追踪报告 · 2026-03-26", []),
    "report_2026-03-27.md": ("report-2026-03-27.html", "2026-03-27", "数据库研究论文追踪报告 · 2026-03-27", []),
}

for md_name, (html_name, date, title, tags) in files.items():
    md_path = os.path.join(REPORTS_DIR, md_name)
    html_path = os.path.join(OUTPUT_DIR, html_name)
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    body = md_to_html(md_content)
    tags_html = ''.join(tags) if tags else '<span class="tag" style="background:rgba(0,0,0,0.05);color:#8e8e93;border:1px solid rgba(0,0,0,0.08)">日常追踪</span>'
    html = HTML_TEMPLATE.format(title=title, date=date, tags=tags_html, body=body)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ Generated: {html_name}")

print(f"\n🎉 All {len(files)} reports converted!")
