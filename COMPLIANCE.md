# Fully 合規清單

改作、fork 與再散布 Fully 時也適用。這份清單不是法律意見。[English](#english)

## 1. 範圍

- Fully 只存網路上公開看得到的內容：任何網頁上的圖、公開的影片、整個公開的圖版。
- 不處理需要帳號才看得到的內容；不繞過付費牆，也不繞過任何存取限制；不碰 DRM（受保護的影片存不下來）。
- app 介面與文件用一般說法（「網路上的圖片與影片」「任何網頁」），不列網站名稱；只有程式碼為了認得網址會寫到網域。

## 2. 文字紅線（README、網站、app 介面、社群、Release notes 都適用）

- 不出現「破解」「crack」「繞過」「bypass」「內部 API」「無限下載」「free download」這類字眼。
- 定位一律寫「設計參考收集：把你有權使用的圖片與影片存下來」／「design reference collector」。
- 任何網站名稱都不寫，FAQ 與 app 介面也一樣；只說「網路上的圖片與影片」「任何網頁」。
- 第三方商標只用純文字，不放它們的標誌。

## 3. 開源元件的授權（再散布時要跟著做）

- app 裡帶著兩個 GPL 的獨立執行檔：影片引擎 yt-dlp（官方打包的執行檔整體為 GPLv3+）與 FFmpeg（這個組建為 GPL v3）。Fully 以子程序呼叫它們，Fully 自己的程式碼照舊是 MIT。
- 再散布含有這兩支執行檔的 app 或 DMG 時：一起附上 `THIRD-PARTY-NOTICES.txt`（裡面有授權與對應原始碼的位置），並確保那些原始碼在你散布期間都拿得到。
- 換掉它們（例如改用 LGPL 組建的 FFmpeg）時，同步更新 `scripts/vendor-fetch.sh` 的釘版與 `THIRD-PARTY-NOTICES.txt`。

## 4. 錢與測試

- 零金流：這個倉與它的官網頁不放斗內、廣告、付費解鎖（GitHub Sponsors 只能掛在帳號層）。
- 測試網址只用自己的內容，或平台自己的公開範例頁。

## English

This checklist also applies to forks, modifications and redistribution. It is not legal advice.

### 1. Scope

- Fully only saves what is publicly visible on the web: images on any web page, public videos, and whole public boards.
- It does not handle content that requires an account, does not get around paywalls or any other access control, and does not touch DRM (protected videos can't be saved).
- The app interface and documentation use general wording ("images and videos on the web", "any web page") and do not list website names; only the code names domains, to recognize links.

### 2. Wording (applies to the README, website, app interface, social posts and release notes)

- Never use words like "crack", "bypass", "internal API", "unlimited downloads" or "free download".
- Describe Fully as a "design reference collector: save the images and videos you have the right to use".
- Never name specific websites, including in FAQs and the app interface; say "images and videos on the web" or "any web page".
- Refer to third-party trademarks in plain text only; do not show their logos.

### 3. Open-source licenses (follow these when you redistribute)

- The app ships two GPL programs as separate executables: the video engine yt-dlp (the official bundled executable is GPLv3+ as a whole) and FFmpeg (this build is GPL v3). Fully runs them as subprocesses; Fully's own code stays MIT.
- When you redistribute an app or DMG that contains them, include `THIRD-PARTY-NOTICES.txt` (licenses and where to get the corresponding source) and make sure that source stays available for as long as you distribute.
- If you swap them out (for example an LGPL build of FFmpeg), update the pins in `scripts/vendor-fetch.sh` and `THIRD-PARTY-NOTICES.txt` together.

### 4. Money and testing

- No money flows: no donations, ads or paid unlocks in this repository or its web page (GitHub Sponsors only at the account level).
- Test only with your own content or a platform's own public sample pages.
