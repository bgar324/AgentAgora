"use client"

import { useCallback } from "react"

import { useFocusedStore } from "@/store/focused"
import type {
  Facet,
  FacetEvidence,
  HypothesisConfirmationMode,
  HypothesisDev,
  NotepadDoc,
  NotepadPart,
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

type PendingNotepadEdit = {
  sessionId: string
  versionId: string
  part: NotepadPart
  text: string
}

const notepadEditQueues = new Map<string, Promise<void>>()
const latestNotepadEdits = new Map<string, PendingNotepadEdit>()
const savedNotepadTexts = new Map<string, string>()
const queuedNotepadEdits = new Map<
  string,
  { edit: PendingNotepadEdit; request: Promise<void> }
>()
const notepadFlushes = new Map<string, Promise<void>>()

function stageNotepadEdit(
  sessionId: string,
  versionId: string,
  part: NotepadPart,
  text: string,
): PendingNotepadEdit {
  const key = `${sessionId}:${versionId}:${part}`
  const current = latestNotepadEdits.get(key)
  if (current?.text === text) return current
  const edit = { sessionId, versionId, part, text }
  latestNotepadEdits.set(key, edit)
  return edit
}

/**
 * Most mutations are exclusive. Perspective generation may run concurrently;
 * workspace revisions reject stale responses while pending adds remain visible.
 */
export function useFocusedPanel() {
  const workspaceViewSet = useFocusedStore((s) => s.workspaceViewSet)
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
            applyView(latest)
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
      study?: { position?: NotepadDoc; arm?: "baseline" | "guided" },
    ) => {
      const view = await viewCall("Starting Investigation", "workspaces", {
        method: "POST",
        body: JSON.stringify({
          problem,
          research_questions: researchQuestions,
          position: study?.position ?? null,
          arm: study?.arm ?? "guided",
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
      source:
        | { paperId: string }
        | { clusterId: string; facets: FacetEvidence[] | null },
      persona?: { name?: string; description?: string },
      invitedPerspectiveIds?: string[],
    ) => {
      const current = useFocusedStore.getState()
      if (current.busy !== null) {
        throw new Error("Wait for the current action to finish.")
      }
      const session = current.session
      const paper =
        session && "paperId" in source
          ? session.papers.find((item) => item.id === source.paperId)
          : null
      const cluster =
        session && "clusterId" in source
          ? session.clusters.find((item) => item.id === source.clusterId)
          : null
      if (!session || (!paper && !cluster)) {
        throw new Error("This literature source is no longer available.")
      }

      const origin = paper ? `paper:${paper.id}` : cluster!.id
      if (
        session.perspectives.some(
          (perspective) =>
            perspective.origin === origin && !perspective.evolved,
        )
      ) {
        throw new Error("This Perspective is already in the matrix.")
      }

      const finalFacets =
        cluster && "facets" in source
          ? (source.facets ?? cluster.facets)
          : []
      const optimisticFacets: Partial<Record<Facet, FacetEvidence>> = {}
      for (const evidence of finalFacets) {
        optimisticFacets[evidence.facet] = evidence
      }
      const sourceId = paper?.id ?? cluster!.id
      const optimisticId = `optimistic:${session.id}:${sourceId}`
      const optimisticPerspective: Perspective = {
        id: optimisticId,
        name: persona?.name?.trim() || paper?.title || cluster!.name,
        color: "#98a2b3",
        facets: optimisticFacets,
        sources: paper
          ? [paper.id]
          : [
              ...new Set(
                finalFacets.flatMap((evidence) =>
                  evidence.paper_id ? [evidence.paper_id] : [],
                ),
              ),
            ].sort(),
        framing: null,
        summary: persona?.description?.trim() ?? "",
        evolved: false,
        origin,
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
              cluster_id: cluster?.id ?? null,
              paper_id: paper?.id ?? null,
              facets: cluster && "facets" in source ? source.facets : null,
              name: persona?.name?.trim() || null,
              description: persona?.description?.trim() || null,
              invited_perspective_ids: invitedPerspectiveIds,
            }),
          },
        )
        return view.active
      } finally {
        optimisticPerspectiveRemove(optimisticId)
      }
    },
    [
      optimisticPerspectiveAdd,
      optimisticPerspectiveRemove,
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

  const decideResolution = useCallback(
    (
      deliberationId: string,
      roundN: number,
      decision: "accept" | "edit" | "keep_open",
      summary?: string,
      note?: string,
    ) =>
      call(
        "Reviewing Thread resolution",
        `sessions/${sessionId}/deliberations/${deliberationId}/rounds/${roundN}/resolution`,
        {
          method: "PUT",
          body: JSON.stringify({
            decision,
            summary: summary ?? null,
            note: note ?? "",
          }),
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

  // Dialogue commands render loading on their triggering button and rely
  // on the authoritative WorkspaceView response alone; no advisory
  // progress stream reaches the panel surfaces.
  const dialogueCommand = useCallback(
    async (label: string, path: string, body: Record<string, unknown>) =>
      exclusive(label, async () => {
        const view = await requestView(`sessions/${sessionId}/${path}`, {
          method: "POST",
          body: JSON.stringify(body),
        })
        return view.active
      }),
    [exclusive, requestView, sessionId],
  )

  // Notepad stage. Every command returns the authoritative WorkspaceView;
  // loading lives on the triggering control.
  const notepadCall = useCallback(
    (label: string, path: string, init?: RequestInit) =>
      exclusive(label, async () => {
        const view = await requestView(
          `sessions/${sessionId}/notepad/${path}`,
          init,
        )
        return view.active
      }),
    [exclusive, requestView, sessionId],
  )

  const startNotepad = useCallback(
    () => notepadCall("Opening the group chat", "start", { method: "POST" }),
    [notepadCall],
  )

  const stageNotepadPart = useCallback(
    (versionId: string, part: NotepadPart, text: string) => {
      if (sessionId === null) return
      stageNotepadEdit(sessionId, versionId, part, text)
    },
    [sessionId],
  )

  const editNotepadPart = useCallback(
    (versionId: string, part: NotepadPart, text: string) => {
      if (sessionId === null) {
        return Promise.reject(new Error("No active investigation."))
      }
      const queueKey = `${sessionId}:${versionId}:${part}`
      if (
        latestNotepadEdits.get(queueKey) === undefined &&
        savedNotepadTexts.get(queueKey) === text
      ) {
        return Promise.resolve()
      }
      const edit = stageNotepadEdit(sessionId, versionId, part, text)
      const queued = queuedNotepadEdits.get(queueKey)
      if (queued?.edit === edit) return queued.request

      const previous = notepadEditQueues.get(queueKey) ?? Promise.resolve()
      const request = previous.then(async () => {
        await requestView(
          `sessions/${sessionId}/notepad/part`,
          {
            method: "PATCH",
            body: JSON.stringify({ version_id: versionId, part, text }),
          },
          (nextView) => {
            const current = useFocusedStore.getState()
            if (
              current.sessionId === sessionId &&
              current.workspace?.id === nextView.workspace.id
            ) {
              workspaceViewSet(nextView)
            }
          },
        )
        savedNotepadTexts.set(queueKey, edit.text)
        if (latestNotepadEdits.get(queueKey) === edit) {
          latestNotepadEdits.delete(queueKey)
        }
      })
      const settled = request.then(
        () => undefined,
        () => undefined,
      )
      const queuedEdit = { edit, request }
      notepadEditQueues.set(queueKey, settled)
      queuedNotepadEdits.set(queueKey, queuedEdit)
      void settled.then(() => {
        if (notepadEditQueues.get(queueKey) === settled) {
          notepadEditQueues.delete(queueKey)
        }
        if (queuedNotepadEdits.get(queueKey) === queuedEdit) {
          queuedNotepadEdits.delete(queueKey)
        }
      })
      return request
    },
    [requestView, sessionId, workspaceViewSet],
  )

  const flushNotepadEdits = useCallback(() => {
    if (sessionId === null) return Promise.resolve()
    const running = notepadFlushes.get(sessionId)
    if (running) return running

    const operation = (async () => {
      const queuePrefix = `${sessionId}:`
      while (true) {
        const queued = [...notepadEditQueues.entries()]
          .filter(([key]) => key.startsWith(queuePrefix))
          .map(([, request]) => request)
        if (queued.length > 0) {
          await Promise.all(queued)
          continue
        }
        const unsaved = [...latestNotepadEdits.values()].filter(
          (edit) => edit.sessionId === sessionId,
        )
        if (unsaved.length === 0) return
        await Promise.all(
          unsaved.map((edit) =>
            editNotepadPart(edit.versionId, edit.part, edit.text),
          ),
        )
      }
    })()
    notepadFlushes.set(sessionId, operation)
    const clear = () => {
      if (notepadFlushes.get(sessionId) === operation) {
        notepadFlushes.delete(sessionId)
      }
    }
    void operation.then(clear, clear)
    return operation
  }, [editNotepadPart, sessionId])

  const addNotepadVersion = useCallback(
    async (copyCurrent: boolean) => {
      await flushNotepadEdits()
      return notepadCall("Starting a version", "versions", {
        method: "POST",
        body: JSON.stringify({ copy_current: copyCurrent }),
      })
    },
    [flushNotepadEdits, notepadCall],
  )

  const switchNotepadVersion = useCallback(
    async (versionId: string) => {
      await flushNotepadEdits()
      return notepadCall("Switching version", `versions/${versionId}`, {
        method: "PUT",
      })
    },
    [flushNotepadEdits, notepadCall],
  )

  const deleteNotepadVersion = useCallback(
    async (versionId: string) => {
      await flushNotepadEdits()
      return notepadCall("Deleting version", `versions/${versionId}`, {
        method: "DELETE",
      })
    },
    [flushNotepadEdits, notepadCall],
  )

  const setNotepadParticipant = useCallback(
    (perspectiveId: string, participating: boolean) =>
      notepadCall("Updating the chat", "participants", {
        method: "PUT",
        body: JSON.stringify({
          perspective_id: perspectiveId,
          participating,
        }),
      }),
    [notepadCall],
  )

  const discussNotepad = useCallback(
    (turns: number) =>
      notepadCall("Agents discussing", "discuss", {
        method: "POST",
        body: JSON.stringify({ turns }),
      }),
    [notepadCall],
  )

  const askNotepad = useCallback(
    (message: string) =>
      notepadCall("Sending", "messages", {
        method: "POST",
        body: JSON.stringify({ message }),
      }),
    [notepadCall],
  )

  const summarizeNotepad = useCallback(
    (part: string) =>
      notepadCall("Summarizing", "summaries", {
        method: "POST",
        body: JSON.stringify({ part }),
      }),
    [notepadCall],
  )

  const decideNotepadProposal = useCallback(
    (
      proposalId: string,
      action: "approve" | "edit" | "reject",
      extra?: { text?: string; reason?: string },
    ) =>
      notepadCall("Recording your decision", "decisions", {
        method: "POST",
        body: JSON.stringify({
          proposal_id: proposalId,
          action,
          text: extra?.text ?? null,
          reason: extra?.reason ?? "",
        }),
      }),
    [notepadCall],
  )

  const clearNotepadChat = useCallback(
    () => notepadCall("Clearing the chat", "chat", { method: "DELETE" }),
    [notepadCall],
  )

  const startDialogue = useCallback(
    () => dialogueCommand("Starting deliberation", "dialogue/start", {}),
    [dialogueCommand],
  )

  const selectDialogueDirections = useCallback(
    (proposalIds: string[]) =>
      dialogueCommand("Creating Working Document", "dialogue/selection", {
        proposal_ids: proposalIds,
      }),
    [dialogueCommand],
  )

  const openDialogueThread = useCallback(
    (threadId: string) =>
      dialogueCommand("Discussing Thread", "dialogue/threads/open", {
        thread_id: threadId,
      }),
    [dialogueCommand],
  )

  const messageDialogueThread = useCallback(
    (threadId: string, message: string, replyTo?: string) =>
      dialogueCommand("Sending message", "dialogue/messages", {
        thread_id: threadId,
        message,
        reply_to: replyTo ?? null,
      }),
    [dialogueCommand],
  )

  const decideDialogueThread = useCallback(
    (
      resolutionId: string,
      action: "close" | "edit_close" | "keep_open" | "request_evidence",
      edits?: {
        consensus?: string
        disagreement?: string
        open_question?: string
      },
    ) =>
      dialogueCommand("Reviewing resolution", "dialogue/decisions", {
        resolution_id: resolutionId,
        action,
        ...edits,
      }),
    [dialogueCommand],
  )

  const continueDialogueFromResolution = useCallback(
    (resolutionId: string) =>
      dialogueCommand(
        "Continuing deliberation",
        "dialogue/threads/continue",
        { resolution_id: resolutionId },
      ),
    [dialogueCommand],
  )

  const fetchDialogueReport = useCallback(
    () => api<{ report: string }>(`sessions/${sessionId}/dialogue/report`),
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
    decideResolution,
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
    startDialogue,
    selectDialogueDirections,
    openDialogueThread,
    messageDialogueThread,
    decideDialogueThread,
    continueDialogueFromResolution,
    fetchDialogueReport,
    startNotepad,
    stageNotepadPart,
    editNotepadPart,
    flushNotepadEdits,
    addNotepadVersion,
    switchNotepadVersion,
    deleteNotepadVersion,
    setNotepadParticipant,
    discussNotepad,
    askNotepad,
    summarizeNotepad,
    decideNotepadProposal,
    clearNotepadChat,
  }
}

