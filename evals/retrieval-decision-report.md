# Retrieval pipeline decision

## Verdict

Use Youngseung's two-round, question-aware retrieval as the production retrieval stage. Replace its current position/K-means clustering stage with a lightweight Kat-style SPECTER + HDBSCAN + DPP stage. Keep the focused app's grounded Perspective model and add a deterministic facet fallback so every selected cluster can form a Perspective.

Do not import Kat's complete BERTopic/DSPy pipeline into the focused production process. The measured import footprint is about 819 MB for Kat versus 170 MB for the focused hybrid adapter, and full-run peak RSS is not available.

This hybrid is justified as a component-level production decision, not as a directly measured end-to-end winner. Youngseung won matched relevance in four of five cases. Kat won balanced clustering in all five cases. The evaluation did not run the composed hybrid itself.

## Decision-grade protocol

The comparison used five research domains and two independent repeats per domain:

- Human-AI decision transparency
- Antibiotic treatment and resistance
- Educational chatbots
- AI writing diversity
- Automated-driving explanations

This produced 20 pipeline runs: 5 cases × 2 repeats × 2 pipelines.

All runs used:

- Semantic Scholar response cache off
- DSPy response cache off
- OpenAI implicit prompt caching disabled with `prompt_cache_options.mode = explicit`
- Unique pipeline and judge cache scopes
- Zero cached response calls
- Zero cached input tokens
- Pooled paper judgments
- Opaque pipeline-neutral aliases
- Text-only Perspective quality judging
- Separate grounding against normalized evidence abstracts
- Hash-balanced clustering samples

The strict aggregate is `evals/results/final_decision_comparison.json`. Embedding-complete source runs are the corresponding `*_strict_cold_comparison.raw.json` files.

## Concise comparison

| Metric | Youngseung | Kat | Status | Result |
|---|---:|---:|---|---|
| Matched delivered relevance | **0.629** | 0.570 | Provisional: no human gold labels | Youngseung |
| Judged relevant evidence delivered | 41.8 | **171.0** | Provisional: no human gold labels | Kat volume |
| Retrieved relevant evidence retained | **92.9%** | 31.0% | Provisional: no human gold labels | Youngseung |
| Balanced silhouette | 0.090 | **0.200** | Comparable | Kat |
| Representative centrality at 5 | 0.967 | **0.973** | Comparable | Kat, small difference |
| Representative diversity at 5 | **0.061** | 0.053 | Comparable | Youngseung, small difference |
| Query-intent diversity | 0.868 | **0.879** | Comparable | Effectively tied |
| Retrieval-outcome diversity | **0.992** | 0.960 | Comparable | Youngseung |
| Cold pipeline latency | 253 s | **232 s** | Comparable | Kat by 8% |

The raw retrieved-corpus relevance mean, raw delivered-relevance mean, raw silhouette, Perspective scores, cluster-size conformance, cluster stability, provider-priced cost, and full-run memory are not admissible cross-pipeline metrics in this result. The artifact records the exact reason for each exclusion.

## Retrieval verdict

Youngseung is the better relevance filter.

- Its matched delivered relevance was 0.629 versus Kat's 0.570.
- It won matched relevance in four of five domains.
- It retained 92.9% of its judged relevant evidence versus Kat's 31.0%.
- Its retrieval outcomes were more diverse: 0.992 versus 0.960.

Kat retrieves a much larger corpus and therefore delivers about 4.1× more total judged relevant evidence. That volume does not mean its evidence is more relevant at a matched review budget. Kat discards roughly 70% of the judged relevant mass it retrieves when it keeps only three clusters.

The relevance verdict remains provisional because there are no human gold labels. The blind annotation workflow is available in `scripts/export_retrieval_gold_pool.py` and `scripts/apply_retrieval_gold_labels.py`.

## Clustering verdict

Kat is the clear clustering winner.

- Balanced silhouette was 0.200 versus Youngseung's 0.090.
- Kat won balanced silhouette in all five domains.
- Kat's representatives were slightly more central at the matched five-paper budget.
- Youngseung's representatives were slightly more diverse.

The 20–100 paper target is only a product conformance check. It did not influence this verdict.

## Perspective verdict

A global Perspective-quality comparison is inadmissible because Youngseung formed only 28 of 30 expected Perspectives. Kat formed all 30.

Kat's complete formation record is operationally stronger. The normalized numeric quality and grounding means remain in the artifact, but they do not support a cross-pipeline winner because missing Youngseung outputs break parity.

Production should retain the focused app's typed, evidence-grounded Perspective object. It should add a deterministic abstract-grounded facet fallback before Perspective formation rather than importing Kat's DSPy profile layer.

## Stability verdict

The partition-stability comparison is inadmissible because Youngseung did not have enough overlapping assigned papers across repeats.

Descriptive evidence still favors Kat's repeatability:

- Corpus overlap: Kat 0.377, Youngseung 0.077
- Assigned-set overlap: Kat 0.114, Youngseung 0.073
- Kat ARI on eligible overlapping subsets: 0.986 with mean support of 76 papers

Do not quote the ARI as a clean head-to-head win. Youngseung's insufficient repeat overlap is itself a production risk.

## Latency and memory verdict

Cold pipeline latency was comparable. Kat averaged 232 seconds and Youngseung 253 seconds. Kat was about 8% faster.

Full-run peak RSS was not recorded, so the evaluation cannot make a decision-grade runtime-memory claim. The separate import probe measured approximately:

- Focused hybrid adapter: 170 MB
- Kat adapter: 819 MB

That 4.8× import difference is strong enough to reject importing Kat's complete pipeline into the focused Railway process, but it is not a substitute for full-run peak RSS.

Provider-priced cost is also inadmissible because the direct OpenAI path does not emit a comparable dollar amount. Model calls and tokens remain recorded.

## Hybrid assessment

A Youngseung-retrieval → Kat-clustering hybrid is justified directionally:

- Youngseung contributes higher matched relevance, high relevant-evidence retention, and a smaller dependency footprint.
- Kat contributes consistently better cluster separation, complete three-Perspective delivery, and stronger repeatability.

The evidence does not justify copying the whole Kat stack. Kat's advantage is concentrated in SPECTER-based density clustering and representative selection. Its broad 1,000-paper retrieval and top-three-cluster truncation are responsible for both its evidence volume and its low relevance retention.

## Smallest recommended production pipeline

1. Keep Youngseung's current two-round retrieval and Luna paper assessment.
2. Keep the existing 200-paper global cap and question-answer priority.
3. Cluster retained SPECTER embeddings with HDBSCAN.
4. If HDBSCAN cannot produce three usable clusters, fall back to the existing deterministic K-means path.
5. Select five representatives per cluster with the existing Kat central-plus-DPP strategy, extracted without BERTopic or DSPy production imports.
6. Keep every retrieved paper explicitly assigned or unassigned and expose both groups in the UI.
7. Form three focused Perspectives with the existing typed, grounded model.
8. Fill any invalid or missing facet from deterministic abstract sentences before Perspective formation.

This is the smallest design that follows the evidence without preserving two full pipelines or importing Kat's high-memory orchestration stack.


## Implemented production pipeline

The production focused path keeps Youngseung's two-round retrieval, but Luna
assessment now ranks rather than deletes question candidates. Answer-bearing
papers rank first, problem-angle papers second, and remaining question
candidates third. The corpus targets 90 papers, can issue four gap-filling
queries, and remains capped at 200.

The retained corpus runs through lightweight UMAP/HDBSCAN over SPECTER
embeddings. It selects three central and two DPP-diverse representatives per
cluster without importing BERTopic or DSPy into the focused process. Corpora
with at least 15 embedded papers request at least three clusters. If density
clustering cannot produce three usable groups, deterministic K-means provides
the three-way fallback.

HDBSCAN noise and papers without embeddings are stored as explicit unassigned
paper IDs. The Extraction UI exposes those papers under **Unassigned
literature**, including the existing abstract-evidence dialog. Invalid or
missing model facets fall back to exact abstract sentences before Perspective
formation.