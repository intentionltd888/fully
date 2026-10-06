# -*- coding: utf-8 -*-
# 離線單元測試（不連網）：CDN_RULES／通用放大規則的候選順序。跑法：/usr/bin/python3 engine/test_rules.py
# 改了 upgrade()／CDN_RULES 就跑一次。這裡放建站平台與通用規則的樣本。
import sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import grab

CASES = [
    # (輸入, 期望的第一候選 或 期望候選之一)
    ("https://images.squarespace-cdn.com/content/v1/abc/1600000000000-XYZ/img.jpg?format=750w",
     "https://images.squarespace-cdn.com/content/v1/abc/1600000000000-XYZ/img.jpg?format=original"),
    ("https://static.wixstatic.com/media/84770f_9c3~mv2.jpg/v1/fill/w_640,h_426,al_c,q_80/84770f_9c3~mv2.webp",
     "https://static.wixstatic.com/media/84770f_9c3~mv2.jpg"),
    ("https://miro.medium.com/v2/resize:fit:700/format:webp/1*tNWGLkRt1qW3_aW5WiGb5Q.jpeg",
     "https://miro.medium.com/1*tNWGLkRt1qW3_aW5WiGb5Q.jpeg"),
    ("https://cdn-images-1.medium.com/fit/t/800/240/1*CWl19R2s2gM5u5NcMEP8oA.jpeg",
     "https://cdn-images-1.medium.com/1*CWl19R2s2gM5u5NcMEP8oA.jpeg"),
    ("https://cdn.prod.website-files.com/5f/6a/hero-p-500.jpg", "https://cdn.prod.website-files.com/5f/6a/hero.jpg"),
    ("https://framerusercontent.com/images/abc.jpg?scale-down-to=1024", "https://framerusercontent.com/images/abc.jpg"),
    ("https://substackcdn.com/image/fetch/w_1456,c_limit,f_auto,q_auto:good/https%3A%2F%2Fimages.example.org%2Fimg.png",
     "https://images.example.org/img.png"),
    ("https://freight.cargo.site/w/1600/q/75/i/abcdef/name.jpg", "https://freight.cargo.site/t/original/i/abcdef/name.jpg"),
    ("https://cdn.myportfolio.com/abc/def_rw_1920.jpg", "https://cdn.myportfolio.com/abc/def_rw_3840.jpg"),
    ("https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEg/s320/name.jpg",
     "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEg/s0/name.jpg"),
    ("https://lh3.googleusercontent.com/pw/ABC123=w800-h600-no", "https://lh3.googleusercontent.com/pw/ABC123=s0"),
    ("https://res.cloudinary.com/demo/image/upload/w_500,c_fill,q_auto/v1600/sample.jpg",
     "https://res.cloudinary.com/demo/image/upload/v1600/sample.jpg"),
    ("https://cdn.shopify.com/s/files/1/0001/products/tee_1024x1024@2x.jpg?v=1600", "https://cdn.shopify.com/s/files/1/0001/products/tee.jpg?v=1600"),
    ("https://cdn.shopify.com/s/files/1/0001/products/tee_grande.jpg", "https://cdn.shopify.com/s/files/1/0001/products/tee.jpg"),
    ("https://example.com/wp-content/uploads/2024/01/pic-1024x768.jpg?w=300", "https://example.com/wp-content/uploads/2024/01/pic.jpg?w=300"),
    ("https://example.com/wp-content/uploads/2024/01/pic-scaled.jpg", "https://example.com/wp-content/uploads/2024/01/pic.jpg"),
    ("https://example.com/img/hero_small_2x.jpg", "https://example.com/img/hero_large_2x.jpg"),
    # MediaWiki：縮圖 → upload.wikimedia.org 原始上傳檔；File: 說明頁 → Special:FilePath
    ("https://thumb.wikimedia.org/wikipedia/commons/thumb/6/67/6265_Dessau.JPG/1280px-6265_Dessau.JPG?utm_source=en",
     "https://upload.wikimedia.org/wikipedia/commons/6/67/6265_Dessau.JPG"),
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/Bauhaus-Signet.svg/220px-Bauhaus-Signet.svg.png",
     "https://upload.wikimedia.org/wikipedia/commons/b/bd/Bauhaus-Signet.svg"),
    ("https://en.wikipedia.org/wiki/File:6265_Dessau.JPG", "https://en.wikipedia.org/wiki/Special:FilePath/6265_Dessau.JPG"),
]

bad = 0
for src, want in CASES:
    first, rest = grab.upgrade(src)
    cands = [first] + rest
    if want is None:
        ok = (first == src)
    else:
        ok = (first == want) or (want in cands and cands.index(want) <= 1)
    if not ok:
        bad += 1
        print("✕", src, "\n   got:", cands[:3], "\n   want:", want)

# 貼文解析（threads_grab）：網址判斷、DASH 清單挑軌、輪播展開。資料是手寫的最小樣本。
import threads_grab as TH

def _t(cond, msg):
    global bad
    CASES.append(msg)
    if not cond:
        bad += 1
        print("✕", msg)

_t(TH.handles("https://www.threads.com/@a.b/post/AbC_1-x?xmt=1") and TH.post_code("https://www.threads.net/@a/post/AbC") == "AbC", "貼文網址")
_t(TH.handles("https://www.threads.com/t/AbC") and TH.post_code("https://www.threads.com/t/AbC") == "AbC", "短網址")
_t(TH.handles("https://www.threads.com/@a") and TH.handles("https://www.threads.com/@a/media") and TH.post_code("https://www.threads.com/@a") is None, "個人頁")
_t(not TH.handles("https://www.threads.com/search?q=x") and not TH.handles("https://www.threads.com/"), "搜尋與首頁交回通用掃圖")
_t(TH.claims("threads.net") and TH.claims("www.threads.com") and not TH.claims("notthreads.com"), "比網域不比子字串")
_t(TH._iso_seconds("PT1M2.5S") == 62.5 and TH._iso_seconds("PT13S") == 13 and TH._iso_seconds("") == 0, "DASH 長度")

_MPD = ('<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="PT13S"><Period>'
        '<AdaptationSet contentType="video">'
        '<Representation bandwidth="900" width="720" height="900" mimeType="video/mp4"><BaseURL>https://v/720.mp4</BaseURL></Representation>'
        '<Representation bandwidth="1800" width="1080" height="1350" mimeType="video/mp4"><BaseURL>https://v/1080.mp4?a=1&amp;b=2</BaseURL></Representation>'
        '</AdaptationSet><AdaptationSet contentType="audio">'
        '<Representation bandwidth="48" mimeType="audio/mp4"><AudioChannelConfiguration value="2"/><BaseURL>https://v/a.mp4</BaseURL></Representation>'
        '</AdaptationSet></Period></MPD>')
_v, _a, _s = TH.dash_tracks(_MPD)
_t(_v == ("https://v/1080.mp4?a=1&b=2", 1080, 1350) and _a == "https://v/a.mp4" and _s == 13, "DASH 挑最大畫面軌＋聲音軌")
_t(TH.dash_tracks("<not xml") == (None, None, 0), "清單讀不懂不報錯")

_img = {"image_versions2": {"candidates": [{"url": "https://i/s.jpg", "width": 320, "height": 400},
                                           {"url": "https://i/l.jpg", "width": 1440, "height": 1800}]}}
_hi = dict(_img, pk="1000000000000000001", video_versions=[{"type": 101, "url": "https://p/720.mp4"}], video_dash_manifest=_MPD)
_lo = dict(_img, pk="1000000000000000002", video_versions=[{"type": 101, "url": "https://p/720b.mp4"}],
           video_dash_manifest=_MPD.replace('width="1080" height="1350"', 'width="720" height="900"'), original_width=720, original_height=900)
_post = {"code": "X", "media_type": 8, "user": {"username": "a"}, "caption": {"text": "標題\n第二行"},
         "carousel_media": [dict(_img, pk="1000000000000000003"), _hi, _lo]}
_rows = TH.post_rows(_post)
_t(len(_rows) == 3 and _rows[0]["url"] == "https://i/l.jpg" and _rows[0]["w"] == 1440 and _rows[0]["title"] == "標題", "輪播：圖取最大、標題取第一行")
_t(_rows[1].get("dash") == ("https://v/a.mp4", 13) and _rows[1]["url"].startswith("https://v/1080") and _rows[1]["alts"] == ["https://p/720.mp4"], "清單比直連大：接兩軌，直連當備援")
_t(not _rows[2].get("dash") and _rows[2]["url"] == "https://p/720b.mp4", "清單沒比直連大：用直連（不轉檔）")
_t(all(r["id"].isdigit() and len(r["id"]) >= 15 for r in _rows), "id 是每一項自己的 pk（抓過的會跳過）")
_t(TH.post_rows({"code": "Y", "media_type": 19, "user": {"username": "a"}}) == [], "純文字貼文沒有檔")

print(f"{len(CASES) - bad}/{len(CASES)} 通過")
sys.exit(1 if bad else 0)
