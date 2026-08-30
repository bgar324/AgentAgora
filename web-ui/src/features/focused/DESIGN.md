# Focused study design reference

## Product boundary

The focused surface has one baseline flow. The URL keeps `arm=baseline` for study assignment, but the API stores no arm and the UI shows no condition control. `demo=1` selects deterministic QA data. Demo and live sessions use the same query, clustering, Perspective, and discussion state transitions.

## Flow

The header shows two steps: **Find papers** and **Discuss**. **Start over** deletes the current workspace. The primary action moves between the paper workflow and the discussion.

### Start

The centered form collects the problem and four position fields:

- Framing
- Previous work
- Methodology
- Expected results

The researcher writes these fields. Agents never update them.

### Find papers

The desktop surface has three independently scrolling columns:

1. The **Problem** column shows the problem, the four position fields, and five suggested searches.
2. The **Papers** column shows a flat paper list. A paper expands its abstract inline.
3. The **Perspective** column edits the selected paper's Job and Description, then builds the Perspective.

One selected paper anchors one hidden literature cluster. The server derives Scope, Explanation, Approach, Significance, Framing, and Position from that cluster. The participant sees only the Perspective name, Description, anchor paper, and related-paper count. A study holds at most six Perspectives.

### Discuss

The surface has three columns:

1. **Document** contains independent versions of the four researcher-authored fields. **Copy current** forks the active version. **Start blank** creates an empty version.
2. **Discussion** runs the active version's persisted agenda.
3. **Perspectives** shows the active speakers as plain identity cards. Expanded cards show only the Description, anchor paper, and related-paper count.

For each Document field, every Perspective gives independent feedback before any Perspective compares the feedback. Every Perspective then gives one comparison. The agenda advances through Framing, Previous work, Methodology, and Expected results. A click emits exactly the selected number of turns and resumes from the persisted agenda.

A researcher question adds one researcher message and one reply from every active Perspective. The common agenda does not reset. A Perspective added later joins the current field. A completed review stops until the researcher starts another review.

**Copy feedback** writes text only to the clipboard. Feedback, comparison, direct replies, and summaries never mutate the Document.

**Finish study** flushes pending edits, snapshots every Document version, and makes the study read-only. Reloading preserves the finished output.

## Interface rules

- One primary action advances each surface.
- Use Document, Discussion, and Perspectives in participant copy.
- Never show Fragment names, cluster names, cluster IDs, source IDs, embeddings, or study-condition names.
- Show the Perspective name instead of an ordinal agent label.
- Keep counts and state as quiet labels.
- Keep every list-row action visible without hover.
- Use sentence case. Do not use arrows or emoji.

## Visual system

Use Inter, near-monochrome neutrals, hairline borders, compact controls, and restrained semantic color. Hierarchy comes from weight, size, and the gray ramp.

Core tokens live in `app/focused/layout.tsx`:

- Neutrals: `--bg`, `--panel`, `--ink`, `--ink-2`, `--mute`, `--line`, and `--line-strong`.
- Inverted controls: `--node` and `--on-node`.
- Semantic states: `--green`, `--amber`, and `--red` with their background tokens.
- Perspective identity colors come from `PERSONA_COLORS` and are the only free colors.

Inputs use a 6px radius. Cards, buttons, and fields use 8px. Modals use 12px. Cards use borders without shadows. Motion lasts 120ms for controls and 180–260ms for entry. Every entry class resolves immediately under `prefers-reduced-motion`.
