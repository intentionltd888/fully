#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pin_grab — Pinterest 圖版解析（兩版共用）。

貼一個 Pinterest 連結，抓下該圖版（或單張 pin）的原始檔，不是瀑布流上的縮圖（236x / 474x）：
  圖片        點進 pin 才看得到的 orig
  影片 pin    影片本身（mp4 裡最大的那支；只有串流格式時，下載端用 ffmpeg 接成 mp4）
  Idea pin    多頁的每一頁（圖或影片）都存

支援：
  https://pin.it/xxxxxxx                 短網址
  https://www.pinterest.com/user/board/  圖版（整個讀到底，一次讀 100 張）
  https://www.pinterest.com/user/board/section/  圖版分區
  https://www.pinterest.com/pin/1234567/ 單張 pin
只讀公開的圖版與 pin，不帶任何帳號資料。搜尋結果與個人頁不歸這裡管（handles() 回 False）。
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse

import core
import core as pg
from core import (T, UA, TIMEOUT, OPT, emit, log, die, read_body, with_retry, Session, safe_name, download,
                  picked, img_done, _host)

_session = Session          # 預覽用的連線
_gallery = None             # 搜尋結果與個人頁的解析器（沒有＝交回通用掃圖）

core.LABELS += [("pinterest.", "Pinterest"), ("pin.it", "Pinterest")]


def claims(host):
    """grab.py 問：這個主機歸不歸圖版解析管。"""
    return "pinterest." in host or host == "pin.it"


def handles(url):
    """圖版、圖版分區、單張 pin、短網址才歸這裡；搜尋結果、個人頁、其他頁面交回去。"""
    if _host(url) == "pin.it":
        return True
    segs = [s for s in urllib.parse.urlparse(url).path.split("/") if s]
    if not segs:
        return False
    if segs[0] == "pin":
        return len(segs) >= 2
    if segs[0] in ("search", "ideas", "today", "settings", "business", "_", "categories", "topics"):
        return False
    return len(segs) >= 2          # /使用者/圖版/（/分區/）；只有一段＝個人頁


def api(sess, resource, options, source_url, handler):
    """Pinterest 內部 resource API（csrftoken 是門票）。"""
    import urllib.request
    data = json.dumps({"options": options, "context": {}}, separators=(",", ":"))
    url = (f"https://www.pinterest.com/resource/{resource}/get/"
           f"?source_url={urllib.parse.quote(source_url, safe='')}"
           f"&data={urllib.parse.quote(data, safe='')}"
           f"&_={int(time.time() * 1000)}")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "gzip",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": sess.csrf,
        "X-APP-VERSION": "ab1af2a",
        "X-Pinterest-AppState": "active",
        "X-Pinterest-Source-Url": source_url,
        "X-Pinterest-PWS-Handler": handler,
        "Referer": "https://www.pinterest.com" + source_url,
    })
    return with_retry(lambda: json.loads(read_body(sess.opener.open(req, timeout=TIMEOUT))), f"{resource}")


# 一次讀 100 張（25 張一頁的話，一萬多張的圖版要翻四百多次）。不設張數上限：讀到 Pinterest 說「沒有了」為止。
# SAFETY_PAGES 只防「書籤一直不結束」這種異常（20 萬張），正常的圖版碰不到。
PAGE_SIZE = 100
SAFETY_PAGES = 2000


def best_image(pin):
    """回傳 (url, 寬, 高)。優先 orig，沒有就挑解析度最大的那個尺寸（Idea pin 每頁的圖叫 originals）。"""
    imgs = pin.get("images") or {}
    if isinstance(imgs.get("orig"), dict) and imgs["orig"].get("url"):
        o = imgs["orig"]
        return o["url"], o.get("width"), o.get("height")
    best = None
    for v in imgs.values():
        if isinstance(v, dict) and v.get("url"):
            area = (v.get("width") or 0) * (v.get("height") or 0)
            if best is None or area > best[0]:
                best = (area, v["url"], v.get("width"), v.get("height"))
    return (best[1], best[2], best[3]) if best else (None, None, None)


def image_alts(imgs, chosen):
    """原圖偶爾回 403（Pinterest 那邊的檔不見了）：其他尺寸由大到小當備援，不讓那張整個抓不到。"""
    c = [((v.get("width") or 0) * (v.get("height") or 0), v["url"]) for v in (imgs or {}).values()
         if isinstance(v, dict) and v.get("url") and v["url"] != chosen]
    return [u for _, u in sorted(c, key=lambda t: t[0], reverse=True)]


# 同一個尺寸有好幾支 mp4 時的偏好：不帶 _t 字尾的 V_EXP7 是原檔，_t1…_t4 是壓過的
VIDEO_PREF = ("V_EXP7", "V_720P", "V_EXP6", "V_EXP5", "V_EXP4", "V_EXP3")


def best_video(video_list):
    """video_list → (網址, 寬, 高, 備援, 是不是串流)。mp4 取最大的那支（同尺寸照 VIDEO_PREF）；
    一支 mp4 都沒有才用串流（m3u8，下載端用 ffmpeg 接成 mp4）。都沒有回 None。"""
    def area_pref(kv):
        k, v = kv
        return ((v.get("width") or 0) * (v.get("height") or 0), -VIDEO_PREF.index(k) if k in VIDEO_PREF else -99)
    items = [(k, v) for k, v in (video_list or {}).items() if isinstance(v, dict) and v.get("url")]
    mp4 = sorted([kv for kv in items if kv[1]["url"].split("?")[0].endswith(".mp4")], key=area_pref, reverse=True)
    if mp4:
        v = mp4[0][1]
        return v["url"], v.get("width"), v.get("height"), [x["url"] for _, x in mp4[1:]], False
    hls = sorted([kv for kv in items if ".m3u8" in kv[1]["url"]], key=area_pref, reverse=True)
    if hls:
        v = hls[0][1]
        return v["url"], v.get("width"), v.get("height"), [], True
    return None


def _title(pin):
    for key in ("grid_title", "title", "auto_alt_text", "description"):
        v = pin.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def pin_rows(pin):
    """一個 pin → 要下載的檔：一般 pin 一張圖；影片 pin 存影片本身；多頁的 Idea pin 每一頁的圖或影片都存。
    id 都是純數字（existing_ids 認得出來，抓過的下次會跳過）：影片＝pin id＋00；Idea pin 第 k 頁＝pin id＋兩位數 k。
    只有一頁的 Idea pin 圖、一般的圖沿用 pin id（以前抓過的不會重抓）。"""
    if not isinstance(pin, dict) or not pin.get("id"):
        return []
    pid = str(pin["id"])
    imgs = pin.get("images") or {}
    thumb = next((imgs[k]["url"] for k in ("236x", "474x", "170x") if isinstance(imgs.get(k), dict) and imgs[k].get("url")), None)
    base = {"title": _title(pin), "referer": "https://www.pinterest.com/"}

    def video_row(rid, vl):
        v = best_video(vl)
        if not v:
            return None
        url, w, h, alts, hls = v
        return dict(base, id=rid, url=url, w=w, h=h, alts=alts, video=True, hls=hls, thumb=thumb or url)

    vl = (pin.get("videos") or {}).get("video_list")
    if vl:
        r = video_row(pid + "00", vl)
        if r:
            return [r]

    pages = (pin.get("story_pin_data") or {}).get("pages") or []
    out = []
    for k, page in enumerate(pages, 1):
        n = 0
        for b in page.get("blocks") or []:
            rid = f"{pid}{k:02d}" + (str(n + 1) if n else "")
            if b.get("block_type") == 3 and (b.get("video") or {}).get("video_list"):
                r = video_row(rid, b["video"]["video_list"])
            elif b.get("block_type") == 2 and (b.get("image") or {}).get("images"):
                u, w, h = best_image(b["image"])
                r = dict(base, id=pid if len(pages) == 1 and not n else rid, url=u, w=w, h=h,
                         alts=image_alts(b["image"]["images"], u), thumb=thumb or u, page_w=236) if u else None
            else:
                r = None
            if r:
                out.append(r)
                n += 1
    if out:
        return out

    url, w, h = best_image(pin)
    if not url:
        return []
    return [dict(base, id=pid, url=url, w=w, h=h, alts=image_alts(imgs, url),
                 thumb=thumb or url, page_w=236)]   # 236＝圖版瀑布流的格子寬（「頁面上的幾倍大」用）


def collect_from_board(sess, final_url, html, max_pages=None):
    """max_pages：預覽卡只要第一頁（名字、張數、縮圖）就夠，不用把整個板翻完。"""
    m = (re.search(r'\[\\"board_id\\",\\"(\d+)\\"\]', html)
         or re.search(r'"board_id"\s*:\s*\\?"(\d+)\\?"', html))
    if not m:
        # 圖版不存在 / 不公開的圖版時，Pinterest 照樣回 HTTP 200 但頁面沒有 board_id
        return None, None, False, 0
    board_id = m.group(1)

    parsed = urllib.parse.urlparse(final_url)
    source_url = parsed.path + (("?" + parsed.query) if parsed.query else "")

    # 圖版名以 API 為正本。頁面標籤不可靠 —— Pinterest 有時整個不回 <title>，
    # 而且改名後 slug 不變，只能問 API 才知道現在叫什麼。
    name = None
    expected = 0
    try:
        j = api(sess, "BoardResource", {"board_id": board_id, "field_set_key": "detailed"},
                source_url, "www/[username]/[slug].js")
        d = (j.get("resource_response") or {}).get("data") or {}
        v = d.get("name")
        if isinstance(v, str) and v.strip():
            name = v.strip()
        expected = int(d.get("pin_count") or 0)
    except Exception:
        pass
    if not name:
        for pat in (r"<h1[^>]*>([^<]{1,80})</h1>", r"<title>([^<]+)</title>"):
            m2 = re.search(pat, html)
            if m2:
                cand = re.sub(r"^Pinterest\s*(上的|の)?\s*", "", m2.group(1)).strip()
                cand = re.sub(r"\s*\|\s*Pinterest\s*$", "", cand).strip()
                if cand:
                    name = cand
                    break

    rows, seen, bookmark, pins, idle = [], set(), None, 0, 0
    collect_from_board.cut = False
    for page_no in range(max_pages or SAFETY_PAGES):
        opts = {"add_vase": True, "board_id": board_id,
                "field_set_key": "react_grid_pin", "filter_section_pins": False,
                "is_react": True, "prepend": False, "page_size": PAGE_SIZE,
                "redux_normalize_feed": True, "gated": False}
        if bookmark:
            opts["bookmarks"] = [bookmark]
        # 中途某頁讀不到就停＝靜默截斷（以前有人回報「只下載部分幾張」）。大圖版讀到後面常被限流（429）：
        # 分段等久一點再接著讀，每次都講；真的讀不下去才停，而且讓 resolve() 講清楚是被限流、再抓一次會接著補。
        j = None
        for wait in (0, 15, 30, 60):
            if wait:
                log(f"    第 {page_no + 1} 頁被擋，{wait} 秒後再試…")
                emit(type="notice", message=T(f"Pinterest 要我們慢一點，{wait} 秒後接著讀（已找到 {pins} 個）",
                                              f"Pinterest asked us to slow down — continuing in {wait}s ({pins} pins so far)"))
                time.sleep(wait)
            try:
                j = api(sess, "BoardFeedResource", opts, source_url, "www/[username]/[slug].js")
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception:
                pass                                  # 連線不穩：一樣等一下再試
        if j is None:
            if page_no == 0:
                return None, name, True, expected
            collect_from_board.cut = True
            log(f"    第 {page_no + 1} 頁一直讀不到，先處理已取得的 {pins} 個")
            break
        rr = j.get("resource_response") or {}
        before = pins
        for p in rr.get("data") or []:
            if not isinstance(p, dict) or not p.get("id") or str(p["id"]) in seen:
                continue
            got = pin_rows(p)
            if got:
                seen.add(str(p["id"]))
                pins += 1
                rows.extend(got)
        idle = idle + 1 if pins == before else 0
        log(f"    讀取中… 已找到 {pins} 個 pin")
        if not max_pages and page_no and page_no % 5 == 0:
            emit(type="notice", message=T(f"讀取圖版清單…已找到 {pins} 個",
                                          f"Reading the board… {pins} pins so far"))
        bookmark = rr.get("bookmark") or (rr.get("bookmarks") or [None])[0]
        if not bookmark or bookmark == "-end-" or idle >= 3:
            break
        time.sleep(0.35)
    collect_from_board.pins = pins
    return rows, name, True, expected


def pin_page_row(html):
    """單張 pin 的保底（API 讀不到時）：og:image 一定是主圖（但只有 736x），把它換算成 originals。
    頁面上第一個 originals 網址常常是「相關推薦」，不能直接拿。"""
    og = (re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
          or re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', html))
    if not og:
        return []
    src = og.group(1)
    m = re.search(r'i\.pinimg\.com/[^/]+/((?:[0-9a-f]{2}/){3}[0-9a-f]{16,})\.(\w+)', src)
    if not m:
        return [{"id": "pin", "url": src, "w": None, "h": None,
                 "title": "", "alts": []}]
    path, ext = m.group(1), m.group(2)
    hit = re.search(r'https://i\.pinimg\.com/originals/' + re.escape(path) + r'\.\w+', html)
    base = f"https://i.pinimg.com/originals/{path}"
    alts = [f"{base}.{e}" for e in ("jpg", "png", "webp", "gif") if e != ext]
    return [{"id": path.rsplit("/", 1)[-1],
             "url": hit.group(0) if hit else f"{base}.{ext}",
             "w": None, "h": None, "title": "", "thumb": src, "page_w": 736,   # 單張 pin 頁載的是 736x
             "referer": "https://www.pinterest.com/",
             "alts": alts + [src]}]


def single_pin_rows(sess, final_url, html):
    """單張 pin：先問 API 拿整個 pin（影片、Idea pin 的每一頁都在裡面），讀不到才退回頁面上的主圖。"""
    m = re.search(r"/pin/(\d+)", urllib.parse.urlparse(final_url).path)
    if m:
        try:
            j = api(sess, "PinResource", {"id": m.group(1), "field_set_key": "detailed"},
                    urllib.parse.urlparse(final_url).path, "www/pin/[id].js")
            d = (j.get("resource_response") or {}).get("data") or {}
            rows = pin_rows(d)
            if rows:
                for r in rows:
                    if not r.get("video"):
                        r["page_w"] = 736
                return rows
        except Exception:
            pass
    return pin_page_row(html)


def collect_from_html(html, name_hint=None):
    """保底：直接從伺服器渲染的 HTML 撈 originals 網址。"""
    urls = re.findall(r'https://i\.pinimg\.com/originals/[0-9a-f/]+\.(?:jpg|jpeg|png|webp|gif)', html)
    seen, rows = set(), []
    for u in dict.fromkeys(urls):
        key = u.rsplit("/", 1)[-1].split(".")[0]
        if key in seen:
            continue
        seen.add(key)
        rows.append({"id": key, "url": u, "w": None, "h": None,
                     "title": "", "referer": "https://www.pinterest.com/"})
    return rows, name_hint


def resolve(sess, link, max_pages=None):
    link = link.strip().strip("<>\"' ")
    if not link.startswith("http"):
        link = "https://" + link.lstrip("/")
    log(f"  → 解析連結 {link}")
    try:
        final_url, html = sess.get_page(link)
    except urllib.error.HTTPError as e:
        die(T(f"打不開這個連結（HTTP {e.code}）。確認一下網址對不對、圖版是不是公開的。",
              f"Couldn't open this link (HTTP {e.code}). Check the address and that the board is public."))
    except Exception as e:
        die(T(f"連線失敗：{e}", f"Connection failed: {e}"))

    resolve.expected = 0
    if "/pin/" in urllib.parse.urlparse(final_url).path:
        rows = single_pin_rows(sess, final_url, html)
        if not rows:
            die(T("這張 pin 讀不到。可能不是公開的，或已被刪除。", "Couldn't read this pin. It may not be public, or it was deleted."))
        # pin 頁的 <title> 是「標題 | 一串相關標籤」，第一個分隔線之後全是雜訊
        title = re.search(r"<title>([^<]+)</title>", html)
        name = re.split(r"\s*[|｜]\s*", title.group(1))[0].strip() if title else "pin"
        name = re.sub(r"^Pinterest\s*(上的|の)?\s*", "", name).strip() or rows[0].get("title") or "pin"
        return rows, name or "pin", final_url

    rows, name, is_board, expected = collect_from_board(sess, final_url, html, max_pages)
    resolve.expected = expected          # 預覽卡要「圖版標示幾張」，只讀第一頁時 len(rows) 不準
    if not is_board:
        die(T("找不到這個圖版。網址打錯、圖版被刪、或不是公開的圖版都會這樣。",
              "Board not found. The address may be wrong, or the board was deleted or isn't public."))
    if not rows:
        log("    圖版 API 讀不到，改用頁面內嵌資料（可能只抓得到部分）")
        rows, name = collect_from_html(html, name)
    if not rows:
        die(T("這個圖版讀得到，但一張圖都沒抓到。可能是空圖版，或 Pinterest 改版了。",
              "The board opened but no images came back. It may be empty, or Pinterest changed something."))

    pins = getattr(collect_from_board, "pins", 0) or len(rows)
    if getattr(collect_from_board, "cut", False) and not max_pages:
        log(f"  Pinterest 暫時不讓我們讀下去，先抓已讀到的 {pins} 個")
        emit(type="notice", message=T(f"Pinterest 暫時限制讀取，先抓已讀到的 {pins} 個；過幾分鐘再抓一次，會接著補完（抓過的會跳過）",
                                      f"Pinterest is limiting requests — grabbing the {pins} pins read so far. Grab again in a few minutes to get the rest (saved ones are skipped)"))
    elif expected and pins < expected and not max_pages:
        log(f"  圖版標示 {expected} 個 pin，Pinterest 給了 {pins} 個（其餘多半已被移除或隱藏）")
        emit(type="notice", message=T(f"圖版標示 {expected} 個，Pinterest 只給得出 {pins} 個（其餘多半已被移除或隱藏），全部抓下來",
                                      f"The board says {expected} pins; Pinterest returns {pins} (the rest were likely removed or hidden) — grabbing all of them"))
    if not name:
        parts = [p for p in urllib.parse.urlparse(final_url).path.split("/") if p]
        name = parts[-1] if parts else "pinterest"
    return rows, name, final_url


def grab_pinterest(url, dest, sess):
    rows, name, _ = resolve(sess, url)
    rows = picked(rows)
    folder = os.path.join(dest, pg.safe_name(name, 60, keep_space=True) or "pinterest")
    nv = sum(1 for r in rows if r.get("video"))

    pg.log(f"\n  圖版：{name}")
    pg.log(f"  檔數：{len(rows)}" + (f"（其中影片 {nv} 支）" if nv else ""))
    pg.log(f"  存到：{folder}\n")
    pg.emit(type="source", kind="pinterest", name=name, count=len(rows), folder=folder,
            label=T("Pinterest 圖版", "Pinterest board") if "/pin/" not in url else T("Pinterest 單張", "Pinterest pin"))

    res = pg.download(rows, folder, dedup=pg.DEDUP)
    pg.log(f"\n  完成 — 新下載 {res.ok} 個"
           + (f"（影片 {res.videos} 支）" if res.videos else "")
           + (f"、已存在跳過 {res.skipped} 個" if res.skipped else "")
           + (f"、一模一樣已經有的 {res.dups} 個" if res.dups else "")
           + (f"、失敗 {res.failed} 個" if res.failed else ""))
    pg.emit(type="done", added=res.ok, skipped=res.skipped, failed=res.failed, folder=folder,
            headline=name[:40], **img_done(res))


grab_board = grab_pinterest       # 掛勾那邊用的中性名字


def probe(url):
    if not handles(url):
        return (_gallery.probe(url) if _gallery else None) or None
    sess = _session()
    rows, name, final = resolve(sess, url, max_pages=None if OPT["items"] else 1)
    single = "/pin/" in urllib.parse.urlparse(final).path
    big = max(rows, key=lambda r: (r.get("w") or 0) * (r.get("h") or 0)) if rows else {}
    out = {"name": name, "count": len(rows) if single else (getattr(resolve, "expected", 0) or len(rows)),
           "thumb": (rows[0].get("thumb") if rows else None), "w": big.get("w"), "h": big.get("h"),
           "page_w": big.get("page_w")}
    if OPT["items"] and not single:
        out["items"] = [{"id": str(r["id"]), "thumb": r.get("thumb") or r["url"], "title": (r.get("title") or "")[:60],
                         "w": r.get("w"), "h": r.get("h")} for r in rows]
    return out


# ─── 單獨跑（終端機）──────────────────────────────────────────────────────

def main():
    argv = [a for a in sys.argv[1:] if a != "--json"]
    if not argv:
        die("用法：pin_grab.py [--json] <Pinterest 連結> [目的地資料夾]")
    grab_pinterest(argv[0], argv[1] if len(argv) > 1 else os.path.expanduser("~/Downloads"), Session())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("已取消", 130)
