# Fully

[![下載 Fully（macOS）](https://img.shields.io/badge/%E4%B8%8B%E8%BC%89-macOS-000000?style=for-the-badge&logo=apple&logoColor=white&labelColor=000000)](https://github.com/intentionltd888/fully/releases/latest/download/Fully.dmg)
[![最新版本](https://img.shields.io/github/v/release/intentionltd888/fully?style=for-the-badge&label=%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC&labelColor=000000&color=555555)](https://github.com/intentionltd888/fully/releases/latest)
[![下載次數](https://img.shields.io/github/downloads/intentionltd888/fully/total?style=for-the-badge&label=%E4%B8%8B%E8%BC%89%E6%AC%A1%E6%95%B8&labelColor=000000&color=555555)](https://github.com/intentionltd888/fully/releases)

把你有權使用的圖片與影片，以原尺寸、最高畫質存下來。[English](README.en.md)

Fully 是 macOS 上的設計參考收集工具（design reference collector）：複製一個網頁的網址，它會掃出頁面上公開看得到的圖片，一張張換成原始尺寸再存下來——不是頁面上的縮圖。貼影片的網址，存最高畫質、存好直接能播的影片；貼圖版的網址，整個圖版讀到底。

## 它做什麼

- **複製就跳預覽卡**：在任何 app 複製網址，螢幕右上角浮出一張卡——縮圖、名稱、有幾張、最大能拿到多大、之前抓過沒。按「抓下來」才開始；不理它，幾秒後自己退場。卡片不搶鍵盤，複製完繼續打字不會誤觸。
- **原尺寸**：縮圖網址換成原圖（建站平台與圖片 CDN 的規則，加上 maxurl 規則庫）；完成畫面告訴你實際拿到多大、是頁面上那張的幾倍。
- **影片**：上千個影片網站，公開看得到的都行。最高畫質，存好 QuickTime 直接能播；也可以只要聲音、每個鏡頭截圖、標題與留言。網址帶時間點（t=83）會另存那一格畫面。影片引擎每天在背景跟上網站改版（設定裡可以關）。
- **圖版**：整個圖版讀到底、一張不漏；影片 pin 存影片本身，多頁的 pin 每一頁都存。貼分區的網址只抓那個分區；貼一個帳號的頁面，他每個公開圖版各存一個資料夾。
- **音檔**：網址直接指到音檔、網頁上的播放器與下載連結、Podcast 訂閱，都照原檔存、不轉檔。
- **貼文**：貼一則公開貼文的網址，輪播裡每一張圖和影片、作者自己接在下面的串文都存。圖片原尺寸；影片取那則貼文能給的最高畫質（直連的檔只到 720p、另有 1080p 畫面時，接上聲音並確保 QuickTime 能播）。
- **快，而且不打擾**：同時下載、對限流的網站客氣；下載中 Mac 不睡；Dock 圖示有進度條與排隊數，選單列有進度環；關掉再開會接著抓。
- **抓完馬上能用**：單張圖直接放進剪貼簿（⌘V 貼進設計軟體）；縮圖可以拖出去；每個檔的「來源」欄記著原網址（Spotlight 找得回來）。
- **之後**：追蹤一個網頁、圖版或影片清單，每 6 小時回去看一次、只抓新的；一模一樣的圖不存第二份；最近抓的留 30 筆。
- **從哪裡送進來都行**：⌃⌥⌘V 叫出面板、分享選單、右鍵「服務 → 用 Fully 抓」、`fully://grab?url=…`、書籤小工具。
- 中文／English 介面，深淺色。有新版時會通知一次，設定頁「關於 Fully」也會出現「下載新版」。

Fully 只處理網路上公開看得到的圖片與影片：不處理需要帳號才看得到的內容，不繞過付費牆或任何存取限制，不碰 DRM。

## 下載

[**下載 Fully.dmg**](https://github.com/intentionltd888/fully/releases/latest/download/Fully.dmg)（Apple Silicon 的 Mac，macOS 12 以上；已通過 Apple 公證）。打開 DMG，把 Fully 拖進「應用程式」，或直接雙擊它。

所有版本在 [Releases](https://github.com/intentionltd888/fully/releases)。使用前請看[使用規範](TERMS.md)；哪些東西會離開你的電腦，寫在 [PRIVACY.md](PRIVACY.md)。

## 自己建置需要什麼

- Apple Silicon 的 Mac，macOS 12 以上
- Xcode 命令列工具（`xcode-select --install`）
- [uv](https://github.com/astral-sh/uv)（凍結引擎用；第一次會下載 Python 3.12 與 PyInstaller）
- `vendor/`（maxurl 規則庫、QuickJS-ng、影片引擎 yt-dlp、FFmpeg）用 `scripts/vendor-fetch.sh` 準備，不進 git，每一個都核對 SHA-256；沒有現成的 qjs 時會從原始碼編，需要 `cmake`

## 建置

```bash
bash scripts/vendor-fetch.sh          # vendor/：maxurl 規則庫＋ qjs ＋ yt-dlp ＋ ffmpeg／ffprobe（都核對 SHA-256）
bash build.sh                         # 組 build/Fully.app（引擎凍成 Resources/bin/fully-engine）
bash scripts/make-dmg.sh              # build/Fully-<版本>.dmg（背景圖可用 FULLY_DMG_BG 指定）
bash scripts/notarize.sh              # Apple 公證＋釘票（要有 Developer ID 與 notarytool 憑據）
python3 engine/test_rules.py          # 縮圖→原圖規則的離線測試
bash scripts/check-clean.sh           # 公開前的原始碼掃描；成品用 bash scripts/check-binary.sh build/Fully.app
```

引擎也能單獨在終端機跑：

```bash
python3 engine/grab.py <網址> <資料夾>                  # 抓一個網頁的圖、一支影片或一個圖版
python3 engine/grab.py --json --probe <網址> <資料夾>   # 只看不抓：名稱、張數（影片：長度）、能拿到多大
python3 engine/grab.py --audio <影片網址> <資料夾>       # 影片只要聲音；--frames 每個鏡頭截圖、--data 標題與留言
```

截圖與設計檢查（不碰網路）：`build/Fully.app/Contents/MacOS/Fully --demo <狀態> --snapshot out.png`（狀態：image video run done doneone err batch pick recent follows settings sites terms privacy）、`--card-demo ask|run|done|err --snapshot out.png`、`--dock-demo out.png`、`--statusicon out.png`；加 `--lang en`、`--theme dark` 換語言與深淺色。

## 倉的長相

```
app/Sources/   Swift 殼：main（面板、佇列、剪貼簿、選單列、服務、fully://）、ClipCard（預覽卡）、
               SideIcons（Dock 與選單列）、Follow（追蹤）、Thumbs（縮圖）、Installer（DMG 雙擊即裝）、Prefs（語言、設定、叫引擎）、
               Engines（影片引擎每天自動更新）、AppUpdate（有沒有新版）
app/           ui.html（主面板）、ui-media.js（影片與圖版的畫面）、card.html（預覽卡）、Share/（分享選單擴充）、lproj/（服務選單名稱）、brand/（商標）
engine/        Python 引擎：grab.py（掃圖、原尺寸規則、預覽）、core.py（下載、去重、事件）、maxurl.py＋maxurl_runner.js、
               media.py（掛上影片、圖版與貼文）、video.py（影片：yt-dlp＋ffmpeg）、pin_grab.py（圖版）、
               threads_grab.py（貼文）、audio.py（音檔）
scripts/       vendor-fetch、make-dmg、notarize、check-clean／check-binary（公開前清洗）
```

## 權利人

如果你認為 Fully 被用來侵害你的權利，請在這個倉[開一個 Issue](https://github.com/intentionltd888/fully/issues)。

## 授權

程式碼 MIT（見 `LICENSE`）。Fully 的標記、字標、app 圖示與 `app/brand/` 裡的字標是商標，不在 MIT 範圍（見 `app/brand/TRADEMARK.md`）。
第三方元件見 `THIRD-PARTY-NOTICES.txt`（影片引擎 yt-dlp 與 FFmpeg 是 GPL 的獨立執行檔，app 以子程序呼叫）；使用規範見 `TERMS.md`；隱私與權限見 `PRIVACY.md`；改作與散布的界線見 `COMPLIANCE.md`。
