# -*- coding: utf-8 -*-
"""
ゲオモバイル キャンペーン＆UQ端末価格ウォッチャー
- キャンペーン一覧の新着を検知 → X / YouTube 用の下書きを自動生成
- 端末一覧の価格・在庫変動を記録（変動日つき）
- 結果を docs/ (GitHub Pages) に出力、新キャンペーン時は GitHub Issue で通知
ANTHROPIC_API_KEY があれば Claude API で下書き生成、なければテンプレ生成。
"""

import json
import os
import re
import sys
import html as html_mod
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- 設定
BASE = "https://mvno.geo-mobile.jp"
CAMPAIGN_LIST_URL = f"{BASE}/campaign/"
DEVICE_LIST_URL = f"{BASE}/uqmobile/smartphone/"

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
DOCS_DIR = ROOT / "docs"
DRAFTS_DIR = DOCS_DIR / "drafts"

JST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PLAN_NOTE = ("※表示価格はコミコミプランバリュー/トクトクプラン2＋"
             "増量オプションII契約時（機種変更除く・税込）")
AFF_PLACEHOLDER = "【アフィリンクに差し替え】"

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


def now_jst() -> datetime:
    return datetime.now(JST)


def jst_str() -> str:
    return now_jst().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 取得
def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def parse_campaigns(html: str) -> dict:
    """キャンペーン一覧ページから {url: title} を抽出"""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = BASE + href
        if not href.startswith(BASE + "/campaign/"):
            continue
        slug = href[len(BASE + "/campaign/"):].strip("/")
        if not slug or "#" in slug:
            continue
        # タイトル: img alt 優先、なければリンクテキスト
        title = ""
        img = a.find("img")
        if img and img.get("alt"):
            title = img["alt"].strip()
        if not title:
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        title = re.sub(r"詳細はこちら|詳しくはこちら", "", title).strip()
        if href not in found or (title and not found[href]):
            found[href] = title or slug
    return found


DEVICE_LINK_RE = re.compile(r"/uqmobile/smartphone/([A-Za-z0-9_\-]+)/?$")
PRICE_USED_RE = re.compile(r"中古端末価格\s*([\d,]+)円")
PRICE_MNP_RE = re.compile(r"MNP契約\s*([\d,]+)円")


def parse_devices(html: str) -> dict:
    """端末一覧ページから {slug: {name, used, mnp, stock}} を抽出"""
    soup = BeautifulSoup(html, "html.parser")
    devices = {}
    for a in soup.find_all("a", href=True):
        m = DEVICE_LINK_RE.search(a["href"])
        if not m:
            continue
        slug = m.group(1)
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not text:
            continue
        name = re.split(r"中古端末価格|MNP契約|在庫切れ", text)[0]
        name = re.sub(r"^(NEW|中古|新品)\s*", "", name).strip()
        used = PRICE_USED_RE.search(text)
        mnp = PRICE_MNP_RE.search(text)
        stock = "在庫切れ" not in text
        devices[slug] = {
            "name": name or slug,
            "used": int(used.group(1).replace(",", "")) if used else None,
            "mnp": int(mnp.group(1).replace(",", "")) if mnp else None,
            "stock": stock,
        }
    return devices


def extract_campaign_detail(url: str) -> dict:
    """キャンペーン個別ページから 見出し・要点を抽出"""
    detail = {"url": url, "title": "", "points": [], "text": ""}
    try:
        soup = BeautifulSoup(fetch(url), "html.parser")
    except Exception as e:
        print(f"  [warn] detail fetch failed: {url} ({e})", file=sys.stderr)
        return detail
    if soup.title:
        detail["title"] = soup.title.get_text(strip=True).split("｜")[0]
    h1 = soup.find("h1")
    if h1:
        detail["title"] = h1.get_text(strip=True) or detail["title"]
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    detail["text"] = body[:4000]
    # 「〜円割引」「1円」「最大〜円」「〜円分」などの訴求ポイントを拾う
    pts = re.findall(
        r"[^。 ]{0,25}(?:最大[\d,]+円[^。 ]{0,12}|[\d,]+円割引|"
        r"[\d,]+円分[^。 ]{0,10}|1円[〜～]?)",
        body,
    )
    seen = set()
    for p in pts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            detail["points"].append(p)
        if len(detail["points"]) >= 4:
            break
    return detail


# ---------------------------------------------------------------- 下書き生成
def drafts_template(d: dict) -> dict:
    title = d["title"] or "新キャンペーン"
    points = d["points"][:3]
    pt_lines = "\n".join(f"✅{p}" for p in points) if points else "✅詳細は下記リンクから"
    today = now_jst().strftime("%Y年%m月%d日")

    x_post = (
        f"【開始】ゲオモバイル×UQで新キャンペーンきたで\n"
        f"「{title}」\n\n"
        f"{pt_lines}\n\n"
        f"{PLAN_NOTE}\n"
        f"詳細はリプ欄👇"
    )
    x_reply = f"▼キャンペーン詳細・申し込みはこちら\n{AFF_PLACEHOLDER}\n（公式: {d['url']}）"
    yt_description = (
        f"━━━━━━━━━━━━━━━\n"
        f"📱{title}（ゲオモバイル / UQ mobile）\n"
        + "".join(f"・{p}\n" for p in points)
        + f"▼詳細・お申し込みはこちら\n{AFF_PLACEHOLDER}\n"
        f"※価格・条件は{today}時点の情報です。最新情報は公式サイトをご確認ください。\n"
        f"{PLAN_NOTE}\n"
        f"━━━━━━━━━━━━━━━"
    )
    yt_community = (
        f"【お知らせ】ゲオモバイル（UQ mobile代理店）で「{title}」が始まりました！\n"
        + "".join(f"・{p}\n" for p in points)
        + f"条件・対象端末など詳しくは概要欄のリンクからご確認ください。\n"
        f"{PLAN_NOTE}"
    )
    return {
        "x_post": x_post,
        "x_reply": x_reply,
        "yt_description": yt_description,
        "yt_community": yt_community,
        "generator": "template",
    }


def drafts_claude(d: dict) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    prompt = f"""あなたは日本のモバイル系YouTubeチャンネル「まさもばチャンネル」のライターです。
以下のキャンペーンページ情報から、SNS投稿の下書きをJSONだけで出力してください。

# スタイルルール（厳守）
- x_post: X本文。結果ファースト（お得額・1円などを冒頭付近に）。本文に外部リンクを入れない。カジュアルな関西弁。140〜200字程度。絵文字は控えめ（2〜4個）。末尾は「詳細はリプ欄👇」。
- x_reply: リプ用。リンクは「{AFF_PLACEHOLDER}」というプレースホルダを使う。公式URLも併記。
- yt_description: YouTube概要欄用ブロック。標準語・丁寧。リンクは「{AFF_PLACEHOLDER}」。取得日時点の情報である旨と「{PLAN_NOTE}」を必ず入れる。
- yt_community: YouTubeコミュニティ投稿用。標準語・丁寧・3〜5行。
- 誇大表現・断定的な最安表現は禁止（景表法配慮）。数字はページ情報にあるものだけ使う。

# キャンペーン情報
タイトル: {d['title']}
URL: {d['url']}
ページ本文（抜粋）: {d['text'][:3000]}

# 出力形式
{{"x_post": "...", "x_reply": "...", "yt_description": "...", "yt_community": "..."}}
JSON以外は一切出力しないこと。"""
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        r.raise_for_status()
        text = "".join(
            b.get("text", "") for b in r.json().get("content", [])
            if b.get("type") == "text"
        )
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        out = json.loads(text)
        out["generator"] = f"claude ({CLAUDE_MODEL})"
        return out
    except Exception as e:
        print(f"  [warn] Claude API failed, falling back to template: {e}",
              file=sys.stderr)
        return None


def save_draft_md(d: dict, drafts: dict) -> str:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_\-]", "_",
                  d["url"].rstrip("/").rsplit("/", 1)[-1])[:40]
    fname = f"{now_jst().strftime('%Y%m%d')}_{slug}.md"
    md = f"""# {d['title']}

- URL: {d['url']}
- 検知日時: {jst_str()} JST
- 生成方式: {drafts['generator']}

## X 本文
```
{drafts['x_post']}
```

## X リプ（リンク用）
```
{drafts['x_reply']}
```

## YouTube 概要欄ブロック
```
{drafts['yt_description']}
```

## YouTube コミュニティ投稿
```
{drafts['yt_community']}
```

> ⚠ 投稿前チェック: {AFF_PLACEHOLDER} を媒体別リンク台帳の該当列リンクに差し替え。数字・期間は公式ページで最終確認。
"""
    (DRAFTS_DIR / fname).write_text(md, encoding="utf-8")
    return fname


# ---------------------------------------------------------------- 通知（Issue）
def create_issue(title: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        print("  [info] GITHUB_TOKEN/REPOSITORY 無しのため Issue 通知スキップ")
        return
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "body": body, "labels": ["new-campaign"]},
            timeout=30,
        )
        r.raise_for_status()
        print(f"  [ok] Issue 作成: {r.json().get('html_url')}")
    except Exception as e:
        print(f"  [warn] Issue 作成失敗: {e}", file=sys.stderr)


# ---------------------------------------------------------------- HTML 出力
def esc(s) -> str:
    return html_mod.escape(str(s)) if s is not None else "—"


def yen(v) -> str:
    return f"{v:,}円" if isinstance(v, int) else "—"


def render_index(state: dict, new_campaign_files: list) -> None:
    camp_rows = ""
    for url, c in sorted(state["campaigns"].items(),
                         key=lambda x: x[1].get("first_seen", ""), reverse=True):
        camp_rows += (
            f"<tr><td><a href='{esc(url)}' target='_blank'>{esc(c['title'])}</a></td>"
            f"<td>{esc(c.get('first_seen', ''))}</td></tr>\n"
        )

    dev_rows = ""
    for slug, dv in sorted(state["devices"].items(),
                           key=lambda x: (x[1].get("mnp") is None,
                                          x[1].get("mnp") or 0)):
        stock = "在庫あり" if dv.get("stock") else "<span class='out'>在庫切れ</span>"
        dev_rows += (
            f"<tr><td>{esc(dv['name'])}</td>"
            f"<td class='num'>{yen(dv.get('mnp'))}</td>"
            f"<td class='num'>{yen(dv.get('used'))}</td>"
            f"<td>{stock}</td>"
            f"<td>{esc(dv.get('changed', '—'))}</td></tr>\n"
        )

    draft_links = ""
    all_drafts = sorted(DRAFTS_DIR.glob("*.md"), reverse=True)[:20]
    for f in all_drafts:
        badge = " 🆕" if f.name in new_campaign_files else ""
        draft_links += f"<li><a href='drafts/{esc(f.name)}'>{esc(f.name)}</a>{badge}</li>\n"

    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ゲオモバイル キャンペーン＆価格ウォッチ</title>
<style>
body{{font-family:"Hiragino Sans","Yu Gothic",sans-serif;margin:16px;color:#222;max-width:900px}}
h1{{font-size:1.3em}} h2{{font-size:1.1em;border-left:4px solid #0a7;padding-left:8px;margin-top:28px}}
table{{border-collapse:collapse;width:100%;font-size:.9em}}
th,td{{border:1px solid #ccc;padding:6px 8px}} th{{background:#f2f7f5}}
td.num{{text-align:right;white-space:nowrap}} .out{{color:#c00}}
.meta{{color:#666;font-size:.85em}}
</style></head><body>
<h1>ゲオモバイル（UQ mobile）キャンペーン＆価格ウォッチ</h1>
<p class="meta">データ更新日時(JST): {jst_str()}（GitHub Actionsで自動更新）</p>

<h2>投稿下書き（新着順）</h2>
<ul>{draft_links or "<li>まだありません</li>"}</ul>

<h2>キャンペーン一覧（検知順）</h2>
<table><tr><th>キャンペーン</th><th>初回検知日</th></tr>
{camp_rows}</table>

<h2>端末価格（MNP安い順）</h2>
<table><tr><th>機種</th><th>MNP契約</th><th>中古端末価格</th><th>在庫</th><th>最終変動日</th></tr>
{dev_rows}</table>
<p class="meta">{esc(PLAN_NOTE)}。価格は取得時点・税込。</p>
</body></html>"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")


# ---------------------------------------------------------------- メイン
def main() -> None:
    state = {"campaigns": {}, "devices": {}}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    first_run = not state["campaigns"]

    # --- キャンペーン
    campaigns_now = parse_campaigns(fetch(CAMPAIGN_LIST_URL))
    new_urls = [u for u in campaigns_now if u not in state["campaigns"]]
    for url, title in campaigns_now.items():
        entry = state["campaigns"].setdefault(
            url, {"title": title, "first_seen": now_jst().strftime("%Y-%m-%d")})
        if title:
            entry["title"] = title

    # --- 端末価格
    devices_now = parse_devices(fetch(DEVICE_LIST_URL))
    for slug, dv in devices_now.items():
        old = state["devices"].get(slug)
        if old and (old.get("mnp") != dv["mnp"] or old.get("used") != dv["used"]
                    or old.get("stock") != dv["stock"]):
            dv["changed"] = now_jst().strftime("%Y/%m/%d")
        else:
            dv["changed"] = (old or {}).get("changed", "—")
        state["devices"][slug] = dv

    # --- 新キャンペーン → 下書き生成＆通知（初回実行は既存分を通知しない）
    new_files = []
    if not first_run:
        for url in new_urls:
            print(f"[new campaign] {url}")
            detail = extract_campaign_detail(url)
            if not detail["title"]:
                detail["title"] = campaigns_now.get(url, url)
            drafts = drafts_claude(detail) or drafts_template(detail)
            fname = save_draft_md(detail, drafts)
            new_files.append(fname)
            create_issue(
                f"【新キャンペーン】{detail['title']}",
                f"検知: {jst_str()} JST\nURL: {detail['url']}\n\n"
                f"下書き: `docs/drafts/{fname}`\n\n---\n\n"
                f"### X 本文\n```\n{drafts['x_post']}\n```\n"
                f"### X リプ\n```\n{drafts['x_reply']}\n```\n"
                f"### YouTube 概要欄\n```\n{drafts['yt_description']}\n```\n"
                f"### YouTube コミュニティ\n```\n{drafts['yt_community']}\n```\n",
            )
    else:
        print(f"[info] 初回実行: 既存キャンペーン {len(new_urls)} 件を記録のみ")

    render_index(state, new_files)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"[done] campaigns={len(state['campaigns'])} "
          f"devices={len(state['devices'])} new={len(new_files)}")


if __name__ == "__main__":
    main()
