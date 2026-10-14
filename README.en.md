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
- **Boards**: reads a whole board to the end, nothing skipped; video pins are saved as videos and every page of a multi-page pin is saved. A section link grabs just that section; an account's page grabs every public board, one folder each.
- **Audio**: links straight to an audio file, players and download links on a page, and podcast feeds — saved as the original files, no re-encoding.
- **Posts**: paste the link of a public post and Fully saves every image and video in it, each item of a carousel, and the author's own follow-up posts in the thread. Images at original size; videos at the best quality the post offers (when the direct file stops at 720p and a 1080p picture exists, Fully joins it with the sound and makes sure QuickTime can play it).
- **Fast and quiet**: parallel downloads that stay polite with rate-limited sites; your Mac doesn't sleep mid-download; the Dock icon shows a progress bar and how many are queued, the menu bar shows a progress ring; quit and reopen and it picks up where it left off.
- **Ready to use**: a single image goes straight to the clipboard (⌘V into your design tool); thumbnails can be dragged out; every file's "Where from" field keeps the source link (findable in Spotlight).
- **Afterwards**: follow a page, board or playlist and Fully checks it every 6 hours, grabbing only what's new; identical images are never saved twice; the last 30 grabs are kept.
- **Send links from anywhere**: ⌃⌥⌘V for the panel, the Share menu, right-click → Services → "Grab with Fully", `fully://grab?url=…`, or the bookmarklet.
- Chinese / English interface, light and dark. When a new version is out you get one notification, and Settings → About Fully shows "Get the new version".

Fully only handles images and videos that are publicly visible on the web: nothing behind an account, no getting around paywalls or any other access control, no DRM.

## Download

[**Download Fully.dmg**](https://github.com/intentionltd888/fully/releases/latest/download/Fully.dmg) (Apple silicon Mac, macOS 12 or later; notarized by Apple). Open the DMG and drag Fully into Applications — or just double-click it.

Every version is under [Releases](https://github.com/intentionltd888/fully/releases). Please read the [terms of use](TERMS.md) first; what leaves your Mac is listed in [PRIVACY.md](PRIVACY.md).

## Rights holders

If you believe Fully is being used to infringe your rights, please [open an issue](https://github.com/intentionltd888/fully/issues) in this repository.

## License

This repository hosts release builds and documentation only; the source code is not public. Released versions are licensed as described in `LICENSE`. The Fully mark, wordmark and app icon are trademarks and are not covered by the LICENSE (see `TRADEMARK.md`).
Third-party components: `THIRD-PARTY-NOTICES.txt` (the yt-dlp video engine and FFmpeg are GPL programs, run as separate executables). Terms of use: `TERMS.md`. Privacy and permissions: `PRIVACY.md`.
