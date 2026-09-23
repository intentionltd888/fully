#!/bin/bash
# make-dmg.sh — 用 build/Fully.app 打安裝 DMG（拖進 Applications 那種；雙擊 app 也會自己裝）
# 用法：bash scripts/make-dmg.sh [背景圖.png] → build/Fully-<版本>.dmg
#   背景圖選填（也可用 FULLY_DMG_BG）：1440×1040（@2x，視窗 720×520，圖示 y=300）；沒給就素底。
#   bounds 是含標題列的外框：高＝內容 520＋標題列 32（macOS 26）；路徑列要關，不然再吃 28pt、頁尾被切。
#   Finder 排版走 AppleScript（第一次系統會問「自動化 Finder」）；被拒就退成素排版，DMG 一樣能用。
# 全程不刪檔：工作區在 /tmp（mktemp），成品 cp 回 build/。
#   DiskImages daemon 讀 ~/Desktop 底下的 -srcfolder 會被 TCC 擋，所以 stage 一律放 /tmp。
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD="${FULLY_BUILD_DIR:-build}"

APP_NAME="Fully"
APP="$BUILD/$APP_NAME.app"
[ -d "$APP" ] || { echo "找不到 $APP——先跑 bash build.sh"; exit 1; }
codesign --verify --deep --strict "$APP" || { echo "簽名驗證失敗——重跑 build.sh"; exit 1; }

VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
BLD=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$APP/Contents/Info.plist")
DMG_NAME="$APP_NAME-$VER.dmg"
BG="${1:-${FULLY_DMG_BG:-}}"

WORK=$(mktemp -d /tmp/fully-dmg.XXXXXX)
STAGE="$WORK/stage"
mkdir -p "$STAGE"
touch "$APP" "$APP/Contents"
ditto "$APP" "$STAGE/$APP_NAME.app"
ln -sfn /Applications "$STAGE/Applications"
if [ -n "$BG" ] && [ -f "$BG" ]; then
  mkdir -p "$STAGE/.background"
  cp "$BG" "$STAGE/.background/bg.png"
  # @2x 背景圖若 DPI 還是 72，Finder 會照像素數當點數畫；寬 ≥1200 就當 @2x，DPI 標 144
  PW=$(sips -g pixelWidth "$STAGE/.background/bg.png" | awk '/pixelWidth/ {print $2}')
  if [ "${PW:-0}" -ge 1200 ]; then
    sips -s dpiWidth 144 -s dpiHeight 144 "$STAGE/.background/bg.png" >/dev/null
  fi
fi

echo "── 1/3 讀寫 DMG ──"
# 同名舊映像還掛著時新的會掛成「Fully 1」，AppleScript 會排到舊的；先把同名掛載退掉
for v in "/Volumes/$APP_NAME" "/Volumes/$APP_NAME "[0-9]*; do
  [ -d "$v" ] || continue
  echo "   退出殘留掛載：$v"
  hdiutil detach "$v" -force >/dev/null 2>&1 || true
done
RW="$WORK/rw.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDRW -fs HFS+ "$RW" >/dev/null
MNT=$(hdiutil attach -readwrite -noverify -noautoopen "$RW" | awk -F'\t' '/\/Volumes\// {print $NF}')
[ -n "$MNT" ] || { echo "掛載失敗"; exit 1; }

echo "── 2/3 Finder 排版 ──"
if [ -f "$STAGE/.background/bg.png" ]; then
  # perl alarm：第一次跑系統會跳「自動化 Finder」授權窗，沒人按會卡住整條 release；120 秒沒回就放棄排版
  perl -e 'alarm 120; exec @ARGV' osascript >/dev/null <<EOA || echo "   ⚠ Finder 排版被拒、逾時或失敗，改素排版（DMG 照樣能用）"
tell application "Finder"
  tell disk "$APP_NAME"
    open
    delay 1
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    try
      set pathbar visible of container window to false
    end try
    set the bounds of container window to {200, 120, 920, 672}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 112
    set text size of opts to 12
    set background picture of opts to POSIX file "$MNT/.background/bg.png"
    set position of item "$APP_NAME.app" of container window to {230, 300}
    set position of item "Applications" of container window to {490, 300}
    close
    open
    update without registering applications
    delay 1
    close
  end tell
end tell
EOA
else
  echo "   （沒有背景圖，素排版）"
fi
sync
if [ -f "$STAGE/.background/bg.png" ] && [ ! -f "$MNT/.DS_Store" ]; then
  echo "   ⚠ Finder 沒把排版寫進 .DS_Store（背景與圖示位置不會有）——多半是 Finder 自動化被拒；先出素排版"
fi
hdiutil detach "$MNT" >/dev/null

echo "── 3/3 壓成唯讀 DMG ──"
OUT="$WORK/$DMG_NAME"
hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -ov -o "$OUT" >/dev/null
SIGN_ID=$(security find-identity -v -p codesigning 2>/dev/null | awk -F'"' '/Developer ID Application/ {print $2; exit}')
if [ -n "$SIGN_ID" ]; then
  codesign --force --timestamp -s "$SIGN_ID" "$OUT" >/dev/null 2>&1 && echo "   DMG 已簽：$SIGN_ID"
fi
cp -f "$OUT" "$BUILD/$DMG_NAME"
echo "✅ $BUILD/$DMG_NAME（$APP_NAME $VER build $BLD，$(du -h "$BUILD/$DMG_NAME" | cut -f1)）"
