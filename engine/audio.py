# -*- coding: utf-8 -*-
"""
audio — 網頁上可以下載的音檔（兩版共用）。

三種進來的方式，存的都是原檔，不轉檔：
  網址直接指到音檔（.mp3／.m4a／.wav／.flac…）  grab_file()：照原樣存一份，檔名用原本的名字
  網頁上放了音檔                                scan()：播放器的 <audio>／<source>、指到音檔的連結、og:audio、
                                                Podcast 訂閱的 <enclosure>（標題取那一集）、結構化資料的 contentUrl。
                                                grab.py 的網頁掃描找到音檔就跟圖一起存
  音樂與 Podcast 平台                           video.py 影片線的「只要聲音」（yt-dlp）
只存網頁本身給出來的檔；要先解密才能播的串流不處理。
"""

import hashlib
import html as htmllib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import core as pg
from core import T, log, die, ua_for, iri, AUDIO_EXTS as AUDIO_EXT
# 事件一律走 pg.emit（grab.py 會換掉它來攔 done）

CAP = 60          # 一頁最多存幾個音檔（Podcast 訂閱動輒上百集；要更早的用「挑幾張」）

# 介面音效、靜音檔（播放器暖機用的 sil-100.mp3 之類）不是內容
JUNK = re.compile(r"^(?:sil(?:ence)?|silent|blank|beep|click|notification)(?:[-_.]?\d+)?\.", re.I)


def is_audio_file(url):
    return urllib.parse.urlparse(url or "").path.lower().endswith(AUDIO_EXT)


def _basename(url):
    """網址最後一段去掉副檔名（%20 之類解回來）。"""
    seg = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
    return os.path.splitext(seg)[0].strip() or ""


# ─── 網頁上的音檔 ──────────────────────────────────────────────────────────

_TAG = re.compile(r"<(audio|source|a|enclosure|media:content)\b([^>]*)>", re.I)
_META = re.compile(r"<meta\b([^>]*)>", re.I)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
_LD = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
_ITEM_TITLE = re.compile(r"<title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</title>", re.S | re.I)


def _attrs(s):
    out = {}
    for m in _ATTR.finditer(s or ""):
        v = next((g for g in m.groups()[1:] if g is not None), "")
        out[m.group(1).lower()] = htmllib.unescape(v)
    return out


_AUDIO_BLOCK = re.compile(r"<audio\b([^>]*)>(.*?)</audio>", re.S | re.I)
_SOURCE = re.compile(r"<source\b([^>]*)>", re.I)


def scan(page, base_url):
    """頁面上的音檔 → [(網址, 名稱)]，依出現順序、同一個只留一次。名稱只有 Podcast 的集數標題、連結的 download／title 才有。
    先看「明講是音檔」的：每個播放器一個（同一個 <audio> 裡的幾個 <source> 是同一段聲音的不同格式，取第一個＝網站首選，
    多半是原檔）、Podcast 的 <enclosure>、og:audio、結構化資料。一個都沒有，才看指到音檔的一般連結
    （連結容易誤認：維基的 /wiki/Talk:x.ogg 是網頁不是檔，最後一段帶冒號的不算）。"""
    out, seen = [], set()

    def add(u, title=""):
        u = (u or "").strip()
        if not u or u.startswith(("data:", "blob:", "javascript:")):
            return
        u = urllib.parse.urljoin(base_url, u)
        if not u.startswith("http"):
            return
        key = u.split("#")[0]
        last = urllib.parse.unquote(urllib.parse.urlparse(u).path.rsplit("/", 1)[-1])
        if key in seen or JUNK.match(last) or ":" in last:      # 帶冒號＝維基那種說明頁（File:x.ogg），不是檔
            return
        seen.add(key)
        out.append((u, htmllib.unescape(title or "").strip()))

    page = page or ""
    for m in _AUDIO_BLOCK.finditer(page):        # 播放器：一個 <audio> 取一個
        src = _attrs(m.group(1)).get("src")
        if not src:
            for s in _SOURCE.finditer(m.group(2)):
                a = _attrs(s.group(1))
                if a.get("src") and ((a.get("type") or "").lower().startswith("audio/")
                                     or is_audio_file(urllib.parse.urljoin(base_url, a["src"]))):
                    src = a["src"]
                    break
        add(src)
    links = []
    for m in _TAG.finditer(page):
        tag, a = m.group(1).lower(), _attrs(m.group(2))
        typ = (a.get("type") or "").lower()
        if tag == "audio" and a.get("src"):      # 沒有收尾的 <audio src=…>
            add(a.get("src"))
        elif tag == "a":
            href = a.get("href") or ""
            full = urllib.parse.urljoin(base_url, href)
            if is_audio_file(full):
                links.append((href, a.get("download") or a.get("title") or ""))
        elif tag in ("enclosure", "media:content"):   # Podcast 訂閱：<item><title>那一集</title>…<enclosure url=…>
            u = a.get("url") or ""
            if typ.startswith("audio/") or is_audio_file(urllib.parse.urljoin(base_url, u)):
                start = page.rfind("<item", 0, m.start())
                t = _ITEM_TITLE.search(page, start, m.start()) if start >= 0 else None
                add(u, t.group(1) if t else "")
    for m in _META.finditer(page):
        a = _attrs(m.group(1))
        prop = (a.get("property") or a.get("name") or "").lower()
        u = a.get("content") or ""
        if prop in ("og:audio", "og:audio:url", "og:audio:secure_url") or (
                prop.endswith(":player:stream") and is_audio_file(urllib.parse.urljoin(base_url, u))):
            add(u)
    for m in _LD.finditer(page):
        for u in re.findall(r'"(?:contentUrl|embedUrl)"\s*:\s*"([^"]+)"', m.group(1)):
            u = u.replace("\\/", "/")
            if is_audio_file(urllib.parse.urljoin(base_url, u)):
                add(u)
    if not out:                                   # 沒有播放器、沒有訂閱：一般的下載連結（檔案清單頁、作品頁的「下載 mp3」）
        for href, title in links:
            add(href, title)
    return out


def rows_for(found, referer):
    """scan() 的結果 → core.download 的下載清單。id＝網址的雜湊（16 碼，existing_ids 認得，再抓會跳過）。"""
    rows = []
    for u, title in found[:CAP]:
        rid = hashlib.sha1(u.split("?")[0].encode("utf-8")).hexdigest()[:16]
        rows.append({"id": rid, "url": u, "alts": [], "thumb": "", "w": None, "h": None,
                     "title": title or _basename(u), "referer": referer, "audio": True})
    if len(found) > CAP:
        log(f"  （找到 {len(found)} 個音檔，只取前 {CAP} 個）")
    return rows


# ─── 網址直接指到音檔 ──────────────────────────────────────────────────────

def _unique(folder, name, ext):
    path = os.path.join(folder, name + ext)
    k = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{name} ({k}){ext}")
        k += 1
    return path


def grab_file(url, dest):
    """一個音檔：照原樣存進存放資料夾（跟單支影片一樣不另開資料夾），檔名用網址裡原本的名字。
    同名的檔已經在、內容也一模一樣＝早就有了，不存第二份；名字一樣內容不同＝另存「名字 (2)」。
    回 False＝網址看起來像音檔、回來的卻是網頁（例：…/wiki/File:x.ogg 是說明頁），交回通用掃描。"""
    name = pg.safe_name(_basename(url), 80, keep_space=True) or "audio"
    log(f"\n  音檔：{name}\n  存到：{dest}\n")
    try:
        blob = pg.fetch_bytes(url, audio=True)
    except urllib.error.HTTPError as e:
        die(T(f"打不開這個音檔（HTTP {e.code}）。", f"Couldn't open this audio file (HTTP {e.code})."))
    except ValueError:
        log("  回來的不是音檔，改當網頁掃")
        return False
    except Exception as e:
        die(T(f"連線失敗：{str(e)[:90]}", f"Connection failed: {str(e)[:90]}"))
    pg.emit(type="source", kind="audio", name=name, count=1, folder=dest, label=pg.site_label(url))
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in AUDIO_EXT:
        ext = pg.sniff_audio_ext(blob)
    os.makedirs(dest, exist_ok=True)
    same = os.path.join(dest, name + ext)
    if os.path.isfile(same) and os.path.getsize(same) == len(blob):
        with open(same, "rb") as fh:
            if hashlib.sha256(fh.read()).digest() == hashlib.sha256(blob).digest():
                pg.emit(type="item", index=1, kind="skip", dim="—", file="")
                pg.emit(type="done", added=0, skipped=1, failed=0, folder=dest, headline=name[:40], dups=0, small=0)
                return True
    path = _unique(dest, name, ext)
    with open(path, "wb") as fh:
        fh.write(blob)
    size = f"{len(blob) / 1048576:.1f} MB" if len(blob) >= 1048576 else f"{len(blob) / 1024:.0f} KB"
    log(f"  [1/1] {size:>11}  {os.path.basename(path)}")
    pg.emit(type="item", index=1, kind="", dim=size, file=os.path.basename(path)[:44])
    pg.emit(type="done", added=1, skipped=0, failed=0, folder=dest, headline=name[:40], file=path,
            audios=1, dups=0, small=0)
    return True


def grab(url, dest):
    """掛勾的入口：直接的音檔照原樣存；音樂與 Podcast 平台交給影片線的「只要聲音」。False＝交回通用掃描。"""
    if is_audio_file(url):
        return grab_file(url, dest)
    import video
    video.grab_video(url, dest, audio=True)
    return True


def probe(url):
    """預覽：直接的檔問名字與大小；平台上的照影片線問（長度、清單幾首），畫面尺寸拿掉。None＝交回通用預覽。"""
    if is_audio_file(url):
        return probe_file(url)
    import video
    p = dict(video.probe(url) or {})
    for k in ("w", "h", "fps", "hdr"):
        p.pop(k, None)
    p["audios"] = p.get("count") or 1
    return p


def probe_file(url):
    """預覽：名字＋大小（HEAD 問一下，問不到就不講）。不下載檔案。"""
    out = {"name": _basename(url) or url, "count": 1, "audios": 1, "thumb": None}
    try:
        req = urllib.request.Request(iri(url), method="HEAD", headers={"User-Agent": ua_for(url)})
        with urllib.request.urlopen(req, timeout=10) as r:
            if (r.headers.get("Content-Type") or "").lower().startswith("text/"):
                return None                     # 是網頁（音檔的說明頁之類）：照網頁預覽
            n = int(r.headers.get("Content-Length") or 0)
            if n:
                out["bytes"] = n
    except Exception:
        pass
    return out
