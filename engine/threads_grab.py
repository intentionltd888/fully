#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
threads_grab — Threads 貼文解析（兩版共用）。

貼一則 Threads 貼文的網址，抓下貼文裡的原始檔，不是動態牆上的縮圖：
  圖片    貼文附的最大那張（image_versions2 的候選裡面積最大的）
  影片    最高畫質。直連的 mp4（video_versions）已含聲音，但多半限在 720p；DASH 清單的畫面軌常有原始解析度，
          比直連大就用清單的畫面軌＋聲音軌（下載端 core.fetch_dash 接成一支、保證 QuickTime 可播），直連的當備援
  輪播    每一項（圖或影片）都存
  串文    作者自己接在下面的每一則也一起存；貼文本身沒有圖或影片、但引用了一則有的，抓被引用的那則
支援：
  https://www.threads.com/@帳號/post/代碼    threads.net 一樣；?xmt=… 之類的參數、結尾的 /media 不影響
  https://www.threads.com/t/代碼             短網址
  https://www.threads.com/@帳號              個人頁（含 /media 分頁）：頁面一次只給最近幾則，抓那幾則裡的圖與影片
只讀公開的貼文，不帶任何帳號資料。

頁面要用瀏覽器「開新分頁」時的那組標頭（Accept＋Sec-Fetch-*）去要，伺服器才會把貼文資料直接寫進
HTML 的 <script type="application/json" data-sjs>；只帶 User-Agent 拿到的是等 JS 再載入的空殼。
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import core
import core as pg
from core import T, UA, TIMEOUT, OPT, log, die, read_body, with_retry, Session, picked, img_done, iri
# 事件一律走 pg.emit：grab.py 會換掉它來攔 done（記資料夾 → 寫來源欄、出總覽圖），from-import 的 emit 攔不到

core.LABELS += [("threads.", "Threads")]

REFERER = "https://www.threads.com/"
NAV_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
PROFILE_TABS = ("media", "replies", "reposts")


def claims(host):
    """grab.py 問：這個主機歸不歸這裡管。"""
    return any(host == d or host.endswith("." + d) for d in ("threads.net", "threads.com"))


def _segs(url):
    return [s for s in urllib.parse.urlparse(url).path.split("/") if s]


def handles(url):
    """單則貼文、短網址、個人頁才歸這裡；其他頁面（搜尋、首頁）交回通用掃圖。"""
    s = _segs(url)
    if len(s) >= 3 and s[0].startswith("@") and s[1] == "post":
        return True
    if len(s) >= 2 and s[0] == "t":
        return True
    return bool(s) and s[0].startswith("@") and len(s[0]) > 1 and (len(s) == 1 or s[1] in PROFILE_TABS)


def post_code(url):
    """網址裡的貼文代碼；個人頁回 None。"""
    s = _segs(url)
    if len(s) >= 3 and s[0].startswith("@") and s[1] == "post":
        return s[2]
    if len(s) >= 2 and s[0] == "t":
        return s[1]
    return None


def _profile_name(url):
    s = _segs(url)
    return urllib.parse.unquote(s[0][1:]) if s and s[0].startswith("@") else ""


# ─── 讀頁面 ──────────────────────────────────────────────────────────────

def fetch_page(sess, url):
    req = urllib.request.Request(iri(url), headers=NAV_HEADERS)

    def once():
        resp = sess.opener.open(req, timeout=TIMEOUT)
        return resp.geturl(), read_body(resp)
    return with_retry(once, "開網頁")


SJS = re.compile(r'<script type="application/json"[^>]*\bdata-sjs\b[^>]*>(.*?)</script>', re.S)


def _walk(o):
    """依文件順序走過整棵 JSON 的每一個物件（迭代，資料有十幾層深）。"""
    stack = [o]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            yield x
            stack.extend(reversed(list(x.values())))
        elif isinstance(x, list):
            stack.extend(reversed(x))


def _is_post(d):
    return bool(d.get("code")) and "media_type" in d and isinstance(d.get("user"), dict)


def _author(post):
    return ((post.get("user") or {}).get("username") or "").lower()


def page_posts(html):
    """頁面資料裡的每一則貼文，依出現順序（代碼 → 貼文）。同一則出現好幾次（主文、串文、相關貼文）只留欄位最多的那份。"""
    posts = {}
    for blob in SJS.findall(html or ""):
        if '"media_type"' not in blob:
            continue
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for d in _walk(data):
            if _is_post(d):
                old = posts.get(d["code"])
                if old is None or len(d) > len(old):
                    posts[d["code"]] = d
    return posts


# ─── 一則貼文 → 要下載的檔 ─────────────────────────────────────────────────

def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _iso_seconds(s):
    """DASH 的長度（PT1M2.5S）→ 秒數；讀不懂回 0。"""
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", s or "")
    if not m:
        return 0
    h, mi, sec = (float(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + sec


MPD = "{urn:mpeg:dash:schema:mpd:2011}"


def dash_tracks(manifest):
    """DASH 清單 → (畫面軌, 聲音軌, 秒數)。畫面軌＝面積最大（同面積取位元率高的）的 (網址, 寬, 高)；
    聲音軌＝位元率最高的網址。每一軌的 BaseURL 就是一個完整的 mp4（不是切片）。讀不懂回 (None, None, 0)。"""
    if not manifest:
        return None, None, 0
    try:
        root = ET.fromstring(manifest)
    except ET.ParseError:
        return None, None, 0
    vids, auds = [], []
    for aset in root.iter(MPD + "AdaptationSet"):
        kind = aset.get("contentType") or ""
        for rep in aset.iter(MPD + "Representation"):
            base = rep.find(MPD + "BaseURL")
            url = (base.text or "").strip() if base is not None else ""
            if not url.startswith("http"):
                continue
            mime = rep.get("mimeType") or aset.get("mimeType") or ""
            bw = _int(rep.get("bandwidth"))
            if kind == "video" or mime.startswith("video"):
                w, h = _int(rep.get("width")), _int(rep.get("height"))
                vids.append((w * h, bw, url, w, h))
            elif kind == "audio" or mime.startswith("audio"):
                auds.append((bw, url))
    v = max(vids) if vids else None
    a = max(auds) if auds else None
    return ((v[2], v[3], v[4]) if v else None), (a[1] if a else None), _iso_seconds(root.get("mediaPresentationDuration"))


# 直連的 mp4 是 720p 級（短邊 720；橫的寬 1280）。清單的畫面軌短邊比這大才值得接兩軌（常要轉檔）
PROGRESSIVE_SHORT = 720


def _image(m):
    """→ (網址, 寬, 高, 備援, 預覽縮圖)：面積最大的那張；次大兩張當備援（原圖偶爾 403）；預覽用寬 ≥320 裡最小的。"""
    cands = [c for c in ((m.get("image_versions2") or {}).get("candidates") or [])
             if isinstance(c, dict) and c.get("url")]
    if not cands:
        return None, None, None, [], None
    cands.sort(key=lambda c: (_int(c.get("width")) * _int(c.get("height"))), reverse=True)
    best = cands[0]
    small = [c for c in cands if _int(c.get("width")) >= 320]
    thumb = (small[-1] if small else cands[-1])["url"]
    return best["url"], _int(best.get("width")) or None, _int(best.get("height")) or None, \
        [c["url"] for c in cands[1:3]], thumb


def _video(m):
    """影片項 → (網址, 寬, 高, 備援, dash) 或 None。dash＝(聲音軌網址, 秒數)：網址是清單的畫面軌，下載端接上聲音軌。"""
    vv = [v for v in (m.get("video_versions") or []) if isinstance(v, dict) and v.get("url")]
    prog = list(dict.fromkeys(v["url"] for v in sorted(vv, key=lambda v: _int(v.get("type")) or 999)))
    track, audio, secs = dash_tracks(m.get("video_dash_manifest") or "")
    if track and min(track[1], track[2]) > PROGRESSIVE_SHORT:
        return track[0], track[1], track[2], prog, (audio, secs)
    if prog:
        return prog[0], _int(m.get("original_width")) or None, _int(m.get("original_height")) or None, prog[1:], None
    if track:                                   # 沒有直連的版本（少見）：照樣接清單
        return track[0], track[1], track[2], [], (audio, secs)
    return None


def _caption(post):
    text = ((post.get("caption") or {}).get("text") or "").strip()
    return text.splitlines()[0].strip() if text else ""


def post_rows(post):
    """一則貼文 → 要下載的檔（輪播展開）。id 用每一項自己的 pk（純數字，existing_ids 認得，抓過的下次會跳過）。"""
    if not isinstance(post, dict):
        return []
    items = [m for m in (post.get("carousel_media") or [post]) if isinstance(m, dict)]
    base = {"title": _caption(post), "referer": REFERER}
    rows = []
    for k, m in enumerate(items, 1):
        rid = str(m.get("pk") or str(m.get("id") or "").split("_")[0] or f"{post.get('pk') or post['code']}{k:02d}")
        url, w, h, alts, thumb = _image(m)
        v = _video(m)
        if v:
            vurl, vw, vh, valts, dash = v
            row = dict(base, id=rid, url=vurl, w=vw, h=vh, alts=valts, video=True, thumb=thumb or vurl)
            if dash:
                row["dash"] = dash
            if m.get("video_duration"):
                row["duration"] = m.get("video_duration")
            elif dash and dash[1]:
                row["duration"] = dash[1]
            rows.append(row)
        elif url:
            rows.append(dict(base, id=rid, url=url, w=w, h=h, alts=alts, thumb=thumb))
    return rows


def _thread(posts, main):
    """主文＋作者自己接在下面的串文（依頁面順序）；被引用的別人貼文另外回。"""
    own, quoted, seen = [main], [], {main["code"]}
    who = _author(main)
    for d in _walk(main.get("text_post_app_info") or {}):
        if _is_post(d) and d["code"] not in seen:
            seen.add(d["code"])
            full = posts.get(d["code"]) or d
            (own if _author(full) == who else quoted).append(full)
    return own, quoted


# ─── 解析：網址 → (要下載的檔, 資料夾名, 標示) ─────────────────────────────

def resolve(sess, url, quiet=False):
    """quiet：預覽時不發提醒（只有真的抓的時候才講）。"""
    url = url.strip().strip("<>\"' ")
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    log(f"  → 解析連結 {url}")
    try:
        final_url, html = fetch_page(sess, url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            die(T("找不到這則貼文。可能已被刪除，或不是公開的。", "Post not found. It may have been deleted, or it isn't public."))
        die(T(f"打不開這個連結（HTTP {e.code}）。確認一下網址對不對。",
              f"Couldn't open this link (HTTP {e.code}). Check the address."))
    except Exception as e:
        die(T(f"連線失敗：{e}", f"Connection failed: {e}"))

    posts = page_posts(html)
    code = post_code(final_url) or post_code(url)
    if code:
        main = posts.get(code)
        if not main:
            die(T("讀不到這則貼文的內容。可能不是公開的，或 Threads 改版了。",
                  "Couldn't read this post. It may not be public, or Threads changed something."))
        own, quoted = _thread(posts, main)
        rows = [r for p in own for r in post_rows(p)]
        if not rows:
            rows = [r for p in quoted for r in post_rows(p)]
            if rows and not quiet:
                pg.emit(type="notice", message=T("這則貼文本身沒有圖或影片，抓的是它引用的那則",
                                              "This post has no images or videos of its own — grabbing the post it quotes"))
        if not rows:
            die(T("這則貼文只有文字，沒有圖片或影片。", "This post is text only — no images or videos."))
        who = (main.get("user") or {}).get("username") or ""
        cap = _caption(main)
        name = f"@{who} {cap[:40]}".strip() if cap else f"@{who} {code}"
        if len(own) > 1:
            log(f"  串文 {len(own)} 則")
        return rows, name, T("Threads 貼文", "Threads post")

    who = _profile_name(final_url) or _profile_name(url)
    mine = [p for p in posts.values() if _author(p) == who.lower()]
    rows = [r for p in mine for r in post_rows(p)]
    if not mine:
        die(T("讀不到這個個人頁的貼文。可能不是公開的帳號，或 Threads 改版了。",
              "Couldn't read posts on this profile. The account may not be public, or Threads changed something."))
    if not rows:
        die(T(f"這個個人頁最近 {len(mine)} 則貼文都沒有圖片或影片。",
              f"The latest {len(mine)} posts on this profile have no images or videos."))
    if not quiet:
        pg.emit(type="notice", message=T(f"個人頁一次只讀得到最近 {len(mine)} 則貼文，先抓這幾則；要某一則的完整串文，貼那則的網址",
                                      f"A profile only shows its latest {len(mine)} posts at once — grabbing those. For a full thread, paste that post's link"))
    return rows, f"@{who}", T("Threads 個人頁", "Threads profile")


def grab_post(url, dest, sess):
    rows, name, label = resolve(sess, url)
    rows = picked(rows)
    folder = os.path.join(dest, pg.safe_name(name, 60, keep_space=True) or "threads")
    nv = sum(1 for r in rows if r.get("video"))

    log(f"\n  {label}：{name}")
    log(f"  檔數：{len(rows)}" + (f"（其中影片 {nv} 支）" if nv else ""))
    log(f"  存到：{folder}\n")
    pg.emit(type="source", kind="threads", name=name, count=len(rows), folder=folder, label=label)

    seen = pg.Seen(folder)                       # 追蹤個人頁：之後的檢查只抓新的
    res = pg.download(rows, folder, dedup=pg.DEDUP, seen=seen, only_new=OPT["sub"])
    log(f"\n  完成 — 新下載 {res.ok} 個"
        + (f"（影片 {res.videos} 支）" if res.videos else "")
        + (f"、已存在跳過 {res.skipped} 個" if res.skipped else "")
        + (f"、一模一樣已經有的 {res.dups} 個" if res.dups else "")
        + (f"、失敗 {res.failed} 個" if res.failed else ""))
    pg.emit(type="done", added=res.ok, skipped=res.skipped, failed=res.failed, folder=folder,
         headline=name[:40], **img_done(res))


def probe(url):
    rows, name, _ = resolve(Session(), url, quiet=True)
    big = max(rows, key=lambda r: (r.get("w") or 0) * (r.get("h") or 0))
    out = {"name": name, "count": len(rows), "thumb": rows[0].get("thumb") or rows[0]["url"],
           "w": big.get("w"), "h": big.get("h")}
    if len(rows) == 1 and rows[0].get("video") and rows[0].get("duration"):
        out["duration"] = rows[0]["duration"]   # 單支影片：預覽卡寫長度＋最高畫質
    if OPT["items"]:
        out["items"] = [{"id": str(r["id"]), "thumb": r.get("thumb") or r["url"], "title": (r.get("title") or "")[:60],
                         "w": r.get("w"), "h": r.get("h")} for r in rows]
    return out


# ─── 單獨跑（終端機）──────────────────────────────────────────────────────

def main():
    argv = [a for a in sys.argv[1:] if a != "--json"]
    pg.JSON_MODE = "--json" in sys.argv
    if not argv:
        die("用法：threads_grab.py [--json] <Threads 連結> [目的地資料夾]")
    pg._ensure_ca_certs()
    grab_post(argv[0], argv[1] if len(argv) > 1 else os.path.expanduser("~/Downloads"), Session())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("已取消", 130)
