#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grab — 貼一個網址，抓下它的「完整版」而不是頁面上的縮圖。

任何網頁：掃出頁面上公開看得到的圖，一張張換成原始尺寸（建站平台與圖片 CDN 的規則＋maxurl），
同時下載、同一張不存兩次。共用底層在 core.py（`import core as pg`）。
影片與圖版：經由擴充（EXT）掛進來——影片線（video.py）認得的影片網址直接交給它，網頁掃不到圖時也問它；
圖版與單張 pin 交給圖版解析（pin_grab.py）。

--json：一行一個事件給 app 的介面層吃。不加就是給人看的純文字。
旗標：--probe（只看不抓）--items（連每一項都列）--pick ID,ID --list 檔 --sub --baseline
"""

import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core as pg
from core import (T, OPT, CUR, BUNDLED_BIN, _host, site_label, picked, img_done, width_hint,
                  sheet_for_images, tag_where_from, _ensure_ca_certs)
import audio as AUDIO      # 網頁上的音檔（播放器、下載連結、Podcast 訂閱）

import media as EXT        # 影片線與圖版解析（靜態 import 才會被 PyInstaller 收進去）
try:                      # maxurl（Apache-2.0）的 1 萬多站縮圖→原圖規則，由包內 qjs 離線執行
    import maxurl as MAXURL
except Exception:
    MAXURL = None


IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".tiff", ".svg")


# ─── 來源判斷 ────────────────────────────────────────────────────────

def kind_of(url):
    if EXT:
        k = EXT.kind_of(url)
        if k:
            return k
    return "web"


# ─── 一般網頁：掃圖 → 升級成原始尺寸 ────────────────────────────────

# 縮圖特徵：WordPress 的 -1024x768、CDN 的 /thumb/、查詢字串裡的 w=／resize=
RESIZE_SUFFIX = re.compile(r"-\d{2,4}x\d{2,4}(?=\.\w{3,4}(?:$|\?))")


RESIZE_QUERY  = re.compile(r"[?&](?:w|h|width|height|resize|fit|size|s|sz|q|quality|format|dpr|crop|ar|rect|"
                           r"scale-down-to|max-w|max-h|maxwidth|maxheight|thumb)=[^&]*")


THUMB_PATH    = [("/thumb/", "/"), ("/thumbs/", "/"), ("/thumbnail/", "/"),
                 ("/small/", "/large/"), ("/medium/", "/large/"), ("/preview/", "/full/"),
                 ("_thumb.", "."), ("_small.", "."), ("_medium.", "."), ("-thumb.", "."),
                 ("/w_200/", "/"), ("/c_thumb/", "/")]


JUNK = re.compile(r"(sprite|icon|logo|avatar|favicon|placeholder|blank|spacer|"
                  r"emoji|badge|button|arrow|pixel|tracking|1x1|"
                  # 網站外框：MediaWiki 頁尾的 powered-by／字標／標語（不算內容，也不算張數）
                  r"poweredby|wordmark|tagline|/footer/|/static/images/|/resources/assets/)", re.I)


# 尺寸級別字樣（Apple／Shopify／各家 CDN 都用這套）：small → large
SIZE_WORD = re.compile(r"_(?:small|medium|mini|tiny|thumb|xs|sm|md)(?=[_.\-])", re.I)


#
# 通用規則猜不到的建站平台／圖片 CDN 寫法。部分翻譯自 Hover Zoom+（MIT，github.com/extesy/hoverzoom）
# 的 plugins/，其餘是各 CDN 公開的尺寸參數慣例。每條規則獨立套在原網址上產生一個候選，
# 候選只是「先試」——下載端會驗回來的是不是真的圖片檔，全失敗才退回原網址，所以猜錯不傷人。
# 格式：(主機 regex, [ (pattern, repl) 或 callable(url)->url|None, … ])，同站多條照順序＝優先序。
_R = re.compile


_IMG = r"(?=\.(?:jpe?g|png|gif|webp|avif)(?:$|[?#]))"


def _substack_inner(url):
    m = re.search(r"substackcdn\.com/image/fetch/[^/]+/(https?(?::|%3A).+)$", url)
    return urllib.parse.unquote(m.group(1)) if m else None


def _mediawiki_file(url):
    """Wikipedia 的「File:x.jpg」說明頁 → Special:FilePath 直接轉到原始上傳檔（本站的）。"""
    m = re.match(r"^(https?://[^/]+)/wiki/(?:File|Image|檔案|文件):([^?#]+)$", url)
    return f"{m.group(1)}/wiki/Special:FilePath/{m.group(2)}" if m else None


def _commons_file(url):
    """同上，但檔案多半放在 Wikimedia Commons——本站的 FilePath 找不到時的第二個候選。"""
    m = re.match(r"^https?://[^/]+/wiki/(?:File|Image|檔案|文件):([^?#]+)$", url)
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{m.group(1)}" if m else None


CDN_RULES = [
    # MediaWiki：…/thumb/6/67/A.jpg/1280px-A.jpg → upload.wikimedia.org/…/6/67/A.jpg（原始上傳檔）。
    # 縮圖也可能從 thumb.wikimedia.org 出，但那個網域沒有原檔（直接給路徑會被轉去 Commons 首頁）——一律換回 upload。
    (_R(r"(^|\.)wikimedia\.org$|(^|\.)wikipedia\.org$"), [
        (_R(r"^https?://(?:upload|thumb)\.wikimedia\.org/(.+?)/thumb(/[0-9a-f]/[0-9a-f]{2}/[^/]+)/[^/?]+(?:\?.*)?$"),
         r"https://upload.wikimedia.org/\1\2"),
        (_R(r"^https?://thumb\.wikimedia\.org/(?!.*/thumb/)(.+?)(?:\?.*)?$"), r"https://upload.wikimedia.org/\1"),
        _mediawiki_file, _commons_file]),
    # 部落格／建站平台
    (_R(r"(^|\.)squarespace(-cdn)?\.com$"), [                       # ?format=750w → original / 2500w
        (_R(r"([?&])format=[^&]*"), r"\1format=original"),
        (_R(r"([?&])format=[^&]*"), r"\1format=2500w")]),
    (_R(r"(^|\.)wixstatic\.com$"), [                                  # …~mv2.jpg/v1/fill/w_500…/x.webp → …~mv2.jpg
        (_R(r"^(.*?~mv2\.[a-z0-9]+)/.*$", re.I), r"\1")]),
    (_R(r"(^|\.)wp\.com$|(^|\.)wordpress\.com$"), [                   # i0.wp.com/…?resize=… → 去參數
        (_R(r"\?.*$"), "")]),
    (_R(r"(^|\.)medium\.com$"), [                                     # miro.medium.com/v2/resize:fit:700/x → /x
        (_R(r"(miro\.medium\.com/)(?:v2/)?(?:(?:resize:[^/]+|max/\d+|fit/[^/]+(?:/\d+)*|format:[^/]+)/)+"), r"\1"),
        (_R(r"(cdn-images-\d+\.medium\.com/)(?:(?:max|fit)/[^/]+/(?:\d+/)*)+"), r"\1")]),
    (_R(r"(^|\.)ghost\.io$|(^|\.)ghost\.org$"), [
        (_R(r"/content/images/size/w\d+h?\d*/"), "/content/images/")]),
    (_R(r"(^|\.)website-files\.com$|(^|\.)webflow\.com$"), [          # name-p-500.jpg → name.jpg
        (_R(r"-p-\d+" + _IMG), "")]),
    (_R(r"(^|\.)framerusercontent\.com$"), [(_R(r"[?&]scale-down-to=\d+"), "")]),
    (_R(r"(^|\.)substackcdn\.com$"), [_substack_inner]),
    (_R(r"(^|\.)notion\.so$|(^|\.)notion\.site$"), [(_R(r"&width=\d+"), "")]),
    (_R(r"(^|\.)cargo\.site$"), [                                     # freight.cargo.site/w/1600/q/75/i/… → /t/original/i/…
        (_R(r"(freight\.cargo\.site/)(?:[wtqh]/[^/]+/)+i/"), r"\1t/original/i/")]),
    (_R(r"(^|\.)myportfolio\.com$"), [(_R(r"_rw_\d+" + _IMG), "_rw_3840"), (_R(r"_rw_\d+" + _IMG), "")]),
    (_R(r"(^|\.)blogspot\.com$|(^|\.)googleusercontent\.com$|(^|\.)ggpht\.com$"), [   # /s320/ 或 =w400-h300 → 原圖
        (_R(r"/(?:s|w)\d+(?:-h\d+)?(?:-[a-z-]+)?/(?=[^/]+$)"), "/s0/"),
        (_R(r"=[swh]\d+[^/]*$"), "=s0")]),
    (_R(r"(^|\.)cloudinary\.com$"), [                                 # /image/upload/w_500,c_fill/v1/x → /image/upload/v1/x
        (_R(r"(/image/upload/)(?:[a-z]{1,3}_[^/]+/)+"), r"\1")]),
    (_R(r"(^|\.)imgix\.net$|(^|\.)ctfassets\.net$|(^|\.)sanity\.io$"), [(_R(r"\?.*$"), "")]),
    # 開店平台
    (_R(r"(^|\.)shopify\.com$|(^|\.)shopifycdn\.com$"), [             # name_1024x1024@2x_crop_center.jpg → name.jpg
        (_R(r"_(?:\d+x\d*|\d*x\d+|pico|icon|thumb|small|compact|medium|large|grande|master)(?:@\d+x)?(?:_crop_[a-z]+)?" + _IMG), "")]),
]


def upgrade(url, extra=()):
    """回傳 (最可能的原圖, [備援網址…])。下載時照順序試，全失敗才算失敗。
       順序很重要：升級版排前面，原網址永遠留在最後當保底。
       extra：maxurl 的候選——排在我們自己的站專用規則後面、通用猜測前面
       （下載端「第一個是真圖就收」，通用猜測常回同尺寸的有效圖，排前面會擋掉 maxurl 找到的大圖）。"""
    ups = []

    # 站專用規則最前面（比通用猜測準）
    host = _host(url)
    for host_re, rules in CDN_RULES:
        if not host_re.search(host):
            continue
        for rule in rules:
            try:
                cand = rule(url) if callable(rule) else rule[0].sub(rule[1], url)
            except Exception:
                cand = None
            if cand and cand != url:
                ups.append(cand)
    ups.extend(extra)

    # small_2x → large_2x（Apple 的 hero 圖就是這樣命名）
    if SIZE_WORD.search(url):
        ups.append(SIZE_WORD.sub("_large", url))

    # -1024x768.jpg → .jpg（WordPress 系）；WordPress 站再多砍 -scaled／-e<13碼>／-cropped 與查詢字串
    u2 = RESIZE_SUFFIX.sub("", url)
    if u2 != url:
        ups.append(u2)
    if "/wp-content/" in url:
        u3 = re.sub(r"-(?:\d{2,4}x\d{2,4}(?:-\d+)?|scaled|e\d{13}|cropped|c-default)(?=\.\w{3,4}(?:$|\?))", "",
                    url).split("?", 1)[0]
        if u3 != url:
            ups.append(u3)

    # 砍掉查詢字串裡的縮放參數
    if "?" in url:
        base, q = url.split("?", 1)
        q2 = RESIZE_QUERY.sub("", "?" + q).lstrip("?&")
        ups.append(base + ("?" + q2 if q2 else ""))

    # 路徑型縮圖目錄
    for a, b in THUMB_PATH:
        if a in url:
            ups.append(url.replace(a, b))

    seen, out = set(), []
    for a in ups + [url]:
        if a and a not in seen:
            seen.add(a); out.append(a)
    return out[0], out[1:]


def identity(url):
    """把同一張圖的各種尺寸版本收斂成同一個鍵，避免 small/large 都下載一次。"""
    path = urllib.parse.urlparse(url).path
    base = os.path.basename(path)
    base = SIZE_WORD.sub("", base)
    base = RESIZE_SUFFIX.sub("", base)
    base = re.sub(r"[_-](?:2x|3x|large|orig|original|full|hd)(?=[_.\-]|$)", "", base, flags=re.I)
    return re.sub(r"\W+", "", base).lower() or path


def largest_in_srcset(srcset):
    best, bw = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1:
            m = re.match(r"(\d+)([wx])", bits[-1])
            if m:
                w = int(m.group(1)) * (1000 if m.group(2) == "x" else 1)
        if w >= bw:
            bw, best = w, bits[0]
    return best


# 一頁掃圖：把所有圖片候選加進 add()。抽成函式，才能對 frame/iframe 遞迴重用。
def scan_images(page, base_url, add):
    absolute = lambda u: urllib.parse.urljoin(base_url, htmllib.unescape(u.strip()))
    # 0 = 最可信：<a> 直接指向圖檔（＝「右鍵在新分頁打開圖片」的完整版）
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', page, re.I):
        h = m.group(1)
        if re.sub(r"[?#].*$", "", h).lower().endswith(IMG_EXT):
            add(absolute(h), 0)
    # 1 = srcset 最大的那個
    for m in re.finditer(r'(?:data-)?srcset=["\']([^"\']+)["\']', page, re.I):
        best = largest_in_srcset(m.group(1))
        if best:
            add(absolute(best), 1)
    # 2 = og:image
    for m in re.finditer(r'<meta[^>]+(?:property|name)=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', page, re.I):
        add(absolute(m.group(1)), 2)
    # 3 = 一般 img（含 lazy-load 屬性）
    for attr in ("data-original", "data-src", "data-lazy-src", "data-full-src",
                 "data-large", "data-zoom-image", "src"):
        for m in re.finditer(r'<img[^>]+' + attr + r'=["\']([^"\']+)["\']', page, re.I):
            u = m.group(1)
            if re.sub(r"[?#].*$", "", u).lower().endswith(IMG_EXT) or "/image" in u.lower():
                add(absolute(u), 3)
    # 4 = CSS 背景圖
    for m in re.finditer(r'background-image\s*:\s*url\(["\']?([^"\')]+)', page, re.I):
        add(absolute(m.group(1)), 4)


# 找出這頁的 <frame>／<iframe> 子頁網址（老式分框網站＝內容其實在子頁裡）
def frame_srcs(page, base_url):
    out = []
    for m in re.finditer(r'<i?frame[^>]+src=["\']([^"\']+)["\']', page, re.I):
        u = urllib.parse.urljoin(base_url, htmllib.unescape(m.group(1).strip()))
        if u.startswith("http") and not u.startswith("data:"):
            out.append(u)
    return out


def maxurl_map(urls, page_url=None):
    """一頁的圖一次問 maxurl（一個 qjs 行程，約 0.2 秒）：{縮圖網址: [更大的候選…]}。沒裝、逾時、出錯都回 {}，不影響原本的規則。"""
    if not MAXURL or not urls:
        return {}
    here = os.path.dirname(os.path.abspath(__file__))
    box = os.path.join(os.path.dirname(BUNDLED_BIN), "maxurl")
    vendor = os.path.join(here, "..", "vendor")
    for runner, lib, q in (
            (os.path.join(box, "maxurl_runner.js"), os.path.join(box, "userscript_smaller.user.js"),
             os.path.join(BUNDLED_BIN, "qjs")),                                                     # app 包內
            (os.path.join(here, "maxurl_runner.js"), os.path.join(vendor, "maxurl", "userscript_smaller.user.js"),
             os.path.join(vendor, "bin", "qjs"))):                                                  # 開發期（原始碼旁邊）
        if os.path.isfile(runner) and os.path.isfile(lib) and os.path.isfile(q):
            return MAXURL.bigger(urls, q, runner, lib=lib, timeout=20, page_url=page_url)
    return {}


def _page_title(page, final_url):
    t = re.search(r"<title>([^<]{1,90})</title>", page or "")
    name = htmllib.unescape(t.group(1)).strip() if t else (urllib.parse.urlparse(final_url).hostname or "")
    name = re.sub(r"\s*[|｜–—-]\s*[^|｜–—-]{1,24}$", "", name).strip()
    return name or T("網頁", "Web page")


WEB_CAP = 60


def _web_rows(cands, referer):
    """候選網址 → 下載清單：可信度高的先來，同一張圖的不同尺寸收斂成一筆，上限 WEB_CAP。
    同一張的其他候選不丟掉，而是排進備援——可信度最高的那個有時其實是網頁不是圖
    （Wikipedia 的 <a href="/wiki/File:x.jpg"> 就是），下載端驗到「不是圖片檔」會接著試真正的圖。
    每筆帶 referer（有些 CDN 擋沒有來源頁的請求）與 page_w（原網址看得出頁面上多寬就記下）。"""
    cands.sort(key=lambda t: t[0])
    mx = maxurl_map([u for _, u, _ in cands], referer)
    rows, by_id = [], {}
    for _, u, shown_w in cands:
        ident = identity(upgrade(u)[0])        # 用我們自己的第一候選算「是不是同一張」（maxurl 的網址常是 …/source 這種通用檔名）
        best, alts = upgrade(u, mx.get(u, ()))
        pw = shown_w or (width_hint(u) if best != u else None)
        if ident in by_id:
            r = by_id[ident]
            for a in [best] + alts:
                if a != r["url"] and a not in r["alts"]:
                    r["alts"].append(a)
            if not r.get("page_w") and pw:
                r["page_w"] = pw
            if r["thumb"] == r["url"]:
                r["thumb"] = u
            continue
        r = {"id": ident[:40] or str(len(rows)), "url": best, "alts": list(alts), "thumb": u,
             "w": None, "h": None, "title": "", "referer": referer, "page_w": pw}
        by_id[ident] = r
        rows.append(r)
    return rows


def _scan_page(url, sess):
    """開網頁、掃圖（含同網域 frame／iframe），回 (final_url, page, rows, 名字, preview_only)。grab_web 與預覽共用。
    preview_only＝整頁只認得出一張，而且只來自 og:image（或同一張當 CSS 背景）：頁面本身讀不到圖，
    存得到的只是分享連結時顯示的那張預覽圖。完成畫面要照實講，不能說成一般的「存好了」。"""
    try:
        final_url, page = sess.get_page(url)
    except urllib.error.HTTPError as e:
        pg.die(T(f"打不開這個網頁（HTTP {e.code}）。", f"Couldn't open this page (HTTP {e.code})."))
    except Exception as e:
        pg.die(T(f"連線失敗：{str(e)[:90]}", f"Connection failed: {str(e)[:90]}"))

    cands, seen = [], set()

    def add(u, priority=1):
        if not u or u.startswith("data:") or not u.startswith("http") or JUNK.search(u):
            return
        key = re.sub(r"[?#].*$", "", u)
        if key in seen:
            return
        seen.add(key)
        cands.append((priority, u, None))

    # 主頁先掃
    scan_images(page, final_url, add)

    # <frame>／<iframe>：內容常整個在子頁裡（老式分框網站、相簿的檢視框都是這樣）。
    # 同網域、限深 1（子頁的子頁不再追）、限量 12，避免把廣告 iframe 也爬爛。
    host0 = _host(final_url)
    frames = frame_srcs(page, final_url)
    if frames:
        pg.log(f"  頁面有 {len(frames)} 個框架，逐一掃進去…")
    for fsrc in frames[:12]:
        if _host(fsrc) != host0:              # 跨網域框架多半是廣告／外嵌播放器，跳過
            continue
        try:
            furl, fpage = sess.get_page(fsrc)
            scan_images(fpage, furl, add)
            for sub in frame_srcs(fpage, furl)[:6]:   # 分框網站常有一層 <frame> 包 <frame>
                if _host(sub) != host0:
                    continue
                try:
                    surl, spage = sess.get_page(sub)
                    scan_images(spage, surl, add)
                except Exception:
                    pass
        except Exception:
            pass
    rows = _web_rows(cands, final_url)
    preview_only = len(rows) == 1 and any(p == 2 for p, _, _ in cands) and all(p in (2, 4) for p, _, _ in cands)
    # 網頁上的音檔：跟圖一起存、排在前面（音樂頁的封面、Podcast 的節目圖照樣存）；有音檔就不算「只有預覽圖」
    arows = AUDIO.rows_for(AUDIO.scan(page, final_url), final_url)
    if arows:
        rows, preview_only = arows + rows, False
    return final_url, page, rows, _page_title(page, final_url), preview_only


def grab_web(url, dest, sess):
    final_url, page, rows, name, preview_only = _scan_page(url, sess)

    # 頁面掃不到半張圖、或只拿得到分享預覽圖（影片頁多半如此）：擴充（影片線）認得就交給它
    if (not rows or preview_only) and EXT and EXT.web_fallback(final_url, dest):
        return
    if not rows:
        pg.die(T("這個網頁上抓不到圖片。有些網站的圖要捲動才載入，或不是公開的。",
                 "No images found on this page. Some sites only load images as you scroll, or aren't public."))

    # 行銷頁動輒上百張素材，抓爆沒有意義。設上限並明講砍掉幾張，不要靜靜截斷。（音檔另有自己的上限，在 audio.py）
    aud = [r for r in rows if r.get("audio")]
    img = [r for r in rows if not r.get("audio")]
    if len(img) > WEB_CAP:
        pg.log(f"  （找到 {len(img)} 張，只取可信度最高的前 {WEB_CAP} 張）")
        img = img[:WEB_CAP]
    rows = picked(aud + img)
    _save_rows(rows, dest, name, _host(final_url) or T("網頁", "Web page"), "audio" if aud and not img else "web",
               preview_only=preview_only)


def _save_rows(rows, dest, name, label, kind, preview_only=False):
    """網頁掃圖與 --list 清單共用：開資料夾 → 同時下載 → done。"""
    folder = os.path.join(dest, pg.safe_name(name, 60, keep_space=True) or "web")
    pg.log(f"\n  網頁：{name}")
    pg.log(f"  張數：{len(rows)}")
    pg.log(f"  存到：{folder}\n")
    pg.emit(type="source", kind=kind, name=name, count=len(rows), folder=folder, label=label)
    seen = pg.Seen(folder)
    # 20 KB 以下當作 icon／sprite，不落地
    res = pg.download(rows, folder, min_bytes=20_000, dedup=pg.DEDUP, seen=seen, only_new=OPT["sub"])
    pg.log(f"\n  完成 — 新下載 {res.ok} 張"
           + (f"、略過 {res.skipped} 張" if res.skipped else "")
           + (f"、一模一樣已經有的 {res.dups} 張" if res.dups else "")
           + (f"、抓不到 {res.failed} 張" if res.failed else ""))
    extra = {}
    if preview_only and res.ok:
        pg.log("  （頁面本身讀不到圖，存到的是分享預覽圖）")
        extra["preview_only"] = True
    pg.emit(type="done", added=res.ok, skipped=res.skipped, failed=res.failed, folder=folder,
            headline=name[:40], **img_done(res), **extra)


def grab_list(listfile, dest):
    """--list：別的程式交來一份「頁面上真的顯示出來的圖」（含捲動才載入的），
    這裡照樣換成原尺寸、同時下載。JSON：{url, title, images:[{u, w, h}]}（w／h＝頁面上那張的實際像素）。"""
    try:
        with open(listfile, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception as e:
        pg.die(T(f"讀不到瀏覽器交過來的清單：{e}", f"Couldn't read the list from the browser: {e}"))
    page_url = data.get("url") or ""
    cands = []
    for k, it in enumerate(data.get("images") or []):
        u = (it or {}).get("u") or ""
        if u.startswith("http") and not JUNK.search(u):
            cands.append((0 if (it.get("w") or 0) >= 600 else 1, u, it.get("w") or None))
    rows = _web_rows(cands, page_url)
    if not rows:
        pg.die(T("這一頁畫面上沒有夠大的圖。往下捲，讓想要的圖出現在畫面上，再按一次。",
                 "No large images on screen yet. Scroll until the images you want show up, then grab again."))
    rows = picked(rows[:300])
    name = (data.get("title") or "").strip()
    name = re.sub(r"\s*[|｜–—-]\s*[^|｜–—-]{1,24}$", "", name).strip() or _host(page_url) or T("網頁", "Web page")
    _save_rows(rows, dest, name, _host(page_url) or T("網頁", "Web page"), "web")


# ─── 預覽（--probe）：只看不抓 ───────────────────────────────────────────

def _session():
    if EXT:
        return EXT.session()
    return pg.Session()


def _probe_web(url):
    sess = _session()
    final_url, page, rows, name, preview_only = _scan_page(url, sess)
    og = re.search(r'<meta[^>]+(?:property|name)=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', page or "", re.I)
    thumb = urllib.parse.urljoin(final_url, htmllib.unescape(og.group(1))) if og else next((r["thumb"] for r in rows if r.get("thumb")), None)
    aud = [r for r in rows if r.get("audio")]
    rows = aud + [r for r in rows if not r.get("audio")][:WEB_CAP]
    out = {"name": name, "count": len(rows), "thumb": thumb}
    if aud:
        out["audios"] = len(aud)            # 預覽卡：全是音檔講「幾個音檔」，混著圖就兩個都講
    if preview_only:
        out["preview_only"] = True
    if OPT["items"]:
        out["items"] = [{"id": r["id"], "thumb": r["thumb"], "title": r["title"] if r.get("audio") else ""} for r in rows]
    return out


def probe_source(url):
    """--probe：吐一個 preview 事件，不下載任何東西。失敗也只回基本資料（預覽卡照樣出、只是沒縮圖）。"""
    kind = kind_of(url)
    out = {"type": "preview", "url": url, "kind": kind, "label": site_label(url)}
    try:
        p = None
        if EXT and kind != "web":
            p = EXT.probe(kind, url)
        if p is None:
            p = _probe_web(url)
            if (not p.get("count") or p.get("preview_only")) and EXT:
                p = EXT.probe_fallback(url) or p
        out.update(p)
    except SystemExit:
        raise
    except Exception as e:
        out["error"] = str(e)[:80]
    if out.get("list") or (out.get("count") or 0) > 1:
        out["multi"] = True
    pg.emit(**out)


# ─── 主流程 ──────────────────────────────────────────────────────────

def main():
    _ensure_ca_certs()
    # 旗標：--pick ID,ID　--list 檔 帶值；其餘是開關
    SWITCHES = {"--json", "--probe", "--items", "--sub", "--baseline"}
    VALUED = {"--pick": "pick", "--list": "list"}
    if EXT:                                  # 擴充另外加它自己的
        SWITCHES |= EXT.SWITCHES
        VALUED.update(EXT.VALUED)
    argv, flags, vals, a = [], set(), {}, sys.argv[1:]
    i = 0
    while i < len(a):
        if a[i] in VALUED and i + 1 < len(a):
            vals[VALUED[a[i]]] = a[i + 1]
            i += 2
            continue
        if a[i] in SWITCHES:
            flags.add(a[i])
        else:
            argv.append(a[i])
        i += 1
    pg.JSON_MODE = "--json" in flags
    OPT.update(pick=vals.get("pick"), sub="--sub" in flags, baseline="--baseline" in flags, items="--items" in flags)
    no_images = False                                # 這一趟不存圖：不做重複比對、不出總覽圖
    if EXT:
        EXT.take_flags(flags, vals)
        no_images = EXT.media_only()

    if vals.get("list"):
        dest = argv[0] if argv else os.path.expanduser("~/Downloads")
        url = ""
        try:
            with open(vals["list"], encoding="utf-8") as fh:
                url = (json.load(fh) or {}).get("url") or ""
        except Exception:
            pass
    else:
        if not argv:
            pg.die("用法：grab.py [--json] <網址> [目的地資料夾]")
        url = argv[0].strip().strip("<>\"' ")
        if not url.startswith("http"):
            url = "https://" + url.lstrip("/")
        dest = argv[1] if len(argv) > 1 else os.path.expanduser("~/Desktop")
    CUR["url"] = url

    if "--probe" in flags:
        probe_source(url)
        return

    kind = kind_of(url) if not vals.get("list") else "web"
    pg.emit(type="detected", kind=kind)

    if OPT["baseline"]:
        baseline(url, dest)
        return

    # 同一張不存兩次：app 設定開著（FULLY_DEDUP=1）就先把存放資料夾的圖做成索引（只算新的，第一次會久一點）
    if os.environ.get("FULLY_DEDUP") == "1" and not no_images:
        try:
            pg.DEDUP = pg.HashIndex(dest).load().refresh()
        except Exception:
            pg.DEDUP = None

    # 攔下 done 事件記住資料夾，結束後把來源網址寫進每個新檔
    started_at = time.time()
    done_folder = {"path": None}
    _orig_emit = pg.emit
    def _emit(**kw):
        if kw.get("type") == "done" and kw.get("folder"):
            done_folder["path"] = kw["folder"]
        _orig_emit(**kw)
    pg.emit = _emit
    try:
        if vals.get("list"):
            grab_list(vals["list"], dest)
        else:
            _dispatch(url, dest, kind)
    finally:
        pg.emit = _orig_emit
        tag_where_from(done_folder["path"], url, started_at)
        if pg.DEDUP is not None:
            pg.DEDUP.save()
    # 圖片批次 ≥6 張自動出總覽圖；追蹤檢查不出（新的通常只有幾張）
    if done_folder["path"] and not (no_images or OPT["sub"]):
        try:
            sh = sheet_for_images(done_folder["path"], started_at)
        except Exception:
            sh = None
        if sh:
            pg.log(f"  總覽圖：{sh}")
            pg.emit(type="extra", sheet=sh, message=T("總覽圖存好了，一眼看完這批", "Overview sheet saved — see the whole batch at a glance"))


def baseline(url, dest):
    """開始追蹤：把來源現有的每一項記成「看過了」，之後的檢查只抓新的。
    網頁不用做事——檢查時比對資料夾裡已經有的檔（.fully-seen）。"""
    n = 0
    if EXT:
        n = EXT.baseline(url)
    pg.emit(type="done", added=0, skipped=n, failed=0, folder="", headline="", baseline=True)


def _dispatch(url, dest, kind):
    sess = _session()
    if EXT and EXT.dispatch(url, dest, kind, sess):
        return
    grab_web(url, dest, sess)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pg.die("已取消", 130)
