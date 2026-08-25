"use client"

import { useCallback } from "react"

import { useFocusedStore } from "@/store/focused"
import type {
  Facet,
  FacetEvidence,
  HypothesisConfirmationMode,
  HypothesisDev,
  HypothesisPart,
  PaperDetail,
  Perspective,
  DeliberationRating,
  QuestionStatus,
  SessionState,
  SearchProgressItem,
  WorkspaceView,
} from "@/types/focused"

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

type SearchProgressResponse = {
  generation: number
  items: SearchProgressItem[]
  next: number
}

const WRAPPED_LINE_END =
  /(?:[,;:]|\b(?:a|an|and|as|between|by|for|from|in|of|on|or|than|that|the|to|which|who|whose|with|without))$/i

export function parseResearchQuestions(value: string): string[] {
  const questions: string[] = []
  let pending: string[] = []
  const flush = () => {
    const question = pending.join(" ").trim()
    if (question) questions.push(question)
    pending = []
  }
  for (const rawLine of value.split(/\r?\n/)) {
    const trimmed = rawLine.trim()
    const listPrefix = trimmed.match(/^(?:[-*•]|\d+[.)])\s+/)
    const line = listPrefix ? trimmed.slice(listPrefix[0].length) : trimmed
    if (!line) {
      flush()
      continue
    }
    if (pending.length > 0) {
      const previous = pending[pending.length - 1]
      const continuesPrevious =
        WRAPPED_LINE_END.test(previous) || /^[a-z]/.test(line)
      if (listPrefix || !continuesPrevious) flush()
    }
    pending.push(line)
    if (/[?？][)"'\]]?$/.test(line)) flush()
  }
  flush()
  return questions
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/focused/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

/**
 * Most mutations are exclusive. Perspective generation may run concurrently;
 * its response merge preserves pending work and rejects older add snapshots.
 */
export function useFocusedPanel() {
  const workspaceViewSet = useFocusedStore((s) => s.workspaceViewSet)
  const perspectiveViewSet = useFocusedStore((s) => s.perspectiveViewSet)
  const busySet = useFocusedStore((s) => s.busySet)
  const queriesCleared = useFocusedStore((s) => s.queriesCleared)
  const searchProgressAdded = useFocusedStore((s) => s.searchProgressAdded)
  const searchProgressCleared = useFocusedStore((s) => s.searchProgressCleared)
  const optimisticPerspectiveAdd = useFocusedStore(
    (s) => s.optimisticPerspectiveAdd,
  )
  const optimisticPerspectiveRemove = useFocusedStore(
    (s) => s.optimisticPerspectiveRemove,
  )
  const sessionId = useFocusedStore((s) => s.sessionId)
  const workspaceId = useFocusedStore((s) => s.workspace?.id ?? null)

  const exclusive = useCallback(
    async <T,>(label: string, operation: () => Promise<T>): Promise<T> => {
      if (useFocusedStore.getState().busy !== null) {
        throw new Error("Wait for the current action to finish.")
      }
      busySet(label)
      try {
        return await operation()
      } finally {
        busySet(null)
      }
    },
    [busySet],
  )

  const requestView = useCallback(
    async (
      path: string,
      init?: RequestInit,
      applyView: (view: WorkspaceView) => void = workspaceViewSet,
    ) => {
      try {
        const view = await api<WorkspaceView>(path, init)
        applyView(view)
        return view
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 409) {
          const currentWorkspaceId = useFocusedStore.getState().workspace?.id
          if (currentWorkspaceId) {
            const latest = await api<WorkspaceView>(
              `workspaces/${currentWorkspaceId}`,
            )
            workspaceViewSet(latest)
          }
        }
        throw cause
      }
    },
    [workspaceViewSet],
  )

  const viewCall = useCallback(
    (label: string, path: string, init?: RequestInit) =>
      exclusive(label, () => requestView(path, init)),
    [exclusive, requestView],
  )

  const call = useCallback(
    async (label: string, path: string, init?: RequestInit) =>
      (await viewCall(label, path, init)).active,
    [viewCall],
  )

  const loadWorkspace = useCallback(
    (id: string) =>
      exclusive("Opening workspace", async () => {
        let lastError: unknown
        for (const delay of [0, 500, 1500, 2500]) {
          if (delay) {
            const { promise, resolve } = Promise.withResolvers<void>()
            window.setTimeout(resolve, delay)
            await promise
          }
          try {
            const view = await api<WorkspaceView>(`workspaces/${id}`)
            workspaceViewSet(view)
            return view.active
          } catch (cause) {
            lastError = cause
            if (
              cause instanceof ApiError &&
              cause.status < 500 &&
              cause.status !== 429
            ) {
              throw cause
            }
          }
        }
        throw lastError
      }),
    [exclusive, workspaceViewSet],
  )

  const deleteWorkspace = useCallback(async () => {
    if (!workspaceId) throw new Error("No active workspace.")
    return exclusive("Deleting workspace", () =>
      api<{ deleted: string }>(`workspaces/${workspaceId}`, {
        method: "DELETE",
      }),
    )
  }, [exclusive, workspaceId])

  const createWorkspace = useCallback(
    async (
      problem: string,
      researchQuestions: string[],
      demo: boolean,
    ) => {
      const view = await viewCall("Starting Investigation", "workspaces", {
        method: "POST",
        body: JSON.stringify({
          problem,
          research_questions: researchQuestions,
          demo,
        }),
      })
      return view.active
    },
    [viewCall],
  )

  const updateBrief = useCallback(
    async (problem: string, researchQuestions: string[]) => {
      const state = await call("Saving brief", `sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify({
          problem,
          research_questions: researchQuestions,
        }),
      })
      queriesCleared()
      return state
    },
    [call, queriesCleared, sessionId],
  )

  const suggestQueries = useCallback(async () => {
    const state = await call(
      "Generating queries",
      `sessions/${sessionId}/suggest-queries`,
      { method: "POST" },
    )
    queriesCleared()
    return state
  }, [call, queriesCleared, sessionId])

  const runSearch = useCallback(
    async (queries: string[]) => {
      if (!sessionId) throw new Error("No active Investigation.")
      return exclusive("Searching literature", async () => {
        const started = await api<{ generation: number }>(
          `sessions/${sessionId}/search-progress`,
          { method: "POST" },
        )
        const generation = started.generation
        searchProgressCleared()
        let polling = true
        let cursor = 0
        const collect = async () => {
          const progress = await api<SearchProgressResponse>(
            `sessions/${sessionId}/search-progress?generation=${generation}&after=${cursor}`,
          )
          for (const item of progress.items) {
            searchProgressAdded(item)
          }
          cursor = progress.next
        }
        const poll = async () => {
          while (polling) {
            try {
              await collect()
            } catch {
              // Progress is advisory; the search request owns error reporting.
            }
            if (polling) {
              await new Promise<void>((resolve) => {
                window.setTimeout(resolve, 150)
              })
            }
          }
        }
        const progress = poll()
        let view: WorkspaceView
        try {
          view = await requestView(
            `sessions/${sessionId}/search`,
            {
              method: "POST",
              body: JSON.stringify({
                queries,
                progress_generation: generation,
              }),
            },
            () => undefined,
          )
        } finally {
          polling = false
          await progress
          try {
            await collect()
          } catch {
            // The completed search result remains authoritative.
          }
        }
        workspaceViewSet(view)
        return view.active
      })
    },
    [
      exclusive,
      requestView,
      searchProgressAdded,
      searchProgressCleared,
      sessionId,
      workspaceViewSet,
    ],
  )

  const generatePerspective = useCallback(
    async (
      clusterId: string,
      facets: FacetEvidence[] | null,
      invitedPerspectiveIds?: string[],
    ) => {
      const current = useFocusedStore.getState()
      if (current.busy !== null) {
        throw new Error("Wait for the current action to finish.")
      }
      const session = current.session
      const cluster = session?.clusters.find((item) => item.id === clusterId)
      if (!session || !cluster) {
        throw new Error("This literature cluster is no longer available.")
      }
      if (
        session.perspectives.some(
          (perspective) =>
            perspective.origin === clusterId && !perspective.evolved,
        )
      ) {
        throw new Error("This Perspective is already in the matrix.")
      }

      const finalFacets = facets ?? cluster.facets
      const optimisticFacets: Partial<Record<Facet, FacetEvidence>> = {}
      for (const evidence of finalFacets) {
        optimisticFacets[evidence.facet] = evidence
      }
      const optimisticId = `optimistic:${session.id}:${clusterId}`
      const optimisticPerspective: Perspective = {
        id: optimisticId,
        name: cluster.name,
        color: "#98a2b3",
        facets: optimisticFacets,
        sources: [
          ...new Set(
            finalFacets.flatMap((evidence) =>
              evidence.paper_id ? [evidence.paper_id] : [],
            ),
          ),
        ].sort(),
        framing: null,
        summary: "",
        evolved: false,
        origin: clusterId,
        source_question_id: null,
        panel_cycle:
          session.deliberations[0]?.completion_history.length ?? 0,
      }

      optimisticPerspectiveAdd(optimisticPerspective)
      try {
        const view = await requestView(
          `sessions/${sessionId}/perspectives`,
          {
            method: "POST",
            body: JSON.stringify({
              cluster_id: clusterId,
              facets,
              invited_perspective_ids: invitedPerspectiveIds,
            }),
          },
          perspectiveViewSet,
        )
        return view.active
      } catch (cause) {
        optimisticPerspectiveRemove(optimisticId)
        throw cause
      }
    },
    [
      optimisticPerspectiveAdd,
      optimisticPerspectiveRemove,
      perspectiveViewSet,
      requestView,
      sessionId,
    ],
  )

  const removePerspective = useCallback(
    (perspectiveId: string) =>
      call(
        "Removing",
        `sessions/${sessionId}/perspectives/${perspectiveId}`,
        { method: "DELETE" },
      ),
    [call, sessionId],
  )


  const createDeliberation = useCallback(
    () =>
      call("Setting up the panel", `sessions/${sessionId}/deliberations`, {
        method: "POST",
      }),
    [call, sessionId],
  )
  const initializeDeliberation = useCallback(
    (deliberationId: string, leadPerspectiveId: string) =>
      call(
        "Generating lead hypothesis",
        `sessions/${sessionId}/deliberations/${deliberationId}/initialize`,
        {
          method: "POST",
          body: JSON.stringify({
            lead_perspective_id: leadPerspectiveId,
          }),
        },
      ),
    [call, sessionId],
  )


  const runRound = useCallback(
    async (deliberationId: string, leadIid: number, threadId: string) =>
      exclusive("Running focused round", async () => {
        const started = await api<{ generation: number }>(
          `sessions/${sessionId}/search-progress`,
          { method: "POST" },
        )
        const generation = started.generation
        searchProgressCleared()
        let polling = true
        let cursor = 0
        const collect = async () => {
          const progress = await api<SearchProgressResponse>(
            `sessions/${sessionId}/search-progress?generation=${generation}&after=${cursor}`,
          )
          progress.items.forEach(searchProgressAdded)
          cursor = progress.next
        }
        const poll = async () => {
          while (polling) {
            try {
              await collect()
            } catch {
              // Progress is advisory; the round request reports failures.
            }
            if (polling) {
              const { promise, resolve } = Promise.withResolvers<void>()
              window.setTimeout(resolve, 500)
              await promise
            }
          }
        }
        const progress = poll()
        let view: WorkspaceView
        try {
          view = await requestView(
            `sessions/${sessionId}/deliberations/${deliberationId}/rounds`,
            {
              method: "POST",
              body: JSON.stringify({
                lead_iid: leadIid,
                thread_id: threadId,
                progress_generation: generation,
              }),
            },
            () => undefined,
          )
        } finally {
          polling = false
          await progress
          try {
            await collect()
          } catch {
            // The final round response remains authoritative.
          }
        }
        workspaceViewSet(view)
        return view.active
      }),
    [
      exclusive,
      requestView,
      searchProgressAdded,
      searchProgressCleared,
      sessionId,
      workspaceViewSet,
    ],
  )
  const completeDeliberation = useCallback(
    (deliberationId: string, selectedQuestionIds: string[]) =>
      call(
        "Ending deliberation",
        `sessions/${sessionId}/deliberations/${deliberationId}/complete`,
        {
          method: "POST",
          body: JSON.stringify({
            selected_question_ids: selectedQuestionIds,
          }),
        },
      ),
    [call, sessionId],
  )
  const rateDeliberation = useCallback(
    (
      deliberationId: string,
      rating: Pick<
        DeliberationRating,
        "divergent" | "convergent" | "note"
      >,
    ) =>
      call(
        "Saving deliberation scores",
        `sessions/${sessionId}/deliberations/${deliberationId}/rating`,
        {
          method: "PUT",
          body: JSON.stringify(rating),
        },
      ),
    [call, sessionId],
  )

  const confirmHypothesis = useCallback(
    (
      deliberationId: string,
      hypothesis: HypothesisDev,
      mode: HypothesisConfirmationMode,
    ) =>
      call(
        "Applying hypothesis",
        `sessions/${sessionId}/deliberations/${deliberationId}/hypothesis`,
        {
          method: "PUT",
          body: JSON.stringify({ hypothesis, mode }),
        },
      ),
    [call, sessionId],
  )
  const saveHypothesis = useCallback(
    (deliberationId: string) =>
      call(
        "Saving hypothesis checkpoint",
        `sessions/${sessionId}/deliberations/${deliberationId}/hypothesis/checkpoint`,
        { method: "POST" },
      ),
    [call, sessionId],
  )




  const createChildInvestigation = useCallback(
    async (questionId: string) => {
      if (!workspaceId || !sessionId) throw new Error("No active Investigation.")
      const view = await viewCall(
        "Starting child Investigation",
        `workspaces/${workspaceId}/investigations/${sessionId}/questions/${questionId}/child`,
        { method: "POST" },
      )
      return view.active
    },
    [sessionId, viewCall, workspaceId],
  )

  const loadSession = useCallback(
    (investigationId: string) =>
      api<SessionState>(`sessions/${investigationId}`),
    [],
  )

  const integrateChildInvestigation = useCallback(
    async (invitedPerspectiveIds?: string[]) => {
      const active = useFocusedStore.getState().session
      const parentId = active?.parent_investigation_id
      if (!workspaceId || !sessionId || !parentId) {
        throw new Error("No active research branch to integrate.")
      }
      const view = await viewCall(
        "Adding research branch to panel",
        `workspaces/${workspaceId}/investigations/${parentId}/children/${sessionId}/integrate`,
        {
          method: "POST",
          body: JSON.stringify({
            invited_perspective_ids: invitedPerspectiveIds,
          }),
        },
      )
      return view.active
    },
    [sessionId, viewCall, workspaceId],
  )

  const switchInvestigation = useCallback(
    async (investigationId: string) => {
      if (!workspaceId) throw new Error("No active workspace.")
      const view = await viewCall(
        "Opening Investigation",
        `workspaces/${workspaceId}/investigations/${investigationId}/active`,
        { method: "PUT" },
      )
      return view.active
    },
    [viewCall, workspaceId],
  )

  const updateQuestionStatus = useCallback(
    async (questionId: string, status: QuestionStatus) => {
      if (!workspaceId || !sessionId) throw new Error("No active Investigation.")
      return viewCall(
        "Updating question",
        `workspaces/${workspaceId}/investigations/${sessionId}/questions/${questionId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ status }),
        },
      )
    },
    [sessionId, viewCall, workspaceId],
  )

  const promoteHypothesis = useCallback(
    async (versionId: string) => {
      if (!workspaceId) throw new Error("No active workspace.")
      return viewCall(
        "Promoting hypothesis",
        `workspaces/${workspaceId}/hypotheses/${versionId}/promote`,
        { method: "PUT" },
      )
    },
    [viewCall, workspaceId],
  )

  const mergeHypotheses = useCallback(
    async (
      targetInvestigationId: string,
      sourceVersionId: string,
      hypothesis: HypothesisDev,
    ) => {
      if (!workspaceId) throw new Error("No active workspace.")
      return viewCall(
        "Merging hypotheses",
        `workspaces/${workspaceId}/hypotheses/merge`,
        {
          method: "POST",
          body: JSON.stringify({
            target_investigation_id: targetInvestigationId,
            source_version_id: sourceVersionId,
            hypothesis,
          }),
        },
      )
    },
    [viewCall, workspaceId],
  )

  const archiveHypothesis = useCallback(
    async (versionId: string) => {
      if (!workspaceId) throw new Error("No active workspace.")
      return viewCall(
        "Archiving hypothesis",
        `workspaces/${workspaceId}/hypotheses/${versionId}`,
        { method: "DELETE" },
      )
    },
    [viewCall, workspaceId],
  )

  const restoreHypothesis = useCallback(
    async (versionId: string) => {
      if (!workspaceId) throw new Error("No active workspace.")
      return viewCall(
        "Restoring hypothesis",
        `workspaces/${workspaceId}/hypotheses/${versionId}/restore`,
        { method: "PUT" },
      )
    },
    [viewCall, workspaceId],
  )

  const sendChat = useCallback(
    (
      deliberationId: string,
      message: string,
      targetIid: number | null,
    ) =>
      call("Deliberating", `sessions/${sessionId}/chat`, {
        method: "POST",
        body: JSON.stringify({
          deliberation_id: deliberationId,
          message,
          target_iid: targetIid,
          proactivity: "high",
        }),
      }),
    [call, sessionId],
  )

  const fetchPaper = useCallback(
    (paperId: string) => api<PaperDetail>(`sessions/${sessionId}/papers/${paperId}`),
    [sessionId],
  )

  return {
    loadWorkspace,
    deleteWorkspace,
    createWorkspace,
    updateBrief,
    suggestQueries,
    runSearch,
    generatePerspective,
    removePerspective,
    createDeliberation,
    initializeDeliberation,
    runRound,
    completeDeliberation,
    rateDeliberation,
    confirmHypothesis,
    saveHypothesis,
    createChildInvestigation,
    loadSession,
    integrateChildInvestigation,
    switchInvestigation,
    updateQuestionStatus,
    promoteHypothesis,
    mergeHypotheses,
    archiveHypothesis,
    restoreHypothesis,
    sendChat,
    fetchPaper,
  }
}

