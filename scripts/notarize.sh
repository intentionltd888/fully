#!/bin/bash
# notarize.sh — Apple 公證＋釘票：make-dmg.sh 產出 DMG 後跑，跑完才能傳給別人
# 前提：① app 是 Developer ID 簽名（build.sh 自動偵測）
#      ② notarytool 憑據已存鑰匙圈：xcrun notarytool store-credentials <profile> --apple-id … --team-id … --password <app 專用密碼>
# profile 名怎麼找（依序）：FULLY_NOTARY_PROFILE 環境變數 → 倉根 .notary-profile 檔（不進 git，一台機器寫一次）→ 預設 fully-notary
# 用法：bash scripts/notarize.sh    Apple 端通常 2–15 分鐘，--wait 會等完
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD="${FULLY_BUILD_DIR:-build}"

APP="$BUILD/Fully.app"
PROFILE="${FULLY_NOTARY_PROFILE:-}"
[ -z "$PROFILE" ] && [ -f .notary-profile ] && PROFILE=$(tr -d '[:space:]' < .notary-profile)
PROFILE="${PROFILE:-fully-notary}"
VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
BLD=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$APP/Contents/Info.plist")
DMG="$BUILD/Fully-$VER.dmg"
[ -f "$DMG" ] || { echo "找不到 $DMG——先跑 bash scripts/make-dmg.sh"; exit 1; }

# 不可用「codesign | grep -q」：pipefail 下 grep -q 提早關管會讓 codesign 吃 SIGPIPE 誤判失敗
SIGN_INFO=$(codesign -dvv "$APP" 2>&1)
echo "$SIGN_INFO" | grep -q "Developer ID Application" \
  || { echo "app 不是 Developer ID 簽名——ad-hoc 的包公證必被退件"; exit 1; }

# 出貨閘：DMG 裡的 app 必須就是現在這顆（cdhash 逐位核對；防公證到舊包）
echo "── 出貨閘：DMG 內容＝當下 app ──"
APP_CD=$(codesign -dvvv "$APP" 2>&1 | awk -F= '/^CDHash=/ && !p {print $2; p=1}')
MNT=$(mktemp -d)
hdiutil attach -readonly -nobrowse -mountpoint "$MNT" "$DMG" >/dev/null
DMG_CD=$(codesign -dvvv "$MNT/Fully.app" 2>&1 | awk -F= '/^CDHash=/ && !p {print $2; p=1}')
hdiutil detach "$MNT" >/dev/null
if [ -z "$APP_CD" ] || [ "$APP_CD" != "$DMG_CD" ]; then
  echo "✗ 擋下：DMG 內的 app（${DMG_CD:-?}）≠ 現在的 $APP（${APP_CD:-?}）——重跑 make-dmg.sh"
  exit 1
fi
echo "   ✓ 同一顆（cdhash $APP_CD）"

echo "── 提交公證（profile：$PROFILE）──"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait

echo "── 釘票 ──"
xcrun stapler staple "$DMG"
xcrun stapler staple "$APP" || echo "⚠ 散裝 app 釘票失敗（DMG 已釘票、出貨不受影響）"

echo "── 驗收 ──"
xcrun stapler validate "$DMG"
spctl -a -vv "$APP" && echo "✓ spctl 通過"

echo "完成 — $DMG（已公證、已釘票，可以直接傳給別人）"
