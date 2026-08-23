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
  After retrieval, the exact submitted queries remain visible as a read-only
  record beside the resulting clusters.
  Adding a Perspective inserts a pending matrix card immediately. The server
  response replaces the card and creates its matching canvas agent; a failed
  request removes the card. Continue opens the canvas directly with every matrix
  Perspective—there is no separate panel-selection step.
  Before round 1, the drawer explains the multi-round flow and the follow-up
  question step, then asks the researcher to choose one or two areas.
- Panel — React Flow canvas (nodes/wires/dot grid) + guided drawer:
  while open, the canvas shows the Research Problem, Perspective agents, and
  panel. Add Perspective uses an unrepresented cluster and appends its agent to
  the same deliberation without clearing prior work. Round conversations stay in
  the drawer; each moderator summary follows its agent turns.
  Shared ground shows explicit Before and Proposed values for every changed
  hypothesis part, then requires a separate Apply changes confirmation. Saving
  creates an immutable checkpoint. End deliberation closes the round/chat/edit
  lifecycle and reveals only the final Hypothesis and Research Problem outputs,
  followed by one deliberation-level divergent/convergent scoring dialog.
  Completed open questions expose Start paper search both in the drawer and on
  their Research Problem node; neither surface forces the user to hunt for the
  other.
  A Research Problem opens a temporary literature branch. Continue imports its
  evidence and Perspectives into the parent, reopens the same panel, and returns
  to the existing Canvas. Prior rounds and checkpoints remain; the earlier
  completion and score move into completion history.
  The Canvas retains each completed panel checkpoint and its final outputs.
  Perspectives imported from a Research Problem branch render beneath that
  Research Problem and feed the continued panel; they never attach to the root
  problem. Saved Hypothesis nodes use the restrained green success surface.

Overlays: modals (add Perspective, Perspective detail, apply changes,
hypothesis, scoring, reset) share ModalShell; the 1180px/96vw panel drawer is
the only side sheet.
The header exposes one Investigation map action when research branches exist.
It does not expose a second Investigation picker.


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

Sentence case, never uppercase labels. No arrows, no emojis, plain language;
prefer “panel” in explanatory copy. The explicit terminal action is
“End deliberation.” Empty states are one actionable line. Buttons say what they
do (Generate search queries, Add Perspective, Start round, Apply shared ground,
Apply changes, End deliberation).
Busy = spinner inside the triggering button.
Visible labels start with a capital letter. Internal agent and paper IDs
never render; use the Perspective name and complete, wrapping
bibliographic title. Sources remain visible as dotted, clickable title
links. Computed cosine-distance metrics are exported for analysis but never
shown to participants; scoring reflects the completed deliberation as a whole.
