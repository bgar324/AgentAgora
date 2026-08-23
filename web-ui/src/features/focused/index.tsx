"use client"


import { ChevronDown } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  ApiError,
  parseResearchQuestions,
  useFocusedPanel,
} from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import type { PaperDetail } from "@/types/focused"

import { StageExtraction } from "./stage-extraction"
import { StageDeliberation } from "./stage-deliberation"
import { WorkspaceMap } from "./workspace-map"
import {
  Button,
  EvidenceHighlight,
  ModalShell,
  SectionLabel,
  Spinner,
} from "./ui"

export function FocusedWorkspace() {
  const session = useFocusedStore((s) => s.session)
  const workspace = useFocusedStore((s) => s.workspace)
  const investigations = useFocusedStore((s) => s.investigations)
  const workspaceScreen = useFocusedStore((s) => s.workspaceScreen)
  const workspaceScreenSet = useFocusedStore((s) => s.workspaceScreenSet)
  const stage = useFocusedStore((s) => s.stage)
  const stageSet = useFocusedStore((s) => s.stageSet)
  const busy = useFocusedStore((s) => s.busy)
  const reset = useFocusedStore((s) => s.reset)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [restoreAttempt, setRestoreAttempt] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const focused = useFocusedPanel()
  const loadWorkspace = focused.loadWorkspace
  useEffect(() => {
    if (session) return
    const params = new URLSearchParams(window.location.search)
    const workspaceId =
      params.get("workspace") ?? window.localStorage.getItem("focused-workspace")
    if (!workspaceId) return
    void loadWorkspace(workspaceId).catch((cause) => {
      if (
        cause instanceof ApiError &&
        (cause.status === 404 || cause.status === 410)
      ) {
        window.localStorage.removeItem("focused-workspace")
        const url = new URL(window.location.href)
        url.searchParams.delete("workspace")
        window.history.replaceState({}, "", url)
        return
      }
      setRestoreError(
        cause instanceof Error ? cause.message : "Could not open this workspace",
      )
    })
  }, [loadWorkspace, restoreAttempt, session])

  useEffect(() => {
    if (!workspace) return
    window.localStorage.setItem("focused-workspace", workspace.id)
    const url = new URL(window.location.href)
    url.searchParams.set("workspace", workspace.id)
    window.history.replaceState({}, "", url)
  }, [workspace])


  const [menuOpen, setMenuOpen] = useState(false)

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
    return <StartScreen />
  }

  const matrixCount = session.perspectives.length
  const isResearchBranch =
    session.parent_investigation_id !== null &&
    session.origin_question_id !== null
  const branchIntegrated = session.integrated_into_parent_at !== null
  const canDeliberate =
    !branchIntegrated && matrixCount >= (isResearchBranch ? 1 : 2)

  const hasInvestigationBranches = investigations.length > 1
  const activeScreen = hasInvestigationBranches ? workspaceScreen : "detail"

  const toggleStage = () => {
    setActionError(null)
    if (stage === "deliberation") {
      stageSet("extraction")
      return
    }
    const continueToCanvas =
      session.parent_investigation_id && session.origin_question_id
        ? focused.integrateChildInvestigation
        : focused.createDeliberation
    void continueToCanvas()
      .then(() => stageSet("deliberation"))
      .catch((cause) =>
        setActionError(
          cause instanceof Error ? cause.message : "Could not continue the panel",
        ),
      )
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="ep-fade-in sticky top-0 z-40 flex min-h-12 flex-wrap items-center gap-x-3 gap-y-2 border-b border-[var(--line)] bg-[var(--panel)] px-3 py-2 sm:h-12 sm:flex-nowrap sm:px-5 sm:py-0">
        <div className="hidden shrink-0 text-[13px] font-semibold tracking-[-0.01em] sm:block">
          Hypothesis Studio
        </div>
        {hasInvestigationBranches && (
          <div className="order-last flex w-full items-center border-t border-[var(--line)] pt-1.5 text-[11px] sm:order-none sm:w-auto sm:border-l sm:border-t-0 sm:pl-3 sm:pt-0">
            <button
              type="button"
              onClick={() => workspaceScreenSet("map")}
              className="shrink-0 font-medium text-[var(--ink-2)] hover:text-[var(--ink)]"
            >
              <span className="sm:hidden">Map</span>
              <span className="hidden sm:inline">Investigation map</span>
            </button>
          </div>
        )}
        {activeScreen === "detail" && (
          <div className="hidden items-center gap-3 lg:flex" aria-label="Progress">
          {(
            [
              ["Search", stage === "extraction" && !session.searched],
              ["Perspectives", stage === "extraction" && session.searched],
              ["Panel", stage === "deliberation"],
            ] as const
          ).map(([name, active], i) => {
            const done =
              (i === 0 && session.searched) ||
              (i === 1 && stage === "deliberation")
            return (
              <span
                key={name}
                className="flex items-center gap-1.5"
                style={{
                  color: active
                    ? "var(--ink)"
                    : done
                      ? "var(--ink-2)"
                      : "var(--mute)",
                }}
              >
                <span
                  className="size-1.5 rounded-full"
                  style={{
                    background: active
                      ? "var(--ink)"
                      : done
                        ? "var(--ink-2)"
                        : "var(--line-strong)",
                  }}
                />
                <span
                  className="text-[11px]"
                  style={{ fontWeight: active ? 500 : 400 }}
                >
                  {name}
                </span>
              </span>
            )
          })}
          </div>
        )}
        {session.demo && (
          <span className="hidden rounded-full border border-[var(--line)] px-1.5 py-px text-[11px] text-[var(--mute)] sm:inline">
            demo
          </span>
        )}
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          className={activeScreen === "map" ? "" : "hidden! sm:inline-flex!"}
          disabled={busy !== null}
          onClick={() => setResetOpen(true)}
        >
          Start over
        </Button>
        {activeScreen === "map" ? (
          <Button
            variant="primary"
            size="sm"
            className="ml-auto"
            disabled={busy !== null}
            onClick={() => workspaceScreenSet("detail")}
          >
            Open current Investigation
          </Button>
        ) : (
          <div className="relative ml-auto shrink-0">
            <div
              className={`flex h-8 items-stretch overflow-hidden rounded-lg ${
                stage === "extraction" ? "btn-primary" : "btn-outline"
              }`}
              style={
                stage === "extraction" && !canDeliberate
                  ? { background: "rgba(16, 24, 40, 0.14)", opacity: 1 }
                  : undefined
              }
            >
              <button
                type="button"
                disabled={
                  busy !== null ||
                  (stage === "extraction" && !canDeliberate)
                }
                onClick={toggleStage}
                title={
                  stage === "extraction" && !canDeliberate
                    ? branchIntegrated
                      ? "This research branch already continues on the parent Canvas"
                      : isResearchBranch
                        ? "Add at least one Perspective first"
                        : "Generate at least two Perspectives first"
                    : undefined
                }
                className="flex items-center gap-1.5 whitespace-nowrap pl-3.5 pr-3 text-[12.5px] font-medium disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--bg)]"
              >
                {busy === "Setting up the panel" ||
                busy === "Continuing parent deliberation" ? (
                  <>
                    <Spinner /> Continuing panel…
                  </>
                ) : branchIntegrated ? (
                  "Continued"
                ) : stage === "extraction" ? (
                  "Continue"
                ) : (
                  "Extraction"
                )}
              </button>
              <div className="my-2 w-px shrink-0 bg-current opacity-15" />
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => setMenuOpen((v) => !v)}
                aria-label="Workspace menu"
                className="flex items-center pl-2 pr-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--bg)]"
              >
                <ChevronDown size={14} strokeWidth={2} />
              </button>
            </div>
            {menuOpen && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setMenuOpen(false)}
                />
                <div className="panel absolute right-0 top-9 z-20 flex w-44 flex-col py-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setMenuOpen(false)
                      setActionError(null)
                      void focused.exportWorkspace().catch((cause) => {
                        setActionError(
                          cause instanceof Error
                            ? cause.message
                            : "Could not export workspace",
                        )
                      })
                    }}
                    className="justify-start!"
                  >
                    Export workspace
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setMenuOpen(false)
                      setResetOpen(true)
                    }}
                    className="justify-start! sm:hidden!"
                  >
                    Start over
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </header>
      {actionError && (
        <div
          role="alert"
          className="border-b border-[var(--line)] bg-[var(--panel)] px-5 py-2 text-[11px] text-[var(--red)]"
        >
          {actionError}
        </div>
      )}

      {activeScreen === "map" ? (
        <WorkspaceMap />
      ) : stage === "extraction" ? (
        <StageExtraction />
      ) : (
        <StageDeliberation />
      )}

      <PaperModal />
      {resetOpen && (
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
      )}
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
        This discards the workspace — every Investigation, paper set, panel,
        and hypothesis branch.
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

function StartScreen() {
  const [problem, setProblem] = useState(
    "Should antibiotics be prescribed broadly? I suspect the faster cure trades off against resistance and gut-flora harm.",
  )
  const [questions, setQuestions] = useState(
    "Does broad-spectrum use raise resistance enough to matter at population level?\nDoes it harm the patient's own flora in ways that outlast the infection?\nWhen does speed to cure outweigh both?",
  )
  const [demo, setDemo] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const { createWorkspace } = useFocusedPanel()

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      await createWorkspace(
        problem.trim(),
        parseResearchQuestions(questions),
        demo,
      )
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
          <h1 className="text-[22px] font-semibold tracking-[-0.02em]">
            Hypothesis Studio
          </h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--ink-2)]">
            Search, extract perspectives, and run a panel.
          </p>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <SectionLabel htmlFor="focused-problem">Problem</SectionLabel>
            <textarea
              id="focused-problem"
              value={problem}
              onChange={(e) => setProblem(e.target.value)}
              rows={3}
              className="field w-full resize-none px-3 py-2.5 text-[13px] leading-relaxed placeholder:text-[var(--mute)]"
              placeholder="Jot down the question or hunch you're exploring."
            />
          </div>
          <div>
            <SectionLabel htmlFor="focused-questions">
              Research questions
            </SectionLabel>
            <textarea
              id="focused-questions"
              value={questions}
              onChange={(e) => setQuestions(e.target.value)}
              rows={4}
              className="field w-full resize-none px-3 py-2.5 text-[13px] leading-relaxed placeholder:text-[var(--mute)]"
              placeholder="One per line."
            />
          </div>
          <label className="flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
            <input
              type="checkbox"
              checked={demo}
              onChange={(e) => setDemo(e.target.checked)}
              className="size-3.5 accent-[var(--node)]"
            />
            Demo mode
          </label>
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
            {starting ? <><Spinner /> Starting…</> : "Begin"}
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

  const hitSentences = useMemo(() => {
    const hits = new Map<number, string[]>()
    detail?.facet_hits.forEach((hit) => {
      const facets = hits.get(hit.sentence_index) ?? []
      facets.push(hit.facet)
      hits.set(hit.sentence_index, facets)
    })
    return hits
  }, [detail])

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
            {[paper.venue, paper.year].filter(Boolean).join(" · ") ||
              "no venue recorded"}
          </div>
          <p className="mb-6 text-[13px] leading-[1.7] text-[var(--ink-2)]">
            {paper.abstract ?? "No abstract available."}
          </p>

          <div className="mb-2">
            <SectionLabel>Abstract evidence</SectionLabel>
          </div>
          <div className="rounded-lg border border-[var(--line)] bg-[var(--bg)] px-4 py-3.5 text-[14px] leading-[1.85] text-[var(--ink)]">
            {paper.abstract_sentences.map((sentence, index) => {
              const facets = hitSentences.get(index)
              if (!facets) return <span key={index}>{sentence} </span>
              const labels = facets.map(
                (facet) => facet.charAt(0).toUpperCase() + facet.slice(1),
              )
              const evidenceLabel =
                labels.length === 1
                  ? `${labels[0]} evidence`
                  : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]} evidence`
              return (
                <EvidenceHighlight key={index} label={evidenceLabel}>
                  {sentence}{" "}
                </EvidenceHighlight>
              )
            })}
          </div>

          {detail.facet_hits.length > 0 && (
            <div className="mt-6">
              <div className="mb-2">
                <SectionLabel>Evidence by area</SectionLabel>
              </div>
              <dl className="flex flex-col gap-1.5">
                {detail.facet_hits.map((hit) => (
                  <div
                    key={`${hit.facet}-${hit.sentence_index}`}
                    className="grid grid-cols-[92px_1fr] items-baseline gap-3 border-t border-[var(--line)] pt-1.5 text-[13px]"
                  >
                    <dt>
                      <SectionLabel>
                        {hit.facet.charAt(0).toUpperCase() + hit.facet.slice(1)}
                      </SectionLabel>
                    </dt>
                    <dd className="leading-snug text-[var(--ink-2)]">
                      {hit.text}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </>
      )}
    </ModalShell>
  )
}
