# Focused Panel design system

Premium-minimal (Linear-grade): one typeface, near-monochrome neutrals,
hairline borders, compact controls, restrained semantic color. Hierarchy
comes from weight, size, and the gray ramp — never uppercase, never
decoration.

## Information architecture

Persistent header: brand · step trail (Search, Perspectives, Panel) ·
demo badge · split Continue button (label | divider | chevron menu:
Export session, Start over).

Surfaces:
- Start — centered 440px form (Problem, Research questions, Demo, Begin)
- Extraction — left rail (brief and question-linked queries), right clusters,
  matrix below.
  Every Perspective exposes Scope, Explanation, Approach, and Significance,
  each grounded in an abstract sentence.
  Adding a Perspective inserts a pending matrix card immediately. The server
  response replaces the card; a failed request removes it.
- Panel — React Flow canvas (nodes/wires/dot grid) + guided drawer:
  each completed round stays visible as a Deliberation Result node. Its
  process-first summary precedes the transcript. Shared ground proposes an
  inspectable before/after update to the four-step working hypothesis.
  Applying changes the working hypothesis; saving creates an immutable
  Hypothesis node. Unresolved points become Research Problem nodes that open
  child-Investigation paper search.

Overlays: modals (picker, Perspective detail, members, hypothesis, reset)
share ModalShell; the 1180px/96vw panel drawer is the only side sheet.

IA rules:
- One primary action per surface; it advances the flow.
- Identity and status at a glance; prose one click away.
- Metadata (counts, states) are quiet labels, never sentences.
- Destructive/tooling actions live in the chevron menu, not the flow.
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

Controls: h-7 sm / h-8 md; text 12 sm / 13 md; icon 13px lucide (chevrons only).
Motion: 120ms micro-interactions; 180–260ms entry using opacity and
at most 8px translation. Lists stagger 36–45ms; drawers travel 18px.
Every entry class resolves instantly under `prefers-reduced-motion`.

## Components (features/focused/ui.tsx)

Button(variant primary|outline|ghost, size sm|md) — primary is --node
fill; ghost transparent, hover --hover; outline hairline + hover bg.
Spinner. ModalShell(title, onClose): 640px/92vw, 48px minimum header,
12px vertical padding, 16px 600 title. SectionLabel: 12px 500 mute.
EmptyLine: 13px mute.
EvidenceHighlight(label): amber evidence mark with a portal tooltip on hover
and keyboard focus.
IdentityChip(color, name, selected?) — dot + colored name; selected
fills --node with white text. ListRow(disabled?, onClick) — hover bg +
border affordance. CheckRow(checked, onToggle) — 13px checklist row.

## Content rules

Sentence case, never uppercase labels. No arrows, no emojis, plain
language; the visible term is "panel", not "deliberation". Empty states are
one actionable line. Buttons say what they do (Generate search queries,
Start round, Apply shared ground, Investigate selected).
Busy = spinner inside the triggering button.
Visible labels start with a capital letter. Internal agent and paper IDs
never render; use the Perspective name and complete, wrapping
bibliographic title. Sources remain visible as dotted, clickable title
links. Computed cosine-distance metrics are exported for analysis but never
shown to participants; only the participant's own round ratings are visible.
