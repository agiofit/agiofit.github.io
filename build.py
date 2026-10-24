#!/usr/bin/env python3
"""build.py - one trilingual source per page, three single-language pages out.

    python build.py            dry run: says what it would write, touches nothing
    python build.py --write    writes

Sources live in _src/ (a leading underscore keeps GitHub Pages from publishing them).
Each source carries <span class="en">…</span><span class="it">…</span><span class="fr">…</span>
(and <tspan> inside SVG) exactly as the site does today. For each language this script keeps
that language's elements, unwraps them, drops the other two with everything they contain,
sets <html lang>, writes canonical, hreflang and og:locale, and turns the JavaScript language
switcher into three plain links: the EN, IT and FR buttons of the site bar's .sitenav-lang
become links to the three versions of the same page. The head carries its Italian and French
text in data-it and data-fr attributes on <title> and on the text <meta> tags; this script
picks the page's language and removes the attributes. An attribute in the body does the same
with data-it-<name> and data-fr-<name>: aria-label="…" data-it-aria-label="…" data-fr-aria-label="…".
Nothing is translated here: the source stays the single place where the three languages live.

Before writing, every page is checked: no element of another language left, span and tspan
balanced, every head text and attribute translated, no call to setLang left, and in the site
bar one language group holding three links to the right pages, in order, with only the page's
own language marked current. The Cut Profile builder's options for "Measured by", "Cut" and
"Does the fabric stretch?" are checked against the schema the builder validates with, and every
agiofit.org link in llms.txt against the sitemap list. If one check fails, nothing is written.
Each file written is read back at once; if one does not hold what was meant, nothing more is
written.

    _src/index.html                      ->  /index.html  /it/index.html  /fr/index.html
    _src/guide/index.html                ->  /guide/  /it/guide/  /fr/guide/
    _src/builder/index.html              ->  /builder/  /it/builder/  /fr/builder/
    _src/builder/cut-profile/index.html  ->  /builder/cut-profile/  /it/builder/cut-profile/
                                             /fr/builder/cut-profile/
    _src/builder/fit-profile/index.html  ->  /builder/fit-profile/  /it/builder/fit-profile/
                                             /fr/builder/fit-profile/
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

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
    "builder/index.html": "builder/",
    "builder/cut-profile/index.html": "builder/cut-profile/",
    "builder/fit-profile/index.html": "builder/fit-profile/",
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


# an attribute in the body whose text changes with the language: the English value is in the
# attribute, the other two in data-it-<name> and data-fr-<name> on the same tag
LANG_ATTR = re.compile(r'\sdata-(it|fr)-([a-z][a-z-]*)="([^"]*)"')
LANG_ATTR_TAG = re.compile(r'<[a-zA-Z][^>]*\sdata-(?:it|fr)-[a-z][^>]*>')


def translate_attrs(html: str, lang: str) -> str:
    """Put the page's language into every attribute that has data-it-* and data-fr-*,
    then drop those two."""
    def one(m):
        tag = m.group(0)
        texts = {(l, name): text for l, name, text in LANG_ATTR.findall(tag)}
        for name in sorted({name for _, name in texts}):
            where = f"{name}, line {line_of(html, m.start())}"
            for l in ("it", "fr"):
                if not texts.get((l, name), "").strip():
                    raise ValueError(f"{where} has no {l} text")
            own = re.compile(r'(\s%s=")[^"]*(")' % re.escape(name))
            if not own.search(tag):
                raise ValueError(f"{where} has translations but no English value")
            if lang != "en":
                tag = own.sub(lambda c: c.group(1) + texts[(lang, name)] + c.group(2), tag, count=1)
        return LANG_ATTR.sub("", tag)
    return LANG_ATTR_TAG.sub(one, html)


def og_locales(lang: str) -> str:
    rows = [f'<meta property="og:locale" content="{OG[lang]}">']
    rows += [f'<meta property="og:locale:alternate" content="{OG[l]}">' for l in LANGS if l != lang]
    return "\n".join(rows)


LANG_GROUP = re.compile(r'<div class="sitenav-lang"[^>]*>(.*?)</div>', re.S)


def check_lang_links(html: str, page: str, lang: str) -> list:
    """The language group of the site bar: one group, three links to the three versions of
    this page, in the order EN, IT, FR, and only the page's own language marked current."""
    groups = LANG_GROUP.findall(html)
    if not groups:
        return ["no language group in the site bar"]
    if len(groups) > 1:
        return [f"{len(groups)} language groups in the bar, expected 1"]
    problems = []
    links = re.findall(r"<a\b([^>]*)>(.*?)</a>", groups[0], re.S)
    want = [("/" + out_path(page, l), l, l.upper()) for l in LANGS]
    got = []
    for attrs, text in links:
        href = re.search(r'\bhref="([^"]*)"', attrs)
        hreflang = re.search(r'\bhreflang="([^"]*)"', attrs)
        got.append((href.group(1) if href else None, hreflang.group(1) if hreflang else None, text.strip()))
    if got != want:
        problems.append(f"language links are {got}, expected {want}")
    current = [hl for (attrs, _), (_, hl, _) in zip(links, got) if re.search(r"\baria-current=", attrs)]
    if current != [lang]:
        problems.append(f"language marked current: {current}, expected ['{lang}']")
    return problems


def check_page(html: str, page: str, lang: str) -> list:
    """What a generated page must satisfy before it is written. Returns the problems found."""
    problems = check_lang_links(html, page, lang)
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
    for m in re.finditer(r"\sdata-(it|fr)-[a-z][a-z-]*=", html):
        problems.append(f"{m.group(0).strip()} left, line {line_of(html, m.start())}")
    # a language button not turned into a link would call a function the page no longer has
    for m in re.finditer(r"setLang\(", html):
        problems.append(f"setLang( left, line {line_of(html, m.start())}")
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


def lang_links(page: str, lang: str) -> str:
    """The language group of the site bar: EN, IT, FR as links to the same page."""
    out = []
    for l in LANGS:
        current = ' aria-current="true"' if l == lang else ""
        out.append(f'<a href="/{out_path(page, l)}" hreflang="{l}" lang="{l}" '
                   f'aria-label="{NAMES[l]}"{current}>{l.upper()}</a>')
    return "\n      ".join(out)


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
    h = translate_attrs(h, lang)

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
    #    language folder the guide and builder links point at that language's pages, the
    #    builders under /builder/ included
    h = re.sub(r'href="(?!http|#|mailto|/)([^"]+)"', r'href="/\1"', h)
    if lang != "en":
        h = h.replace('href="/guide/"', 'href="/%s/guide/"' % lang)
        h = h.replace('href="/builder/', 'href="/%s/builder/' % lang)
        h = h.replace('href="/"', 'href="/%s/"' % lang)
        h = h.replace('href="/#schemas"', 'href="/%s/#schemas"' % lang)

    # 5. the switcher: links, not JavaScript. Written after step 4, so these links are not
    #    localized: on /it/guide/ the EN link must stay /guide/
    if LANG_GROUP.search(h):
        h = LANG_GROUP.sub(
            lambda m: m.group(0).split(">", 1)[0] + ">\n      " + lang_links(page, lang) + "\n    </div>",
            h, count=1,
        )
    h = drop_function(h, "setLang")
    # a script block that held only setLang is now empty: the page has no use for it
    h = re.sub(r"\n*<script>\s*</script>", "", h)
    h = re.sub(r"var LANG\s*=\s*'[a-z]{2}'", "var LANG = '%s'" % lang, h, count=1)
    h = re.sub(r'body\.lang-(en|it|fr)[^}]*\}', "", h)
    return h


def write_and_read_back(target: Path, text: str) -> bool:
    """Write a file, then read it back: it only counts as written if it holds what was meant."""
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    with open(target, encoding="utf-8", newline="") as f:
        return f.read() == text


class SelectOptions(HTMLParser):
    """The option values of the <select> elements with the given ids."""

    def __init__(self, ids):
        super().__init__(convert_charrefs=True)
        self.values = {i: None for i in ids}
        self.open = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "select" and a.get("id") in self.values:
            self.open = a["id"]
            self.values[self.open] = []
        elif tag == "option" and self.open:
            self.values[self.open].append(a.get("value"))

    def handle_endtag(self, tag):
        if tag == "select":
            self.open = None


# the Cut Profile builder's source, under _src/, and the page it becomes
CUT_BUILDER = "builder/cut-profile/index.html"


def check_builder() -> tuple:
    """The Cut Profile builder's options against the schema it checks with: "Measured by", "Cut"
    and "Does the fabric stretch?".

    A value the schema does not accept makes a file nobody can download; a value it accepts
    but the builder does not offer leaves someone out. The source is read: its option values
    are the ones all three pages carry. Returns (problems, summary).
    """
    name = "_src/" + CUT_BUILDER
    page = SRC / CUT_BUILDER
    if not page.is_file():
        return [f"{name} is missing"], ""
    html = page.read_text(encoding="utf-8")

    m = re.search(r"""\bSCHEMA_URL\s*=\s*["']([^"']+)["']""", html)
    if not m:
        return [f"SCHEMA_URL not found in {name}"], ""
    url = urljoin("/" + PAGES[CUT_BUILDER], m.group(1))
    if not url.startswith("/"):
        return [f"SCHEMA_URL is not on this site: {m.group(1)}"], ""
    schema_path = ROOT / url.lstrip("/")
    if not schema_path.is_file():
        return [f"SCHEMA_URL points at {url}, which is missing"], ""
    try:
        props = json.loads(schema_path.read_text(encoding="utf-8"))["properties"]
        enums = {
            "published_by": props["provenance"]["properties"]["published_by"]["enum"],
            "cut": props["cut"]["enum"],
            "stretch_class": props["fabric"]["properties"]["stretch_class"]["enum"],
        }
    except (ValueError, KeyError, TypeError) as e:
        return [f"{url} has no enum where expected ({e})"], ""

    parser = SelectOptions(enums)
    parser.feed(html)
    problems = []
    for sid, allowed in enums.items():
        found = parser.values[sid]
        if found is None:
            problems.append(f'<select id="{sid}"> not found in {name}')
            continue
        if sid in ("cut", "stretch_class"):
            found = [v for v in found if v != ""]    # "not stated" and "I don't know" write nothing
        extra = [v for v in found if v not in allowed]
        missing = [v for v in allowed if v not in found]
        if extra:
            problems.append(f"#{sid}: not in the schema: {', '.join(map(str, extra))}")
        if missing:
            problems.append(f"#{sid}: missing from the builder: {', '.join(missing)}")
    counted = ", ".join(f"#{sid} ({len(allowed)})" for sid, allowed in enums.items())
    summary = f"{name}: {counted} match {url.lstrip('/')}"
    return problems, summary


# a site link in llms.txt ends at whitespace or at the ")" that closes a Markdown link
LLMS_LINK = re.compile(re.escape(SITE) + r"[^\s)]*")


def check_llms(sitemap_urls: list) -> tuple:
    """Every agiofit.org link in llms.txt against the sitemap list.

    llms.txt is written by hand, not by this script; a link to a URL the sitemap does not
    list points nowhere. Links to other hosts are not checked: this script makes no network
    requests. Returns (problems, links).
    """
    page = ROOT / "llms.txt"
    if not page.is_file():
        return ["llms.txt is missing"], []
    links = []
    for m in LLMS_LINK.finditer(page.read_text(encoding="utf-8")):
        u = m.group(0).split("#", 1)[0]
        if u not in links:
            links.append(u)
    problems = [f"{u}  (not in the sitemap list)" for u in links if u not in sitemap_urls]
    return problems, links


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
        problems = check_page(html, page, lang)
        print(f"  /{rel:36} {lang}  {len(html):>6} bytes  problems: {len(problems)}")
        for p in problems:
            print(f"      {p}")
        failed = failed or bool(problems)
    if failed:
        print("\n  Nothing written: the pages above did not pass the checks\n")
        return 1

    urls = [f"{SITE}/{out_path(p, l)}" for p in PAGES for l in LANGS]
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

    problems, summary = check_builder()
    if problems:
        print()
        for p in problems:
            print(f"  {p}")
        print("\n  Nothing written: the builder's options do not match its schema\n")
        return 1
    print(f"\n  {summary}")

    problems, links = check_llms(sitemap_urls)
    if problems:
        print()
        for p in problems:
            print(f"  {p}")
        print("\n  Nothing written: llms.txt is missing or links outside the sitemap list\n")
        return 1
    print(f"  llms.txt: {len(links)} site links, all in the sitemap list")
    for u in links:
        print(f"      {u}")

    if not write:
        print("\nDry run: nothing was touched.")
        print("To write for real:  python build.py --write\n")
        return 0

    rows = "\n".join(f"  <url><loc>{u}</loc></url>" for u in sitemap_urls)
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + rows + "\n</urlset>\n")
    writes = [(ROOT / out_path(page, lang) / "index.html", html) for page, lang, html in plan]
    writes.append((ROOT / "sitemap.xml", sitemap))

    # each file is read back before the next one is written: at the first one that does not
    # hold what was meant, nothing more is written
    for target, text in writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not write_and_read_back(target, text):
            rel = str(target.relative_to(ROOT)).replace("\\", "/")
            print(f"\n  Nothing more written: {rel} read back differs\n")
            return 1

    print("\nWritten, sitemap included.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
