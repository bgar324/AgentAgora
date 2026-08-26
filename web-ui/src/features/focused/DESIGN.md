# Focused Panel design system

Premium-minimal (Linear-grade): one typeface, near-monochrome neutrals,
hairline borders, compact controls, restrained semantic color. Hierarchy
comes from weight, size, and the gray ramp — never uppercase, never
decoration.

## Information architecture

Persistent header: brand · step trail (Search, Perspectives, Panel) ·
demo badge · Start over · one primary Continue or Add to panel action.

Surfaces:
- Start — centered 440px form (Problem, Research questions, Demo, Begin)
- Extraction — left rail (brief and question-linked queries), right clusters,
  matrix below.
  Every Perspective exposes Scope, Explanation, Approach, and Significance,
  each grounded in an abstract sentence.
  Complete SPECTER embeddings are grouped with lightweight UMAP/HDBSCAN; the
  existing deterministic K-means path remains the fallback. Each cluster uses
  five central-plus-DPP representatives for naming and grounded facet
  extraction. Density noise and papers without embeddings remain explicit
  under Unassigned literature, where every abstract stays inspectable.
  Retrieval is breadth-preserving: answer-bearing papers rank first,
  problem-angle papers second, and remaining question candidates third. The
  corpus targets 90 papers, expands with at most four gap queries when
  underfilled, and remains capped at 200. A corpus with at least 15 embedded
  papers requests at least three Perspective-eligible clusters; a density
  result below three falls back to deterministic three-way clustering.
  Submitted and automatically expanded queries remain visible as a read-only
  record beside the resulting clusters. During retrieval, the right cluster
  panel centers a connected timeline. Only the active query has a spinner.
  After the last query, the rows collapse into a Searched papers disclosure.
  Opening the disclosure shows every query count and the result total before
  duplicate papers were removed. A line connects that frozen stage to Creating
  Perspectives. When both stages finish, one summary line stays above the
  cluster cards.
  Wrapped research-question lines are joined through their closing question
  mark. A zero-result search stays retryable and never seals the Investigation.
  Adding a Perspective inserts a pending matrix card immediately. Its own card
  and button show progress while other clusters remain addable. Every cluster
  editor renders all four hypothesis areas, including a blank editor when the
  server omits an area. The server response replaces the pending card and
  creates its matching canvas agent. A failed request removes only that card.
  Continue opens the canvas directly with every matrix Perspective. There is no
  separate panel-selection step. Before round 1, the researcher chooses a lead
  Perspective and generates its baseline hypothesis.
- Panel — React Flow canvas (nodes/wires/dot grid) + guided drawer:
  while open, the canvas shows the Research Problem, Perspective agents, and
  panel. Adding a Perspective archives the current panel cycle and starts a new
  deliberation with no rounds, chat, questions, or working hypothesis. The new
  Perspective always participates; the researcher chooses which existing
  Perspectives to invite. Archived rounds and hypotheses remain inspectable.
  Each round examines exactly one area, and the same lead opens every exchange.
  A round runs up to three exchanges. After each complete exchange, the
  moderator proposes concrete shared ground and every Perspective accepts,
  qualifies, or rejects it. Unanimous acceptance ends the loop; otherwise the
  third exchange returns the disagreement or unsettled boundary without forcing
  consensus. The drawer reports each stage, groups agent turns by exchange, and
  shows every moderator check. Researchers can ask a question before or between
  rounds. A question submitted during a round waits until that round finishes.
  Each final moderator summary follows its exchanges. Shared ground shows
  explicit Before and accented Proposed values for every changed hypothesis
  part. The researcher selects which proposed parts to apply; unselected parts
  retain the current text. Saving creates an immutable checkpoint. Review and
  end becomes available after any completed round with a saved hypothesis.
  Selected open questions become Research Problem nodes; unselected questions
  remain in panel history. Confirm and end closes the round, chat, and edit
  lifecycle, then opens the deliberation-level divergent and convergent scoring
  dialog.
  Selected open questions expose Start paper search in the drawer and on their
  Research Problem node. Unselected open questions remain available in history.
  A Research Problem opens a temporary literature branch. Back to panel returns
  to the parent without changing the branch. After the current parent
  deliberation ends, Add to panel imports the branch’s evidence and Perspectives
  into a fresh deliberation. Imported Perspectives always participate; existing
  Perspectives are optional invitations. The prior panel cycle, score, and final
  outputs remain in history.
  Representative papers appear first in every cluster. The researcher can
  expand the remaining cluster library and inspect every paper in the
  Perspective. Perspectives imported from a Research Problem branch render
  beneath that Research Problem; they never attach to the root problem. Saved
  Hypothesis nodes use the restrained green success surface.

Overlays: modals (add Perspective, Perspective detail, apply changes,
hypothesis, scoring, reset) share ModalShell; the 1180px/96vw panel drawer is
the only side sheet.
The header exposes one Investigation map action when research branches exist.
It does not expose a second Investigation picker.


IA rules:
- One primary action per surface; it advances the flow.
- Identity and status at a glance; prose one click away.
- Metadata (counts, states) are quiet labels, never sentences.
- Start over remains a quiet secondary header action; the flow has one primary action.
- Every list row has exactly one affordance, visible without hover.
- A Perspective's name is its speaker identity; never expose ordinal
  agent labels such as A1 or A2.
- Start creates a new Investigation and is the intentional reset target.
  The Brief may be edited inline until its first paper search; after that
  evidence boundary is fixed and changing it requires a new Investigation.
- Question-specific retrieval records both answering papers and misses and
  runs only the queries the researcher selected.
- Model-supplied source IDs, abstract indices, citations, and moderator
  evidence references are validated before they become user-visible provenance.
- A completed Investigation's literature cannot be replaced in place. New
  searches begin from a Research Problem node and preserve the parent canvas.

## Tokens (app/focused/layout.tsx)

Neutrals: --bg #fafafa · --panel #fff · --ink #101828 · --ink-2 #475467 ·
--mute #98a2b3 · --line 8% · --line-strong 16% · --hover #f5f5f5.
Inverted surface: --node #101828, captions on it --on-node #b6bfcc,
accent on it --on-node-accent #7cc5ab.
Semantic: --green #067647 (+bg) consensus/success · --amber #b54708
(+bg) unsettled/highlight · --red #d92d20 disagreement/error/destructive.
Wires: --wire #d0d5dd. Perspective identity colors arrive from data
(PERSONA_COLORS) and are the only free color in the UI.

Radius: 6 inputs inside rows · 8 default (cards, buttons, fields) ·
12 modals. Shadows: cards none (borders only); modals
--shadow-modal 0 20px 50px rgba(16,24,40,.16).

Type: Inter only. Scale (px) — 11 micro/meta, 12 labels/body-sm,
13 body/default, 14 emphasis, 16 modal titles, 22 hero. No other sizes.
Weights: 400 body · 500 buttons/labels/emphasis · 600 titles. No 700+.
Tracking -0.01em on 13px+ headings.

Controls: h-7 sm / h-8 md; text 12 sm / 13 md; icon 13px lucide.
Motion: 120ms micro-interactions; 180–260ms entry using opacity and
at most 8px translation. Lists stagger 36–45ms; drawers travel 18px.
Every entry class resolves instantly under `prefers-reduced-motion`.

## Components (features/focused/ui.tsx)

Button(variant primary|outline|ghost|danger, size sm|md) — primary is --node
fill; ghost transparent, hover --hover; outline hairline + hover bg; danger
red-tinted outline for destructive actions (reject/discard).
Spinner. ModalShell(title, onClose): 640px/92vw, 48px minimum header,
12px vertical padding, 16px 600 title. SectionLabel: 12px 500 mute.
EmptyLine: 13px mute.
EvidenceHighlight(label): amber evidence mark with a portal tooltip on hover
and keyboard focus.
IdentityChip(color, name, selected?, lead?) — person icon + colored name,
or a tilted crown when lead; selected
fills --node with white text. ListRow(disabled?, onClick) — hover bg +
border affordance. CheckRow(checked, onToggle) — 13px checklist row.

## Content rules

Sentence case, never uppercase labels. No arrows, no emojis, plain language;
prefer "panel" in explanatory copy. The terminal actions are "Review and end"
and "Confirm and end." Empty states are one actionable line. Buttons say what
they do, such as Generate search queries, Add Perspective, Start round, Apply
shared ground, Apply selected parts, Review and end, and Confirm and end.
Busy = spinner inside the triggering button.
Visible labels start with a capital letter. Internal agent and paper IDs
never render; use the Perspective name and complete, wrapping
bibliographic title. Sources remain visible as dotted, clickable title
links. Computed cosine-distance metrics are exported for analysis but never
shown to participants; scoring reflects the completed deliberation as a whole.
