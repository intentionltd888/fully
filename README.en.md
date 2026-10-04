# Fully

[![Download Fully for macOS](https://img.shields.io/badge/Download-macOS-000000?style=for-the-badge&logo=apple&logoColor=white&labelColor=000000)](https://github.com/intentionltd888/fully/releases/latest/download/Fully.dmg)
[![Latest release](https://img.shields.io/github/v/release/intentionltd888/fully?style=for-the-badge&label=release&labelColor=000000&color=555555)](https://github.com/intentionltd888/fully/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/intentionltd888/fully/total?style=for-the-badge&label=downloads&labelColor=000000&color=555555)](https://github.com/intentionltd888/fully/releases)

Save the images and videos you have the right to use — at their original size and best quality. [中文](README.md)

Fully is a design reference collector for macOS. Copy the link of a web page and Fully finds the publicly visible images on it, swaps each one for its original-size file and saves it — not the thumbnail you see on the page. Paste a video link and you get the best quality, ready to play; paste a board link and Fully reads the whole board.

## What it does

- **A preview card when you copy a link**: copy a link in any app and a card slides in at the top right — thumbnail, name, how many images, the largest size you'll get, and whether you've saved it before. Nothing happens until you click "Grab"; ignore it and it leaves on its own. The card never takes the keyboard, so you can keep typing.
- **Original size**: thumbnail URLs are swapped for the originals (rules for site builders and image CDNs, plus the maxurl rule set). The done screen tells you the size you actually got and how many times larger it is than the one on the page.
- **Video**: thousands of video sites — anything publicly visible. Best quality, plays in QuickTime right away; or just the audio, a frame from each shot, or titles & comments. A link with a timestamp (t=83) also saves that frame. The video engine keeps up with site changes in the background, once a day (you can turn this off).
- **Boards**: reads a whole board to the end, nothing skipped; video pins are saved as videos and every page of a multi-page pin is saved.
- **Fast and quiet**: parallel downloads that stay polite with rate-limited sites; your Mac doesn't sleep mid-download; the Dock icon shows a progress bar and how many are queued, the menu bar shows a progress ring; quit and reopen and it picks up where it left off.
- **Ready to use**: a single image goes straight to the clipboard (⌘V into your design tool); thumbnails can be dragged out; every file's "Where from" field keeps the source link (findable in Spotlight).
- **Afterwards**: follow a page, board or playlist and Fully checks it every 6 hours, grabbing only what's new; identical images are never saved twice; the last 30 grabs are kept.
- **Send links from anywhere**: ⌃⌥⌘V for the panel, the Share menu, right-click → Services → "Grab with Fully", `fully://grab?url=…`, or the bookmarklet.
- Chinese / English interface, light and dark.

Fully only handles images and videos that are publicly visible on the web: nothing behind an account, no getting around paywalls or any other access control, no DRM.

## Download

[**Download Fully.dmg**](https://github.com/intentionltd888/fully/releases/latest/download/Fully.dmg) (Apple silicon Mac, macOS 12 or later; notarized by Apple). Open the DMG and drag Fully into Applications — or just double-click it.

Every version is under [Releases](https://github.com/intentionltd888/fully/releases). Please read the [terms of use](TERMS.md) first; what leaves your Mac is listed in [PRIVACY.md](PRIVACY.md).

## Building it yourself

You need:

- An Apple silicon Mac on macOS 12 or later
- Xcode command line tools (`xcode-select --install`)
- [uv](https://github.com/astral-sh/uv) (freezes the engine; the first run downloads Python 3.12 and PyInstaller)
- `vendor/` (the maxurl rule set, QuickJS-ng, the yt-dlp video engine and FFmpeg), prepared by `scripts/vendor-fetch.sh` and kept out of git, each one SHA-256 checked; if there's no ready qjs it's built from source, which needs `cmake`

```bash
bash scripts/vendor-fetch.sh          # vendor/: maxurl rule set + qjs + yt-dlp + ffmpeg/ffprobe (all SHA-256 checked)
bash build.sh                         # build/Fully.app (the engine is frozen into Resources/bin/fully-engine)
bash scripts/make-dmg.sh              # build/Fully-<version>.dmg (FULLY_DMG_BG sets a background image)
bash scripts/notarize.sh              # Apple notarization + stapling (needs a Developer ID and notarytool credentials)
python3 engine/test_rules.py          # offline tests for the thumbnail → original rules
bash scripts/check-clean.sh           # pre-publish source scan; scan a build with bash scripts/check-binary.sh build/Fully.app
```

The engine also runs on its own in Terminal:

```bash
python3 engine/grab.py <link> <folder>                  # grab the images on a page, a video, or a board
python3 engine/grab.py --json --probe <link> <folder>   # look only: name, count (videos: length), largest size
python3 engine/grab.py --audio <video link> <folder>    # audio only; --frames a frame per shot, --data titles & comments
```

Screenshots and design review (no network): `build/Fully.app/Contents/MacOS/Fully --demo <state> --snapshot out.png` (states: image video run done doneone err batch pick recent follows settings sites terms privacy), `--card-demo ask|run|done|err --snapshot out.png`, `--dock-demo out.png`, `--statusicon out.png`; add `--lang en` or `--theme dark`.

## Layout

```
app/Sources/   Swift shell: main (panel, queue, clipboard, menu bar, Services, fully://), ClipCard (preview card),
               SideIcons (Dock and menu bar), Follow (following), Thumbs (thumbnails), Installer (double-click install from the DMG),
               Prefs (language, settings, running the engine), Engines (daily video-engine updates)
app/           ui.html (main panel), ui-media.js (video and board screens), card.html (preview card), Share/ (Share menu extension),
               lproj/ (Services menu names), brand/ (trademarks)
engine/        Python engine: grab.py (page scan, original-size rules, preview), core.py (downloads, dedup, events), maxurl.py + maxurl_runner.js,
               media.py (hooks in video and boards), video.py (video: yt-dlp + ffmpeg), pin_grab.py (boards)
scripts/       vendor-fetch, make-dmg, notarize, check-clean / check-binary (pre-publish scans)
```

## Rights holders

If you believe Fully is being used to infringe your rights, please [open an issue](https://github.com/intentionltd888/fully/issues) in this repository.

## License

The code is MIT-licensed (see `LICENSE`). The Fully mark, wordmark and app icon, and the wordmark in `app/brand/`, are trademarks and are not covered by the MIT license (see `app/brand/TRADEMARK.md`).
Third-party components: `THIRD-PARTY-NOTICES.txt` (the yt-dlp video engine and FFmpeg are GPL programs, run as separate executables). Terms of use: `TERMS.md`. Privacy and permissions: `PRIVACY.md`. Limits for forks and redistribution: `COMPLIANCE.md`.
