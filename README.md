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

## 權利人

如果你認為 Fully 被用來侵害你的權利，請在這個倉[開一個 Issue](https://github.com/intentionltd888/fully/issues)。

## 授權

這個倉只放發佈版的安裝檔與說明，原始碼不公開。已發佈的版本照 `LICENSE` 授權。Fully 的標記、字標與 app 圖示是商標，不在 LICENSE 範圍（見 `TRADEMARK.md`）。
第三方元件見 `THIRD-PARTY-NOTICES.txt`（影片引擎 yt-dlp 與 FFmpeg 是 GPL 的獨立執行檔，app 以子程序呼叫）；使用規範見 `TERMS.md`；隱私與權限見 `PRIVACY.md`。
