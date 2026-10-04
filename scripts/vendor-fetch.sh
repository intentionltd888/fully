#!/bin/bash
# vendor-fetch.sh — 準備 vendor/（第三方的東西不進 git，建置前用這支備好）
#
#   vendor/maxurl/userscript_smaller.user.js   maxurl 規則庫（Apache-2.0），釘在 tag 的 commit，逐位元組核對 SHA-256
#   vendor/maxurl/LICENSE-maxurl.txt           它的授權全文（Apache-2.0 §4(a)：散布時隨附）
#   vendor/bin/qjs                             QuickJS-ng（MIT），跑 maxurl、也給 yt-dlp 解網站的 JavaScript 挑戰；
#                                              從釘住的 commit 自己編（arm64、最低 macOS 11）——官方預編譯版的最低系統版本太新
#   vendor/bin/yt-dlp                          影片引擎，官方 yt-dlp_macos 單檔（釘版本，核對官方 SHA2-256SUMS 裡的那一行）
#   vendor/bin/ffmpeg、vendor/bin/ffprobe      FFmpeg 靜態組建（GPL v3，martin-riedl.de 的 macOS arm64 釘版，核對 zip 與執行檔的 SHA-256）
# 用法：bash scripts/vendor-fetch.sh
#       FULLY_VENDOR_FROM=<資料夾> bash scripts/vendor-fetch.sh   本機已有現成的（<資料夾>/maxurl/…、<資料夾>/bin/…）就複製，照樣核對
# 已經備好而且核對得過的，不會重抓。編 qjs 需要 Xcode 命令列工具、git 與 cmake（brew install cmake）。
set -euo pipefail
cd "$(dirname "$0")/.."

MAXURL_COMMIT="89cef6985a65448251954338ea0f84c8d53585b1"      # qsniyg/maxurl tag v2026.6.0
MAXURL_SHA="660a0877131c4d06444d9324565d0acc444452eae5f2fabc1f87e780244b58c3"
MAXURL_LICENSE_SHA="0cf1d5527289cc92e6b07e535f5a8c6d2aa9ee5754fc1bffce9d70e9ce5449c3"
QJS_TAG="v0.16.1"
QJS_COMMIT="954dc53628e36891f93c359aa60895c2ae3dac6b"         # quickjs-ng/quickjs tag v0.16.1
QJS_VERSION="0.16.1"
YTDLP_VER="2026.08.19"                                          # yt-dlp 官方發行版（app 裝好後會自己每天更新）
YTDLP_SHA="0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202"   # yt-dlp_macos（官方 SHA2-256SUMS）
FFMPEG_BUILD="1785863997_9.0"                                    # https://ffmpeg.martin-riedl.de 的 macOS arm64 組建 9.0
FFMPEG_ZIP_SHA="5267ef149ee0d208057a1b316aac079b661b0476574dee5da7d225769773c603"
FFMPEG_SHA="f54ec33409c78f54564c80afa16213b0970065100a87f4129516be0c8660c493"
FFPROBE_ZIP_SHA="7778fbb533fb60d3336cbd9a9e51eced71658f020b570c7203590c1c41d42f50"
FFPROBE_SHA="f7142685d6e692ac22fde47facf8c078ce5333512e3ccfa4b83225d0561ad428"

FROM="${FULLY_VENDOR_FROM:-}"
mkdir -p vendor/maxurl vendor/bin

sha() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

fetch_checked() { # 目的地, 期望 SHA-256, 本機來源（可空）, 網址
  local dst="$1" want="$2" local_src="$3" url="$4"
  if [ -f "$dst" ] && [ "$(sha "$dst")" = "$want" ]; then echo "   ✓ $dst（已經有了）"; return 0; fi
  local tmp; tmp=$(mktemp)
  if [ -n "$local_src" ] && [ -f "$local_src" ]; then
    cp "$local_src" "$tmp"
  else
    curl -fsSL "$url" -o "$tmp"
  fi
  if [ "$(sha "$tmp")" != "$want" ]; then
    echo "✕ $dst 的 SHA-256 對不上（來源：${local_src:-$url}）"; mv "$tmp" "$dst.rejected"; exit 1
  fi
  mv "$tmp" "$dst"
  chmod 644 "$dst"
  echo "   ✓ $dst"
}

echo "── maxurl 規則庫 ──"
RAW="https://raw.githubusercontent.com/qsniyg/maxurl/$MAXURL_COMMIT"
fetch_checked vendor/maxurl/userscript_smaller.user.js "$MAXURL_SHA" "${FROM:+$FROM/maxurl/userscript_smaller.user.js}" "$RAW/userscript_smaller.user.js"
fetch_checked vendor/maxurl/LICENSE-maxurl.txt "$MAXURL_LICENSE_SHA" "${FROM:+$FROM/maxurl/LICENSE-maxurl.txt}" "$RAW/LICENSE"

echo "── QuickJS-ng（qjs）──"
qjs_ok() { # 能跑、版本對、arm64、最低 macOS ≤ 12
  local q="$1"
  [ -x "$q" ] || return 1
  "$q" -h 2>&1 | head -1 | grep -q "version $QJS_VERSION" || return 1
  file -b "$q" | grep -q "arm64" || return 1
  local minos; minos=$(otool -l "$q" | grep -A3 LC_BUILD_VERSION | awk '/minos/{print $2; exit}')
  [ -n "$minos" ] && [ "${minos%%.*}" -le 12 ]
}
if qjs_ok vendor/bin/qjs; then
  echo "   ✓ vendor/bin/qjs（已經有了）"
elif [ -n "$FROM" ] && qjs_ok "$FROM/bin/qjs"; then
  cp "$FROM/bin/qjs" vendor/bin/qjs && echo "   ✓ vendor/bin/qjs（從 $FROM 複製）"
else
  command -v cmake >/dev/null || { echo "✕ 找不到 cmake（brew install cmake）"; exit 1; }
  SRC=$(mktemp -d /tmp/fully-qjs.XXXXXX)
  git clone --quiet --depth 1 --branch "$QJS_TAG" https://github.com/quickjs-ng/quickjs "$SRC/quickjs"
  [ "$(git -C "$SRC/quickjs" rev-parse HEAD)" = "$QJS_COMMIT" ] || { echo "✕ $QJS_TAG 的 commit 對不上"; exit 1; }
  # -ffile-prefix-map：斷言訊息裡的 __FILE__ 會把編譯時的絕對路徑寫進二進位；對映成相對路徑，成品不帶建置機的目錄
  cmake -S "$SRC/quickjs" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0 -DCMAKE_OSX_ARCHITECTURES=arm64 -DBUILD_QJS_LIBC=ON \
        -DCMAKE_C_FLAGS="-ffile-prefix-map=$SRC/quickjs=." >/dev/null
  cmake --build "$SRC/build" --target qjs_exe -j >/dev/null
  cp "$SRC/build/qjs" vendor/bin/qjs
  qjs_ok vendor/bin/qjs || { echo "✕ 編出來的 qjs 沒通過檢查"; exit 1; }
  echo "   ✓ vendor/bin/qjs（從 $QJS_TAG 原始碼編）"
fi

echo "── 影片引擎（yt-dlp）──"
fetch_checked vendor/bin/yt-dlp "$YTDLP_SHA" "${FROM:+$FROM/bin/yt-dlp}" \
  "https://github.com/yt-dlp/yt-dlp/releases/download/$YTDLP_VER/yt-dlp_macos"
chmod 755 vendor/bin/yt-dlp

echo "── FFmpeg（ffmpeg／ffprobe）──"
fetch_zipped() { # 執行檔名, 期望 zip SHA-256, 期望執行檔 SHA-256
  local name="$1" zip_want="$2" want="$3" dst="vendor/bin/$1"
  if [ -f "$dst" ] && [ "$(sha "$dst")" = "$want" ]; then echo "   ✓ $dst（已經有了）"; chmod 755 "$dst"; return 0; fi
  if [ -n "$FROM" ] && [ -f "$FROM/bin/$name" ] && [ "$(sha "$FROM/bin/$name")" = "$want" ]; then
    cp "$FROM/bin/$name" "$dst" && chmod 755 "$dst" && echo "   ✓ $dst（從 $FROM 複製）"; return 0
  fi
  local tmp; tmp=$(mktemp -d)
  curl -fsSL "https://ffmpeg.martin-riedl.de/download/macos/arm64/$FFMPEG_BUILD/$name.zip" -o "$tmp/$name.zip"
  [ "$(sha "$tmp/$name.zip")" = "$zip_want" ] || { echo "✕ $name.zip 的 SHA-256 對不上"; exit 1; }
  unzip -q -o "$tmp/$name.zip" -d "$tmp/x"
  [ "$(sha "$tmp/x/$name")" = "$want" ] || { echo "✕ $name 的 SHA-256 對不上"; exit 1; }
  mv "$tmp/x/$name" "$dst" && chmod 755 "$dst"
  echo "   ✓ $dst（FFmpeg $FFMPEG_BUILD）"
}
fetch_zipped ffmpeg "$FFMPEG_ZIP_SHA" "$FFMPEG_SHA"
fetch_zipped ffprobe "$FFPROBE_ZIP_SHA" "$FFPROBE_SHA"
echo "完成 — vendor/ 準備好了"
