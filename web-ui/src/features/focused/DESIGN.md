# Focused study design reference

## Product boundary

The focused surface has one baseline flow at `/focused`. `/demo` runs the same flow on deterministic QA data. `?workspace=<id>` reopens a specific workspace; `/focused` without it resumes the last workspace from this browser, and `/demo` without it always starts fresh. The UI shows no condition control. Demo and live sessions use the same query, clustering, Perspective, and discussion state transitions.

## Flow

The header shows two steps: **Find papers** and **Discuss**. **Start over** saves pending notepad edits, clears this browser's active workspace, and returns to the start screen. The previous workspace, including finished study data, remains stored and can be reopened with its workspace URL. The primary action moves between the paper workflow and the discussion.

### Start

The centered form collects the problem and four position fields:

- Framing
- Previous work
- Methodology
- Expected results

The researcher writes these fields. Agents never update them.

The start screen uses native form values so browser-restored and autofilled text can be submitted without relying on React input events. **Continue** validates the Problem when submitted and is disabled only while creating the workspace. The form uses POST rather than placing research text in the URL.

### Find papers

The desktop surface has three independently scrolling columns:

1. The **Problem** column shows the problem, the four position fields, and five suggested searches.
2. The **Papers** column shows a flat paper list. A paper expands its abstract inline.
3. The **Perspective** column edits the selected paper's Job and Description, then builds the Perspective. Building is optimistic: the editor clears at once, the new row shows **Adding…** until the server confirms, and further papers can be carried and built meanwhile. A failed build stays in the column with its error, **Retry** (which restores the wording to the editor), and **Dismiss**.

Search shows skeleton rows alongside real retrieval progress until papers arrive. Carrying a paper focuses the Job field; carrying the same paper again keeps its current wording. Pending build rows update in place when confirmed. The six-slot count includes pending builds, with ready and adding counts shown separately.

One selected paper anchors one hidden literature cluster. The server derives Scope, Explanation, Approach, Significance, Framing, and Position from that cluster. The participant sees only the Perspective name, Description, anchor paper, and related-paper count. A study holds at most six Perspectives.

Source titles wrap left-aligned in both the paper-building cards and the discussion sidebar. Related-paper counts sit on a separate line without a leading separator.

### Discuss

The surface has three columns:

1. The left column lists **Discussion topics** above **Document**. The topic list is collapsed by default; its header shows the topic count and a toggle. Document contains independent versions of the four researcher-authored fields. **Copy current** forks the active version. **Start blank** creates an empty version.
2. **Discussion** runs the active version's persisted agenda. The roster is collapsed by default; the header shows one colored icon per Perspective beside the label and a toggle that expands the named chips.
3. **Perspectives** shows the active speakers as plain identity cards. Expanded cards show only the Description, anchor paper, and related-paper count.

Each topic is an evidence-motivated proposal with a title, scientific question, tentative hypothesis, rationale, and citations. Live generation uses the Perspective's source abstracts. The researcher's position guides relevance but is not evidence. Demo mode uses deterministic question types and cited abstract excerpts.

Selecting a topic prepares an editable chat question without replacing an existing draft. The hypothesis and rationale appear beside the composer. **Send** records the topic on the researcher message and every Perspective reply. A failed request preserves the question and selected topic. These exchanges do not rewrite the Document or advance its field-review agenda.

Topics persist across Document versions, cleared chats, and reloads. Topics from removed Perspectives remain available. A new Perspective receives a topic without replacing existing topics. A generation failure leaves chat available and offers **Retry**. Discussion actions hold the busy state through pending Document saves and the subsequent command.

The topic action reads **Suggesting topics…** while generation is pending.

For each Document field, every Perspective gives independent feedback before any Perspective compares the feedback. Every Perspective then gives one comparison. The agenda advances through Framing, Previous work, Methodology, and Expected results. A click requests the selected number of turns one at a time, so each turn appears as it finishes; the click stops early if the agenda completes. A failure mid-way keeps the turns already recorded.

The visible turn selection stays unchanged while individual turns arrive.

The app-styled **Turns** dropdown retains the 1–8 range. Its popover escapes panel clipping and stays within the viewport. Arrow keys, Home, and End move the highlighted option; Enter, Space, or Tab commit it. Escape and outside clicks dismiss it without changing the selection.

A researcher question adds one researcher message and one reply from every active Perspective. The common agenda does not reset. A Perspective added later joins the current field. A completed review stops until the researcher starts another review.

Send displays a local **Sending** preview immediately. The recorded turn replaces that preview on success; failure restores the draft and keeps its topic. Discussion, Send, and Summary show activity inside the conversation. Incoming turns appear without moving a reader who has scrolled into older feedback; **Jump to latest** returns to the bottom. Completing a request does not take focus away from another control the researcher opened.

After a send receives HTTP 502 or 504, the UI keeps its busy guard and performs one uncached workspace read, limited to five seconds. A new researcher turn must match the submitted version, normalized text, and topic before the UI accepts the saved result. Earlier identical messages do not count. An unconfirmed result keeps the draft and topic and asks the researcher to refresh before sending again. Recovery never resends the prompt automatically.

**Papers**, **Build another Perspective**, and version navigation wait for the active command to settle. This keeps pending message drafts and topics mounted for error recovery.

**Copy feedback** writes text only to the clipboard. Feedback, comparison, direct replies, and summaries never mutate the Document.

**Clear chat** requires confirmation. Cancel and Escape leave the conversation untouched. Confirmation clears the current version’s visible chat without changing its Document or review progress.

**Finish study** flushes pending edits, snapshots every Document version, and makes the study read-only. Reloading preserves the finished output.
Finished topic rows expand their saved hypothesis and rationale for inspection. This changes only the local view, without preparing a new message or writing to the workspace.

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

Core tokens live in `app/(focused)/layout.tsx`:

- Neutrals: `--bg`, `--panel`, `--ink`, `--ink-2`, `--mute`, `--line`, and `--line-strong`.
- Inverted controls: `--node` and `--on-node`.
- Semantic states: `--green`, `--amber`, and `--red` with their background tokens.
- Perspective identity colors come from `PERSONA_COLORS` and are the only free colors.

Inputs use a 6px radius. Cards, buttons, and fields use 8px. Modals use 12px. Cards use borders without shadows. Motion lasts 120ms for controls and 180–260ms for entry. Every entry class resolves immediately under `prefers-reduced-motion`.

Pending dots and skeletons use restrained opacity pulses. Reduced motion disables these and existing spinners. Conversation scroll anchoring is instantaneous so rapid replies remain pinned without mistaking animated scroll events for reader input.
