#!/usr/bin/env python3
"""build.py - one trilingual source per page, three single-language pages out.

    python build.py            dry run: says what it would write, touches nothing
    python build.py --write    writes

Sources live in _src/ (a leading underscore keeps GitHub Pages from publishing them).
Each source carries <span class="en">…</span><span class="it">…</span><span class="fr">…</span>
exactly as the site does today. For each language this script keeps that language's spans,
unwraps them, drops the other two, sets <html lang>, writes canonical and hreflang, and turns
the JavaScript language switcher into three plain links. Nothing is translated here: the source
stays the single place where the three languages live.

    _src/index.html        ->  /index.html        /it/index.html        /fr/index.html
    _src/guide/index.html  ->  /guide/index.html  /it/guide/index.html  /fr/guide/index.html
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "_src"
SITE = "https://agiofit.org"

LANGS = ["en", "it", "fr"]
NAMES = {"en": "English", "it": "Italiano", "fr": "Français"}
OG = {"en": "en", "it": "it", "fr": "fr"}

# source file -> path of the English output, relative to the site root
PAGES = {
    "index.html": "",
    "guide/index.html": "guide/",
}


def out_path(page: str, lang: str) -> str:
    """Where a page goes for a language. English keeps the existing URLs."""
    base = PAGES[page]
    return base if lang == "en" else f"{lang}/{base}"


def strip_languages(html: str, lang: str) -> str:
    """Keep this language's spans, unwrapped; remove the other two entirely."""
    for other in LANGS:
        if other != lang:
            html = re.sub(
                r'<span class="%s">.*?</span>' % other, "", html, flags=re.S
            )
    html = re.sub(r'<span class="%s">(.*?)</span>' % lang, r"\1", html, flags=re.S)
    return html


def drop_function(html: str, name: str) -> str:
    """Remove one JavaScript function by matching its braces.

    The guide keeps its interactive demo in the same <script> block, so the whole block
    cannot go. With the switcher turned into links, nothing calls this function any more.
    """
    start = html.find("function %s(" % name)
    if start < 0:
        return html
    i = html.index("{", start)
    depth = 0
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return html[:start] + html[j + 1:].lstrip("\n")
    return html


def switcher(page: str, lang: str) -> str:
    """Three links instead of three buttons: crawlers follow links, not onclick."""
    out = []
    for l in LANGS:
        href = "/" + out_path(page, l)
        if l == lang:
            out.append(f'<a href="{href}" aria-current="true" hreflang="{l}">{NAMES[l]}</a>')
        else:
            out.append(f'<a href="{href}" hreflang="{l}">{NAMES[l]}</a>')
    return "\n    ".join(out)


def head_links(page: str, lang: str) -> str:
    rows = [f'<link rel="canonical" href="{SITE}/{out_path(page, lang)}">']
    for l in LANGS:
        rows.append(f'<link rel="alternate" hreflang="{l}" href="{SITE}/{out_path(page, l)}">')
    rows.append(f'<link rel="alternate" hreflang="x-default" href="{SITE}/{out_path(page, "en")}">')
    return "\n".join(rows)


def build_page(source: str, page: str, lang: str) -> str:
    h = source

    # 1. one language only
    h = strip_languages(h, lang)

    # 2. the document declares which language it is, and the body no longer switches
    h = re.sub(r'<html([^>]*)\slang="[a-z-]+"', r'<html\1 lang="%s"' % lang, h, count=1)
    h = h.replace(' id="html-root"', "")
    h = re.sub(r'<body[^>]*>', "<body>", h, count=1)

    # 3. canonical + hreflang, replacing whatever canonical was there
    h = re.sub(r'\s*<link rel="canonical"[^>]*>', "", h)
    h = h.replace("</head>", head_links(page, lang) + "\n</head>", 1)
    h = re.sub(r'(<meta property="og:locale" content=")[^"]*(")', r"\g<1>%s\g<2>" % OG[lang], h)
    h = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
               r"\g<1>%s/%s\g<2>" % (SITE, out_path(page, lang)), h)

    # 4. every internal link is absolute, so a page works from any folder; and inside a
    #    language folder the guide link points at that language's guide
    h = re.sub(r'href="(?!http|#|mailto|/)([^"]+)"', r'href="/\1"', h)
    if lang != "en":
        h = h.replace('href="/guide/"', 'href="/%s/guide/"' % lang)
        h = h.replace('href="/"', 'href="/%s/"' % lang)

    # 5. the switcher: links, not JavaScript
    h = re.sub(
        r'<div class="lingua-box"[^>]*>.*?</div>',
        '<div class="lingua-box" role="group" aria-label="Language / Lingua / Langue">\n    '
        + switcher(page, lang) + "\n  </div>",
        h, count=1, flags=re.S,
    )
    h = drop_function(h, "setLang")
    h = re.sub(r"var LANG\s*=\s*'[a-z]{2}'", "var LANG = '%s'" % lang, h, count=1)
    h = re.sub(r'body\.lang-(en|it|fr)[^}]*\}', "", h)

    # 6. the switcher is now links, so it needs link styling, not button styling
    h = h.replace("</style>", """  .lingua-box a{font:inherit;font-size:13px;text-decoration:none;color:var(--ink);
    opacity:.6;padding:6px 12px;border-radius:999px}
  .lingua-box a:hover{opacity:1}
  .lingua-box a[aria-current]{opacity:1;font-weight:600;background:rgba(30,36,48,.06)}
</style>""", 1)
    return h


def main() -> int:
    write = "--write" in sys.argv
    if not SRC.is_dir():
        print("\n  Nothing written: _src is missing\n")
        return 1

    plan = []
    for page in PAGES:
        src = SRC / page
        if not src.is_file():
            print(f"\n  Nothing written: {src} is missing\n")
            return 1
        text = src.read_text(encoding="utf-8")
        for lang in LANGS:
            if not re.search(r'<span class="%s">' % lang, text):
                print(f"\n  Nothing written: {page} has no {lang} text\n")
                return 1
            plan.append((page, lang, build_page(text, page, lang)))

    print()
    for page, lang, html in plan:
        target = ROOT / out_path(page, lang) / "index.html"
        rel = str(target.relative_to(ROOT)).replace("\\", "/")
        leftover = len(re.findall(r'<span class="(en|it|fr)">', html))
        print(f"  /{rel:26} {lang}  {len(html):>6} bytes  leftover spans: {leftover}")
        if leftover:
            print("\n  Nothing written: language spans are still in the output\n")
            return 1

    if not write:
        print("\nDry run: nothing was touched.")
        print("To write for real:  python build.py --write\n")
        return 0

    for page, lang, html in plan:
        target = ROOT / out_path(page, lang) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8", newline="")

    urls = [f"{SITE}/{out_path(p, l)}" for p in PAGES for l in LANGS] + [f"{SITE}/builder/"]
    schemas = ["fit-profile", "cut-profile", "match-report"]
    rows = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    rows += "\n" + "\n".join(
        f"  <url><loc>{SITE}/schemas/v0.1/{s}.schema.json</loc></url>" for s in schemas
    )
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + rows + "\n</urlset>\n", encoding="utf-8", newline="")

    print("\nWritten, sitemap included.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
