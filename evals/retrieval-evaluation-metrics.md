# Retrieval evaluation methodology

The decision-grade evaluator compares Youngseung and Kat on separate dimensions. It does not produce a composite winner score.

The current protocol version is `fair-v2`.

## Evaluation flow

For each case and repeat, the harness:

1. Runs both pipelines serially with Semantic Scholar response caching disabled and DSPy response caching disabled.
2. Records every executed query and the first paper IDs returned for that query.
3. Pools the papers from both pipelines and judges each unique paper once.
4. Forms up to three Perspectives from the three largest delivered clusters for each pipeline.
5. Judges Perspective text quality without showing evidence.
6. Judges grounding separately against five normalized evidence abstracts.
7. Calculates coverage, relevance-retention, balanced-clustering, query-outcome, repeatability, and operating metrics.
8. Writes an embedding-complete `*.raw.json` resume artifact and a compact review report.

The runner alternates pipeline order between repeats. It refuses an acceptance run that records a cached model response, any cached input tokens, or no live input tokens. OpenAI implicit prompt caching is disabled with `prompt_cache_options.mode = explicit`.

## Blinding and pooled judgments

The judge never receives pipeline names or raw cluster IDs. It receives opaque aliases such as `D01`, `V01`, and `S01`.

Paper judgments are pooled by case and repeat. If both pipelines retrieve the same paper, Sol judges that paper once and both runs receive the same score.

The artifact records:

- Judge model
- Rubric version
- A digest of the exact judge packets
- Judge model usage

The runner rejects `--append` unless the embedding-complete raw sidecar exists and uses the same cache and rubric protocol.

## Relevance metrics

GPT-5.6 Sol grades every pooled paper on this ordinal scale:

| Grade | Meaning | Numeric gain |
|---:|---|---:|
| 0 | Off-topic | 0.00 |
| 1 | Background or method only | 0.25 |
| 2 | Related mechanism, construct, or measure | 0.50 |
| 3 | Directly addresses a research question | 0.75 |
| 4 | Directly answers the stated relationship | 1.00 |

### Retrieved-corpus relevance

`relevance_mean` is the mean gain across every retrieved paper.

This value describes corpus purity. It is not admissible as a cross-pipeline comparison when retrieved corpus sizes differ by more than 2×. Kat retrieves about 1,000 papers while Youngseung usually retrieves fewer than 200, so the decision report must not use this metric as a headline comparison.

### Delivered relevance

A paper is delivered when it belongs to one of the three clusters used to form Perspectives.

The evaluator reports:

- `matched_delivered_relevance_mean`: mean judged gain over an equal, deterministic sample of up to 60 delivered papers per pipeline
- `delivered_relevance_mean`: mean judged gain among all delivered papers; inadmissible as a quality comparison when delivered counts differ by more than 10%
- `relevant_papers_delivered`: sum of judged gains among delivered papers
- `retained_relevance_recall`: delivered relevant gain divided by total retrieved relevant gain
- `filter_lift`: delivered mean relevance divided by retrieved-corpus mean relevance
- `discarded_papers`: retrieved papers not delivered to a Perspective cluster

Use delivered relevant evidence and retained relevance together. Volume alone rewards broad retrieval. Retention alone rewards a tiny selective corpus.

### Human gold labels

`gold_recall` uses human-labeled relevant paper IDs when available. The current decision can proceed without those labels, but every LLM-judged relevance metric remains `provisional` until a human pool is complete.

Create a pipeline-blind, fixed-depth TREC-style annotation pool with:

```bash
PYTHONPATH=src .venv/bin/python scripts/export_retrieval_gold_pool.py \
  --results evals/results/<case>.raw.json \
  --output evals/gold/<case>.csv \
  --depth-per-run 60
```

A human assigns grades 0–4. Apply a complete pool with:

```bash
.venv/bin/python scripts/apply_retrieval_gold_labels.py \
  --labels evals/gold/<case>.csv \
  --map evals/gold/<case>.map.json \
  --output evals/retrieval_cases_labeled.json
```

The importer preserves labels for cases outside the current pool.

## Perspective metrics

Both pipelines submit the same production-stage artifact: a formed Perspective, not a cluster card.

Each run judges at most three Perspectives selected from the three largest delivered clusters. A missing Perspective occupies a slot and lowers `perspective_coverage`; it does not disappear from the denominator.

### Perspective quality

The quality packet contains no evidence. Sol scores each Perspective for:

- Coherence
- Relevance to the research problem
- Specificity

`perspective_quality` is the mean of those three dimensions across the three expected slots. The judge does not reward verbosity or citation count.

### Perspective grounding

Grounding uses a separate packet. Each Perspective receives up to five abstracts chosen by one rule for both pipelines:

1. Papers the Perspective cites
2. Cluster representatives
3. Remaining cluster members

Sol scores whether substantive claims follow from at least one supplied abstract. It does not reward the number or length of abstracts.

The evaluator also reports `evidence_coverage`, the fraction of Perspective slots that declare at least one source. Evidence coverage stays separate from the judged grounding score.

### Perspective distinctness

Sol scores every within-set Perspective pair. `perspective_distinctness` is the mean pairwise score, which avoids comparing one holistic score across different set sizes.

## Query metrics

The query ledger records every executed search, including discovery searches and relaxed fallbacks. Duplicate query text remains visible in `executed_queries`; `unique_queries` reports its normalized deduplicated count.

### Retrieval-intent diversity

For each executed query, let $R_q$ be the first 20 distinct returned paper IDs. The primary deterministic query-diversity metric is:

$$
\operatorname{mean}_{i<j}\left(1-\frac{|R_i\cap R_j|}{|R_i\cup R_j|}\right)
$$

This measures diversity in retrieved outcomes. It gives the same score to terse Semantic Scholar keywords and verbose prose that retrieve the same papers.

`corpus_expansion` is:

$$
\frac{|\bigcup_q R_q|}{\sum_q |R_q|}
$$

The blinded judge also reports `query_intent_diversity` and `query_research_coverage`. Its prompt explicitly ignores grammar, verbosity, and keyword-versus-prose form.

The old token-Jaccard `query_diversity` remains only as a `provisional` diagnostic because it rewards padding and removal of useful shared anchor terms.

## Clustering metrics

### Assigned fraction

`assigned_fraction` is delivered papers divided by retrieved papers. Every retrieved paper must be assigned to exactly one delivered cluster or explicitly marked unassigned.

### Raw silhouette

`silhouette` uses cosine distance over all assigned papers. It is marked `inadmissible` when pipeline coverage differs by more than 10%, because discarding most papers can manufacture a cleaner core.

### Balanced silhouette

`balanced_silhouette` selects the same number of largest clusters and the same number of embedded papers per cluster for both pipelines. Papers are sampled by a deterministic hash, not by centroid proximity, so larger clusters do not contribute only their tightest core.

The report includes the matched cluster count and papers-per-cluster count. The metric is `inadmissible` when either pipeline lacks enough embedded clusters.

### Representative metrics

Raw representative metrics remain diagnostic when representative counts differ. Comparable variants use five representatives per cluster:

- `representative_centrality_at_5`: cosine similarity to the cluster centroid
- `representative_diversity_at_5`: mean pairwise cosine distance among representatives

### Evidence-size conformance

`evidence_size_conformance` is the fraction of clusters with 20–100 papers. It is an `inadmissible` quality metric and remains only as a product conformance check. It must not support a pipeline-quality verdict.

## Stability metrics

For independent repeats from the same case, the evaluator reports:

- `corpus_stability`: Jaccard overlap of retrieved paper IDs
- `assigned_stability`: Jaccard overlap of delivered paper IDs
- `cluster_stability`: adjusted Rand index over papers assigned in both repeats
- `cluster_stability_support`: number of overlapping assigned papers behind ARI

Cluster stability is `inadmissible` when:

- A repeat used a replayed response
- Fewer than 30 assigned papers overlap
- Overlap is less than 25% of the smaller delivered set

A perfect score from a replayed cache is never reported as stability.

## Operational metrics

`latency_s` covers pipeline query generation, retrieval, assessment, clustering, and Perspective formation. It excludes blinded judging.

Latency is admissible only when all contributing runs use the same cold cache protocol and record no cached model calls.

`model_cost_usd` is inadmissible when provider-priced cost is missing for either pipeline. Token counts remain reportable even when priced cost is unavailable.

`peak_rss_mb` is `null` until the live adapter records it. Import-memory measurements in `evals/results/import_rss.json` are separate and must not be presented as full-run peak memory.

## Machine-readable comparability

Every compact comparison contains a `comparability` map. Each metric has one status:

- `comparable`: admissible for a cross-pipeline claim
- `provisional`: reportable with a stated limitation
- `inadmissible`: do not force or compare the number

The final decision table must include only `comparable` metrics. It may include `provisional` relevance values only when it marks the missing-human-label limitation directly. It must not use `inadmissible` values to support the verdict.
