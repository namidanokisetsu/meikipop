# LLM lookup experiments

Evaluated 2026-10-14.

**Decision: LLM use is unjustified in the dictionary lookup pipeline.** Do not
add generated contextual explanations, gloss rewriting/aggregation, or LLM
reranking. Preserve dictionary content and deterministic presentation. Ranking
showed measurable gains, but those gains do not justify unreliable choices,
extra latency, GPU memory and runtime complexity here. This decision concerns
lookup enrichment; the existing explicit translation feature is separate.

## Configuration and scope

All local runs used Qwen3.5-4B Q4_K_M on an RTX 5070 12 GB, Ryzen 9700X and
32 GB RAM, through the existing llama.cpp b11146 runtime with full GPU offload,
temperature 0 and seed 42. Only 4B inference was tested; the partial 9B download
was removed without running it. No application integration was made.

The model download was 2.74 GB. Loaded GPU memory increased by about 3.1 GiB
with an 8,192-token context and 3.34 GiB with the ranking run's 16,384-token
context. Server startup took about 2 seconds with possible OS file caching.
Timings below measure complete local HTTP answers with a loaded model and no
prompt-cache reuse. They exclude OCR, dictionary lookup, UI rendering and
gaming/concurrent workload. These were individual timed trials, not repeated
load tests.

## Contextual selection and generated output

The first experiments used 32 hand-authored Turkish/Japanese cases, then 12
fresh cases after a prompt revision. Outputs combined supplied sense IDs,
ambiguity/error status, compact contextual meaning and grammar. Eight original
cases also received actual installed dictionary content and Turkish analyses;
these retained the controlled candidate choices. Four length tests repeated
dictionary material. Eight sentence-only diagnostics removed the supplied
candidates. There were 172 requests including warmups and output-format checks.

| Condition | Cases | Median answer time | Exact sense-ID/status matches |
| --- | ---: | ---: | ---: |
| Original prompt, thinking off | 32 | 0.54 s | 24/32 |
| Original plus installed-library evidence | 8 | 0.81 s | 7/8 |
| 512-token reasoning budget | 32 | 4.27 s | 25/32 |
| Reasoning plus installed-library evidence | 8 | 4.43 s | 8/8 |
| Revised prompt, original cases | 32 | 0.53 s | 21/32 |
| Revised prompt, fresh cases | 12 | 0.52 s | 11/12 |
| Revised plus installed-library evidence | 8 | 0.78 s | 7/8 |
| Repeated dictionary material, about 4K/7K input tokens | 4 | 1.09/1.62 s by size | 3/4 |
| Sentence-only diagnostics | 8 | 0.66 s | Not comparable |

These match counts do not score generated prose. Even matching selections
produced wrong meanings: Turkish negative `kazma` became "Dig" despite a
correct negative-imperative label, and Japanese passive/potential constructions
were confused. Other failures included invented grammar, forced resolution of
ambiguity, unauthorized OCR repair and plausible English linked to the wrong
supplied sense. Sentence-only prompts retained major negation/voice errors.
Limited reasoning cost roughly eight times as much for one extra original-set
match; unrestricted reasoning was not tested.

All 148 schema-constrained requests satisfied the basic JSON schema. Each
original/reasoning prompt-only batch had a field-type failure among eight
requests; the revised batch fixed types but still broke brevity and semantic
requirements. Two simple dictionary-text injection probes did not trigger the
injected output. None of these format checks established linguistic reliability.
Synthetic long inputs measured processing cost, not comprehension of thousands
of distinct competing facts.

Separately, the user reported a disastrous explanation of the Turkish
"Haydar Haydar" verses, including number, vocabulary and religious-context
errors. That report motivated restricting scope; it was not a controlled local
benchmark and is not included in the scores above.

## Ranking actual Meikipop results

The final experiment used actual search results and expanded renderer order
for 56 sentences: the earlier 44 plus 12 new contextual pairs. Relevant IDs
were labeled before inference. Ten cases had missing/uncertain meanings or
partial target matches and were excluded from the main score. Single-candidate
cases were also excluded from each ranking comparison.

The model received sentence context, target, readings, inflections, morphology
and dictionary definitions. It could promote up to three existing IDs and
leave all other candidates in their original order; it could not rewrite text.
Entry ranking and gloss-block ranking were separate alternatives. All 176
non-warmup requests, including reversed-input checks, returned valid JSON.

| Task | Relevant item first, current → LLM | Rank improved / unchanged / worsened | Median / p95 delay |
| --- | ---: | ---: | ---: |
| Whole entries | 20/35 → 31/35 | 13 / 20 / 2 | 0.22 / 0.57 s |
| Individual gloss blocks | 24/44 → 40/44 | 18 / 25 / 1 | 0.27 / 0.92 s |

The longest request took 1.13 seconds; the largest prompt was 6,196 tokens.
Context capacity was sufficient for these inputs. Turkish swimming `yüz`
improved from gloss #10 to #1, and Japanese frog `かえる` from #9 to #1.
However, entry ranking displaced correct readings for opening a book and a
request not to open a window. When the bread-roll meaning of `açma` was absent,
gloss ranking promoted "to break one's fast" instead of abstaining.

Reversing candidate input order reduced correct first choices to 26/35 entries
and 33/44 glosses. Seven previously correct entry choices and nine correct
gloss choices became wrong; two wrong choices improved in each task. The
current order already placed a relevant entry in the first three in 33/35
cases, or a relevant gloss in 39/44. No reading-time savings were measured.
Flat gloss promotion is a hypothetical presentation; the current popup groups
entries and does not independently move glosses across them.

These small, deliberately ambiguous sets were manually judged without
independent native-speaker review. Some gloss blocks bundle multiple senses.
The results establish neither production accuracy nor failure of every small
model. For this project, the observed gains do not justify the reliability
and integration costs. Formatting remains ordinary application code;
missing dictionary coverage needs dictionary/pipeline improvements.

## Retained evidence

Raw artifacts remain outside Git under
`%LOCALAPPDATA%\meikipop-llm-experiment\2026-10-14\`. The root `report.html`,
`summary.json`, `review_notes.json`, `results_*.jsonl`, fixtures, frozen labels,
`requests/` and runner scripts preserve the original conditions and outputs.
The `ranking/` subdirectory contains its own report, summary, per-case CSV,
actual lookup inputs, frozen labels, requests, outputs and scripts. Historical
reports retain their earlier tentative recommendations; the decision above
supersedes those recommendations. Runners use local absolute paths and append
results, so archive old outputs before any explicitly requested rerun.

Model provenance is recorded in `models.json`: `unsloth/Qwen3.5-4B-GGUF`,
revision `e87f176479d0855a907a41277aca2f8ee7a09523`, file
`Qwen3.5-4B-Q4_K_M.gguf`, SHA256
`00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4`.
Weights, generated reports and raw outputs stay outside the repository.
