"use client"

import { useMemo, useState } from "react"
import Markdown from "react-markdown"

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
import {
  Button,
  EmptyLine,
  ModalShell,
  SectionLabel,
  Spinner,
} from "./ui"

const KIND_LABELS: Record<CanonContribution["kind"], string> = {
  answer: "Answers the question",
  reply: "Reply",
  support: "Cites evidence",
  challenge: "Challenge",
}

const DECISION_HINT =
  "Accept the resolution to close this Thread, edit its wording first, or keep the discussion open."

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

function ProgressTrail() {
  const busy = useFocusedStore((s) => s.busy)
  const items = useFocusedStore((s) => s.searchProgress)
  if (!busy) return null
  const recent = items.slice(-6)
  return (
    <div className="mt-3 space-y-1 border-t border-[var(--line)] pt-3">
      {recent.map((item) => (
        <p
          key={item.sequence}
          className="truncate text-[11.5px] leading-relaxed text-[var(--mute)]"
        >
          {"author" in item && item.author ? `${item.author}: ` : ""}
          {item.message}
        </p>
      ))}
      <p className="flex items-center gap-2 text-[11.5px] text-[var(--mute)]">
        <Spinner /> {busy}
      </p>
    </div>
  )
}

function DialogueOpening() {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const [error, setError] = useState<string | null>(null)
  return (
    <section className="mx-auto mt-6 w-full max-w-[560px] rounded-lg border border-[var(--line)] bg-[var(--panel)] p-5">
      <SectionLabel>Set up the panel</SectionLabel>
      <p className="mt-2 text-[13px] leading-relaxed text-[var(--ink-2)]">
        Each Perspective proposes a scientific claim from its literature,
        reviews a peer&apos;s proposal, and refines its own. You then choose
        which refined directions the Working Document should organize.
      </p>
      <div className="mt-4 flex items-center gap-2">
        <Button
          variant="primary"
          disabled={busy !== null}
          onClick={() => {
            setError(null)
            focused
              .startDialogue()
              .catch((cause) =>
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not start the deliberation",
                ),
              )
          }}
        >
          {busy ? <Spinner /> : null} Start deliberation
        </Button>
      </div>
      {error && (
        <p className="mt-3 text-[12px] text-[var(--red)]">{error}</p>
      )}
      <ProgressTrail />
    </section>
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
    <label className="block cursor-pointer rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4 transition-colors hover:border-[var(--line-strong)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="size-2 rounded-full"
            style={{ background: color ?? "var(--ink-2)" }}
          />
          <span className="text-[12px] font-semibold">{name}</span>
        </div>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 accent-[var(--ink)]"
        />
      </div>
      <p className="mt-2 text-[13.5px] font-medium leading-snug">
        {refinement.proposal.claim.text}
      </p>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-[var(--ink-2)]">
        {refinement.proposal.argument.reasoning}
      </p>
      {review && (
        <div className="mt-3 border-t border-[var(--line)] pt-2.5">
          <p className="text-[11px] font-medium text-[var(--mute)]">
            Peer review
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--ink-2)]">
            {review.response}
          </p>
          {review.question && (
            <p className="mt-1 text-[12.5px] italic text-[var(--ink-2)]">
              {review.question}
            </p>
          )}
        </div>
      )}
      <div className="mt-3 border-t border-[var(--line)] pt-2.5">
        <p className="text-[11px] font-medium text-[var(--mute)]">
          Refinement · {refinement.decision === "revise" ? "Revised" : "Unchanged"}
        </p>
        <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--ink-2)]">
          {refinement.reason}
        </p>
        {refinement.open_question && (
          <p className="mt-1 text-[12.5px] text-[var(--ink-2)]">
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
  const [picked, setPicked] = useState<string[]>(() =>
    [...new Set(dialogue.refinements.map((r) => r.proposal_id))],
  )
  const [error, setError] = useState<string | null>(null)
  const reviewByProposal = useMemo(() => {
    const map = new Map<string, { response: string; question: string | null }>()
    for (const review of dialogue.reviews) {
      map.set(review.proposal_id, {
        response: review.response,
        question: review.question,
      })
    }
    return map
  }, [dialogue.reviews])

  return (
    <section className="mx-auto mt-6 w-full max-w-[880px]">
      <SectionLabel>Choose the directions</SectionLabel>
      <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--ink-2)]">
        The selected refinements become the objectives of the shared Working
        Document.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
          {busy ? <Spinner /> : null} Create Working Document
        </Button>
        <span className="text-[12px] text-[var(--mute)]">
          {picked.length} of {dialogue.refinements.length} selected
        </span>
      </div>
      {error && <p className="mt-2 text-[12px] text-[var(--red)]">{error}</p>}
      <ProgressTrail />
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
    <aside className="shrink-0 border-b border-[var(--line)] bg-[var(--panel)] px-4 py-4 lg:w-[300px] lg:overflow-y-auto lg:border-b-0 lg:border-r">
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
              className="text-[12.5px] leading-relaxed text-[var(--ink-2)]"
            >
              {objective.text}
            </li>
          ))}
        </ol>
      </div>
      <div className="mt-3 space-y-3">
        {document.sections.map((section) => (
          <div
            key={section.id}
            className="border-t border-[var(--line)] pt-2.5"
          >
            <p className="text-[12px] font-semibold">{section.title}</p>
            <p className="mt-1 whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--ink-2)]">
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
                className="break-all text-[11.5px] text-[var(--mute)]"
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
            Final report
          </Button>
        </div>
      )}
    </aside>
  )
}

function ThreadPicker({
  session,
  dialogue,
}: {
  session: SessionState
  dialogue: DialogueState
}) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const [error, setError] = useState<string | null>(null)
  const threads = latestThreads(dialogue)
  const suggested = threads.filter((thread) => thread.status === "suggested")
  const closed = threads.filter((thread) => thread.status === "closed")
  return (
    <div className="mx-auto w-full max-w-[640px] py-6">
      <SectionLabel>Threads</SectionLabel>
      <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--ink-2)]">
        Each Thread is one scientific issue. Opening a Thread runs the
        discussion: every Perspective answers, the panel challenges and
        replies, and the moderator records where it ended for your review.
      </p>
      <div className="mt-4 space-y-2.5">
        {suggested.map((thread) => (
          <div
            key={thread.id}
            className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4"
          >
            <p className="text-[13px] font-semibold">{thread.title}</p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--ink-2)]">
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
                  focused
                    .openDialogueThread(thread.id)
                    .catch((cause) =>
                      setError(
                        cause instanceof Error
                          ? cause.message
                          : "Could not open the Thread",
                      ),
                    )
                }}
              >
                Open Thread
              </Button>
            </div>
          </div>
        ))}
        {suggested.length === 0 && (
          <EmptyLine>
            No suggested Threads remain. Review the final report from the
            Working Document panel.
          </EmptyLine>
        )}
      </div>
      {closed.length > 0 && (
        <div className="mt-6">
          <SectionLabel>Resolved</SectionLabel>
          <div className="mt-2 space-y-2">
            {closed.map((thread) => {
              const resolution = latestResolution(
                dialogue,
                thread.resolution_id,
              )
              return (
                <div
                  key={thread.id}
                  className="rounded-lg border border-[var(--line)] p-3.5"
                >
                  <p className="text-[12.5px] font-semibold">{thread.title}</p>
                  {resolution?.consensus && (
                    <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                      {resolution.consensus}
                    </p>
                  )}
                  {resolution?.open_question && (
                    <p className="mt-1 text-[12px] text-[var(--mute)]">
                      Open question: {resolution.open_question}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {error && <p className="mt-3 text-[12px] text-[var(--red)]">{error}</p>}
      <ProgressTrail />
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
    <div className={isResearcher ? "flex justify-end" : ""}>
      <div
        className={`${
          isResearcher
            ? "w-fit max-w-[78%] rounded-xl border border-[var(--line)] bg-[color-mix(in_srgb,var(--node)_6%,var(--panel))] px-3 py-2.5"
            : "rounded-xl border border-[var(--line)] bg-[var(--panel)] px-3 py-2.5"
        }`}
      >
        <div className="mb-1 flex items-baseline justify-between gap-3">
          <span className="flex items-center gap-1.5 text-[11px] font-semibold">
            {!isResearcher && (
              <span
                aria-hidden
                className="size-1.5 rounded-full"
                style={{ background: color ?? "var(--ink-2)" }}
              />
            )}
            {name}
          </span>
          <span className="text-[10.5px] text-[var(--mute)]">
            {KIND_LABELS[turn.kind]}
            {replyName ? ` · to ${replyName}` : ""}
          </span>
        </div>
        <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--ink)]">
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

function ResolutionCard({
  resolution,
  onDecide,
  busy,
}: {
  resolution: CanonResolution
  onDecide: (
    action: "close" | "edit_close" | "keep_open",
    consensus?: string,
  ) => void
  busy: string | null
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(resolution.consensus ?? "")
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4">
      <SectionLabel>Thread resolution · your review</SectionLabel>
      <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--mute)]">
        {DECISION_HINT}
      </p>
      <div className="mt-2.5 space-y-2">
        {resolution.consensus && (
          <p className="text-[13px] leading-relaxed">
            <span className="font-semibold">Consensus.</span>{" "}
            {resolution.consensus}
          </p>
        )}
        {resolution.disagreement && (
          <p className="text-[13px] leading-relaxed">
            <span className="font-semibold">Disagreement.</span>{" "}
            {resolution.disagreement}
          </p>
        )}
        {resolution.open_question && (
          <p className="text-[13px] leading-relaxed">
            <span className="font-semibold">Open question.</span>{" "}
            {resolution.open_question}
          </p>
        )}
      </div>
      {editing && (
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={3}
          className="mt-3 w-full resize-none rounded-lg border border-[var(--line)] bg-transparent px-3 py-2 text-[13px] leading-relaxed outline-none focus:border-[var(--line-strong)]"
          placeholder="Rewrite the consensus in your own words"
        />
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!editing ? (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={busy !== null}
              onClick={() => onDecide("close")}
            >
              Accept &amp; close
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null}
              onClick={() => setEditing(true)}
            >
              Edit &amp; close
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() => onDecide("keep_open")}
            >
              Keep open
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="primary"
              size="sm"
              disabled={busy !== null || !text.trim()}
              onClick={() => onDecide("edit_close", text.trim())}
            >
              Close with this wording
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
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-3 py-6">
      <div>
        <SectionLabel>Thread</SectionLabel>
        <h2 className="mt-1 text-[14px] font-semibold leading-snug">
          {thread.title}
        </h2>
        <p className="mt-0.5 text-[12.5px] leading-relaxed text-[var(--ink-2)]">
          {thread.question}
        </p>
        {thread.context && (
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--mute)]">
            {thread.context}
          </p>
        )}
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
      <ProgressTrail />
      {pending && (
        <ResolutionCard
          resolution={pending}
          busy={busy}
          onDecide={(action, consensus) => {
            setError(null)
            focused
              .decideDialogueThread(
                pending.id,
                action,
                action === "edit_close" ? { consensus } : undefined,
              )
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
      <div className="flex items-end gap-2">
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
          placeholder="Challenge the panel: why do you hold that position?"
          className="min-h-9 w-full flex-1 resize-none rounded-lg border border-[var(--line)] bg-transparent px-3 py-2 text-[13px] leading-snug outline-none focus:border-[var(--line-strong)]"
        />
        <Button
          variant="primary"
          size="sm"
          disabled={busy !== null || !message.trim()}
          onClick={send}
        >
          Send
        </Button>
      </div>
      {error && <p className="text-[12px] text-[var(--red)]">{error}</p>}
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
    <aside className="shrink-0 border-t border-[var(--line)] bg-[var(--panel)] px-4 py-4 lg:w-[280px] lg:overflow-y-auto lg:border-l lg:border-t-0">
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
              <p className="flex items-center gap-1.5 text-[12px] font-semibold">
                <span
                  aria-hidden
                  className="size-1.5 rounded-full"
                  style={{ background: who?.color ?? "var(--ink-2)" }}
                />
                {who?.label ?? state.profile.focus}
                <span className="font-normal text-[var(--mute)]">
                  {revisions > 0
                    ? ` · ${revisions} revision${revisions === 1 ? "" : "s"}`
                    : ""}
                </span>
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

function ReportModal({ onClose }: { onClose: () => void }) {
  const focused = useFocusedPanel()
  const [report, setReport] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useMemo(() => {
    focused
      .fetchDialogueReport()
      .then((response) => setReport(response.report))
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "Could not load report",
        ),
      )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <ModalShell title="Final report" onClose={onClose}>
      {error && <p className="text-[12px] text-[var(--red)]">{error}</p>}
      {!report && !error && (
        <p className="flex items-center gap-2 text-[12.5px] text-[var(--mute)]">
          <Spinner /> Synthesizing…
        </p>
      )}
      {report && (
        <article className="[&_h1]:text-[16px] [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-[12.5px] [&_h3]:font-semibold [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mt-2 [&_p]:text-[12.5px] [&_p]:leading-relaxed">
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

  if (!dialogue || dialogue.stage === "opening") {
    return (
      <main className="flex-1 px-4 pb-10">
        <DialogueOpening />
      </main>
    )
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

  return (
    <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <DocumentPanel
        dialogue={dialogue}
        onReport={hasClosed ? () => setReportOpen(true) : null}
      />
      <div className="min-w-0 flex-1 overflow-y-auto px-4">
        {active ? (
          <Conversation
            session={session}
            dialogue={dialogue}
            thread={active}
          />
        ) : (
          <ThreadPicker session={session} dialogue={dialogue} />
        )}
      </div>
      <PerspectivesRail session={session} dialogue={dialogue} />
      {reportOpen && <ReportModal onClose={() => setReportOpen(false)} />}
    </main>
  )
}
