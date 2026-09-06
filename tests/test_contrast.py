"""Contrast, computed from the tokens rather than eyeballed.

axe found 39 failing nodes on the landing page alone, all from one token used for every hint,
caption and sample-size chip in the interface. A ratio is arithmetic, so it belongs in a test
where it fails before a person sees it, not in a review where someone squints at a screenshot.

The pairs here are the ones the interface actually renders: each ink token against each surface it
appears on. WCAG AA wants 4.5:1 for body text and 3:1 for large text and for the edges of shapes,
so text tokens are held to the higher bar and mark tokens to the lower one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "web" / "app" / "globals.css"

BODY_TEXT_MIN = 4.5
MARK_MIN = 3.0


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def tokens() -> dict[str, dict[str, str]]:
    """The light and dark palettes, read from the stylesheet that ships.

    Parsed rather than duplicated: a copy of the values in this file would drift from the ones the
    browser uses, and then the test would be checking a palette nobody sees.
    """
    css = CSS.read_text()
    # Both palettes list the same token names, and the light one comes first. So the first time a
    # name repeats, everything after it belongs to the dark theme.
    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    seen_dark = False
    for name, value in re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6})", css):
        target = dark if seen_dark else light
        if name in target and target is light:
            seen_dark = True
            target = dark
        target[name] = value
    assert light and dark, "could not read both palettes from globals.css"
    return {"light": light, "dark": dark}


SURFACES = ("--bg", "--bg-raised", "--bg-sunken")
TEXT_TOKENS = ("--ink", "--ink-secondary", "--ink-muted", "--warn-ink", "--teal-ink")


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("text", TEXT_TOKENS)
@pytest.mark.parametrize("surface", SURFACES)
def test_text_is_legible_on_every_surface_it_appears_on(mode: str, text: str, surface: str) -> None:
    palette = tokens()[mode]
    if text not in palette or surface not in palette:
        pytest.skip(f"{text} is not defined in the {mode} palette")
    ratio = contrast(palette[text], palette[surface])
    assert ratio >= BODY_TEXT_MIN, (
        f"{mode}: {text} ({palette[text]}) on {surface} ({palette[surface]}) is {ratio:.2f}:1, "
        f"below the {BODY_TEXT_MIN}:1 AA needs for body text"
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_the_mark_colour_clears_the_bar_for_a_shape(mode: str) -> None:
    """`--sand` carries borders and fills, where 3:1 is the standard.

    It is deliberately not held to the text bar: it failed that at 3.48:1 and the fix was to stop
    using it for text, not to darken a colour chosen to look right as a mark. `--warn-ink` is the
    text half of that pair, and the test above holds it to 4.5.
    """
    palette = tokens()[mode]
    for surface in SURFACES:
        ratio = contrast(palette["--sand"], palette[surface])
        assert ratio >= MARK_MIN, f"{mode}: --sand on {surface} is {ratio:.2f}:1"


def test_the_two_halves_of_the_warning_pair_are_both_defined() -> None:
    """A mark colour and its text counterpart, in both themes.

    Kept separate even where they coincide, so darkening one for legibility cannot silently
    change what a chart looks like.
    """
    for mode in ("light", "dark"):
        palette = tokens()[mode]
        assert "--sand" in palette, f"{mode} has no mark colour"
        assert "--warn-ink" in palette, f"{mode} has no text colour for warnings"
