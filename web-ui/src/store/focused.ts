"use client"

import { create } from "zustand"

import type {
  InvestigationSummary,
  Perspective,
  SessionState,
  WorkspaceState,
  WorkspaceView,
} from "@/types/focused"

type Stage = "extraction" | "deliberation"
type WorkspaceScreen = "detail" | "map"

type FocusedState = {
  workspace: WorkspaceState | null
  investigations: InvestigationSummary[]
  workspaceScreen: WorkspaceScreen
  sessionId: string | null
  session: SessionState | null
  stage: Stage
  pickedQueries: string[]
  openClusterId: string | null
  openPaperId: string | null
  busy: string | null
}

type FocusedActions = {
  workspaceViewSet: (view: WorkspaceView) => void
  optimisticPerspectiveAdd: (perspective: Perspective) => void
  optimisticPerspectiveRemove: (id: string) => void
  workspaceScreenSet: (screen: WorkspaceScreen) => void
  stageSet: (stage: Stage) => void
  queryToggled: (query: string) => void
  queriesCleared: () => void
  openClusterSet: (id: string | null) => void
  openPaperSet: (id: string | null) => void
  busySet: (label: string | null) => void
  reset: () => void
}

const initialState: FocusedState = {
  workspace: null,
  investigations: [],
  workspaceScreen: "detail",
  sessionId: null,
  session: null,
  stage: "extraction",
  pickedQueries: [],
  openClusterId: null,
  openPaperId: null,
  busy: null,
}

export const useFocusedStore = create<FocusedState & FocusedActions>()(
  (set) => ({
    ...initialState,
    workspaceViewSet: (view) =>
      set((state) => {
        const activeChanged = state.sessionId !== view.active.id
        return {
          workspace: view.workspace,
          investigations: view.investigations,
          session: view.active,
          sessionId: view.active.id,
          stage: activeChanged
            ? view.active.deliberations.length > 0
              ? "deliberation"
              : "extraction"
            : state.stage,
          pickedQueries: activeChanged ? [] : state.pickedQueries,
          openClusterId: activeChanged ? null : state.openClusterId,
          openPaperId: activeChanged ? null : state.openPaperId,
        }
      }),
    optimisticPerspectiveAdd: (perspective) =>
      set((state) => {
        if (
          !state.session ||
          state.session.perspectives.some(
            (item) => item.origin === perspective.origin && !item.evolved,
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
    workspaceScreenSet: (workspaceScreen) => set({ workspaceScreen }),
    stageSet: (stage) => set({ stage }),
    queryToggled: (query) =>
      set((state) => ({
        pickedQueries: state.pickedQueries.includes(query)
          ? state.pickedQueries.filter((q) => q !== query)
          : [...state.pickedQueries, query],
      })),
    queriesCleared: () => set({ pickedQueries: [] }),
    openClusterSet: (openClusterId) => set({ openClusterId }),
    openPaperSet: (openPaperId) => set({ openPaperId }),
    busySet: (busy) => set({ busy }),
    reset: () => set(initialState),
  }),
)
