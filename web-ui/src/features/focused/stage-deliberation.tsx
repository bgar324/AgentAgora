"use client"

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react"
import Markdown from "react-markdown"
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type NodeProps,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import { useFocusedPanel } from "@/hooks/use-focused"
import { useFocusedStore } from "@/store/focused"
import {
  FACETS,
  type AgentState,
  type ClusterCard,
  type DeliberationPoint,
  type DeliberationCompletion,
  type DeliberationRound,
  type DeliberationState,
  type Facet,
  type FacetVerdict,
  type HypothesisDev,
  type HypothesisVersion,
  type QuestionStatus,
  type Perspective,
  type Turn,
} from "@/types/focused"

import {
  Button,
  EmptyLine,
  IdentityChip,
  ModalShell,
  SectionLabel,
  Spinner,
  useDialogSurface,
} from "./ui"





const FACET_META: Record<
  Facet,
  { label: string; short: string; color: string; tint: string }
> = {
  scope: {
    label: "Scope",
    short: "Who, where, and under what conditions",
    color: "#3468a3",
    tint: "#eef5fc",
  },
  explanation: {
    label: "Explanation",
    short: "How the phenomenon is understood",
    color: "#287667",
    tint: "#edf8f5",
  },
  approach: {
    label: "Approach",
    short: "How the claim can be established",
    color: "#a96613",
    tint: "#fff6e8",
  },
  significance: {
    label: "Significance",
    short: "Why the result is consequential",
    color: "#a64d70",
    tint: "#fff0f5",
  },
}

const VERDICT_META: Record<
  FacetVerdict["status"],
  { label: string; color: string }
> = {
  consensus: { label: "Consensus", color: "var(--green)" },
  disagreement: { label: "Disagreement", color: "var(--red)" },
  unsettled: { label: "Unsettled", color: "var(--amber)" },
}

export function StageDeliberation() {
  const session = useFocusedStore((state) => state.session)
  const workspace = useFocusedStore((state) => state.workspace)
  const busy = useFocusedStore((state) => state.busy)
  const {
    createChildInvestigation,
    generatePerspective,
    switchInvestigation,
  } = useFocusedPanel()
  const [agentModal, setAgentModal] = useState<AgentState | null>(null)
  const [savedHypothesisModal, setSavedHypothesisModal] =
    useState<HypothesisVersion | null>(null)
  const [scoringId, setScoringId] = useState<string | null>(null)
  const [addPerspectiveOpen, setAddPerspectiveOpen] = useState(false)
  const [addingPerspective, setAddingPerspective] = useState(false)
  const [canvasError, setCanvasError] = useState<string | null>(null)
  const [drawerId, setDrawerId] = useState<string | null>(null)
  const [archiveIndex, setArchiveIndex] = useState<number | null>(null)
  const availableClusters = useMemo(() => {
    if (!session) return []
    const represented = new Set(
      session.perspectives.map((perspective) => perspective.origin),
    )
    return session.clusters.filter((cluster) => !represented.has(cluster.id))
  }, [session])

  const nodes = useMemo<RFNode[]>(() => {
    if (!session) return []
    const result: RFNode[] = [
      {
        id: "problem",
        type: "epProblem",
        position: { x: 0, y: 0 },
        draggable: false,
        data: { problem: session.origin_question ?? session.problem },
      },
    ]
    const deliberation = session.deliberations[0]
    if (!deliberation) return result

    const history = deliberation.completion_history
    const allQuestions = [
      ...history.flatMap((completion) => completion.recommended_questions),
      ...deliberation.recommended_questions,
    ]
    const panelX = (cycle: number) => 720 + cycle * 1060
    const artifactX = (cycle: number) => panelX(cycle) + 360
    const branchAgentX = (cycle: number) => panelX(cycle) + 700
    const historyPanelId = (cycle: number) =>
      `panel-${deliberation.id}-completion-${cycle + 1}`
    const currentPanelId = `panel-${deliberation.id}`
    const perspectiveForAgent = (agent: AgentState) =>
      session.perspectives.find((item) => item.id === agent.perspective_id)
    const membersFor = (agentIids: number[]) =>
      agentIids.map((iid) => {
        const agent = session.agents.find((item) => item.iid === iid)
        const perspective = agent ? perspectiveForAgent(agent) : undefined
        return {
          id: iid,
          name: perspective?.name ?? agent?.label ?? "Perspective",
          color: perspective?.color ?? "var(--mute)",
        }
      })

    const completionAgentIids = (
      completion: DeliberationState["completion_history"][number],
    ) =>
      completion.agent_iids.length
        ? completion.agent_iids
        : (completion.rounds.at(-1)?.participant_iids ?? [])
    const questionIdsForCompletion = (
      completion: DeliberationState["completion_history"][number],
    ) =>
      Array.from(
        new Set([
          ...completion.selected_question_ids,
          ...completion.recommended_questions
            .filter((question) => question.child_investigation_id !== null)
            .map((question) => question.id),
        ]),
      )
    const questionCycle = new Map<string, number>()
    history.forEach((completion, cycle) => {
      questionIdsForCompletion(completion).forEach((questionId) => {
        questionCycle.set(questionId, cycle)
      })
    })
    const targetCycleForAgent = (agent: AgentState) => {
      const perspective = perspectiveForAgent(agent)
      if (perspective && perspective.panel_cycle > 0) {
        return Math.min(perspective.panel_cycle, history.length)
      }
      const sourceQuestionId = perspective?.source_question_id
      const sourceCycle = sourceQuestionId
        ? questionCycle.get(sourceQuestionId)
        : undefined
      if (sourceCycle !== undefined) return sourceCycle + 1
      const completedCycle = history.findIndex((completion) =>
        completionAgentIids(completion).includes(agent.iid),
      )
      return completedCycle >= 0 ? completedCycle : history.length
    }
    const agentGroups = new Map<number, AgentState[]>()
    for (const agent of session.agents) {
      const targetCycle = targetCycleForAgent(agent)
      agentGroups.set(targetCycle, [
        ...(agentGroups.get(targetCycle) ?? []),
        agent,
      ])
    }
    for (const [targetCycle, agents] of agentGroups) {
      const x = targetCycle === 0 ? 330 : branchAgentX(targetCycle - 1)
      agents.forEach((agent, index) => {
        const perspective = perspectiveForAgent(agent)
        result.push({
          id: `agent-${agent.iid}`,
          type: "epAgent",
          position: {
            x,
            y: index * 175 - Math.max(0, agents.length - 1) * 87.5,
          },
          data: {
            agentId: agent.iid,
            name: perspective?.name ?? agent.label,
            color: perspective?.color ?? "var(--mute)",
            meta: `${perspective?.sources.length ?? 0} source${perspective?.sources.length === 1 ? "" : "s"}`,
            onOpen: () => setAgentModal(agent),
          },
        })
      })
    }

    const renderedVersionIds = new Set<string>()
    const addArtifacts = (
      cycle: number,
      versionId: string | null,
      questionIds: string[],
    ) => {
      const version =
        versionId !== null && !renderedVersionIds.has(versionId)
          ? workspace?.hypothesis_versions.find((item) => item.id === versionId)
          : undefined
      if (version) renderedVersionIds.add(version.id)
      const questions = allQuestions.filter((question) =>
        questionIds.includes(question.id),
      )
      const artifacts = [
        ...(version ? [{ kind: "hypothesis" as const, version }] : []),
        ...questions.map((question) => ({
          kind: "research" as const,
          question,
        })),
      ]
      artifacts.forEach((artifact, index) => {
        const y = (index - (artifacts.length - 1) / 2) * 165
        if (artifact.kind === "hypothesis") {
          result.push({
            id: `hypothesis-${artifact.version.id}`,
            type: "epHypothesis",
            position: { x: artifactX(cycle), y },
            data: {
              versionId: artifact.version.id,
              hypothesis:
                [
                  artifact.version.steps.hypothesis,
                  artifact.version.steps.reasoning,
                  artifact.version.steps.problem,
                  artifact.version.steps.previous_work,
                ].find((part) => part !== "Not established yet.") ??
                artifact.version.steps.hypothesis,
              promoted:
                workspace?.promoted_hypothesis_version_id === artifact.version.id,
              onOpen: () => setSavedHypothesisModal(artifact.version),
            },
          })
          return
        }
        const question = artifact.question
        const actionable =
          question.status === "open" || question.child_investigation_id !== null
        result.push({
          id: `research-${question.id}`,
          type: "epResearchProblem",
          position: { x: artifactX(cycle), y },
          data: {
            questionId: question.id,
            question: question.question,
            status: question.status,
            hasChild: question.child_investigation_id !== null,
            actionable,
            busy: busy !== null,
            onOpen: async () => {
              if (busy || !actionable) return
              setCanvasError(null)
              try {
                if (question.child_investigation_id) {
                  await switchInvestigation(question.child_investigation_id)
                } else {
                  await createChildInvestigation(question.id)
                }
              } catch (cause) {
                setCanvasError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not open this research problem",
                )
              }
            },
          },
        })
      })
    }

    history.forEach((completion, cycle) => {
      const fallbackAgentIids =
        completion.rounds.at(-1)?.participant_iids ?? []
      result.push({
        id: historyPanelId(cycle),
        type: "epPanel",
        position: { x: panelX(cycle), y: 0 },
        data: {
          members: membersFor(
            completion.agent_iids.length
              ? completion.agent_iids
              : fallbackAgentIids,
          ),
          status: `${
            completion.reason === "restarted" ? "Restarted" : "Ended"
          } after ${completion.round_count} ${
            completion.round_count === 1 ? "round" : "rounds"
          }`,
          canJoin: true,
          ended: true,
          onJoin: () => setArchiveIndex(cycle),
        },
      })
      addArtifacts(
        cycle,
        completion.final_hypothesis_version_id,
        questionIdsForCompletion(completion),
      )
    })

    const completedRounds = deliberation.rounds.filter((round) => round.completed)
    const ended = deliberation.completed_at !== null
    const currentCycle = history.length
    result.push({
      id: currentPanelId,
      type: "epPanel",
      position: { x: panelX(currentCycle), y: 0 },
      data: {
        members: membersFor(deliberation.agent_iids),
        status: ended
          ? `Ended after ${completedRounds.length} ${
              completedRounds.length === 1 ? "round" : "rounds"
            }`
          : completedRounds.length
            ? `${completedRounds.length} completed ${
                completedRounds.length === 1 ? "round" : "rounds"
              }`
            : deliberation.agent_iids.length >= 2
              ? "Ready for a focused round"
              : "Needs two Perspectives",
        canJoin: deliberation.agent_iids.length >= 2,
        ended,
        onJoin: () => setDrawerId(deliberation.id),
      },
    })
    if (ended && completedRounds.length > 0) {
      addArtifacts(
        currentCycle,
        deliberation.final_hypothesis_version_id,
        Array.from(
          new Set([
            ...deliberation.selected_question_ids,
            ...deliberation.recommended_questions
              .filter((question) => question.child_investigation_id !== null)
              .map((question) => question.id),
          ]),
        ),
      )
    }
    return result
  }, [
    busy,
    createChildInvestigation,
    session,
    switchInvestigation,
    workspace,
  ])

  const edges = useMemo<RFEdge[]>(() => {
    if (!session) return []
    const deliberation = session.deliberations[0]
    if (!deliberation) return []
    const style = { stroke: "var(--wire)", strokeWidth: 1.25 }
    const markerEnd = {
      type: MarkerType.ArrowClosed,
      color: "var(--wire)",
      width: 12,
      height: 12,
    }
    const result: RFEdge[] = []
    const history = deliberation.completion_history
    const historyPanelId = (cycle: number) =>
      `panel-${deliberation.id}-completion-${cycle + 1}`
    const currentPanelId = `panel-${deliberation.id}`
    const panelForCycle = (cycle: number) =>
      cycle < history.length ? historyPanelId(cycle) : currentPanelId
    const questionIdsForCompletion = (
      completion: DeliberationState["completion_history"][number],
    ) =>
      Array.from(
        new Set([
          ...completion.selected_question_ids,
          ...completion.recommended_questions
            .filter((question) => question.child_investigation_id !== null)
            .map((question) => question.id),
        ]),
      )
    const questionCycle = new Map<string, number>()
    history.forEach((completion, cycle) => {
      questionIdsForCompletion(completion).forEach((questionId) => {
        questionCycle.set(questionId, cycle)
      })
    })

    const completionAgentIids = (
      completion: DeliberationState["completion_history"][number],
    ) =>
      completion.agent_iids.length
        ? completion.agent_iids
        : (completion.rounds.at(-1)?.participant_iids ?? [])
    for (const agent of session.agents) {
      const perspective = session.perspectives.find(
        (item) => item.id === agent.perspective_id,
      )
      const sourceQuestionId = perspective?.source_question_id
      const sourceCycle = sourceQuestionId
        ? questionCycle.get(sourceQuestionId)
        : undefined
      const completedCycle = history.findIndex((completion) =>
        completionAgentIids(completion).includes(agent.iid),
      )
      const declaredCycle =
        perspective && perspective.panel_cycle > 0
          ? Math.min(perspective.panel_cycle, history.length)
          : undefined
      const targetCycle =
        declaredCycle ??
        (sourceCycle !== undefined
          ? sourceCycle + 1
          : completedCycle >= 0
            ? completedCycle
            : history.length)
      if (sourceQuestionId && sourceCycle !== undefined) {
        result.push({
          id: `e-question-${sourceQuestionId}-agent-${agent.iid}`,
          source: `research-${sourceQuestionId}`,
          target: `agent-${agent.iid}`,
          style,
          markerEnd,
        })
      } else if (targetCycle === 0) {
        result.push({
          id: `e-problem-${agent.iid}`,
          source: "problem",
          target: `agent-${agent.iid}`,
          style,
          markerEnd,
        })
      } else {
        result.push({
          id: `e-panel-${targetCycle}-agent-${agent.iid}`,
          source: historyPanelId(targetCycle - 1),
          target: `agent-${agent.iid}`,
          style,
          markerEnd,
        })
      }
      result.push({
        id: `e-agent-${agent.iid}-panel-${targetCycle}`,
        source: `agent-${agent.iid}`,
        target: panelForCycle(targetCycle),
        style,
        markerEnd,
      })
    }

    const renderedVersionIds = new Set<string>()
    const addArtifactEdges = (
      cycle: number,
      versionId: string | null,
      questionIds: string[],
    ) => {
      const panelId = panelForCycle(cycle)
      if (versionId && !renderedVersionIds.has(versionId)) {
        renderedVersionIds.add(versionId)
        result.push({
          id: `e-hypothesis-${versionId}`,
          source: panelId,
          target: `hypothesis-${versionId}`,
          style,
          markerEnd,
        })
      }
      questionIds.forEach((questionId) => {
        result.push({
          id: `e-research-${questionId}`,
          source: panelId,
          target: `research-${questionId}`,
          style,
          markerEnd,
        })
      })
    }
    history.forEach((completion, cycle) => {
      addArtifactEdges(
        cycle,
        completion.final_hypothesis_version_id,
        questionIdsForCompletion(completion),
      )
    })
    if (deliberation.completed_at !== null) {
      const historicalQuestionIds = new Set(
        history.flatMap((completion) =>
          questionIdsForCompletion(completion),
        ),
      )
      const currentQuestionIds = Array.from(
        new Set([
          ...deliberation.selected_question_ids,
          ...deliberation.recommended_questions
            .filter((question) => question.child_investigation_id !== null)
            .map((question) => question.id),
        ]),
      ).filter((questionId) => !historicalQuestionIds.has(questionId))
      addArtifactEdges(
        history.length,
        deliberation.final_hypothesis_version_id,
        currentQuestionIds,
      )
    }
    return result
  }, [session])

  if (!session) return null

  return (
    <div className="ep-fade-in relative h-[calc(100vh-49px)]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.35}
        nodesDraggable={false}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={22}
          size={1}
          color="rgba(16,24,40,0.07)"
        />
        <RefitOnNodes count={nodes.length} />
        {availableClusters.length > 0 && (
          <Panel position="top-left" className="!m-3">
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null || addingPerspective}
              onClick={() => setAddPerspectiveOpen(true)}
            >
              Add Perspective
            </Button>
          </Panel>
        )}
        {canvasError && (
          <Panel position="bottom-left" className="!m-3">
            <p role="alert" className="text-[11px] text-[var(--red)]">
              {canvasError}
            </p>
          </Panel>
        )}
      </ReactFlow>

      {archiveIndex !== null &&
        session.deliberations[0]?.completion_history[archiveIndex] && (
          <ArchivedPanelDialog
            completion={
              session.deliberations[0].completion_history[archiveIndex]
            }
            onClose={() => setArchiveIndex(null)}
            onOpenAgent={setAgentModal}
          />
        )}
      {drawerId && (
        <PanelDrawer
          deliberationId={drawerId}
          onClose={() => setDrawerId(null)}
          onOpenAgent={setAgentModal}
          onEnded={() => setScoringId(drawerId)}
          onRate={() => setScoringId(drawerId)}
        />
      )}
      {addPerspectiveOpen && (
        <AddPerspectiveDialog
          clusters={availableClusters}
          perspectives={session.perspectives.filter(
            (perspective) =>
              !perspective.evolved &&
              !perspective.id.startsWith("optimistic:"),
          )}
          busy={busy !== null || addingPerspective}
          adding={addingPerspective}
          onAdd={async (clusterId, invitedPerspectiveIds) => {
            setAddingPerspective(true)
            try {
              await generatePerspective(
                clusterId,
                null,
                invitedPerspectiveIds,
              )
              setAddPerspectiveOpen(false)
            } finally {
              setAddingPerspective(false)
            }
          }}
          onClose={() => setAddPerspectiveOpen(false)}
        />
      )}
      <AgentModal agent={agentModal} onClose={() => setAgentModal(null)} />
      <SavedHypothesisModal
        version={savedHypothesisModal}


        onClose={() => setSavedHypothesisModal(null)}
      />
      {scoringId && (
        <DeliberationScoringDialog
          deliberationId={scoringId}
          onClose={() => setScoringId(null)}
        />
      )}
    </div>
  )
}
function ArchivedPanelDialog({
  completion,
  onClose,
  onOpenAgent,
}: {
  completion: DeliberationCompletion
  onClose: () => void
  onOpenAgent: (agent: AgentState) => void
}) {
  const session = useFocusedStore((state) => state.session)
  if (!session) return null
  const agents = completion.agent_iids
    .map((iid) => session.agents.find((agent) => agent.iid === iid))
    .filter((agent): agent is AgentState => agent !== undefined)
  const hypothesis = completion.applied_hypothesis ?? completion.hypothesis

  return (
    <ModalShell title="Panel history" onClose={onClose} wide>
      <p className="mb-3 text-[12px] text-[var(--ink-2)]">
        {completion.reason === "restarted"
          ? "This panel was archived when a new panel cycle started."
          : "This panel ended with a saved hypothesis."}
      </p>
      <div className="mb-4 flex flex-wrap gap-1.5">
        {agents.map((agent) => {
          const perspective = session.perspectives.find(
            (item) => item.id === agent.perspective_id,
          )
          return (
            <IdentityChip
              key={agent.iid}
              color={perspective?.color ?? "var(--ink-2)"}
              name={perspective?.name ?? agent.label}
              onClick={() => onOpenAgent(agent)}
            />
          )
        })}
      </div>
      <div className="flex flex-col gap-4">
        {completion.rounds.map((round) => (
          <section key={round.n} aria-label={`Archived round ${round.n}`}>
            <RoundRecord round={round} />
          </section>
        ))}
      </div>
      {hypothesis && (
        <section className="mt-4 rounded-lg border border-[var(--line)] p-3">
          <SectionLabel>Last working hypothesis</SectionLabel>
          <dl className="mt-2 grid gap-2">
            {(
              [
                ["Problem", hypothesis.problem],
                ["Previous work", hypothesis.previous_work],
                ["Reasoning", hypothesis.reasoning],
                ["Hypothesis", hypothesis.hypothesis],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt className="text-[10.5px] font-medium text-[var(--mute)]">
                  {label}
                </dt>
                <dd className="text-[12px] leading-relaxed text-[var(--ink-2)]">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      {completion.recommended_questions.length > 0 && (
        <section className="mt-4 rounded-lg border border-[var(--line)] p-3">
          <SectionLabel>Research Problems</SectionLabel>
          <ul className="mt-2 flex flex-col gap-1.5">
            {completion.recommended_questions.map((question) => (
              <li
                key={question.id}
                className="text-[12px] leading-relaxed text-[var(--ink-2)]"
              >
                {question.question}
              </li>
            ))}
          </ul>
        </section>
      )}
    </ModalShell>
  )
}

function PanelDrawer({
  deliberationId,
  onClose,
  onOpenAgent,
  onEnded,
  onRate,
}: {
  deliberationId: string
  onClose: () => void
  onOpenAgent: (agent: AgentState) => void
  onEnded: () => void
  onRate: () => void
}) {
  const session = useFocusedStore((state) => state.session)
  const busy = useFocusedStore((state) => state.busy)
  const operationProgress = useFocusedStore((state) => state.searchProgress)
  const {
    initializeDeliberation,
    createChildInvestigation,
    runRound,
    completeDeliberation,
    confirmHypothesis,
    saveHypothesis,
    switchInvestigation,
    updateQuestionStatus,
    sendChat,
  } = useFocusedPanel()
  const [selectedFacets, setSelectedFacets] = useState<Facet[]>([])
  const [message, setMessage] = useState("")
  const [leadSelection, setLeadSelection] = useState("")
  const [target, setTarget] = useState<number | null>(null)
  const [pendingChat, setPendingChat] = useState<{
    text: string
    status: "queued" | "thinking"
    targetIid: number | null
    targetLabel: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const drawerTitleId = useId()
  const drawerRef = useDialogSurface<HTMLElement>(onClose)
  const latestChatRef = useRef<HTMLDivElement>(null)
  const chatInputRef = useRef<HTMLInputElement>(null)
  const flushingQueuedChatRef = useRef(false)
  const [hypothesisDraft, setHypothesisDraft] = useState<HypothesisDev | null>(
    () => {
      const current = useFocusedStore
        .getState()
        .session?.deliberations.find((item) => item.id === deliberationId)
      return current?.hypothesis ? { ...current.hypothesis } : null
    },
  )
  const runningRound = busy === "Running focused round"

  const active = session?.deliberations.find((item) => item.id === deliberationId)

  useEffect(() => {
    if (!session || !active) onClose()
  }, [session, active, onClose])
  useEffect(() => {
    if (active?.chat.length || pendingChat) {
      latestChatRef.current?.scrollIntoView({ block: "start" })
    }
  }, [active?.chat.length, pendingChat])
  useEffect(() => {
    if (
      runningRound ||
      pendingChat?.status !== "queued" ||
      active === undefined ||
      flushingQueuedChatRef.current
    ) {
      return
    }
    const queued = pendingChat
    flushingQueuedChatRef.current = true
    void sendChat(active.id, queued.text, queued.targetIid)
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "Request failed"),
      )
      .finally(() => {
        flushingQueuedChatRef.current = false
        setPendingChat(null)
      })
  }, [active, pendingChat, runningRound, sendChat])



  if (!session || !active) return null
  const agents = active.agent_iids
    .map((iid) => session.agents.find((item) => item.iid === iid))
    .filter((item): item is AgentState => item !== undefined)
  const leadAgent = agents.find(
    (agent) => agent.perspective_id === active.lead_perspective_id,
  )
  const openerIid = leadAgent?.iid ?? null

  const perspectiveOf = (agent: AgentState): Perspective | undefined =>
    session.perspectives.find((item) => item.id === agent.perspective_id)

  const act = async <Result,>(
    operation: () => Promise<Result>,
  ): Promise<Result | undefined> => {
    setError(null)
    try {
      return await operation()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request failed")
    }
  }

  const toggleFacet = (facet: Facet) => {
    setSelectedFacets((current) => {
      if (current.includes(facet)) {
        return current.filter((item) => item !== facet)
      }
      return current.length < 1 ? [...current, facet] : current
    })
  }

  const startRound = () => {
    if (openerIid == null || selectedFacets.length !== 1) return
    void act(async () => {
      const state = await runRound(active.id, openerIid, selectedFacets)
      const updated = state.deliberations.find((item) => item.id === active.id)
      setHypothesisDraft(
        updated?.hypothesis ? { ...updated.hypothesis } : null,
      )
      setSelectedFacets([])
      return state
    })
  }

  const initializePanel = () => {
    const leadPerspectiveId =
      leadSelection || active.lead_perspective_id || agents[0]?.perspective_id
    if (!leadPerspectiveId) return
    void act(async () => {
      const state = await initializeDeliberation(active.id, leadPerspectiveId)
      const updated = state.deliberations.find((item) => item.id === active.id)
      setHypothesisDraft(
        updated?.hypothesis ? { ...updated.hypothesis } : null,
      )
      return state
    })
  }

  const confirmDraft = async (
    draft: HypothesisDev,
    selectedParts?: (keyof HypothesisDev)[],
  ): Promise<boolean> => {
    if (Object.values(draft).some((part) => !part.trim())) {
      setError("Complete all four hypothesis fields.")
      return false
    }
    const mode = active.hypothesis_confirmed
      ? "edit_applied"
      : "apply_pending"
    const state = await act(() =>
      confirmHypothesis(active.id, draft, mode, selectedParts),
    )
    if (!state) return false
    const updated = state.deliberations.find((item) => item.id === active.id)
    setHypothesisDraft(
      updated?.applied_hypothesis
        ? { ...updated.applied_hypothesis }
        : null,
    )
    return true
  }
  const rejectDraft = async (): Promise<boolean> => {
    if (!active.applied_hypothesis) return false
    const rejected =
      (await act(() =>
        confirmHypothesis(
          active.id,
          active.applied_hypothesis!,
          "reject_pending",
        ),
      )) !== undefined
    if (rejected) setHypothesisDraft({ ...active.applied_hypothesis })
    return rejected
  }
  const saveDraft = async (): Promise<boolean> =>
    (await act(() => saveHypothesis(active.id))) !== undefined

  const endDeliberation = async (
    selectedQuestionIds: string[],
  ): Promise<boolean> => {
    const ended =
      (await act(() =>
        completeDeliberation(active.id, selectedQuestionIds),
      )) !== undefined
    if (ended) onEnded()
    return ended
  }



  const send = () => {
    const text = message.trim()
    if (!text) return
    const targetAgent = agents.find((agent) => agent.iid === target)
    const status = runningRound ? "queued" : "thinking"
    setPendingChat({
      text,
      status,
      targetIid: target,
      targetLabel: targetAgent
        ? (perspectiveOf(targetAgent)?.name ?? targetAgent.label)
        : "Panel",
    })
    setMessage("")
    if (status === "queued") return
    void act(() => sendChat(active.id, text, target)).finally(() =>
      setPendingChat(null),
    )
  }

  const discussedFacetCount = FACETS.filter((facet) =>
    active.rounds.some(
      (round) => round.completed && round.facets.includes(facet),
    ),
  ).length
  const selectedLeadId =
    leadSelection ||
    active.lead_perspective_id ||
    agents[0]?.perspective_id ||
    ""
  const roundProgress = operationProgress.filter(
    (item) =>
      item.kind === "round_stage" ||
      item.kind === "round_turn" ||
      item.kind === "round_check",
  )
  const latestRoundStage = [...roundProgress]
    .reverse()
    .find((item) => item.kind === "round_stage")
  const latestExchangeProgress = [...roundProgress]
    .reverse()
    .find((item) => typeof item.exchange_n === "number")

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div
        aria-hidden="true"
        className="ep-fade-in absolute inset-0 bg-[rgba(16,24,40,0.32)] backdrop-blur-[2px]"
        onClick={onClose}
      />
      <aside
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={drawerTitleId}
        tabIndex={-1}
        className="ep-drawer-enter relative flex h-full w-[min(1180px,96vw)] flex-col border-l border-[var(--line)] bg-[var(--panel)] shadow-[-12px_0_40px_rgba(16,24,40,0.1)]"
      >
        <header className="flex h-12 items-center gap-3 border-b border-[var(--line)] px-5">
          <div
            id={drawerTitleId}
            className="flex-1 text-[13px] font-semibold tracking-[-0.01em]"
          >
            Focused panel
          </div>
          <span className="text-[11px] text-[var(--mute)]">
            {active.completed_at
              ? "Ended"
              : `${active.rounds.filter((round) => round.completed).length} completed rounds`}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="text-[13px] text-[var(--mute)] hover:text-[var(--ink)]"
          >
            ×
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto lg:flex lg:overflow-hidden">
          <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
          <div
            data-testid="panel-conversation-scroll"
            className="min-w-0 flex-1 px-5 py-4 lg:overflow-y-auto"
          >
          <div className="flex flex-wrap items-center gap-2">
            {agents.map((agent) => {
              const perspective = perspectiveOf(agent)
              return (
                <div key={agent.iid} className="flex items-center gap-1">
                  <IdentityChip
                    color={perspective?.color ?? "var(--ink-2)"}
                    name={perspective?.name ?? agent.label}
                    onClick={() => onOpenAgent(agent)}
                  />
                  {agent.iid === openerIid && (
                    <span className="text-[9.5px] font-semibold text-[var(--green)]">
                      Lead
                    </span>
                  )}
                </div>
              )
            })}
            {agents.length < 2 && (
              <EmptyLine>Add at least two Perspectives to the matrix.</EmptyLine>
            )}
          </div>


          <div className="mt-4 min-w-0">
            <div className="min-w-0">
              <div className="flex flex-col gap-5">
            {active.rounds.map((round, index) => (
              <RoundRecord
                key={round.n}
                round={round}
                showPrompts={
                  active.completed_at === null &&
                  round.completed &&
                  index === active.rounds.length - 1
                }
                onPrompt={(prompt) => {
                  setMessage(prompt)
                  window.requestAnimationFrame(() => chatInputRef.current?.focus())
                }}
              />
            ))}
          </div>
          {(active.chat.length > 0 || pendingChat) && (
            <section
              className="mt-5 border-t border-[var(--line)] pt-4"
              data-testid="panel-chat-transcript"
            >
              <SectionLabel>Follow-up conversation</SectionLabel>
              <div className="mt-2 flex flex-col gap-2.5">
                {active.chat.map((turn, index) => (
                  <div
                    key={turn.id}
                    ref={
                      !pendingChat && index === active.chat.length - 1
                        ? latestChatRef
                        : undefined
                    }
                  >
                    <TurnBubble turn={turn} />
                  </div>
                ))}
                {pendingChat && (
                  <>
                    <TurnBubble
                      turn={{
                        id: -2,
                        agent_iid: null,
                        agent_label: "",
                        role: "user",
                        kind: "user",
                        facet: null,
                        text: pendingChat.text,
                        citations: [],
                        exchange_n: null,
                      }}
                    />
                    <div ref={latestChatRef}>
                      <TurnBubble
                        turn={{
                          id: -1,
                          agent_iid: pendingChat.targetIid,
                          agent_label: pendingChat.targetLabel,
                          role: "other",
                          kind: "answer",
                          facet: null,
                          text:
                            pendingChat.status === "queued" && runningRound
                              ? "Queued for after this round"
                              : "Thinking…",
                          citations: [],
                          exchange_n: null,
                        }}
                        thinking={
                          pendingChat.status === "thinking" || !runningRound
                        }
                      />
                    </div>
                  </>
                )}
              </div>
            </section>
          )}



          {runningRound && latestRoundStage && (
            <section
              role="status"
              aria-live="polite"
              data-testid="round-progress"
              className="ep-card-enter mt-4 rounded-xl border border-[var(--line)] bg-[var(--bg)] p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-[12px] font-semibold text-[var(--ink)]">
                  {latestRoundStage.message}
                </span>
                <span className="text-[10.5px] tabular-nums text-[var(--mute)]">
                  {latestExchangeProgress?.exchange_n
                    ? `Exchange ${latestExchangeProgress.exchange_n}/${latestExchangeProgress.max_exchanges ?? 3} · `
                    : ""}
                  {latestRoundStage.step}/{latestRoundStage.total_steps}
                </span>
              </div>
              <progress
                className="mt-2 h-1.5 w-full accent-[var(--green)]"
                max={latestRoundStage.total_steps}
                value={latestRoundStage.step}
              />
              <div className="mt-3 flex flex-col gap-2">
                {roundProgress
                  .filter(
                    (item) =>
                      (item.kind === "round_turn" && item.text) ||
                      item.kind === "round_check",
                  )
                  .map((item) =>
                    item.kind === "round_check" ? (
                      <div
                        key={item.sequence}
                        className="rounded-lg border border-[var(--line)] bg-[var(--bg)] px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2 text-[10.5px] font-semibold">
                          <span>Moderator check</span>
                          <span
                            className={
                              item.unanimous
                                ? "text-[var(--green)]"
                                : "text-[var(--amber)]"
                            }
                          >
                            {item.unanimous ? "Unanimous" : "Continuing"}
                          </span>
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink-2)]">
                          {item.proposed_shared_ground ||
                            "No substantive shared ground yet."}
                        </p>
                      </div>
                    ) : (
                      <div
                        key={item.sequence}
                        className="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10.5px] font-semibold text-[var(--ink-2)]">
                            {item.agent_label || "Panel"}
                          </span>
                          <span className="text-[9.5px] text-[var(--mute)]">
                            Exchange {item.exchange_n ?? 1}
                          </span>
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink-2)]">
                          {item.text}
                        </p>
                      </div>
                    ),
                  )}
              </div>
            </section>
          )}

          {active.no_agreement && active.questions_generated && (
            <div className="ep-card-enter mt-5 rounded-xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3.5">
              <div className="text-[12px] font-semibold text-[var(--ink-2)]">
                No new shared ground
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                This round left the working hypothesis unchanged. Its unresolved
                points still ground the next investigation.
              </p>
            </div>
          )}


          {active.completed_at === null &&
            active.baseline_hypothesis === null && (
              <section className="ep-card-enter rounded-xl border border-[var(--line)] bg-[var(--bg)] p-4">
                <SectionLabel>Set up the panel</SectionLabel>
                <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
                  Choose the lead Perspective
                </h2>
                <p className="mt-1 text-[12px] leading-relaxed text-[var(--mute)]">
                  The lead drafts the baseline hypothesis and opens every round.
                  The remaining Perspectives form the panel.
                </p>
                {active.rounds.length > 0 && (
                  <p className="mt-2 text-[11px] leading-relaxed text-[var(--amber)]">
                    Confirming a lead archives these earlier rounds, questions,
                    and chat in Panel history, then starts a new cycle.
                  </p>
                )}
                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {agents.map((agent) => {
                    const perspective = perspectiveOf(agent)
                    const selected = agent.perspective_id === selectedLeadId
                    return (
                      <button
                        key={agent.iid}
                        type="button"
                        aria-pressed={selected}
                        disabled={!!busy}
                        onClick={() => setLeadSelection(agent.perspective_id)}
                        className="rounded-lg border px-3 py-2.5 text-left"
                        style={{
                          borderColor: selected
                            ? (perspective?.color ?? "var(--ink)")
                            : "var(--line-strong)",
                          background: selected
                            ? "var(--panel)"
                            : "transparent",
                        }}
                      >
                        <span className="text-[12px] font-semibold text-[var(--ink)]">
                          {perspective?.name ?? agent.label}
                        </span>
                        <span className="mt-0.5 block text-[10.5px] text-[var(--mute)]">
                          {selected ? "Lead" : "Panel member"}
                        </span>
                      </button>
                    )
                  })}
                </div>
                <Button
                  variant="primary"
                  size="md"
                  className="mt-3"
                  disabled={!!busy || !selectedLeadId}
                  onClick={initializePanel}
                >
                  {busy === "Generating lead hypothesis" ? (
                    <>
                      <Spinner /> Generating baseline…
                    </>
                  ) : (
                    "Confirm lead and generate baseline"
                  )}
                </Button>
              </section>
            )}

          {active.completed_at === null &&
            active.baseline_hypothesis !== null &&
            (active.hypothesis === null || active.hypothesis_confirmed) && (
              <section
                className={`ep-card-enter rounded-xl border border-[var(--line)] bg-[var(--bg)] p-4 ${
                  active.rounds.length > 0 ? "mt-4" : ""
                }`}
              >
            {active.rounds.length === 0 && (
              <div className="mb-4 border-b border-[var(--line)] pb-4">
                <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
                  How this panel works
                </h2>
                <p className="mt-1 max-w-[68ch] text-[12px] leading-relaxed text-[var(--ink-2)]">
                  Every Perspective in the matrix is now part of this panel.
                  Together, they will build and refine the working hypothesis
                  shown on the right.
                </p>
                <p className="mt-1.5 max-w-[68ch] text-[12px] leading-relaxed text-[var(--mute)]">
                  Each round examines one area. You can revisit an area and ask
                  the panel or one Perspective a follow-up question between rounds.
                </p>
              </div>
            )}
            <div className="flex items-start justify-between gap-4">
              <div>
                <SectionLabel>Round {active.rounds.length + 1}</SectionLabel>
                <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
                  Choose what this panel should focus on
                </h2>
                <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-[var(--mute)]">
                  Select one area. Areas remain reusable, and you can end after
                  any completed round.
                </p>
              </div>
              <div className="shrink-0 text-right">
                <span className="rounded-full border border-[var(--line)] bg-[var(--panel)] px-2 py-1 text-[11px] text-[var(--mute)]">
                  {selectedFacets.length}/1 selected
                </span>
                <div className="mt-1.5 text-[10.5px] text-[var(--mute)]">
                  {discussedFacetCount}/4 discussed
                </div>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              {FACETS.map((facet) => {
                const selected = selectedFacets.includes(facet)
                const unavailable = !selected && selectedFacets.length >= 1
                const meta = FACET_META[facet]
                const discussedRounds = active.rounds
                  .filter(
                    (round) =>
                      round.completed && round.facets.includes(facet),
                  )
                  .map((round) => round.n)
                return (
                  <button
                    key={facet}
                    type="button"
                    aria-pressed={selected}
                    disabled={!!busy || unavailable}
                    onClick={() => toggleFacet(facet)}
                    className="rounded-lg border px-3 py-2.5 text-left transition disabled:cursor-default disabled:opacity-45"
                    style={{
                      borderColor: selected ? meta.color : "var(--line-strong)",
                      background: selected ? meta.tint : "var(--panel)",
                    }}
                  >
                    <div
                      className="text-[12px] font-semibold"
                      style={{ color: selected ? meta.color : "var(--ink)" }}
                    >
                      {meta.label}
                    </div>
                    <div className="mt-0.5 text-[11px] leading-snug text-[var(--mute)]">
                      {meta.short}
                    </div>
                    <div
                      className="mt-1 text-[10.5px] leading-snug"
                      data-testid={`facet-history-${facet}`}
                      style={{
                        color:
                          discussedRounds.length > 0
                            ? meta.color
                            : "var(--mute)",
                      }}
                    >
                      {discussedRounds.length === 0
                        ? "Not discussed yet"
                        : discussedRounds.length === 1
                          ? `Discussed in round ${discussedRounds[0]}`
                          : `Discussed in rounds ${discussedRounds.join(", ")}`}
                    </div>
                  </button>
                )
              })}
            </div>

            <div className="mt-3 flex justify-end border-t border-[var(--line)] pt-3">
              <Button
                variant="primary"
                size="md"
                disabled={
                  !!busy ||
                  agents.length < 2 ||
                  openerIid == null ||
                  selectedFacets.length !== 1
                }
                onClick={startRound}
              >
                {runningRound ? (
                  <>
                    <Spinner /> Deliberating…
                  </>
                ) : (
                  "Start round"
                )}
              </Button>
            </div>
          </section>
          )}
          {error && (
            <div role="alert" className="mt-4 text-[12px] text-[var(--red)]">
              {error}
            </div>
          )}
            </div>
          </div>
          </div>
        {active.completed_at === null &&
          active.baseline_hypothesis !== null && (
          <footer
            data-testid="panel-chat-bar"
            className="border-t border-[var(--line)] bg-[var(--panel)] px-5 py-3"
          >
            <div className="flex items-center gap-2">
              <select
                value={target ?? "all"}
                onChange={(event) =>
                  setTarget(
                    event.target.value === "all"
                      ? null
                      : Number(event.target.value),
                  )
                }
                className="field h-9 max-w-[180px] px-2.5 text-[11px] text-[var(--ink-2)]"
                aria-label="Message recipient"
                disabled={
                  pendingChat !== null || (!!busy && !runningRound)
                }
              >
                <option value="all">Panel</option>
                {agents.map((agent) => (
                  <option key={agent.iid} value={agent.iid}>
                    {perspectiveOf(agent)?.name ?? agent.label}
                  </option>
                ))}
              </select>
              <input
                ref={chatInputRef}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    send()
                  }
                }}
                className="field h-9 min-w-0 flex-1 px-3 text-[13px]"
                placeholder="Ask a question at any point…"
                disabled={
                  pendingChat !== null ||
                  (!!busy && !runningRound) ||
                  agents.length === 0
                }
              />
              <Button
                variant="primary"
                size="sm"
                onClick={send}
                disabled={
                  pendingChat !== null ||
                  (!!busy && !runningRound) ||
                  !message.trim() ||
                  agents.length === 0
                }
              >
                {busy === "Deliberating" && !pendingChat ? <Spinner /> : "Send"}
              </Button>
            </div>
          </footer>
        )}
          </div>
          <div
            data-testid="working-hypothesis-sidebar"
            className="shrink-0 border-t border-[var(--line)] px-4 py-4 lg:w-[380px] lg:overflow-y-auto lg:border-l lg:border-t-0"
          >
            <WorkingHypothesisPanel
              deliberation={active}
              value={hypothesisDraft}
              savedHypothesis={session.applied_hypothesis}
              savedVersionId={session.applied_hypothesis_version_id}
              busy={busy !== null}
              applying={busy === "Applying hypothesis"}
              saving={busy === "Saving hypothesis checkpoint"}
              completed={active.completed_at !== null}
              ending={busy === "Ending deliberation"}
              onChange={setHypothesisDraft}
              onApply={confirmDraft}
              onReject={rejectDraft}
              onSave={saveDraft}
              onEnd={endDeliberation}
              onRate={onRate}
              onInvestigateQuestion={(questionId) => {
                void act(() => createChildInvestigation(questionId))
              }}
              onOpenChild={(investigationId) =>
                act(() => switchInvestigation(investigationId))
              }
              onSetQuestionStatus={(questionId, status) =>
                act(() => updateQuestionStatus(questionId, status))
              }
            />
          </div>
        </div>

      </aside>
    </div>
  )
}

function RoundRecord({
  round,
  showPrompts = false,
  onPrompt,
}: {
  round: DeliberationRound
  showPrompts?: boolean
  onPrompt?: (prompt: string) => void
}) {
  const exchangeNumbers = Array.from(
    new Set(round.turns.map((turn) => turn.exchange_n ?? 1)),
  )
  return (
    <section className="ep-enter">
      <div className="mb-2 flex items-center gap-2">
        <SectionLabel>Round {round.n}</SectionLabel>
        {round.facets.map((facet) => (
          <span
            key={facet}
            className="rounded-full border border-[var(--line-strong)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--ink-2)]"
          >
            {FACET_META[facet].label}
          </span>
        ))}
        {!round.completed && (
          <span className="ml-auto flex items-center gap-1.5 text-[11px] text-[var(--mute)]">
            <Spinner /> In progress
          </span>
        )}
      </div>

      <div
        className="flex flex-col gap-3"
        data-testid={`round-${round.n}-discussion`}
      >
        {exchangeNumbers.map((exchangeN) => {
          const check = round.moderator_checks.find(
            (item) => item.exchange_n === exchangeN,
          )
          return (
            <section
              key={exchangeN}
              className="rounded-xl border border-[var(--line)] p-3"
            >
              <div className="mb-2 text-[10.5px] font-semibold text-[var(--mute)]">
                Exchange {exchangeN}
              </div>
              <div className="flex flex-col gap-2.5">
                {round.turns
                  .filter((turn) => (turn.exchange_n ?? 1) === exchangeN)
                  .map((turn) => (
                    <TurnBubble key={turn.id} turn={turn} />
                  ))}
              </div>
              {check && (
                <div className="mt-3 rounded-lg bg-[var(--bg)] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <SectionLabel>Moderator check</SectionLabel>
                    <span
                      className={`text-[10.5px] font-semibold ${
                        check.unanimous
                          ? "text-[var(--green)]"
                          : "text-[var(--amber)]"
                      }`}
                    >
                      {check.unanimous ? "Unanimous" : "Not unanimous"}
                    </span>
                  </div>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--ink-2)]">
                    {check.proposed_shared_ground ||
                      "No substantive shared ground yet."}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {check.assents.map((assent) => (
                      <span
                        key={assent.agent_iid}
                        title={assent.reason}
                        className="rounded-full border border-[var(--line)] px-2 py-0.5 text-[9.5px] text-[var(--ink-2)]"
                      >
                        {assent.agent_label}: {assent.decision}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )
        })}
      </div>
      {round.resolution && (
        <div data-testid={`round-${round.n}-summary`}>
          <ResolutionCard resolution={round.resolution} />
        </div>
      )}

      {round.verdicts.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          {round.verdicts.map((verdict) => {
            const meta = VERDICT_META[verdict.status]
            return (
              <div
                key={verdict.facet}
                className="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-semibold text-[var(--ink)]">
                    {FACET_META[verdict.facet].label}
                  </span>
                  <span
                    className="text-[10.5px] font-semibold"
                    style={{ color: meta.color }}
                  >
                    {meta.label}
                  </span>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-[var(--ink-2)]">
                  {verdict.summary}
                </p>
              </div>
            )
          })}
        </div>
      )}

      {round.reflections.some((item) => item.decision === "revised") && (
        <div className="mt-3 rounded-lg border border-[var(--line)] px-3 py-2.5">
          <SectionLabel>Lead Perspective update</SectionLabel>
          <div className="mt-1 flex flex-col gap-2">
            {round.reflections
              .filter((item) => item.decision === "revised")
              .map((item) => (
                <div key={item.agent_iid} className="text-[11px] leading-relaxed">
                  <div>
                    <span className="font-semibold text-[var(--ink)]">
                      {item.perspective_name}
                    </span>{" "}
                    <span className="text-[var(--mute)]">{item.reason}</span>
                  </div>
                  {item.revisions.map((revision) => (
                    <p
                      key={revision.facet}
                      className="mt-1 text-[var(--ink-2)]"
                    >
                      <span className="font-semibold">
                        {FACET_META[revision.facet].label}:
                      </span>{" "}
                      {revision.text}
                    </p>
                  ))}
                </div>
              ))}
          </div>
        </div>
      )}

      {showPrompts && onPrompt && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--line)] pt-3">
          <span className="text-[10.5px] text-[var(--mute)]">
            Ask about this round:
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              onPrompt(
                round.stop_reason === "unanimous"
                  ? "Why did the panel agree on this shared ground?"
                  : "Which disagreements or uncertainties remain unresolved?",
              )
            }
          >
            {round.stop_reason === "unanimous"
              ? "Why this agreement?"
              : "What remains unresolved?"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              onPrompt(
                "Which part of the working hypothesis would you change, and why?",
              )
            }
          >
            What would you change?
          </Button>
        </div>
      )}
    </section>
  )
}

const THINKING_SCORES = [1, 2, 3, 4, 5, 6, 7] as const

function DeliberationScoringDialog({
  deliberationId,
  onClose,
}: {
  deliberationId: string
  onClose: () => void
}) {
  const session = useFocusedStore((state) => state.session)
  const busy = useFocusedStore((state) => state.busy)
  const { rateDeliberation } = useFocusedPanel()
  const deliberation = session?.deliberations.find(
    (item) => item.id === deliberationId,
  )
  const [divergent, setDivergent] = useState<number | null>(
    deliberation?.rating?.divergent ?? null,
  )
  const [convergent, setConvergent] = useState<number | null>(
    deliberation?.rating?.convergent ?? null,
  )
  const [error, setError] = useState<string | null>(null)
  if (!deliberation) return null

  const questions = [
    {
      key: "divergent",
      title: "Divergent thinking",
      question:
        "Did the multi-agent deliberation help you expand the range of ideas you were considering—for example, did anything come up that you would not have thought of alone?",
      value: divergent,
      setValue: setDivergent,
    },
    {
      key: "convergent",
      title: "Convergent thinking",
      question:
        "Did the multi-agent deliberation help you settle on a single, well-supported direction—for example, did the discussion narrow things down rather than leave you with more open options?",
      value: convergent,
      setValue: setConvergent,
    },
  ] as const

  const save = async () => {
    if (divergent === null || convergent === null) return
    setError(null)
    try {
      await rateDeliberation(deliberation.id, {
        divergent,
        convergent,
        note: deliberation.rating?.note ?? "",
      })
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save scores")
    }
  }

  return (
    <ModalShell title="Rate this deliberation" onClose={onClose}>
      <p className="mb-4 text-[12px] leading-relaxed text-[var(--ink-2)]">
        Consider the completed deliberation as a whole.
      </p>
      <div className="flex flex-col gap-5">
        {questions.map((item) => (
          <fieldset key={item.key} aria-label={item.title}>
            <legend className="text-[12px] font-semibold text-[var(--ink)]">
              {item.title}
            </legend>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
              {item.question}
            </p>
            <div className="mt-2 w-fit">
              <div className="flex items-center gap-1.5">
                {THINKING_SCORES.map((score) => (
                  <label key={score} className="relative cursor-pointer">
                    <input
                      type="radio"
                      name={`deliberation-${deliberation.id}-${item.key}`}
                      value={score}
                      checked={item.value === score}
                      disabled={busy !== null}
                      onChange={() => item.setValue(score)}
                      className="peer absolute inset-0 opacity-0"
                    />
                    <span className="grid size-8 place-items-center rounded-md border border-[var(--line-strong)] text-[12px] font-medium text-[var(--ink-2)] peer-checked:border-[var(--ink)] peer-checked:bg-[var(--ink)] peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--ink)]">
                      {score}
                    </span>
                  </label>
                ))}
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-[var(--mute)]">
                <span>Not at all</span>
                <span>Very much</span>
              </div>
            </div>
          </fieldset>
        ))}
      </div>
      {error && (
        <p role="alert" className="mt-4 text-[12px] text-[var(--red)]">
          {error}
        </p>
      )}
      <div className="mt-5 flex justify-end">
        <Button
          variant="primary"
          size="sm"
          disabled={
            busy !== null || divergent === null || convergent === null
          }
          onClick={() => void save()}
        >
          {busy === "Saving deliberation scores" ? (
            <>
              <Spinner /> Saving…
            </>
          ) : deliberation.rating ? (
            "Update scores"
          ) : (
            "Save scores"
          )}
        </Button>
      </div>
    </ModalShell>
  )
}

function ResolutionCard({ resolution }: { resolution: NonNullable<DeliberationRound["resolution"]> }) {
  const groups: {
    title: string
    points: DeliberationPoint[]
    color: string
  }[] = [
    { title: "Shared ground", points: resolution.consensus_points, color: "var(--green)" },
    { title: "Disagreement", points: resolution.disagreement_points, color: "var(--red)" },
    { title: "Still unsettled", points: resolution.unsettled_points, color: "var(--amber)" },
  ]
  return (
    <section
      aria-label="Moderator summary"
      className="mt-3 rounded-xl border border-[var(--line)] bg-[var(--bg)] p-3.5"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12px] font-semibold text-[var(--ink)]">
          Moderator
        </span>
        <span className="text-[10.5px] text-[var(--mute)]">Round summary</span>
      </div>
      <p className="mt-1 text-[13px] leading-relaxed text-[var(--ink)]">
        {resolution.summary}
      </p>
      <div className="mt-3 grid grid-cols-3 gap-3">
        {groups.map((group) => (
          <div key={group.title}>
            <div className="text-[10.5px] font-semibold" style={{ color: group.color }}>
              {group.title}
            </div>
            {group.points.length ? (
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {group.points.map((point, index) => (
                  <li key={`${point.facet}-${index}`} className="text-[11px] leading-relaxed text-[var(--ink-2)]">
                    <span className="font-semibold text-[var(--ink)]">
                      {FACET_META[point.facet].label}:
                    </span>{" "}
                    {point.text}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-[11px] text-[var(--mute)]">None recorded</p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}



const HYPOTHESIS_PARTS: {
  key: keyof HypothesisDev
  label: string
  prompt: string
}[] = [
  { key: "problem", label: "Problem", prompt: "What needs explaining?" },
  { key: "previous_work", label: "Previous work", prompt: "What does prior work establish?" },
  { key: "reasoning", label: "Reasoning", prompt: "Why should the claim follow?" },
  { key: "hypothesis", label: "Hypothesis", prompt: "What testable claim follows?" },
]

function normalizedHypothesisPart(value: string | undefined): string {
  const normalized = value?.trim() ?? ""
  return normalized === "Not established yet." ? "" : normalized
}

function WorkingHypothesisPanel({
  deliberation,
  value,
  savedHypothesis,
  savedVersionId,
  busy,
  applying,
  saving,
  completed,
  ending,
  onChange,
  onApply,
  onReject,
  onSave,
  onEnd,
  onRate,
  onInvestigateQuestion,
  onOpenChild,
  onSetQuestionStatus,
}: {
  deliberation: DeliberationState
  value: HypothesisDev | null
  savedHypothesis: HypothesisDev | null
  savedVersionId: string | null
  busy: boolean
  applying: boolean
  saving: boolean
  completed: boolean
  ending: boolean
  onChange: (value: HypothesisDev) => void
  onApply: (
    value: HypothesisDev,
    selectedParts: (keyof HypothesisDev)[],
  ) => Promise<boolean>
  onReject: () => Promise<boolean>
  onSave: () => Promise<boolean>
  onEnd: (selectedQuestionIds: string[]) => Promise<boolean>
  onRate: () => void
  onInvestigateQuestion: (questionId: string) => void
  onOpenChild: (investigationId: string) => void
  onSetQuestionStatus: (
    questionId: string,
    status: QuestionStatus,
  ) => void
}) {
  const visibleQuestions = deliberation.recommended_questions
  const openQuestions = visibleQuestions.filter(
    (question) => question.status === "open",
  )
  const current: HypothesisDev = value ?? {
    problem: "",
    previous_work: "",
    reasoning: "",
    hypothesis: "",
  }
  const [editing, setEditing] = useState(false)
  const [applyConfirmationOpen, setApplyConfirmationOpen] = useState(false)
  const [finalReviewOpen, setFinalReviewOpen] = useState(false)
  const [selectedHypothesisParts, setSelectedHypothesisParts] = useState<
    (keyof HypothesisDev)[]
  >([])
  const [selectedQuestionIds, setSelectedQuestionIds] = useState<string[]>(
    () =>
      deliberation.recommended_questions
        .filter(
          (question) =>
            question.status === "open" && question.selected_for_followup,
        )
        .map((question) => question.id),
  )
  const hasCompletedRound = deliberation.rounds.some((round) => round.completed)
  const pending = value !== null && !deliberation.hypothesis_confirmed
  const unsaved =
    deliberation.hypothesis_confirmed &&
    deliberation.applied_hypothesis !== null &&
    (!savedHypothesis ||
      HYPOTHESIS_PARTS.some(
        (part) =>
          deliberation.applied_hypothesis?.[part.key] !==
          savedHypothesis[part.key],
      ))
  const reviewingChanges = pending || editing
  const baseline = deliberation.applied_hypothesis
  const changedParts = reviewingChanges
    ? HYPOTHESIS_PARTS.filter(
        (part) =>
          normalizedHypothesisPart(current[part.key]) !==
          normalizedHypothesisPart(baseline?.[part.key]),
      )
    : []
  const cancelEditing = () => {
    const original = deliberation.hypothesis ?? deliberation.applied_hypothesis
    if (original) onChange({ ...original })
    setEditing(false)
  }

  return (
    <aside className="min-w-0">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[13px] font-semibold tracking-[-0.01em]">
            Working hypothesis
          </div>
          <p className="mt-0.5 text-[10.5px] leading-relaxed text-[var(--mute)]">
            Four steps that evolve as the panel establishes shared ground.
          </p>
        </div>
        {value && (
          <span
            className="shrink-0 text-[10px] font-medium"
            style={{
              color: pending || unsaved ? "var(--amber)" : "var(--green)",
            }}
          >
            {pending
              ? "Update ready"
              : unsaved
                ? "Applied, not saved"
                : savedVersionId
                  ? `Saved ${savedVersionId}`
                  : "Applied"}
          </span>
        )}
      </div>

      {reviewingChanges && (
        <p className="mt-2 text-[10.5px] leading-relaxed text-[var(--ink-2)]">
          {changedParts.length} of {HYPOTHESIS_PARTS.length} parts changed.
          Review the previous and proposed text before applying.
        </p>
      )}

      <div className="mt-3 flex flex-col gap-2.5">
        {HYPOTHESIS_PARTS.map((part, index) => {
          const changed =
            reviewingChanges &&
            normalizedHypothesisPart(current[part.key]) !==
              normalizedHypothesisPart(baseline?.[part.key])
          return (
            <div key={part.key}>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[10px] font-medium text-[var(--mute)]">
                  {index + 1}
                </span>
                <span className="text-[11px] font-semibold text-[var(--ink)]">
                  {part.label}
                </span>
                <span className="text-[9.5px] text-[var(--mute)]">
                  {part.prompt}
                </span>
                {changed && (
                  <span className="ml-auto text-[9.5px] font-semibold text-[var(--amber)]">
                    Changed
                  </span>
                )}
              </div>
              {changed && (
                <div className="mt-1 rounded-lg border border-[var(--line)] bg-[var(--panel)] px-2.5 py-2">
                  <div className="text-[9.5px] font-medium text-[var(--mute)]">
                    Before
                  </div>
                  <p className="mt-0.5 text-[10.5px] leading-relaxed text-[var(--ink-2)]">
                    {baseline?.[part.key] || "Not established yet."}
                  </p>
                </div>
              )}
              {changed && (
                <div className="mt-1 text-[9.5px] font-medium text-[var(--mute)]">
                  Proposed
                </div>
              )}
              {editing && value ? (
                <textarea
                  rows={3}
                  aria-label={`${part.label} hypothesis step`}
                  value={current[part.key]}
                  onChange={(event) =>
                    onChange({ ...current, [part.key]: event.target.value })
                  }
                  className="field mt-1 w-full resize-y bg-[var(--panel)] px-2.5 py-2 text-[11.5px] leading-relaxed"
                  disabled={busy}
                />
              ) : (
                <div
                  data-hypothesis-part={part.key}
                  className={`mt-1 min-h-[62px] rounded-lg border border-[var(--line)] bg-[var(--bg)] px-2.5 py-2 text-[11.5px] leading-relaxed ${
                    current[part.key]
                      ? "text-[var(--ink-2)]"
                      : "text-[var(--mute)]"
                  }`}
                  style={
                    changed
                      ? {
                          borderColor: "var(--amber)",
                          background:
                            "color-mix(in srgb, var(--amber) 7%, var(--panel))",
                        }
                      : undefined
                  }
                >
                  {current[part.key] || "Not established yet."}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {value ? (
        <div className="mt-3 border-t border-[var(--line)] pt-3">
          {pending && (
            <p className="mb-2 text-[10.5px] leading-relaxed text-[var(--ink-2)]">
              The latest round proposed changes from supported shared ground.
              Apply them to the working hypothesis before saving a checkpoint.
            </p>
          )}
          {unsaved && !pending && (
            <p className="mb-2 text-[10.5px] leading-relaxed text-[var(--ink-2)]">
              The working hypothesis has unsaved changes. Save it when the
              four-part claim is ready to appear on the canvas.
            </p>
          )}
          <div className="flex gap-2">
            {!completed && !editing && (
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => setEditing(true)}
                disabled={busy}
              >
                {pending ? "Edit update" : "Edit hypothesis"}
              </Button>
            )}
            {!completed && pending && !editing && (
              <Button
                variant="ghost"
                size="sm"
                className="flex-1"
                onClick={() => void onReject()}
                disabled={busy}
              >
                Reject update
              </Button>
            )}
            {!completed && editing && (
              <Button
                variant="ghost"
                size="sm"
                className="flex-1"
                onClick={cancelEditing}
                disabled={busy}
              >
                Cancel editing
              </Button>
            )}
            {!completed && (pending || editing) && (
              <Button
                variant={pending ? "primary" : "outline"}
                size="sm"
                className="flex-1"
                onClick={() => {
                  setSelectedHypothesisParts(
                    changedParts.map((part) => part.key),
                  )
                  setApplyConfirmationOpen(true)
                }}
                disabled={busy || changedParts.length === 0}
              >
                {applying ? (
                  <>
                    <Spinner /> Applying…
                  </>
                ) : pending ? (
                  "Apply shared ground"
                ) : (
                  "Apply edits"
                )}
              </Button>
            )}
            {!completed && unsaved && !pending && !editing && (
              <Button
                variant="primary"
                size="sm"
                className="flex-1"
                onClick={() => void onSave()}
                disabled={busy}
              >
                {saving ? (
                  <>
                    <Spinner /> Saving…
                  </>
                ) : (
                  "Save hypothesis"
                )}
              </Button>
            )}
          </div>
        </div>
      ) : (
        <p className="mt-3 rounded-lg bg-[var(--bg)] px-3 py-2.5 text-[10.5px] leading-relaxed text-[var(--mute)]">
          Complete a round to add supported shared ground.
        </p>
      )}
      <div className="mt-4 border-t border-[var(--line)] pt-3">
        <SectionLabel>Open questions</SectionLabel>
        {visibleQuestions.length > 0 ? (
          <>
            <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--mute)]">
              Start a child Investigation when a question needs new literature
              and new Perspectives. It inherits the last applied hypothesis;
              any update still awaiting review stays here.
            </p>
            <div className="mt-2 flex flex-col gap-2.5">
              {visibleQuestions.map((item) => (
                <article
                  key={item.id}
                  className="rounded-lg border border-[var(--line)] bg-[var(--bg)] p-2.5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-[11px] font-medium leading-relaxed text-[var(--ink)]">
                      {item.question}
                    </span>
                    {item.child_investigation_id ? (
                      <select
                        aria-label={`Status for ${item.question}`}
                        value={item.status}
                        disabled={busy}
                        onChange={(event) => {
                          const status = event.target.value
                          if (
                            status === "investigating" ||
                            status === "addressed" ||
                            status === "archived"
                          ) {
                            onSetQuestionStatus(item.id, status)
                          }
                        }}
                        className="shrink-0 border-0 bg-transparent text-[9.5px] font-medium capitalize text-[var(--ink-2)] outline-none"
                      >
                        <option value="investigating">Investigating</option>
                        <option value="addressed">Addressed</option>
                        <option value="archived">Archived</option>
                      </select>
                    ) : (
                      <span className="shrink-0 text-[9px] font-medium capitalize text-[var(--mute)]">
                        {item.status}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[9.5px] leading-relaxed text-[var(--mute)]">
                    {item.source_kind === "disagreement"
                      ? "From disagreement"
                      : "From an unsettled point"}
                    {" · "}
                    {item.rationale}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {item.status === "open" && (
                      <>
                        <span className="self-center text-[9.5px] text-[var(--mute)]">
                          {completed
                            ? "Start a child Investigation with fresh literature and Perspectives."
                            : "Its Research Problem node appears when you end the deliberation."}
                        </span>
                        {completed && (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => onInvestigateQuestion(item.id)}
                          >
                            Start paper search
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => onSetQuestionStatus(item.id, "archived")}
                        >
                          Archive
                        </Button>
                      </>
                    )}
                    {item.status === "archived" &&
                      !item.child_investigation_id && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => onSetQuestionStatus(item.id, "open")}
                        >
                          Reopen
                        </Button>
                      )}
                    {item.child_investigation_id && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          onOpenChild(item.child_investigation_id!)
                        }
                      >
                        Open Investigation
                      </Button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </>
        ) : (
          <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--mute)]">
            Unresolved points from the panel will appear here.
          </p>
        )}
      </div>
      <div className="mt-4 border-t border-[var(--line)] pt-3">
        {completed ? (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-[var(--ink)]">
                Deliberation ended
              </div>
              <p className="mt-0.5 text-[10.5px] text-[var(--mute)]">
                The final hypothesis and Research Problem nodes are on the canvas.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 whitespace-nowrap"
              disabled={busy}
              onClick={onRate}
            >
              {deliberation.rating ? "Update scores" : "Rate deliberation"}
            </Button>
          </div>
        ) : (
          <>
            <p className="text-[10.5px] leading-relaxed text-[var(--mute)]">
              {hasCompletedRound
                ? "Review the saved hypothesis and choose which open questions to prioritize before ending."
                : "Complete a round before reviewing and ending the deliberation."}
            </p>
            <Button
              variant="primary"
              size="sm"
              className="mt-2 w-full"
              disabled={
                !hasCompletedRound ||
                busy ||
                pending ||
                unsaved ||
                editing ||
                savedVersionId === null
              }
              onClick={() => {
                setSelectedQuestionIds(
                  openQuestions
                    .filter((question) => question.selected_for_followup)
                    .map((question) => question.id),
                )
                setFinalReviewOpen(true)
              }}
            >
              Review and end
            </Button>
          </>
        )}
      </div>
      {finalReviewOpen && (
        <ModalShell
          title="Review and end deliberation"
          onClose={() => {
            if (!ending) setFinalReviewOpen(false)
          }}
        >
          <p className="text-[12px] leading-relaxed text-[var(--ink-2)]">
            Confirm the saved hypothesis and choose the open questions that
            should remain prioritized.
          </p>
          <div className="mt-3 rounded-lg border border-[var(--line)] bg-[var(--bg)] p-3">
            <SectionLabel>Final hypothesis</SectionLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink)]">
              {deliberation.applied_hypothesis?.hypothesis}
            </p>
          </div>
          <div className="mt-3 flex max-h-64 flex-col gap-2 overflow-y-auto">
            {openQuestions.length > 0 ? (
              openQuestions.map((question) => {
                const selected = selectedQuestionIds.includes(question.id)
                return (
                  <label
                    key={question.id}
                    className="flex cursor-pointer items-start gap-2 rounded-lg border border-[var(--line)] p-2.5"
                  >
                    <input
                      type="checkbox"
                      checked={selected}
                      disabled={ending}
                      onChange={() =>
                        setSelectedQuestionIds((current) =>
                          selected
                            ? current.filter((id) => id !== question.id)
                            : [...current, question.id],
                        )
                      }
                    />
                    <span className="text-[11px] leading-relaxed text-[var(--ink-2)]">
                      {question.question}
                    </span>
                  </label>
                )
              })
            ) : (
              <EmptyLine>No open questions to carry forward.</EmptyLine>
            )}
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={ending}
              onClick={() => setFinalReviewOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={ending}
              onClick={() => {
                const openQuestionIds = new Set(
                  openQuestions.map((question) => question.id),
                )
                void onEnd(
                  selectedQuestionIds.filter((id) => openQuestionIds.has(id)),
                ).then((ended) => {
                  if (ended) setFinalReviewOpen(false)
                })
              }}
            >
              {ending ? (
                <>
                  <Spinner /> Ending…
                </>
              ) : (
                "Confirm and end"
              )}
            </Button>
          </div>
        </ModalShell>
      )}

      {applyConfirmationOpen && (
        <ModalShell
          title="Apply hypothesis changes?"
          onClose={() => {
            if (!applying) setApplyConfirmationOpen(false)
          }}
        >
          <p className="mb-4 text-[12px] leading-relaxed text-[var(--ink-2)]">
            Select the proposed parts to apply. Unselected parts keep their
            current text.
          </p>
          <div className="flex max-h-[52vh] flex-col gap-3 overflow-y-auto">
            {changedParts.map((part) => {
              const selected = selectedHypothesisParts.includes(part.key)
              return (
                <label
                  key={part.key}
                  data-testid={`changed-hypothesis-part-${part.key}`}
                  className="cursor-pointer rounded-lg border px-3 py-2.5"
                  style={{
                    borderColor: selected ? "var(--amber)" : "var(--line)",
                    background: selected
                      ? "color-mix(in srgb, var(--amber) 7%, var(--panel))"
                      : "transparent",
                  }}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      aria-label={`Apply ${part.label}`}
                      checked={selected}
                      disabled={applying || baseline === null}
                      onChange={() =>
                        setSelectedHypothesisParts((currentParts) =>
                          selected
                            ? currentParts.filter((key) => key !== part.key)
                            : [...currentParts, part.key],
                        )
                      }
                    />
                    <span className="text-[11px] font-semibold text-[var(--ink)]">
                      {part.label}
                    </span>
                  </div>
                  <div className="mt-2 text-[9.5px] font-medium text-[var(--mute)]">
                    Before
                  </div>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink-2)]">
                    {baseline?.[part.key] || "Not established yet."}
                  </p>
                  <div className="mt-2 text-[9.5px] font-medium text-[var(--amber)]">
                    Proposed
                  </div>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ink)]">
                    {current[part.key] || "Not established yet."}
                  </p>
                </label>
              )
            })}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={applying}
              onClick={() => setApplyConfirmationOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={applying || selectedHypothesisParts.length === 0}
              onClick={() => {
                void onApply(current, selectedHypothesisParts).then((applied) => {
                  if (!applied) return
                  setEditing(false)
                  setApplyConfirmationOpen(false)
                })
              }}
            >
              {applying ? (
                <>
                  <Spinner /> Applying…
                </>
              ) : (
                `Apply ${selectedHypothesisParts.length} part${
                  selectedHypothesisParts.length === 1 ? "" : "s"
                }`
              )}
            </Button>
          </div>
        </ModalShell>
      )}
    </aside>
  )
}

function TurnBubble({
  turn,
  thinking = false,
}: {
  turn: Turn
  thinking?: boolean
}) {
  const session = useFocusedStore((state) => state.session)
  const openPaperSet = useFocusedStore((state) => state.openPaperSet)
  const perspective =
    turn.agent_iid == null
      ? undefined
      : session?.agents
          .filter((agent) => agent.iid === turn.agent_iid)
          .map((agent) =>
            session.perspectives.find(
              (item) => item.id === agent.perspective_id,
            ),
          )[0]
  const isUser = turn.role === "user"
  const isSupport = turn.kind === "support"
  const identityColor = perspective?.color ?? "var(--ink-2)"

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`w-full rounded-xl border px-3 py-2.5 ${
          isUser
            ? "border-transparent bg-[var(--node)] text-white"
            : isSupport
              ? "border-[var(--line)] bg-[var(--bg)]"
              : "border-[var(--line)] bg-[var(--panel)]"
        }`}
      >
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <span
            className={`text-[11px] font-semibold ${
              isUser ? "text-white" : ""
            }`}
            style={isUser ? undefined : { color: identityColor }}
          >
            {isUser ? "Researcher" : turn.agent_label || "Panel"}
            {turn.role === "lead" && (
              <span className="ml-1 text-[9.5px] text-[var(--green)]">
                Lead
              </span>
            )}
          </span>
          {turn.facet && (
            <span
              className={`shrink-0 text-[10px] font-medium ${
                isUser ? "text-white/70" : "text-[var(--mute)]"
              }`}
            >
              {FACET_META[turn.facet].label}
            </span>
          )}
        </div>
        {thinking ? (
          <p className="flex items-center gap-2 text-[12.5px] leading-relaxed text-[var(--mute)]">
            <Spinner />
            Thinking…
          </p>
        ) : isUser ? (
          <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-white">
            {turn.text}
          </p>
        ) : (
          <div className="text-[12.5px] leading-relaxed text-[var(--ink)] [&_a]:underline [&_a]:underline-offset-2 [&_li]:my-1 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-0 [&_p+p]:mt-2 [&_strong]:font-semibold [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
            <Markdown>{turn.text}</Markdown>
          </div>
        )}
        {turn.citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {turn.citations.map((paperId) => {
              const paper = session?.papers.find((item) => item.id === paperId)
              return (
                <button
                  key={paperId}
                  type="button"
                  onClick={() => openPaperSet(paperId)}
                  className="text-[10px] underline decoration-dotted underline-offset-2"
                  style={{
                    color: isUser
                      ? "rgba(255,255,255,.72)"
                      : "var(--mute)",
                  }}
                >
                  {paper?.title ?? "Source"}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}


function AddPerspectiveDialog({
  clusters,
  perspectives,
  busy,
  adding,
  onAdd,
  onClose,
}: {
  clusters: ClusterCard[]
  perspectives: Perspective[]
  busy: boolean
  adding: boolean
  onAdd: (clusterId: string, invitedPerspectiveIds: string[]) => Promise<void>
  onClose: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [invited, setInvited] = useState<string[]>(() =>
    perspectives.map((perspective) => perspective.id),
  )

  const add = async (cluster: ClusterCard) => {
    setError(null)
    try {
      await onAdd(cluster.id, invited)
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not add the Perspective",
      )
    }
  }

  return (
    <ModalShell
      title="Add a Perspective"
      onClose={() => {
        if (!busy) onClose()
      }}
    >
      <p className="mb-4 text-[12px] leading-relaxed text-[var(--ink-2)]">
        The added Perspective starts a new deliberation from scratch. Prior
        rounds and hypotheses remain in panel history.
      </p>
      <fieldset className="mb-4">
        <legend className="mb-1.5 text-[12px] font-medium text-[var(--ink-2)]">
          Invite existing Perspectives
        </legend>
        <div className="flex flex-col gap-1.5">
          {perspectives.map((perspective) => {
            const selected = invited.includes(perspective.id)
            return (
              <button
                key={perspective.id}
                type="button"
                aria-pressed={selected}
                disabled={busy}
                onClick={() =>
                  setInvited((current) =>
                    current.includes(perspective.id)
                      ? current.filter((id) => id !== perspective.id)
                      : [...current, perspective.id],
                  )
                }
                className="flex items-center gap-2 rounded-lg border border-[var(--line-strong)] px-3 py-2 text-left disabled:opacity-50"
              >
                <span
                  className="grid size-4 place-items-center rounded-[4px] text-[10px] text-white"
                  style={{
                    background: selected ? "var(--ink)" : "transparent",
                    border: `1px solid ${
                      selected ? "var(--ink)" : "var(--line-strong)"
                    }`,
                  }}
                  aria-hidden
                >
                  {selected ? "✓" : ""}
                </span>
                <span className="text-[12px] font-medium">
                  {perspective.name}
                </span>
              </button>
            )
          })}
        </div>
        {invited.length === 0 && (
          <p className="mt-1.5 text-[11px] text-[var(--amber)]">
            Invite at least one existing Perspective so the panel has two
            participants.
          </p>
        )}
      </fieldset>
      <div className="flex flex-col gap-2">
        {clusters.map((cluster) => (
          <button
            key={cluster.id}
            type="button"
            aria-label={`Add ${cluster.name}`}
            disabled={busy || invited.length === 0}
            onClick={() => void add(cluster)}
            className="rounded-lg border border-[var(--line-strong)] px-3 py-2.5 text-left transition hover:border-[var(--ink-2)] disabled:cursor-default disabled:opacity-50"
          >
            <span className="flex items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="block text-[12px] font-semibold text-[var(--ink)]">
                  {cluster.name}
                </span>
                <span className="mt-0.5 block text-[11px] leading-relaxed text-[var(--mute)]">
                  {cluster.blurb}
                </span>
              </span>
              <span className="shrink-0 text-[10.5px] text-[var(--mute)]">
                {cluster.paper_ids.length} papers
              </span>
            </span>
          </button>
        ))}
      </div>
      {adding && (
        <p
          role="status"
          aria-live="polite"
          className="mt-3 inline-flex items-center gap-1.5 text-[11px] text-[var(--mute)]"
        >
          <Spinner /> Adding Perspective…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-[12px] text-[var(--red)]">
          {error}
        </p>
      )}
    </ModalShell>
  )
}


function AgentModal({ agent, onClose }: { agent: AgentState | null; onClose: () => void }) {
  const session = useFocusedStore((state) => state.session)
  const openPaperSet = useFocusedStore((state) => state.openPaperSet)
  if (!agent || !session) return null
  const perspective = session.perspectives.find((item) => item.id === agent.perspective_id)
  if (!perspective) return null
  const deliberation = session.deliberations[0]
  const archivedCycle = deliberation?.completion_history.find(
    (completion) =>
      completion.agent_iids.includes(agent.iid) ||
      completion.rounds.some((round) =>
        round.participant_iids.includes(agent.iid),
      ),
  )
  const leadPerspectiveId = archivedCycle
    ? archivedCycle.lead_perspective_id
    : deliberation?.lead_perspective_id
  const isLead = leadPerspectiveId === agent.perspective_id
  const displayedPerspective = isLead
    ? ((archivedCycle
        ? archivedCycle.revised_perspective
        : deliberation?.revised_perspective) ?? perspective)
    : perspective
  return (
    <ModalShell title={perspective.name} onClose={onClose}>
      <div className="mb-3">
        <SectionLabel>
          {isLead
            ? `Lead Perspective · Version ${agent.facet_version}`
            : archivedCycle
              ? "Archived Perspective"
              : "Current Perspective"}
        </SectionLabel>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {FACETS.map((facet) => {
          const evidence = agent.facets[facet]
          const baselineEvidence = perspective.facets[facet]
          return (
            <div key={facet} className="rounded-lg border border-[var(--line)] p-3">
              <div className="text-[11px] font-semibold" style={{ color: FACET_META[facet].color }}>
                {FACET_META[facet].label}
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                {evidence?.text ?? "Not established"}
              </p>
              {baselineEvidence?.text &&
                baselineEvidence.text !== evidence?.text && (
                  <p className="mt-2 text-[10px] leading-relaxed text-[var(--mute)]">
                    Started from: {baselineEvidence.text}
                  </p>
                )}
              {evidence?.paper_id && (
                <button
                  type="button"
                  onClick={() => openPaperSet(evidence.paper_id)}
                  className="mt-2 text-[10.5px] text-[var(--mute)] underline decoration-dotted underline-offset-2"
                >
                  View abstract evidence
                </button>
              )}
              {evidence?.edited && (
                <p className="mt-2 text-[10px] font-medium text-[var(--green)]">Revised through deliberation</p>
              )}
            </div>
          )
        })}
      </div>
      {displayedPerspective.framing && (
        <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-3">
          <div>
            <SectionLabel>Framing</SectionLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">{displayedPerspective.framing.framing}</p>
          </div>
          <div>
            <SectionLabel>Position</SectionLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">{displayedPerspective.framing.position}</p>
          </div>
        </div>
      )}
    </ModalShell>
  )
}


function SavedHypothesisModal({
  version,
  onClose,
}: {
  version: HypothesisVersion | null
  onClose: () => void
}) {
  if (!version) return null
  return (
    <ModalShell title={`Saved hypothesis ${version.id}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        {HYPOTHESIS_PARTS.map((part) => (
          <div
            key={part.key}
            className="rounded-lg border border-[var(--line)] px-3 py-2.5"
          >
            <SectionLabel>{part.label}</SectionLabel>
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--ink-2)]">
              {version.steps[part.key]}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-[var(--mute)]">
        Saved from round {version.source_round ?? "unknown"}
        {version.parent_ids.length
          ? ` · follows ${version.parent_ids.join(" + ")}`
          : " · first checkpoint"}
      </p>
    </ModalShell>
  )
}

function RefitOnNodes({ count }: { count: number }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    window.setTimeout(() => void fitView({ padding: 0.3, maxZoom: 1 }), 40)
  }, [count, fitView])
  return null
}

const HIDDEN_HANDLE: CSSProperties = {
  width: 1,
  height: 1,
  opacity: 0,
  border: 0,
}

function ProblemNode({ data }: NodeProps) {
  const { problem } = data as { problem: string }
  return (
    <div
      data-testid="root-research-problem-node"
      className="ep-node-enter panel px-4 py-3.5"
      style={{ width: 280 }}
    >
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} />
      <div className="text-[11px] font-medium text-[var(--mute)]">Research problem</div>
      <p className="mt-1 text-[13px] font-medium leading-relaxed">{problem}</p>
    </div>
  )
}

function AgentNode({ data }: NodeProps) {
  const { agentId, name, color, meta, onOpen } = data as {
    agentId: number
    name: string
    color: string
    meta: string
    onOpen: () => void
  }
  return (
    <button
      type="button"
      data-testid={`agent-node-${agentId}`}
      onClick={onOpen}
      className="ep-node-enter panel nodrag nopan block px-3.5 py-3 text-left"
      style={{ width: 280 }}
    >
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} />
      <div className="flex items-center gap-2">
        <span className="size-2 rounded-full" style={{ background: color }} />
        <span className="text-[13px] font-semibold" style={{ color }}>{name}</span>
      </div>
      <p className="mt-1.5 text-[11px] text-[var(--mute)]">{meta}</p>
    </button>
  )
}

function PanelNode({ id, data }: NodeProps) {
  const { members, status, canJoin, ended, onJoin } = data as {
    members: { id: number; name: string; color: string }[]
    status: string
    canJoin: boolean
    ended: boolean
    onJoin: () => void
  }
  return (
    <div
      data-testid={`panel-node-${id}`}
      className="ep-node-enter panel px-3.5 py-3"
      style={{ width: 280 }}
    >
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} />
      <div className="text-[13px] font-semibold tracking-[-0.01em]">Focused panel</div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
        {members.map((member) => (
          <span key={member.id} className="text-[11px]" style={{ color: member.color }}>
            {member.name}
          </span>
        ))}
        {!members.length && <span className="text-[11px] text-[var(--mute)]">No members yet</span>}
      </div>
      <div className="mt-1.5 text-[11px] font-medium text-[var(--mute)]">{status}</div>
      <div className="mt-2.5">
        <Button
          variant={ended ? "outline" : "primary"}
          size="sm"
          className="nodrag nopan w-full"
          disabled={!canJoin}
          onClick={(event) => {
            event.stopPropagation()
            onJoin()
          }}
        >
          {ended ? "Review" : "Join"}
        </Button>
      </div>
    </div>
  )
}


function HypothesisNode({ data }: NodeProps) {
  const { versionId, hypothesis, promoted, onOpen } = data as {
    versionId: string
    hypothesis: string
    promoted: boolean
    onOpen: () => void
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className="ep-node-enter panel nodrag nopan block w-[300px] px-4 py-3.5 text-left"
      style={{
        background: "var(--green-bg)",
        borderColor: "rgba(6, 118, 71, 0.28)",
      }}
      data-testid={`saved-hypothesis-node-${versionId}`}
    >
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10.5px] font-semibold text-[var(--green)]">
          Saved hypothesis · {versionId}
        </span>
        {promoted && (
          <span className="text-[9.5px] font-medium text-[var(--green)]">
            Promoted
          </span>
        )}
      </div>
      <p className="mt-1.5 line-clamp-4 text-[12px] font-medium leading-relaxed text-[var(--ink)]">
        {hypothesis}
      </p>
    </button>
  )
}

function ResearchProblemNode({ data }: NodeProps) {
  const { questionId, question, status, hasChild, actionable, busy, onOpen } =
    data as {
      questionId: string
      question: string
      status: QuestionStatus
      hasChild: boolean
      actionable: boolean
      busy: boolean
      onOpen: () => void
    }
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={busy || !actionable}
      className="ep-node-enter panel nodrag nopan block w-[300px] px-4 py-3.5 text-left disabled:opacity-60"
      data-testid={`research-problem-node-${questionId}`}
    >
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} />
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10.5px] font-medium text-[var(--mute)]">
          Research problem
        </span>
        <span className="text-[9.5px] font-medium capitalize text-[var(--ink-2)]">
          {status}
        </span>
      </div>
      <p className="mt-1.5 line-clamp-4 text-[12px] font-medium leading-relaxed text-[var(--ink)]">
        {question}
      </p>
      <div className="mt-2 text-[10.5px] text-[var(--mute)]">
        {hasChild
          ? "Open paper search"
          : actionable
            ? "Start paper search"
            : "No search linked"}
      </div>
    </button>
  )
}

const NODE_TYPES = {
  epProblem: ProblemNode,
  epAgent: AgentNode,
  epPanel: PanelNode,
  epHypothesis: HypothesisNode,
  epResearchProblem: ResearchProblemNode,
}
