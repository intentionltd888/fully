# -*- coding: utf-8 -*-
"""
media — 公開版掛進 grab.py 的影片線與圖版解析。

認得的影片網址直接交給 video.py（yt-dlp：最高畫質＋QuickTime 可播保證、只要聲音、每個鏡頭截圖、標題與留言）；
圖版與單張 pin 交給 pin_grab.py（整個圖版讀到底、影片 pin 存影片本身、多頁的 pin 每一頁都存）；
Threads 貼文與個人頁交給 threads_grab.py（圖片原尺寸、影片最高畫質、輪播每一項、作者自己的串文）；
其他網址照常當網頁掃圖，頁面掃不到圖、或只拿得到分享預覽圖時，再問一次影片線。
只處理公開看得到的內容：不帶任何帳號資料。
grab.py 認得的鉤子：SWITCHES／VALUED／take_flags／media_only／session／kind_of／probe／probe_fallback／
  web_fallback／dispatch／baseline
"""

import core as pg
from core import T, _host
import video as VIDEO
import pin_grab as PIN
import threads_grab as THREADS


# ─── 旗標 ────────────────────────────────────────────────────────────────

SWITCHES = {"--audio", "--data", "--frames"}
VALUED = {"--archive": "archive"}


def take_flags(flags, vals):
    pg.OPT.update(audio="--audio" in flags, data="--data" in flags, frames="--frames" in flags,
                  archive=vals.get("archive"))


def media_only():
    """這一趟不存圖（只要聲音／標題與留言）：不做重複比對、不出總覽圖。"""
    return bool(pg.OPT.get("audio") or pg.OPT.get("data"))


def session():
    return pg.Session()


# ─── 來源判斷、預覽、分派 ─────────────────────────────────────────────────

def kind_of(url):
    host = _host(url)
    if PIN.claims(host) and PIN.handles(url):
        return "board"
    if THREADS.claims(host) and THREADS.handles(url):
        return "post"
    return "video" if VIDEO.is_video_host(host) or VIDEO.is_video_file(url) else None


def probe(kind, url):
    """影片網址、圖版的預覽；None＝交給 grab.py 的通用掃圖預覽。"""
    if kind == "video":
        return VIDEO.probe(url) or {}
    if kind == "board":
        return PIN.probe(url)
    if kind == "post":
        return THREADS.probe(url)
    return None


def probe_fallback(url):
    """通用掃圖一張都沒看到（或只有分享預覽圖）：問影片線認不認得。"""
    return VIDEO.probe(url) or None


def web_fallback(url, dest):
    """頁面掃不到圖（或只有分享預覽圖）：影片線認得就接手，回 True。"""
    return VIDEO.try_video(url, dest)


def dispatch(url, dest, kind, sess):
    """True＝這裡處理完了；False＝交回 grab.py 的通用掃圖。"""
    opt = pg.OPT
    if kind == "video":
        VIDEO.grab_video(url, dest, audio=opt["audio"], data=opt["data"], frames=opt["frames"])
        return True
    if opt["data"] or opt["frames"]:
        pg.emit(type="notice", message=T("這個來源沒有「標題與留言／每個鏡頭截圖」，照一般方式抓原始尺寸",
                                         "That option is for videos — grabbing this one at original size instead"))
    if kind == "board":
        PIN.grab_board(url, dest, sess)
        return True
    if kind == "post":
        THREADS.grab_post(url, dest, sess)
        return True
    return False


def baseline(url):
    """開始追蹤影片清單：寫 yt-dlp 的下載紀錄（只列清單不下載，幾秒）；其他來源不用做事。"""
    if VIDEO.is_video_host(_host(url)) and pg.OPT.get("archive"):
        return VIDEO.baseline(url)
    return 0
