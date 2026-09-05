"use client"

import { useCallback } from "react"

import { useFocusedStore } from "@/store/focused"
import { MAX_PERSPECTIVES, NOTEPAD_PARTS } from "@/types/focused"
import type {
  NotepadDoc,
  NotepadPart,
  PaperDetail,
  Perspective,
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
type CreateWorkspaceInput = {
  problem: string
  demo: boolean
  position: NotepadDoc
}


function isPathSegment(value: unknown): value is string | number {
  return typeof value === "string" || typeof value === "number"
}

function apiErrorMessage(payload: unknown, fallback: string): string {
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("detail" in payload)
  ) {
    return fallback
  }
  const detail = payload.detail
  if (typeof detail === "string") return detail.trim() || fallback
  if (
    typeof detail === "object" &&
    detail !== null &&
    "message" in detail &&
    typeof detail.message === "string"
  ) {
    return detail.message.trim() || fallback
  }
  if (!Array.isArray(detail)) return fallback
  const messages = detail.flatMap((entry) => {
    if (typeof entry === "string") {
      const message = entry.trim()
      return message ? [message] : []
    }
    if (
      typeof entry !== "object" ||
      entry === null ||
      !("msg" in entry) ||
      typeof entry.msg !== "string"
    ) {
      return []
    }
    const message = entry.msg.trim()
    if (!message) return []
    const location = "loc" in entry ? entry.loc : undefined
    const path = Array.isArray(location)
      ? location
          .filter(isPathSegment)
          .filter((segment) => segment !== "body")
          .join(".")
      : ""
    return [path ? `${path}: ${message}` : message]
  })
  return messages.length > 0 ? messages.join("; ") : fallback
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/focused/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText || "Request failed"
    try {
      detail = apiErrorMessage(await response.json(), detail)
    } catch {
      // Keep the HTTP status text when the response is not JSON.
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
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
const NOTEPAD_DRAFTS_KEY = "focused-notepad-drafts"

function persistNotepadDrafts() {
  if (typeof window === "undefined") return
  const drafts = [...latestNotepadEdits.values()]
  try {
    if (drafts.length === 0) {
      window.localStorage.removeItem(NOTEPAD_DRAFTS_KEY)
    } else {
      window.localStorage.setItem(NOTEPAD_DRAFTS_KEY, JSON.stringify(drafts))
    }
  } catch {
    // Autosave continues when browser storage is unavailable.
  }
}

function restoreNotepadDrafts(sessionId: string) {
  if (typeof window === "undefined") return
  let stored: unknown
  try {
    const raw = window.localStorage.getItem(NOTEPAD_DRAFTS_KEY)
    if (!raw) return
    stored = JSON.parse(raw)
  } catch {
    return
  }
  if (!Array.isArray(stored)) return
  for (const item of stored) {
    if (
      typeof item !== "object" ||
      item === null ||
      !("sessionId" in item) ||
      item.sessionId !== sessionId ||
      !("versionId" in item) ||
      typeof item.versionId !== "string" ||
      !("part" in item) ||
      typeof item.part !== "string" ||
      !("text" in item) ||
      typeof item.text !== "string"
    ) {
      continue
    }
    const part = NOTEPAD_PARTS.find((candidate) => candidate === item.part)
    if (!part) continue
    const key = `${sessionId}:${item.versionId}:${part}`
    if (!latestNotepadEdits.has(key)) {
      latestNotepadEdits.set(key, {
        sessionId,
        versionId: item.versionId,
        part,
        text: item.text,
      })
    }
  }
}

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
  persistNotepadDrafts()
  return edit
}

/** One hook for the single baseline product surface. */
export function useFocusedPanel() {
  const workspaceViewSet = useFocusedStore((state) => state.workspaceViewSet)
  const busySet = useFocusedStore((state) => state.busySet)
  const queriesCleared = useFocusedStore((state) => state.queriesCleared)
  const searchProgressAdded = useFocusedStore(
    (state) => state.searchProgressAdded,
  )
  const searchProgressCleared = useFocusedStore(
    (state) => state.searchProgressCleared,
  )
  const optimisticPerspectiveAdd = useFocusedStore(
    (state) => state.optimisticPerspectiveAdd,
  )
  const optimisticPerspectiveRemove = useFocusedStore(
    (state) => state.optimisticPerspectiveRemove,
  )
  const notepadDraftStaged = useFocusedStore(
    (state) => state.notepadDraftStaged,
  )
  const notepadDraftAcknowledged = useFocusedStore(
    (state) => state.notepadDraftAcknowledged,
  )
  const sessionId = useFocusedStore((state) => state.sessionId)
  const workspaceId = useFocusedStore((state) => state.workspace?.id ?? null)

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
            await new Promise<void>((resolve) => window.setTimeout(resolve, delay))
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
    async ({
      problem,
      demo,
      position,
    }: CreateWorkspaceInput) => {
      const view = await viewCall("Starting study", "workspaces", {
        method: "POST",
        body: JSON.stringify({
          problem,
          position,
          demo,
        }),
      })
      return view.active
    },
    [viewCall],
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
      if (!sessionId) throw new Error("No active study.")
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
          for (const item of progress.items) searchProgressAdded(item)
          cursor = progress.next
        }
        const poll = async () => {
          while (polling) {
            try {
              await collect()
            } catch {
              // Progress is advisory; the search request reports failures.
            }
            if (polling) {
              await new Promise<void>((resolve) => window.setTimeout(resolve, 150))
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
            // The completed search response remains authoritative.
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
      paperId: string,
      persona?: { name?: string; description?: string },
    ) => {
      const current = useFocusedStore.getState()
      if (current.busy !== null) {
        throw new Error("Wait for the current action to finish.")
      }
      const session = current.session
      const paper = session?.papers.find((item) => item.id === paperId)
      if (!session || !paper) {
        throw new Error("This paper is no longer available.")
      }
      if (session.perspectives.length >= MAX_PERSPECTIVES) {
        throw new Error("A study supports at most six Perspectives.")
      }
      if (
        session.perspectives.some(
          (perspective) => perspective.anchor_paper_id === paper.id,
        )
      ) {
        throw new Error("This paper already has a Perspective.")
      }
      const optimisticId = `optimistic:${session.id}:${paper.id}`
      const optimisticPerspective: Perspective = {
        id: optimisticId,
        name: persona?.name?.trim() || paper.title,
        color: "#98a2b3",
        summary: persona?.description?.trim() ?? "",
        anchor_paper_id: paper.id,
        related_paper_count: 0,
      }
      optimisticPerspectiveAdd(optimisticPerspective)
      try {
        const view = await requestView(`sessions/${sessionId}/perspectives`, {
          method: "POST",
          body: JSON.stringify({
            paper_id: paper.id,
            name: persona?.name?.trim() || null,
            description: persona?.description?.trim() || null,
          }),
        })
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

  const fetchPaper = useCallback(
    (paperId: string) =>
      api<PaperDetail>(`sessions/${sessionId}/papers/${paperId}`),
    [sessionId],
  )


  const stageNotepadPart = useCallback(
    (versionId: string, part: NotepadPart, text: string) => {
      if (sessionId === null) return
      stageNotepadEdit(sessionId, versionId, part, text)
      notepadDraftStaged(versionId, part, text)
    },
    [notepadDraftStaged, sessionId],
  )

  const editNotepadPart = useCallback(
    (versionId: string, part: NotepadPart, text: string) => {
      if (sessionId === null) {
        return Promise.reject(new Error("No active study."))
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
        notepadDraftAcknowledged(versionId, part, edit.text)
        savedNotepadTexts.set(queueKey, edit.text)
        if (latestNotepadEdits.get(queueKey) === edit) {
          latestNotepadEdits.delete(queueKey)
          persistNotepadDrafts()
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
    [
      notepadDraftAcknowledged,
      requestView,
      sessionId,
      workspaceViewSet,
    ],
  )

  const flushNotepadEdits = useCallback(() => {
    if (sessionId === null) return Promise.resolve()
    restoreNotepadDrafts(sessionId)
    for (const edit of latestNotepadEdits.values()) {
      if (edit.sessionId === sessionId) {
        notepadDraftStaged(edit.versionId, edit.part, edit.text)
      }
    }
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
  }, [editNotepadPart, notepadDraftStaged, sessionId])

  const notepadCall = useCallback(
    (label: string, path: string, init?: RequestInit, skipDraftFlush = false) =>
      exclusive(label, async () => {
        if (!skipDraftFlush) await flushNotepadEdits()
        const view = await requestView(
          `sessions/${sessionId}/notepad/${path}`,
          init,
        )
        return view.active
      }),
    [exclusive, flushNotepadEdits, requestView, sessionId],
  )

  const startNotepad = useCallback(
    () => notepadCall("Opening the discussion", "start", { method: "POST" }, true),
    [notepadCall],
  )

  const addNotepadVersion = useCallback(
    async (copyCurrent: boolean) => {
      return notepadCall("Starting a version", "versions", {
        method: "POST",
        body: JSON.stringify({ copy_current: copyCurrent }),
      })
    },
    [notepadCall],
  )

  const switchNotepadVersion = useCallback(
    async (versionId: string, skipDraftFlush = false) => {
      return notepadCall(
        "Switching version",
        `versions/${versionId}`,
        { method: "PUT" },
        skipDraftFlush,
      )
    },
    [notepadCall],
  )

  const deleteNotepadVersion = useCallback(
    async (versionId: string) => {
      return notepadCall("Deleting version", `versions/${versionId}`, {
        method: "DELETE",
      })
    },
    [notepadCall],
  )

  const discussNotepad = useCallback(
    async (versionId: string, turns: number) => {
      return notepadCall("Agents discussing", "discuss", {
        method: "POST",
        body: JSON.stringify({ version_id: versionId, turns }),
      })
    },
    [notepadCall],
  )

  const generateNotepadTopics = useCallback(async () => {
    return notepadCall("Generating topics", "topics", { method: "POST" })
  }, [notepadCall])

  const askNotepad = useCallback(
    async (
      versionId: string,
      message: string,
      topicId: string | null = null,
    ) => {
      return notepadCall("Sending", "messages", {
        method: "POST",
        body: JSON.stringify({
          version_id: versionId,
          message,
          topic_id: topicId,
        }),
      })
    },
    [notepadCall],
  )

  const summarizeNotepad = useCallback(
    async (versionId: string) => {
      return notepadCall("Summarizing", "summaries", {
        method: "POST",
        body: JSON.stringify({ version_id: versionId }),
      })
    },
    [notepadCall],
  )

  const restartNotepadReview = useCallback(
    async (versionId: string) => {
      return notepadCall("Restarting review", "restart", {
        method: "POST",
        body: JSON.stringify({ version_id: versionId }),
      })
    },
    [notepadCall],
  )

  const clearNotepadChat = useCallback(async () => {
    return notepadCall("Clearing the chat", "chat", { method: "DELETE" })
  }, [notepadCall])

  const finishNotepadStudy = useCallback(async () => {
    return notepadCall("Finishing study", "finish", { method: "POST" })
  }, [notepadCall])

  return {
    loadWorkspace,
    deleteWorkspace,
    createWorkspace,
    suggestQueries,
    runSearch,
    generatePerspective,
    removePerspective,
    fetchPaper,
    startNotepad,
    stageNotepadPart,
    editNotepadPart,
    flushNotepadEdits,
    addNotepadVersion,
    switchNotepadVersion,
    deleteNotepadVersion,
    discussNotepad,
    generateNotepadTopics,
    askNotepad,
    summarizeNotepad,
    restartNotepadReview,
    clearNotepadChat,
    finishNotepadStudy,
  }
}
