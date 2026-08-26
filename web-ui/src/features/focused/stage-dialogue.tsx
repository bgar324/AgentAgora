"use client"

import { useEffect, useMemo, useState } from "react"
import Markdown from "react-markdown"
import { ArrowUp, CircleCheck, UserRound } from "lucide-react"

import { useFocusedPanel } from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import type {
  CanonContribution,
  CanonRefinement,
  CanonResolution,
  CanonThread,
  DialogueState,
  SessionState,
} from "@/types/focused"
import { Button, EmptyLine, ModalShell, SectionLabel, Spinner } from "./ui"

// Busy labels owned by use-focused.ts; a button spins only for its own
// command, everything else just disables. One spinner per surface.
const BUSY = {
  start: "Starting deliberation",
  select: "Creating Working Document",
  open: "Discussing Thread",
  message: "Sending message",
  decide: "Reviewing resolution",
} as const

const KIND_LABELS: Record<CanonContribution["kind"], string> = {
  answer: "Answers the question",
  reply: "Reply",
  support: "Cites evidence",
  challenge: "Challenge",
}

function latestThreads(dialogue: DialogueState): CanonThread[] {
  const latest = new Map<string, CanonThread>()
  for (const thread of dialogue.threads) latest.set(thread.id, thread)
  return [...latest.values()]
}

function latestResolution(
  dialogue: DialogueState,
  resolutionId: string | null,
): CanonResolution | null {
  if (!resolutionId) return null
  for (let i = dialogue.resolutions.length - 1; i >= 0; i--) {
    if (dialogue.resolutions[i].id === resolutionId) {
      return dialogue.resolutions[i]
    }
  }
  return null
}

function pendingResolution(
  dialogue: DialogueState,
  threadId: string,
): CanonResolution | null {
  const seen = new Set<string>()
  for (let i = dialogue.resolutions.length - 1; i >= 0; i--) {
    const resolution = dialogue.resolutions[i]
    if (resolution.thread_id !== threadId || seen.has(resolution.id)) continue
    seen.add(resolution.id)
    if (resolution.status === "pending") return resolution
  }
  return null
}

function useNames(session: SessionState, dialogue: DialogueState) {
  return useMemo(() => {
    const colors = new Map(
      session.perspectives.map((perspective) => [
        perspective.id,
        perspective.color,
      ]),
    )
    const names = new Map<string, { label: string; color?: string }>()
    for (const state of dialogue.perspective_states) {
      names.set(state.id, {
        label: state.label || state.profile.focus,
        color: colors.get(state.id),
      })
    }
    names.set("researcher", { label: "Researcher" })
    names.set("moderator", { label: "Moderator" })
    return names
  }, [session.perspectives, dialogue.perspective_states])
}

function PerspectiveDot({ color }: { color?: string }) {
  return (
    <UserRound
      aria-hidden
      size={13}
      strokeWidth={2.2}
      className="shrink-0"
      style={{ color: color ?? "var(--ink-2)" }}
    />
  )
}

function ErrorLine({ children }: { children: string }) {
  return (
    <p role="alert" className="mt-2 text-[12px] text-[var(--red)]">
      {children}
    </p>
  )
}


export function PanelIntroDialog({
  onClose,
  onStarted,
}: {
  onClose: () => void
  onStarted: () => void
}) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const [error, setError] = useState<string | null>(null)
  const starting = busy === BUSY.start
  const start = () => {
    setError(null)
    focused
      .startDialogue()
      .then(onStarted)
      .catch((cause) =>
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not start the deliberation",
        ),
      )
  }
  return (
    <ModalShell title="Set up the panel" onClose={onClose}>
      <p className="text-[12px] leading-relaxed text-[var(--ink-2)]">
        Each Perspective proposes a scientific claim from its literature,
        reviews a peer&apos;s proposal, and refines its own. You then choose
        which refined directions the Working Document should organize.
      </p>
      {error && <ErrorLine>{error}</ErrorLine>}
      <div className="mt-4 flex justify-end gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={busy !== null}
          onClick={onClose}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={busy !== null}
          onClick={start}
        >
          {starting ? <Spinner /> : null} Start deliberation
        </Button>
      </div>
    </ModalShell>
  )
}

function RefinementCard({
  refinement,
  review,
  name,
  color,
  checked,
  onToggle,
}: {
  refinement: CanonRefinement
  review: { response: string; question: string | null } | null
  name: string
  color?: string
  checked: boolean
  onToggle: () => void
}) {
  return (
    <label className="ep-card-enter ep-interactive-card panel block cursor-pointer px-4 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[12px] font-semibold">
          <PerspectiveDot color={color} />
          {name}
        </span>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Include ${name}`}
          className="mt-0.5 size-3.5 accent-[var(--node)]"
        />
      </div>
      <p className="mt-2 text-[13px] font-medium leading-snug">
        {refinement.proposal.claim.text}
      </p>
      <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ink-2)]">
        {refinement.proposal.argument.reasoning}
      </p>
      {review && (
        <div className="mt-3 border-t border-[var(--line)] pt-2.5">
          <p className="text-[11px] font-medium text-[var(--mute)]">
            Peer review
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
            {review.response}
          </p>
          {review.question && (
            <p className="mt-1 text-[12px] italic leading-relaxed text-[var(--ink-2)]">
              {review.question}
            </p>
          )}
        </div>
      )}
      <div className="mt-3 border-t border-[var(--line)] pt-2.5">
        <p className="text-[11px] font-medium text-[var(--mute)]">
          Refinement ·{" "}
          {refinement.decision === "revise" ? "Revised" : "Unchanged"}
        </p>
        <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
          {refinement.reason}
        </p>
        {refinement.open_question && (
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--mute)]">
            Open question: {refinement.open_question}
          </p>
        )}
      </div>
    </label>
  )
}

function DialogueSelection({
  session,
  dialogue,
}: {
  session: SessionState
  dialogue: DialogueState
}) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const names = useNames(session, dialogue)
  const [picked, setPicked] = useState<string[]>(() => [
    ...new Set(dialogue.refinements.map((r) => r.proposal_id)),
  ])
  const [error, setError] = useState<string | null>(null)
  const creating = busy === BUSY.select
  const reviewByProposal = useMemo(() => {
    const map = new Map<
      string,
      { response: string; question: string | null }
    >()
    for (const review of dialogue.reviews) {
      map.set(review.proposal_id, {
        response: review.response,
        question: review.question,
      })
    }
    return map
  }, [dialogue.reviews])

  return (
    <section
      aria-label="Choose the directions"
      className="ep-enter mx-auto mt-6 w-full max-w-[880px]"
    >
      <SectionLabel>Choose the directions</SectionLabel>
      <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
        The selected refinements become the objectives of the shared Working
        Document.
      </p>
      <div className="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {dialogue.refinements.map((refinement) => {
          const who = names.get(refinement.proposal.perspective_id)
          return (
            <RefinementCard
              key={refinement.id}
              refinement={refinement}
              review={reviewByProposal.get(refinement.proposal_id) ?? null}
              name={who?.label ?? refinement.profile.focus}
              color={who?.color}
              checked={picked.includes(refinement.proposal_id)}
              onToggle={() =>
                setPicked((current) =>
                  current.includes(refinement.proposal_id)
                    ? current.filter((id) => id !== refinement.proposal_id)
                    : [...current, refinement.proposal_id],
                )
              }
            />
          )
        })}
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button
          variant="primary"
          size="sm"
          disabled={busy !== null || picked.length === 0}
          onClick={() => {
            setError(null)
            focused
              .selectDialogueDirections(picked)
              .catch((cause) =>
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not create the Working Document",
                ),
              )
          }}
        >
          {creating ? <Spinner /> : null} Create Working Document
        </Button>
        <span className="text-[11px] text-[var(--mute)]">
          {picked.length} of {dialogue.refinements.length} selected
        </span>
      </div>
      {error && <ErrorLine>{error}</ErrorLine>}
    </section>
  )
}

function DocumentPanel({
  dialogue,
  onReport,
}: {
  dialogue: DialogueState
  onReport: (() => void) | null
}) {
  const document = dialogue.document
  if (!document) return null
  return (
    <aside
      data-testid="dialogue-document-panel"
      aria-label="Working Document"
      className="shrink-0 border-b border-[var(--line)] bg-[var(--panel)] px-4 py-4 lg:w-[300px] lg:overflow-y-auto lg:border-b-0 lg:border-r"
    >
      <SectionLabel>Working Document · v{document.version}</SectionLabel>
      <h2 className="mt-1 text-[13px] font-semibold leading-snug">
        {document.title}
      </h2>
      <div className="mt-3">
        <p className="text-[11px] font-medium text-[var(--mute)]">
          Objectives
        </p>
        <ol className="mt-1 list-decimal space-y-1 pl-4">
          {document.objectives.map((objective) => (
            <li
              key={objective.id}
              className="text-[12px] leading-relaxed text-[var(--ink-2)]"
            >
              {objective.text}
            </li>
          ))}
        </ol>
      </div>
      <div className="mt-3 space-y-3">
        {document.sections.map((section) => (
          <div key={section.id} className="border-t border-[var(--line)] pt-2.5">
            <p className="text-[12px] font-semibold">{section.title}</p>
            <p className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-[var(--ink-2)]">
              {section.text || "Opens with its Thread's discussion."}
            </p>
          </div>
        ))}
      </div>
      {document.references.length > 0 && (
        <div className="mt-3 border-t border-[var(--line)] pt-2.5">
          <p className="text-[11px] font-medium text-[var(--mute)]">
            References
          </p>
          <ol className="mt-1 list-decimal space-y-0.5 pl-4">
            {document.references.map((reference, index) => (
              <li
                key={`${reference}-${index}`}
                className="break-all text-[11px] text-[var(--mute)]"
              >
                {reference}
              </li>
            ))}
          </ol>
        </div>
      )}
      {onReport && (
        <div className="mt-4 border-t border-[var(--line)] pt-3">
          <Button variant="outline" size="sm" onClick={onReport}>
            Draft report
          </Button>
        </div>
      )}
    </aside>
  )
}

function ResolvedList({
  dialogue,
  closed,
}: {
  dialogue: DialogueState
  closed: CanonThread[]
}) {
  if (closed.length === 0) return null
  return (
    <div className="mt-6">
      <SectionLabel>Resolved</SectionLabel>
      <div className="mt-2 space-y-2">
        {closed.map((thread) => {
          const resolution = latestResolution(dialogue, thread.resolution_id)
          return (
            <div key={thread.id} className="panel px-4 py-3">
              <p className="text-[12px] font-semibold">{thread.title}</p>
              {resolution?.consensus && (
                <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                  {resolution.consensus}
                </p>
              )}
              {resolution?.open_question && (
                <p className="mt-1 text-[12px] leading-relaxed text-[var(--mute)]">
                  Open question: {resolution.open_question}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ThreadPicker({
  session,
  dialogue,
  onReport,
}: {
  session: SessionState
  dialogue: DialogueState
  onReport: () => void
}) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const [error, setError] = useState<string | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)
  const threads = latestThreads(dialogue)
  const suggested = threads.filter((thread) => thread.status === "suggested")
  const closed = threads.filter((thread) => thread.status === "closed")
  const allResolved = suggested.length === 0 && closed.length > 0

  if (allResolved) {
    return (
      <div className="ep-enter mx-auto w-full max-w-[640px] py-6">
        <section
          aria-label="Deliberation complete"
          className="ep-card-enter panel flex flex-col items-center px-6 py-8 text-center"
        >
          <CircleCheck
            aria-hidden
            size={22}
            strokeWidth={1.8}
            className="text-[var(--green)]"
          />
          <h2 className="mt-2.5 text-[13px] font-semibold">
            All Threads resolved
          </h2>
          <p className="mt-1 max-w-[42ch] text-[12px] leading-relaxed text-[var(--ink-2)]">
            Every scientific issue this panel raised has a recorded
            resolution. The moderator has synthesized them into the final
            report.
          </p>
          <Button
            variant="primary"
            size="sm"
            className="mt-4"
            onClick={onReport}
          >
            Review the final report
          </Button>
        </section>
        <ResolvedList dialogue={dialogue} closed={closed} />
      </div>
    )
  }

  return (
    <div className="ep-enter mx-auto w-full max-w-[640px] py-6">
      <SectionLabel>Threads</SectionLabel>
      <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
        Each Thread is one scientific issue. Opening it runs the discussion
        and ends with a resolution for your review.
      </p>
      <div className="mt-4 space-y-2.5">
        {suggested.map((thread, index) => {
          const opening = busy === BUSY.open && openingId === thread.id
          return (
            <div
              key={thread.id}
              data-testid="dialogue-thread-card"
              className="ep-card-enter panel px-4 py-3.5"
              style={{ animationDelay: `${index * 42}ms` }}
            >
              <p className="text-[13px] font-semibold">{thread.title}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                {thread.question}
              </p>
              {thread.context && (
                <p className="mt-1 text-[12px] leading-relaxed text-[var(--mute)]">
                  {thread.context}
                </p>
              )}
              <div className="mt-3">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => {
                    setError(null)
                    setOpeningId(thread.id)
                    focused
                      .openDialogueThread(thread.id)
                      .catch((cause) =>
                        setError(
                          cause instanceof Error
                            ? cause.message
                            : "Could not open the Thread",
                        ),
                      )
                      .finally(() => setOpeningId(null))
                  }}
                >
                  {opening ? (
                    <>
                      <Spinner /> Opening…
                    </>
                  ) : (
                    "Open Thread"
                  )}
                </Button>
              </div>
            </div>
          )
        })}
      </div>
      <ResolvedList dialogue={dialogue} closed={closed} />
      {error && <ErrorLine>{error}</ErrorLine>}
    </div>
  )
}

function TurnBubble({
  turn,
  name,
  color,
  replyName,
}: {
  turn: CanonContribution
  name: string
  color?: string
  replyName: string | null
}) {
  const isResearcher = turn.author_id === "researcher"
  return (
    <div className={isResearcher ? "flex justify-end" : undefined}>
      <div
        className={
          isResearcher
            ? "w-fit max-w-[78%] rounded-xl border border-[var(--line)] bg-[color-mix(in_srgb,var(--node)_6%,var(--panel))] px-3 py-2.5"
            : "rounded-xl border border-[var(--line)] bg-[var(--panel)] px-3 py-2.5"
        }
      >
        <div className="mb-1 flex items-baseline justify-between gap-3">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold">
            {!isResearcher && <PerspectiveDot color={color} />}
            {name}
          </span>
          <span className="shrink-0 text-[10.5px] text-[var(--mute)]">
            {KIND_LABELS[turn.kind]}
            {replyName ? ` · to ${replyName}` : ""}
          </span>
        </div>
        <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed">
          {turn.text}
        </p>
        {turn.observation_ids.length > 0 && (
          <p className="mt-1 text-[10.5px] text-[var(--mute)]">
            Cites {turn.observation_ids.length} observation
            {turn.observation_ids.length === 1 ? "" : "s"}
          </p>
        )}
      </div>
    </div>
  )
}

type ResolutionEdits = {
  consensus?: string
  disagreement?: string
  open_question?: string
}

const RESOLUTION_PARTS = [
  ["consensus", "Consensus"],
  ["disagreement", "Disagreement"],
  ["open_question", "Open question"],
] as const

function ResolutionCard({
  resolution,
  onDecide,
  busy,
}: {
  resolution: CanonResolution
  onDecide: (
    action: "close" | "edit_close" | "keep_open",
    edits?: ResolutionEdits,
  ) => void
  busy: string | null
}) {
  const [editing, setEditing] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [chosen, setChosen] = useState<string | null>(null)
  const deciding = busy === BUSY.decide
  const decide = (
    action: "close" | "edit_close" | "keep_open",
    edits?: ResolutionEdits,
  ) => {
    setChosen(action)
    onDecide(action, edits)
  }
  const beginEdit = () => {
    setDrafts({
      consensus: resolution.consensus ?? "",
      disagreement: resolution.disagreement ?? "",
      open_question: resolution.open_question ?? "",
    })
    setEditing(true)
  }
  // A field is submitted only when it differs from the recorded value;
  // an emptied field clears that part. At least one part must remain.
  const edits: ResolutionEdits = {}
  for (const [key] of RESOLUTION_PARTS) {
    const draft = (drafts[key] ?? "").trim()
    if (draft !== ((resolution[key] ?? "") as string).trim()) {
      edits[key] = draft
    }
  }
  const changed = Object.keys(edits).length > 0
  const anyRemaining = RESOLUTION_PARTS.some(
    ([key]) => (drafts[key] ?? "").trim().length > 0,
  )
  const submitEdit = () => {
    if (!changed) {
      decide("close")
      return
    }
    decide("edit_close", edits)
  }
  return (
    <div
      data-testid="dialogue-resolution-card"
      className="ep-card-enter panel px-4 py-3.5"
    >
      <SectionLabel>Thread resolution · your review</SectionLabel>
      {!editing ? (
        <div className="mt-2 space-y-2">
          {RESOLUTION_PARTS.map(([key, label]) =>
            resolution[key] ? (
              <p key={key} className="text-[12.5px] leading-relaxed">
                <span className="font-semibold">{label}.</span>{" "}
                {resolution[key]}
              </p>
            ) : null,
          )}
        </div>
      ) : (
        <div className="mt-2 space-y-2.5">
          {RESOLUTION_PARTS.map(([key, label]) => (
            <div key={key}>
              <label
                htmlFor={`resolution-${key}`}
                className="text-[11px] font-medium text-[var(--mute)]"
              >
                {label}
              </label>
              <textarea
                id={`resolution-${key}`}
                value={drafts[key] ?? ""}
                onChange={(event) =>
                  setDrafts((current) => ({
                    ...current,
                    [key]: event.target.value,
                  }))
                }
                rows={2}
                disabled={busy !== null}
                className="field mt-1 w-full resize-none px-3 py-2 text-[12.5px] leading-relaxed placeholder:text-[var(--mute)]"
                placeholder={
                  key === "open_question"
                    ? "What remains unresolved? Leave empty to record none."
                    : `Rewrite the ${label.toLowerCase()}, or leave empty to record none.`
                }
              />
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!editing ? (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={busy !== null}
              onClick={() => decide("close")}
            >
              {deciding && chosen === "close" ? <Spinner /> : null} Accept
              &amp; close
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null}
              onClick={beginEdit}
            >
              Edit &amp; close
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() => decide("keep_open")}
            >
              {deciding && chosen === "keep_open" ? <Spinner /> : null} Keep
              open
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={busy !== null || !anyRemaining}
              onClick={submitEdit}
            >
              {deciding && chosen === "edit_close" ? <Spinner /> : null} Close
              with this wording
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

function Conversation({
  session,
  dialogue,
  thread,
}: {
  session: SessionState
  dialogue: DialogueState
  thread: CanonThread
}) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const names = useNames(session, dialogue)
  const [message, setMessage] = useState("")
  const [error, setError] = useState<string | null>(null)
  const sending = busy === BUSY.message
  const turns = dialogue.contributions.filter(
    (turn) => turn.thread_id === thread.id,
  )
  const byId = new Map(turns.map((turn) => [turn.id, turn]))
  const pending = pendingResolution(dialogue, thread.id)

  const send = () => {
    const text = message.trim()
    if (!text) return
    setError(null)
    focused
      .messageDialogueThread(thread.id, text)
      .then(() => setMessage(""))
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "Could not send message",
        ),
      )
  }

  return (
    <div
      data-testid="dialogue-conversation"
      className="ep-enter mx-auto flex min-h-full w-full max-w-[640px] flex-1 flex-col gap-3 pt-6"
    >
      <div>
        <SectionLabel>Thread</SectionLabel>
        <h2 className="mt-1 text-[13px] font-semibold leading-snug">
          {thread.title}
        </h2>
        <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--ink-2)]">
          {thread.question}
        </p>
      </div>
      <div className="space-y-2.5">
        {turns.map((turn) => {
          const who = names.get(turn.author_id)
          const target = turn.reply_to ? byId.get(turn.reply_to) : null
          const replyName = target
            ? (names.get(target.author_id)?.label ?? null)
            : null
          return (
            <TurnBubble
              key={turn.id}
              turn={turn}
              name={who?.label ?? turn.author_id}
              color={who?.color}
              replyName={replyName}
            />
          )
        })}
      </div>
      {pending && (
        <ResolutionCard
          resolution={pending}
          busy={busy}
          onDecide={(action, edits) => {
            setError(null)
            focused
              .decideDialogueThread(pending.id, action, edits)
              .catch((cause) =>
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not record the decision",
                ),
              )
          }}
        />
      )}
      <div className="sticky bottom-0 mt-auto bg-[var(--bg)] pb-5 pt-2">
        <div className="relative">
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            rows={2}
            disabled={busy !== null}
            aria-label="Message the panel"
            placeholder="Challenge the panel: why do you hold that position?"
            className="field min-h-9 w-full resize-none py-2 pl-3 pr-12 text-[12.5px] leading-snug placeholder:text-[var(--mute)]"
          />
          <button
            type="button"
            aria-label="Send"
            disabled={busy !== null || !message.trim()}
            onClick={send}
            className="absolute bottom-2 right-2 grid size-7 place-items-center rounded-full bg-[var(--node)] text-white transition-opacity hover:opacity-90 disabled:opacity-35"
          >
            {sending ? (
              <Spinner className="size-3.5" />
            ) : (
              <ArrowUp size={14} strokeWidth={2.2} aria-hidden />
            )}
          </button>
        </div>
        {error && <ErrorLine>{error}</ErrorLine>}
      </div>
    </div>
  )
}

function PerspectivesRail({
  session,
  dialogue,
}: {
  session: SessionState
  dialogue: DialogueState
}) {
  const names = useNames(session, dialogue)
  const revisedBy = useMemo(() => {
    const map = new Map<string, number>()
    for (const reflection of dialogue.reflections) {
      if (reflection.decision === "revise") {
        map.set(
          reflection.perspective_id,
          (map.get(reflection.perspective_id) ?? 0) + 1,
        )
      }
    }
    return map
  }, [dialogue.reflections])
  return (
    <aside
      aria-label="Perspectives"
      className="shrink-0 border-t border-[var(--line)] bg-[var(--panel)] px-4 py-4 lg:w-[280px] lg:overflow-y-auto lg:border-l lg:border-t-0"
    >
      <SectionLabel>Perspectives</SectionLabel>
      <div className="mt-2 space-y-3">
        {dialogue.perspective_states.map((state) => {
          const who = names.get(state.id)
          const revisions = revisedBy.get(state.id) ?? 0
          return (
            <div
              key={state.id}
              className="border-b border-[var(--line)] pb-3 last:border-b-0 last:pb-0"
            >
              <p className="flex items-baseline gap-1.5 text-[12px] font-semibold">
                <PerspectiveDot color={who?.color} />
                {who?.label ?? state.profile.focus}
                {revisions > 0 && (
                  <span className="font-normal text-[var(--mute)]">
                    · {revisions} revision{revisions === 1 ? "" : "s"}
                  </span>
                )}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                {state.profile.perspective.position}
              </p>
            </div>
          )
        })}
      </div>
    </aside>
  )
}

function ReportModal({
  final,
  onClose,
}: {
  final: boolean
  onClose: () => void
}) {
  const focused = useFocusedPanel()
  const [report, setReport] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    focused
      .fetchDialogueReport()
      .then((response) => {
        if (!cancelled) setReport(response.report)
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(
            cause instanceof Error ? cause.message : "Could not load report",
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [focused])
  return (
    <ModalShell title={final ? "Final report" : "Draft report"} onClose={onClose}>
      {error && <ErrorLine>{error}</ErrorLine>}
      {!report && !error && (
        <p className="flex items-center gap-2 text-[12px] text-[var(--mute)]">
          <Spinner /> Synthesizing
        </p>
      )}
      {report && (
        <article className="[&_h1]:text-[15px] [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-[12.5px] [&_h3]:font-semibold [&_li]:my-1 [&_li]:text-[12.5px] [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mt-2 [&_p]:text-[12.5px] [&_p]:leading-relaxed">
          <Markdown>{report}</Markdown>
        </article>
      )}
    </ModalShell>
  )
}

export function StageDialogue() {
  const session = useFocusedStore((s) => s.session)
  const [reportOpen, setReportOpen] = useState(false)
  if (!session) return null
  const dialogue = session.dialogue

  // The panel stage is only entered after the opening phase completes;
  // index.tsx owns the intro dialog. A transient render without dialogue
  // state shows nothing rather than a duplicate dialog.
  if (!dialogue || dialogue.stage === "opening") {
    return <main aria-label="Panel setup" className="flex-1" />
  }

  if (dialogue.stage === "selection") {
    return (
      <main className="flex-1 px-4 pb-10">
        <DialogueSelection session={session} dialogue={dialogue} />
      </main>
    )
  }

  const threads = latestThreads(dialogue)
  const active =
    threads.find((thread) => thread.status === "open") ??
    (dialogue.active_thread_id
      ? (threads.find(
          (thread) =>
            thread.id === dialogue.active_thread_id &&
            pendingResolution(dialogue, thread.id) !== null,
        ) ?? null)
      : null)
  const hasClosed = threads.some((thread) => thread.status === "closed")
  const allResolved =
    !active &&
    hasClosed &&
    !threads.some((thread) => thread.status === "suggested")

  return (
    <main className="flex min-h-0 flex-1 flex-col lg:max-h-[calc(100dvh-48px)] lg:flex-row lg:overflow-hidden">
      <DocumentPanel
        dialogue={dialogue}
        onReport={
          hasClosed && !allResolved ? () => setReportOpen(true) : null
        }
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto px-4">
        {active ? (
          <Conversation session={session} dialogue={dialogue} thread={active} />
        ) : (
          <ThreadPicker
            session={session}
            dialogue={dialogue}
            onReport={() => setReportOpen(true)}
          />
        )}
      </div>
      <PerspectivesRail session={session} dialogue={dialogue} />
      {reportOpen && (
        <ReportModal
          final={allResolved}
          onClose={() => setReportOpen(false)}
        />
      )}
    </main>
  )
}
