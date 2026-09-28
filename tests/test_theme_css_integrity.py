"""Static integrity checks of the web-UI stylesheets (no Qt, no browser).

Guards against the failure that silently disabled whole dark modes: a
comment closed early by a stray "*/" (e.g. a glob such as "--bz-*/--accent"
written inside a comment). The rest of the sentence is then parsed as CSS and
swallows the next rule -- in kde-plasma and windows-8 the entire
[data-theme="dark"] block was dropped, and the browser reports nothing.

Checks every resources/web/spike/*.css and every theme tokens.css the way a
browser tokenizes them: comments and strings are blanked first, then
  * no comment is left open, no "*/" appears outside a comment,
  * braces balance,
  * no line outside comments reads like prose (the tell of an early close);
and every theme defines, in :root, the three tokens style.css cannot do
without: --text-primary, --surface-window, --border-control; a theme
opting into its own tooltip sets --t2k-tooltip-bg/-fg together. Finally, the
themes theme_switcher.js declares without a dark mode are exactly those whose
tokens.css has no [data-theme="dark"] rule.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SPIKE = Path(__file__).resolve().parents[1] / "resources" / "web" / "spike"
SHARED_CSS = sorted(SPIKE.glob("*.css"))
THEME_CSS = sorted(SPIKE.glob("themes/*/tokens.css"))
REQUIRED_ROOT_TOKENS = ("--text-primary", "--surface-window", "--border-control")


def blank_comments_and_strings(src: str) -> tuple[str, list[str]]:
    """Returns the CSS with comments and strings replaced by spaces (newlines
    kept, so line numbers survive) plus the problems met while doing it."""
    problems: list[str] = []
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                problems.append(f"line {src.count(chr(10), 0, i) + 1}: comment never closed")
                break
            out.append(re.sub(r"[^\n]", " ", src[i:j + 2]))
            i = j + 2
        elif src[i] in "\"'":
            quote, j = src[i], i + 1
            while j < n and src[j] not in (quote, "\n"):
                j += 2 if src[j] == "\\" else 1
            out.append(" " * (j + 1 - i))
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out), problems


def css_problems(src: str) -> list[str]:
    css, problems = blank_comments_and_strings(src)
    depth = 0
    for k, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                problems.append(f"line {css.count(chr(10), 0, k) + 1}: unexpected closing brace")
                depth = 0
    if depth:
        problems.append(f"{depth} unclosed brace(s) at end of file")
    for m in re.finditer(r"\*/", css):
        problems.append(f"line {css.count(chr(10), 0, m.start()) + 1}: stray */ outside any comment (a comment was closed early)")
    for ln, line in enumerate(css.split("\n"), 1):
        s = line.strip()
        if not s or ":" in s or "{" in s or s.endswith(",") or s == "}":
            continue
        if re.search(r"[A-Za-zÀ-ÿ]{3,} [a-zà-ÿ]{2,} [a-zà-ÿ]{2,}", s):
            problems.append(f"line {ln}: text outside comments reads like prose: {s[:70]!r}")
    return problems


def root_declarations(src: str) -> dict[str, str]:
    """Custom properties declared in top-level `:root { }` blocks."""
    css, _ = blank_comments_and_strings(src)
    decls: dict[str, str] = {}
    for m in re.finditer(r"(?:^|[}\s]):root\s*\{([^{}]*)\}", css):
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]*);", m.group(1)):
            decls[name] = value.strip()
    return decls


def test_checker_flags_an_early_closed_comment():
    # The kde-plasma bug, verbatim in shape: the glob closes the comment.
    bad = '/* primitives --bz-*/--accent are re-resolved here, no need to repeat them. */\n[data-theme="dark"] { --x: 1; }\n'
    assert any("stray */" in p for p in css_problems(bad))
    assert css_problems('/* fine */\n:root { --x: 1; }\n') == []


@pytest.mark.parametrize("path", SHARED_CSS + THEME_CSS, ids=lambda p: str(p.relative_to(SPIKE)))
def test_stylesheet_parses_like_the_author_meant(path: Path):
    problems = css_problems(path.read_text(encoding="utf-8"))
    assert not problems, f"{path.relative_to(SPIKE)}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("path", THEME_CSS, ids=lambda p: p.parent.name)
def test_theme_defines_required_root_tokens(path: Path):
    decls = root_declarations(path.read_text(encoding="utf-8"))
    missing = [t for t in REQUIRED_ROOT_TOKENS if not decls.get(t)]
    assert not missing, f"{path.parent.name}: :root lacks {missing}"


def has_dark_block(src: str) -> bool:
    """A rule for [data-theme="dark"] outside comments (a :not() does not count).
    Blanking keeps every offset, so the blanked-out string is read back from src."""
    css, _ = blank_comments_and_strings(src)
    return any(
        re.match(r"""["']?dark["']?\]""", src[m.end():]) and not css[:m.start()].endswith(":not(")
        for m in re.finditer(r"\[data-theme=", css)
    )


def test_dark_block_detection():
    assert has_dark_block(':root { --x: 1; }\n[data-theme="dark"] { --x: 2; }\n')
    assert not has_dark_block('/* no [data-theme="dark"] block */\n[data-theme="hc"] { --x: 2; }\n')
    assert not has_dark_block(':root:not([data-theme="dark"]) .row { color: red; }\n')


def test_themes_without_dark_mode_match_their_css():
    # theme_switcher.js hides "Sombre" and applies "dark" as light for these:
    # a theme gaining or losing its dark block must update that list too.
    js = (SPIKE / "theme_switcher.js").read_text(encoding="utf-8")
    declared = set(re.findall(r'"([\w-]+)"', re.search(r"THEMES_WITHOUT_DARK_MODE = new Set\(\[(.*?)\]\)", js, re.S).group(1)))
    actual = {p.parent.name for p in THEME_CSS if not has_dark_block(p.read_text(encoding="utf-8"))}
    assert declared == actual, f"declared without dark: {sorted(declared)}, CSS without dark: {sorted(actual)}"


@pytest.mark.parametrize("path", THEME_CSS, ids=lambda p: p.parent.name)
def test_theme_tooltip_opt_in_sets_the_pair_together(path: Path):
    """style.css falls back per property: a block setting only one of the
    pair would put the theme's tooltip ink on the window surface, or the
    reverse -- the unreadable mix style.css's comment warns about."""
    css, _ = blank_comments_and_strings(path.read_text(encoding="utf-8"))
    for block in re.findall(r"\{([^{}]*)\}", css):
        has_bg, has_fg = "--t2k-tooltip-bg" in block, "--t2k-tooltip-fg" in block
        assert has_bg == has_fg, f"{path.parent.name}: a block sets only one of --t2k-tooltip-bg/-fg"
