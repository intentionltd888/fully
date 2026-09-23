# Fully 隱私與權限

## 中文

Fully 沒有自己的伺服器、沒有帳號、沒有遙測。下面是它實際會做的事，一條一條列。

### 會離開你電腦的
1. **你貼的網址。** Fully 直接連那個網頁，以及存放它圖片的伺服器，把圖存回來。對方看得到你的 IP，跟你用瀏覽器打開那一頁一樣。有些對流量要求嚴格的網站，Fully 會照規矩報出自己的名字。Fully 不會登入任何網站，也不會讀你瀏覽器裡的任何資料。
2. **你複製的網址（預設開啟，可以關）。** Fully 開著的時候，會一直留意剪貼簿有沒有新的網址。複製到一個網址時，它會先讀一次那個網頁，在右上角跳出預覽卡（縮圖、名稱、有幾張、能拿到多大），這一步不下載任何檔案。
   - 這些網址不會自動去讀：內部網路、IP 位址、`.local`，以及網址裡有 token、auth、login、code=、session 這類字的（讀了可能把一次性登入連結用掉）。
   - 預覽卡和面板上的縮圖，直接從那個網站的圖片伺服器載入。
   - 設定裡可以改成「關」（完全不看剪貼簿）或「直接抓」。
3. **你選擇追蹤的網頁。** 在完成畫面按「追蹤」之後，Fully 開著時每 6 小時回去看一次那一頁，只存新的圖。停止方法：最近抓的 → 追蹤中 → 那一列的 ✕。「現在檢查」可以手動看一次。

除了以上三項，Fully 不連任何網路：沒有自動更新、沒有使用分析、沒有當機回報、沒有廣告，也不連我們的伺服器。新版會放在官網與公開倉，下載新的 DMG 蓋過去就好。

### 留在你電腦上的
- **存下的圖片**：預設在 `~/Downloads/Fully`，照來源自動開子資料夾；位置可以在設定裡改。每個檔案會記下它的來源網址（Finder 的「來源」欄）。
- **最近抓的、設定、還沒抓完的清單**：存在本機的 app 設定裡（最近抓的只留 30 筆）。
- **`~/Library/Application Support/Fully/`**：`hash-index.json` 用來記住抓過哪些圖，同一張不存兩次（設定可關）；`follows.json` 是你追蹤的網頁清單。

### 權限：macOS 會問你的，以及 Fully 會動到的

| 項目 | 什麼時候 | 為什麼 | 不給或關掉會怎樣 |
|---|---|---|---|
| 通知（macOS 會問） | 第一次抓完 | 告訴你好了，點一下就在 Finder 顯示 | 沒有通知，其他照常 |
| 剪貼簿（讀） | Fully 開著時一直留意有沒有新網址（預設「跳卡片」） | 複製網址就能預覽、少一步 | 設定改成「關」，自己貼上 |
| 剪貼簿（寫） | 單張抓完 | 把原圖放進剪貼簿，⌘V 就能貼到別的 app | 設定裡可以關 |
| 下載資料夾 | 第一次存檔（依 macOS 版本可能會問） | 把圖存進去 | 在設定裡改存到別的資料夾 |
| 下載中不讓電腦睡著 | 抓東西的時候 | 抓到一半不會斷；螢幕照樣可以關 | 抓完自動恢復 |
| 全域快速鍵 ⌃⌥⌘V | 一直都在 | 叫出 Fully | 不需要任何權限 |
| 分享選單、右鍵「用 Fully 抓」、`fully://` 連結 | 安裝後由系統列出 | 從別的 app 把網址送進來 | 不需要任何權限；不用就不會動 |
| Dock | 第一次安裝 | 把 Fully 加進 Dock（改的是 Dock 設定，只做一次） | 自己從 Dock 拿掉就好 |
| 安裝到「應用程式」 | 從 DMG 打開時 | 複製到 `/Applications`，會先問你 | 你自己拖過去 |

Fully 不會要求：完整磁碟取用、輔助使用、螢幕錄影、麥克風、相機、位置、鑰匙圈。

### 你該知道的
- **複製網址就會被看一眼。** 預設開著，是為了複製完就能預覽。不想要就到設定把剪貼簿改成「關」。
- **檔案帶著來源網址。** 把存下來的圖傳給別人時，對方在 Finder 看得到它來自哪個網址。
- **原檔原樣保存。** 圖裡原作者留下的中繼資料（例如拍攝資訊），Fully 不修改、也不上傳。

「不會上傳」是說明，不是文宣。

---

## English

Fully has no server, no account and no telemetry. Here is everything it actually does.

### What leaves your Mac
1. **The link you paste.** Fully connects straight to that page and the servers that host its images, and saves the images. The site sees your IP address, exactly as if you opened the page in a browser. Sites with strict traffic rules see Fully identify itself by name. Fully never signs in to any website and never reads anything from your browsers.
2. **Links you copy (on by default, can be turned off).** While Fully is running it watches the clipboard for new links. When you copy one, it reads that page once to show a preview card in the top-right corner (thumbnail, name, how many images, how large they are). No files are downloaded at this step.
   - These are never read automatically: local network addresses, IP addresses, `.local`, and links containing words like token, auth, login, code=, or session (reading them could use up a one-time sign-in link).
   - Thumbnails on the card and in the panel load directly from that site's image servers.
   - In Settings you can switch this to "Off" (the clipboard is not watched at all) or "Download right away".
3. **Pages you choose to follow.** After you press "Follow" on the done screen, Fully checks that page every 6 hours while it is running and saves only new images. To stop: Recent → Following → the ✕ on that row. "Check now" checks once by hand.

Apart from these three, Fully makes no network connections: no automatic updates, no analytics, no crash reports, no ads, and nothing sent to us. New versions are posted on the website and in the public repository; download the new DMG to update.

### What stays on your Mac
- **Saved images**: `~/Downloads/Fully` by default, sorted into subfolders by source; you can change the location in Settings. Each file records the address it came from (Finder's "Where from").
- **Recent items, settings and unfinished downloads**: kept in the app's local preferences (Recent keeps 30).
- **`~/Library/Application Support/Fully/`**: `hash-index.json` remembers which images you already have so the same one isn't saved twice (can be turned off); `follows.json` lists the pages you follow.

### Permissions: what macOS asks you, and what Fully touches

| Item | When | Why | If you say no or turn it off |
|---|---|---|---|
| Notifications (macOS asks) | After your first download | Tell you it's done; click to show the file in Finder | No notifications; everything else works |
| Clipboard (read) | Watched for new links while Fully runs (default: show a card) | Preview a link as soon as you copy it | Set it to "Off" and paste yourself |
| Clipboard (write) | After a single image is saved | Puts the original on the clipboard so ⌘V pastes it into other apps | Can be turned off in Settings |
| Downloads folder | First save (macOS may ask, depending on version) | Save images there | Choose another folder in Settings |
| Keep the Mac awake while downloading | During a download | A download won't break halfway; the display can still sleep | Returns to normal when done |
| Global shortcut ⌃⌥⌘V | Always | Summon Fully | Needs no permission |
| Share menu, "Grab with Fully" service, `fully://` links | Listed by macOS after install | Send links in from other apps | Needs no permission; nothing happens unless you use them |
| Dock | First install | Add Fully to the Dock (changes the Dock preference, once) | Remove it from the Dock |
| Install to Applications | When opened from the DMG | Copy to `/Applications`, after asking you | Drag it there yourself |

Fully never asks for Full Disk Access, Accessibility, Screen Recording, microphone, camera, location or Keychain access.

### Good to know
- **Copying a link means Fully takes a look.** It is on by default so you can preview right after copying. Turn the clipboard setting to "Off" if you don't want that.
- **Files carry their source address.** If you send a saved image to someone, they can see in Finder where it came from.
- **Originals are kept as they are.** Metadata left by the author (such as camera information) is not changed or uploaded.

"Nothing is uploaded" is a description, not a selling point.
