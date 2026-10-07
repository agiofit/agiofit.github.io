#!/usr/bin/env python3
"""build.py - one trilingual source per page, three single-language pages out.

    python build.py            dry run: says what it would write, touches nothing
    python build.py --write    writes

Sources live in _src/ (a leading underscore keeps GitHub Pages from publishing them).
Each source carries <span class="en">…</span><span class="it">…</span><span class="fr">…</span>
(and <tspan> inside SVG) exactly as the site does today. For each language this script keeps
that language's elements, unwraps them, drops the other two with everything they contain,
sets <html lang>, writes canonical, hreflang and og:locale, and turns the JavaScript language
switcher into three plain links. The head carries its Italian and French text in data-it and
data-fr attributes on <title> and on the text <meta> tags; this script picks the page's language
and removes the attributes. Nothing is translated here: the source stays the single place where
the three languages live.

Before writing, every page is checked: no element of another language left, span and tspan
balanced, every head text translated. If one check fails, nothing is written.

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
OG = {"en": "en_GB", "it": "it_IT", "fr": "fr_FR"}

# head tags whose text changes with the language: the English text is in the tag,
# the other two in data-it and data-fr
HEAD_FIELDS = {
    "title": r"<title\b[^>]*>",
    "description": r'<meta name="description"[^>]*>',
    "og:title": r'<meta property="og:title"[^>]*>',
    "og:description": r'<meta property="og:description"[^>]*>',
    "og:image:alt": r'<meta property="og:image:alt"[^>]*>',
}

# opening or closing span/tspan; the attributes are kept to read the class
LANG_TAG = re.compile(r"<(/?)(span|tspan)\b([^>]*)>")

# source file -> path of the English output, relative to the site root
PAGES = {
    "index.html": "",
    "guide/index.html": "guide/",
}


def out_path(page: str, lang: str) -> str:
    """Where a page goes for a language. English keeps the existing URLs."""
    base = PAGES[page]
    return base if lang == "en" else f"{lang}/{base}"


def line_of(html: str, pos: int) -> int:
    return html.count("\n", 0, pos) + 1


def strip_languages(html: str, lang: str) -> str:
    """Keep this language's span/tspan elements, unwrapped; remove the other two entirely.

    A small parser, not a regular expression: a language element can hold other spans
    (<span class="mono">), so it ends at its own closing tag, not at the first one.
    """
    out = []
    pos = 0
    stack = []        # (tag, kind) of the open elements; kind is keep, drop or other
    drop_at = None    # stack depth of the element being dropped, if any
    for m in LANG_TAG.finditer(html):
        closing, tag, attrs = m.groups()
        if drop_at is None:
            out.append(html[pos:m.start()])
        pos = m.end()
        if closing:
            if not stack or stack[-1][0] != tag:
                raise ValueError(f"</{tag}> without its opening tag, line {line_of(html, m.start())}")
            _, kind = stack.pop()
            if drop_at is not None:
                if len(stack) == drop_at:
                    drop_at = None
            elif kind == "other":
                out.append(m.group(0))
            continue
        c = re.search(r'\bclass="(en|it|fr)"', attrs)
        kind = "other" if not c else ("keep" if c.group(1) == lang else "drop")
        stack.append((tag, kind))
        if drop_at is not None:
            continue
        if kind == "drop":
            drop_at = len(stack) - 1
        elif kind == "other":
            out.append(m.group(0))
    if stack:
        raise ValueError(f"<{stack[-1][0]}> never closed")
    out.append(html[pos:])
    return "".join(out)


def translate_head(html: str, lang: str) -> str:
    """Put the page's language into the head text fields, then drop data-it and data-fr."""
    for field, pattern in HEAD_FIELDS.items():
        m = re.search(pattern, html)
        if not m:
            raise ValueError(f"{field} is missing from the head")
        tag = m.group(0)
        new_tag = re.sub(r'\s+data-(it|fr)="[^"]*"', "", tag)
        if lang != "en":
            t = re.search(r'\sdata-%s="([^"]*)"' % lang, tag)
            if not t or not t.group(1).strip():
                raise ValueError(f"{field} has no {lang} text")
            if field == "title":
                end = html.index("</title>", m.end())
                html = html[:m.start()] + new_tag + t.group(1) + html[end:]
                continue
            new_tag = re.sub(r'(\scontent=")[^"]*(")',
                             lambda c: c.group(1) + t.group(1) + c.group(2), new_tag, count=1)
        html = html[:m.start()] + new_tag + html[m.end():]
    return html


def og_locales(lang: str) -> str:
    rows = [f'<meta property="og:locale" content="{OG[lang]}">']
    rows += [f'<meta property="og:locale:alternate" content="{OG[l]}">' for l in LANGS if l != lang]
    return "\n".join(rows)


def check_page(html: str, lang: str) -> list:
    """What a generated page must satisfy before it is written. Returns the problems found."""
    problems = []
    for m in re.finditer(r'<([a-zA-Z][\w-]*)\b[^>]*\sclass="(en|it|fr)"', html):
        problems.append(f'<{m.group(1)} class="{m.group(2)}"> left, line {line_of(html, m.start())}')
    stack = []
    for m in LANG_TAG.finditer(html):
        closing, tag, _ = m.groups()
        if not closing:
            stack.append(tag)
        elif not stack or stack[-1] != tag:
            problems.append(f"</{tag}> without its opening tag, line {line_of(html, m.start())}")
        else:
            stack.pop()
    if stack:
        problems.append(f"{len(stack)} span/tspan never closed")
    if re.search(r"\sdata-(it|fr)=", html):
        problems.append("data-it or data-fr left in the page")
    return problems


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

    # 1. one language only, in the body and in the head
    h = strip_languages(h, lang)
    h = translate_head(h, lang)

    # 2. the document declares which language it is, and the body no longer switches
    h = re.sub(r'<html([^>]*)\slang="[a-z-]+"', r'<html\1 lang="%s"' % lang, h, count=1)
    h = h.replace(' id="html-root"', "")
    h = re.sub(r'<body[^>]*>', "<body>", h, count=1)

    # 3. canonical + hreflang, replacing whatever canonical was there
    h = re.sub(r'\s*<link rel="canonical"[^>]*>', "", h)
    h = h.replace("</head>", head_links(page, lang) + "\n</head>", 1)
    h = re.sub(r'\s*<meta property="og:locale(:alternate)?"[^>]*>', "", h)
    h = re.sub(r'(<meta property="og:image:alt"[^>]*>)',
               lambda m: m.group(1) + "\n" + og_locales(lang), h, count=1)
    h = re.sub(r'(<meta property="og:url" content=")[^"]*(")',
               r"\g<1>%s/%s\g<2>" % (SITE, out_path(page, lang)), h)

    # 4. every internal link is absolute, so a page works from any folder; and inside a
    #    language folder the guide link points at that language's guide
    h = re.sub(r'href="(?!http|#|mailto|/)([^"]+)"', r'href="/\1"', h)
    if lang != "en":
        h = h.replace('href="/guide/"', 'href="/%s/guide/"' % lang)
        h = h.replace('href="/"', 'href="/%s/"' % lang)
        h = h.replace('href="/#schemas"', 'href="/%s/#schemas"' % lang)

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
            try:
                plan.append((page, lang, build_page(text, page, lang)))
            except ValueError as e:
                print(f"\n  Nothing written: {page} ({lang}): {e}\n")
                return 1

    print()
    failed = False
    for page, lang, html in plan:
        target = ROOT / out_path(page, lang) / "index.html"
        rel = str(target.relative_to(ROOT)).replace("\\", "/")
        problems = check_page(html, lang)
        print(f"  /{rel:26} {lang}  {len(html):>6} bytes  problems: {len(problems)}")
        for p in problems:
            print(f"      {p}")
        failed = failed or bool(problems)
    if failed:
        print("\n  Nothing written: the pages above did not pass the checks\n")
        return 1

    urls = [f"{SITE}/{out_path(p, l)}" for p in PAGES for l in LANGS] + [f"{SITE}/builder/"]
    schemas = ["fit-profile", "cut-profile", "match-report"]
    sitemap_urls = urls + [f"{SITE}/schemas/v0.1/{s}.schema.json" for s in schemas]

    # every sitemap URL needs its file; the pages this run writes count as present
    planned = {ROOT / out_path(page, lang) / "index.html" for page, lang, _ in plan}
    missing = []
    for u in sitemap_urls:
        if not u.startswith(SITE + "/"):
            missing.append(f"{u}  (does not start with {SITE}/)")
            continue
        rel = u[len(SITE) + 1:]
        if rel == "" or rel.endswith("/"):
            rel += "index.html"
        if ROOT / rel not in planned and not (ROOT / rel).is_file():
            missing.append(f"{u}  (no file {rel})")
    if missing:
        print()
        for m in missing:
            print(f"  {m}")
        print("\n  Nothing written: sitemap URLs without a file\n")
        return 1

    if not write:
        print("\nDry run: nothing was touched.")
        print("To write for real:  python build.py --write\n")
        return 0

    for page, lang, html in plan:
        target = ROOT / out_path(page, lang) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8", newline="")

    rows = "\n".join(f"  <url><loc>{u}</loc></url>" for u in sitemap_urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + rows + "\n</urlset>\n", encoding="utf-8", newline="")

    print("\nWritten, sitemap included.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
