from agora.workflow.events import Event
from agora.workflow.node import Node, NodeContext, NodeResult
from agora.workflow.state import WorkflowState


class Graph:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}

    def register(self, node: Node) -> None:
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node: {node.id}")

        self.nodes[node.id] = node

    def connect(self, source: str, target: str) -> None:
        if source not in self.nodes:
            raise ValueError(f"Unknown source node: {source}")

        if target not in self.nodes:
            raise ValueError(f"Unknown target node: {target}")

        if source in self.edges:
            raise ValueError(f"Node already has a successor: {source}")

        self.edges[source] = target

    async def run(
        self,
        state: WorkflowState,
        *,
        event: Event | None = None,
    ) -> tuple[WorkflowState, list[NodeResult]]:
        results: list[NodeResult] = []
        trigger = event

        while state.current_node is not None:
            node = self.nodes.get(state.current_node)

            if node is None:
                raise ValueError(f"Unknown current node: {state.current_node}")

            state = state.model_copy(
                update={
                    "stage": node.stage,
                    "status": "active",
                    "waiting_for": None,
                }
            )
            result = await node.run(NodeContext(state=state, event=trigger))
            results.append(result)

            if result.wait and result.waiting_for is None:
                raise ValueError(
                    f"Waiting node {node.id} did not state what it awaits"
                )

            if not result.wait and result.waiting_for is not None:
                raise ValueError(
                    f"Node {node.id} supplied waiting_for without waiting"
                )

            state = state.model_copy(
                update={
                    "current_node": self.edges.get(node.id),
                    "status": "waiting" if result.wait else "active",
                    "waiting_for": result.waiting_for if result.wait else None,
                    "version": state.version + 1,
                }
            )

            if result.events:
                trigger = result.events[-1]

            if result.wait or state.current_node is None:
                break

        return state, results
