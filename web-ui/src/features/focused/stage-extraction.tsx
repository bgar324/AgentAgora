"use client"

import { useState } from "react"
import { Pencil } from "lucide-react"

import {
  parseResearchQuestions,
  useFocusedPanel,
} from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import type {
  ClusterCard,
  Facet,
  FacetEvidence,
} from "@/types/focused"

import { Button, EmptyLine, ModalShell, SectionLabel, Spinner } from "./ui"

const FACET_META: Record<Facet, { label: string; description: string }> = {
  scope: {
    label: "Scope",
    description: "Phenomena, settings, populations, tasks, and conditions",
  },
  explanation: {
    label: "Explanation",
    description: "How the phenomenon is understood",
  },
  approach: {
    label: "Approach",
    description: "How the claim is investigated or established",
  },
  significance: {
    label: "Significance",
    description: "Why the work is consequential",
  },
}
export function StageExtraction() {
  const session = useFocusedStore((s) => s.session)
  const picked = useFocusedStore((s) => s.pickedQueries)
  const queryToggled = useFocusedStore((s) => s.queryToggled)
  const busy = useFocusedStore((s) => s.busy)
  const {
    suggestQueries,
    runSearch,
    removePerspective,
    updateBrief,
    switchInvestigation,
  } = useFocusedPanel()
  const [error, setError] = useState<string | null>(null)
  const [editingBrief, setEditingBrief] = useState(false)
  const [draftProblem, setDraftProblem] = useState("")
  const [draftQuestions, setDraftQuestions] = useState("")
  const [perspectiveToRemove, setPerspectiveToRemove] = useState<{
    id: string
    name: string
  } | null>(null)
  const [removalError, setRemovalError] = useState<string | null>(null)

  if (!session) return null
  const integrated = session.integrated_into_parent_at !== null
  const parentInvestigationId = session.parent_investigation_id
  const hasPendingPerspectives = session.perspectives.some((perspective) =>
    perspective.id.startsWith("optimistic:"),
  )
  const queryOptions = session.suggested_queries.slice(0, 5)
  const selectedQueries = queryOptions
    .filter(({ query }) => picked.includes(query))
    .map(({ query }) => query)


  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed")
    }
  }
  const retrySearch = async () => {
    await updateBrief(session.problem, session.research_questions)
    const refreshed = await suggestQueries()
    await runSearch(refreshed.suggested_queries.map(({ query }) => query))
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


  const beginBriefEdit = () => {
    setDraftProblem(session.problem)
    setDraftQuestions(session.research_questions.join("\n"))
    setEditingBrief(true)
  }

  const saveBrief = async () => {
    const problem = draftProblem.trim()
    const questions = parseResearchQuestions(draftQuestions)
    if (problem.length < 3) {
      setError("Problem must be at least three characters.")
      return
    }
    setError(null)
    try {
      await updateBrief(problem, questions)
      setEditingBrief(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save the brief")
    }
  }

  return (
    <div className="ep-fade-in flex flex-col">
      {parentInvestigationId && (
        <div className="ep-card-enter mx-6 mt-4 flex flex-col gap-3 rounded-lg border border-[var(--line)] bg-[var(--panel)] px-4 py-3 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-medium text-[var(--ink)]">
              Research branch
            </div>
            <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink-2)]">
              {integrated ? (
                <>
                  This research branch has already been added to the parent
                  Canvas and is now read-only.
                </>
              ) : (
                <>
                  Started from “{session.origin_question}”. Search fresh
                  literature and add new Perspectives. Back to panel returns
                  without changing this branch. Add to panel imports it after
                  the current parent deliberation ends.
                  {session.applied_hypothesis_version_id
                    ? ` This branch begins from ${session.applied_hypothesis_version_id}.`
                    : " No hypothesis checkpoint had been applied yet."}
                </>
              )}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={busy !== null || hasPendingPerspectives}
            onClick={() =>
              void act(() => switchInvestigation(parentInvestigationId))
            }
            className="shrink-0 self-start sm:self-auto"
          >
            {busy === "Opening Investigation" ? (
              <>
                <Spinner /> Returning…
              </>
            ) : (
              "Back to panel"
            )}
          </Button>
        </div>
      )}
      <div className="grid grid-cols-1 items-stretch gap-5 px-4 py-5 lg:grid-cols-[360px_1fr] lg:px-6">
        {/* the problem and the search */}
        <div className="flex h-full flex-col gap-5">
          <div className="ep-enter panel px-4 py-3.5">
            {editingBrief ? (
              <div className="flex flex-col gap-3">
                <div>
                  <SectionLabel htmlFor="brief-problem">Problem</SectionLabel>
                  <textarea
                    id="brief-problem"
                    value={draftProblem}
                    rows={4}
                    disabled={
                      busy === "Saving brief" ||
                      session.parent_investigation_id !== null
                    }
                    onChange={(event) => setDraftProblem(event.target.value)}
                    className="field w-full resize-none px-3 py-2 text-[13px] leading-relaxed"
                  />
                </div>
                <div>
                  <SectionLabel htmlFor="brief-questions">
                    Research questions
                  </SectionLabel>
                  <textarea
                    id="brief-questions"
                    value={draftQuestions}
                    rows={5}
                    disabled={busy === "Saving brief"}
                    onChange={(event) => setDraftQuestions(event.target.value)}
                    className="field w-full resize-none px-3 py-2 text-[13px] leading-relaxed"
                    placeholder="One question per line"
                  />
                </div>
                <p className="text-[11px] leading-relaxed text-[var(--mute)]">
                  {session.parent_investigation_id
                    ? "The research problem is shared by the workspace. Refine this child Investigation’s questions until its first paper search."
                    : "You can refine the brief until the first paper search. After retrieval begins, use an open question to start a child Investigation."}
                  {session.demo &&
                    " Demo mode continues to use the fixed antibiotic corpus."}
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={busy === "Saving brief" || draftProblem.trim().length < 3}
                    onClick={() => void saveBrief()}
                  >
                    {busy === "Saving brief" ? (
                      <>
                        <Spinner /> Saving…
                      </>
                    ) : (
                      "Save brief"
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy === "Saving brief"}
                    onClick={() => setEditingBrief(false)}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1 text-[13px] font-medium leading-relaxed">
                    {session.problem}
                  </div>
                  {(!session.searched || session.papers.length === 0) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={beginBriefEdit}
                      aria-label="Edit investigation brief"
                      title="Edit investigation brief"
                      className="shrink-0 px-2!"
                    >
                      <Pencil size={14} strokeWidth={1.8} aria-hidden />
                    </Button>
                  )}
                </div>
                {session.research_questions.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-1.5 border-t border-[var(--line)] pt-3">
                    {session.research_questions.map((question, index) => (
                      <li
                        key={index}
                        className="text-[13px] leading-snug text-[var(--ink-2)]"
                      >
                        {question}
                      </li>
                    ))}
                  </ul>
                )}
                {!session.searched ? (
                  <>
                    <p className="mt-3 text-[12px] leading-relaxed text-[var(--mute)]">
                      {session.demo
                        ? "Load five search queries for the fixed antibiotic demo."
                        : "Generate up to five search queries based on your problem and research questions. You can review them before searching."}
                    </p>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={busy === "Generating queries"}
                      onClick={() => void act(suggestQueries)}
                      className="mt-4"
                    >
                      {busy === "Generating queries" ? (
                        <>
                          <Spinner /> {session.demo ? "Loading…" : "Generating…"}
                        </>
                      ) : session.demo ? (
                        "Load demo queries"
                      ) : (
                        "Generate search queries"
                      )}
                    </Button>
                  </>
                ) : session.papers.length === 0 ? (
                  <p className="mt-3 text-[12px] leading-relaxed text-[var(--mute)]">
                    No literature was saved from the last search.
                  </p>
                ) : (
                  <p className="mt-3 text-[12px] leading-relaxed text-[var(--mute)]">
                    This literature set is preserved. Start from a Research
                    Problem node when a new question needs new papers.
                  </p>
                )}
              </>
            )}
          </div>

          {session.searched && session.searched_queries.length > 0 && (
            <section
              aria-label="Queries searched"
              className="ep-enter panel px-4 py-3.5"
            >
              <SectionLabel>Queries searched</SectionLabel>
              <ul className="mt-2 divide-y divide-[var(--line)]">
                {session.searched_queries.map((query) => (
                  <li
                    key={query}
                    className="py-2 text-[12px] leading-snug text-[var(--ink-2)] first:pt-0 last:pb-0"
                  >
                    {query}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!session.searched &&
            !editingBrief &&
            session.suggested_queries.length > 0 && (
            <div className="ep-enter flex flex-col gap-1.5">
              <SectionLabel>Choose queries to search</SectionLabel>
              {queryOptions.map((s, i) => {
                const on = selectedQueries.includes(s.query)
                return (
                  <button
                    key={i}
                    onClick={() => queryToggled(s.query)}
                    title={s.rationale}
                    aria-pressed={on}
                    className="ep-card-enter flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-[13px] transition"
                    style={{
                      animationDelay: `${i * 36}ms`,
                      borderColor: on
                        ? "var(--ink)"
                        : "var(--line-strong)",
                      background: on ? "var(--panel)" : "transparent",
                    }}
                  >
                    <span
                      className="grid size-4 shrink-0 place-items-center rounded-[4px]"
                      style={{
                        border: `1.5px solid ${on ? "var(--ink)" : "var(--line-strong)"}`,
                        background: on ? "var(--ink)" : "transparent",
                      }}
                    >
                      {on && (
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 10 10"
                          fill="none"
                          className="text-white"
                        >
                          <path
                            d="M2 5.5L4 7.5L8 3"
                            stroke="currentColor"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      )}
                    </span>
                    <span className="min-w-0 leading-snug text-[var(--ink-2)]">
                      <span className="block">{s.query}</span>
                      {s.kind === "question" &&
                        s.question_index !== null &&
                        session.research_questions[s.question_index] && (
                          <span className="mt-0.5 block text-[11px] font-medium text-[var(--ink-2)]">
                            For: {session.research_questions[s.question_index]}
                          </span>
                        )}
                      <span className="mt-0.5 block text-[11px] text-[var(--mute)]">
                        {s.rationale}
                      </span>
                    </span>
                  </button>
                )
              })}
              <Button
                variant="primary"
                size="sm"
                disabled={!selectedQueries.length || busy === "Searching literature"}
                onClick={() => void act(() => runSearch(selectedQueries))}
                className="mt-1"
              >
                {busy === "Searching literature" ? (
                  <>
                    <Spinner /> Searching…
                  </>
                ) : (
                  <>
                    Search papers
                    {selectedQueries.length
                      ? ` (${selectedQueries.length} ${selectedQueries.length === 1 ? "query" : "queries"})`
                      : ""}
                  </>
                )}
              </Button>
            </div>
          )}
          {error && (
            <div className="text-[13px] text-[var(--red)]">{error}</div>
          )}
        </div>

        {/* the clusters */}
        <div className="h-full">
          {!session.searched ? (
            <div className="ep-enter panel flex h-full min-h-[220px] flex-col items-center justify-center gap-1.5 px-8 text-center">
              <EmptyLine>Run a search to see the clusters.</EmptyLine>
            </div>
          ) : session.clusters.length === 0 ? (
            <div className="ep-enter panel flex h-full min-h-[220px] flex-col items-center justify-center gap-2 px-8 text-center">
              <EmptyLine>No papers matched those searches.</EmptyLine>
              <p className="max-w-[42ch] text-[11px] leading-relaxed text-[var(--mute)]">
                Retry generates shorter academic queries automatically.
              </p>
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
            session.clusters.map((cluster, index) => (
              <ClusterRow key={cluster.id} cluster={cluster} index={index} />
            ))
          )}
        </div>
      </div>

      {/* the matrix */}
      {session.perspectives.length > 0 && (
        <div className="ep-enter border-t border-[var(--line)] px-4 py-5 lg:px-6">
        <div className="mb-4">
          <div>
            <h2 className="text-[14px] font-semibold tracking-[-0.01em]">
              Perspective matrix ({session.perspectives.length})
            </h2>
          </div>
          <p className="mt-1 max-w-[90ch] text-[12px] leading-relaxed text-[var(--mute)]">
            Each Perspective contains Scope, Explanation, Approach, and
            Significance, extracted only from paper abstracts.
          </p>
        </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {session.perspectives.map((p, index) => (
              <div
                key={p.id}
                className="ep-card-enter ep-interactive-card rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3.5 py-3"
                style={{ animationDelay: `${index * 45}ms` }}
              >
                <div className="flex items-baseline gap-2">
                  <span className="text-[13px] font-semibold tracking-[-0.01em]">
                    {p.name}
                  </span>
                  {p.evolved && (
                    <SectionLabel>Revised</SectionLabel>
                  )}
                  <button
                    onClick={() => {
                      const hasAgents = session.agents.some(
                        (a) => a.perspective_id === p.id,
                      )
                      if (hasAgents) {
                        setRemovalError(null)
                        setPerspectiveToRemove({ id: p.id, name: p.name })
                        return
                      }
                      void act(() => removePerspective(p.id))
                    }}
                    disabled={
                      busy !== null || hasPendingPerspectives || integrated
                    }
                    aria-label={`Remove ${p.name} from the matrix`}
                    title={
                      integrated
                        ? "This research branch was already continued"
                        : session.agents.some((a) => a.perspective_id === p.id)
                          ? "Remove from the matrix and any panel it has joined"
                          : "Remove from the matrix"
                    }
                    className="ml-auto text-[13px] leading-none text-[var(--mute)] hover:text-[var(--red)] disabled:opacity-50"
                  >
                    ✕
                  </button>
                </div>
                <div className="mt-1.5 flex flex-col gap-1">
                  {Object.values(p.facets).map((evidence) => (
                    <div
                      key={evidence.facet}
                      className="text-[12px] leading-snug"
                    >
                      <span className="text-[var(--mute)]">
                        {FACET_META[evidence.facet].label} —{" "}
                      </span>
                      <span className="text-[var(--ink-2)]">
                        {evidence.text}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 text-[12px] font-medium text-[var(--mute)]">
                  {p.id.startsWith("optimistic:") ? (
                    <span className="inline-flex items-center gap-1.5">
                      <Spinner /> Adding to matrix…
                    </span>
                  ) : (
                    <>
                      {p.sources.length} source{" "}
                      {p.sources.length === 1 ? "paper" : "papers"}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
      </div>
      )}
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
        Remove {name} from the matrix? This Perspective will also be removed from
        every panel it has joined.
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

function ClusterRow({ cluster, index }: { cluster: ClusterCard; index: number }) {
  const openClusterId = useFocusedStore((s) => s.openClusterId)
  const openClusterSet = useFocusedStore((s) => s.openClusterSet)
  const openPaperSet = useFocusedStore((s) => s.openPaperSet)
  const session = useFocusedStore((s) => s.session)
  const busy = useFocusedStore((s) => s.busy)
  const { generatePerspective } = useFocusedPanel()
  const integrated = session?.integrated_into_parent_at !== null
  const [edits, setEdits] = useState<
    Partial<Record<Facet, FacetEvidence>>
  >({})
  const [editing, setEditing] = useState<Facet | null>(null)
  const [generationError, setGenerationError] = useState<string | null>(null)

  const open = openClusterId === cluster.id
  const inMatrix = !!session?.perspectives.some(
    (p) => p.origin === cluster.id && !p.evolved,
  )
  const pendingPerspective = !!session?.perspectives.some(
    (p) => p.origin === cluster.id && p.id.startsWith("optimistic:"),
  )
  const facets = cluster.facets.map(
    (evidence) => edits[evidence.facet] ?? evidence,
  )
  const complete = facets.every((evidence) => evidence.text.trim())
  const papers = cluster.paper_ids
    .map((id) => session?.papers.find((p) => p.id === id))
    .filter(Boolean)

  const generate = async () => {
    setGenerationError(null)
    const payload = cluster.facets.map(
      (evidence) => edits[evidence.facet] ?? evidence,
    )
    try {
      await generatePerspective(cluster.id, payload)
    } catch (cause) {
      setGenerationError(
        cause instanceof Error ? cause.message : "Could not add this Perspective.",
      )
    }
  }

  return (
    <div
      className="ep-card-enter ep-interactive-card panel mb-2.5 px-4 py-3.5"
      style={{ animationDelay: `${index * 42}ms` }}
    >
      <div
        className="cursor-pointer"
        onClick={() => openClusterSet(open ? null : cluster.id)}
      >
        <div className="flex items-baseline gap-2.5">
          <h3 className="text-[13px] font-semibold tracking-[-0.01em]">
            {cluster.name}
          </h3>
          <span className="ml-auto shrink-0 text-[12px] font-medium text-[var(--mute)]">
            {cluster.paper_ids.length}{" "}
            {cluster.paper_ids.length === 1 ? "paper" : "papers"}
            <span className="ml-1 opacity-70">{open ? "▾" : "▸"}</span>
          </span>
        </div>
        <p
          className={`mt-1 max-w-[60ch] text-[13px] text-[var(--ink-2)]${open ? "" : " line-clamp-1"}`}
        >
          {cluster.blurb}
        </p>
      </div>

      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="ep-expand-enter mt-3.5"
        >
          <dl className="flex flex-col gap-2.5">
            {facets.map((evidence) => {
              const key = evidence.facet
              const edited = !!edits[key]
              return (
                <div
                  key={key}
                  className="grid grid-cols-1 items-start gap-2 sm:grid-cols-[140px_1fr] sm:gap-3"
                >
                  <div>
                    <SectionLabel>{FACET_META[key].label}</SectionLabel>
                    <p className="mt-0.5 text-[10.5px] leading-snug text-[var(--mute)]">
                      {FACET_META[key].description}
                    </p>
                  </div>
                  <dd className="flex min-w-0 flex-col items-start gap-1.5">
                    {editing === key ? (
                      <input
                        autoFocus
                        className="field w-full max-w-[54ch] px-2.5 py-1 text-[13px]"
                        defaultValue={evidence.text}
                        onBlur={(event) => {
                          const text = event.target.value.trim()
                          if (text && text !== evidence.text) {
                            setEdits((previous) => ({
                              ...previous,
                              [key]: {
                                ...evidence,
                                text,
                                edited: true,
                                paper_id: null,
                                sentence_index: null,
                                sentence: null,
                              },
                            }))
                          }
                          setEditing(null)
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur()
                        }}
                      />
                    ) : (
                      <>
                        <button
                          disabled={integrated}
                          onClick={() => {
                            if (!integrated) setEditing(key)
                          }}
                          className={`max-w-full text-left text-[13px] leading-snug underline decoration-dotted underline-offset-4 hover:text-[var(--ink)] disabled:cursor-default disabled:no-underline ${
                            evidence.text
                              ? "text-[var(--ink-2)] decoration-[var(--line-strong)]"
                              : "font-medium text-[var(--amber)] decoration-[var(--amber)]"
                          }`}
                        >
                          {evidence.text || "Add text"}
                        </button>
                        {edited && (
                          <span className="text-[11px] font-medium text-[var(--green)]">
                            Researcher edited · source link removed
                          </span>
                        )}
                        {evidence.sentence_index !== null &&
                          evidence.paper_id && (
                            <button
                              className="text-[11px] text-[var(--mute)] underline decoration-dotted underline-offset-2 hover:text-[var(--ink-2)]"
                              onClick={() => openPaperSet(evidence.paper_id!)}
                              title={
                                evidence.sentence ??
                                "View the supporting abstract sentence"
                              }
                            >
                              View abstract evidence
                            </button>
                          )}
                      </>
                    )}
                  </dd>
                </div>
              )
            })}
          </dl>

          <div className="mt-4 border-t border-[var(--line)] pt-3">
            <div className="mb-1.5 text-[12px] font-medium text-[var(--mute)]">Representative papers</div>
            <div className="flex flex-col">
              {papers.slice(0, 3).map(
                (p) =>
                  p && (
                    <button
                      key={p.id}
                      onClick={() => openPaperSet(p.id)}
                      className="group flex items-baseline gap-2 border-t border-[var(--line)] py-1.5 text-left first:border-t-0"
                    >
                      <span className="text-[13px] leading-snug text-[var(--ink)] group-hover:text-[var(--green)]">
                        {p.title}
                      </span>
                      <span className="ml-auto shrink-0 text-[12px] font-medium text-[var(--mute)]">
                        {session?.clusters
                          .flatMap((item) => item.facets)
                          .filter((evidence) => evidence.paper_id === p.id)
                          .length ?? 0}{" "}
                        areas
                      </span>
                    </button>
                  ),
              )}
            </div>
            <Button
              variant={inMatrix ? "outline" : "primary"}
              size="sm"
              onClick={() => void generate()}
              className={`mt-3.5 w-full ${
                inMatrix && !pendingPerspective ? "ep-success-state" : ""
              }`}
              disabled={
                integrated || inMatrix || !complete || busy !== null
              }
              aria-live="polite"
            >
              {pendingPerspective ? (
                <>
                  <Spinner /> Adding to matrix…
                </>
              ) : inMatrix ? (
                <>
                  <span aria-hidden>✓</span> Added to matrix
                </>
              ) : !complete ? (
                "Complete all four areas"
              ) : (
                "Add to matrix"
              )}
            </Button>
            {generationError && (
              <p role="alert" className="mt-2 text-[11px] text-[var(--red)]">
                {generationError}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
