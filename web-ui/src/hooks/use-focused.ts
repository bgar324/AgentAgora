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
 * Mutations return one authoritative WorkspaceView. Calls are serialized in the
 * browser so an older response cannot overwrite a newer workspace snapshot.
 */
export function useFocusedPanel() {
  const workspaceViewSet = useFocusedStore((s) => s.workspaceViewSet)
  const busySet = useFocusedStore((s) => s.busySet)
  const queriesCleared = useFocusedStore((s) => s.queriesCleared)
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

  const viewCall = useCallback(
    (label: string, path: string, init?: RequestInit) =>
      exclusive(label, async () => {
        try {
          const view = await api<WorkspaceView>(path, init)
          workspaceViewSet(view)
          return view
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 409) {
            const currentWorkspaceId =
              useFocusedStore.getState().workspace?.id
            if (currentWorkspaceId) {
              const latest = await api<WorkspaceView>(
                `workspaces/${currentWorkspaceId}`,
              )
              workspaceViewSet(latest)
            }
          }
          throw cause
        }
      }),
    [exclusive, workspaceViewSet],
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
    (queries: string[]) =>
      call("Searching literature", `sessions/${sessionId}/search`, {
        method: "POST",
        body: JSON.stringify({ queries }),
      }),
    [call, sessionId],
  )

  const generatePerspective = useCallback(
    async (clusterId: string, facets: FacetEvidence[] | null) => {
      const current = useFocusedStore.getState()
      if (current.busy !== null) {
        throw new Error("Wait for the current action to finish.")
      }
      const session = current.session
      const cluster = session?.clusters.find((item) => item.id === clusterId)
      if (!session || !cluster) {
        throw new Error("This literature cluster is no longer available.")
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
      }

      optimisticPerspectiveAdd(optimisticPerspective)
      try {
        return await call("Generating perspective", `sessions/${sessionId}/perspectives`, {
          method: "POST",
          body: JSON.stringify({ cluster_id: clusterId, facets }),
        })
      } catch (cause) {
        optimisticPerspectiveRemove(optimisticId)
        throw cause
      }
    },
    [
      call,
      optimisticPerspectiveAdd,
      optimisticPerspectiveRemove,
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

  const runRound = useCallback(
    (deliberationId: string, leadIid: number, facets: Facet[]) =>
      call(
        "Running focused round",
        `sessions/${sessionId}/deliberations/${deliberationId}/rounds`,
        {
          method: "POST",
          body: JSON.stringify({ lead_iid: leadIid, facets }),
        },
      ),
    [call, sessionId],
  )
  const completeDeliberation = useCallback(
    (deliberationId: string) =>
      call(
        "Ending deliberation",
        `sessions/${sessionId}/deliberations/${deliberationId}/complete`,
        { method: "POST" },
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
      partsFromSource: HypothesisPart[],
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
            parts_from_source: partsFromSource,
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
          proactivity: "med",
        }),
      }),
    [call, sessionId],
  )

  const fetchPaper = useCallback(
    (paperId: string) => api<PaperDetail>(`sessions/${sessionId}/papers/${paperId}`),
    [sessionId],
  )

  const exportWorkspace = useCallback(async () => {
    if (!workspaceId) throw new Error("No active workspace.")
    return exclusive("Exporting workspace", async () => {
      const payload = await api<Record<string, unknown>>(
        `workspaces/${workspaceId}/export`,
      )
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `hypothesis-workspace-${workspaceId}.json`
      a.click()
      URL.revokeObjectURL(url)
    })
  }, [exclusive, workspaceId])

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
    runRound,
    completeDeliberation,
    rateDeliberation,
    confirmHypothesis,
    saveHypothesis,
    createChildInvestigation,
    switchInvestigation,
    updateQuestionStatus,
    promoteHypothesis,
    mergeHypotheses,
    archiveHypothesis,
    restoreHypothesis,
    sendChat,
    fetchPaper,
    exportWorkspace,
  }
}

