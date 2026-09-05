"use client"

import { Check, X } from "lucide-react"
import { useEffect, useState } from "react"

import { ApiError, useFocusedPanel } from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import {
  NOTEPAD_LABELS,
  NOTEPAD_PARTS,
  type NotepadDoc,
  type NotepadPart,
  type PaperDetail,
} from "@/types/focused"

import { StageExtraction } from "./stage-extraction"
import { StageNotepad } from "./stage-notepad"
import {
  Button,
  ModalShell,
  SectionLabel,
  Spinner,
} from "./ui"

export function FocusedWorkspace({ demo = false }: { demo?: boolean }) {
  const session = useFocusedStore((state) => state.session)
  const workspace = useFocusedStore((state) => state.workspace)
  const stage = useFocusedStore((state) => state.stage)
  const stageSet = useFocusedStore((state) => state.stageSet)
  const busy = useFocusedStore((state) => state.busy)
  const reset = useFocusedStore((state) => state.reset)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [restoreAttempt, setRestoreAttempt] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const focused = useFocusedPanel()
  const loadWorkspace = focused.loadWorkspace

  useEffect(() => {
    if (session) return
    const explicitWorkspaceId = new URL(window.location.href).searchParams.get(
      "workspace",
    )
    // The demo route never resumes a stored workspace on its own.
    const workspaceId = demo
      ? explicitWorkspaceId
      : (explicitWorkspaceId ??
        window.localStorage.getItem("focused-workspace"))
    if (!workspaceId) return
    void loadWorkspace(workspaceId).catch((cause) => {
      if (
        cause instanceof ApiError &&
        (cause.status === 404 || cause.status === 410)
      ) {
        window.localStorage.removeItem("focused-workspace")
        const nextUrl = new URL(window.location.href)
        nextUrl.searchParams.delete("workspace")
        window.history.replaceState({}, "", nextUrl)
        return
      }
      setRestoreError(
        cause instanceof Error ? cause.message : "Could not open this workspace",
      )
    })
  }, [demo, loadWorkspace, restoreAttempt, session])

  useEffect(() => {
    if (!workspace) return
    window.localStorage.setItem("focused-workspace", workspace.id)
    const url = new URL(window.location.href)
    url.searchParams.set("workspace", workspace.id)
    window.history.replaceState({}, "", url)
  }, [workspace])

  if (!session) {
    if (busy === "Opening workspace") {
      return (
        <div className="flex min-h-screen items-center justify-center gap-2 text-[12px] text-[var(--mute)]">
          <Spinner /> Opening workspace…
        </div>
      )
    }
    if (restoreError) {
      return (
        <RestoreErrorScreen
          onRetry={() => {
            setRestoreError(null)
            setRestoreAttempt((value) => value + 1)
          }}
          onStartNew={() => {
            window.localStorage.removeItem("focused-workspace")
            const url = new URL(window.location.href)
            url.searchParams.delete("workspace")
            window.history.replaceState({}, "", url)
            setRestoreError(null)
          }}
        />
      )
    }
    return <StartScreen demo={demo} />
  }

  const hasPendingPerspectives = session.perspectives.some((perspective) =>
    perspective.id.startsWith("optimistic:"),
  )
  const perspectiveCount = session.perspectives.filter(
    (perspective) => !perspective.id.startsWith("optimistic:"),
  ).length
  const finished = session.notepad?.final_snapshot !== null && session.notepad !== null

  const toggleStage = () => {
    if (finished) return
    setActionError(null)
    if (stage === "deliberation") {
      stageSet("extraction")
      return
    }
    if (session.notepad !== null) {
      stageSet("deliberation")
      return
    }
    void focused
      .startNotepad()
      .then(() => stageSet("deliberation"))
      .catch((cause) =>
        setActionError(
          cause instanceof Error
            ? cause.message
            : "Could not open the discussion",
        ),
      )
  }

  return (
    <div className="flex min-h-screen flex-col lg:h-dvh lg:overflow-hidden">
      <header className="ep-fade-in sticky top-0 z-40 flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-[var(--line)] bg-[var(--panel)] px-3 py-2 sm:h-12 sm:flex-nowrap sm:px-5 sm:py-0">
        <div className="hidden shrink-0 text-[13px] font-semibold tracking-[-0.01em] sm:block">
          Hypothesis Studio
        </div>
        <ol className="hidden items-center lg:flex" aria-label="Progress">
          {(
            [
              ["Find papers", stage === "extraction"],
              ["Discuss", stage === "deliberation"],
            ] as const
          ).map(([name, active], index) => {
            const done = index === 0 && stage === "deliberation"
            return (
              <li key={name} className="flex items-center">
                {index > 0 ? (
                  <span
                    aria-hidden
                    className="mx-2.5 h-px w-5"
                    style={{
                      background:
                        done || active ? "var(--line-strong)" : "var(--line)",
                    }}
                  />
                ) : null}
                <span
                  className="flex items-center gap-1.5"
                  aria-current={active ? "step" : undefined}
                >
                  <span
                    className="grid size-4 shrink-0 place-items-center rounded-full text-[9.5px] font-semibold tabular-nums"
                    style={
                      done || active
                        ? {
                            background: "var(--node)",
                            color: "var(--on-node, #fff)",
                          }
                        : {
                            border: "1px solid var(--line-strong)",
                            color: "var(--mute)",
                          }
                    }
                  >
                    {done ? (
                      <Check size={9} strokeWidth={2.6} aria-hidden />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <span
                    className="text-[11px]"
                    style={{
                      color: active
                        ? "var(--ink)"
                        : done
                          ? "var(--ink-2)"
                          : "var(--mute)",
                      fontWeight: active ? 600 : 450,
                    }}
                  >
                    {name}
                  </span>
                </span>
              </li>
            )
          })}
        </ol>
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          disabled={busy !== null || hasPendingPerspectives}
          onClick={() => setResetOpen(true)}
        >
          Start over
        </Button>
        <Button
          variant={stage === "extraction" ? "primary" : "outline"}
          size="sm"
          disabled={
            busy !== null ||
            hasPendingPerspectives ||
            finished ||
            (stage === "extraction" && perspectiveCount < 1)
          }
          onClick={toggleStage}
          title={
            finished
              ? "This study is finished"
              : hasPendingPerspectives
                ? "Wait for Perspectives to finish adding"
                : stage === "extraction" && perspectiveCount < 1
                  ? "Build at least one Perspective first"
                  : undefined
          }
        >
          {busy === "Opening the discussion" ? (
            <>
              <Spinner /> Opening discussion…
            </>
          ) : stage === "extraction" ? (
            "Continue"
          ) : (
            "Papers"
          )}
        </Button>
      </header>
      {actionError ? (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-3 border-b border-[var(--line)] bg-[var(--panel)] px-5 py-2 text-[11px] text-[var(--red)]"
        >
          <span className="min-w-0 flex-1">{actionError}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setActionError(null)}
            className="shrink-0 text-[var(--mute)] hover:text-[var(--ink)]"
          >
            <X size={14} strokeWidth={1.8} aria-hidden />
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col">
        {stage === "extraction" ? (
          <StageExtraction />
        ) : (
          <StageNotepad session={session} />
        )}
      </div>
      <PaperModal />
      {resetOpen ? (
        <ResetDialog
          onClose={() => {
            setResetError(null)
            setResetOpen(false)
          }}
          onConfirm={() => {
            setResetError(null)
            void focused
              .deleteWorkspace()
              .then(() => {
                window.localStorage.removeItem("focused-workspace")
                const url = new URL(window.location.href)
                url.searchParams.delete("workspace")
                window.history.replaceState({}, "", url)
                setResetOpen(false)
                reset()
              })
              .catch((cause) =>
                setResetError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not reset workspace",
                ),
              )
          }}
          busy={busy === "Deleting workspace"}
          error={resetError}
        />
      ) : null}
    </div>
  )
}



function RestoreErrorScreen({
  onRetry,
  onStartNew,
}: {
  onRetry: () => void
  onStartNew: () => void
}) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="panel w-full max-w-[420px] p-5">
        <h1 className="text-[16px] font-semibold">
          Couldn’t open this workspace
        </h1>
        <p
          role="alert"
          className="mt-2 text-[12px] leading-relaxed text-[var(--ink-2)]"
        >
          We couldn’t load it. Try again, or begin a new Investigation.
        </p>
        <div className="mt-4 flex gap-2">
          <Button variant="primary" size="sm" onClick={onRetry}>
            Try again
          </Button>
          <Button variant="ghost" size="sm" onClick={onStartNew}>
            New Investigation
          </Button>
        </div>
      </div>
    </div>
  )
}


function ResetDialog({
  onClose,
  onConfirm,
  busy,
  error,
}: {
  onClose: () => void
  onConfirm: () => void
  busy: boolean
  error: string | null
}) {
  return (
    <ModalShell title="Start over?" onClose={onClose}>
      <p className="mb-5 text-[13px] leading-relaxed text-[var(--ink-2)]">
        Deletes the working workspace: every Investigation, paper, panel, and
        saved hypothesis. Study interaction records remain.
      </p>
      {error && (
        <p role="alert" className="mb-3 text-[12px] text-[var(--red)]">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={onConfirm} disabled={busy}>
          {busy ? <><Spinner /> Resetting…</> : "Reset workspace"}
        </Button>
      </div>
    </ModalShell>
  )
}

const PART_HINTS: Record<NotepadPart, string> = {
  framing: "How you are framing the problem.",
  prior: "What is already known, and where it stops.",
  method: "How you would go about it.",
  expected: "What you expect to find, and why it would matter.",
}

const DEMO_PROBLEM =
  "Should antibiotics be prescribed broadly? I suspect the faster cure trades off against resistance and gut-flora harm."

const DEMO_POSITION: NotepadDoc = {
  framing: "Prescribing breadth is an evolutionary-pressure problem, not a dosing problem.",
  prior:
    "Cohort work links broad-spectrum days to resistance, but rarely prices the acute benefit against it.",
  method:
    "Compare severity-matched cohorts on resistome carriage and time-to-cure, measured the same way at every site.",
  expected:
    "Narrower first-line holds outcomes outside sepsis, and the harm horizon runs past the treated infection.",
}

const EMPTY_POSITION: NotepadDoc = {
  framing: "",
  prior: "",
  method: "",
  expected: "",
}

function StartScreen({ demo }: { demo: boolean }) {
  const [customProblem, setCustomProblem] = useState("")
  const [customPosition, setCustomPosition] =
    useState<NotepadDoc>(EMPTY_POSITION)
  const [demoPosition, setDemoPosition] =
    useState<NotepadDoc>(DEMO_POSITION)
  const problem = demo ? DEMO_PROBLEM : customProblem
  const position = demo ? demoPosition : customPosition
  const setPosition = demo ? setDemoPosition : setCustomPosition
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const { createWorkspace } = useFocusedPanel()

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      await createWorkspace({
        problem: problem.trim(),
        demo,
        position,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed to start")
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="ep-enter w-full max-w-[440px]">
        <div className="mb-8">
          <h1 className="text-[22px] font-semibold">
            Hypothesis Studio
          </h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--ink-2)]">
            Write the problem and your position. A panel of Perspectives
            discusses it with you.
          </p>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <SectionLabel htmlFor="focused-problem">Problem</SectionLabel>
            <textarea
              id="focused-problem"
              value={problem}
              onChange={(event) => setCustomProblem(event.target.value)}
              disabled={demo}
              rows={3}
              className="field w-full resize-none px-3 py-2.5 text-[13px] leading-relaxed placeholder:text-[var(--mute)]"
              placeholder="Jot down the question or hunch you're exploring."
            />
          </div>

          <div className="space-y-3">
            <SectionLabel>Your position, in four parts</SectionLabel>
            {NOTEPAD_PARTS.map((part) => (
              <div key={part}>
                <label
                  htmlFor={`position-${part}`}
                  className="text-[11px] font-medium text-[var(--ink-2)]"
                >
                  {NOTEPAD_LABELS[part]}
                </label>
                <textarea
                  id={`position-${part}`}
                  value={position[part]}
                  rows={2}
                  onChange={(event) =>
                    setPosition((current) => ({
                      ...current,
                      [part]: event.target.value,
                    }))
                  }
                  className="field mt-1 w-full resize-none px-3 py-2 text-[12.5px] leading-relaxed placeholder:text-[var(--mute)]"
                  placeholder={PART_HINTS[part]}
                />
              </div>
            ))}
          </div>
          {error && (
            <div className="text-[13px] text-[var(--red)]">{error}</div>
          )}
          <Button
            variant="primary"
            size="md"
            onClick={() => void start()}
            disabled={starting || problem.trim().length < 3}
            className="mt-1"
          >
            {starting ? <><Spinner /> Continuing…</> : "Continue"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function PaperModal() {
  const openPaperId = useFocusedStore((s) => s.openPaperId)
  const openPaperSet = useFocusedStore((s) => s.openPaperSet)
  const { fetchPaper } = useFocusedPanel()
  const [detail, setDetail] = useState<PaperDetail | null>(null)
  const [errorPaperId, setErrorPaperId] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (!openPaperId) return
    let cancelled = false
    fetchPaper(openPaperId)
      .then((next) => {
        if (!cancelled) {
          setDetail(next)
          setErrorPaperId(null)
        }
      })
      .catch(() => {
        if (!cancelled) setErrorPaperId(openPaperId)
      })
    return () => {
      cancelled = true
    }
  }, [fetchPaper, openPaperId, retry])


  if (!openPaperId) return null
  const ready = detail?.paper.id === openPaperId
  const failed = errorPaperId === openPaperId
  const paper = ready ? detail.paper : null

  return (
    <ModalShell
      title={paper?.title ?? "Abstract evidence"}
      onClose={() => openPaperSet(null)}
      wide
    >
      {!paper && !failed && (
        <div className="flex min-h-40 items-center justify-center gap-2 text-[12px] text-[var(--mute)]">
          <Spinner /> Loading abstract…
        </div>
      )}
      {!paper && failed && (
        <div className="flex min-h-40 flex-col items-center justify-center text-center">
          <p className="text-[13px] font-medium text-[var(--ink)]">
            This abstract could not be loaded.
          </p>
          <p className="mt-1 text-[11px] text-[var(--mute)]">
            The paper remains selected. Retry when the API is available.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => {
              setErrorPaperId(null)
              setRetry((value) => value + 1)
            }}
          >
            Retry
          </Button>
        </div>
      )}
      {paper && detail && (
        <>
          <div className="mb-1 text-[12px] text-[var(--mute)]">
            {[
              paper.authors.length > 3
                ? `${paper.authors.slice(0, 3).join(", ")} et al.`
                : paper.authors.join(", "),
              paper.venue,
              paper.year,
            ]
              .filter(Boolean)
              .join(" · ") || "no venue recorded"}
          </div>
          <div className="mb-2">
            <SectionLabel>Abstract</SectionLabel>
          </div>
          <div className="rounded-lg border border-[var(--line)] bg-[var(--bg)] px-4 py-3.5 text-[14px] leading-[1.85] text-[var(--ink)]">
            {paper.abstract_sentences.join(" ") ||
              paper.abstract ||
              "No abstract available."}
          </div>
        </>
      )}
    </ModalShell>
  )
}
