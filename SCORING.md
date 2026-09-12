# Scoring: how to check the numbers yourself

This directory ships the two things you need to reproduce a score rather than take one
on trust: what each system actually produced on every row, and the program that grades
it.

```
scoring/score_comparison.py     the grader
scoring/classify_diff.py        helper it imports
model-outputs/benchmark-123/    8 systems x 123 rows
model-outputs/heldout-374/      8 systems x 374 rows
```

Each output file is one JSON object per line, `{"id": ..., "output": ...}`, holding the
text that system returned for that row and nothing else.

## Run it

```bash
python3 scoring/score_comparison.py --set benchmark-123.jsonl \
  --outputs model-outputs/benchmark-123/flow-ft.jsonl   --label "SpeakoFlow Mini" \
  --outputs model-outputs/benchmark-123/qwen35-9b.jsonl --label "Qwen3.5-9B"
```

Add `--markdown` for a table, `--json` for raw numbers, and one `--outputs`/`--label`
pair per system you want compared. Python 3.9 or newer, no dependencies to install.

Swap `--set heldout-374.jsonl` and the matching `model-outputs/heldout-374/` directory
to score the larger suite.

## What is measured

Two rates, kept apart and never blended:

- **restraint**: of the rows whose correct output *is* the input, how often the system
  returned it unchanged.
- **edit accuracy**: of the rows that need a change, how often the system produced
  exactly the expected output.

A system that returns every input untouched scores 100 on the first and 0 on the second.
That is the point of reporting them separately: a single blended accuracy would let
doing nothing look like half-competence.

The grader also prints rows altered against the true rate, a content-damage count (rows
where a word the answer keeps went missing), a breakdown of whether misses were
substantive or only formatting, and a split by input length band.

## Expected output

Run the commands above and you should get exactly these numbers. If you do not, please
open an issue, because that is a bug worth knowing about.

### benchmark-123

| model | restraint | edit | rows altered vs true | damaged rows |
|---|---|---|---|---|
| flow-ft | 92.2% (47/51) | 54.2% (39/72) | 51.2% vs 58.5% | 13/123 (10.6%) |
| gemma4-e2b | 86.3% (44/51) | 12.5% (9/72) | 24.4% vs 58.5% | 14/123 (11.4%) |
| qwen35-08b-base | 88.2% (45/51) | 4.2% (3/72) | 10.6% vs 58.5% | 7/123 (5.7%) |
| qwen35-9b | 92.2% (47/51) | 23.6% (17/72) | 35.8% vs 58.5% | 11/123 (8.9%) |
| s1-mini-ours | 11.8% (6/51) | 2.8% (2/72) | 92.7% vs 58.5% | 76/123 (61.8%) |
| s1-mini-own | 11.8% (6/51) | 8.3% (6/72) | 93.5% vs 58.5% | 77/123 (62.6%) |
| sotto-lfm25-ours | 3.9% (2/51) | 4.2% (3/72) | 90.2% vs 58.5% | 81/123 (65.9%) |
| sotto-lfm25-own | 2.0% (1/51) | 1.4% (1/72) | 88.6% vs 58.5% | 86/123 (69.9%) |

### heldout-374

| model | restraint | edit | rows altered vs true | damaged rows |
|---|---|---|---|---|
| flow-ft | 89.1% (164/184) | 47.4% (90/190) | 47.9% vs 50.8% | 36/374 (9.6%) |
| gemma4-e2b | 88.6% (163/184) | 11.1% (21/190) | 21.4% vs 50.8% | 21/374 (5.6%) |
| qwen35-08b-base | 86.4% (159/184) | 4.2% (8/190) | 12.6% vs 50.8% | 26/374 (7.0%) |
| qwen35-9b | 87.0% (160/184) | 25.3% (48/190) | 36.9% vs 50.8% | 28/374 (7.5%) |
| s1-mini-ours | 14.7% (27/184) | 5.3% (10/190) | 90.9% vs 50.8% | 203/374 (54.3%) |
| s1-mini-own | 24.5% (45/184) | 7.9% (15/190) | 84.0% vs 50.8% | 197/374 (52.7%) |
| sotto-lfm25-ours | 9.8% (18/184) | 5.3% (10/190) | 89.6% vs 50.8% | 269/374 (71.9%) |
| sotto-lfm25-own | 12.0% (22/184) | 3.2% (6/190) | 87.4% vs 50.8% | 262/374 (70.1%) |

`-ours` and `-own` distinguish two prompts for the same system: the shared prompt used
across all systems, and that system's own documented prompt format.

## These numbers do not match the paper, and here is why

The published sets are subsets. 27 of the 150 benchmark rows and 28 of the 402 held-out
rows carry verbatim speech-recogniser output rather than a hand-written reconstruction,
and those are the only rows that could contain a participant's own speech, so they are
withheld. Every figure in the paper is computed over the full 150 and 402; every figure
above is computed over the 123 and 374 that are public.

The two are close but not identical, and neither is more correct than the other. They
answer slightly different questions on slightly different row sets. If you are checking
whether the grading is sound, use the numbers above, because those are the ones you can
reproduce. If you are reading the paper, its tables are the full-set figures and it says
so.

## What is not here

- The 55 withheld rows, and any system's output on them.
- Training code and model weights for the fine-tuned systems.
- One system in the paper's main table, a hosted frontier model, has no per-row outputs
  at all. They were lost before this release and it is a closed model, so they cannot be
  regenerated. That row is not in this directory and the paper flags it as its
  weakest-evidenced result.

## Licence

The corpus is CC BY 4.0, as stated in `LICENSE`. The two scripts under `scoring/` are
released for the purpose of checking these results.
