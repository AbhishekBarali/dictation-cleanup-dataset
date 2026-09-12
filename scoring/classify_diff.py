"""Classify why an output missed its reference, deterministically.

Gate 2 of the scoring pipeline. Every failure from exact match lands here first,
and most of them leave with an explanation that cost nothing to compute.

The point is to answer "is exact match too strict?" with a number instead of an
argument. If 30 of 40 misses differ only in whitespace, that is a fact about the
metric, not a fact about the models, and a reader can see it.

Only what this cannot explain goes on to a judge. That keeps the expensive,
biased step off the rows that never needed it.

Categories, checked in this order, first match wins:

  exact               byte identical, not a miss at all
  whitespace          identical after collapsing runs of spaces and tabs
  line_break          identical after collapsing all newlines to single spaces
  terminal_punct      identical after stripping .,;: from the end of every line
  bullet_glyph        identical after normalising leading -, *, and bullet chars
  list_number         identical after normalising "1." / "1)" list markers
  case                identical after lowercasing
  quote_style         identical after straightening curly quotes and apostrophes
  substantive         none of the above; a real disagreement

A row can differ in more than one way. `all_causes` lists every category that
would explain it on its own; `cause` is the first, which is the one to report.
A row whose only causes are cosmetic is a formatting miss. A row that reaches
`substantive` is where the interesting question lives.

Standard library only. No network, no model.
"""

from __future__ import annotations

import re
import unicodedata

BULLET_CHARS = "-*\u2022\u2023\u25e6\u2043\u2219"
CURLY = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2032": "'", "\u2033": '"',
}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def n_whitespace(s: str) -> str:
    """Collapse runs of spaces and tabs, strip each line, drop blank lines."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def n_line_break(s: str) -> str:
    """Every newline becomes a single space. Layout differences vanish."""
    return re.sub(r"\s+", " ", s).strip()


def n_terminal_punct(s: str) -> str:
    """Strip sentence-final punctuation from the end of every line."""
    lines = [re.sub(r"[.,;:!?]+$", "", ln.rstrip()) for ln in s.split("\n")]
    return "\n".join(lines)


def n_bullet_glyph(s: str) -> str:
    """Any leading bullet character becomes a single canonical marker."""
    pat = re.compile(rf"^\s*[{re.escape(BULLET_CHARS)}]\s+")
    lines = [pat.sub("- ", ln) for ln in s.split("\n")]
    return "\n".join(lines)


def n_list_number(s: str) -> str:
    """Normalise numbered list markers: '1.', '1)', '(1)' all become '1.'."""
    pat = re.compile(r"^\s*\(?(\d+)[.)]\s+")
    lines = [pat.sub(lambda m: f"{m.group(1)}. ", ln) for ln in s.split("\n")]
    return "\n".join(lines)


def n_case(s: str) -> str:
    return s.lower()


def n_quote_style(s: str) -> str:
    out = s
    for a, b in CURLY.items():
        out = out.replace(a, b)
    return out


# Order matters: the cheapest and least interesting explanations are tried first,
# so `cause` reports the mildest difference that accounts for the miss.
NORMALISERS: list[tuple[str, callable]] = [
    ("whitespace", n_whitespace),
    ("line_break", n_line_break),
    ("terminal_punct", n_terminal_punct),
    ("bullet_glyph", n_bullet_glyph),
    ("list_number", n_list_number),
    ("case", n_case),
    ("quote_style", n_quote_style),
]

COSMETIC = {name for name, _ in NORMALISERS}


def classify(expected: str, got: str) -> dict:
    """Return {cause, all_causes, cosmetic} for one output against its reference."""
    exp, out = _nfc(expected), _nfc(got)
    if exp == out:
        return {"cause": "exact", "all_causes": [], "cosmetic": True}

    causes: list[str] = []
    for name, fn in NORMALISERS:
        try:
            if fn(exp) == fn(out):
                causes.append(name)
        except Exception:  # a normaliser must never decide a score by crashing
            continue

    # Composed normalisers: whitespace plus one other is still cosmetic, and this
    # is common, because a model that changes a bullet character usually changes
    # the spacing around it too.
    if not causes:
        for name, fn in NORMALISERS:
            if name == "whitespace":
                continue
            try:
                if n_whitespace(fn(exp)) == n_whitespace(fn(out)):
                    causes.append(f"whitespace+{name}")
            except Exception:
                continue

    if not causes:
        return {"cause": "substantive", "all_causes": [], "cosmetic": False}
    return {"cause": causes[0], "all_causes": causes, "cosmetic": True}


def word_loss(expected: str, got: str) -> list[str]:
    """Words the reference keeps that the output dropped. Case-insensitive.

    This is the damage signal and it is deliberately separate from the cause
    categories: losing a word the speaker said is a different kind of failure
    from rendering a bullet differently, and blending them would hide it.
    """
    from collections import Counter
    e = Counter(re.findall(r"\w+", expected.lower()))
    g = Counter(re.findall(r"\w+", got.lower()))
    missing = e - g
    return sorted(missing.elements())


if __name__ == "__main__":
    cases = [
        ("- milk\n- bread", "* milk\n* bread", "bullet_glyph"),
        ("a b c", "a  b   c", "whitespace"),
        ("one.\ntwo.", "one. two.", "line_break"),
        ("1. a\n2. b", "1) a\n2) b", "list_number"),
        ("Sign off.", "sign off.", "case"),
        ("say 'no'", "say \u2018no\u2019", "quote_style"),
        ("- a\n- b", "- a\n- b", "exact"),
        ("the quote was nine thousand", "the quote was eleven thousand", "substantive"),
    ]
    bad = 0
    for exp, got, want in cases:
        res = classify(exp, got)
        ok = res["cause"] == want
        bad += not ok
        print(f"{'ok ' if ok else 'FAIL'} {want:16s} got {res['cause']}")
    print("word_loss check:", word_loss("keep the whole clause", "keep the clause"))
    raise SystemExit(1 if bad else 0)
