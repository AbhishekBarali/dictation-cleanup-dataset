#!/usr/bin/env python3
"""Score a model against the comparison set. Never blends the two numbers.

Half the rows are no-ops where the correct answer is to return the input
untouched. A model that changes nothing at all would score 47.5% on a blended
metric and look like it half works, so a single accuracy number is worse than
no number. Everything here is reported per row class.

METRICS

  passthrough accuracy   of the rows whose correct output IS the input, how
                         often the model returned it byte for byte. Measures
                         restraint. A destructive model fails here.

  edit accuracy          of the rows that need a change, how often the model
                         produced exactly the expected output. Measures skill.

  over-edit rate         share of ALL rows the model altered at all, against
                         the true rate. Above the true rate means it is touching
                         text it should leave alone.

  content damage rate    share of rows where the model dropped a word that the
                         expected output keeps. This is the failure that shipped
                         in August 2026: whole clauses deleted around a spoken
                         "new paragraph". It is tracked separately because a row
                         can fail edit accuracy harmlessly (wrong line break)
                         or harmfully (words gone), and those are not the same
                         defect.

  near-miss              exact match after collapsing whitespace runs and
                         stripping ends. The gap between this and the strict
                         number is how much of the loss is formatting pedantry
                         rather than substance.

USAGE

  Generate outputs on the machine that has the model, one JSON object per line:

      {"id": "hid-004", "output": "...model text..."}

  Then score:

      python3 tools/score_comparison.py --outputs runs/ft-0.8b.jsonl --label "FT 0.8B"

  Compare several models side by side:

      python3 tools/score_comparison.py \\
          --outputs runs/base-0.8b.jsonl --label "Base 0.8B" \\
          --outputs runs/ft-0.8b.jsonl   --label "FT 0.8B" \\
          --outputs runs/ft-2b.jsonl     --label "FT 2B" \\
          --markdown > docs/RESULTS.md

  Do NOT cap max_tokens when generating. The set contains rows over 500 words
  and a cap silently truncates them, which hides exactly the failure mode the
  long rows exist to catch.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from classify_diff import classify  # noqa: E402

SET_PATH = ROOT / "data" / "comparison-v1.jsonl"
BOOTSTRAP = 2000
SEED = 20260825

WORD = re.compile(r"[a-z0-9']+")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def words(text: str) -> Counter:
    return Counter(WORD.findall(text.lower()))


def loose(text: str) -> str:
    """Collapse whitespace runs and strip ends. Keeps line breaks as single
    newlines so a blank-line-versus-newline mistake still counts as a miss."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.strip().splitlines())


def wilson(hits: int, n: int) -> tuple[float, float]:
    """95% Wilson interval. Honest about small n, unlike a bare percentage."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def score_one(rows: list[dict], outputs: dict[str, str]) -> dict:
    missing = [r["id"] for r in rows if r["id"] not in outputs]

    per_row = []
    for r in rows:
        out = outputs.get(r["id"])
        if out is None:
            continue
        identity = r["input"] == r["expected"]

        # Gate 1, strict. A row may carry an `accepted` list of additional valid
        # renderings, added only after a human ratified them (see docs/SCORING.md).
        # Identity rows never carry one: on those the input unchanged is the only
        # correct answer, so widening them would destroy what they measure.
        refs = [r["expected"]]
        if not identity:
            refs += [a for a in (r.get("accepted") or []) if a]
        exact = out in refs
        exact_primary = out == r["expected"]

        # Gate 2, deterministic. Why did it miss? Cheapest explanation wins.
        cls = classify(r["expected"], out)
        for alt in refs[1:]:
            if cls["cause"] == "substantive":
                alt_cls = classify(alt, out)
                if alt_cls["cause"] != "substantive":
                    cls = alt_cls
        cause = "exact" if exact else cls["cause"]
        cosmetic_miss = (not exact) and cls["cosmetic"]

        near = loose(out) == loose(r["expected"])
        changed = out != r["input"]

        # Damage: a word the speaker actually said, which the expected output
        # keeps, and the model dropped. Intersecting with the input first is
        # what separates real destruction from a merely missed correction: a
        # model that fails to fix "Vircil" into "Vercel" has not damaged
        # anything, it has just not helped. A model that eats the clause the
        # marker was attached to has.
        keep = words(r["expected"]) & words(r["input"])
        lost = keep - words(out)
        damaged = bool(lost)

        per_row.append(
            {
                "id": r["id"],
                "category": r["category"],
                "subcategory": r["subcategory"],
                "bucket": r["bucket"],
                "identity": identity,
                "exact": exact,
                "exact_primary": exact_primary,
                "accepted_hit": bool(exact and not exact_primary),
                "cause": cause,
                "cosmetic_miss": cosmetic_miss,
                "near": near,
                "changed": changed,
                "damaged": damaged,
                "lost_words": sum(lost.values()),
            }
        )

    ident = [x for x in per_row if x["identity"]]
    edit = [x for x in per_row if not x["identity"]]

    pass_hits = sum(1 for x in ident if x["exact"])
    edit_hits = sum(1 for x in edit if x["exact"])
    edit_near = sum(1 for x in edit if x["near"])
    pass_near = sum(1 for x in ident if x["near"])

    # Gate 2 tolerant tier: a cosmetic miss counts as a pass here and nowhere else.
    edit_tolerant = sum(1 for x in edit if x["exact"] or x["cosmetic_miss"])
    pass_tolerant = sum(1 for x in ident if x["exact"] or x["cosmetic_miss"])
    cause_counts = Counter(x["cause"] for x in per_row if not x["exact"])

    true_change_rate = len(edit) / len(per_row) if per_row else 0.0
    model_change_rate = sum(1 for x in per_row if x["changed"]) / len(per_row) if per_row else 0.0

    # Bootstrap the two headline rates so a reader sees the spread, not a
    # false-precision percentage off 38 rows.
    rng = random.Random(SEED)

    def boot(sample: list[dict], key: str) -> tuple[float, float]:
        if not sample:
            return (0.0, 0.0)
        means = []
        n = len(sample)
        for _ in range(BOOTSTRAP):
            means.append(sum(sample[rng.randrange(n)][key] for _ in range(n)) / n)
        means.sort()
        return (means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP)])

    return {
        "scored": len(per_row),
        "missing": missing,
        "per_row": per_row,
        "causes": dict(cause_counts),
        "tolerant": {
            "passthrough_hits": pass_tolerant,
            "passthrough_rate": pass_tolerant / len(ident) if ident else 0.0,
            "edit_hits": edit_tolerant,
            "edit_rate": edit_tolerant / len(edit) if edit else 0.0,
        },
        "accepted_hits": sum(1 for x in per_row if x["accepted_hit"]),
        "passthrough": {
            "n": len(ident),
            "hits": pass_hits,
            "rate": pass_hits / len(ident) if ident else 0.0,
            "wilson": wilson(pass_hits, len(ident)),
            "bootstrap": boot(ident, "exact"),
            "near_rate": pass_near / len(ident) if ident else 0.0,
        },
        "edit": {
            "n": len(edit),
            "hits": edit_hits,
            "rate": edit_hits / len(edit) if edit else 0.0,
            "wilson": wilson(edit_hits, len(edit)),
            "bootstrap": boot(edit, "exact"),
            "near_rate": edit_near / len(edit) if edit else 0.0,
        },
        "over_edit": {
            "true_rate": true_change_rate,
            "model_rate": model_change_rate,
            "delta": model_change_rate - true_change_rate,
        },
        "damage": {
            "n": len(per_row),
            "rows": sum(1 for x in per_row if x["damaged"]),
            "rate": sum(1 for x in per_row if x["damaged"]) / len(per_row) if per_row else 0.0,
            "total_words_lost": sum(x["lost_words"] for x in per_row),
            "worst": sorted(
                (x for x in per_row if x["damaged"]),
                key=lambda x: -x["lost_words"],
            )[:5],
        },
        "per_row": per_row,
    }


def by_group(per_row: list[dict], field: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for x in per_row:
        groups[x[field]].append(x)
    out = {}
    for name, xs in sorted(groups.items()):
        out[name] = {
            "n": len(xs),
            "exact": sum(1 for x in xs if x["exact"]),
            "damaged": sum(1 for x in xs if x["damaged"]),
        }
    return out


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def report_text(label: str, s: dict) -> str:
    p, e, o, d = s["passthrough"], s["edit"], s["over_edit"], s["damage"]
    lines = [
        f"=== {label}",
        f"  scored {s['scored']} rows" + (f", MISSING {len(s['missing'])}" if s["missing"] else ""),
        "",
        f"  passthrough accuracy   {p['hits']}/{p['n']}  {pct(p['rate'])}"
        f"   95% CI [{pct(p['wilson'][0])}, {pct(p['wilson'][1])}]",
        f"    relaxed whitespace   {pct(p['near_rate'])}",
        f"  edit accuracy          {e['hits']}/{e['n']}  {pct(e['rate'])}"
        f"   95% CI [{pct(e['wilson'][0])}, {pct(e['wilson'][1])}]",
        f"    relaxed whitespace   {pct(e['near_rate'])}",
        "",
        f"  tolerant tier (gate 2: cosmetic-only misses forgiven)",
        f"    passthrough          {s['tolerant']['passthrough_hits']}/{p['n']}"
        f"  {pct(s['tolerant']['passthrough_rate'])}",
        f"    edit                 {s['tolerant']['edit_hits']}/{e['n']}"
        f"  {pct(s['tolerant']['edit_rate'])}",
        "",
        f"  over-edit    model changed {pct(o['model_rate'])} of rows, true rate {pct(o['true_rate'])}"
        f"  ({'+' if o['delta'] >= 0 else ''}{pct(o['delta'])})",
        f"  damage       {d['rows']}/{d['n']} rows lost a word the answer keeps"
        f"  ({pct(d['rate'])}), {d['total_words_lost']} words total",
    ]
    if d["worst"]:
        lines.append("    worst rows: " + ", ".join(f"{x['id']} (-{x['lost_words']})" for x in d["worst"]))
    if s.get("accepted_hits"):
        lines.append(f"  {s['accepted_hits']} rows matched a ratified alternative answer, "
                     "not the primary reference")
    if s.get("causes"):
        lines.append("")
        lines.append("  why the misses missed:")
        for cause, n in sorted(s["causes"].items(), key=lambda kv: -kv[1]):
            lines.append(f"    {cause:24s} {n}")
        sub = s["causes"].get("substantive", 0)
        tot = sum(s["causes"].values())
        if tot:
            lines.append(f"    -> {tot - sub} of {tot} misses are formatting only. "
                         f"{sub} are real disagreements and are all a judge may see.")
    lines.append("")
    lines.append("  by length band:")
    for band, g in by_group(s["per_row"], "bucket").items():
        lines.append(f"    {band:10} {g['exact']}/{g['n']} exact, {g['damaged']} damaged")
    return "\n".join(lines)


def report_markdown(results: list[tuple[str, dict]]) -> str:
    out = ["# Comparison set results", ""]
    out.append("Set: `data/comparison-v1.jsonl`. Scored on rows no model was trained on.")
    out.append("")
    out.append("Per-run output from `tools/score_comparison.py`. For anything published,")
    out.append("use `tools/build_metrics.py` and `tools/render_results.py`: this report has")
    out.append("no overall score, no intervals on the difference between models and no")
    out.append("do-nothing baseline, all of which are needed to read the two rates below.")
    out.append("")
    out.append("The overall score published elsewhere is the unweighted mean of the two")
    out.append("accuracies. Note that plain accuracy over all rows is not: about half the")
    out.append("rows are no-ops, so a model that edits nothing scores 45.3% that way and")
    out.append("50.0% on the unweighted mean.")
    out.append("")
    out.append("| model | restraint | edit | rows altered vs true | damaged rows |")
    out.append("|---|---|---|---|---|")
    for label, s in results:
        p, e, o, d = s["passthrough"], s["edit"], s["over_edit"], s["damage"]
        out.append(
            f"| {label} | {pct(p['rate'])} ({p['hits']}/{p['n']}) "
            f"| {pct(e['rate'])} ({e['hits']}/{e['n']}) "
            f"| {pct(o['model_rate'])} vs {pct(o['true_rate'])} "
            f"| {d['rows']}/{d['n']} ({pct(d['rate'])}) |"
        )
    out.append("")
    out.append("Passthrough accuracy is restraint: leaving clean text alone. Edit accuracy")
    out.append("is skill: producing the exact expected change. Damaged rows lost a word the")
    out.append("expected answer keeps, which is the destructive failure and is worse than")
    out.append("simply missing an edit.")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outputs", action="append", required=True, type=Path,
                    help="JSONL of {id, output}; repeat for several models")
    ap.add_argument("--label", action="append", default=[],
                    help="display name per --outputs, in the same order")
    ap.add_argument("--set", dest="set_path", type=Path, default=SET_PATH)
    ap.add_argument("--markdown", action="store_true", help="emit a markdown table")
    ap.add_argument("--json", dest="as_json", action="store_true", help="emit raw json")
    ap.add_argument("--residual-out", type=Path,
                    help="write the substantive misses (gate 3 input) to this JSONL. "
                         "Only these rows may ever reach a judge.")
    args = ap.parse_args()

    rows = load_jsonl(args.set_path)
    labels = args.label + [p.stem for p in args.outputs[len(args.label):]]

    results = []
    for path, label in zip(args.outputs, labels):
        recs = load_jsonl(path)
        outputs = {r["id"]: r["output"] for r in recs}
        results.append((label, score_one(rows, outputs)))

    if args.as_json:
        print(json.dumps({lbl: {k: v for k, v in s.items() if k != "per_row"}
                          for lbl, s in results}, indent=2))
    elif args.markdown:
        print(report_markdown(results))
    else:
        for label, s in results:
            print(report_text(label, s))
            print()

    if args.residual_out:
        by_id = {r["id"]: r for r in rows}
        written = 0
        args.residual_out.parent.mkdir(parents=True, exist_ok=True)
        with args.residual_out.open("w", encoding="utf-8") as fh:
            for label, s in results:
                out_map = {}
                for path, lbl in zip(args.outputs, labels):
                    if lbl == label:
                        out_map = {r["id"]: r["output"] for r in load_jsonl(path)}
                        break
                for x in s["per_row"]:
                    if x["exact"] or x["cause"] != "substantive":
                        continue
                    fh.write(json.dumps({
                        "id": x["id"],
                        "label": label,
                        "is_identity": x["identity"],
                        "category": x["category"],
                        "subcategory": x["subcategory"],
                        "output": out_map.get(x["id"], ""),
                        "damaged": x["damaged"],
                        "lost_words": x["lost_words"],
                    }, ensure_ascii=False) + "\n")
                    written += 1
        n_noop = sum(1 for label, s in results
                     for x in s["per_row"]
                     if not x["exact"] and x["cause"] == "substantive" and x["identity"])
        print(f"\nresidual: {written} substantive misses -> {args.residual_out}",
              file=sys.stderr)
        if n_noop:
            print(f"  {n_noop} of those are no-op rows. judge.py refuses them: on a row "
                  f"whose\n  correct output is the input unchanged there is no better "
                  f"answer to find.", file=sys.stderr)

    for label, s in results:
        if s["missing"]:
            print(f"warning: {label} missing {len(s['missing'])} rows: "
                  f"{', '.join(s['missing'][:6])}", file=sys.stderr)


if __name__ == "__main__":
    main()
