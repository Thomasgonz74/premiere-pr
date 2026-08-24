"""WCAG contrast-ratio check for the high-contrast ("hc") variant of every
web-UI theme under resources/web/spike/themes/.

Historical note: an older audit report proposed this check against
resources/styles/*_hc.qss (the native Qt/QSS UI). That UI is gone -- the app
is now a QWebEngineView rendering resources/web/spike/*.html/css/js, and the
*_hc.qss files are stale (kept on disk only because an unrelated packaging
test asserts one is present in the frozen bundle). This test reads the real
runtime tokens instead: each theme's tokens.css defines a `:root { ... }`
block (defaults) and a `[data-theme="hc"] { ... }` block (high-contrast
overrides) of plain `--name: value;` custom properties -- no nested
selectors, per the file convention these themes already follow. The
effective hc value for a variable is the hc override if present, else the
root value (CSS custom-property inheritance).

Pairs tested are the ones resources/web/spike/style.css actually paints
together, not guesses:
  * body text:      color: var(--text-primary)   on  background: var(--surface-window)
                     (e.g. .context-menu / .context-menu-item, .tabbar / .tab-btn)
  * selection:       color: var(--selection-text) on  background: var(--selection-bg)
                     (#downloadsList .row.selected, .context-menu-item:hover)
  * title bar:       color: var(--title-active-text) on background: var(--gradient-title-active)
                     (.titlebar / .titlebar-title)

--text-primary/--surface-window/--selection-bg/--selection-text/
--title-active-text are defined by name in all 34 themes and always resolve
to a single solid color (verified: no theme defines any of them as a
gradient). --gradient-title-active is NOT that simple: about half the themes
alias it straight to a flat `linear-gradient(var(--X), var(--X))` (one
solid color), but several themes (macOS stripes, art-deco's sunburst overlay,
win7 Aero glass, ...) genuinely paint a multi-color pattern there, and a
few themes never override .titlebar's background from the plain-color
default at all -- there is no single second title-bar-background variable
name that is consistent across all 34 themes (only win95_classic actually
defines --title-active-bg; the rest use 33 different theme-local names in
their own structural CSS, which is exactly the "named differently" case the
task called out to skip rather than mis-pair). So: this test resolves
--gradient-title-active per theme and only scores the title-bar pair when
that resolves to exactly one literal color; when it resolves to more than
one (a real gradient/stripe pattern) or none, the pair is skipped for that
theme and printed as a SKIP note instead of silently mis-pairing colors.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
THEMES_DIR = REPO_ROOT / "resources" / "web" / "spike" / "themes"

AAA_MIN_RATIO = 7.0

# (human label, text variable, background variable, backdrop variable) --
# the background variable is itself just a var name; --gradient-title-active
# happens to be one that doesn't always resolve to a single color (see
# module docstring). The backdrop variable is what the background paints
# *on top of* in the real DOM, needed only when the background turns out to
# be a translucent rgba() -- e.g. #downloadsList's rows live inside
# `.listbox { background: var(--surface-field) }`, so a translucent
# --selection-bg alpha-blends with --surface-field, not with black.
PAIRS = [
    ("body text on window background", "text-primary", "surface-window", None),
    ("selected-row text on selection background", "selection-text", "selection-bg", "surface-field"),
    ("title-bar text on title-bar background", "title-active-text", "gradient-title-active", None),
]

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_VAR_DECL_RE = re.compile(r"--([\w-]+)\s*:\s*(.+)", re.S)
_HEX_RE = re.compile(r"#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{3})\b")
_RGB_RE = re.compile(
    r"rgba?\(\s*([\d.]+%?)\s*,\s*([\d.]+%?)\s*,\s*([\d.]+%?)\s*(?:,\s*([\d.]+%?)\s*)?\)"
)


def _extract_block(css: str, selector_re: str) -> str | None:
    """Return the raw content of the first `<selector> { ... }` block, using
    balanced-brace matching (values here never contain nested braces)."""
    m = re.search(selector_re + r"\s*\{", css)
    if not m:
        return None
    start = m.end()
    depth = 1
    i = start
    while i < len(css) and depth > 0:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
        i += 1
    return css[start : i - 1]


def _parse_vars(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for decl in block.split(";"):
        decl = decl.strip()
        if not decl:
            continue
        m = _VAR_DECL_RE.match(decl)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _load_theme_vars(tokens_css_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (root_vars, hc_vars) parsed from a theme's tokens.css."""
    css = _COMMENT_RE.sub("", tokens_css_path.read_text(encoding="utf-8"))
    root_block = _extract_block(css, r":root")
    hc_block = _extract_block(css, r'\[data-theme=["\']hc["\']\]')
    root_vars = _parse_vars(root_block) if root_block else {}
    hc_vars = _parse_vars(hc_block) if hc_block else {}
    return root_vars, hc_vars


def _resolve(name: str, root_vars: dict[str, str], hc_vars: dict[str, str],
             depth: int = 0, seen: frozenset[str] = frozenset()) -> str | None:
    """Fully expand the effective (hc-overridden-else-root) value of `name`,
    substituting every var(--x[, fallback]) reference it contains, recursively."""
    raw = hc_vars.get(name, root_vars.get(name))
    if raw is None:
        return None
    return _resolve_value(raw, root_vars, hc_vars, depth, seen | {name})


def _resolve_value(value: str, root_vars: dict[str, str], hc_vars: dict[str, str],
                    depth: int, seen: frozenset[str]) -> str:
    if depth > 25:
        return value
    out = []
    i = 0
    n = len(value)
    while True:
        idx = value.find("var(", i)
        if idx == -1:
            out.append(value[i:])
            break
        out.append(value[i:idx])
        paren_depth = 1
        j = idx + 4
        while j < n and paren_depth > 0:
            if value[j] == "(":
                paren_depth += 1
            elif value[j] == ")":
                paren_depth -= 1
            j += 1
        inner = value[idx + 4 : j - 1]
        name_part, _, fallback_part = inner.partition(",")
        name_part = name_part.strip()
        var_name = name_part[2:] if name_part.startswith("--") else name_part
        if var_name in seen:
            replacement = ""  # cycle guard
        else:
            resolved = _resolve(var_name, root_vars, hc_vars, depth + 1, seen)
            replacement = resolved if resolved is not None else _resolve_value(
                fallback_part.strip(), root_vars, hc_vars, depth + 1, seen
            )
        out.append(replacement)
        i = j
    return "".join(out)


def _extract_colors(expanded: str) -> list[tuple[int, int, int, float]]:
    """Return every literal color found as (r, g, b, alpha) -- alpha is 1.0
    unless the source used rgba()/#RGBA/#RRGGBBAA with a real alpha channel."""
    colors: list[tuple[int, int, int, float]] = []
    for m in _RGB_RE.finditer(expanded):
        def chan(g: str) -> int:
            return round(float(g[:-1]) / 100 * 255) if g.endswith("%") else round(float(g))
        r, g, b = (chan(x) for x in m.groups()[:3])
        a_raw = m.group(4)
        alpha = 1.0 if a_raw is None else (
            float(a_raw[:-1]) / 100 if a_raw.endswith("%") else float(a_raw)
        )
        colors.append((r, g, b, round(alpha, 4)))
    for m in _HEX_RE.finditer(expanded):
        h = m.group(0)[1:]
        alpha = 1.0
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        elif len(h) == 4:
            alpha = round(int(h[3] * 2, 16) / 255, 4)
            h = "".join(c * 2 for c in h[:3])
        elif len(h) == 8:
            alpha = round(int(h[6:8], 16) / 255, 4)
            h = h[:6]
        colors.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha))
    return colors


def _single_rgba(expanded: str) -> tuple[tuple[int, int, int, float] | None, set]:
    """If `expanded` contains exactly one distinct literal color, return it
    (plus the raw set, for diagnostics); otherwise (None, set-of-whatever-was-found)."""
    colors = set(_extract_colors(expanded))
    if len(colors) == 1:
        return next(iter(colors)), colors
    return None, colors


def _composite(fg_rgba: tuple[int, int, int, float], backdrop_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Alpha-blend a translucent foreground color over an opaque backdrop
    (standard "source-over" compositing)."""
    r, g, b, a = fg_rgba
    br, bgc, bb = backdrop_rgb
    return (
        round(a * r + (1 - a) * br),
        round(a * g + (1 - a) * bgc),
        round(a * b + (1 - a) * bb),
    )


def _srgb_channel_to_linear(c: int) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_channel_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    l1, l2 = _relative_luminance(rgb1), _relative_luminance(rgb2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _theme_dirs() -> list[Path]:
    return sorted(p for p in THEMES_DIR.iterdir() if (p / "tokens.css").is_file())


def test_theme_dirs_found():
    # Sanity check the enumeration itself isn't silently empty.
    assert len(_theme_dirs()) == 34


def test_hc_contrast_meets_aaa():
    failures: list[str] = []
    skips: list[str] = []

    for theme_dir in _theme_dirs():
        theme_id = theme_dir.name
        root_vars, hc_vars = _load_theme_vars(theme_dir / "tokens.css")

        for label, text_name, bg_name, backdrop_name in PAIRS:
            text_expanded = _resolve(text_name, root_vars, hc_vars)
            bg_expanded = _resolve(bg_name, root_vars, hc_vars)
            if text_expanded is None or bg_expanded is None:
                skips.append(f"{theme_id}: {label} -- variable not defined in this theme")
                continue

            bg_rgba, bg_all = _single_rgba(bg_expanded)
            if bg_rgba is None:
                skips.append(
                    f"{theme_id}: {label} -- background does not resolve to a single solid "
                    f"color (found {sorted(bg_all)!r}); likely a multi-stop gradient/stripe pattern"
                )
                continue

            if bg_rgba[3] >= 0.999:
                bg_rgb = bg_rgba[:3]
            elif backdrop_name is None:
                skips.append(
                    f"{theme_id}: {label} -- background is translucent ({bg_rgba}) and this "
                    "pair has no defined backdrop to composite it against"
                )
                continue
            else:
                backdrop_expanded = _resolve(backdrop_name, root_vars, hc_vars)
                backdrop_rgba, backdrop_all = (
                    _single_rgba(backdrop_expanded) if backdrop_expanded is not None else (None, set())
                )
                if backdrop_rgba is None or backdrop_rgba[3] < 0.999:
                    skips.append(
                        f"{theme_id}: {label} -- background is translucent ({bg_rgba}) but its "
                        f"backdrop (--{backdrop_name}) isn't a single opaque color "
                        f"(found {sorted(backdrop_all)!r}), can't composite"
                    )
                    continue
                bg_rgb = _composite(bg_rgba, backdrop_rgba[:3])

            text_rgba, text_all = _single_rgba(text_expanded)
            if text_rgba is None:
                skips.append(
                    f"{theme_id}: {label} -- text does not resolve to a single solid color "
                    f"(found {sorted(text_all)!r})"
                )
                continue
            text_rgb = text_rgba[:3] if text_rgba[3] >= 0.999 else _composite(text_rgba, bg_rgb)

            ratio = _contrast_ratio(text_rgb, bg_rgb)
            if ratio < AAA_MIN_RATIO:
                failures.append(
                    f"{theme_id}: {label} -- {ratio:.2f}:1 "
                    f"(text {text_rgb} on bg {bg_rgb}, need >= {AAA_MIN_RATIO}:1)"
                )

    if skips:
        print(f"\n{len(skips)} pair(s) skipped (not a single-solid-color pairing):")
        for s in skips:
            print(f"  SKIP: {s}")

    assert not failures, (
        f"{len(failures)} theme/pair combination(s) fall short of WCAG AAA (7:1) "
        "in high-contrast mode:\n" + "\n".join(f"  - {f}" for f in failures)
    )
