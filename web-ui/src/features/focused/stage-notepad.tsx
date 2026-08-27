"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ChevronRight, Plus, UserRound, X } from "lucide-react"

import { useFocusedPanel } from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import {
  NOTEPAD_LABELS,
  NOTEPAD_PARTS,
  type NotepadPart,
  type NotepadProposal,
  type NotepadState,
  type NotepadTurn,
  type Perspective,
  type SessionState,
} from "@/types/focused"
import { Button, EmptyLine, SectionLabel, Spinner } from "./ui"

const PART_PLACEHOLDERS: Record<NotepadPart, string> = {
  framing: "How you are framing the problem.",
  prior: "What is already known, and where it stops.",
  method: "How you would go about it.",
  expected: "What you expect to find, and why it would matter.",
}

function ErrorLine({ children }: { children: string }) {
  return (
    <p role="alert" className="mt-2 text-[12px] text-[var(--red)]">
      {children}
    </p>
  )
}

/* -------------------------------------------------------------------------- */
/* Column 1 - the notepad                                                     */
/* -------------------------------------------------------------------------- */

function PartField({
  part,
  value,
  versionId,
  onCommit,
}: {
  part: NotepadPart
  value: string
  versionId: string
  onCommit: (part: NotepadPart, text: string) => Promise<unknown>
}) {
  // "Changes take effect as they are typed; there is nothing to save."
  // The textarea owns the keystrokes; the server catches up behind them.
  const [text, setText] = useState(value)
  const timer = useRef<number | undefined>(undefined)
  const pending = useRef(false)

  useEffect(() => {
    if (!pending.current) setText(value)
  }, [value, versionId])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const change = (next: string) => {
    setText(next)
    pending.current = true
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      void onCommit(part, next).finally(() => {
        pending.current = false
      })
    }, 450)
  }

  return (
    <div>
      <label
        htmlFor={`notepad-${part}`}
        className="text-[11px] font-medium text-[var(--ink-2)]"
      >
        {NOTEPAD_LABELS[part]}
      </label>
      <textarea
        id={`notepad-${part}`}
        data-testid={`notepad-part-${part}`}
        value={text}
        rows={2}
        onChange={(event) => change(event.target.value)}
        placeholder={PART_PLACEHOLDERS[part]}
        className="field mt-1 min-h-14 w-full resize-none rounded-lg px-3 py-2 text-[12.5px] leading-relaxed [field-sizing:content]"
      />
    </div>
  )
}

function NotepadColumn({
  notepad,
  busy,
}: {
  notepad: NotepadState
  busy: string | null
}) {
  const focused = useFocusedPanel()
  const [error, setError] = useState<string | null>(null)
  const version =
    notepad.versions.find((item) => item.id === notepad.active_version_id) ??
    notepad.versions[0]

  const guard = (action: Promise<unknown>) => {
    setError(null)
    action.catch((cause) =>
      setError(cause instanceof Error ? cause.message : "Could not save"),
    )
  }

  const commit = useCallback(
    (part: NotepadPart, text: string) => focused.editNotepadPart(part, text),
    [focused],
  )

  if (!version) return null

  return (
    <section
      data-testid="notepad-panel"
      className="ep-enter panel flex min-h-0 flex-col rounded-xl px-4 py-3.5"
    >
      <SectionLabel>Notepad</SectionLabel>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {notepad.versions.map((item) => {
          const active = item.id === version.id
          return (
            <span key={item.id} className="flex items-center">
              <button
                type="button"
                data-testid={`notepad-version-${item.name}`}
                aria-pressed={active}
                disabled={busy !== null}
                onClick={() => guard(focused.switchNotepadVersion(item.id))}
                className="rounded-md border px-2 py-0.5 text-[11px] tabular-nums transition-colors"
                style={{
                  borderColor: active ? "var(--line-strong)" : "var(--line)",
                  color: active ? "var(--ink)" : "var(--mute)",
                  fontWeight: active ? 500 : 400,
                }}
              >
                {item.name}
              </button>
              {notepad.versions.length > 1 ? (
                <button
                  type="button"
                  aria-label={`Delete ${item.name}`}
                  disabled={busy !== null}
                  onClick={() => guard(focused.deleteNotepadVersion(item.id))}
                  className="ml-0.5 text-[var(--mute)] transition-opacity hover:opacity-70"
                >
                  <X size={11} strokeWidth={2.2} />
                </button>
              ) : null}
            </span>
          )
        })}
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => guard(focused.addNotepadVersion(true))}
          className="ml-1 flex items-center gap-1 rounded-md border border-dashed border-[var(--line)] px-2 py-0.5 text-[11px] text-[var(--mute)] transition-colors hover:border-[var(--line-strong)] hover:text-[var(--ink-2)]"
        >
          {busy === "Starting a version" ? (
            <Spinner className="size-3" />
          ) : (
            <Plus size={11} strokeWidth={2.2} />
          )}
          Version
        </button>
      </div>
      <p className="mt-1.5 text-[10.5px] text-[var(--mute)]">
        Edits take effect as you type. Versions are independent.
      </p>
      <div className="mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {NOTEPAD_PARTS.map((part) => (
          <PartField
            key={part}
            part={part}
            versionId={version.id}
            value={version.doc[part]}
            onCommit={commit}
          />
        ))}
      </div>
      {error ? <ErrorLine>{error}</ErrorLine> : null}
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Column 2 - the conversation                                                */
/* -------------------------------------------------------------------------- */

function TurnRow({
  turn,
  color,
}: {
  turn: NotepadTurn
  color: string | undefined
}) {
  const isResearcher = turn.role === "researcher"
  const isSummary = turn.role === "summary"
  return (
    <div className={isResearcher ? "flex justify-end" : ""}>
      <div
        className={
          isResearcher
            ? "w-fit max-w-[78%] rounded-xl border border-[var(--line)] bg-[color-mix(in_srgb,var(--node)_6%,var(--panel))] px-3 py-2.5"
            : isSummary
              ? "rounded-xl border border-dashed border-[var(--line)] px-3 py-2.5"
              : "rounded-xl border border-[var(--line)] px-3 py-2.5"
        }
      >
        <div className="mb-1 flex items-baseline gap-1.5">
          {!isResearcher && !isSummary ? (
            <UserRound
              aria-hidden
              size={12}
              strokeWidth={2.2}
              className="shrink-0"
              style={{ color: color ?? "var(--ink-2)" }}
            />
          ) : null}
          <span className="text-[11px] font-medium text-[var(--ink-2)]">
            {isResearcher ? "You" : turn.author_label}
          </span>
        </div>
        <p className="text-[12.5px] leading-relaxed">{turn.text}</p>
      </div>
    </div>
  )
}

function ProposalCard({
  proposal,
  live,
  guided,
  busy,
}: {
  proposal: NotepadProposal
  live: string
  guided: boolean
  busy: string | null
}) {
  const focused = useFocusedPanel()
  // What the panel contributes, apart from the wording it was raised
  // against. Approval folds this onto whatever the part says at that moment.
  const addition = proposal.addition || proposal.proposed_text
  const merged = live ? `${live} ${addition}` : addition
  // One state, not an `editing` flag beside a draft string: the draft is
  // created when the editor opens, so it can never hold wording from
  // before the researcher's latest edit to this part.
  const [draft, setDraft] = useState<string | null>(null)
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const deciding = busy === "Recording your decision"

  const decide = (
    action: "approve" | "edit" | "reject",
    extra?: { text?: string; reason?: string },
  ) => {
    setError(null)
    focused
      .decideNotepadProposal(proposal.id, action, extra)
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "Could not record that",
        ),
      )
  }

  if (!guided) {
    // The baseline seam: one button, blind append, no diff and no evidence.
    return (
      <div
        data-testid="notepad-proposal"
        className="ep-card-enter rounded-xl border border-dashed border-[var(--line)] px-3 py-2.5"
      >
        <p className="text-[11px] text-[var(--mute)]">
          {`Adds the summary above to ${NOTEPAD_LABELS[proposal.part]}.`}
        </p>
        <div className="mt-2.5">
          <Button
            variant="primary"
            size="sm"
            disabled={busy !== null}
            onClick={() => decide("approve")}
          >
            {deciding ? <Spinner /> : null}Copy into the notepad
          </Button>
        </div>
        {error ? <ErrorLine>{error}</ErrorLine> : null}
      </div>
    )
  }

  return (
    <div
      data-testid="notepad-proposal"
      className="ep-card-enter rounded-xl border border-[var(--line)] px-3 py-2.5"
    >
      <SectionLabel>
        {`Proposed for ${NOTEPAD_LABELS[proposal.part]} - your review`}
      </SectionLabel>
      {/* The notepad stays editable while this sits here, so the diff reads
          the live wording: approval folds the addition onto it. */}
      {live ? (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--mute)] line-through">
          {live}
        </p>
      ) : null}
      <p className="mt-1 text-[12.5px] leading-relaxed">
        {live ? `${live} ${addition}` : addition}
      </p>
      {proposal.reason ? (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ink-2)]">
          {proposal.reason}
        </p>
      ) : null}
      {proposal.citations.length > 0 ? (
        <p className="mt-1 text-[10.5px] text-[var(--mute)]">
          {`Cites ${proposal.citations.join(", ")}`}
        </p>
      ) : null}
      {draft !== null ? (
        <div className="mt-2.5 space-y-2">
          <textarea
            value={draft}
            rows={4}
            aria-label="Your wording"
            onChange={(event) => setDraft(event.target.value)}
            className="field w-full resize-none rounded-lg px-3 py-2 text-[12.5px] leading-relaxed"
          />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={busy !== null || !draft.trim()}
              onClick={() => decide("edit", { text: draft.trim() })}
            >
              {deciding ? <Spinner /> : null}Accept with this wording
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() => setDraft(null)}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={busy !== null}
            onClick={() => decide("approve")}
          >
            {deciding ? <Spinner /> : null}Approve
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy !== null}
            onClick={() => setDraft(merged)}
          >
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy !== null}
            onClick={() => decide("reject", { reason: reason.trim() })}
          >
            Reject
          </Button>
          <input
            value={reason}
            aria-label="Why you are rejecting"
            placeholder="Why? The panel reads this."
            onChange={(event) => setReason(event.target.value)}
            className="field min-w-0 flex-1 rounded-lg px-2.5 py-1.5 text-[12px]"
          />
        </div>
      )}
      {error ? <ErrorLine>{error}</ErrorLine> : null}
    </div>
  )
}

function ConversationColumn({
  session,
  notepad,
  busy,
}: {
  session: SessionState
  notepad: NotepadState
  busy: string | null
}) {
  const focused = useFocusedPanel()
  const [message, setMessage] = useState("")
  const [turns, setTurns] = useState(4)
  const [part, setPart] = useState<NotepadPart>("framing")
  const [error, setError] = useState<string | null>(null)
  const guided = session.arm === "guided"

  const colors = useMemo(() => {
    const map = new Map<string, string>()
    for (const perspective of session.perspectives) {
      map.set(perspective.id, perspective.color)
    }
    return map
  }, [session.perspectives])

  const pending = notepad.proposals.filter((item) => item.status === "pending")
  const liveDoc =
    notepad.versions.find((item) => item.id === notepad.active_version_id)
      ?.doc ?? notepad.versions[0]?.doc
  const guard = (action: Promise<unknown>) => {
    setError(null)
    action.catch((cause) =>
      setError(cause instanceof Error ? cause.message : "Could not do that"),
    )
  }

  const send = () => {
    const text = message.trim()
    if (!text) return
    setMessage("")
    guard(focused.askNotepad(text))
  }

  return (
    <section
      data-testid="notepad-conversation"
      className="ep-enter panel flex min-h-0 flex-col rounded-xl px-4 py-3.5"
    >
      <SectionLabel>Conversation</SectionLabel>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-[var(--mute)]">In the chat</span>
        {session.perspectives.map((perspective) => {
          const inChat = notepad.in_chat.includes(perspective.id)
          return (
            <button
              key={perspective.id}
              type="button"
              disabled={busy !== null}
              aria-pressed={inChat}
              aria-label={`${inChat ? "Remove" : "Add"} ${perspective.name}`}
              onClick={() =>
                guard(
                  focused.setNotepadParticipant(perspective.id, !inChat),
                )
              }
              className="flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors"
              style={{
                borderColor: inChat ? "var(--line-strong)" : "var(--line)",
                color: inChat ? "var(--ink)" : "var(--mute)",
              }}
            >
              <UserRound
                aria-hidden
                size={11}
                strokeWidth={2.2}
                style={{ color: inChat ? perspective.color : "var(--mute)" }}
              />
              {perspective.name}
              {inChat ? (
                <X size={10} strokeWidth={2.2} />
              ) : (
                <Plus size={10} strokeWidth={2.2} />
              )}
            </button>
          )
        })}
      </div>

      <div className="mt-3 min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
        {notepad.turns.length === 0 && pending.length === 0 ? (
          <EmptyLine>
            No one has spoken yet. Let the agents discuss, or ask them
            something.
          </EmptyLine>
        ) : null}
        {notepad.turns.map((turn) => (
          <TurnRow
            key={turn.id}
            turn={turn}
            color={turn.author_id ? colors.get(turn.author_id) : undefined}
          />
        ))}
        {pending.map((proposal) => (
          <ProposalCard
            key={proposal.id}
            proposal={proposal}
            live={liveDoc?.[proposal.part] ?? ""}
            guided={guided}
            busy={busy}
          />
        ))}
      </div>

      <div className="mt-3 space-y-2 border-t border-[var(--line)] pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={busy !== null || notepad.in_chat.length === 0}
            onClick={() => guard(focused.discussNotepad(turns))}
          >
            {busy === "Agents discussing" ? <Spinner /> : null}Let agents
            discuss
          </Button>
          <input
            type="number"
            min={1}
            max={8}
            value={turns}
            aria-label="Turns"
            onChange={(event) =>
              setTurns(Math.min(8, Math.max(1, Number(event.target.value) || 1)))
            }
            className="field w-14 rounded-lg px-2 py-1 text-[12px] tabular-nums"
          />
          <Button
            variant="outline"
            size="sm"
            disabled={busy !== null}
            onClick={() => guard(focused.summarizeNotepad(part))}
          >
            {busy === "Summarizing" ? <Spinner /> : null}Summarize so far
          </Button>
          <select
            value={part}
            aria-label="Which part the summary goes to"
            onChange={(event) => setPart(event.target.value as NotepadPart)}
            className="field rounded-lg px-2 py-1 text-[12px]"
          >
            {NOTEPAD_PARTS.map((item) => (
              <option key={item} value={item}>
                {NOTEPAD_LABELS[item]}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy !== null || notepad.turns.length === 0}
            onClick={() => guard(focused.clearNotepadChat())}
          >
            {busy === "Clearing the chat" ? <Spinner /> : null}Clear
          </Button>
        </div>
        <div className="relative">
          <textarea
            value={message}
            rows={2}
            aria-label="Message the panel"
            placeholder="Ask the panel something..."
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            className="field min-h-9 w-full resize-none rounded-lg py-2 pl-3 pr-12 text-[12.5px] leading-snug"
          />
          <button
            type="button"
            aria-label="Send"
            disabled={busy !== null || !message.trim()}
            onClick={send}
            className="absolute bottom-2 right-2 grid size-7 place-items-center rounded-full bg-[var(--node)] text-white transition-opacity hover:opacity-90 disabled:opacity-35"
          >
            {busy === "Sending" ? (
              <Spinner className="size-3.5" />
            ) : (
              <ChevronRight
                size={14}
                strokeWidth={2.2}
                aria-hidden
                className="-rotate-90"
              />
            )}
          </button>
        </div>
      </div>
      {error ? <ErrorLine>{error}</ErrorLine> : null}
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Column 3 - the perspectives                                                */
/* -------------------------------------------------------------------------- */

function PerspectiveCard({
  perspective,
  inChat,
  busy,
}: {
  perspective: Perspective
  inChat: boolean
  busy: string | null
}) {
  const focused = useFocusedPanel()
  const [open, setOpen] = useState(false)
  const source = perspective.facets.explanation ?? perspective.facets.scope

  return (
    <div className="ep-card-enter rounded-xl border border-[var(--line)] px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-baseline gap-1.5 text-left"
        >
          <UserRound
            aria-hidden
            size={12}
            strokeWidth={2.2}
            className="shrink-0"
            style={{ color: perspective.color }}
          />
          <span className="truncate text-[12.5px] font-medium">
            {perspective.name}
          </span>
        </button>
        <button
          type="button"
          disabled={busy !== null}
          aria-label={`${inChat ? "Remove from" : "Add to"} the chat`}
          onClick={() =>
            focused.setNotepadParticipant(perspective.id, !inChat)
          }
          className="shrink-0 rounded-md border px-1.5 py-0.5 text-[10.5px] transition-colors"
          style={{
            borderColor: inChat ? "var(--line-strong)" : "var(--line)",
            color: inChat ? "var(--ink)" : "var(--mute)",
          }}
        >
          {inChat ? "in chat" : "add"}
        </button>
      </div>
      {open && source ? (
        <div className="mt-2 space-y-1.5">
          <p className="text-[12px] leading-relaxed text-[var(--ink-2)]">
            {source.text}
          </p>
          {source.paper_id ? (
            <p className="text-[10.5px] text-[var(--mute)]">
              {`Source paper ${source.paper_id}`}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function PerspectivesColumn({
  session,
  notepad,
  busy,
  onCollapse,
}: {
  session: SessionState
  notepad: NotepadState
  busy: string | null
  onCollapse: () => void
}) {
  return (
    <section
      data-testid="notepad-perspectives"
      className="ep-enter panel flex min-h-0 flex-col rounded-xl px-4 py-3.5"
    >
      <div className="flex items-center justify-between">
        <SectionLabel>Perspectives</SectionLabel>
        <button
          type="button"
          aria-label="Collapse the perspectives"
          onClick={onCollapse}
          className="text-[var(--mute)] transition-opacity hover:opacity-70"
        >
          <ChevronRight size={14} strokeWidth={2.2} />
        </button>
      </div>
      <div className="mt-2.5 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {session.perspectives.map((perspective) => (
          <PerspectiveCard
            key={perspective.id}
            perspective={perspective}
            inChat={notepad.in_chat.includes(perspective.id)}
            busy={busy}
          />
        ))}
        <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-2.5">
          <p className="text-[11px] text-[var(--mute)]">
            Build a new one from a cluster on the search step. It joins the
            chat when you return.
          </p>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* The stage                                                                  */
/* -------------------------------------------------------------------------- */

export function StageNotepad({ session }: { session: SessionState }) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((s) => s.busy)
  const [collapsed, setCollapsed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const notepad = session.notepad

  if (!notepad) {
    return (
      <main className="mx-auto w-full max-w-[640px] px-4 py-10">
        <section className="ep-enter panel rounded-xl px-4 py-3.5">
          <SectionLabel>Group chat</SectionLabel>
          <p className="mt-1.5 text-[12.5px] leading-relaxed">
            Your notepad carries the four parts you wrote. The panel discusses
            them, and nothing reaches the notepad without your decision.
          </p>
          <div className="mt-3">
            <Button
              variant="primary"
              size="sm"
              disabled={busy !== null || session.perspectives.length === 0}
              onClick={() => {
                setError(null)
                focused
                  .startNotepad()
                  .catch((cause) =>
                    setError(
                      cause instanceof Error
                        ? cause.message
                        : "Could not open the chat",
                    ),
                  )
              }}
            >
              {busy === "Opening the group chat" ? <Spinner /> : null}Open the
              group chat
            </Button>
          </div>
          {session.perspectives.length === 0 ? (
            <EmptyLine>Build at least one Perspective first.</EmptyLine>
          ) : null}
          {error ? <ErrorLine>{error}</ErrorLine> : null}
        </section>
      </main>
    )
  }

  return (
    <main
      className={`grid min-h-0 flex-1 gap-3 px-4 pb-4 lg:max-h-[calc(100dvh-48px)] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden ${
        collapsed
          ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_40px]"
          : "lg:grid-cols-3"
      }`}
    >
      <NotepadColumn notepad={notepad} busy={busy} />
      <ConversationColumn session={session} notepad={notepad} busy={busy} />
      {collapsed ? (
        <button
          type="button"
          aria-label="Expand the perspectives"
          onClick={() => setCollapsed(false)}
          className="panel hidden rounded-xl text-[var(--mute)] lg:block"
        >
          <span className="[writing-mode:vertical-rl] text-[11px]">
            Perspectives
          </span>
        </button>
      ) : (
        <PerspectivesColumn
          session={session}
          notepad={notepad}
          busy={busy}
          onCollapse={() => setCollapsed(true)}
        />
      )}
    </main>
  )
}
