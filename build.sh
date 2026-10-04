#!/bin/bash
# Fully — build：編譯 → 組 .app → 介面與引擎 → icon → 簽名
# 產出 build/Fully.app。DMG：bash scripts/make-dmg.sh　公證：bash scripts/notarize.sh
# 全程不刪檔（覆蓋式重建）。第一次建置前先跑 bash scripts/vendor-fetch.sh（qjs、maxurl 規則庫、yt-dlp、ffmpeg）。
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Fully"
BUILD="${FULLY_BUILD_DIR:-build}"
APP="$BUILD/$APP_NAME.app"
MACOS="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"
VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" app/Info.plist)
BLD=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" app/Info.plist)
{ [ -x vendor/bin/qjs ] && [ -f vendor/maxurl/userscript_smaller.user.js ] && [ -x vendor/bin/yt-dlp ] \
  && [ -x vendor/bin/ffmpeg ] && [ -x vendor/bin/ffprobe ]; } \
  || { echo "✕ vendor/ 還沒準備好——先跑 bash scripts/vendor-fetch.sh"; exit 1; }
mkdir -p "$MACOS" "$RES" "$BUILD"

echo "── 1/5 編譯 Swift ──"
SWIFT_SRC=(app/Sources/*.swift)
SWIFT_FLAGS=()
swiftc -O "${SWIFT_SRC[@]}" ${SWIFT_FLAGS[@]+"${SWIFT_FLAGS[@]}"} -o "$MACOS/$APP_NAME" \
  -framework AppKit -framework WebKit -framework Carbon -framework QuickLookThumbnailing \
  -target arm64-apple-macos12.0

cp app/Info.plist "$APP/Contents/Info.plist"

# 分享選單擴充（Safari／Chrome／Finder 的「分享 → Fully」）：沙盒裡的小程式，只把網址轉成 fully://grab 交給主程式
SHARE="$APP/Contents/PlugIns/FullyShare.appex"
mkdir -p "$SHARE/Contents/MacOS"
swiftc -O -application-extension -parse-as-library -module-name FullyShare app/Share/ShareViewController.swift \
  -o "$SHARE/Contents/MacOS/FullyShare" -Xlinker -e -Xlinker _NSExtensionMain -framework AppKit \
  -target arm64-apple-macos12.0
cp app/Share/Info.plist "$SHARE/Contents/Info.plist"
# 擴充的版本跟著 app 走（app/Info.plist 是唯一版本正本；兩邊不一致時 pluginkit 會顯示舊號）
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" -c "Set :CFBundleVersion $BLD" "$SHARE/Contents/Info.plist"

echo "── 2/5 介面與引擎 ──"
cp app/ui.html app/card.html app/ui-media.js "$RES/"
cp engine/grab.py engine/core.py engine/maxurl.py engine/media.py engine/video.py engine/pin_grab.py "$RES/"
# maxurl（Apache-2.0）：縮圖→原圖規則庫，包內 qjs 離線跑。資料檔，不放 bin/（那裡每支都要 codesign）
mkdir -p "$RES/maxurl"
cp engine/maxurl_runner.js vendor/maxurl/userscript_smaller.user.js vendor/maxurl/LICENSE-maxurl.txt "$RES/maxurl/"
# 使用規範、隱私與權限：app 內「關於」與精靈第一頁讀這兩份
mkdir -p "$RES/docs"
cp TERMS.md "$RES/docs/terms.md"
cp PRIVACY.md "$RES/docs/privacy.md"
# 右鍵「服務」選單的名稱（中英）
for lp in app/lproj/*.lproj; do [ -d "$lp" ] && mkdir -p "$RES/$(basename "$lp")" && cp "$lp"/* "$RES/$(basename "$lp")/"; done
mkdir -p "$RES/brand"
cp app/brand/intention_wordmark.png "$RES/brand/"        # 頁尾「Powered by」的字標（商標，見 app/brand/TRADEMARK.md）
chmod 644 "$RES/ui.html" "$RES/card.html" "$RES/"*.py "$RES/maxurl/"* "$RES/docs/"*

mkdir -p "$RES/bin"
# 影片引擎：yt-dlp（出廠版；真正跑的是 Application Support 那份會自更新的副本，見 Engines.swift）
# ＋ffmpeg／ffprobe（合併影音、轉成 QuickTime 能播的格式、截圖；只在本機處理檔案）
cp vendor/bin/yt-dlp vendor/bin/ffmpeg vendor/bin/ffprobe "$RES/bin/"
cp vendor/bin/qjs "$RES/bin/"                            # JavaScript 執行環境：maxurl 規則庫、yt-dlp 解網站的挑戰
cp THIRD-PARTY-NOTICES.txt "$RES/"

# 引擎凍成獨立執行檔（不吃系統 Python）；改了引擎的 .py 重跑 build 就會重凍
bash engine/freeze.sh
cp "$BUILD/engine/fully-engine" "$RES/bin/"
chmod 755 "$RES/bin/"*

# 版本表（精靈與設定頁顯示用；比逐支跑 --version 快）
{
  echo "yt-dlp=$(vendor/bin/yt-dlp --version 2>/dev/null | tail -1)"
  echo "ffmpeg=$(vendor/bin/ffmpeg -version 2>/dev/null | head -1 | sed -E 's/^ffmpeg version ([0-9.]+).*/\1/')"
  echo "qjs=$(vendor/bin/qjs -h 2>&1 | head -1 | sed -E 's/.*version //')"
  echo "app=$VER ($BLD)"
} > "$RES/engine-versions.txt"
echo "   $(tr '\n' ' ' < "$RES/engine-versions.txt")"

echo "── 3/5 App icon ──"
# 每次重畫（AppKit 向量，1 秒）。只在缺檔時畫的話，改了 make-icon.swift 之後 Dock 還是舊圖
swift app/make-icon.swift "$BUILD/icon_1024.png"
ICONSET="$BUILD/AppIcon.iconset"
mkdir -p "$ICONSET"
for sz in 16 32 128 256 512; do
  sips -z $sz $sz "$BUILD/icon_1024.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
  dbl=$((sz * 2))
  sips -z $dbl $dbl "$BUILD/icon_1024.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"

# 防呆：覆蓋式重建會留上一輪的雜物（多一支執行檔，整個 DMG 就會被公證退件）——移進 build/stray/，不刪
STRAY=$(ls "$MACOS" | grep -v "^$APP_NAME$" || true)
if [ -n "$STRAY" ]; then
  mkdir -p "$BUILD/stray"
  for f in $STRAY; do
    echo "   ⚠ MacOS/ 有非預期檔案：$f → 移入 $BUILD/stray/"
    mv "$MACOS/$f" "$BUILD/stray/$f-$(date +%Y%m%d-%H%M%S)"
  done
fi
OK_RES="ui\.html|card\.html|ui-media\.js|grab\.py|core\.py|maxurl\.py|media\.py|video\.py|pin_grab\.py|maxurl|docs|[A-Za-z-]+\.lproj|AppIcon\.icns|brand|bin|THIRD-PARTY-NOTICES\.txt|engine-versions\.txt"
STRAY_RES=$(ls "$RES" | grep -vE "^($OK_RES)$" || true)
[ -n "$STRAY_RES" ] && echo "   ⚠ Resources/ 有非預期檔案：$STRAY_RES"

echo "── 4/5 簽名 ──"
SIGN_ID=$(security find-identity -v -p codesigning 2>/dev/null \
          | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)"/\1/')
if [ -n "$SIGN_ID" ]; then
  echo "   Developer ID：$SIGN_ID"
  for b in "$RES/bin/"*; do
    codesign --force --options runtime --timestamp \
             --entitlements app/bin.entitlements -s "$SIGN_ID" "$b"
  done
  # 巢狀的擴充要先簽（App Extension 規定沙盒），外層 app 最後簽
  codesign --force --options runtime --timestamp \
           --entitlements app/Share/Share.entitlements -s "$SIGN_ID" "$SHARE"
  codesign --force --options runtime --timestamp \
           --entitlements app/Fully.entitlements \
           -s "$SIGN_ID" "$APP"
else
  echo "   找不到 Developer ID，退回 ad-hoc（只能自己這台用，不能給別人）"
  codesign --force --sign - --entitlements app/Share/Share.entitlements "$SHARE"
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --strict "$APP" && echo "   簽名驗證通過"

echo "── 5/5 完成 ──"
echo "完成 — $APP_NAME $VER ($BLD)"
echo "  app：$PWD/$APP"
echo "  DMG：bash scripts/make-dmg.sh    公證：bash scripts/notarize.sh"
