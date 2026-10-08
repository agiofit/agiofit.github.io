#!/usr/bin/env python3
"""demo_reports.py - the guide's demo shows the reference implementation's own answers.

    python demo_reports.py [path/to/agiofit]            dry run: says what it would write
    python demo_reports.py [path/to/agiofit] --write    writes _src/guide/index.html

The path is a clone of agiofit/agiofit, ../agiofit by default (next to this repository).
The clone is only read. Its reference implementation is imported and asked for the Match
Report of each example profile against the example shirt, at every disclosure level.
The reports go into the guide source as a JSON block, together with the commit they came
from, the number of tests, each profile's default level and the Italian and French text for
the reference's sentences.
The numbers the page quotes from the reference sit between <!-- ref:NAME --> markers and
are rewritten from the same reports.
Each profile is read as of its own updated_at. The reference counts how old a measurement is
from the day of the calculation, and the demo must not change with the calendar.

Nothing is computed in the page: the demo only shows these reports. After a change to the
reference, run this script, then python build.py.
"""

import html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GUIDE = ROOT / "_src" / "guide" / "index.html"

LEVELS = ["result_only", "explained", "scoped", "full"]
GARMENT = "examples/cut-shirt.json"
PROFILES = {
    "mature": "examples/profile-mature.json",
    "cold-start": "examples/profile-cold-start.json",
}

BLOCK_START = "<!-- reference-reports:start -->"
BLOCK_END = "<!-- reference-reports:end -->"

# Every marker the page must carry. A name is "tests", "commit", or a path into the
# reports: profile/level/key/..., where a list item is picked by index or by key=value.
MARKERS = [
    "tests",
    "commit",
    "mature/explained/recommended_size",
    "mature/explained/confidence",
    "mature/explained/alternatives/0/size_label",
    "mature/explained/alternatives/0/score",
    "mature/explained/explanation/zone=shoulders/zone",
    "mature/explained/explanation/zone=shoulders/assessment",
    "cold-start/result_only/recommended_size",
    "cold-start/result_only/confidence",
]
MARKER = re.compile(r"<!-- ref:([\w./=-]+) -->(.*?)<!-- /ref:([\w./=-]+) -->", re.S)

# The sentences the reference writes into caveats, improve_by and notes, in the other two
# languages. A report with a sentence missing here stops the script.
TRANSLATIONS = {
    "No zone could be compared: the profile has no measurements this garment can be matched against.": {
        "it": "Nessuna zona confrontabile: il profilo non ha misure da confrontare con questo capo.",
        "fr": "Aucune zone comparable : le profil n'a pas de mesures à comparer avec ce vêtement.",
    },
    "Answer derived from past purchases alone.": {
        "it": "Risposta ricavata solo dagli acquisti passati.",
        "fr": "Réponse tirée des seuls achats passés.",
    },
    "Add a measurement for thigh circumference.": {
        "it": "Aggiungi la circonferenza della coscia.",
        "fr": "Ajoutez le tour de cuisse.",
    },
    "Add a measurement for arm length.": {
        "it": "Aggiungi la lunghezza del braccio.",
        "fr": "Ajoutez la longueur de bras.",
    },
    "Add a measurement for chest circumference.": {
        "it": "Aggiungi la circonferenza del torace.",
        "fr": "Ajoutez le tour de poitrine.",
    },
    "Add a measurement for hip circumference.": {
        "it": "Aggiungi la circonferenza dei fianchi.",
        "fr": "Ajoutez le tour de hanches.",
    },
    "Re-measure with a tape: arm_length, inseam.": {
        "it": "Rimisura col metro: arm_length, inseam.",
        "fr": "Reprenez au mètre ruban : arm_length, inseam.",
    },
    "Derived from 1 past Sartoria Esempio purchase(s) in this category, no measurements used.": {
        "it": "Ricavata da 1 acquisto passato di Sartoria Esempio in questa categoria, senza misure.",
        "fr": "Déduite d'un achat passé chez Sartoria Esempio dans cette catégorie, sans mesures.",
    },
}


class Stop(Exception):
    """Something is wrong: say what, and write nothing."""


def git(clone: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed in {clone}: {r.stderr.strip()}")
    return r.stdout


def check_clone(clone: Path) -> str:
    """The short commit of a clean clone. The data has to come from one precise commit."""
    if not (clone / ".git").exists():
        raise Stop(f"{clone} is not a git repository")
    if git(clone, "status", "--porcelain").strip():
        raise Stop(f"{clone} has uncommitted changes")
    return git(clone, "log", "-1", "--format=%h").strip()


def import_reference(clone: Path):
    """Import agiofit from the clone, and make sure that is where it came from."""
    ref = (clone / "reference").resolve()
    sys.dont_write_bytecode = True    # the clone is read, not written
    sys.path.insert(0, str(ref))
    import agiofit
    from agiofit import match
    if Path(agiofit.__file__).resolve().parent != ref / "agiofit":
        raise Stop(f"agiofit was imported from {agiofit.__file__}, not from {ref}")
    if list(match.DISCLOSURE_LEVELS) != LEVELS:
        raise Stop(f"the reference's levels are {match.DISCLOSURE_LEVELS}, not {LEVELS}")
    return match


def count_tests(clone: Path) -> int:
    files = sorted((clone / "reference" / "tests").glob("test_*.py"))
    if not files:
        raise Stop("no test files in reference/tests")
    n = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        if "parametrize" in text:
            raise Stop(f"{f.name} uses parametrize: counting def test_ would no longer be true")
        n += len(re.findall(r"^\s*def test_", text, flags=re.M))
    return n


def sentences(report: dict) -> list:
    """The English sentences a report carries that the page shows translated."""
    out = list(report.get("caveats", [])) + list(report.get("improve_by", []))
    out += [x["note"] for x in report.get("explanation", []) if x.get("note")]
    out += [x["note"] for x in report.get("alternatives", []) if x.get("note")]
    return out


def lookup(data: dict, name: str):
    if name in ("tests", "commit"):
        return data[name]
    value = data["reports"]
    for part in name.split("/"):
        if isinstance(value, list):
            if "=" in part:
                k, v = part.split("=", 1)
                found = [x for x in value if isinstance(x, dict) and str(x.get(k)) == v]
                if not found:
                    raise Stop(f"marker {name}: no item with {part}")
                value = found[0]
            elif part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                raise Stop(f"marker {name}: no item {part}")
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise Stop(f"marker {name}: no {part} in the report")
    if isinstance(value, (dict, list)):
        raise Stop(f"marker {name} points at a structure, not a value")
    return value


def shown(value) -> str:
    return html.escape(value) if isinstance(value, str) else json.dumps(value)


def update_markers(page: str, data: dict) -> tuple:
    found = {}

    def repl(m):
        name, closing = m.group(1), m.group(3)
        if name != closing:
            raise Stop(f"marker ref:{name} is closed by /ref:{closing}")
        if name not in MARKERS:
            raise Stop(f"marker ref:{name} is not one this script knows")
        value = shown(lookup(data, name))
        found[name] = found.get(name, 0) + 1
        return f"<!-- ref:{name} -->{value}<!-- /ref:{name} -->"

    page = MARKER.sub(repl, page)
    opened = len(re.findall(r"<!-- ref:", page))
    if opened != sum(found.values()):
        raise Stop("a <!-- ref: --> marker has no matching closing marker")
    missing = [n for n in MARKERS if n not in found]
    if missing:
        raise Stop("markers missing from the page: " + ", ".join(missing))
    return page, found


def json_block(data: dict) -> str:
    body = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    return (BLOCK_START + '\n<script type="application/json" id="reference-reports">\n'
            + body + "\n</script>\n" + BLOCK_END)


def run(clone: Path, write: bool) -> int:
    commit = check_clone(clone)
    match = import_reference(clone)
    tests = count_tests(clone)

    garment = json.loads((clone / GARMENT).read_text(encoding="utf-8"))
    reports, defaults = {}, {}
    for key, path in PROFILES.items():
        profile = json.loads((clone / path).read_text(encoding="utf-8"))
        # The day the profile was last updated, not today: see the docstring.
        as_of = datetime.fromisoformat(profile["updated_at"].replace("Z", "+00:00"))
        # the reference's own rule: the profile's default_level, else result_only
        defaults[key] = (profile.get("disclosure_defaults") or {}).get("default_level") or "result_only"
        reports[key] = {}
        for level in LEVELS:
            r = match.recommend(profile, garment, level, now=as_of).to_json()
            r.pop("computed_at", None)    # changes at every run
            reports[key][level] = r

    used = sorted({s for p in reports.values() for r in p.values() for s in sentences(r)})
    untranslated = [s for s in used if s not in TRANSLATIONS]
    if untranslated:
        raise Stop("sentences without a translation:\n      " + "\n      ".join(untranslated))

    data = {
        "commit": commit,
        "tests": tests,
        "default_level": defaults,
        "reports": reports,
        # the same reports as the CLI prints them: parsed in the browser, 16.0 would show as 16
        "reports_text": {k: {lvl: json.dumps(r, indent=2, ensure_ascii=False) for lvl, r in v.items()}
                         for k, v in reports.items()},
        "translations": {s: TRANSLATIONS[s] for s in used},
    }

    with open(GUIDE, encoding="utf-8", newline="") as f:
        page = f.read()
    if page.count(BLOCK_START) != 1 or page.count(BLOCK_END) != 1:
        raise Stop(f"{GUIDE.name} must hold {BLOCK_START} and {BLOCK_END} once each")
    a = page.index(BLOCK_START)
    b = page.index(BLOCK_END) + len(BLOCK_END)
    if b < a:
        raise Stop(f"{BLOCK_END} comes before {BLOCK_START}")
    new = page[:a] + json_block(data) + page[b:]
    new, found = update_markers(new, data)

    print(f"\n  reference  {clone}  commit {commit}")
    print(f"  tests      {tests}")
    for key in PROFILES:
        row = "  ".join(f"{lvl} {r['recommended_size']} @ {r['confidence']:.2f}"
                        for lvl, r in reports[key].items())
        print(f"  {key:10} default {defaults[key]:11}  {row}")
    print(f"  sentences  {len(used)}, all translated")
    for name in MARKERS:
        print(f"  ref:{name:52} x{found[name]}  {shown(lookup(data, name))}")

    if new == page:
        print("\n  _src/guide/index.html is already up to date.\n")
        return 0
    if not write:
        print("\nDry run: nothing was touched. _src/guide/index.html would change.")
        print("To write for real:  python demo_reports.py --write\n")
        return 0
    with open(GUIDE, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    with open(GUIDE, encoding="utf-8", newline="") as f:
        if f.read() != new:
            raise Stop("the file read back is not what was written")
    print("\nWritten: _src/guide/index.html. Now run python build.py.\n")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--write"]
    clone = Path(args[0]) if args else ROOT / ".." / "agiofit"
    try:
        return run(clone.resolve(), "--write" in sys.argv)
    except Stop as e:
        print(f"\n  Nothing written: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
