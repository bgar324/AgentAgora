"use client"

import { useMemo, useState } from "react"
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type NodeProps,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import { useFocusedPanel } from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import type {
  HypothesisDev,
  HypothesisVersion,
  InvestigationSummary,
} from "@/types/focused"

import { Button, ModalShell, SectionLabel, Spinner } from "./ui"

const HIDDEN_HANDLE = { opacity: 0, pointerEvents: "none" } as const

const WORKSPACE_NODE_TYPES = {
  investigation: InvestigationNode,
}

function investigationName(
  investigation: InvestigationSummary,
  rootId: string,
): string {
  return investigation.id === rootId
    ? "Initial Investigation"
    : investigation.origin_question ?? "Child Investigation"
}

export function WorkspaceMap() {
  const workspace = useFocusedStore((state) => state.workspace)
  const investigations = useFocusedStore((state) => state.investigations)
  const session = useFocusedStore((state) => state.session)
  const busy = useFocusedStore((state) => state.busy)
  const workspaceScreenSet = useFocusedStore((state) => state.workspaceScreenSet)
  const {
    switchInvestigation,
    promoteHypothesis,
    mergeHypotheses,
    archiveHypothesis,
    restoreHypothesis,
  } = useFocusedPanel()
  const [mergeSource, setMergeSource] = useState<HypothesisVersion | null>(null)
  const [archiveCandidate, setArchiveCandidate] =
    useState<HypothesisVersion | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { nodes, edges } = useMemo(() => {
    if (!workspace) return { nodes: [], edges: [] }
    const byId = new Map(investigations.map((item) => [item.id, item]))
    const depths = new Map<string, number>()
    const depthOf = (item: InvestigationSummary): number => {
      const known = depths.get(item.id)
      if (known !== undefined) return known
      const parent = item.parent_investigation_id
        ? byId.get(item.parent_investigation_id)
        : undefined
      const depth = parent ? depthOf(parent) + 1 : 0
      depths.set(item.id, depth)
      return depth
    }
    const rowsByDepth = new Map<number, number>()
    const graphNodes: RFNode[] = investigations.map((item) => {
      const depth = depthOf(item)
      const row = rowsByDepth.get(depth) ?? 0
      rowsByDepth.set(depth, row + 1)
      const version = workspace.hypothesis_versions.find(
        (candidate) => candidate.id === item.applied_hypothesis_version_id,
      )
      const ownsCheckpoint = version?.investigation_id === item.id
      return {
        id: item.id,
        type: "investigation",
        position: { x: depth * 460, y: row * 190 },
        draggable: false,
        data: {
          investigationId: item.id,
          title: investigationName(item, workspace.root_investigation_id),
          active: item.id === workspace.active_investigation_id,
          searched: item.searched,
          paperCount: item.paper_count,
          perspectiveCount: item.perspective_count,
          roundCount: item.completed_rounds,
          openQuestionCount: item.open_question_count,
          hypothesisId: ownsCheckpoint ? (version?.id ?? null) : null,
          inheritedHypothesisId:
            version && !ownsCheckpoint ? version.id : null,
          promoted:
            ownsCheckpoint &&
            version?.id === workspace.promoted_hypothesis_version_id,
          onOpen: async () => {
            setError(null)
            try {
              await switchInvestigation(item.id)
              workspaceScreenSet("detail")
            } catch (cause) {
              setError(
                cause instanceof Error
                  ? cause.message
                  : "Could not open Investigation",
              )
            }
          },
        },
      }
    })
    const graphEdges: RFEdge[] = investigations
      .filter((item) => item.parent_investigation_id)
      .map((item) => ({
        id: `edge-${item.id}`,
        source: item.parent_investigation_id!,
        target: item.id,
        label: item.origin_question
          ? `${item.origin_question.slice(0, 30)}${item.origin_question.length > 30 ? "…" : ""}`
          : "Open question",
        type: "smoothstep",
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "var(--wire)",
          width: 12,
          height: 12,
        },
        style: { stroke: "var(--wire)", strokeWidth: 1.2 },
        labelStyle: {
          fill: "var(--ink-2)",
          fontSize: 9,
          fontWeight: 500,
        },
        labelBgStyle: { fill: "var(--panel)", fillOpacity: 0.94 },
        labelBgPadding: [6, 4] as [number, number],
        labelBgBorderRadius: 4,
      }))
    return { nodes: graphNodes, edges: graphEdges }
  }, [investigations, switchInvestigation, workspace, workspaceScreenSet])

  if (!workspace || !session) return null
  const currentVersion = workspace.hypothesis_versions.find(
    (version) => version.id === session.applied_hypothesis_version_id,
  )
  const visibleVersions = workspace.hypothesis_versions.filter(
    (version) => !version.archived,
  )
  const archivedVersions = workspace.hypothesis_versions.filter(
    (version) => version.archived,
  )

  const run = async (operation: () => Promise<unknown>): Promise<boolean> => {
    setError(null)
    try {
      await operation()
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request failed")
      return false
    }
  }

  return (
    <main className="grid min-h-[calc(100vh-49px)] grid-cols-1 bg-[var(--bg)] xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="relative min-h-[620px] border-b border-[var(--line)] xl:border-b-0 xl:border-r">
        <div className="pointer-events-none absolute left-5 top-5 z-10 max-w-[420px] rounded-xl border border-[var(--line)] bg-[var(--panel)]/95 px-4 py-3 shadow-sm backdrop-blur-sm">
          <SectionLabel>Investigation map</SectionLabel>
          <h1 className="mt-1 text-[17px] font-semibold tracking-[-0.02em]">
            Follow questions without flattening the research
          </h1>
          <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--mute)]">
            Each node keeps its own literature, Perspectives, panel rounds, and
            hypothesis checkpoint. Selecting a node opens that Investigation.
          </p>
        </div>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={WORKSPACE_NODE_TYPES}
          fitView
          fitViewOptions={{ padding: 0.28, maxZoom: 1 }}
          minZoom={0.35}
          maxZoom={1.35}
          nodesDraggable={false}
          proOptions={{ hideAttribution: true }}
          aria-label="Investigation lineage"
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={22}
            size={1}
            color="rgba(16,24,40,0.07)"
          />
        </ReactFlow>
      </section>

      <aside className="bg-[var(--panel)] px-4 py-5" aria-label="Hypothesis lineage">
        <div className="flex items-start justify-between gap-3">
          <div>
            <SectionLabel>Hypothesis lineage</SectionLabel>
            <h2 className="mt-1 text-[15px] font-semibold tracking-[-0.01em]">
              {visibleVersions.length
                ? `${visibleVersions.length} saved checkpoint${visibleVersions.length === 1 ? "" : "s"}`
                : "No applied checkpoint yet"}
            </h2>
          </div>
          {busy && <Spinner />}
        </div>
        <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--mute)]">
          Promotion chooses the workspace direction. Alternatives remain
          traceable and can be merged step by step.
        </p>

        <div className="mt-4 flex flex-col gap-2">
          {visibleVersions.map((version) => {
            const investigation = investigations.find(
              (item) => item.id === version.investigation_id,
            )
            const promoted =
              workspace.promoted_hypothesis_version_id === version.id
            const branchCurrent =
              investigation?.applied_hypothesis_version_id === version.id
            return (
              <article
                key={version.id}
                className="rounded-xl border border-[var(--line)] bg-[var(--bg)] p-3"
                data-testid={`hypothesis-version-${version.id}`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-semibold">{version.id}</span>
                  {promoted && (
                    <span className="text-[9.5px] font-medium text-[var(--green)]">
                      Promoted
                    </span>
                  )}
                  {branchCurrent && !promoted && (
                    <span className="text-[9.5px] font-medium text-[var(--ink-2)]">
                      Branch checkpoint
                    </span>
                  )}
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-[var(--ink-2)]">
                  {version.steps.hypothesis}
                </p>
                <p className="mt-1 text-[9.5px] text-[var(--mute)]">
                  {investigation
                    ? investigationName(investigation, workspace.root_investigation_id)
                    : "Investigation"}
                  {version.parent_ids.length
                    ? ` · from ${version.parent_ids.join(" + ")}`
                    : " · branch origin"}
                </p>
                <p className="mt-1 text-[9px] leading-relaxed text-[var(--mute)]">
                  Content source{" "}
                  {version.step_sources.hypothesis ?? version.id}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {branchCurrent && !promoted && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!!busy}
                      onClick={() => void run(() => promoteHypothesis(version.id))}
                    >
                      Promote
                    </Button>
                  )}
                  {currentVersion && currentVersion.id !== version.id && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!!busy}
                      onClick={() => setMergeSource(version)}
                    >
                      Compare and merge
                    </Button>
                  )}
                  {!branchCurrent && !promoted && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!!busy}
                      onClick={() => setArchiveCandidate(version)}
                    >
                      Archive
                    </Button>
                  )}
                </div>
              </article>
            )
          })}
          {!visibleVersions.length && (
            <div className="rounded-xl border border-dashed border-[var(--line-strong)] px-3 py-4 text-[11px] leading-relaxed text-[var(--mute)]">
              Apply a panel-supported hypothesis to create the first immutable
              checkpoint.
            </div>
          )}
        </div>
        {archivedVersions.length > 0 && (
          <div className="mt-4 border-t border-[var(--line)] pt-3">
            <SectionLabel>Archived hypotheses</SectionLabel>
            <div className="mt-2 flex flex-col gap-1.5">
              {archivedVersions.map((version) => (
                <div
                  key={version.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-[var(--line)] px-2.5 py-2"
                >
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold">{version.id}</div>
                    <p className="truncate text-[9.5px] text-[var(--mute)]">
                      {version.steps.hypothesis}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!!busy}
                    onClick={() => void run(() => restoreHypothesis(version.id))}
                  >
                    Restore
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
        {error && (
          <p role="alert" className="mt-3 text-[11px] text-[var(--red)]">
            {error}
          </p>
        )}
      </aside>

      {mergeSource && currentVersion && (
        <MergeModal
          source={mergeSource}
          target={currentVersion}
          busy={busy === "Merging hypotheses"}
          onClose={() => setMergeSource(null)}
          onMerge={async (hypothesis) => {
            const merged = await run(() =>
              mergeHypotheses(session.id, mergeSource.id, hypothesis),
            )
            if (merged) setMergeSource(null)
          }}
        />
      )}
      {archiveCandidate && (
        <ModalShell
          title={`Archive ${archiveCandidate.id}?`}
          onClose={() => setArchiveCandidate(null)}
        >
          <p className="text-[12px] leading-relaxed text-[var(--ink-2)]">
            This removes the checkpoint from the active lineage. Its content and
            provenance stay saved, and it can be restored later.
          </p>
          <div className="mt-4 flex justify-end gap-2 border-t border-[var(--line)] pt-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setArchiveCandidate(null)}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={busy === "Archiving hypothesis"}
              onClick={() => {
                void run(() => archiveHypothesis(archiveCandidate.id)).then(
                  (archived) => {
                    if (archived) setArchiveCandidate(null)
                  },
                )
              }}
            >
              Archive hypothesis
            </Button>
          </div>
        </ModalShell>
      )}
    </main>
  )
}

function InvestigationNode({ data }: NodeProps) {
  const node = data as {
    investigationId: string
    title: string
    active: boolean
    searched: boolean
    paperCount: number
    perspectiveCount: number
    roundCount: number
    openQuestionCount: number
    hypothesisId: string | null
    inheritedHypothesisId: string | null
    promoted: boolean
    onOpen: () => void
  }
  return (
    <button
      type="button"
      data-testid={`investigation-node-${node.investigationId}`}
      onClick={node.onOpen}
      className="nodrag w-[280px] rounded-xl border bg-[var(--panel)] p-4 text-left shadow-sm transition-colors hover:border-[var(--ink-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--node)]"
      style={{
        borderColor: node.active ? "var(--node)" : "var(--line-strong)",
      }}
      aria-current={node.active ? "page" : undefined}
    >
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <div className="flex items-center justify-between gap-3">
        <span className="text-[9.5px] font-medium text-[var(--mute)]">
          {node.active ? "Open now" : node.searched ? "In progress" : "Ready to search"}
        </span>
        {node.promoted ? (
          <span className="text-[9.5px] font-medium text-[var(--green)]">
            Promoted branch
          </span>
        ) : node.inheritedHypothesisId ? (
          <span className="text-[9.5px] font-medium text-[var(--ink-2)]">
            Inherits {node.inheritedHypothesisId}
          </span>
        ) : node.hypothesisId ? (
          <span className="text-[9.5px] font-medium text-[var(--ink-2)]">
            {node.hypothesisId}
          </span>
        ) : null}
      </div>
      <div className="mt-2 line-clamp-3 text-[13px] font-semibold leading-snug tracking-[-0.01em]">
        {node.title}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-[var(--line)] pt-2 text-[9.5px] text-[var(--mute)]">
        <span>{node.paperCount} papers</span>
        <span>{node.perspectiveCount} Perspectives</span>
        <span>{node.roundCount} rounds</span>
        <span>{node.openQuestionCount} open</span>
      </div>
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} />
    </button>
  )
}

function MergeModal({
  source,
  target,
  busy,
  onClose,
  onMerge,
}: {
  source: HypothesisVersion
  target: HypothesisVersion
  busy: boolean
  onClose: () => void
  onMerge: (hypothesis: HypothesisDev) => Promise<void>
}) {
  const [hypothesis, setHypothesis] = useState(target.steps.hypothesis)
  return (
    <ModalShell title={`Compare ${source.id} with ${target.id}`} onClose={onClose}>
      <p className="mb-4 text-[11.5px] leading-relaxed text-[var(--ink-2)]">
        Review both candidates and write the combined hypothesis to save on the
        current branch.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-[var(--line)] p-3">
          <SectionLabel>{target.id}</SectionLabel>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--mute)]">
            {target.steps.hypothesis}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--line)] p-3">
          <SectionLabel>{source.id}</SectionLabel>
          <p className="mt-1 text-[11px] leading-relaxed text-[var(--ink-2)]">
            {source.steps.hypothesis}
          </p>
        </div>
      </div>
      <label className="mt-4 block">
        <SectionLabel>Combined hypothesis</SectionLabel>
        <textarea
          rows={5}
          value={hypothesis}
          onChange={(event) => setHypothesis(event.target.value)}
          disabled={busy}
          className="field mt-1 w-full resize-y px-3 py-2 text-[12px] leading-relaxed"
        />
      </label>
      <div className="mt-4 flex justify-end gap-2 border-t border-[var(--line)] pt-3">
        <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || !hypothesis.trim()}
          onClick={() =>
            void onMerge({ hypothesis: hypothesis.trim() })
          }
        >
          {busy ? <><Spinner /> Merging…</> : "Save merged hypothesis"}
        </Button>
      </div>
    </ModalShell>
  )
}
