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
print(f"{len(CASES) - bad}/{len(CASES)} 通過")
sys.exit(1 if bad else 0)
