#!/usr/bin/env python3
"""
sync_vla_articles.py
自动检测 VLA 文章 → 生成 HTML → 更新 vla.html → 推送 GitHub
"""
import os, re, subprocess, json
from datetime import datetime
from pathlib import Path

ARTICLES_DIR  = "/Users/adam/WorkBuddy/20260401174510/articles"
SITE_DIR     = "/Users/adam/WorkBuddy/20260324123505"
OUTPUT_DIR   = os.path.join(SITE_DIR, "vla-articles")
VLA_HTML     = os.path.join(SITE_DIR, "vla.html")
INDEX_HTML   = os.path.join(SITE_DIR, "index.html")
STATE_FILE   = os.path.join(SITE_DIR, ".workbuddy", "vla_state.json")
GIT_BRANCH   = "gh-pages"
GIT_USER     = "ColdZoo"
GIT_REPO_URL = "github.com/ColdZoo/coldzoo.github.io.git"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)


def get_github_token():
    r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return token if token else ""


# ──────────────────────────────────────────────
# 1. Markdown → HTML 转换
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
# 2. 解析文章文件名 → 元数据
# ──────────────────────────────────────────────
def parse_article_filename(fname: str):
    """
    01_扩散策略数学基础与2025前沿改进.md
    → num=01, title=扩散策略数学基础与2025前沿改进, slug=01-diffusion-robot
    """
    m = re.match(r'^(\d{2})_(.+)\.md$', fname)
    if m:
        num = m.group(1)
        raw_title = m.group(2)
        # 清理标题：去掉下划线，还原空格
        clean_title = raw_title.replace('_', ' ')
        slug = f"{num}-{clean_title[:20].replace(' ', '-')}"
        return num, clean_title, slug
    return None


def extract_excerpt(md_content: str, max_chars=120) -> str:
    for line in md_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('|') or line.startswith('-') or line.startswith('*'):
            continue
        text = re.sub(r'[#*`\[\]()]', '', line)[:max_chars]
        if len(text) > 20:
            return text + '……'
    return 'VLA 机器人控制与扩散策略系列研究……'


def detect_tags(md_content: str) -> list:
    lower = md_content.lower()
    tags = []
    if any(k in lower for k in ['扩散', 'ddpm', 'flow matching', 'ddim']):
        tags.append('<span class="tag tag-diffusion">扩散模型</span>')
    if any(k in lower for k in ['vla', 'vision-language', 'go-1', 'acot', 'π0', 'pi-zero']):
        tags.append('<span class="tag tag-vla">VLA架构</span>')
    if any(k in lower for k in ['loss', 'l1', 'huber', '损失函数']):
        tags.append('<span class="tag tag-loss">损失函数</span>')
    if any(k in lower for k in ['语义', 'latent', '中间层', 'semantic']):
        tags.append('<span class="tag tag-semantic">语义层</span>')
    if any(k in lower for k in ['action chunk', 'chunk', '时序', 'temporal']):
        tags.append('<span class="tag tag-temporal">时序建模</span>')
    if any(k in lower for k in ['cfg', 'classifier-free', 'guidance']):
        tags.append('<span class="tag tag-cfg">CFG</span>')
    if any(k in lower for k in ['推理', 'ddim', 'dpm-solver', 'tensorrt', '量化']):
        tags.append('<span class="tag tag-inference">推理优化</span>')
    if any(k in lower for k in ['训练', '分布式', '混合精度', '课程学习', 'lora']):
        tags.append('<span class="tag tag-training">训练策略</span>')
    if any(k in lower for k in ['多模态', '视觉编码', 'siglip', 'dino', 'depth']):
        tags.append('<span class="tag tag-multimodal">多模态</span>')
    if any(k in lower for k in ['agibot', '比赛', 'challenge', '实战']):
        tags.append('<span class="tag tag-competition">比赛实战</span>')
    if not tags:
        tags.append('<span class="tag tag-default">综述</span>')
    return tags


# ──────────────────────────────────────────────
# 3. 文章 HTML 模板
# ──────────────────────────────────────────────
ARTICLE_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title} · 蔡政</title>
  <script>
    window.MathJax = {
      tex: {
        inlineMath: [['$', '$'], ['\\(', '\\)']],
        displayMath: [['$$', '$$'], ['\\[', '\\]']],
      },
      svg: { fontCache: 'global' },
      startup: { ready: () => MathJax.startup.defaultReady() }
    };
  </script>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js" async></script>
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
    .back-bar{{max-width:800px;margin:0 auto;padding:20px 24px 0;}}
    .back-link{{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--color-primary);text-decoration:none;padding:6px 12px;border-radius:8px;background:rgba(91,108,249,0.07);transition:all 0.15s;}}
    .back-link:hover{{background:rgba(91,108,249,0.13);}}
    .article-wrap{{max-width:800px;margin:0 auto;padding:20px 24px 100px;}}
    .article-header{{margin-bottom:36px;}}
    .article-tags{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;}}
    .tag{{font-size:11px;font-weight:600;padding:3px 9px;border-radius:7px;border:1px solid transparent;}}
    .tag-diffusion{{background:rgba(91,108,249,0.1);color:#5b6cf9;border-color:rgba(91,108,249,0.18);}}
    .tag-vla{{background:rgba(16,185,129,0.1);color:#059669;border-color:rgba(16,185,129,0.2);}}
    .tag-loss{{background:rgba(239,68,68,0.1);color:#dc2626;border-color:rgba(239,68,68,0.2);}}
    .tag-semantic{{background:rgba(139,92,246,0.1);color:#7c3aed;border-color:rgba(139,92,246,0.2);}}
    .tag-temporal{{background:rgba(245,158,11,0.1);color:#b45309;border-color:rgba(245,158,11,0.2);}}
    .tag-cfg{{background:rgba(236,72,153,0.1);color:#db2777;border-color:rgba(236,72,153,0.2);}}
    .tag-inference{{background:rgba(59,130,246,0.1);color:#2563eb;border-color:rgba(59,130,246,0.2);}}
    .tag-training{{background:rgba(34,197,94,0.1);color:#16a34a;border-color:rgba(34,197,94,0.2);}}
    .tag-multimodal{{background:rgba(249,115,22,0.1);color:#ea580c;border-color:rgba(249,115,22,0.2);}}
    .tag-competition{{background:rgba(234,179,8,0.1);color:#ca8a04;border-color:rgba(234,179,8,0.2);}}
    .tag-default{{background:rgba(0,0,0,0.05);color:#8e8e93;border-color:rgba(0,0,0,0.08);}}
    .article-title{{font-size:34px;font-weight:700;letter-spacing:-0.8px;line-height:1.2;margin-bottom:12px;}}
    .article-meta{{font-size:13px;color:var(--color-text-muted);}}
    .article-series{{display:inline-block;margin-bottom:16px;font-size:12px;font-weight:700;padding:4px 12px;border-radius:999px;background:linear-gradient(135deg,#5b6cf9,#a78bfa);color:#fff;}}
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
  <a href="vla.html" class="menu-item">← VLA 文章</a>
  <span class="spacer"></span>
  <span class="menubar-time" id="menubar-time"></span>
</nav>
<div class="back-bar"><a href="vla.html" class="back-link">← 返回列表</a></div>
<div class="article-wrap">
  <div class="article-header">
    <div class="article-series">第 {num} 篇 · 共 10 篇</div>
    <div class="article-tags">{tags}</div>
    <h1 class="article-title">{title}</h1>
    <div class="article-meta">📅 2026-04-02 &nbsp;·&nbsp; VLA 机器人控制系列文章</div>
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
# 4. 扫描所有文章并生成 HTML
# ──────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"processed": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def build_all_articles():
    state = load_state()
    processed = set(state["processed"])
    new_count = 0
    all_articles = []

    md_files = sorted(
        [f for f in os.listdir(ARTICLES_DIR) if f.endswith('.md')],
        reverse=True
    )

    for fname in md_files:
        parsed = parse_article_filename(fname)
        if not parsed:
            continue
        num, clean_title, slug = parsed
        html_name = f"article-{slug}.html"
        md_path = os.path.join(ARTICLES_DIR, fname)
        html_path = os.path.join(OUTPUT_DIR, html_name)

        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        tags = detect_tags(md_content)
        excerpt = extract_excerpt(md_content)

        all_articles.append({
            "num": num,
            "fname": fname,
            "html": html_name,
            "title": clean_title,
            "tags": tags,
            "excerpt": excerpt,
        })

        if fname not in processed or not os.path.exists(html_path):
            body = md_to_html(md_content)
            tags_html = ''.join(tags)
            html = ARTICLE_TEMPLATE.format(
                num=num,
                title=clean_title,
                tags=tags_html,
                body=body
            )
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"  ✅ 生成: {html_name}")
            new_count += 1
            processed.add(fname)

    save_state({"processed": list(processed)})
    # 按编号升序排列（01, 02, ... 10）
    all_articles.sort(key=lambda x: x["num"])
    return all_articles, new_count


# ──────────────────────────────────────────────
# 5. 重建 vla.html 列表页
# ──────────────────────────────────────────────
VLA_LIST_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>VLA 机器人控制 · 蔡政</title>
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
    .menubar{{position:sticky;top:0;z-index:100;height:48px;background:rgba(242,241,246,0.88);backdrop-filter:blur(24px) saturate(1.8);border-bottom:1px solid rgba(0,0,0,0.07);display:flex;align-items:center;padding:0 20px;gap:16px;}}
    .menubar .logo{{font-size:15px;font-weight:700;color:var(--color-text);text-decoration:none;}}
    .menubar .menu-item{{font-size:13px;font-weight:500;padding:4px 10px;border-radius:6px;color:var(--color-text);text-decoration:none;transition:background 0.15s;}}
    .menubar .menu-item:hover{{background:rgba(0,0,0,0.07);}}
    .menubar .spacer{{flex:1;}}
    .menubar-time{{font-size:13px;font-weight:500;color:var(--color-text-secondary);}}
    .page-wrap{{max-width:860px;margin:0 auto;padding:40px 24px 120px;}}
    .page-header{{margin-bottom:36px;}}
    .page-header h1{{font-size:40px;font-weight:700;letter-spacing:-1px;margin-bottom:10px;}}
    .page-header p{{font-size:15px;color:var(--color-text-secondary);line-height:1.6;}}
    .series-banner{{background:linear-gradient(135deg,#5b6cf9,#a78bfa,#818cf8);border-radius:20px;padding:24px 28px;margin-bottom:32px;color:#fff;}}
    .series-banner h2{{font-size:22px;font-weight:700;margin-bottom:6px;}}
    .series-banner p{{font-size:14px;opacity:0.9;}}
    .series-meta{{display:flex;gap:16px;margin-top:12px;font-size:13px;opacity:0.85;}}
    .report-list{{display:flex;flex-direction:column;gap:12px;}}
    .report-card{{background:var(--bg-card);border:1px solid var(--glass-border);border-radius:16px;box-shadow:var(--glass-shadow);backdrop-filter:blur(20px);padding:20px 24px;text-decoration:none;color:inherit;display:flex;align-items:center;gap:16px;transition:transform 0.15s,box-shadow 0.15s;}}
    .report-card:hover{{transform:translateX(4px);box-shadow:0 12px 40px rgba(60,60,100,0.14);}}
    .report-card .card-left{{flex:1;}}
    .card-tags{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;}}
    .tag{{font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px;border:1px solid transparent;}}
    .tag-diffusion{{background:rgba(91,108,249,0.1);color:#5b6cf9;border-color:rgba(91,108,249,0.18);}}
    .tag-vla{{background:rgba(16,185,129,0.1);color:#059669;border-color:rgba(16,185,129,0.2);}}
    .tag-loss{{background:rgba(239,68,68,0.1);color:#dc2626;border-color:rgba(239,68,68,0.2);}}
    .tag-semantic{{background:rgba(139,92,246,0.1);color:#7c3aed;border-color:rgba(139,92,246,0.2);}}
    .tag-temporal{{background:rgba(245,158,11,0.1);color:#b45309;border-color:rgba(245,158,11,0.2);}}
    .tag-cfg{{background:rgba(236,72,153,0.1);color:#db2777;border-color:rgba(236,72,153,0.2);}}
    .tag-inference{{background:rgba(59,130,246,0.1);color:#2563eb;border-color:rgba(59,130,246,0.2);}}
    .tag-training{{background:rgba(34,197,94,0.1);color:#16a34a;border-color:rgba(34,197,94,0.2);}}
    .tag-multimodal{{background:rgba(249,115,22,0.1);color:#ea580c;border-color:rgba(249,115,22,0.2);}}
    .tag-competition{{background:rgba(234,179,8,0.1);color:#ca8a04;border-color:rgba(234,179,8,0.2);}}
    .tag-default{{background:rgba(0,0,0,0.05);color:#8e8e93;border-color:rgba(0,0,0,0.08);}}
    .card-num{{font-size:28px;font-weight:800;background:linear-gradient(135deg,#5b6cf9,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;min-width:48px;text-align:center;}}
    .card-title{{font-size:16px;font-weight:700;margin-bottom:4px;color:var(--color-text);}}
    .card-excerpt{{font-size:13px;color:var(--color-text-muted);line-height:1.5;}}
    .card-arrow{{font-size:18px;color:var(--color-primary);opacity:0.5;transition:opacity 0.15s;}}
    .report-card:hover .card-arrow{{opacity:1;}}
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
    <h1>🤖 VLA 机器人控制系列</h1>
    <p>扩散模型 × 视觉-语言-动作（VLA）架构在机器人控制中的原理、优化与实战</p>
  </div>
  <div class="series-banner">
    <h2>📚 完整系列 · 共 10 篇</h2>
    <p>从扩散策略数学基础到 AgiBot World Challenge 2026 比赛实战，深度覆盖 GO-1、ACoT-VLA、π0、GR00T-N1 等前沿模型</p>
    <div class="series-meta">
      <span>🎯 核心模型：ACoT-VLA / GO-1 / π0 / GR00T-N1</span>
      <span>📐 关键优化：L1 Loss · CFG · Action Chunking · Latent Diffusion</span>
    </div>
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
</script>
</body>
</html>'''


def build_card(article):
    tags_html = ''.join(article["tags"])
    return f'''    <a href="vla-articles/{article["html"]}" class="report-card">
      <div class="card-num">{article["num"]}</div>
      <div class="card-left">
        <div class="card-tags">{tags_html}</div>
        <div class="card-title">{article["title"]}</div>
        <div class="card-excerpt">{article["excerpt"]}</div>
      </div>
      <div class="card-arrow">→</div>
    </a>'''


def rebuild_vla_html(all_articles):
    cards = '\n'.join(build_card(a) for a in all_articles)
    html = VLA_LIST_TEMPLATE.format(cards=cards)
    with open(VLA_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✅ vla.html 已更新（{len(all_articles)} 篇）")


# ──────────────────────────────────────────────
# 6. 更新主页博客板块（加入 VLA 系列入口）
# ──────────────────────────────────────────────
def update_index_blog(all_articles):
    if not os.path.exists(INDEX_HTML):
        print("  ⚠️  index.html 不存在，跳过")
        return
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()

    # 生成 VLA 文章入口
    vla_card = f'''<a href="vla.html" class="blog-item" style="background:linear-gradient(135deg,#5b6cf9,#a78bfa);color:#fff;">
      <div>
        <div class="blog-meta" style="color:rgba(255,255,255,0.75);">
          <span class="blog-category" style="background:rgba(255,255,255,0.2);color:#fff;">系列文章</span>
          <span class="blog-date">2026-04-02</span>
        </div>
        <div class="blog-title" style="color:#fff;">🤖 VLA 机器人控制系列 · 共 10 篇</div>
        <div class="blog-excerpt" style="color:rgba(255,255,255,0.8);">扩散模型 × 视觉-语言-动作架构：ACoT-VLA、GO-1、π0、GR00T-N1 深度解析</div>
      </div>
      <span class="blog-arrow" style="color:#fff;">→</span>
    </a>'''

    # 替换 blog-list 区域
    new_content = re.sub(
        r'(<div class="blog-list">\s*)(.*?)(\s*</div>\s*(?:<div[^>]*btn-secondary[^>]*>.*?</div>)?)',
        lambda m: m.group(1) + vla_card + '\n    ' + m.group(2) + m.group(3),
        content,
        flags=re.DOTALL
    )
    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"  ✅ index.html 已更新（加入 VLA 系列入口）")


# ──────────────────────────────────────────────
# 7. Git 推送
# ──────────────────────────────────────────────
def git_push(new_count, total):
    os.chdir(SITE_DIR)
    subprocess.run(['git', 'checkout', GIT_BRANCH], capture_output=True)
    subprocess.run(['git', 'add', '-A'], capture_output=True)

    result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True)
    if result.returncode == 0:
        print("  ℹ️  没有新内容，跳过推送")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    msg = f"Auto: sync {new_count} VLA article(s) [{today}] (total {total})"
    subprocess.run(['git', 'commit', '-m', msg], capture_output=True)

    token = get_github_token()
    if not token:
        print("  ❌ 推送失败: 无法获取 GitHub token")
        return False

    push_repo = f"https://x-access-token:{token}@{GIT_REPO_URL}"
    subprocess.run(['git', 'remote', 'set-url', 'origin', push_repo], capture_output=True)
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
    print(f"  VLA Articles Sync  [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"{'='*50}")

    print("\n📄 扫描 VLA 文章...")
    all_articles, new_count = build_all_articles()
    print(f"  共 {len(all_articles)} 篇文章，新增 {new_count} 篇")

    if new_count > 0 or len(all_articles) > 0:
        print("\n📝 重建 vla.html...")
        rebuild_vla_html(all_articles)

        print("\n🏠 更新主页 VLA 系列入口...")
        update_index_blog(all_articles)

        print("\n🚀 推送到 GitHub...")
        git_push(new_count, len(all_articles))
    else:
        print("\n✅ 没有新文章，无需更新")

    print(f"\n✨ 同步完成！VLA 系列: https://coldzoo.github.io/vla.html\n")
