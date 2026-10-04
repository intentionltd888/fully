#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core — Fully 引擎的共用底層。

事件輸出（--json）、語言、連線與重試、圖片驗證與尺寸、同時下載、同一張不存兩次、
追蹤用的「看過了」紀錄、旗標（OPT）、總覽圖、來源欄。
其他模組用 `import core as pg`。只用 Python 標準函式庫。
"""

import gzip
import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── 基礎工具 ────────────────────────────────────────────────────────────

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
# 有些站要求非瀏覽器的程式報上真名（Wikimedia 的 User-Agent 政策；用瀏覽器身分會被 429、Retry-After 600 秒），
# 對它們就老實講自己是誰。
FAIR_UA = "Fully/2.3 (+https://intention.ltd; design reference collector)"
FAIR_UA_HOSTS = ("wikimedia.org", "wikipedia.org", "wikidata.org", "wiktionary.org", "mediawiki.org")


def ua_for(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return FAIR_UA if any(h == d or h.endswith("." + d) for d in FAIR_UA_HOSTS) else UA


TIMEOUT = 45


# --json：一行一個 JSON 事件，給 app 的介面層吃。不加就是給人看的純文字。
JSON_MODE = False


# 介面語言（app 用 FULLY_LANG 告訴引擎）。給人看的句子一律寫成 T("中文", "English")。
LANG = "en" if os.environ.get("FULLY_LANG", "zh").lower().startswith("en") else "zh"


def T(zh, en):
    return en if LANG == "en" else zh


# 圖片是多條同時下載，事件從好幾個執行緒吐出來——同一把鎖，一行才不會被切成兩半
_out_lock = threading.Lock()


def emit(**obj):
    if JSON_MODE:
        s = json.dumps(obj, ensure_ascii=False)
        with _out_lock:
            print(s, flush=True)


def log(msg=""):
    if not JSON_MODE:
        with _out_lock:
            print(msg, flush=True)


def die(msg, code=1, **extra):
    """extra 會併進 error 事件（例如 nospace=True）。"""
    emit(type="error", message=msg.replace("\n", " ").replace("    ", ""), **extra)
    log(f"\n  ✕ {msg}")
    sys.exit(0 if JSON_MODE else code)   # 事件已送出，別讓 app 再蓋一個中斷訊息


def iri(url):
    """網址裡有中文、ü 這類字（沒編碼過）時，urllib 會直接炸 'ascii' codec——先轉成 %XX（已經編過的不動）。"""
    try:
        url.encode("ascii")
        return url
    except UnicodeEncodeError:
        return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def read_body(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


class Redirects(urllib.request.HTTPRedirectHandler):
    """Python 3.11 以前的 urllib 不認 308（有些短網址就是走 308），補上。"""
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_307(req, fp, 307, msg, headers)


# 限流／暫時性故障才重試。404、403 這種「你要的東西不在」重試也沒用，別浪費時間。
RETRY_CODES = (408, 425, 429, 500, 502, 503, 504)


RETRY_TIMES = 3


def with_retry(fn, what="請求"):
    """指數退避重試。各家網站與 CDN 連打太多次都會限流，
       這是唯一一種「等一下再試就會好」的錯誤，值得自動處理。"""
    delay = 1.5
    for attempt in range(RETRY_TIMES + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES or attempt == RETRY_TIMES:
                raise
            try:
                wait = float(e.headers.get("Retry-After") or 0) or delay
            except ValueError:
                wait = delay
            if wait > 30:        # 網站明講要等好幾分鐘（429＋Retry-After 600）：別讓人乾等，直接算這張抓不到
                raise
            log(f"    {what}被限流（{e.code}），{wait:.0f} 秒後重試…")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == RETRY_TIMES:
                raise
            log(f"    {what}連線不穩，{delay:.0f} 秒後重試…")
        time.sleep(min(delay, 20))
        delay *= 2.2


class Session:
    """匿名 session（網頁掃圖用；同一趟裡網站發的 cookie 會記著，不帶任何既有的 cookie）。"""

    def _make_jar(self):
        return http.cookiejar.CookieJar()

    def __init__(self):
        ctx = ssl.create_default_context()
        self.jar = self._make_jar()
        self.opener = urllib.request.build_opener(
            Redirects(),
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ctx),
        )
        self.opener.addheaders = [
            ("User-Agent", UA),
            ("Accept-Language", "zh-TW,zh;q=0.9,en;q=0.8"),
            ("Accept-Encoding", "gzip"),
        ]

    @property
    def csrf(self):
        for c in self.jar:
            if c.name == "csrftoken":
                return c.value
        return ""

    def get_page(self, url):
        def once():
            req = urllib.request.Request(iri(url), headers={"User-Agent": ua_for(url)})
            resp = self.opener.open(req, timeout=TIMEOUT)
            return resp.geturl(), read_body(resp)
        return with_retry(once, "開網頁")



# ─── 下載 ────────────────────────────────────────────────────────────────

def safe_name(s, limit=40, keep_space=False):
    """資料夾名：只擋檔案系統真正不接受的字元，其餘照原樣保留 ——
       白名單會把 `Neo-futurist × Chrome` 洗成 `Neo futurist  Chrome`，使用者就認不出來了。
       檔名：走白名單轉連字號，因為後面還要接序號與 id。"""
    if keep_space:
        s = re.sub(r'[/\\:*?"<>|\x00-\x1f]+', " ", s)
        return re.sub(r"\s+", " ", s).strip(" .")[:limit]
    allowed = r"0-9A-Za-z一-鿿぀-ヿ가-힯"
    s = re.sub(r"[^" + allowed + r"]+", "-", s)
    return s.strip("-")[:limit]


def existing_ids(folder):
    ids = set()
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            for m in re.findall(r"([0-9a-f]{16,}|\d{15,})", f):
                ids.add(m)
    return ids


def fetch_bytes(url, referer=None, video=False):
    """抓下來先驗證再落地，避免留下寫壞的半截檔（本工具不做任何刪檔）。
    referer：網頁掃圖帶原頁網址（有些 CDN 擋沒有來源頁的請求）；沒給就不帶。
    video：來源模組說這一筆是影片檔（例如圖版裡的影片 pin）——驗的是 mp4／mov 的檔頭，不是圖片的。"""
    headers = {"User-Agent": ua_for(url)}
    if referer:
        headers["Referer"] = iri(referer)
    req = urllib.request.Request(iri(url), headers=headers)

    def once():
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    blob = with_retry(once, "下載影片" if video else "下載圖片")
    if video:
        if not is_mp4(blob):
            raise ValueError(T("不是影片檔", "not a video"))
        return blob
    if len(blob) < 1024 and b"<svg" not in blob[:1024].lower():
        raise ValueError(T("回應太小，應該是錯誤頁", "response too small (error page?)"))
    # AVIF/HEIC 的魔數在第 4–12 位元組（ftyp box）——有些 CDN 只給 avif，
    # 沒認它的話每張都會被當「不是圖片檔」擋掉。
    is_isobmff = blob[4:8] == b"ftyp" and blob[8:12] in (
        b"avif", b"avis", b"heic", b"heix", b"mif1", b"msf1")
    if not (blob[:3] == b"\xff\xd8\xff" or blob[:8] == b"\x89PNG\r\n\x1a\n"
            or blob[:4] == b"RIFF" or blob[:6] in (b"GIF87a", b"GIF89a")
            or is_isobmff or is_svg(blob)):
        raise ValueError(T("不是圖片檔", "not an image"))
    return blob


def is_mp4(b):
    """mp4／mov：第一個 box 的型別在第 4–8 位元組（ftyp，少數舊檔直接是 moov／mdat／free／wide）。"""
    return len(b) > 1024 and b[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip")


def fetch_hls(url, referer=None):
    """串流（m3u8）→ 一支 mp4：交給 yt-dlp（它自己的串流下載器把每一段都抓齊，再用 ffmpeg 在本機合併）。
    不讓 ffmpeg 直接開網路串流：只抓到第一段也會回「成功」（實測 8 秒的影片只剩 2 秒），等於靜靜交出半截檔。
    寫進系統暫存區、驗過檔頭才交回去；回 (位元組, 暫存檔)，下載端用搬的放進資料夾，不留第二份。"""
    import glob
    import subprocess
    import tempfile
    import video
    yt, ff = video.find_ytdlp(), find_ffmpeg_dir()
    if not yt or not ff:
        raise ValueError(T("少了影片引擎，接不起串流影片", "The video engine is missing — can't join a streamed video"))
    d = tempfile.mkdtemp(prefix="fully-stream-")
    cmd = yt + ["--no-warnings", "--quiet", "--no-progress", "--no-playlist", "--ffmpeg-location", ff,
                "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", os.path.join(d, "v.%(ext)s")]
    if referer:
        cmd += ["--referer", iri(referer)]
    r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=900)
    out = [p for p in glob.glob(os.path.join(d, "v.*")) if not p.endswith((".part", ".ytdl"))]
    if r.returncode != 0 or not out:
        last = (r.stderr or "").strip().splitlines()
        raise ValueError(last[-1][:60] if last else T("串流影片接不起來", "couldn't join the streamed video"))
    with open(out[0], "rb") as fh:
        blob = fh.read()
    if not is_mp4(blob):
        raise ValueError(T("不是影片檔", "not a video"))
    return blob, out[0]


def is_svg(b):
    """SVG 向量圖（網站標誌、圖示、插畫常是這個）也收。只看開頭，不是 HTML 就算。"""
    head = b[:2048].lstrip().lower()
    return (head.startswith(b"<svg") or head.startswith(b"<?xml")) and b"<svg" in head and b"<html" not in head


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".bmp", ".tiff", ".svg")


def sniff_ext(b):
    """網址沒有副檔名（或是 .php 這種）時看檔頭決定。"""
    if b[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return ".webp"
    if b[4:8] == b"ftyp":
        return ".heic" if b[8:12] in (b"heic", b"heix") else ".avif"
    if b[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    if is_svg(b):
        return ".svg"
    return ".jpg"


def image_size(b):
    """從檔頭讀寬高（JPEG／PNG／GIF／WebP／AVIF・HEIC），不解碼。讀不出來回 (None, None)。
    「拿到多大」（完成畫面）靠這個——量的是真的存下來的那個檔，不是網站說的數字。"""
    try:
        if b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR":
            return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return int.from_bytes(b[6:8], "little"), int.from_bytes(b[8:10], "little")
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            c = b[12:16]
            if c == b"VP8X":
                return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
            if c == b"VP8 ":
                return int.from_bytes(b[26:28], "little") & 0x3FFF, int.from_bytes(b[28:30], "little") & 0x3FFF
            if c == b"VP8L":
                v = int.from_bytes(b[21:25], "little")
                return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if b[:3] == b"\xff\xd8\xff":
            i, n = 2, len(b)
            while i + 9 < n:
                if b[i] != 0xFF:
                    i += 1
                    continue
                m = b[i + 1]
                if m == 0xFF:                                  # 填充位元組
                    i += 1
                    continue
                if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:     # 沒有長度欄的標記
                    i += 2
                    continue
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
                i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
        if is_svg(b):
            head = b[:4096].decode("utf-8", "replace")
            tag = re.search(r"<svg\b[^>]*>", head, re.S)
            if tag:
                t = tag.group(0)
                wm = re.search(r'\bwidth=["\']([\d.]+)(?:px)?["\']', t)
                hm = re.search(r'\bheight=["\']([\d.]+)(?:px)?["\']', t)
                if wm and hm:
                    return round(float(wm.group(1))), round(float(hm.group(1)))
                vb = re.search(r'viewBox=["\']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', t)
                if vb:
                    return round(float(vb.group(1))), round(float(vb.group(2)))
            return None, None
        if b[4:8] == b"ftyp":
            # HEIC 常是格狀拼圖：每一塊（512×512）各有一個 ispe，整張圖的那個最大——取面積最大的
            best, j = (None, None), b.find(b"ispe")
            while 0 < j and j + 16 <= len(b):
                w, h = int.from_bytes(b[j + 8:j + 12], "big"), int.from_bytes(b[j + 12:j + 16], "big")
                if w * h > (best[0] or 0) * (best[1] or 0):
                    best = (w, h)
                j = b.find(b"ispe", j + 4)
            if best[0]:
                return best
        if b[:4] in (b"II*\x00", b"MM\x00*"):
            bo = "little" if b[:2] == b"II" else "big"
            off = int.from_bytes(b[4:8], bo)
            n = int.from_bytes(b[off:off + 2], bo)
            w = h = None
            for k in range(n):
                e = off + 2 + 12 * k
                tag, typ = int.from_bytes(b[e:e + 2], bo), int.from_bytes(b[e + 2:e + 4], bo)
                val = int.from_bytes(b[e + 8:e + 10], bo) if typ == 3 else int.from_bytes(b[e + 8:e + 12], bo)
                if tag == 256:
                    w = val
                elif tag == 257:
                    h = val
            if w and h:
                return w, h
    except Exception:
        pass
    return None, None


def file_image_size(path):
    try:
        with open(path, "rb") as fh:
            return image_size(fh.read(262144))
    except OSError:
        return None, None


def data_dir():
    d = os.environ.get("FULLY_DATA_DIR") or os.path.expanduser("~/Library/Application Support/Fully")
    os.makedirs(d, exist_ok=True)
    return d


class HashIndex:
    """同一張不存兩次：記住存放資料夾裡每張圖的 sha256。
    索引住 FULLY_DATA_DIR/hash-index.json（{路徑: [大小, mtime, sha]}），每次開工只重算新增或改過的檔；
    檔案被使用者搬走或丟掉，索引自動忘記它——比對只認「現在還在」的檔。"""

    MAX_FILE = 60 * 1024 * 1024

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.path = os.path.join(data_dir(), "hash-index.json")
        self.files, self.by_sha = {}, {}
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.files = (json.load(fh) or {}).get("files") or {}
        except Exception:
            self.files = {}
        # 暫存資料夾（測試、存到暫存夾）裡的檔：已經不在就忘掉，索引不用一直背著（只 stat 這幾個，不掃全部）
        tmp = tuple({os.path.realpath(tempfile.gettempdir()) + "/", os.path.realpath("/tmp") + "/", "/tmp/"})
        for pth in [p for p in self.files if p.startswith(tmp) and not os.path.exists(p)]:
            self.files.pop(pth, None)
        return self

    def refresh(self, limit=40000):
        """掃 root 底下的圖：新的或改過的才讀檔算 sha。第一次掃很多張時先講一聲（約每秒數百張）。"""
        todo, seen = [], set()
        for dirpath, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for nm in names:
                if nm.startswith(".") or not nm.lower().endswith(IMAGE_EXTS):
                    continue
                pth = os.path.join(dirpath, nm)
                try:
                    st = os.stat(pth)
                except OSError:
                    continue
                seen.add(pth)
                old = self.files.get(pth)
                if old and old[0] == st.st_size and abs(old[1] - st.st_mtime) < 1:
                    continue
                if st.st_size <= self.MAX_FILE:
                    todo.append((pth, st.st_size, st.st_mtime))
                if len(seen) >= limit:
                    break
        if len(todo) > 300:
            emit(type="notice", message=T(f"第一次比對重複的圖（{len(todo)} 張），要一點時間…",
                                          f"Indexing {len(todo)} images for duplicate checks — one-time, takes a moment…"))
        for pth, size, mt in todo:
            try:
                h = hashlib.sha256()
                with open(pth, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                self.files[pth] = [size, mt, h.hexdigest()]
            except OSError:
                pass
        # root 底下已經不在的檔從索引拿掉（別的 root 的留著：換過存放位置也照樣認得）
        prefix = self.root.rstrip("/") + "/"
        for pth in [p for p in self.files if p.startswith(prefix) and p not in seen]:
            self.files.pop(pth, None)
        self.by_sha = {}
        for pth, v in self.files.items():
            self.by_sha.setdefault(v[2], pth)
        return self

    def lookup(self, sha):
        with self.lock:
            p = self.by_sha.get(sha)
            if not p or os.path.exists(p):
                return p
            # 記的那份不在了：同一張可能還有別的副本（別的資料夾），找到就改認它
            for q, v in self.files.items():
                if v[2] == sha and q != p and os.path.exists(q):
                    self.by_sha[sha] = q
                    return q
            self.by_sha.pop(sha, None)
        return None

    def add(self, sha, path, size):
        with self.lock:
            try:
                mt = os.path.getmtime(path)
            except OSError:
                mt = time.time()
            self.files[path] = [size, mt, sha]
            self.by_sha.setdefault(sha, path)

    def add_file(self, path):
        """外部工具自己寫檔的路線：寫完再補進索引；回之前已存在的同一張（重複時），否則 None。"""
        try:
            st = os.stat(path)
            if st.st_size > self.MAX_FILE:
                return None
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
        except OSError:
            return None
        prior = self.lookup(sha)
        self.add(sha, path, st.st_size)
        return prior if prior and prior != path else None

    def save(self):
        """跟硬碟上的版本合併再寫（追蹤與手動下載可能同時在跑），先寫暫存再換名，不留半截檔。"""
        try:
            with open(self.path, encoding="utf-8") as fh:
                disk = (json.load(fh) or {}).get("files") or {}
        except Exception:
            disk = {}
        prefix = self.root.rstrip("/") + "/"
        merged = {p: v for p, v in disk.items() if not p.startswith(prefix)}
        merged.update(self.files)
        tmp = self.path + f".{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "files": merged}, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass


class Seen:
    """資料夾裡的 .fully-seen：抓過的圖（網頁掃圖的 id）一行一個。追蹤來源「只抓新的」靠它。"""

    def __init__(self, folder):
        self.path = os.path.join(folder, ".fully-seen")
        self.ids, self.new = set(), []
        self.lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.ids = {ln.strip() for ln in fh if ln.strip()}
        except OSError:
            pass

    def add(self, rid):
        with self.lock:
            if rid not in self.ids:
                self.ids.add(rid)
                self.new.append(rid)

    def save(self):
        if not self.new:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write("".join(f"{r}\n" for r in self.new))
            self.new = []
        except OSError:
            pass


class DLResult:
    """download() 的結果。可以照舊 `ok, skipped, failed = download(...)` 拆開，也可以拿更多欄位。"""

    def __init__(self):
        self.ok = self.skipped = self.failed = self.dups = self.small = 0
        self.videos = 0             # 存下來的裡面有幾支是影片（圖版裡的影片 pin）
        self.files, self.best, self.dup_of, self.page_w = [], (0, 0), None, None
        self.best_file = None       # 最大那張的路徑：一整批的縮圖用它（第一張常是地圖、標誌）

    def __iter__(self):
        return iter((self.ok, self.skipped, self.failed))


def download(rows, folder, min_bytes=0, workers=6, per_host=4, dedup=None, seen=None, only_new=False):
    """圖片下載（多條同時）：全域 workers 條、同一個主機最多 per_host 條，跟瀏覽器開頁的連線數同級。
    實測 12 張 1280 寬的圖：一張一張 21.3 秒 → 同時 6 張 3.9 秒。
    min_bytes：小於這個大小的直接不落地（icon／sprite）。圖片先讀進記憶體驗過才寫檔，不會留半截檔、不做任何刪檔。
    dedup：HashIndex——一模一樣的圖已經存過就不再存一份（算「已經有了」）。
    seen／only_new：追蹤來源用——抓過的 id 記在資料夾的 .fully-seen，only_new 時直接跳過。"""
    os.makedirs(folder, exist_ok=True)
    have = existing_ids(folder)
    total = len(rows)
    res = DLResult()
    sems, sem_lock, stop = {}, threading.Lock(), threading.Event()

    def host_sem(u):
        h = urllib.parse.urlparse(u).hostname or ""
        with sem_lock:
            if h not in sems:
                strict = any(h == d or h.endswith("." + d) for d in FAIR_UA_HOSTS)   # 對限流嚴格的站客氣一點
                sems[h] = threading.Semaphore(2 if strict else per_host)
            return sems[h]

    def work(i, r):
        if stop.is_set():
            return "bad", T("停下來了", "stopped")
        rid = str(r["id"])
        if rid in have or (only_new and seen is not None and rid in seen.ids):
            return "skip", None
        blob = used = src_file = None
        last = None
        vid = bool(r.get("video"))
        for cand in [r["url"]] + list(r.get("alts") or []):
            try:
                with host_sem(cand):
                    if vid and r.get("hls") and cand == r["url"]:
                        blob, src_file = fetch_hls(cand, r.get("referer"))
                    else:
                        blob = fetch_bytes(cand, r.get("referer"), video=vid)
                used = cand
                break
            except Exception as e:
                last = e
        if blob is None:
            return "bad", str(last)[:60]
        if min_bytes and not vid and len(blob) < min_bytes:
            # 檔案小不一定是圖示：有些原圖本來就只有 400 px、13 KB（Wikimedia 上的老照片）——量得到而且夠大就照存
            sw, sh = image_size(blob)
            if not (sw and sh and max(sw, sh) >= 400 and min(sw, sh) >= 200):
                return "small", len(blob)
        sha = hashlib.sha256(blob).hexdigest()
        if dedup is not None:
            prior = dedup.lookup(sha)
            if prior:
                if seen is not None:
                    seen.add(rid)
                return "dup", prior
        ext = os.path.splitext(urllib.parse.urlparse(used).path)[1].lower()
        if vid:
            ext = ext if ext in (".mp4", ".mov", ".m4v") else ".mp4"
        elif ext not in IMAGE_EXTS:
            ext = sniff_ext(blob)
        slug = safe_name(r.get("title") or "")
        stem = f"{i:03d}_{slug}_{rid}" if slug else f"{i:03d}_{rid}"
        path = os.path.join(folder, stem + ext)
        try:
            moved = False
            if src_file:                            # 串流影片在暫存區已經是一個完整的檔：搬過去，不留第二份
                try:
                    os.replace(src_file, path)
                    moved = True
                except OSError:
                    pass
            if not moved:
                with open(path, "wb") as fh:
                    fh.write(blob)
        except OSError as e:
            if e.errno == 28:                       # ENOSPC：磁碟滿了，其他條也別再試
                stop.set()
                return "nospace", None
            return "bad", str(e)[:60]
        w, h = (None, None) if vid else image_size(blob)
        if not w:
            w, h = r.get("w"), r.get("h")
        if dedup is not None:
            dedup.add(sha, path, len(blob))
        if seen is not None:
            seen.add(rid)
        return "ok", (path, w, h, len(blob), r)

    done_n, nospace = 0, False
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(work, i, r): i for i, r in enumerate(rows, 1)}
        for fut in as_completed(futs):
            try:
                kind, info = fut.result()
            except Exception as e:
                kind, info = "bad", str(e)[:60]
            done_n += 1
            if kind == "ok":
                path, w, h, size, r = info
                res.ok += 1
                res.videos += 1 if r.get("video") else 0
                res.files.append(path)
                if w and h and w * h > res.best[0] * res.best[1]:
                    res.best = (w, h)
                    res.page_w = r.get("page_w")
                    res.best_file = path
                dim = f"{w}×{h}" if w else f"{size / 1024:.0f} KB"
                note = r.get("note") or ""                 # 來源模組想補一句的（例如「只存了封面」）
                log(f"  [{done_n}/{total}] {dim:>11}  {os.path.basename(path)[:52]}{note}")
                emit(type="item", index=done_n, kind="", dim=dim, file=os.path.basename(path)[:44])
            elif kind == "dup":
                res.dups += 1
                res.dup_of = info
                log(f"  [{done_n}/{total}] 已經有一模一樣的：{os.path.basename(info)[:40]}")
                emit(type="item", index=done_n, kind="dup", dim="—", file="")
            elif kind in ("skip", "small"):
                res.skipped += 1
                if kind == "small":
                    res.small += 1
                # 跳過的列刻意只留一個破折號 —— 整面重複的「已有 跳過」很吵，大字與副標已經講完了
                emit(type="item", index=done_n, kind="skip", dim="—", file="")
            else:
                if kind == "nospace":
                    nospace = True
                res.failed += 1
                log(f"  [{done_n}/{total}] 失敗：{info}")
                emit(type="item", index=done_n, kind="bad", dim=T("失敗", "failed"), file=(info or "")[:48])
    if seen is not None:
        seen.save()
    if nospace:
        if dedup is not None:
            dedup.save()
        die(T("磁碟空間不夠了。先清出一點空間再抓一次，已經抓到的都留著。",
              "Your disk is full. Free up some space and try again — everything saved so far is kept."), nospace=True)
    return res


# ─── 旗標與共用判斷 ───────────────────────────────────────────────────────

# 旗標（main() 依命令列填好）：
#   pick      只抓預覽時挑過的那幾項（逗號分隔的 id；清單型來源是 1 起算的序號）
#   sub       追蹤來源的定期檢查：只抓新的
#   baseline  剛開始追蹤，把現有的全記成「看過了」
#   items     --probe 時連每一項都列出來（挑幾張用）
OPT = {"pick": None, "sub": False, "baseline": False, "items": False}


def picked(rows):
    """挑幾張：OPT pick 有值就只留挑到的那幾筆。"""
    if not OPT["pick"]:
        return rows
    want = {p.strip() for p in OPT["pick"].split(",") if p.strip()}
    return [r for r in rows if str(r.get("id")) in want]


def pick_range():
    """清單型來源的挑選＝序號，格式 1,3,5-9。不合格式就當沒挑。"""
    p = (OPT["pick"] or "").replace(" ", "")
    return p if p and re.fullmatch(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*", p) else None


def _expand_range(spec):
    out = set()
    for part in (spec or "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                out.update(str(k) for k in range(int(a), int(b) + 1))
        elif part.isdigit():
            out.add(part)
    return out


def img_done(res):
    """圖片路線 done 事件的共同欄位（「拿到多大」）：
    w／h／dims＝這批存下來最大的那張（量檔頭，不是網站說的）；page_w＝那張在原頁面上的顯示寬（知道才給）；
    dups＝一模一樣早就存過、這次沒再存的張數；單張時 file＝那個檔（完成畫面縮圖、剪貼簿、拖出都用它）。"""
    d = {"dups": res.dups, "small": res.small}
    if res.videos:
        d["videos"] = res.videos        # 一批裡有幾支是影片（完成畫面另外講）
    if res.best[0]:
        d.update(w=res.best[0], h=res.best[1], dims=f"{res.best[0]}×{res.best[1]}")
        if res.page_w:
            d["page_w"] = res.page_w
    if res.ok == 1 and res.files:
        d["file"] = res.files[0]
    elif res.ok > 1 and res.files:
        d["first"] = res.best_file or sorted(res.files)[0]   # 一整批：最大那張當縮圖（預覽卡、通知、完成畫面）
    elif res.ok == 0 and res.dups and res.dup_of:
        d["dup_of"] = res.dup_of
    return d


# 縮圖網址裡的寬度線索（WordPress -300x200、?w=500、format=750w、/236x/、_500.jpg…）。
# 知道頁面上那張多寬，完成畫面才能講「頁面上那張的 N 倍」；猜不到就不講，不編數字。
WIDTH_HINTS = [re.compile(p, re.I) for p in (
    r"-(\d{2,4})x\d{2,4}\.(?:jpe?g|png|gif|webp|avif)", r"[?&](?:w|width|mw|maxwidth|max-w|imwidth)=(\d{2,4})\b",
    r"[?&]format=(\d{2,4})w\b", r"/s(\d{2,4})(?:-h\d+)?(?:-[a-z-]+)?/", r"=[sw](\d{2,4})(?:-h\d+)?[^/]*$",
    r"/(\d{2,4})x/(?=[0-9a-f]{2}/)", r"_(\d{3,4})\.(?:jpe?g|png|gif)(?:$|\?)", r"/max/(\d{2,4})/", r"resize:fit:(\d{2,4})",
    r"[/,]w_(\d{2,4})\b", r"_rw_(\d{3,4})", r"-p-(\d{2,4})\.", r"/mw(\d{3,4})/", r"@(\d{2,4})w", r"_(\d{2,4})w\.",
    r"il_(\d{2,4})x", r"s-l(\d{2,4})\.", r"\._S[XLY](\d{2,4})_", r"/fit/(\d{2,4})/", r"/(\d{2,4})x\d{2,4}/",
    r"/(\d{2,4})px-[^/]+$")]                      # MediaWiki 縮圖：…/thumb/…/220px-X.jpg


def width_hint(url):
    for rx in WIDTH_HINTS:
        m = rx.search(url or "")
        if m:
            n = int(m.group(1))
            if 16 <= n <= 4000:
                return n
    return None


def _host(u):
    """取主機名並去掉 www. 前綴。注意：不能用 lstrip("www.")——那是字元集，
    會把 wikipedia.org 剝成 ikipedia.org。"""
    h = (urllib.parse.urlparse(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


# 自帶的二進位（Resources/bin/）：不押在使用者機器裝過什麼工具上，要用的全部包進 app。
# 引擎本身也凍成獨立執行檔（fully-engine，見 engine/freeze.sh），跟其他工具住同一個 bin/。
# 凍結後 __file__ 指向啟動時的暫存解壓目錄，只有 sys.executable 才是 bin/ 裡的真位置。
FROZEN = bool(getattr(sys, "frozen", False))


BUNDLED_BIN = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
               else os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))


def find_ffmpeg_dir():
    """回傳含 ffmpeg 的目錄（拼總覽圖用）。沒有就 None。"""
    if os.path.exists(os.path.join(BUNDLED_BIN, "ffmpeg")):
        return BUNDLED_BIN
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
        if os.path.exists(os.path.join(d, "ffmpeg")):
            return d
    from shutil import which
    w = which("ffmpeg")
    return os.path.dirname(w) if w else None


def no_space():
    die(T("磁碟空間不夠了。先清出一點空間再抓一次，已經抓到的都留著。",
             "Your disk is full. Free up some space and try again — everything saved so far is kept."), nospace=True)


def _stream_lines(p, idle_limit):
    """逐行吐出子程序的 stdout（bytes→str）。連續 idle_limit 秒沒有任何輸出就當它卡死：
    砍掉、補一行 "__idle__" 讓呼叫端知道（偶發的網路卡住會讓一項停十分鐘沒動靜，
    單獨重抓同一項幾秒就好——不能讓使用者乾等）。
    用 os.read＋select 而不是 for line in p.stdout：文字包裝層會預讀，select 會被騙。"""
    import select
    fd = p.stdout.fileno()
    buf = b""
    while True:
        ready, _, _ = select.select([fd], [], [], idle_limit)
        if not ready:
            try:
                p.terminate()
            except Exception:
                pass
            yield "__idle__"
            return
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode("utf-8", "replace").rstrip()
    if buf.strip():
        yield buf.decode("utf-8", "replace").rstrip()


def contact_sheet(paths, sheet, ffmpeg, cols=5, cell=(320, 180)):
    """把一串圖片拼成一張接觸表（每格縮進 cell 的框、補滿、cols 欄）。抽影格與圖片批次共用。"""
    if not paths:
        return None
    rows = max(1, -(-len(paths) // cols))
    listfile = sheet + ".list.txt"
    with open(listfile, "w") as fh:
        for pth in paths:
            fh.write("file '" + pth.replace("'", "'\\''") + "'\n")
    w, h = cell
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listfile,
           "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=#EEEFF2,tile={cols}x{rows}:padding=6:margin=12:color=#EEEFF2",
           "-frames:v", "1", "-q:v", "3", sheet]
    try:
        ok = subprocess.run(cmd, capture_output=True, text=True, timeout=600).returncode == 0
    except Exception:
        ok = False
    try:
        os.replace(listfile, os.path.join(os.path.dirname(sheet), ".sheet-list.txt"))
    except OSError:
        pass
    return sheet if ok and os.path.exists(sheet) else None


IMG_SHEET_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".tiff")


def sheet_for_images(folder, since, minimum=6, cap=60):
    """圖片批次（情境 2：整個板／整個專案）抓完，≥ minimum 張就出一張「接觸表.jpg」讓人一眼看完。
    只拿這次新抓的（mtime ≥ since），最多 cap 張；已有接觸表就不重做。"""
    if not folder or not os.path.isdir(folder):
        return None
    sheet = os.path.join(folder, "接觸表.jpg")
    if os.path.exists(sheet):
        return None
    ffdir = find_ffmpeg_dir()
    if not ffdir:
        return None
    imgs = []
    for f in sorted(os.listdir(folder)):
        pth = os.path.join(folder, f)
        if f.startswith(".") or not f.lower().endswith(IMG_SHEET_EXT) or not os.path.isfile(pth):
            continue
        try:
            if os.path.getmtime(pth) >= since - 2:
                imgs.append(pth)
        except OSError:
            pass
    if len(imgs) < minimum:
        return None
    return contact_sheet(imgs[:cap], sheet, os.path.join(ffdir, "ffmpeg"), cols=5, cell=(320, 240))


def _ensure_ca_certs():
    """HTTPS 憑證驗證的保險絲（凍結版才可能用到）。
    獨立執行檔內的 OpenSSL 認的是編譯時寫死的憑證路徑；目前 python-build-standalone
    指向 /etc/ssl/cert.pem（每台 macOS 系統自帶，不靠 CLT／Homebrew，實測載到 128 張根憑證）。
    萬一哪天預設路徑載不到任何 CA，就退兩級：先指系統那份 cert.pem，再不然從系統鑰匙圈
    匯出根憑證。SSL_CERT_FILE 對之後建立的每個 context 都生效（含 urllib 隱含建的）。
    子程序也吃這個環境變數：包內的 ffmpeg 是靜態組建，它自己的 OpenSSL 認的是組建機上的路徑，
    在使用者的 Mac 上一張根憑證都載不到（「certificate verify failed」）——所以一律把系統那份指給它
    （使用者自己設過 SSL_CERT_FILE 就不動）。"""
    import ssl
    for cafile in ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"):
        if os.path.exists(cafile):
            os.environ.setdefault("SSL_CERT_FILE", cafile)
            break
    try:
        if ssl.create_default_context().cert_store_stats().get("x509_ca", 0) > 0:
            return
    except Exception:
        pass
    for cafile in ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"):
        if os.path.exists(cafile):
            os.environ["SSL_CERT_FILE"] = cafile
            return
    try:
        pem = subprocess.run(
            ["/usr/bin/security", "find-certificate", "-a", "-p",
             "/System/Library/Keychains/SystemRootCertificates.keychain"],
            capture_output=True, text=True, timeout=10).stdout
        if "BEGIN CERTIFICATE" in pem:
            cache = os.path.expanduser("~/Library/Caches/ltd.intention.fullsize")
            os.makedirs(cache, exist_ok=True)
            path = os.path.join(cache, "system-roots.pem")
            with open(path, "w") as f:
                f.write(pem)
            os.environ["SSL_CERT_FILE"] = path
    except Exception:
        pass


def tag_where_from(folder, url, since):
    """把來源網址寫進每個新檔的「來源」欄（kMDItemWhereFroms，Finder 資訊窗看得到、Spotlight 可搜）。
    Safari 下載就是這樣做的；用 xattr 指令（macOS 內建），失敗靜默。最多 500 檔。"""
    if not folder or not os.path.isdir(folder):
        return
    try:
        import plistlib
        hexval = plistlib.dumps([url], fmt=plistlib.FMT_BINARY).hex()
    except Exception:
        return
    n = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.startswith("."):
                continue
            path = os.path.join(root, f)
            try:
                if os.path.getmtime(path) < since - 2:
                    continue
                subprocess.run(["/usr/bin/xattr", "-wx", "com.apple.metadata:kMDItemWhereFroms", hexval, path],
                               capture_output=True, timeout=10)
                n += 1
            except Exception:
                pass
            if n >= 500:
                return

DEDUP = None          # HashIndex：同一張不存兩次（app 設定開著時 grab.main 會設好；別的模組用 core.DEDUP 讀，別 from-import）
CUR = {"url": ""}     # 這一趟的原始網址（錯誤訊息要告訴介面是哪個站）

# 站名對照（網域片段, 名稱）；預設是空的＝一律顯示網域
LABELS = []


def site_label(url):
    """預覽卡上的來源名稱。"""
    h = _host(url)
    for k, v in LABELS:
        if k in h:
            return v
    return h or T("網頁", "Web page")
