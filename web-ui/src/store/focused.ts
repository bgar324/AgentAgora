"use client"

import { create } from "zustand"

import type {
  NotepadPart,
  Perspective,
  SearchProgressItem,
  SessionState,
  WorkspaceState,
  WorkspaceView,
} from "@/types/focused"

const MAX_SEARCH_PROGRESS_EVENTS = 192

type Stage = "extraction" | "deliberation"

export function notepadDraftKey(versionId: string, part: NotepadPart) {
  return `${versionId}:${part}`
}

type FocusedState = {
  workspace: WorkspaceState | null
  sessionId: string | null
  session: SessionState | null
  stage: Stage
  pickedQueries: string[]
  openPaperId: string | null
  busy: string | null
  searchProgress: SearchProgressItem[]
  notepadDrafts: Record<string, string>
}

type FocusedActions = {
  workspaceViewSet: (view: WorkspaceView) => void
  optimisticPerspectiveAdd: (perspective: Perspective) => void
  optimisticPerspectiveRemove: (id: string) => void
  notepadDraftStaged: (
    versionId: string,
    part: NotepadPart,
    text: string,
  ) => void
  notepadDraftAcknowledged: (
    versionId: string,
    part: NotepadPart,
    text: string,
  ) => void
  stageSet: (stage: Stage) => void
  queryToggled: (query: string) => void
  queriesCleared: () => void
  searchProgressAdded: (item: SearchProgressItem) => void
  searchProgressCleared: () => void
  openPaperSet: (id: string | null) => void
  busySet: (label: string | null) => void
  reset: () => void
}

const initialState: FocusedState = {
  workspace: null,
  sessionId: null,
  session: null,
  stage: "extraction",
  pickedQueries: [],
  openPaperId: null,
  busy: null,
  searchProgress: [],
  notepadDrafts: {},
}

function workspaceViewPatch(
  state: FocusedState,
  view: WorkspaceView,
): Partial<FocusedState> {
  const currentWorkspace = state.workspace
  const sameWorkspace = currentWorkspace?.id === view.workspace.id
  if (
    sameWorkspace &&
    currentWorkspace !== null &&
    currentWorkspace.revision > view.workspace.revision
  ) {
    return {}
  }
  const activeChanged = state.sessionId !== view.active.id
  const currentSession = sameWorkspace && !activeChanged ? state.session : null
  const finished = view.active.notepad?.final_snapshot != null
  const representedAnchors = new Set(
    view.active.perspectives.map((perspective) => perspective.anchor_paper_id),
  )
  const pendingPerspectives = finished
    ? []
    : (currentSession?.perspectives.filter(
        (perspective) =>
          perspective.id.startsWith("optimistic:") &&
          !representedAnchors.has(perspective.anchor_paper_id),
      ) ?? [])
  const active =
    pendingPerspectives.length > 0
      ? {
          ...view.active,
          perspectives: [...view.active.perspectives, ...pendingPerspectives],
        }
      : view.active
  return {
    workspace: view.workspace,
    session: active,
    sessionId: active.id,
    stage: finished
      ? "deliberation"
      : activeChanged
        ? active.notepad !== null
          ? "deliberation"
          : "extraction"
        : state.stage,
    pickedQueries: activeChanged || finished ? [] : state.pickedQueries,
    openPaperId: activeChanged || finished ? null : state.openPaperId,
    searchProgress: activeChanged || finished ? [] : state.searchProgress,
    notepadDrafts: activeChanged || finished ? {} : state.notepadDrafts,
  }
}

export const useFocusedStore = create<FocusedState & FocusedActions>()((set) => ({
  ...initialState,
  workspaceViewSet: (view) => set((state) => workspaceViewPatch(state, view)),
  optimisticPerspectiveAdd: (perspective) =>
    set((state) => {
      if (
        !state.session ||
        state.session.perspectives.some(
          (item) => item.anchor_paper_id === perspective.anchor_paper_id,
        )
      ) {
        return {}
      }
      return {
        session: {
          ...state.session,
          perspectives: [...state.session.perspectives, perspective],
        },
      }
    }),
  optimisticPerspectiveRemove: (id) =>
    set((state) => ({
      session: state.session
        ? {
            ...state.session,
            perspectives: state.session.perspectives.filter(
              (perspective) => perspective.id !== id,
            ),
          }
        : null,
    })),
  notepadDraftStaged: (versionId, part, text) =>
    set((state) => ({
      notepadDrafts: {
        ...state.notepadDrafts,
        [notepadDraftKey(versionId, part)]: text,
      },
    })),
  notepadDraftAcknowledged: (versionId, part, text) =>
    set((state) => {
      const key = notepadDraftKey(versionId, part)
      if (state.notepadDrafts[key] !== text) return {}
      const notepadDrafts = { ...state.notepadDrafts }
      delete notepadDrafts[key]
      return { notepadDrafts }
    }),
  stageSet: (stage) => set({ stage }),
  queryToggled: (query) =>
    set((state) => ({
      pickedQueries: state.pickedQueries.includes(query)
        ? state.pickedQueries.filter((item) => item !== query)
        : [...state.pickedQueries, query],
    })),
  queriesCleared: () => set({ pickedQueries: [] }),
  searchProgressAdded: (item) =>
    set((state) => ({
      searchProgress: [...state.searchProgress, item].slice(
        -MAX_SEARCH_PROGRESS_EVENTS,
      ),
    })),
  searchProgressCleared: () => set({ searchProgress: [] }),
  openPaperSet: (openPaperId) => set({ openPaperId }),
  busySet: (busy) => set({ busy }),
  reset: () => set(initialState),
}))
