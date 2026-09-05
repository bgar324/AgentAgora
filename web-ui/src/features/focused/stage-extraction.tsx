"use client"

import { useState } from "react"
import { Check, ChevronDown } from "lucide-react"

import { useFocusedPanel } from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import {
  MAX_PERSPECTIVES,
  NOTEPAD_LABELS,
  NOTEPAD_PARTS,
} from "@/types/focused"
import type { ExpPaper } from "@/types/focused"

import { Button, EmptyLine, ModalShell, SectionLabel, Spinner } from "./ui"

function paperAbstract(paper: ExpPaper): string {
  return paper.abstract?.trim() || paper.abstract_sentences.join(" ").trim()
}

export function StageExtraction() {
  const session = useFocusedStore((state) => state.session)
  const picked = useFocusedStore((state) => state.pickedQueries)
  const queryToggled = useFocusedStore((state) => state.queryToggled)
  const busy = useFocusedStore((state) => state.busy)
  const openPaperSet = useFocusedStore((state) => state.openPaperSet)
  const {
    suggestQueries,
    runSearch,
    generatePerspective,
    removePerspective,
  } = useFocusedPanel()
  const [searchError, setSearchError] = useState<string | null>(null)
  const [failedBuilds, setFailedBuilds] = useState<
    Record<string, { name: string; description: string; error: string }>
  >({})
  const [openPaperId, setOpenPaperId] = useState<string | null>(null)
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null)
  const [job, setJob] = useState("")
  const [description, setDescription] = useState("")
  const [perspectiveToRemove, setPerspectiveToRemove] = useState<{
    id: string
    name: string
  } | null>(null)
  const [removalError, setRemovalError] = useState<string | null>(null)

  if (!session) return null

  const hasPendingPerspectives = session.perspectives.some((perspective) =>
    perspective.id.startsWith("optimistic:"),
  )
  const atPerspectiveLimit = session.perspectives.length >= MAX_PERSPECTIVES
  const queryOptions = session.suggested_queries.slice(0, 5)
  const selectedQueries = queryOptions
    .filter(({ query }) => picked.includes(query))
    .map(({ query }) => query)
  const selectedPaper = session.papers.find(
    (paper) => paper.id === selectedPaperId,
  )
  const failedList = Object.entries(failedBuilds)

  const act = async (action: () => Promise<unknown>) => {
    setSearchError(null)
    try {
      await action()
    } catch (cause) {
      setSearchError(cause instanceof Error ? cause.message : "Request failed.")
    }
  }

  const retrySearch = async () => {
    const refreshed = await suggestQueries()
    await runSearch(refreshed.suggested_queries.map(({ query }) => query))
  }

  const dismissFailed = (paperId: string) => {
    setFailedBuilds((current) => {
      if (!(paperId in current)) return current
      const next = { ...current }
      delete next[paperId]
      return next
    })
  }

  const carryPaper = (
    paper: ExpPaper,
    wording?: { name: string; description: string },
  ) => {
    setSelectedPaperId(paper.id)
    setJob(wording?.name ?? paper.title.slice(0, 200))
    setDescription(wording?.description ?? paperAbstract(paper).slice(0, 2000))
    dismissFailed(paper.id)
  }

  // The editor frees immediately; the optimistic row in the Perspectives
  // column carries the in-flight state and a failure lands there with Retry.
  const buildPerspective = async () => {
    if (!selectedPaper) return
    const paper = selectedPaper
    const wording = { name: job, description }
    setSelectedPaperId(null)
    setJob("")
    setDescription("")
    try {
      await generatePerspective(paper.id, wording)
    } catch (cause) {
      setFailedBuilds((current) => ({
        ...current,
        [paper.id]: {
          ...wording,
          error:
            cause instanceof Error
              ? cause.message
              : "Could not build this Perspective.",
        },
      }))
    }
  }

  const confirmPerspectiveRemoval = async () => {
    if (!perspectiveToRemove) return
    setRemovalError(null)
    try {
      await removePerspective(perspectiveToRemove.id)
      setPerspectiveToRemove(null)
    } catch (cause) {
      setRemovalError(
        cause instanceof Error
          ? cause.message
          : "Could not remove this Perspective.",
      )
    }
  }

  return (
    <div className="ep-fade-in flex min-h-0 flex-1 flex-col">

      <main
        className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-4 lg:max-h-[calc(100dvh-49px)] lg:grid-cols-[minmax(250px,0.82fr)_minmax(320px,1.18fr)_minmax(290px,1fr)] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden lg:px-6 lg:py-5"
        data-testid="paper-workflow"
      >
        <section
          className="panel min-h-0 overflow-y-auto px-4 py-3.5"
          data-testid="search-brief"
          aria-label="Problem, position, and paper search"
        >
          <SectionLabel>Problem</SectionLabel>
          <p className="mt-2 text-[13px] font-medium leading-relaxed text-[var(--ink)]">
            {session.problem}
          </p>

          <div className="my-4 border-t border-[var(--line)]" />
          <SectionLabel>Your position</SectionLabel>
          <dl className="mt-2 space-y-3">
            {NOTEPAD_PARTS.map((part) => (
              <div key={part}>
                <dt className="text-[11px] font-medium text-[var(--ink-2)]">
                  {NOTEPAD_LABELS[part]}
                </dt>
                <dd className="mt-0.5 text-[12px] leading-relaxed text-[var(--mute)]">
                  {session.position[part] || "Not provided."}
                </dd>
              </div>
            ))}
          </dl>

          <div className="my-4 border-t border-[var(--line)]" />
          <SectionLabel>Paper search</SectionLabel>
          {!session.searched && queryOptions.length === 0 && (
            <>
              <p className="mt-2 text-[12px] leading-relaxed text-[var(--mute)]">
                Suggest five alternate searches from the problem and your four
                position parts.
              </p>
              <Button
                variant="primary"
                size="sm"
                disabled={busy !== null}
                onClick={() => void act(suggestQueries)}
                className="mt-3 w-full"
              >
                {busy === "Generating queries" ? (
                  <>
                    <Spinner /> Suggesting…
                  </>
                ) : (
                  "Suggest queries"
                )}
              </Button>
            </>
          )}

          {!session.searched && queryOptions.length > 0 && (
            <div className="mt-2 flex flex-col gap-1.5">
              {queryOptions.map((suggestion) => {
                const selected = selectedQueries.includes(suggestion.query)
                return (
                  <button
                    key={suggestion.query}
                    type="button"
                    data-testid="suggested-query"
                    onClick={() => queryToggled(suggestion.query)}
                    title={suggestion.rationale}
                    aria-pressed={selected}
                    className="flex cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition"
                    style={{
                      borderColor: selected
                        ? "var(--ink)"
                        : "var(--line-strong)",
                      background: selected ? "var(--panel-2)" : "transparent",
                    }}
                  >
                    <span
                      className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-[4px]"
                      style={{
                        border: `1.5px solid ${selected ? "var(--ink)" : "var(--line-strong)"}`,
                        background: selected ? "var(--ink)" : "transparent",
                      }}
                    >
                      {selected && (
                        <Check
                          size={10}
                          strokeWidth={2}
                          className="text-white"
                          aria-hidden
                        />
                      )}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[12px] leading-snug text-[var(--ink-2)]">
                        {suggestion.query}
                      </span>
                      <span className="mt-0.5 block text-[10.5px] leading-snug text-[var(--mute)]">
                        {suggestion.rationale}
                      </span>
                    </span>
                  </button>
                )
              })}
              <Button
                variant="primary"
                size="sm"
                disabled={
                  selectedQueries.length === 0 || busy !== null
                }
                onClick={() => void act(() => runSearch(selectedQueries))}
                className="mt-1 w-full"
              >
                {busy === "Searching literature" ? (
                  <>
                    <Spinner /> Searching…
                  </>
                ) : (
                  `Search papers (${selectedQueries.length})`
                )}
              </Button>
            </div>
          )}

          {session.searched && (
            <div className="mt-2">
              <p className="text-[12px] leading-relaxed text-[var(--mute)]">
                {session.papers.length} paper
                {session.papers.length === 1 ? "" : "s"} returned.
              </p>
              {session.searched_queries.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-snug text-[var(--mute)]">
                  {session.searched_queries.map((query) => (
                    <li key={query}>{query}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {searchError && (
            <p role="alert" className="mt-3 text-[12px] text-[var(--red)]">
              {searchError}
            </p>
          )}
        </section>

        <section
          className="panel flex min-h-[260px] min-w-0 flex-col overflow-hidden"
          data-testid="paper-results-surface"
          aria-label="Returned papers"
        >
          <div className="flex items-baseline justify-between border-b border-[var(--line)] px-4 py-3.5">
            <SectionLabel>Papers</SectionLabel>
            {session.searched && (
              <span className="text-[11px] text-[var(--mute)]">
                {session.papers.length} returned
              </span>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {!session.searched ? (
              busy === "Searching literature" ? (
                <div className="flex h-full min-h-[180px] items-center justify-center gap-2 text-[12px] text-[var(--mute)]">
                  <Spinner /> Searching papers…
                </div>
              ) : (
                <div className="flex h-full min-h-[180px] items-center justify-center px-6 text-center">
                  <EmptyLine>Search to see papers here.</EmptyLine>
                </div>
              )
            ) : session.papers.length === 0 ? (
              <div className="flex h-full min-h-[180px] flex-col items-center justify-center gap-3 px-6 text-center">
                <EmptyLine>No papers matched those searches.</EmptyLine>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => void act(retrySearch)}
                >
                  {busy !== null ? (
                    <>
                      <Spinner /> Retrying…
                    </>
                  ) : (
                    "Retry search"
                  )}
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {session.papers.map((paper, index) => {
                  const abstract = paperAbstract(paper)
                  const open = openPaperId === paper.id
                  const status = session.perspectives.find(
                    (perspective) => perspective.anchor_paper_id === paper.id,
                  )
                  return (
                    <article
                      key={paper.id}
                      className="ep-card-enter rounded-lg border border-[var(--line)] bg-[var(--panel)]"
                      style={{ animationDelay: `${Math.min(index, 12) * 28}ms` }}
                      data-testid="paper-result"
                    >
                      <button
                        type="button"
                        onClick={() => setOpenPaperId(open ? null : paper.id)}
                        aria-expanded={open}
                        className="flex w-full cursor-pointer items-start gap-3 px-3 py-3 text-left"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-medium leading-snug text-[var(--ink)]">
                            {paper.title}
                          </span>
                          <span className="mt-1 block text-[10.5px] leading-snug text-[var(--mute)]">
                            {[paper.authors.slice(0, 2).join(", "), paper.year, paper.venue]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </span>
                        <ChevronDown
                          size={15}
                          strokeWidth={1.8}
                          aria-hidden
                          className="mt-0.5 shrink-0 text-[var(--mute)] transition-transform"
                          style={{ transform: open ? "rotate(180deg)" : undefined }}
                        />
                      </button>
                      {open && (
                        <div className="border-t border-[var(--line)] px-3 py-3">
                          <SectionLabel>Abstract</SectionLabel>
                          <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ink-2)]">
                            {abstract || "No abstract is available for this paper."}
                          </p>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={
                              !abstract ||
                              status !== undefined ||
                              busy !== null ||
                              atPerspectiveLimit
                            }
                            onClick={() => carryPaper(paper)}
                            className="mt-3"
                          >
                            {status === undefined
                              ? "Add to editor"
                              : status.id.startsWith("optimistic:")
                                ? "Adding…"
                                : "Perspective built"}
                          </Button>
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            )}
          </div>
        </section>

        <section
          className="panel flex min-h-[300px] min-w-0 flex-col overflow-hidden"
          data-testid="perspective-editor"
          aria-label="Perspective editor"
        >
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3.5">
            <SectionLabel>Perspective editor</SectionLabel>
            {selectedPaper ? (
              <div className="mt-2">
                <p className="text-[11px] leading-snug text-[var(--mute)]">
                  Carried from {selectedPaper.title}
                </p>
                <label className="mt-3 block">
                  <span className="text-[11px] font-medium text-[var(--ink-2)]">
                    Job
                  </span>
                  <input
                    value={job}
                    onChange={(event) => setJob(event.target.value)}
                    maxLength={200}
                    className="field mt-1 w-full px-3 py-2 text-[12.5px]"
                  />
                </label>
                <label className="mt-3 block">
                  <span className="text-[11px] font-medium text-[var(--ink-2)]">
                    Description
                  </span>
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    maxLength={2000}
                    rows={8}
                    className="field mt-1 w-full resize-y px-3 py-2 text-[12px] leading-relaxed"
                  />
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={
                    !job.trim() ||
                    !description.trim() ||
                    atPerspectiveLimit ||
                    busy !== null
                  }
                  onClick={() => void buildPerspective()}
                  className="mt-3 w-full"
                >
                  Build Perspective
                </Button>
              </div>
            ) : (
              <div className="flex min-h-[150px] items-center justify-center px-4 text-center">
                <EmptyLine>Add a paper to start editing.</EmptyLine>
              </div>
            )}

            <div className="my-4 border-t border-[var(--line)]" />
            <div className="flex items-baseline justify-between">
              <SectionLabel>Built Perspectives</SectionLabel>
              <span className="text-[11px] text-[var(--mute)]">
                {session.perspectives.length} / {MAX_PERSPECTIVES}
              </span>
            </div>
            {session.perspectives.length === 0 && failedList.length === 0 ? (
              <div className="py-8 text-center">
                <EmptyLine>No Perspectives built yet.</EmptyLine>
              </div>
            ) : (
              <div className="mt-2 space-y-2" data-testid="built-perspectives">
                {session.perspectives.map((perspective) => (
                  <article
                    key={perspective.id}
                    className="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2.5"
                  >
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <h3 className="text-[12.5px] font-semibold leading-snug text-[var(--ink)]">
                          {perspective.name}
                        </h3>
                        {perspective.summary && (
                          <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-[var(--ink-2)]">
                            {perspective.summary}
                          </p>
                        )}
                      </div>
                      {!perspective.id.startsWith("optimistic:") && (
                        <button
                          type="button"
                          onClick={() => {
                            setRemovalError(null)
                            setPerspectiveToRemove({
                              id: perspective.id,
                              name: perspective.name,
                            })
                          }}
                          disabled={
                            busy !== null ||
                            hasPendingPerspectives
                          }
                          aria-label={`Remove ${perspective.name}`}
                          className="shrink-0 text-[13px] leading-none text-[var(--mute)] hover:text-[var(--red)] disabled:opacity-50"
                        >
                          ×
                        </button>
                      )}
                    </div>
                    <div className="mt-2 text-[10.5px] text-[var(--mute)]">
                      {perspective.id.startsWith("optimistic:") ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Spinner /> Adding…
                        </span>
                      ) : perspective.anchor_paper_id ? (
                        <span>
                          <button
                            type="button"
                            onClick={() =>
                              openPaperSet(perspective.anchor_paper_id)
                            }
                            className="underline decoration-[var(--line-strong)] underline-offset-2 hover:text-[var(--ink-2)]"
                          >
                            {session.papers.find(
                              (paper) =>
                                paper.id === perspective.anchor_paper_id,
                            )?.title ?? "Anchor paper"}
                          </button>
                          {` · ${perspective.related_paper_count} related ${
                            perspective.related_paper_count === 1
                              ? "paper"
                              : "papers"
                          }`}
                        </span>
                      ) : (
                        "Source pending"
                      )}
                    </div>
                  </article>
                ))}
                {failedList.map(([paperId, failed]) => (
                  <article
                    key={`failed:${paperId}`}
                    data-testid="failed-perspective"
                    className="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2.5"
                  >
                    <h3 className="text-[12.5px] font-semibold leading-snug text-[var(--ink)]">
                      {failed.name}
                    </h3>
                    <p
                      role="alert"
                      className="mt-1 text-[11px] leading-relaxed text-[var(--red)]"
                    >
                      {failed.error}
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy !== null}
                        onClick={() => {
                          const paper = session.papers.find(
                            (item) => item.id === paperId,
                          )
                          if (paper) carryPaper(paper, failed)
                          else dismissFailed(paperId)
                        }}
                      >
                        Retry
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => dismissFailed(paperId)}
                      >
                        Dismiss
                      </Button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>

      {perspectiveToRemove && (
        <RemovePerspectiveDialog
          name={perspectiveToRemove.name}
          busy={busy === "Removing"}
          error={removalError}
          onClose={() => {
            if (busy === "Removing") return
            setRemovalError(null)
            setPerspectiveToRemove(null)
          }}
          onConfirm={() => void confirmPerspectiveRemoval()}
        />
      )}
    </div>
  )
}

function RemovePerspectiveDialog({
  name,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  name: string
  busy: boolean
  error: string | null
  onClose: () => void
  onConfirm: () => void
}) {
  return (
    <ModalShell title="Remove Perspective?" onClose={onClose}>
      <p className="mb-5 text-[13px] leading-relaxed text-[var(--ink-2)]">
        Remove {name}? This Perspective will also leave every discussion it has
        joined.
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
        <Button
          variant="primary"
          size="sm"
          onClick={onConfirm}
          disabled={busy}
        >
          {busy ? (
            <>
              <Spinner /> Removing…
            </>
          ) : (
            "Remove Perspective"
          )}
        </Button>
      </div>
    </ModalShell>
  )
}
