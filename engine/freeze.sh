#!/bin/bash
# freeze.sh — 把 grab.py（連同 core.py、maxurl.py，以及影片線 video.py、圖版解析 pin_grab.py）凍成單一獨立執行檔 fully-engine
#
# 為什麼：/usr/bin/python3 在沒裝 Xcode 命令列工具的 Mac 上只是個「要不要安裝開發者工具？」的空殼，
# 引擎一啟動就死。所以引擎凍成 PyInstaller 單檔＋Developer ID 簽章（app/bin.entitlements）＋公證，
# app 從此不碰系統 Python。
#
# 工具鏈：uv 管理的 python-build-standalone 3.12（arm64、最低 macOS 11、設計上可散布）
#   ＋ PyInstaller（uv --with 臨時環境，第一次會下載，之後走快取）。
#   不用 Homebrew 的 python —— bottle 只保證能在「建置那台的 macOS 版本」跑，
#   對方 macOS 較舊會被 dyld 擋（built for macOS X which is newer than running OS）。
#   不用 /usr/bin/python3 —— 那正是我們要擺脫的東西。
#
# 用法：bash engine/freeze.sh        → build/engine/fully-engine（build.sh 會自己呼叫）
# 改了引擎的 .py 就要重跑（約 20–40 秒），不用重編 Swift。
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "✕ 找不到 uv（brew install uv）"; exit 1; }

OUT="${FULLY_BUILD_DIR:-build}/engine"     # 跟著 build.sh 的 FULLY_BUILD_DIR 走
mkdir -p "$OUT"

BIN="$OUT/fully-engine"
# 上一輪的成品先挪開，凍結失敗時才不會悄悄把舊的包進去（不刪檔，留 .prev 可回頭比對）
[ -e "$BIN" ] && mv -f "$BIN" "$BIN.prev"

echo "   PyInstaller 凍結中（python-build-standalone 3.12 arm64）…"
EXCL=()
if ! uv run --python 3.12 --with pyinstaller pyinstaller \
      --onefile --name fully-engine --noconfirm \
      --paths engine ${EXCL[@]+"${EXCL[@]}"} \
      --distpath "$OUT" --workpath "$OUT/work" --specpath "$OUT" \
      --log-level WARN \
      engine/grab.py > "$OUT/freeze.log" 2>&1; then
  echo "✕ PyInstaller 失敗，最後 20 行："; tail -20 "$OUT/freeze.log" | sed 's/^/   /'; exit 1
fi
grep -iE "warning|error" "$OUT/freeze.log" | grep -v "WARNING: Failed to collect submodules for 'pkg_resources" | sed 's/^/   /' || true

[ -x "$BIN" ] || { echo "✕ 凍結失敗：沒有產出 $BIN"; exit 1; }

# 自我檢查：架構、最低 macOS、能不能不靠任何系統 Python 起來（PATH 只給 /usr/bin:/bin）
ARCH=$(file -b "$BIN" | sed -E 's/.*executable (arm64|x86_64).*/\1/')
MINOS=$(otool -l "$BIN" | grep -A3 LC_BUILD_VERSION | awk '/minos/{print $2; exit}')
OUTPUT=$(env -i PATH=/usr/bin:/bin HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" "$BIN" --json 2>&1 || true)
echo "$OUTPUT" | grep -q '"type": *"error"' \
  || { echo "✕ 凍結版起不來或沒吐 JSON 事件：$OUTPUT"; exit 1; }
SIZE=$(du -h "$BIN" | cut -f1)
echo "   fully-engine ✓  $ARCH · 最低 macOS $MINOS · $SIZE"

