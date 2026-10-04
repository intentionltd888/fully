# -*- coding: utf-8 -*-
"""
video — 影片線（兩版共用）。

yt-dlp（最高畫質＋QuickTime 可播保證）、只要聲音、每個鏡頭截圖、標題與留言、網址帶時間點另存那一格、
影片預覽、追蹤清單的下載紀錄。只處理公開看得到的影片：不帶任何帳號資料。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

import core as pg
from core import (T, OPT, BUNDLED_BIN, FROZEN, _host, site_label,
                  pick_range, _expand_range, no_space, find_ffmpeg_dir, contact_sheet)

# 影片的要法（grab.py 的擴充依命令列填進 OPT）：audio／data／frames；archive＝追蹤影片清單用的下載紀錄檔
OPT.setdefault("archive", None)
for _k in ("audio", "data", "frames"):
    OPT.setdefault(_k, False)

# 認得的影片站：直接走影片線（其他網址先當網頁掃圖，掃不到圖或只有分享預覽圖時再問 yt-dlp）
HOSTS = (
    "youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com",
    "bilibili.com", "b23.tv", "tiktok.com",
    "instagram.com", "facebook.com", "twitch.tv", "dailymotion.com",
    "youku.com", "nicovideo.jp", "douyin.com", "rumble.com", "streamable.com",
)

# 頁面不是公開的（要帳號才看得到）：各站的錯誤字樣
NOT_PUBLIC_ERR = re.compile(r"only works when logged-in|Failed to fetch \w+ OAuth token|"
                            r"requires authentication|Private video|login required", re.I)


def _account_args():
    """這一趟要帶給 yt-dlp 的帳號參數（公開版一律沒有）。"""
    return []


def _not_public():
    pg.die(T("這支影片不是公開的。Fully 只存公開看得到的內容。",
             "This video isn't public. Fully only saves what's publicly visible."), not_public=True, site=_host(pg.CUR["url"]))




def is_video_host(host):
    # 比網域不比子字串：「x.com」是 vox.com、dropbox.com、firefox.com 的子字串
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def find_ytdlp():
    """Application Support 的自更新版（FULLY_YTDLP，app 的 Engines.swift 每天更新）→ 包內出廠版 → Homebrew → PATH → python 模組。"""
    managed = os.environ.get("FULLY_YTDLP", "")
    if managed and os.access(managed, os.X_OK):
        return [managed]
    bundled = os.path.join(BUNDLED_BIN, "yt-dlp")
    if os.path.exists(bundled):
        return [bundled]
    for p in ("/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp", "/opt/local/bin/yt-dlp"):
        if os.path.exists(p):
            return [p]
    from shutil import which
    w = which("yt-dlp")
    if w:
        return [w]
    if FROZEN:
        return None   # 凍結後 sys.executable 是引擎自己，不是能 -m yt_dlp 的直譯器
    try:
        subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                       capture_output=True, check=True, timeout=20)
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return None


def is_our_ytdlp(yt):
    """是我們散布／更新的官方 yt-dlp（包內或 Application Support），不是使用者自己裝的舊版。"""
    if not yt:
        return False
    ours = {os.path.join(BUNDLED_BIN, "yt-dlp"), os.environ.get("FULLY_YTDLP", "")}
    return yt[0] in ours


def js_runtime_args(yt):
    """yt-dlp 抓 YouTube 要一個 JavaScript runtime 解 n 挑戰，沒有的機器整站只剩縮圖
    （yt-dlp 會報「n challenge solving failed… Only images are available」）。
    包內帶 quickjs-ng（自建 arm64、最低 macOS 11，約 1 MB）；`--js-runtimes` 是「加開」不是取代——
    有 Homebrew deno 的機器 yt-dlp 仍優先用 deno（快），沒有的才落到包內 qjs（一支多花幾秒）。
    只在用包內 yt-dlp 時加（系統裝的舊版 yt-dlp 可能不認這個選項）。"""
    qjs = os.path.join(BUNDLED_BIN, "qjs")
    if is_our_ytdlp(yt) and os.path.exists(qjs):
        return ["--js-runtimes", f"quickjs:{qjs}"]
    return []


def nightly_ytdlp(current):
    """搶先版槽：YouTube 改版當天穩定版常常還沒修，官方原話「有問題的人應該改裝 nightly」。
    槽位在 FULLY_ENGINES_DIR/yt-dlp-nightly：沒有就從現用的複製一份，再讓它自己 --update-to nightly@latest
    （它會驗 SHA2-256SUMS）。更新失敗或起不來就回 None，不影響穩定版。"""
    d = os.environ.get("FULLY_ENGINES_DIR", "")
    if not d:
        return None
    try:
        os.makedirs(d, exist_ok=True)
        slot = os.path.join(d, "yt-dlp-nightly")
        if not os.path.exists(slot):
            import shutil
            shutil.copy2(current, slot)
            os.chmod(slot, 0o755)
        subprocess.run([slot, "--update-to", "nightly@latest"], capture_output=True, text=True, timeout=240)
        v = subprocess.run([slot, "--version"], capture_output=True, text=True, timeout=30)
        if v.returncode == 0 and v.stdout.strip():
            pg.log(f"  搶先版 yt-dlp {v.stdout.strip()}")
            return slot
    except Exception:
        pass
    return None


# YouTube 換線路階梯：yt-dlp 預設的 android_vr 線在部分網路抓媒體段被 403
# （穩定版與 nightly 都一樣，-4／-6 也一樣），但 web_embedded 客戶端拿得到同一份完整格式表
# （2160p60／H.264 到 1080p60／AAC）而且抓得動；tv／mweb 只剩 360p，當最後保底並明講。
# 第一級留 yt-dlp 自己的預設，讓它日後修好時我們自動跟上。
YT_LADDER = [
    ([], None),
    (["--extractor-args", "youtube:player_client=web_embedded"],
     "YouTube 擋了預設線路，換一條再抓…"),
    (["--extractor-args", "youtube:player_client=tv,mweb"],
     "備用線路只拿得到 360p，先抓下來…"),
]


YT_RETRY = re.compile(r"HTTP Error 403|Requested format is not available", re.I)


# QuickTime 可播保證：畫質不打折＋自動轉檔。
# YouTube 高解析（1440p+）只給 VP9/AV1＋常配 Opus —— QuickTime 全都不認。
# -S 排序已讓 ≤1080p 直接挑到原生 H.264+AAC（零轉檔）；走到這裡的多半是 4K，
# 用 Apple VideoToolbox 硬體編碼轉 HEVC（快、耗電低），音訊轉 AAC。
COMPAT_V = ("h264", "hevc")


COMPAT_A = ("aac",)


def ensure_playable(path, progress=None):
    ffdir = find_ffmpeg_dir()
    if not ffdir or not os.path.isfile(path):
        return
    ffmpeg = os.path.join(ffdir, "ffmpeg")
    ffprobe = os.path.join(ffdir, "ffprobe")
    if not os.path.exists(ffprobe):
        ffprobe = "ffprobe"
    try:
        j = json.loads(subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=60).stdout or "{}")
    except Exception:
        return
    streams = j.get("streams") or []
    v = next((x for x in streams if x.get("codec_type") == "video"), {})
    a = next((x for x in streams if x.get("codec_type") == "audio"), {})
    vcodec = (v.get("codec_name") or "").lower()
    acodec = (a.get("codec_name") or "").lower()
    ok_v = vcodec in COMPAT_V
    ok_a = (not a) or acodec in COMPAT_A
    if ok_v and ok_a:
        return                                   # 原生可播，什麼都不用做

    dur = float((j.get("format") or {}).get("duration") or 0)
    height = int(v.get("height") or 0)
    # 位元率：跟原檔同級，抓不到就按解析度給
    br = int(v.get("bit_rate") or 0) \
        or {2160: 18_000_000, 1440: 10_000_000, 1080: 6_000_000}.get(height) \
        or max(4_000_000, height * 4000)

    pg.log(f"  轉成 QuickTime 可播格式（{vcodec or '?'}/{acodec or '無聲'} → "
           f"{'不動' if ok_v else 'HEVC'}/AAC）…")
    pg.emit(type="notice", message=T("轉成 QuickTime 可播的格式…", "Converting to a format QuickTime can play…"))

    tmp = path + ".轉檔中.mp4"
    ten_bit = "10" in (v.get("pix_fmt") or "")

    # 重試階梯（單一路徑失敗就放行原檔＝把 QuickTime 打不開的檔交出去）：
    #   ① HEVC（10-bit 來源帶 main10）→ ② HEVC 8-bit → ③ H.264 8-bit（QuickTime 鐵定認）
    ladders = []
    if ok_v:
        ladders.append(["-c:v", "copy"])
    else:
        if ten_bit:
            ladders.append(["-c:v", "hevc_videotoolbox", "-b:v", str(br),
                            "-tag:v", "hvc1", "-profile:v", "main10"])
        ladders.append(["-c:v", "hevc_videotoolbox", "-b:v", str(br),
                        "-tag:v", "hvc1", "-pix_fmt", "yuv420p"])
        ladders.append(["-c:v", "h264_videotoolbox", "-b:v", str(br),
                        "-pix_fmt", "yuv420p"])

    def run_once(vargs):
        cmd = [ffmpeg, "-y", "-hide_banner", "-i", path, "-map", "0:v:0"]
        if a:
            cmd += ["-map", "0:a:0"]
        cmd += ["-map", "0:s?", "-c:s", "copy"] + vargs
        if a:
            cmd += (["-c:a", "copy"] if ok_a else ["-c:a", "aac", "-b:a", "256k"])
        cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", tmp]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, bufsize=1)
            for line in proc.stdout:
                if line.startswith("out_time_ms=") and dur > 0 and progress:
                    try:
                        progress(min(99.0, int(line.split("=")[1]) / 1_000_000 / dur * 100))
                    except ValueError:
                        pass
            proc.wait()
            return proc.returncode == 0 and os.path.getsize(tmp) > 1000
        except Exception:
            return False

    def tmp_compatible():
        """轉完再驗一次才算數 —— 不驗就放行等於沒轉。"""
        try:
            jj = json.loads(subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", tmp],
                capture_output=True, text=True, timeout=60).stdout or "{}")
        except Exception:
            return False
        vv = next((x for x in (jj.get("streams") or []) if x.get("codec_type") == "video"), {})
        aa = next((x for x in (jj.get("streams") or []) if x.get("codec_type") == "audio"), {})
        return ((vv.get("codec_name") or "").lower() in COMPAT_V and
                ((not aa) or (aa.get("codec_name") or "").lower() in COMPAT_A))

    done_ok = False
    for vargs in ladders:
        if run_once(vargs) and tmp_compatible():
            done_ok = True
            break

    if done_ok:
        os.replace(tmp, path)                    # 換掉自己剛下載的中繼檔（非使用者資料）
    else:
        pg.log("  轉檔失敗，保留原始檔（IINA／VLC 可播）")
        pg.emit(type="notice", message=T("這支轉不成 QuickTime 格式，保留原始畫質檔（IINA／VLC 可播）",
                                         "Couldn't convert this one for QuickTime — kept the original (plays in IINA or VLC)"))




IMP_RETRY = re.compile(r"HTTP Error 403|Cloudflare|cf-mitigated|Unsupported browser|challenge", re.I)


def video_info(path):
    """影片拿到多大（完成畫面）：寬高、每秒幾格、HDR，量存下來的檔。"""
    ffdir = find_ffmpeg_dir()
    if not ffdir or not path or not os.path.isfile(path):
        return {}
    probe = os.path.join(ffdir, "ffprobe")
    try:
        j = json.loads(subprocess.run([probe, "-v", "quiet", "-print_format", "json", "-show_streams", path],
                                      capture_output=True, text=True, timeout=60).stdout or "{}")
    except Exception:
        return {}
    v = next((x for x in (j.get("streams") or []) if x.get("codec_type") == "video"), None)
    if not v or not v.get("width"):
        return {}
    w, h = int(v["width"]), int(v["height"])
    fps = 0
    try:
        a, b = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1").split("/")
        fps = round(float(a) / float(b or 1)) if float(b or 1) else 0
    except Exception:
        pass
    hdr = (v.get("color_transfer") or "") in ("smpte2084", "arib-std-b67")
    short = min(w, h)
    res = f"{short}p" if short in (144, 240, 360, 480, 720, 1080, 1440, 2160, 4320) else f"{h}p"
    return {"w": w, "h": h, "dims": f"{w}×{h}", "res": res, "fps": fps, "hdr": hdr}


def grab_video(url, dest, audio=False, data=False, frames=False, signed_out=None):
    # signed_out：圖庫站的退路（_signed_out_probe 的結果）——不再探測一次、只抓影片項目、檔名帶 id
    orig_url = url
    yt = find_ytdlp()
    if not yt:
        pg.die(T("找不到 yt-dlp，影片下載需要它。終端機跑 `brew install yt-dlp` 就好。",
                  "yt-dlp is missing — video downloads need it. Reinstall Fully, or run `brew install yt-dlp`."))
    yt_extra = js_runtime_args(yt)
    if is_our_ytdlp(yt) and "youtu" in _host(url):
        # 解題腳本（yt-dlp-ejs）跟 yt-dlp 本體分開發版；允許它自己去 GitHub 拉最新的，YouTube 改版時多半只要這個就修好
        yt_extra += ["--remote-components", "ejs:github"]
    yt_bin = yt[0]
    pg.log(f"  yt-dlp：{yt_bin}（{'自更新版' if yt_bin == os.environ.get('FULLY_YTDLP') else '出廠版／系統版'}）")
    yt = yt + yt_extra

    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")

    cookie_args = _account_args()
    no_dash = False                  # 換到 Vimeo 內嵌播放器時設 True（見下面）

    def probe(extra):
        try:
            r = subprocess.run(yt + cookie_args + extra + ["-J", "--no-warnings", "--flat-playlist",
                                             "--skip-download", url],
                               capture_output=True, text=True, timeout=75, env=env)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return 1, "", "逾時"
        # 注意：probe 讀的是外層的 url 變數 —— 換端點後要先改 url 再呼叫

    # 退路已經探測過了（看得到影片才會走到這裡）：不再問一次
    code, out, err = (0, "", "") if signed_out else probe([])

    # Vimeo 主站常回「不公開」，但「內嵌播放器端點」拿得到同一支公開影片 ——
    # player.vimeo.com/video/<id> ＋ Referer 標頭就拿得到格式（其他下載器走的就是這條）。
    if code != 0 and NOT_PUBLIC_ERR.search(err or "") and "vimeo.com" in url:
        m = re.search(r"vimeo\.com/(?:video/)?(\d+)(?:/([0-9a-f]+))?", url)
        if m and "player.vimeo.com" not in url:
            player = f"https://player.vimeo.com/video/{m.group(1)}"
            if m.group(2):                       # 未上市影片的 hash
                player += f"?h={m.group(2)}"
            ref = ["--referer", "https://vimeo.com/"]
            pg.log("  Vimeo 主站拿不到，改走內嵌播放器端點…")
            pg.emit(type="notice", message=T("改走 Vimeo 內嵌播放器…", "Trying Vimeo's embedded player…"))
            url = player
            # player 端點的 DASH 軌帶 DRM、HLS 軌乾淨 —— 探測與下載都要用「排除 DASH」的選擇器。
            # 不能把 -f 塞進 cookie_args：下載指令後面還有自己的 -f，後面的會蓋掉前面的，又選回帶 DRM 的軌
            #（探測成功、下載才報「有 DRM 保護」）。所以記一個旗標，組下載指令時直接換掉選擇器。
            cookie_args = cookie_args + ref
            no_dash = True
            code, out, err = probe(["-f", "bv*[protocol!*=dash]+ba[protocol!*=dash]/b[protocol!*=dash]"])

    # 不是公開的 → 公開版直接講清楚
    if code != 0 and NOT_PUBLIC_ERR.search(err or ""):
        if code != 0:
            _not_public()

    meta = (signed_out or {}).get("meta") or {}
    if out and out.strip():
        try:
            meta = json.loads(out) or {}         # -J 偶爾印 null——json.loads 會回 None
        except Exception:
            pass

    # 單支 vs 清單看「網址形狀」，不信探測 —— watch 連結常帶 list=（電台／合輯參數），
    # 照探測走會把側欄整串拉下來（貼一支拉下幾十支）。
    # 只有明確的 /playlist 頁才算清單。
    pu = urllib.parse.urlparse(url)
    forced_single = ("v=" in (pu.query or "")) or (pu.hostname or "").endswith("youtu.be")
    explicit_list = "/playlist" in (pu.path or "")

    title = (meta.get("title") or T("影片", "Video")).strip()
    entries = meta.get("entries") or []
    is_list = (not forced_single) and (
        explicit_list or (meta.get("_type") == "playlist" and len(entries) > 1))
    count = len(entries) if is_list else 1
    rng = (signed_out or {}).get("items") or pick_range()   # 退路：只抓貼文裡的影片項目（已含預覽時挑過的）
    if is_list and rng:
        count = len([e for k, e in enumerate(entries, 1) if str(k) in _expand_range(rng)])
    if forced_single and meta.get("_type") == "playlist" and entries:
        # 探測拿到的是清單名（「Radio」之類），跟使用者要的那支無關 —— 用第一項的名字
        title = (entries[0].get("title") or title).strip()

    folder = os.path.join(dest, pg.safe_name(title, 60, keep_space=True)) if is_list else dest
    os.makedirs(folder, exist_ok=True)

    pg.log(f"\n  影片：{title}")
    pg.log(f"  存到：{folder}\n")
    mode_name = "audio" if audio else ("data" if data else ("frames" if frames else "av"))
    if data:
        folder = os.path.join(dest, pg.safe_name(title, 60, keep_space=True))   # 資料模式一律開一夾（表格＋縮圖＋留言）
        os.makedirs(folder, exist_ok=True)
    pg.emit(type="source", kind="video", name=title, count=count, folder=folder,
            single=(not is_list) and not data, audio=audio, mode=mode_name,
            label=site_label(url) + "・" + (T("只要聲音", "audio only") if audio else (T("標題與留言", "titles & comments") if data
                                        else (T("每個鏡頭截圖", "shot frames") if frames else T("影片", "video")))))

    # ── 只要資料：不抓影片，抓標題／頻道／觀看數／發布日／長度／縮圖／留言 → 資料.csv＋留言.txt ──
    if data:
        return grab_data(url, folder, yt, cookie_args, env, is_list, title, count)

    ff = find_ffmpeg_dir()
    outlist = os.path.join(tempfile.gettempdir(), f"fully-out-{os.getpid()}.txt")
    nd = "[protocol!*=dash]" if no_dash else ""    # Vimeo 內嵌播放器：DASH 軌帶 DRM，只拿 HLS
    if audio:
        # 僅音訊：最佳音軌 → M4A（AAC，QuickTime 原生）
        # ＋封面＋中繼資料。獨立版 yt-dlp 內建 mutagen，--embed-thumbnail 可用。
        mode_args = ["-f", f"ba{nd}/b{nd}", "-x", "--audio-format", "m4a", "--audio-quality", "0",
                     "--embed-thumbnail", "--add-metadata"]
    else:
        fmt = f"bv*{nd}+ba{nd}/b{nd}" if ff else f"b{nd}"    # 沒 ffmpeg 就退單檔最佳（畫質受限），有才能合最高畫質
        mode_args = ["-f", fmt, "--remux-video", "mp4",
                     # 解析度永遠優先；同解析度挑 H.264/AAC（QuickTime 原生），挑不到才拿 VP9/AV1
                     "-S", "res,vcodec:h264,acodec:aac",
                     # 字幕不嵌進影片：有官方中／英字幕就
                     # 另存同名 .srt 在影片旁（播放器自動配對），沒有就靜默略過
                     "--sub-langs", "zh-Hant.*,zh.*,en.*",
                     "--write-subs", "--convert-subs", "srt"]
    # 退路的站標題都是同一個（輪播每一支同名）：檔名帶 id，不然第二支起會被當成「已經下載過」
    name_tpl = "%(title)s [%(id)s].%(ext)s" if signed_out else "%(title)s.%(ext)s"
    cmd_head = yt + cookie_args + (["--ffmpeg-location", ff] if ff else []) + mode_args + [
        "--print-to-file", "after_move:filepath", outlist,
        "--merge-output-format", "mp4",
        # 分段影片（HLS／DASH：Vimeo、IG、多數新聞站）同時抓 4 段；YouTube 的一般格式是整檔，不受影響
        "-N", "4",
        "--no-warnings", "--newline", "--no-playlist" if not is_list else "--yes-playlist",
        "--progress-template", "download:@@%(progress._percent_str)s|%(info.title)s",
        "-o", os.path.join(folder, name_tpl),
    ]
    if is_list and rng:
        cmd_head += ["--playlist-items", rng]
    if OPT["archive"]:                          # 追蹤中的清單：紀錄檔裡有的就跳過（只抓新的）
        cmd_head += ["--download-archive", OPT["archive"]]
    is_youtube = "youtu" in (pu.hostname or "")
    # 非 YouTube 站被 403／Cloudflare 擋 → 換成瀏覽器身分（curl_cffi，官方 yt-dlp_macos 內建）再試一次
    ladder = YT_LADDER if is_youtube else ([([], None), (["--impersonate", "chrome"],
                                             T("網站擋了一般連線，換成瀏覽器身分再試…", "The site blocked a plain request — retrying as a browser…"))]
                                           if is_our_ytdlp([yt_bin]) else [([], None)])

    # yt-dlp 分開抓影像流與聲音流，各自 0→100。直接照抄會讓進度倒退，
    # 所以把兩段映射到不重疊的區間，最後留給 ffmpeg 合併：
    #   影像 0–55％ ／ 聲音 55–90％ ／ 合併 90–100％
    STAGES = ([(0, 85, "音訊"), (85, 100, "處理")] if audio else
              [(0, 50, "影像"), (50, 72, "聲音"), (72, 80, "合併"), (80, 100, "轉檔")])
    stream, shown, tail = 0, -1, []

    def report(pct_in_stage, label):
        nonlocal shown
        lo, hi, stage = STAGES[min(stream, len(STAGES) - 1)]
        overall = min(99, int(lo + (hi - lo) * pct_in_stage / 100))
        if overall > shown:                      # 只准往前
            shown = overall
            pg.emit(type="progress", percent=overall, stage=stage, name=label[:40])
            pg.log(f"  {overall:3d}%  {stage}  {label[:48]}")

    def run_once(extra):
        """跑一次 yt-dlp，回 returncode（最後幾行留在外層的 tail）。進度只准往前（shown 不重設），
        換線路重來時階段歸零、百分比從上次停的地方接著走。"""
        nonlocal stream, tail
        stream, tail = 0, []
        p = subprocess.Popen(cmd_head + extra + [url], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("@@"):
                m = re.match(r"@@\s*([\d.]+)%\|(.*)", line)
                if m:
                    report(float(m.group(1)), m.group(2))
                continue
            if line.startswith("[download] Destination:"):
                if shown >= 0:
                    stream += 1
            elif line.startswith("[Merger]") or line.startswith("[VideoConvertor]"):
                stream = 2
                report(50, title)
            tail.append(line)
            del tail[:-8]
        p.wait()
        return p.returncode

    def run_ladder():
        rc, raw = 1, ""
        for step, (extra, note) in enumerate(ladder):
            if note:
                pg.log(f"  {note}")
                pg.emit(type="notice", message=note)
            rc = run_once(extra)
            if rc == 0:
                break
            raw = next((t for t in reversed(tail) if "ERROR" in t), "")
            raw = re.sub(r"^ERROR:\s*(\[\w+\]\s*)?", "", raw).strip()
            # 只有「被擋」這類錯才換線路；私人／地區／不公開之類換線路也沒用，直接往下報
            if not ((YT_RETRY if is_youtube else IMP_RETRY).search(raw) and step < len(ladder) - 1):
                break
        return rc, raw

    rc, raw = run_ladder()

    # YouTube 抓不到而且不是「不公開／私人／地區／DRM」這類換引擎也沒用的問題 → 多半是今天改版、穩定版還沒修。
    # 把搶先版槽更新到最新再整個階梯跑一次（只試一次）。
    YT_STALE = re.compile(r"403|format is not available|challenge|confirm you.re not a bot|"
                          r"Unable to extract|Failed to (extract|parse)|nsig|player", re.I)
    if (rc != 0 and is_youtube and is_our_ytdlp([yt_bin]) and YT_STALE.search(raw or "")
            and not NOT_PUBLIC_ERR.search(raw or "")
            and not re.search(r"private|removed|deleted|DRM|geo|country", raw or "", re.I)):
        pg.log("  YouTube 可能剛改版，改用搶先版引擎再試一次…")
        pg.emit(type="notice", message=T("YouTube 可能剛改版，正在換搶先版引擎再試一次…",
                                         "YouTube may have just changed — retrying with the preview engine…"))
        nb = nightly_ytdlp(yt_bin)
        if nb:
            cmd_head[0] = nb
            rc, raw = run_ladder()

    if rc != 0:
        if re.search(r"No space left|Errno 28", raw or "", re.I):
            no_space()
        elif NOT_PUBLIC_ERR.search(raw):
            _not_public()
        elif re.search(r"geo|country|region", raw, re.I):
            pg.die(T("這個影片有地區限制，這裡抓不到。", "This video is region-locked and can't be saved from here."))
        elif re.search(r"private|unavailable|removed|deleted", raw, re.I):
            pg.die(T("這個影片是私人的、或已經被移除了。", "This video is private or has been removed."))
        elif re.search(r"DRM|protected", raw, re.I):
            pg.die(T("這個影片有 DRM 保護，Fully 不處理受保護的內容。", "This video is DRM-protected. Fully doesn't handle protected content."))
        elif OPT["archive"] and re.search(r"already been recorded", raw or "", re.I):
            pass
        else:
            pg.die(raw[:110] or T("影片下載失敗。", "The video download failed."))

    # QuickTime 相容保證（多檔清單逐支處理；進度重用 80–100 的轉檔段）
    outs = []
    try:
        with open(outlist) as fh:
            outs = [ln.strip() for ln in fh if ln.strip()]
    except OSError:
        pass
    stream = len(STAGES) - 1
    if not audio:
        for f in outs:
            ensure_playable(f, progress=lambda pct: report(pct, title))

    # 抽影格：場景切換抽格（上限 60）＋一張接觸表，跟影片同夾
    sheet = None
    if frames and not audio and outs and ff:
        stream = len(STAGES) - 1
        pg.emit(type="progress", percent=90, stage="抽影格", name=title[:40])
        pg.emit(type="notice", message=T("正在找場景切換、抽影格…", "Finding scene changes and saving frames…"))
        for f in outs:
            r = extract_frames(f, ff, progress=lambda pct: pg.emit(type="progress", percent=int(90 + pct * 0.09), stage="抽影格", name=title[:40]))
            if r:
                sheet = r
                pg.log(f"  抽了影格＋接觸表：{os.path.basename(os.path.dirname(r))}")
                pg.emit(type="notice", message=T("每個鏡頭的截圖和總覽圖都存好了", "Shot frames and the overview sheet are saved"))

    # 網址帶時間點 → 另存那一格（提案簡報與分鏡參考常用；螢幕截圖只有縮圖畫質）
    frame = None
    if not audio and not is_list and outs and ff:
        t = _time_param(orig_url)
        if t is not None:
            frame = grab_frame(outs[0], t, os.path.join(ff, "ffmpeg"))
            if frame:
                pg.log(f"  另存 {_fmt_t(t)} 那一格：{os.path.basename(frame)}")
                pg.emit(type="notice", message=T(f"另存了 {_fmt_t(t)} 那一格（PNG）", f"Also saved the frame at {_fmt_t(t)} (PNG)"))

    pg.log(f"\n  完成 — {title}")
    vinfo = video_info(outs[0]) if (outs and not audio) else {}
    if is_list or OPT["archive"]:
        count = len(outs)                       # 清單＝這次真的新存了幾支（追蹤時跳過的不算）
    pg.emit(type="done", added=count, skipped=0, failed=0, folder=folder, **vinfo,
            headline=title[:40], frame=frame, sheet=sheet, file=(outs[0] if outs else None))


def extract_frames(video, ffdir, progress=None, cap=60, cols=5):
    """場景切換偵測抽格（select scene>0.3，上限 cap 張）；太少（<12）就改成平均每 N 秒一格。
    輸出：<影片同名> 影格/001.png…＋接觸表.jpg。回接觸表路徑；失敗回 None。"""
    ffmpeg = os.path.join(ffdir, "ffmpeg")
    ffprobe = os.path.join(ffdir, "ffprobe")
    stem, _ = os.path.splitext(video)
    outdir = f"{stem} 影格"
    os.makedirs(outdir, exist_ok=True)
    try:
        dur = float(subprocess.run([ffprobe, "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                   capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    except Exception:
        dur = 0
    pattern = os.path.join(outdir, "%03d.png")

    def run(vf):
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-vf", vf,
               "-vsync", "vfr", "-frames:v", str(cap), "-q:v", "2", pattern]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=900).returncode == 0
        except Exception:
            return False

    if progress:
        progress(10)
    ok = run("select='gt(scene,0.30)',scale='min(1920,iw)':-2")
    n = len([f for f in os.listdir(outdir) if f.endswith(".png")]) if ok else 0
    if n < 12 and dur > 0:
        # 場景切換太少（靜態畫面、單鏡頭）→ 補平均每 N 秒一格（不同前綴，兩批都留）
        step = max(1.0, dur / 30.0)
        pattern2 = os.path.join(outdir, "avg-%03d.png")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-vf", f"fps=1/{step:.3f},scale='min(1920,iw)':-2",
               "-frames:v", str(cap), "-q:v", "2", pattern2]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except Exception:
            pass
    frames = sorted(f for f in os.listdir(outdir) if f.endswith(".png"))
    if not frames:
        return None
    if progress:
        progress(70)
    sheet = contact_sheet([os.path.join(outdir, f) for f in frames], f"{stem} 接觸表.jpg", ffmpeg, cols=cols)
    if progress:
        progress(100)
    return sheet


def grab_data(url, folder, yt, cookie_args, env, is_list, title, count):
    """只要資料：yt-dlp --skip-download 拿 info.json＋縮圖＋留言，整理成 資料.csv 與 留言.txt。"""
    import csv
    pg.emit(type="progress", percent=10, stage="資料", name=title[:40])
    cmd = yt + cookie_args + ["--skip-download", "--write-info-json", "--write-thumbnail", "--write-comments",
                              "--extractor-args", "youtube:max_comments=200,all,0,0",
                              "--no-warnings", "--newline",
                              "--no-playlist" if not is_list else "--yes-playlist",
                              "-o", os.path.join(folder, "%(title)s.%(ext)s"), url]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        seen = 0
        for line in p.stdout:
            if "[info] Writing video metadata" in line or "Writing video metadata" in line:
                seen += 1
                pg.emit(type="progress", percent=min(85, 10 + int(75 * seen / max(1, count))), stage="資料", name=title[:40])
        p.wait()
    except Exception as e:
        pg.die(T(f"抓資料失敗：{e}", f"Couldn't get the details: {e}"))
    infos = sorted(f for f in os.listdir(folder) if f.endswith(".info.json"))
    if not infos:
        pg.die(T("這個來源拿不到資料（可能不是公開的或已被移除）。", "No details available for this source (it may not be public, or it was removed)."))
    pg.emit(type="progress", percent=90, stage="資料", name=title[:40])
    rows, comments_out = [], []
    for f in infos:
        try:
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                j = json.load(fh)
        except Exception:
            continue
        up = j.get("upload_date") or ""
        rows.append({
            "標題": j.get("title") or "", "頻道": j.get("uploader") or j.get("channel") or "",
            "觀看數": j.get("view_count") or "", "按讚數": j.get("like_count") or "",
            "留言數": j.get("comment_count") or len(j.get("comments") or []),
            "發布日": f"{up[:4]}-{up[4:6]}-{up[6:]}" if len(up) == 8 else up,
            "長度（秒）": j.get("duration") or "", "解析度": f"{j.get('width') or ''}x{j.get('height') or ''}",
            "網址": j.get("webpage_url") or j.get("original_url") or "",
        })
        cs = j.get("comments") or []
        if cs:
            comments_out.append(f"## {j.get('title') or ''}（前 {len(cs)} 則，按讚數排）")
            for c in sorted(cs, key=lambda c: -(c.get("like_count") or 0))[:200]:
                comments_out.append(f"- [{c.get('like_count') or 0}] {c.get('author') or ''}：{(c.get('text') or '').strip()}")
            comments_out.append("")
    with open(os.path.join(folder, "資料.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["標題"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    if comments_out:
        with open(os.path.join(folder, "留言.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(comments_out))
    pg.log(f"\n  資料：{len(rows)} 筆 → 資料.csv" + ("＋留言.txt" if comments_out else ""))
    pg.emit(type="done", added=len(rows), skipped=0, failed=0, folder=folder,
            headline=title[:40], csv=os.path.join(folder, "資料.csv"), file=os.path.join(folder, "資料.csv"))


def _time_param(url):
    """YouTube 的 t=83／t=1m23s／t=83s，或 #t=83。沒有就 None。"""
    pu = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(pu.query or "")
    raw = (q.get("t") or q.get("start") or [None])[0]
    if raw is None and pu.fragment.startswith("t="):
        raw = pu.fragment[2:]
    if not raw:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", raw.strip())
    if not m or not any(m.groups()):
        return None
    h, mnt, sec = (int(x or 0) for x in m.groups())
    return h * 3600 + mnt * 60 + sec


def _fmt_t(t):
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def grab_frame(video, t, ffmpeg):
    """把影片第 t 秒那一格存成同名 PNG（最高品質，不縮放）。失敗回 None、不影響主流程。"""
    stem, _ = os.path.splitext(video)
    out = f"{stem} @ {_fmt_t(t).replace(':', '-')}.png"
    try:
        r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                            "-ss", str(t), "-i", video, "-frames:v", "1", "-q:v", "1", out],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1000:
            return out
    except Exception:
        pass
    return None


def _best_thumb(m):
    if not isinstance(m, dict):
        return None
    th = [t for t in (m.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    if th:
        th.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0) or t.get("preference") or 0)
        mid = [t for t in th if 200 <= (t.get("width") or 0) <= 1280]
        return (mid[-1] if mid else th[-1])["url"]
    return m.get("thumbnail")


def probe(url):
    yt = find_ytdlp()
    if not yt:
        return {}
    extra = js_runtime_args(yt)
    if is_our_ytdlp(yt) and "youtu" in _host(url):
        extra += ["--remote-components", "ejs:github"]
    pu = urllib.parse.urlparse(url)
    forced_single = ("v=" in (pu.query or "")) or (pu.hostname or "").endswith("youtu.be")
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")

    def run(u, more):
        try:
            return subprocess.run(yt + extra + _account_args() + more + ["-J", "--flat-playlist", "--no-warnings", "--skip-download"]
                                  + (["--no-playlist"] if forced_single else []) + [u],
                                  capture_output=True, text=True, timeout=60, env=env)
        except subprocess.TimeoutExpired:
            return None

    r = run(url, [])
    if r is not None and r.returncode != 0 and NOT_PUBLIC_ERR.search(r.stderr or "") and "vimeo.com" in url:
        m = re.search(r"vimeo\.com/(?:video/)?(\d+)(?:/([0-9a-f]+))?", url)
        if m and "player.vimeo.com" not in url:
            r = run(f"https://player.vimeo.com/video/{m.group(1)}" + (f"?h={m.group(2)}" if m.group(2) else ""),
                    ["--referer", "https://vimeo.com/"])
    if r is None or r.returncode != 0:
        return {"not_public": True} if (r is not None and NOT_PUBLIC_ERR.search(r.stderr or "")) else {}
    try:
        meta = json.loads(r.stdout or "null") or {}
    except Exception:
        return {}
    entries = [e for e in (meta.get("entries") or []) if isinstance(e, dict)]
    is_list = (not forced_single) and ("/playlist" in (pu.path or "") or (meta.get("_type") == "playlist" and len(entries) > 1))
    out = {"name": (meta.get("title") or "").strip()[:120], "thumb": _best_thumb(meta) or (entries and _best_thumb(entries[0])) or None}
    if is_list:
        out["count"] = len(entries)
        out["list"] = True
        if OPT["items"]:
            out["items"] = [{"id": str(k + 1), "title": (e.get("title") or "")[:80], "thumb": _best_thumb(e),
                             "dur": e.get("duration")} for k, e in enumerate(entries[:300])]
    else:
        if forced_single and entries:
            meta = entries[0]
        out["count"] = 1
        out["duration"] = meta.get("duration")
        out.update(_top_format(meta))
    return out


def _top_format(meta):
    """預覽卡的「最高 1080p」：最高那一格的寬高、每秒幾格、HDR。"""
    fm = [f for f in (meta.get("formats") or []) if (f.get("vcodec") or "none") != "none" and f.get("height")]
    if not fm:
        return {}
    top = max(fm, key=lambda f: ((f.get("height") or 0), (f.get("fps") or 0)))
    return dict(w=top.get("width"), h=top.get("height"), fps=round(top.get("fps") or 0),
                hdr=any((f.get("dynamic_range") or "SDR") not in ("SDR", None) for f in fm))




def try_video(url, dest):
    """網頁掃不到圖時的後備：yt-dlp 的通用解析器認得就當影片抓。回 True＝處理完了。"""
    yt = find_ytdlp()
    if not yt:
        return False
    pg.log("  這一頁本身讀不到圖，改試影片…")
    pg.emit(type="notice", message=T("這一頁本身讀不到圖，改試影片…", "No images in the page itself — trying it as a video…"))
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    try:
        probe = subprocess.run(yt + _account_args() + ["-J", "--no-warnings", "--skip-download", url],
                               capture_output=True, text=True, timeout=75, env=env)
        if probe.returncode == 0 and probe.stdout.strip():
            grab_video(url, dest)
            return True
    except Exception:
        pass
    return False


def baseline(url):
    """開始追蹤影片清單：把現有每一支寫進下載紀錄（--force-write-archive，只列清單不下載），回記了幾支。"""
    yt = find_ytdlp()
    if not yt or not OPT["archive"]:
        return 0
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    try:
        subprocess.run(yt + js_runtime_args(yt) + _account_args() + ["--flat-playlist", "--force-write-archive", "--skip-download",
                       "--download-archive", OPT["archive"], "--no-warnings", url],
                       capture_output=True, text=True, timeout=300, env=env)
        with open(OPT["archive"], encoding="utf-8") as fh:
            return sum(1 for ln in fh if ln.strip())
    except Exception:
        return 0
