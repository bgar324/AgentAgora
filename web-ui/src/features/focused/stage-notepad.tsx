"use client"

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import {
  ArrowUp,
  Check,
  ChevronRight,
  Clipboard,
  Plus,
  Trash2,
  UserRound,
  X,
} from "lucide-react"

import { useFocusedPanel } from "@/hooks/use-focused"
import { notepadDraftKey, useFocusedStore } from "@/store/focused"
import {
  MAX_PERSPECTIVES,
  NOTEPAD_LABELS,
  NOTEPAD_PARTS,
  type DiscussionTopic,
  type NotepadPart,
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

function PartField({
  part,
  value,
  draft,
  versionId,
  onCommit,
  onStage,
  onFocus,
  disabled,
  readOnly,
}: {
  part: NotepadPart
  value: string
  draft: string | undefined
  versionId: string
  onCommit: (
    versionId: string,
    part: NotepadPart,
    text: string,
  ) => Promise<unknown>
  onStage: (versionId: string, part: NotepadPart, text: string) => void
  onFocus: (part: NotepadPart) => void
  disabled: boolean
  readOnly: boolean
}) {
  const timer = useRef<number | undefined>(undefined)
  const pending = useRef<{ text: string; revision: number } | null>(null)
  const latestRevision = useRef(0)
  const commitRef = useRef(onCommit)
  const inFlight = useRef<Promise<void>>(Promise.resolve())
  const readOnlyRef = useRef(readOnly)

  useEffect(() => {
    commitRef.current = onCommit
  }, [onCommit])
  useLayoutEffect(() => {
    readOnlyRef.current = readOnly
    if (readOnly) {
      window.clearTimeout(timer.current)
      pending.current = null
    }
  }, [readOnly])


  const flush = useCallback(() => {
    window.clearTimeout(timer.current)
    if (readOnlyRef.current) {
      pending.current = null
      return inFlight.current
    }
    const next = pending.current
    if (next === null) return inFlight.current
    pending.current = null
    const operation = commitRef
      .current(versionId, part, next.text)
      .then(() => undefined)
      .catch((cause: unknown) => {
        if (
          !readOnlyRef.current &&
          pending.current === null &&
          latestRevision.current === next.revision
        ) {
          pending.current = next
        }
        throw cause
      })
    inFlight.current = operation
    void operation.catch(() => undefined)
    return operation
  }, [part, versionId])

  useEffect(
    () => () => {
      window.clearTimeout(timer.current)
    },
    [],
  )

  const change = (text: string) => {
    onStage(versionId, part, text)
    latestRevision.current += 1
    pending.current = { text, revision: latestRevision.current }
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      void flush().catch(() => undefined)
    }, 450)
  }

  return (
    <div>
      <label
        htmlFor={`notepad-${versionId}-${part}`}
        className="text-[11px] font-medium text-[var(--ink-2)]"
      >
        {NOTEPAD_LABELS[part]}
      </label>
      <textarea
        id={`notepad-${versionId}-${part}`}
        data-testid={`notepad-part-${part}`}
        value={draft ?? value}
        rows={2}
        onChange={(event) => change(event.target.value)}
        onFocus={() => onFocus(part)}
        disabled={disabled}
        placeholder={PART_PLACEHOLDERS[part]}
        className="field mt-1 min-h-14 w-full resize-none rounded-lg px-3 py-2 text-[12.5px] leading-relaxed [field-sizing:content]"
      />
    </div>
  )
}

type TopicSelection = { topicId: string; seed: number }

function TopicRow({
  topic,
  perspective,
  selected,
  disabled,
  readOnly,
  onSelect,
}: {
  topic: DiscussionTopic
  perspective: Perspective | undefined
  selected: boolean
  disabled: boolean
  readOnly: boolean
  onSelect: () => void
}) {
  return (
    <li>
      <button
        type="button"
        data-testid="notepad-topic"
        aria-pressed={readOnly ? undefined : selected}
        aria-expanded={readOnly ? selected : undefined}
        disabled={disabled}
        onClick={onSelect}
        className="w-full rounded-lg border px-2.5 py-2 text-left transition-colors disabled:cursor-default"
        style={{
          borderColor: selected ? "var(--line-strong)" : "var(--line)",
          background: selected
            ? "color-mix(in srgb, var(--node) 5%, transparent)"
            : "transparent",
        }}
      >
        <span className="flex items-baseline gap-1.5">
          <UserRound
            aria-hidden
            size={11}
            strokeWidth={2.2}
            className="shrink-0"
            style={{ color: perspective?.color ?? "var(--mute)" }}
          />
          <span className="min-w-0 flex-1 break-words text-[12px] font-medium">
            {topic.title}
          </span>
        </span>
        <span className="mt-0.5 block break-words text-[11px] leading-relaxed text-[var(--ink-2)]">
          {topic.question}
        </span>
        <span className="mt-0.5 block break-words text-[10.5px] text-[var(--mute)]">
          {perspective ? perspective.name : "Perspective no longer in the chat"}
        </span>
        {readOnly && selected ? (
          <span className="mt-2 block border-t border-[var(--line)] pt-2 text-[11px] leading-relaxed">
            <span className="block break-words">
              {`Tentative hypothesis. ${topic.hypothesis}`}
            </span>
            <span className="mt-1 block break-words text-[var(--ink-2)]">
              {topic.rationale}
            </span>
          </span>
        ) : null}
      </button>
    </li>
  )
}

function TopicList({
  session,
  notepad,
  busy,
  selectedTopicId,
  onSelect,
}: {
  session: SessionState
  notepad: NotepadState
  busy: string | null
  selectedTopicId: string | null
  onSelect: (topicId: string) => void
}) {
  const generateNotepadTopics = useFocusedPanel().generateNotepadTopics
  const [error, setError] = useState<string | null>(null)
  const attempted = useRef(new Set<string>())
  const [open, setOpen] = useState(false)
  const finished = notepad.final_snapshot !== null
  const generating = busy === "Generating topics"
  const topics = useMemo(() => notepad.topics ?? [], [notepad.topics])
  const perspectives = useMemo(
    () =>
      session.perspectives.filter(
        (perspective) => !perspective.id.startsWith("optimistic:"),
      ),
    [session.perspectives],
  )
  const covered = useMemo(
    () => new Set(topics.map((topic) => topic.perspective_id)),
    [topics],
  )
  const missing = perspectives.filter(
    (perspective) => !covered.has(perspective.id),
  )
  const signature = missing.map((perspective) => perspective.id).join(",")
  const ordered = useMemo(() => {
    const rank = new Map(
      perspectives.map((perspective, index) => [perspective.id, index]),
    )
    return [...topics].sort((left, right) => {
      const leftRank = rank.get(left.perspective_id) ?? perspectives.length
      const rightRank = rank.get(right.perspective_id) ?? perspectives.length
      if (leftRank !== rightRank) return leftRank - rightRank
      return left.created_at < right.created_at ? -1 : 1
    })
  }, [perspectives, topics])

  const generate = useCallback(() => {
    setError(null)
    void generateNotepadTopics().catch((cause: unknown) =>
      setError(
        cause instanceof Error ? cause.message : "Could not suggest topics",
      ),
    )
  }, [generateNotepadTopics])

  // One automatic attempt per set of uncovered Perspectives. A failure keeps
  // the signature marked so the surface offers Retry instead of looping.
  useEffect(() => {
    if (finished || signature === "" || busy !== null) return
    if (attempted.current.has(signature)) return
    attempted.current.add(signature)
    generate()
  }, [busy, finished, generate, signature])

  const showAction = !finished && (error !== null || missing.length > 0)

  return (
    <div data-testid="notepad-topics">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <SectionLabel>Discussion topics</SectionLabel>
          <button
            type="button"
            data-testid="notepad-topics-toggle"
            aria-expanded={open}
            aria-label={open ? "Hide discussion topics" : "Show discussion topics"}
            onClick={() => setOpen((value) => !value)}
            className="inline-flex shrink-0 items-center gap-0.5 rounded-md px-1 py-0.5 text-[11px] tabular-nums text-[var(--mute)] hover:text-[var(--ink-2)]"
          >
            {ordered.length}
            <ChevronRight
              aria-hidden
              size={12}
              strokeWidth={2}
              className="shrink-0 transition-transform"
              style={{ transform: open ? "rotate(90deg)" : undefined }}
            />
          </button>
        </div>
        {showAction ? (
          <button
            type="button"
            data-testid="notepad-topics-generate"
            disabled={busy !== null}
            onClick={generate}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--ink-2)] hover:border-[var(--line-strong)] disabled:opacity-40"
          >
            {generating ? <Spinner className="size-3" /> : null}
            {error !== null
              ? "Retry"
              : ordered.length === 0
                ? "Suggest topics"
                : "Suggest more"}
          </button>
        ) : null}
      </div>
      {!open ? null : ordered.length === 0 ? (
        <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--mute)]">
          {generating
            ? "Generating topics from the retrieved papers."
            : perspectives.length === 0
              ? "Build a Perspective to get topics."
              : "No topics yet."}
        </p>
      ) : (
        <ul className="mt-1.5 max-h-[280px] space-y-1.5 overflow-y-auto pr-1">
          {ordered.map((topic) => (
            <TopicRow
              key={topic.id}
              topic={topic}
              perspective={perspectives.find(
                (perspective) => perspective.id === topic.perspective_id,
              )}
              selected={topic.id === selectedTopicId}
              disabled={busy !== null}
              readOnly={finished}
              onSelect={() => onSelect(topic.id)}
            />
          ))}
        </ul>
      )}
      {open && generating && ordered.length > 0 ? (
        <p className="mt-1 text-[10.5px] text-[var(--mute)]">
          Adding topics for the newer Perspectives.
        </p>
      ) : null}
      {error ? <ErrorLine>{error}</ErrorLine> : null}
      {open ? (
        <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--mute)]">
          {finished
            ? "Proposals from this study. The topics stay with the final output."
            : "Select one to prepare a question."}
        </p>
      ) : null}
    </div>
  )
}

function NotepadColumn({
  session,
  notepad,
  busy,
  selectedTopicId,
  onTopicSelect,
  onPartFocus,
  onFinish,
}: {
  session: SessionState
  notepad: NotepadState
  busy: string | null
  selectedTopicId: string | null
  onTopicSelect: (topicId: string) => void
  onPartFocus: (part: NotepadPart) => void
  onFinish: () => void
}) {
  const focused = useFocusedPanel()
  const drafts = useFocusedStore((state) => state.notepadDrafts)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const finished = notepad.final_snapshot !== null
  const version =
    notepad.versions.find((item) => item.id === notepad.active_version_id) ??
    notepad.versions[0]

  const guard = (action: Promise<unknown>) => {
    setError(null)
    action.catch((cause) =>
      setError(cause instanceof Error ? cause.message : "Could not save"),
    )
  }

  const editNotepadPart = focused.editNotepadPart
  const stageNotepadPart = focused.stageNotepadPart
  const flushNotepadEdits = focused.flushNotepadEdits
  useEffect(() => {
    if (finished) return
    void flushNotepadEdits().then(
      () => setFieldErrors({}),
      (cause) =>
        setError(cause instanceof Error ? cause.message : "Could not save"),
    )
  }, [finished, flushNotepadEdits])
  const commit = useCallback(
    async (versionId: string, part: NotepadPart, text: string) => {
      const key = `${versionId}:${part}`
      try {
        const result = await editNotepadPart(versionId, part, text)
        setFieldErrors((current) => {
          if (!(key in current)) return current
          const next = { ...current }
          delete next[key]
          return next
        })
        return result
      } catch (cause) {
        setFieldErrors((current) => ({
          ...current,
          [key]: cause instanceof Error ? cause.message : "Could not save",
        }))
        throw cause
      }
    },
    [editNotepadPart],
  )

  if (!version) return null

  return (
    <section
      data-testid="notepad-panel"
      className="ep-enter panel flex min-h-0 flex-col rounded-xl px-4 py-3.5"
    >
      <TopicList
        session={session}
        notepad={notepad}
        busy={busy}
        selectedTopicId={selectedTopicId}
        onSelect={onTopicSelect}
      />
      <div className="my-3 border-t border-[var(--line)]" />
      <SectionLabel>Document</SectionLabel>
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
                onClick={() =>
                  guard(focused.switchNotepadVersion(item.id, finished))
                }
                className="rounded-md border px-2 py-0.5 text-[11px] tabular-nums transition-colors"
                style={{
                  borderColor: active ? "var(--line-strong)" : "var(--line)",
                  color: active ? "var(--ink)" : "var(--mute)",
                  fontWeight: active ? 500 : 400,
                }}
              >
                {item.name}
              </button>
              {notepad.versions.length > 1 && !finished ? (
                <button
                  type="button"
                  aria-label={`Delete ${item.name}`}
                  disabled={busy !== null}
                  onClick={() =>
                    guard(focused.deleteNotepadVersion(item.id))
                  }
                  className="ml-0.5 text-[var(--mute)] hover:text-[var(--red)]"
                >
                  <X size={11} strokeWidth={2.2} />
                </button>
              ) : null}
            </span>
          )
        })}
        {!finished ? (
          <>
            <button
              type="button"
              disabled={busy !== null}
              aria-label="Add version by copying the current version"
              title="Copy the current version"
              onClick={() => guard(focused.addNotepadVersion(true))}
              className="ml-1 flex items-center gap-1 rounded-md border border-dashed border-[var(--line)] px-2 py-0.5 text-[11px] text-[var(--mute)] hover:border-[var(--line-strong)] hover:text-[var(--ink-2)]"
            >
              {busy === "Starting a version" ? (
                <Spinner className="size-3" />
              ) : (
                <Plus size={11} strokeWidth={2.2} />
              )}
              Copy current
            </button>
            <button
              type="button"
              disabled={busy !== null}
              aria-label="Add a blank version"
              title="Start with four blank parts"
              onClick={() => guard(focused.addNotepadVersion(false))}
              className="flex items-center rounded-md border border-dashed border-[var(--line)] px-2 py-0.5 text-[11px] text-[var(--mute)] hover:border-[var(--line-strong)] hover:text-[var(--ink-2)]"
            >
              Start blank
            </button>
          </>
        ) : null}
      </div>
      <p className="mt-1.5 text-[10.5px] text-[var(--mute)]">
        {finished
          ? "Study complete. These versions are the final output."
          : "Edits take effect as you type. Versions are independent."}
      </p>
      <div className="mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {NOTEPAD_PARTS.map((part) => (
          <PartField
            key={`${version.id}:${part}`}
            part={part}
            versionId={version.id}
            value={version.doc[part]}
            draft={
              finished ? undefined : drafts[notepadDraftKey(version.id, part)]
            }
            readOnly={finished}
            onCommit={commit}
            onStage={stageNotepadPart}
            disabled={busy !== null || finished}
            onFocus={onPartFocus}
          />
        ))}
      </div>
      {error || Object.values(fieldErrors)[0] ? (
        <ErrorLine>{error || Object.values(fieldErrors)[0]}</ErrorLine>
      ) : null}
      <div className="mt-3 border-t border-[var(--line)] pt-3">
        <Button
          variant={finished ? "outline" : "primary"}
          size="sm"
          disabled={finished || busy !== null}
          onClick={onFinish}
          className="w-full"
        >
          {busy === "Finishing study" ? <Spinner /> : null}
          {finished ? "Study finished" : "Finish study"}
        </Button>
      </div>
    </section>
  )
}

function CopyFeedback({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle")
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setState("copied")
      window.setTimeout(() => setState("idle"), 1600)
    } catch {
      setState("error")
    }
  }
  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="mt-2 inline-flex items-center gap-1 rounded-md border border-[var(--line)] px-2 py-1 text-[10.5px] font-medium text-[var(--ink-2)] hover:border-[var(--line-strong)]"
    >
      {state === "copied" ? (
        <Check size={11} aria-hidden />
      ) : (
        <Clipboard size={11} aria-hidden />
      )}
      {state === "copied"
        ? "Copied"
        : state === "error"
          ? "Copy failed"
          : "Copy feedback"}
    </button>
  )
}

function TurnRow({
  turn,
  color,
  topicTitle,
}: {
  turn: NotepadTurn
  color?: string
  topicTitle?: string
}) {
  const isResearcher = turn.role === "researcher"
  const isSummary = turn.role === "summary"
  const copyable = turn.role === "perspective" || isSummary
  return (
    <div className={isResearcher ? "flex justify-end" : ""}>
      <article
        data-testid={`notepad-turn-${turn.kind}`}
        className={
          isResearcher
            ? "w-fit max-w-[78%] rounded-xl border border-[var(--line)] bg-[color-mix(in_srgb,var(--node)_6%,var(--panel))] px-3 py-2.5"
            : isSummary
              ? "rounded-xl border border-dashed border-[var(--line)] px-3 py-2.5"
              : "rounded-xl border border-[var(--line)] px-3 py-2.5"
        }
      >
        <div className="mb-1 flex items-baseline justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-[var(--ink-2)]">
            {!isResearcher && !isSummary ? (
              <UserRound
                aria-hidden
                size={12}
                strokeWidth={2.2}
                className="shrink-0"
                style={{ color: color ?? "var(--ink-2)" }}
              />
            ) : null}
            {isResearcher ? "You" : turn.author_label}
          </span>
          {turn.part ? (
            <span className="text-[10px] text-[var(--mute)]">
              {NOTEPAD_LABELS[turn.part]}
            </span>
          ) : null}
        </div>
        {topicTitle ? (
          <div className="mb-1 break-words text-[10.5px] text-[var(--mute)]">
            {`Topic: ${topicTitle}`}
          </div>
        ) : null}
        <p className="text-[12.5px] leading-relaxed">{turn.text}</p>
        {copyable ? <CopyFeedback text={turn.text} /> : null}
      </article>
    </div>
  )
}

function AgendaStatus({ notepad }: { notepad: NotepadState }) {
  const version = notepad.active_version_id
    ? notepad.versions.find((item) => item.id === notepad.active_version_id)
    : notepad.versions[0]
  if (!version) return null
  const agenda = version.agenda
  if (agenda.phase === "complete") {
    return <span>Draft review complete</span>
  }
  const done =
    agenda.phase === "feedback"
      ? agenda.feedback_done_ids.length
      : agenda.comparison_done_ids.length
  return (
    <span>
      {`${agenda.phase === "feedback" ? "Reviewing" : "Comparing"} ${NOTEPAD_LABELS[agenda.part]} · ${done}/${agenda.participant_ids.length}`}
    </span>
  )
}

function ConversationColumn({
  session,
  notepad,
  busy,
  selection,
  onClearSelection,
}: {
  session: SessionState
  notepad: NotepadState
  busy: string | null
  selection: TopicSelection | null
  onClearSelection: () => void
}) {
  const focused = useFocusedPanel()
  const [message, setMessage] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [topicNotice, setTopicNotice] = useState<string | null>(null)
  const [turnBudgets, setTurnBudgets] = useState<Record<string, number>>({})
  const [rosterOpen, setRosterOpen] = useState(false)
  const input = useRef<HTMLTextAreaElement | null>(null)
  const seeded = useRef<{ seed: number; text: string | null } | null>(null)
  const focusPending = useRef(false)
  const version = notepad.active_version_id
    ? notepad.versions.find((item) => item.id === notepad.active_version_id)
    : notepad.versions[0]
  const versionId = version?.id ?? ""
  const turns = turnBudgets[versionId] ?? version?.agenda.turn_budget ?? 4
  const finished = notepad.final_snapshot !== null
  const topics = useMemo(() => notepad.topics ?? [], [notepad.topics])
  const selectedTopic =
    selection === null
      ? null
      : (topics.find((topic) => topic.id === selection.topicId) ?? null)
  const colors = useMemo(
    () => new Map(session.perspectives.map((item) => [item.id, item.color])),
    [session.perspectives],
  )
  const topicTitles = useMemo(
    () => new Map(topics.map((topic) => [topic.id, topic.title])),
    [topics],
  )
  const visibleTurns = notepad.turns
    .filter((turn) => turn.version_id === versionId)
    .slice(version?.visible_turn_start ?? 0)
  const visibleFeedbackCount = visibleTurns.filter(
    (turn) => turn.role === "perspective",
  ).length

  const focusComposer = useCallback(() => {
    const node = input.current
    if (node === null || node.disabled) {
      focusPending.current = true
      return
    }
    focusPending.current = false
    node.focus()
  }, [])

  useEffect(() => {
    if (focusPending.current) focusComposer()
  }, [busy, focusComposer, versionId])

  // Seeding runs once per selection. An untouched seeded question is replaced;
  // anything the researcher wrote is kept and the topic simply rides along.
  useEffect(() => {
    if (finished || selection === null || selectedTopic === null) return
    if (seeded.current?.seed === selection.seed) return
    const previous = seeded.current
    const keepDraft = message.trim() !== "" && message !== previous?.text
    seeded.current = {
      seed: selection.seed,
      text: keepDraft ? null : selectedTopic.question,
    }
    if (keepDraft) {
      setTopicNotice(
        "Your draft is kept. Send attaches this topic, or use its question.",
      )
    } else {
      setMessage(selectedTopic.question)
      setTopicNotice(null)
    }
    focusComposer()
  }, [finished, focusComposer, message, selectedTopic, selection])

  const guard = (action: Promise<unknown>) => {
    setError(null)
    action.catch((cause) =>
      setError(cause instanceof Error ? cause.message : "Could not do that"),
    )
  }
  const clearTopic = () => {
    setTopicNotice(null)
    onClearSelection()
  }
  const useTopicQuestion = () => {
    if (selectedTopic === null) return
    setMessage(selectedTopic.question)
    setTopicNotice(null)
    if (selection !== null) {
      seeded.current = { seed: selection.seed, text: selectedTopic.question }
    }
    focusComposer()
  }
  const send = () => {
    const text = message.trim()
    if (!text || !versionId) return
    const sent = message
    const topicId = selectedTopic?.id ?? null
    setError(null)
    void focused.askNotepad(versionId, text, topicId).then(
      () => {
        setMessage((current) => (current === sent ? "" : current))
        setTopicNotice(null)
        seeded.current = null
        onClearSelection()
      },
      (cause: unknown) => {
        setError(cause instanceof Error ? cause.message : "Could not send")
      },
    )
  }

  return (
    <section
      data-testid="notepad-conversation"
      className="ep-enter panel flex min-h-0 flex-col rounded-xl px-4 py-3.5"
    >
      <div className="flex items-center gap-1.5">
        <SectionLabel>Discussion</SectionLabel>
        <button
          type="button"
          data-testid="notepad-roster-toggle"
          aria-expanded={rosterOpen}
          aria-label={rosterOpen ? "Hide who is in the chat" : "Show who is in the chat"}
          onClick={() => setRosterOpen((value) => !value)}
          className="inline-flex shrink-0 items-center gap-0.5 rounded-md px-1 py-0.5 text-[var(--mute)] hover:text-[var(--ink-2)]"
        >
          {rosterOpen
            ? null
            : session.perspectives.map((perspective) => (
                <UserRound
                  key={perspective.id}
                  aria-hidden
                  size={11}
                  strokeWidth={2.2}
                  className="shrink-0"
                  style={{ color: perspective.color }}
                />
              ))}
          <ChevronRight
            aria-hidden
            size={12}
            strokeWidth={2}
            className="shrink-0 transition-transform"
            style={{ transform: rosterOpen ? "rotate(90deg)" : undefined }}
          />
        </button>
      </div>
      {rosterOpen ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-[var(--mute)]">In the chat</span>
          {session.perspectives.map((perspective) => (
            <span
              key={perspective.id}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--line-strong)] px-2 py-0.5 text-[11px] text-[var(--ink)]"
            >
              <UserRound
                aria-hidden
                size={11}
                strokeWidth={2.2}
                className="shrink-0"
                style={{ color: perspective.color }}
              />
              {perspective.name}
            </span>
          ))}
        </div>
      ) : null}
      <div className="mt-2 text-[10.5px] font-medium text-[var(--mute)]">
        <AgendaStatus notepad={notepad} />
      </div>

      <div className="mt-3 min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
        {visibleTurns.length === 0 ? (
          <EmptyLine>
            Start the draft review, or ask the Perspectives a specific question.
          </EmptyLine>
        ) : null}
        {visibleTurns.map((turn) => (
          <TurnRow
            key={turn.id}
            turn={turn}
            color={turn.author_id ? colors.get(turn.author_id) : undefined}
            topicTitle={
              turn.topic_id ? topicTitles.get(turn.topic_id) : undefined
            }
          />
        ))}
      </div>

      <div className="mt-3 space-y-2 border-t border-[var(--line)] pt-3">
        {version?.agenda.phase === "complete" && !finished ? (
          <Button
            variant="outline"
            size="sm"
            disabled={busy !== null}
            onClick={() => guard(focused.restartNotepadReview(version.id))}
            className="w-full"
          >
            {busy === "Restarting review" ? <Spinner /> : null}
            Start another review
          </Button>
        ) : null}
        <div
          data-testid="discussion-actions"
          className="grid grid-cols-[minmax(0,1fr)_32px] gap-2 min-[480px]:grid-cols-[minmax(0,1fr)_auto_32px]"
        >
          <div className="field flex h-8 min-w-0 overflow-hidden rounded-lg">
            <button
              type="button"
              aria-label="Let agents discuss"
              disabled={
                finished ||
                busy !== null ||
                !versionId ||
                version?.agenda.phase === "complete"
              }
              onClick={() => guard(focused.discussNotepad(versionId, turns))}
              className="inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-3 text-[13px] font-medium text-[var(--ink)] hover:bg-[color-mix(in_srgb,var(--node)_5%,transparent)] disabled:opacity-40"
            >
              {busy === "Agents discussing" ? <Spinner /> : null}
              Discuss
            </button>
            <label className="flex w-[88px] shrink-0 items-center border-l border-[var(--line)] px-2.5">
              <span className="sr-only">Turns</span>
              <select
                value={turns}
                aria-label="Turns"
                disabled={finished || busy !== null || !versionId}
                onChange={(event) =>
                  setTurnBudgets((current) => ({
                    ...current,
                    [versionId]: Number(event.target.value),
                  }))
                }
                className="w-full bg-transparent text-[13px] font-medium tabular-nums text-[var(--ink-2)] outline-none"
              >
                {Array.from({ length: 8 }, (_, index) => index + 1).map(
                  (count) => (
                    <option key={count} value={count}>
                      {`${count} ${count === 1 ? "turn" : "turns"}`}
                    </option>
                  ),
                )}
              </select>
            </label>
          </div>
          <Button
            variant="outline"
            size="md"
            disabled={finished || busy !== null || visibleFeedbackCount < 2}
            onClick={() => guard(focused.summarizeNotepad(versionId))}
            className="col-span-2 row-start-2 justify-center min-[480px]:col-span-1 min-[480px]:row-auto"
          >
            {busy === "Summarizing" ? <Spinner /> : null}
            Summarize so far
          </Button>
          <button
            type="button"
            aria-label="Clear chat"
            title="Clear chat"
            disabled={finished || busy !== null || visibleTurns.length === 0}
            onClick={() => guard(focused.clearNotepadChat())}
            className="col-start-2 row-start-1 grid size-8 place-items-center rounded-lg text-[var(--mute)] hover:bg-[var(--red-bg)] hover:text-[var(--red)] disabled:pointer-events-none disabled:opacity-35 min-[480px]:col-auto min-[480px]:row-auto"
          >
            {busy === "Clearing the chat" ? (
              <Spinner className="size-3" />
            ) : (
              <Trash2 size={14} strokeWidth={1.8} aria-hidden />
            )}
          </button>
        </div>
        {selectedTopic !== null && !finished ? (
          <div
            data-testid="composer-topic"
            className="rounded-lg border border-dashed border-[var(--line-strong)] px-2.5 py-2"
          >
            <p className="break-words text-[11px] font-medium text-[var(--ink)]">
              {`Topic: ${selectedTopic.title}`}
            </p>
            <p className="mt-0.5 break-words text-[10.5px] leading-relaxed text-[var(--mute)]">
              {`Tentative hypothesis. ${selectedTopic.hypothesis}`}
            </p>
            <p className="mt-1 break-words text-[10.5px] leading-relaxed text-[var(--ink-2)]">
              {selectedTopic.rationale}
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {message !== selectedTopic.question ? (
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={useTopicQuestion}
                  className="rounded-md border border-[var(--line)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--ink-2)] hover:border-[var(--line-strong)]"
                >
                  Use its question
                </button>
              ) : null}
              <button
                type="button"
                data-testid="composer-topic-clear"
                disabled={busy !== null}
                onClick={clearTopic}
                className="rounded-md border border-[var(--line)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--ink-2)] hover:border-[var(--line-strong)]"
              >
                Clear topic
              </button>
            </div>
            {topicNotice ? (
              <p className="mt-1 break-words text-[10.5px] leading-relaxed text-[var(--amber)]">
                {topicNotice}
              </p>
            ) : null}
          </div>
        ) : null}
        <div className="relative">
          <textarea
            ref={input}
            value={message}
            rows={2}
            aria-label="Message the panel"
            placeholder="Ask the panel something..."
            disabled={finished || busy !== null || !versionId}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            className="field block min-h-9 w-full resize-none rounded-lg py-2 pl-3 pr-12 text-[12.5px] leading-snug"
          />
          <button
            type="button"
            aria-label="Send"
            disabled={finished || busy !== null || !message.trim() || !versionId}
            onClick={send}
            className="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg bg-[var(--node)] text-white hover:opacity-90 disabled:opacity-35"
          >
            {busy === "Sending" ? (
              <Spinner className="size-3.5" />
            ) : (
              <ArrowUp size={15} strokeWidth={2.1} aria-hidden />
            )}
          </button>
        </div>
      </div>
      {error ? <ErrorLine>{error}</ErrorLine> : null}
    </section>
  )
}

function PerspectiveCard({
  perspective,
  papers,
}: {
  perspective: Perspective
  papers: SessionState["papers"]
}) {
  const [open, setOpen] = useState(false)
  const openPaperSet = useFocusedStore((state) => state.openPaperSet)
  const anchor = papers.find((paper) => paper.id === perspective.anchor_paper_id)
  return (
    <article className="rounded-lg border border-[var(--line)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <UserRound size={12} aria-hidden style={{ color: perspective.color }} />
        <span className="min-w-0 flex-1 text-[12.5px] font-medium">
          {perspective.name}
        </span>
        <ChevronRight
          size={13}
          aria-hidden
          className={open ? "rotate-90" : ""}
        />
      </button>
      {open ? (
        <div className="border-t border-[var(--line)] px-3 py-2.5">
          {perspective.summary ? (
            <p className="text-[12px] leading-relaxed text-[var(--ink-2)]">
              {perspective.summary}
            </p>
          ) : null}
          <div className="mt-2 text-[10.5px] text-[var(--mute)]">
            {anchor ? (
              <button
                type="button"
                onClick={() => openPaperSet(anchor.id)}
                className="underline underline-offset-2"
              >
                {anchor.title}
              </button>
            ) : (
              "Anchor paper unavailable"
            )}
            {` · ${perspective.related_paper_count} related ${
              perspective.related_paper_count === 1 ? "paper" : "papers"
            }`}
          </div>
        </div>
      ) : null}
    </article>
  )
}

function PerspectivesColumn({
  session,
  onCollapse,
  onBuildAnother,
}: {
  session: SessionState
  onCollapse: () => void
  onBuildAnother: () => void
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
          className="hidden text-[var(--mute)] hover:text-[var(--ink)] lg:block"
        >
          <ChevronRight size={14} strokeWidth={2.2} />
        </button>
      </div>
      <div className="mt-2.5 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {session.perspectives.map((perspective) => (
          <PerspectiveCard
            key={perspective.id}
            perspective={perspective}
            papers={session.papers}
          />
        ))}
        {session.notepad?.final_snapshot === null &&
        session.perspectives.length < MAX_PERSPECTIVES ? (
          <button
            type="button"
            data-testid="notepad-build-perspective"
            onClick={onBuildAnother}
            className="w-full rounded-xl border border-dashed border-[var(--line)] px-3 py-2.5 text-left hover:border-[var(--line-strong)]"
          >
            <span className="flex items-center gap-1.5 text-[12.5px] font-medium">
              <Plus size={12} strokeWidth={2.2} aria-hidden />
              Build another Perspective
            </span>
            <span className="mt-0.5 block text-[11px] leading-relaxed text-[var(--mute)]">
              Opens the papers step. It joins the current draft review.
            </span>
          </button>
        ) : null}
      </div>
    </section>
  )
}

export function StageNotepad({ session }: { session: SessionState }) {
  const focused = useFocusedPanel()
  const busy = useFocusedStore((state) => state.busy)
  const stageSet = useFocusedStore((state) => state.stageSet)
  const [collapsed, setCollapsed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const notepad = session.notepad
  const [selection, setSelection] = useState<TopicSelection | null>(null)
  const seed = useRef(0)
  const activeVersionId = notepad?.active_version_id ?? null
  const finished = notepad?.final_snapshot != null

  const [composerVersion, setComposerVersion] = useState(activeVersionId)
  if (composerVersion !== activeVersionId) {
    setComposerVersion(activeVersionId)
    setSelection(null)
  }

  const clearSelection = useCallback(() => setSelection(null), [])
  const selectTopic = useCallback((topicId: string) => {
    seed.current += 1
    const next = seed.current
    setSelection((current) =>
      current?.topicId === topicId ? null : { topicId, seed: next },
    )
  }, [])

  if (!notepad) {
    return (
      <main className="mx-auto w-full max-w-[640px] px-4 py-10">
        <section className="ep-enter panel rounded-xl px-4 py-3.5">
          <SectionLabel>Discussion</SectionLabel>
          <p className="mt-1.5 text-[12.5px] leading-relaxed">
            The Perspectives will review the four notepad elements in order.
          </p>
          <Button
            variant="primary"
            size="sm"
            className="mt-3"
            disabled={busy !== null || session.perspectives.length === 0}
            onClick={() => {
              setError(null)
              focused.startNotepad().catch((cause) =>
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not open the discussion",
                ),
              )
            }}
          >
            {busy === "Opening the discussion" ? <Spinner /> : null}
            Open discussion
          </Button>
          {error ? <ErrorLine>{error}</ErrorLine> : null}
        </section>
      </main>
    )
  }

  return (
    <main
      className={`grid min-h-0 flex-1 gap-3 p-4 lg:max-h-[calc(100dvh-48px)] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden ${
        collapsed
          ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_40px]"
          : "lg:grid-cols-3"
      }`}
    >
      <NotepadColumn
        session={session}
        notepad={notepad}
        selectedTopicId={selection?.topicId ?? null}
        onTopicSelect={selectTopic}
        busy={busy}
        onPartFocus={() => undefined}
        onFinish={() => {
          setError(null)
          void focused.finishNotepadStudy().catch((cause) =>
            setError(
              cause instanceof Error ? cause.message : "Could not finish study",
            ),
          )
        }}
      />
      <ConversationColumn
        session={session}
        notepad={notepad}
        busy={busy}
        selection={finished ? null : selection}
        onClearSelection={clearSelection}
      />
      {collapsed ? (
        <>
          <div className="lg:hidden">
            <PerspectivesColumn
              session={session}
              onCollapse={() => setCollapsed(true)}
              onBuildAnother={() => stageSet("extraction")}
            />
          </div>
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
        </>
      ) : (
        <PerspectivesColumn
          session={session}
          onCollapse={() => setCollapsed(true)}
          onBuildAnother={() => stageSet("extraction")}
        />
      )}
      {error ? <ErrorLine>{error}</ErrorLine> : null}
    </main>
  )
}
