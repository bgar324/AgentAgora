# Spec: document-based perspective-guided deliberation

**Status:** implemented and verified, pending Kat's design specification.
**Date:** 2026-08-26.
**Baseline commit:** `main@f58a101`.
**Implementation:** `src/agora/focused/notepad.py`, `web-ui/src/features/focused/stage-notepad.tsx`, 22 backend tests in `tests/test_focused_notepad.py`, 10 browser tests in `web-ui/e2e/notepad-protocol.spec.ts`. The Thread board stays reachable at `?surface=threads` (env: `NEXT_PUBLIC_FOCUSED_SURFACE=threads`), so this is a flag flip away from rollback and its old suite still runs against it.
**Replaces:** the Thread-picker panel (`stage-dialogue.tsx`), which the PI found confusing. The deliberation *engine* is unchanged; only the object of deliberation and its surface move.

This is our best-faith implementation reading of the direction Kat and Youngseung have given, written so building can start before the full design specification lands. It is not a competing design. Where they have specified something (three columns, the four-part notepad, versions as the study output, the HITL references), this follows it exactly. Where they have not, it picks the option closest to what they have already said and flags it in §8 for them to overrule. Every mechanic is implemented by a function we already host from `katjpg/agent-agora` (byte-identical vendored copy, verified 2026-08-26).


---

## 0. Revision note: one shell, two arms

The first draft of this spec proposed a two-column document surface. That was wrong and is withdrawn.

Youngseung's baseline specification defines three columns (notepad, conversation, perspectives). Both arms must use **that same shell**, because two arms differing in layout *and* in deliberation mechanic cannot attribute an observed effect to the mechanic. The manipulation has to be the only difference.

Consequences:

1. The three-column shell is built once and configured per arm.
2. The notepad is **the four parts** (Framing, Previous work, Methodology, Expected results) in both arms, not Kat's per-Thread `sections`, because the study's dependent variable is the set of four-part versions and those must be comparable across arms.
3. Pane count was never the source of the cognitive load. Concept count, gating, and a read-only artifact were. Those fixes survive unchanged in three columns.
---

## 1. The one-sentence model

**The document is the object of deliberation.** Perspectives propose changes to it, the researcher is the merge gate, and every accepted change is recorded with its provenance.

The previous model made a Thread the object and the document a byproduct. Inverting that removes the navigation layer (a list of Threads to visit) that produced most of the cognitive load, because the artifact under discussion is always on screen and always editable.

---

## 2. Interaction contract: four verbs, everywhere

Borrowed from the LangChain HITL middleware Kat referenced, because a small fixed decision vocabulary is the thing that makes an agentic surface legible.

| Verb | Meaning | Implemented by |
|---|---|---|
| **Approve** | Take the proposal as written, folded onto the current wording. | `decide_proposal(action="approve")` (Kat's `apply_suggestion(action="accept")` shape) |
| **Edit** | Take it in my wording. | `decide_proposal(action="edit", text=…)` |
| **Reject** | Don't take it, and here is why. | `decide_proposal(action="reject", reason=…)` |
| **Ask** | Reply to the proposing Perspective instead of deciding. | existing contribution/reply path |

Today the product uses three different vocabularies for the same shape: `accept / edit / keep_open / request_evidence` on resolutions, `apply / edit / reject` on hypotheses, and status transitions on questions. Collapsing to these four, used identically on every surface, is the single largest legibility win available and costs no engine changes.

**Rejection is not silent.** The reason lands on `NotepadProposal.decision_reason` and is read back into the chat, so the panel has it as context and a later proposal can differ. This is the `reject` + feedback pattern from the middleware, and it is the part our current auto-accept path throws away entirely.

A correction to an earlier draft of this spec: Kat's `Suggestion.reason` is the *proposer's* justification, and `apply_suggestion(action="reject")` returns the suggestion marked rejected with no `Revision` and nowhere to put the researcher's words. So a rejection reason cannot ride on her `Suggestion` as written. We carry a distinct `decision_reason` field. If the notepad ever moves onto her `Suggestion` type directly, that needs a new field and a migration - open item §8.7.

**Stale proposals re-base; they are never auto-rejected.** The notepad is editable while a proposal is pending, so by the time the researcher decides, the wording the proposal was raised against is often gone. Two rules follow:

1. A proposal stores its **addition** (what the panel contributes), not only an absolute `proposed_text`. Approving appends the addition to whatever the part says at that moment, and the chat says it was *folded into your newer wording*. Writing the frozen text would silently discard the researcher's edit; that was a real defect, and `test_approving_after_your_own_edit_keeps_both` pins it for both arms.
2. The review card renders the **live** wording in its diff, not the frozen `current_text`, so the researcher never reviews a strikethrough of text that no longer exists.

Kat's `apply_suggestion` takes the opposite position: it raises when `section.version != suggestion.section_version`, which under "always editable" invalidates every pending Suggestion the moment a human types. Adopting her function for this surface therefore requires either re-basing before the call or relaxing that guard - open item §8.8.

**Policy, not blanket review.** Following the middleware's `interrupt_on` model: agent writes to the document always require a decision; agent conversation turns never do. The researcher's own edits are never reviewed.

---

## 3. Answers to the four open questions

### Q1. Do agents propose continuously, or on demand?

**On demand, bounded, and announced.**

The researcher asks the panel to review a section (or the whole document). Each participating Perspective returns **at most one proposal per section**. The queue is therefore bounded by construction: *N Perspectives × 1 proposal*, known before the click.

Rationale: continuous proposal generation produces an unbounded review queue, which is the same failure as the Thread board. The baseline's "Let agents discuss · 4 turns" is legible precisely because the cost is stated up front, and the middleware's policy model exists for the same reason. Bounded, announced work is the property to preserve.

### Q2. Versions: linear history or parallel alternatives?

**Both, at different levels. Parallel named versions of the document; revision history inside each.**

- `DocumentVersion` is a named container (`v1`, `v2`, …) holding its own sections and its own revision log.
- Fork copies the current version or starts blank. Versions are independent. Deleting is allowed while more than one exists.
- Inside a version, every accepted change appends a `Revision` (previous / proposed / accepted text, which suggestion, which decision).

Rationale: the baseline's notepad versions **are the study's dependent variable** ("The several versions of hypotheses on Notepad are the final output"). The experimental arm must produce a comparable artifact or the two conditions cannot be compared. Keeping per-version revision history on top is strictly additive and is where our provenance contribution lives.

### Q3. Anchored discussion per section, or one document-level conversation?

**Anchored per section is the deliberation. A document-level chat exists for questions that are not about one section.**

`Thread.section_id` already anchors a discussion to a document region; we built that field and never used it for anchoring. A contested section shows its own discussion beside it, so disagreement appears *at the paragraph in question* rather than in a separate list.

The document-level chat maps to the baseline's group chat and to the `respond` verb: ask the panel something, get replies, no document write implied.

### Q4. Does the researcher's own edit trigger agent reaction?

**No. Editing is silent and free; exposure to the panel is explicit.**

Auto-reacting to typing makes the system unpredictable and prevents thinking in the document. The researcher edits freely, then chooses when to ask the panel to look. This also keeps the request volume low enough to matter for cost.

### Q5 (added). What is the terminal artifact?

The set of `DocumentVersion`s, each with its revision history and the decisions that produced it. Directly comparable to the baseline's notepad versions, plus provenance the baseline does not have.

---

## 4. State model

New types on `SessionState.dialogue` (additive, own migration, so a rollback is a flag flip and not a data problem):

```
DocumentVersion
  id: str
  name: str                     # "v1", "v2", … researcher-renameable
  document: WorkingDocument     # Kat's type, unchanged
  revisions: list[Revision]     # Kat's type, unchanged
  created_from: str | None      # source version id, or None when blank
  created_at: datetime

DialogueState (extended)
  versions: list[DocumentVersion]
  active_version_id: str | None
```

Unchanged and reused as-is: `WorkingDocument`, `DocumentSection`, `Objective`, `Suggestion`, `Revision`, `Thread`, `Contribution`, `Resolution`, `Reflection`, `PerspectiveState`.

**One deviation from Kat's contract, flagged for her review.** `Suggestion` requires `thread_id` and `resolution_id`. A direct section-review proposal has a Thread (the review request, anchored via `section_id`) but no `Resolution`, since no discussion preceded it. For now `resolution_id` carries the review request's id. If she wants the strict ordering (Resolution before Suggestion), the fix is to run `summarize_thread` at the end of a review round and reference the real resolution; that adds a step the researcher must clear, which is why I did not choose it by default.

---

## 5. Command surface

| Command | Effect | Review required |
|---|---|---|
| `PATCH …/document/sections/{id}` | Researcher edits section text. | no |
| `POST …/document/versions` | Fork current or blank. | no |
| `DELETE …/document/versions/{id}` | Delete a version (never the last). | no |
| `POST …/document/review` | Ask the panel to review a section, or the whole document. Creates one pending `Suggestion` per Perspective. | produces the queue |
| `POST …/suggestions/{id}/decision` | `approve` / `edit` / `reject`, with reason on reject. | this is the gate |
| `POST …/dialogue/messages` | Ask the panel, anchored to a section or document-level. | no |

Every mutation stays a revision-checked aggregate transaction, as all existing ones are.

---

## 6. Surface

**One shell, three columns, identical in both arms**, per Youngseung's baseline specification.

| Column | Contents |
|---|---|
| Left | Notepad: the four parts, editable as typed, no save affordance. Version tabs above (`v1 v2 ＋ Version`; `＋` offers copy-current or blank; `×` deletes while more than one exists). Switching tabs swaps the four fields. |
| Middle | Conversation: an "In the chat" roster (`×` removes, `+ Add` restores), the stream, then `Let agents discuss` with a turn count, `Summarize so far`, `Clear`, then the input box. |
| Right | Perspectives: cards expanding to description and source paper, an `in chat` / `add` toggle, a dashed box to build a new one, and `›` collapsing the column to a rail. |

**The manipulation, and nothing else:**

| | Baseline arm | Experimental arm |
|---|---|---|
| Agents | hand-written personas (name, job, description) | Perspectives carrying grounded facets from their literature cluster |
| Turns | ungrounded prose | cite abstract evidence with `[n]` markers |
| Notepad writes | `Copy into the notepad`, blind append to one part | a proposal card: current-versus-proposed diff, reason, cited evidence, and the four verbs |
| Discussion scope | one flat conversation | one flat conversation (anchoring a discussion to a single part is possible with `Thread.section_id`, but neither Kat nor Youngseung asked for it, so it stays out until they do) |

Nouns a first-time researcher must learn: **notepad, part, version, proposal, Perspective, chat.** Six. The Thread board required roughly twelve.

---

## 7. What this deliberately does not do

- No auto-accept anywhere. Every agent write passes a human decision.
- No continuous background proposing.
- No separate Thread list, no Thread status vocabulary, no moderator-check surface.
- No hypothesis object distinct from the document. The document is the hypothesis.

---

## 8. Open items for Kat

1. Is the `resolution_id` deviation in §4 acceptable, or should a review round produce a real `Resolution` first?
2. Should a Perspective be able to propose changes to a section it has no grounded evidence for? Current answer: no, it may only cite its own observations.
3. Should versions be comparable side by side (diff two versions), or is switching enough for the study?
4. Does the experimental arm keep clustering in the retrieval step? The baseline mockup drops it, and if only one arm has it, retrieval quality confounds the deliberation comparison.
5. The summary needs a target part. Shipped answer: the researcher picks it next to `Summarize so far`, defaulting to Framing. The alternative is letting the panel choose, which hides a decision inside an agent.
6. Turn-taking is not guidance. A speaker's second turn answers the previous speaker by name in **both** arms, because identical repeated text was a rendering defect, not a manipulation. Only the baseline's turns stay uncited and never reference the notepad.
7. **Where does a rejection reason live if we adopt `Suggestion`?** `Suggestion.reason` is already the proposer's. Options: add `decision_reason` to `Suggestion` (schema change plus migration), or keep decisions in a separate record and leave `Suggestion` immutable. We currently do the latter on our own type. Your call which one the canonical schema should carry.
8. **Should `apply_suggestion` keep raising on `section_version` drift?** Under "always editable" that fires constantly. We re-base instead. If the guard is load-bearing for the document path, the notepad needs to stay on its own type; if not, relaxing it to a re-base would let both surfaces share one function.

---

## 9. What shipped, measured

Both arms, same fixture, four turns and one summary (`tests/test_focused_notepad.py`):

| | baseline | guided |
|---|---|---|
| turns citing evidence | 0/4 | 4/4 |
| turns quoting the researcher's own wording | none | yes |
| pending decisions raised by one summary | 1 | 1 |
| seam carries a reason | no | yes |
| seam carries its evidence | no | yes |
| notepad written before the researcher decides | no | no |
| notepad written after the researcher decides | yes | yes |

Step count, seam location, and layout are identical. The difference is grounding and reviewability, which is the manipulation.
