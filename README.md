# Dictation cleanup dataset

Input/output pairs for **post-ASR dictation cleanup**: turning a raw speech
transcript into the text the speaker actually meant to type.

This is not grammar or punctuation correction. Modern recognisers already handle
those. The task here is speaker *intent*: retractions, redirections,
clarifications that modify earlier text, spoken formatting requests, and knowing
when to change nothing at all.

## Three files

| file | rows | what it is |
|---|---|---|
| `train-3337.jsonl` | 3,337 | the training corpus |
| `heldout-374.jsonl` | 374 | held-out evaluation suite |
| `benchmark-123.jsonl` | 123 | the benchmark subset, a subset of the held-out suite |

The benchmark rows are drawn from the held-out suite, so `benchmark-123` and
`heldout-374` overlap by design and share `hid-` identifiers. The training corpus
is disjoint from both.

**Read this before you use the evaluation files.** They were a *held-out* suite,
which is a property of not being public. Publishing them ends that: any model
trained after this release may have seen them, so a strong score on these rows
from a recent model is not evidence of generalisation. They remain useful for
scoring models that predate this release, for reproducing the numbers in the
accompanying paper, and as a specification of what the task actually asks for.
If you need a clean held-out split, build one.

```json
{"id": "sf-02008",
 "category": "wrong_word_right_transcription",
 "input":  "The container is HLXU 4839210. No, 4839211.",
 "output": "The container is HLXU 4839211."}
```

```json
{"id": "sf-00006",
 "category": "spoken_symbol",
 "input":  "Send it to a.author at example dot com and copy the design channel.",
 "output": "Send it to a.author@example.com and copy the design channel."}
```

The training file names its target `output`; the two evaluation files name theirs
`expected`. That difference is inherited from the tooling and is not meaningful.

## The most important thing about this dataset

**1,535 of 3,337 training rows (46%) have `output` identical to `input`.** The
evaluation files are built the same way: 184 of 374, and 51 of 123.

That is deliberate and it is the point. A cleanup model that edits everything it
is shown is useless, because most dictation arrives already correct. Nearly half
this corpus exists to teach a model to leave text alone. If you train on it and
drop the no-op rows, you will build a model that damages correct text, and the
loss curve will look fine while it happens.

## Fields

The training file and the two evaluation files do not share a schema. The training file
names its target `output`; the evaluation files name it `expected` and carry two extra
fields the scorer reads.

`train-3337.jsonl`:

| field | meaning |
|---|---|
| `id` | stable row identifier |
| `input` | the raw transcript as a recogniser produced it |
| `output` | the text the speaker meant, per the cleanup specification |
| `category` | phenomenon class, see below |
| `subcategory` | finer split within the category |
| `mode` | intended cleanup mode (`default` for nearly all rows) |
| `length` | rough length band |
| `persona` | one of 46 speaker personas, so a model does not overfit one voice |
| `input_source` | `authored` for every released row, see Provenance |

`heldout-374.jsonl` and `benchmark-123.jsonl`:

| field | meaning |
|---|---|
| `id` | stable row identifier |
| `input` | the raw transcript as a recogniser produced it |
| `expected` | the text the speaker meant, per the cleanup specification |
| `category` | phenomenon class, see below |
| `subcategory` | finer split within the category |
| `provenance` | `authored` for every released row, see Provenance |
| `bucket` | input length band: `under_50`, `50_199`, `200_499`, `500_plus`, `800_plus` |
| `mode`, `persona` | present in `heldout-374.jsonl` only |

A row is a no-op when `input` and `expected` are byte-identical. That is 51 of the 123
benchmark rows and 184 of the 374 held-out rows.

## Checking the numbers

`SCORING.md` documents how to reproduce every score, and `scoring/` plus
`model-outputs/` contain the grader and the per-row outputs of eight systems on both
evaluation files. The scores you get from those files will not equal the tables in the
paper, because the paper computes over the full 150 and 402 rows including the withheld
ones. `SCORING.md` prints the exact figures the released subsets produce.

## Categories

| category | rows | what it tests |
|---|---|---|
| `no_op` | 1071 | already correct; must be returned unchanged |
| `retraction` | 316 | speaker takes something back mid-sentence |
| `wrong_word_right_transcription` | 308 | recogniser heard correctly, speaker misspoke |
| `spoken_command` | 306 | spoken instruction that is content, not a command to obey |
| `format_intent` | 235 | structure implied by speech flow |
| `dictated_question` | 186 | a question being dictated, not asked of the system |
| `instruction_as_text` | 162 | instruction-shaped text that must survive verbatim |
| `spoken_symbol` | 150 | "at", "dot com", "new line" and similar |
| `disfluency_artifact` | 142 | filler and repair residue |
| `speaker_grammar` | 121 | speaker's own grammar, preserved not corrected |
| `clarification` | 117 | later speech that modifies earlier text |
| `empty_or_noise` | 71 | nothing usable was said |
| `truncated_input` | 52 | recording cut mid-utterance |
| `hallucination_loop` | 50 | recogniser repetition artefacts |
| `language_preserved` | 50 | non-English content that must not be translated |

One rule worth stating explicitly, because it is the one people get wrong:
**a spoken formatting request is content.** If a speaker says "make that a
bulleted list", that phrase is part of what they dictated. The model must neither
obey it nor delete it. Structure is inferred from natural enumeration in the
speech flow, never from an explicit command.

## Provenance

Every released row is `authored`: hand-written by one person, one row at a time.
No row was produced by a language model.

Hand-written does not mean invented. The rows are **reconstructions of phenomena
observed in real dictation**. No public speech corpus fits this task, because the
large ones are read speech and read speech contains almost none of the
retractions and self-corrections that appear when someone dictates to a computer
and expects the result to be typed. Around eight users of a dictation application
supplied their locally saved transcript history, each asked beforehand to delete
anything they did not want shared, and the author contributed several hundred
sessions of his own use. No audio was ever collected. Identifying content was
removed, and each row was then written by hand to preserve the recognition
failure and the speaker's repair while rewriting the content that carried them.

The consequence, stated plainly: these rows carry the *phenomena* of real
dictation without being a *distributional sample* of it. The distance between the
two is not measured, and you should not assume it is small.

## What is withheld, and why

**56 rows are held back across the three files, and they are all the same kind of
row.** Every row in this corpus is either `authored` (hand-written reconstruction)
or `real_asr` (verbatim recogniser output from a session). Only the `authored`
rows are released:

| file | released | withheld |
|---|---|---|
| `train-3337.jsonl` | 3,337 authored | 1 real_asr |
| `heldout-374.jsonl` | 374 authored | 28 real_asr |
| `benchmark-123.jsonl` | 123 authored | 27 real_asr |

The `real_asr` rows are the only ones carrying verbatim session text rather than a
reconstruction, which makes them both the rows that could contain participant
speech and the rows containing personal content belonging to the author. They are
withheld for both reasons. The benchmark and held-out withheld sets overlap, since
one is a subset of the other.

The practical consequence for anyone reproducing the accompanying paper's numbers:
those numbers were computed over the full sets including the `real_asr` rows, so
scores computed on these released files will differ. The released rows are the
majority in every case and the phenomenon coverage is unchanged, but the figures
are not expected to match to the decimal.

Personal email addresses belonging to the author, and one real institutional
address that survived de-identification, were replaced with `example` placeholders.
Internal authoring fields (review notes, correction scaffolding, gate and track
markers) were dropped rather than published, since they were review material and
not part of the data.

Names appearing in rows are either fictional or, in a handful of name-spelling
test cases, the author's own. Those are kept: the point of those rows is a real
name being mis-recognised, and a fictional substitute would not exercise it.

## Known limitations

- **English only.** The `language_preserved` rows contain other languages, but
  only to test that they survive untouched.
- **Text to text.** Inputs are transcripts, so recognition errors are out of
  scope. A model that cleans text well may still fail on audio.
- **One annotator.** Every `output` reflects one person's reading of the cleanup
  specification. There is no second annotator and no inter-annotator agreement
  figure. This is the dataset's main weakness and it is not mitigated.
- **Reconstructed, not sampled.** See Provenance.
- Filler removal ("um", "uh") in the source application is done by a regex layer
  before a model ever sees the text, so inputs here may differ from what a bare
  recogniser emits.

## Licence

CC BY 4.0. Attribution required. See `LICENSE`.

## Citation

```bibtex
@misc{barali2026dictationcleanup,
  title  = {Dictation Cleanup Dataset},
  author = {Abhishek Barali},
  year   = {2026},
  note   = {3,337 authored input/output pairs for post-ASR dictation cleanup}
}
```
