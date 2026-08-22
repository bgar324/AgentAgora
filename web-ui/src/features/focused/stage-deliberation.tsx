"use client"

import { useEffect, useId, useMemo, useState, type CSSProperties } from "react"
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
  type DeliberationPoint,
  type DeliberationRound,
  type DeliberationState,
  type Facet,
  type FacetVerdict,
  type HypothesisDev,
  type RecommendedQuestion,
  type QuestionStatus,
  type Perspective,
  type Turn,
} from "@/types/focused"

import {
  Button,
  EmptyLine,
  IdentityChip,
  ListRow,
  ModalShell,
  SectionLabel,
  Spinner,
  useDialogSurface,
} from "./ui"

function distinctActiveQuestions(
  questions: RecommendedQuestion[],
): RecommendedQuestion[] {
  const selected = new Map<string, RecommendedQuestion>()
  questions
    .filter(
      (question) =>
        question.status === "open" || question.status === "investigating",
    )
    .forEach((question) => {
      const key = question.question
        .trim()
        .toLocaleLowerCase()
        .replace(/\s+/g, " ")
      const current = selected.get(key)
      if (!current || question.status === "investigating") {
        selected.set(key, question)
      }
    })
  return [...selected.values()]
}


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
  const busy = useFocusedStore((state) => state.busy)
  const [pickerOpen, setPickerOpen] = useState(() => {
    const current = useFocusedStore.getState().session
    return (
      current !== null &&
      current.agents.length === 0 &&
      current.perspectives.length > 0
    )
  })
  const [agentModal, setAgentModal] = useState<AgentState | null>(null)
  const [wireModal, setWireModal] = useState<DeliberationState | null>(null)
  const [hypModal, setHypModal] = useState<DeliberationState | null>(null)
  const [drawerId, setDrawerId] = useState<string | null>(null)

  const nodes = useMemo<RFNode[]>(() => {
    if (!session) return []
    const result: RFNode[] = [
      {
        id: "problem",
        type: "epProblem",
        position: { x: 0, y: 0 },
        draggable: false,
        data: { problem: session.problem },
      },
    ]

    session.agents.forEach((agent, index) => {
      const perspective = session.perspectives.find(
        (item) => item.id === agent.perspective_id,
      )
      result.push({
        id: `agent-${agent.iid}`,
        type: "epAgent",
        position: {
          x: 330,
          y: index * 175 - Math.max(0, session.agents.length - 1) * 87.5,
        },
        data: {
          name: perspective?.name ?? agent.label,
          color: perspective?.color ?? "var(--mute)",
          meta: `${perspective?.sources.length ?? 0} source${perspective?.sources.length === 1 ? "" : "s"}`,
          onOpen: () => setAgentModal(agent),
        },
      })
    })

    const deliberation = session.deliberations[0]
    if (deliberation) {
      const completed = deliberation.rounds.filter((round) => round.completed).length
      result.push({
        id: `panel-${deliberation.id}`,
        type: "epPanel",
        position: { x: 720, y: 0 },
        data: {
          members: deliberation.agent_iids.map((iid) => {
            const agent = session.agents.find((item) => item.iid === iid)
            const perspective = agent
              ? session.perspectives.find((item) => item.id === agent.perspective_id)
              : undefined
            return {
              id: iid,
              name: perspective?.name ?? agent?.label ?? "Perspective",
              color: perspective?.color ?? "var(--mute)",
            }
          }),
          status: completed
            ? `${completed} focused ${completed === 1 ? "round" : "rounds"}`
            : deliberation.agent_iids.length >= 2
              ? "Ready for a focused round"
              : "Needs two Perspectives",
          canJoin: deliberation.agent_iids.length >= 2,
          onJoin: () => setDrawerId(deliberation.id),
          onMembers: () => setWireModal(deliberation),
        },
      })

      if (deliberation.questions_generated || deliberation.hypothesis) {
        result.push({
          id: `out-${deliberation.id}`,
          type: "epOutput",
          position: { x: 1110, y: 0 },
          data: {
            hypothesis: deliberation.hypothesis_confirmed
              ? (deliberation.hypothesis?.hypothesis ?? null)
              : null,
            questions: distinctActiveQuestions(
              deliberation.recommended_questions,
            )
              .slice(-3)
              .map((item) => ({ id: item.id, text: item.question })),
            onHypothesis: () => setHypModal(deliberation),
            onQuestions: () => setDrawerId(deliberation.id),
          },
        })
      }
    }
    return result
  }, [session])

  const edges = useMemo<RFEdge[]>(() => {
    if (!session) return []
    const style = { stroke: "var(--wire)", strokeWidth: 1.25 }
    const markerEnd = {
      type: MarkerType.ArrowClosed,
      color: "var(--wire)",
      width: 12,
      height: 12,
    }
    const result: RFEdge[] = session.agents.map((agent) => ({
      id: `e-problem-${agent.iid}`,
      source: "problem",
      target: `agent-${agent.iid}`,
      style,
      markerEnd,
    }))
    const deliberation = session.deliberations[0]
    if (!deliberation) return result
    deliberation.agent_iids.forEach((iid) => {
      if (session.agents.some((agent) => agent.iid === iid)) {
        result.push({
          id: `e-${deliberation.id}-${iid}`,
          source: `agent-${iid}`,
          target: `panel-${deliberation.id}`,
          style,
          markerEnd,
        })
      }
    })
    if (deliberation.questions_generated || deliberation.hypothesis) {
      result.push({
        id: `e-out-${deliberation.id}`,
        source: `panel-${deliberation.id}`,
        target: `out-${deliberation.id}`,
        style,
        markerEnd,
      })
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
        <Panel position="top-left" className="!m-3 flex items-center gap-1.5">
          {session.perspectives.some(
            (perspective) =>
              !session.agents.some(
                (agent) => agent.perspective_id === perspective.id,
              ),
          ) && (
              <Button
                variant="outline"
                size="sm"
                disabled={!!busy}
                onClick={() => setPickerOpen(true)}
              >
                Add a Perspective
              </Button>
            )}
        </Panel>
      </ReactFlow>

      {drawerId && (
        <PanelDrawer
          deliberationId={drawerId}
          onClose={() => setDrawerId(null)}
          onOpenWire={setWireModal}
          onOpenAgent={setAgentModal}
        />
      )}
      {pickerOpen && (
        <PerspectivePicker onClose={() => setPickerOpen(false)} />
      )}
      <AgentModal agent={agentModal} onClose={() => setAgentModal(null)} />
      {wireModal && (
        <WireModal deliberation={wireModal} onClose={() => setWireModal(null)} />
      )}
      <HypothesisModal
        deliberation={hypModal}
        onClose={() => setHypModal(null)}
      />
    </div>
  )
}

function PanelDrawer({
  deliberationId,
  onClose,
  onOpenWire,
  onOpenAgent,
}: {
  deliberationId: string
  onClose: () => void
  onOpenWire: (deliberation: DeliberationState) => void
  onOpenAgent: (agent: AgentState) => void
}) {
  const session = useFocusedStore((state) => state.session)
  const busy = useFocusedStore((state) => state.busy)
  const {
    runRound,
    confirmHypothesis,
    createChildInvestigation,
    switchInvestigation,
    updateQuestionStatus,
    sendChat,
  } = useFocusedPanel()
  const [selectedFacets, setSelectedFacets] = useState<Facet[]>([])
  const [message, setMessage] = useState("")
  const [target, setTarget] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const drawerTitleId = useId()
  const drawerRef = useDialogSurface<HTMLElement>(onClose)
  const [hypothesisDraft, setHypothesisDraft] = useState<HypothesisDev | null>(
    () => {
      const current = useFocusedStore
        .getState()
        .session?.deliberations.find((item) => item.id === deliberationId)
      return current?.hypothesis ? { ...current.hypothesis } : null
    },
  )

  const active = session?.deliberations.find((item) => item.id === deliberationId)

  useEffect(() => {
    if (!session || !active) onClose()
  }, [session, active, onClose])


  if (!session || !active) return null
  const agents = active.agent_iids
    .map((iid) => session.agents.find((item) => item.iid === iid))
    .filter((item): item is AgentState => item !== undefined)
  const openerIid =
    agents.length > 0
      ? agents[active.rounds.length % agents.length].iid
      : null

  const perspectiveOf = (agent: AgentState): Perspective | undefined =>
    session.perspectives.find((item) => item.id === agent.perspective_id)

  const act = async (operation: () => Promise<unknown>) => {
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
      return current.length < 2 ? [...current, facet] : current
    })
  }

  const startRound = () => {
    if (openerIid == null || selectedFacets.length === 0) return
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

  const confirmDraft = async (): Promise<boolean> => {
    if (
      !hypothesisDraft ||
      Object.values(hypothesisDraft).some((part) => !part.trim())
    ) {
      setError("Complete all four hypothesis fields.")
      return false
    }
    const mode = active.hypothesis_confirmed
      ? "edit_applied"
      : "apply_pending"
    return (
      (await act(() =>
        confirmHypothesis(active.id, hypothesisDraft, mode),
      )) !== undefined
    )
  }


  const send = () => {
    const text = message.trim()
    if (!text) return
    setMessage("")
    void act(() => sendChat(active.id, text, target))
  }

  const runningRound = busy === "Running focused round"

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
            {active.rounds.filter((round) => round.completed).length} completed rounds
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
                <IdentityChip
                  key={agent.iid}
                  color={perspective?.color ?? "var(--ink-2)"}
                  name={perspective?.name ?? agent.label}
                  onClick={() => onOpenAgent(agent)}
                />
              )
            })}
            {agents.length < 2 && (
              <>
                <EmptyLine>Choose at least two Perspectives.</EmptyLine>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!!busy}
                  onClick={() => onOpenWire(active)}
                >
                  Members
                </Button>
              </>
            )}
          </div>


          <div className="mt-4 min-w-0">
            <div className="min-w-0">
              <div className="flex flex-col gap-5">
            {active.rounds.map((round) => (
              <RoundRecord key={round.n} round={round} />
            ))}
          </div>


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


          {(active.hypothesis === null || active.hypothesis_confirmed) && (
              <section
                className={`ep-card-enter rounded-xl border border-[var(--line)] bg-[var(--bg)] p-4 ${
                  active.rounds.length > 0 ? "mt-4" : ""
                }`}
              >
            <div className="flex items-start justify-between gap-4">
              <div>
                <SectionLabel>Round {active.rounds.length + 1}</SectionLabel>
                <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
                  Choose what this panel should focus on
                </h2>
                <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-[var(--mute)]">
                  Select one or two areas. Each guides its own evidence-grounded
                  discussion before the moderator produces one synthesis.
                </p>
              </div>
              <span className="shrink-0 rounded-full border border-[var(--line)] bg-[var(--panel)] px-2 py-1 text-[11px] text-[var(--mute)]">
                {selectedFacets.length}/2 selected
              </span>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              {FACETS.map((facet) => {
                const selected = selectedFacets.includes(facet)
                const unavailable = !selected && selectedFacets.length >= 2
                const meta = FACET_META[facet]
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
                  selectedFacets.length === 0
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
        {active.rounds.some((round) => round.completed) && (
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
              >
                <option value="all">Panel</option>
                {agents.map((agent) => (
                  <option key={agent.iid} value={agent.iid}>
                    {perspectiveOf(agent)?.name ?? agent.label}
                  </option>
                ))}
              </select>
              <input
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    send()
                  }
                }}
                className="field h-9 min-w-0 flex-1 px-3 text-[13px]"
                placeholder="Ask the panel about this round…"
                disabled={!!busy || agents.length === 0}
              />
              <Button
                variant="primary"
                size="sm"
                onClick={send}
                disabled={!!busy || !message.trim() || agents.length === 0}
              >
                {busy === "Deliberating" ? <Spinner /> : "Send"}
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
              busy={busy !== null}
              saving={busy === "Saving hypothesis"}
              onChange={setHypothesisDraft}
              onApply={confirmDraft}
              onCreateChild={(questionId) =>
                act(() => createChildInvestigation(questionId))
              }
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

function RoundRecord({ round }: { round: DeliberationRound }) {
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

      <div className="flex flex-col gap-2.5">
        {round.turns.map((turn) => (
          <TurnBubble key={turn.id} turn={turn} />
        ))}
      </div>

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
                  <span className="text-[10.5px] font-semibold" style={{ color: meta.color }}>
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

      {round.resolution && <ResolutionCard resolution={round.resolution} />}

      {round.reflections.some((item) => item.decision === "revised") && (
        <div className="mt-3 rounded-lg border border-[var(--line)] px-3 py-2.5">
          <SectionLabel>Perspective updates</SectionLabel>
          <div className="mt-1 flex flex-col gap-1.5">
            {round.reflections
              .filter((item) => item.decision === "revised")
              .map((item) => (
                <div key={item.agent_iid} className="text-[11px] leading-relaxed">
                  <span className="font-semibold text-[var(--ink)]">
                    {item.perspective_name}
                  </span>{" "}
                  <span className="text-[var(--mute)]">{item.reason}</span>
                </div>
              ))}
          </div>
        </div>
      )}

    </section>
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
    <div className="mt-3 rounded-xl border border-[var(--line)] bg-[var(--bg)] p-3.5">
      <SectionLabel>Moderator synthesis</SectionLabel>
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
    </div>
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

function WorkingHypothesisPanel({
  deliberation,
  value,
  busy,
  saving,
  onChange,
  onApply,
  onCreateChild,
  onOpenChild,
  onSetQuestionStatus,
}: {
  deliberation: DeliberationState
  value: HypothesisDev | null
  busy: boolean
  saving: boolean
  onChange: (value: HypothesisDev) => void
  onApply: () => Promise<boolean>
  onCreateChild: (questionId: string) => void
  onOpenChild: (investigationId: string) => void
  onSetQuestionStatus: (
    questionId: string,
    status: QuestionStatus,
  ) => void
}) {
  const visibleQuestions = deliberation.recommended_questions
  const current: HypothesisDev = value ?? {
    problem: "",
    previous_work: "",
    reasoning: "",
    hypothesis: "",
  }
  const pending = value !== null && !deliberation.hypothesis_confirmed
  const [editing, setEditing] = useState(false)

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
            style={{ color: pending ? "var(--amber)" : "var(--green)" }}
          >
            {pending ? "Update ready" : "Applied"}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-col gap-2.5">
        {HYPOTHESIS_PARTS.map((part, index) => (
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
            </div>
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
                  current[part.key] ? "text-[var(--ink-2)]" : "text-[var(--mute)]"
                }`}
              >
                {current[part.key] || "Not established yet."}
              </div>
            )}
          </div>
        ))}
      </div>

      {value ? (
        <div className="mt-3 border-t border-[var(--line)] pt-3">
          {pending && (
            <p className="mb-2 text-[10.5px] leading-relaxed text-[var(--ink-2)]">
              The latest round proposed changes from supported shared ground
              only. Review or edit them before applying.
            </p>
          )}
          <div className="flex gap-2">
            {!editing && (
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
            {(pending || editing) && (
              <Button
                variant={pending ? "primary" : "outline"}
                size="sm"
                className="flex-1"
                onClick={() => {
                  void onApply().then((saved) => {
                    if (saved) setEditing(false)
                  })
                }}
                disabled={busy}
              >
                {saving ? (
                  <>
                    <Spinner /> Saving…
                  </>
                ) : pending ? (
                  "Apply shared ground"
                ) : (
                  "Save edits"
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
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() => onCreateChild(item.id)}
                        >
                          Start child Investigation
                        </Button>
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
    </aside>
  )
}

function TurnBubble({ turn }: { turn: Turn }) {
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
        <p
          className={`text-[12.5px] leading-relaxed ${
            isUser ? "text-white" : "text-[var(--ink)]"
          }`}
        >
          {turn.text}
        </p>
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

function PerspectivePicker({ onClose }: { onClose: () => void }) {
  const session = useFocusedStore((state) => state.session)
  const busy = useFocusedStore((state) => state.busy)
  const { addAgent, createDeliberation, wireAgents } = useFocusedPanel()
  const [selected, setSelected] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  if (!session) return null
  const placed = new Set(session.agents.map((agent) => agent.perspective_id))
  const available = session.perspectives.filter((perspective) => !placed.has(perspective.id))
  const total = session.agents.length + selected.length

  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    )
  }

  const continueToPanel = async () => {
    if (total < 2) return
    setError(null)
    try {
      let current = useFocusedStore.getState().session
      if (!current?.deliberations.length) {
        current = await createDeliberation()
      }
      for (const perspectiveId of selected) {
        current = await addAgent(perspectiveId)
      }
      const latest = useFocusedStore.getState().session ?? current
      const deliberation = latest?.deliberations[0]
      if (latest && deliberation) {
        await wireAgents(
          deliberation.id,
          latest.agents.map((agent) => agent.iid),
        )
      }
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not place Perspectives")
    }
  }

  return (
    <ModalShell title="Choose the focused panel" onClose={onClose}>
      <div className="flex flex-col gap-1">
        {available.map((perspective) => {
          const active = selected.includes(perspective.id)
          return (
            <ListRow key={perspective.id} onClick={() => toggle(perspective.id)}>
              <span className="size-2 rounded-full" style={{ background: perspective.color }} />
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-semibold">{perspective.name}</span>
                <span className="block truncate text-[11px] text-[var(--mute)]">{perspective.summary}</span>
              </span>
              <span className="text-[11px] font-medium" style={{ color: active ? "var(--green)" : "var(--mute)" }}>
                {active ? "Selected" : "Add"}
              </span>
            </ListRow>
          )
        })}
        {!available.length && <EmptyLine>Every Perspective is already on the canvas.</EmptyLine>}
      </div>
      {error && <p className="mt-3 text-[12px] text-[var(--red)]">{error}</p>}
      <div className="mt-4 flex items-center justify-between">
        <span className="text-[11px] text-[var(--mute)]">{total} panel members</span>
        <Button
          variant="primary"
          size="sm"
          disabled={!!busy || total < 2}
          onClick={() => void continueToPanel()}
        >
          {busy ? <><Spinner /> Seating…</> : "Continue to panel"}
        </Button>
      </div>
    </ModalShell>
  )
}

function AgentModal({ agent, onClose }: { agent: AgentState | null; onClose: () => void }) {
  const session = useFocusedStore((state) => state.session)
  const openPaperSet = useFocusedStore((state) => state.openPaperSet)
  if (!agent || !session) return null
  const perspective = session.perspectives.find((item) => item.id === agent.perspective_id)
  if (!perspective) return null
  return (
    <ModalShell title={perspective.name} onClose={onClose}>
      <div className="mb-3">
        <SectionLabel>Current Perspective</SectionLabel>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {FACETS.map((facet) => {
          const evidence = agent.facets[facet]
          return (
            <div key={facet} className="rounded-lg border border-[var(--line)] p-3">
              <div className="text-[11px] font-semibold" style={{ color: FACET_META[facet].color }}>
                {FACET_META[facet].label}
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">
                {evidence?.text ?? "Not established"}
              </p>
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
      {perspective.framing && (
        <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-3">
          <div>
            <SectionLabel>Framing</SectionLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">{perspective.framing.framing}</p>
          </div>
          <div>
            <SectionLabel>Position</SectionLabel>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-2)]">{perspective.framing.position}</p>
          </div>
        </div>
      )}
    </ModalShell>
  )
}

function WireModal({ deliberation, onClose }: { deliberation: DeliberationState; onClose: () => void }) {
  const session = useFocusedStore((state) => state.session)
  const busy = useFocusedStore((state) => state.busy)
  const { wireAgents } = useFocusedPanel()
  const [selected, setSelected] = useState<number[]>(deliberation.agent_iids)
  const [error, setError] = useState<string | null>(null)
  if (!session) return null
  const locked = deliberation.rounds.length > 0

  const save = async () => {
    setError(null)
    try {
      await wireAgents(deliberation.id, selected)
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update panel")
    }
  }

  return (
    <ModalShell title="Panel members" onClose={onClose}>
      {locked && (
        <p className="mb-3 text-[12px] text-[var(--mute)]">
          Membership is locked because a focused round has started.
        </p>
      )}
      <div className="flex flex-col gap-1">
        {session.agents.map((agent) => {
          const perspective = session.perspectives.find((item) => item.id === agent.perspective_id)
          const active = selected.includes(agent.iid)
          return (
            <ListRow
              key={agent.iid}
              disabled={locked}
              onClick={() =>
                setSelected((current) =>
                  active
                    ? current.filter((iid) => iid !== agent.iid)
                    : [...current, agent.iid],
                )
              }
            >
              <span className="size-2 rounded-full" style={{ background: perspective?.color ?? "var(--mute)" }} />
              <span className="flex-1 text-[13px] font-medium">{perspective?.name ?? agent.label}</span>
              <span className="text-[11px] text-[var(--mute)]">{active ? "Seated" : "Available"}</span>
            </ListRow>
          )
        })}
      </div>
      {error && <p className="mt-3 text-[12px] text-[var(--red)]">{error}</p>}
      {!locked && (
        <div className="mt-4 flex justify-end">
          <Button variant="primary" size="sm" disabled={!!busy || selected.length < 2} onClick={() => void save()}>
            Save members
          </Button>
        </div>
      )}
    </ModalShell>
  )
}

function HypothesisModal({ deliberation, onClose }: { deliberation: DeliberationState | null; onClose: () => void }) {
  if (!deliberation?.hypothesis) return null
  return (
    <ModalShell title="How the hypothesis was developed" onClose={onClose}>
      <div className="flex flex-col gap-3">
        {HYPOTHESIS_PARTS.map((part) => (
          <div key={part.key} className="rounded-lg border border-[var(--line)] px-3 py-2.5">
            <SectionLabel>{part.label}</SectionLabel>
            <p className="mt-1 text-[13px] leading-relaxed text-[var(--ink-2)]">
              {deliberation.hypothesis?.[part.key]}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-[var(--mute)]">
        This record is generated only from the moderator’s supported consensus
        points. Disagreement and unsettled points remain in the next-question record.
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
    <div className="ep-node-enter panel px-4 py-3.5" style={{ width: 280 }}>
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} />
      <div className="text-[11px] font-medium text-[var(--mute)]">Research problem</div>
      <p className="mt-1 text-[13px] font-medium leading-relaxed">{problem}</p>
    </div>
  )
}

function AgentNode({ data }: NodeProps) {
  const { name, color, meta, onOpen } = data as {
    name: string
    color: string
    meta: string
    onOpen: () => void
  }
  return (
    <button
      type="button"
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

function PanelNode({ data }: NodeProps) {
  const { members, status, canJoin, onJoin, onMembers } = data as {
    members: { id: number; name: string; color: string }[]
    status: string
    canJoin: boolean
    onJoin: () => void
    onMembers: () => void
  }
  return (
    <div className="ep-node-enter panel px-3.5 py-3" style={{ width: 280 }}>
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
      <div className="mt-2.5 flex gap-1.5">
        <Button
          variant="primary"
          size="sm"
          className="nodrag nopan flex-1"
          disabled={!canJoin}
          onClick={(event) => {
            event.stopPropagation()
            onJoin()
          }}
        >
          Join
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="nodrag nopan"
          onClick={(event) => {
            event.stopPropagation()
            onMembers()
          }}
        >
          Members
        </Button>
      </div>
    </div>
  )
}

function OutputNode({ data }: NodeProps) {
  const { hypothesis, questions, onHypothesis, onQuestions } = data as {
    hypothesis: string | null
    questions: { id: string; text: string }[]
    onHypothesis: () => void
    onQuestions: () => void
  }
  return (
    <div className="ep-node-enter" style={{ width: 300 }}>
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} />
      {hypothesis && (
        <button
          type="button"
          className="mb-3 block w-full rounded-xl px-4 py-3.5 text-left text-white"
          style={{ background: "var(--node)" }}
          onClick={onHypothesis}
        >
          <div className="text-[11px] text-[var(--on-node)]">Shared-ground hypothesis</div>
          <div className="mt-1 text-[13px] font-medium leading-[1.5]">{hypothesis}</div>
        </button>
      )}
      {questions.length > 0 && (
        <button
          type="button"
          className="block w-full rounded-xl px-4 py-3.5 text-left text-white"
          style={{ background: "var(--node)" }}
          onClick={onQuestions}
        >
          <div className="text-[11px] text-[var(--on-node)]">Next research questions</div>
          <ul className="mt-1 list-disc pl-4 text-[12px] leading-snug">
            {questions.map((question) => (
              <li key={question.id}>{question.text}</li>
            ))}
          </ul>
          <div className="mt-1.5 text-[11px] text-[var(--on-node-accent)]">Review rationale</div>
        </button>
      )}
    </div>
  )
}

const NODE_TYPES = {
  epProblem: ProblemNode,
  epAgent: AgentNode,
  epPanel: PanelNode,
  epOutput: OutputNode,
}
