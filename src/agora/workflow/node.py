import asyncio
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from agora.config.deliberation import DeliberationConfig
from agora.db.store import DeliberationStore
from agora.deliberation.document import DocumentCreation
from agora.deliberation.proposal import ProposalGenerator
from agora.deliberation.review import review_panel
from agora.deliberation.revision import refine_panel
from agora.schemas.deliberation import ProposalInput, ProposalResult
from agora.workflow.events import (
    DocumentInitialized,
    Event,
    EvidenceRetrieved,
    ProposalSelectionRequested,
    ProposalsGenerated,
    ProposalsRefined,
    ReviewsGenerated,
    ThreadOpened,
    WorkflowEvent,
    event_id,
)
from agora.workflow.state import WaitingFor, WorkflowStage, WorkflowState


class NodeContext(BaseModel):
    state: WorkflowState
    event: Event | None = None


class NodeResult(BaseModel):
    events: list[WorkflowEvent] = Field(default_factory=list)
    wait: bool = False
    waiting_for: WaitingFor | None = None


class Node(Protocol):
    id: str
    stage: WorkflowStage

    async def run(self, context: NodeContext) -> NodeResult:
        ...


class GenerateProposals:
    id = "generate_proposals"
    stage: WorkflowStage = "opening"

    def __init__(
        self,
        generator: ProposalGenerator,
        store: DeliberationStore,
        config: DeliberationConfig | None = None,
    ):
        self.generator = generator
        self.store = store
        self.config = config or DeliberationConfig()

    async def run(self, context: NodeContext) -> NodeResult:
        state = context.state
        proposal_context = await self.store.proposal_context(
            state.investigation_id
        )

        if not proposal_context.perspectives:
            raise ValueError(
                "Proposal generation requires selected Perspectives"
            )

        semaphore = asyncio.Semaphore(self.config.max_parallel)

        async def generate(item: ProposalInput) -> ProposalResult:
            peers = [
                other.profile.focus
                for other in proposal_context.perspectives
                if other.perspective_id != item.perspective_id
            ]

            async with semaphore:
                prediction = await self.generator.acall(
                    investigation_id=state.investigation_id,
                    corpus_id=proposal_context.corpus_id,
                    question=proposal_context.question,
                    item=item,
                    peers=peers,
                )
                return prediction.result

        proposals = await asyncio.gather(
            *[generate(item) for item in proposal_context.perspectives]
        )

        created_at = datetime.now(UTC)
        caused_by = context.event.id if context.event is not None else None
        events: list[WorkflowEvent] = []

        for item, result in zip(
            proposal_context.perspectives,
            proposals,
            strict=True,
        ):
            if result.snippet_ids:
                events.append(
                    EvidenceRetrieved(
                        id=event_id(
                            state.run_id,
                            "evidence_retrieved",
                            item.perspective_id,
                        ),
                        run_id=state.run_id,
                        investigation_id=state.investigation_id,
                        created_at=created_at,
                        caused_by=caused_by,
                        perspective_id=item.perspective_id,
                        query=item.profile.perspective.position,
                        snippet_ids=result.snippet_ids,
                    )
                )

        events.append(
            ProposalsGenerated(
                id=event_id(
                    state.run_id,
                    "proposals_generated",
                    state.investigation_id,
                ),
                run_id=state.run_id,
                investigation_id=state.investigation_id,
                created_at=created_at,
                caused_by=caused_by,
                proposal_ids=[result.proposal.id for result in proposals],
                perspective_ids=[
                    result.proposal.perspective_id for result in proposals
                ],
            )
        )

        await self.store.save_proposals(
            state.investigation_id,
            proposals=list(proposals),
            events=events,
            expected_version=proposal_context.deliberation_version,
        )

        return NodeResult(events=events)


class ReviewProposals:
    id = "review_proposals"
    stage: WorkflowStage = "opening"

    def __init__(
        self,
        store: DeliberationStore,
        config: DeliberationConfig | None = None,
    ):
        self.store = store
        self.config = config or DeliberationConfig()

    async def run(self, context: NodeContext) -> NodeResult:
        state = context.state
        proposal_context = await self.store.proposal_context(
            state.investigation_id
        )
        perspectives = {
            perspective.id: perspective
            for perspective in await self.store.perspectives(
                state.investigation_id
            )
        }
        proposals = await self.store.proposals(state.investigation_id)

        reviews = await review_panel(
            question=proposal_context.question,
            proposals=proposals,
            perspectives=perspectives,
            max_parallel=self.config.max_parallel,
        )

        events: list[WorkflowEvent] = [
            ReviewsGenerated(
                id=event_id(
                    state.run_id,
                    "reviews_generated",
                    state.investigation_id,
                ),
                run_id=state.run_id,
                investigation_id=state.investigation_id,
                created_at=datetime.now(UTC),
                caused_by=context.event.id if context.event else None,
                review_ids=[review.id for review in reviews],
            )
        ]

        await self.store.save_reviews(
            state.investigation_id,
            reviews=list(reviews),
            events=events,
            expected_version=proposal_context.deliberation_version,
        )

        return NodeResult(events=events)


class RefineProposals:
    id = "refine_proposals"
    stage: WorkflowStage = "opening"

    def __init__(
        self,
        store: DeliberationStore,
        config: DeliberationConfig | None = None,
    ):
        self.store = store
        self.config = config or DeliberationConfig()

    async def run(self, context: NodeContext) -> NodeResult:
        state = context.state
        proposal_context = await self.store.proposal_context(
            state.investigation_id
        )
        perspectives = {
            perspective.id: perspective
            for perspective in await self.store.perspectives(
                state.investigation_id
            )
        }
        proposals = await self.store.proposals(state.investigation_id)
        reviews = await self.store.reviews(state.investigation_id)

        refinements = await refine_panel(
            question=proposal_context.question,
            proposals=proposals,
            reviews=reviews,
            perspectives=perspectives,
            max_parallel=self.config.max_parallel,
        )

        events: list[WorkflowEvent] = [
            ProposalsRefined(
                id=event_id(
                    state.run_id,
                    "proposals_refined",
                    state.investigation_id,
                ),
                run_id=state.run_id,
                investigation_id=state.investigation_id,
                created_at=datetime.now(UTC),
                caused_by=context.event.id if context.event else None,
                refinement_ids=[
                    refinement.id for refinement in refinements
                ],
                proposal_ids=[
                    refinement.proposal.id for refinement in refinements
                ],
            )
        ]

        await self.store.save_refinements(
            state.investigation_id,
            refinements=list(refinements),
            events=events,
            expected_version=proposal_context.deliberation_version,
        )

        return NodeResult(events=events)


class RequestProposalSelection:
    id = "request_proposal_selection"
    stage: WorkflowStage = "selection"

    def __init__(self, store: DeliberationStore):
        self.store = store

    async def run(self, context: NodeContext) -> NodeResult:
        state = context.state
        proposals = await self.store.proposals(state.investigation_id)

        events: list[WorkflowEvent] = [
            ProposalSelectionRequested(
                id=event_id(
                    state.run_id,
                    "proposal_selection_requested",
                    state.investigation_id,
                ),
                run_id=state.run_id,
                investigation_id=state.investigation_id,
                created_at=datetime.now(UTC),
                caused_by=context.event.id if context.event else None,
                proposal_ids=[proposal.id for proposal in proposals],
            )
        ]

        await self.store.append_events(
            state.investigation_id,
            events=events,
            expected_version=self.store.deliberation_version(
                state.investigation_id
            ),
        )

        return NodeResult(
            events=events,
            wait=True,
            waiting_for="proposal_selection",
        )


class CreateDocument:
    id = "create_document"
    stage: WorkflowStage = "deliberation"

    def __init__(
        self,
        store: DeliberationStore,
        creation: DocumentCreation,
        *,
        title: str,
        n_threads: int = 3,
        created_by: str = "moderator",
    ):
        self.store = store
        self.creation = creation
        self.title = title
        self.n_threads = n_threads
        self.created_by = created_by

    async def run(self, context: NodeContext) -> NodeResult:
        state = context.state
        proposal_context = await self.store.proposal_context(
            state.investigation_id
        )
        refinements = await self.store.selected_refinements(
            state.investigation_id
        )
        created_at = datetime.now(UTC)
        document_id = f"{state.investigation_id}:document"

        prediction = await self.creation.acall(
            document_id=document_id,
            thread_ids=[
                f"{state.investigation_id}:thread:{i}"
                for i in range(1, self.n_threads + 1)
            ],
            investigation_id=state.investigation_id,
            title=self.title,
            question=proposal_context.question,
            refinements=refinements,
            created_by=self.created_by,
            created_at=created_at,
            n=self.n_threads,
        )
        document = prediction.document
        threads = prediction.threads

        caused_by = context.event.id if context.event else None
        events: list[WorkflowEvent] = [
            DocumentInitialized(
                id=event_id(
                    state.run_id,
                    "document_initialized",
                    document.id,
                ),
                run_id=state.run_id,
                investigation_id=state.investigation_id,
                created_at=created_at,
                caused_by=caused_by,
                document_id=document.id,
                thread_ids=[thread.id for thread in threads],
            ),
            ThreadOpened(
                id=event_id(
                    state.run_id,
                    "thread_opened",
                    threads[0].id,
                ),
                run_id=state.run_id,
                investigation_id=state.investigation_id,
                created_at=created_at,
                caused_by=caused_by,
                thread_id=threads[0].id,
            ),
        ]

        await self.store.save_document(
            state.investigation_id,
            document=document,
            threads=threads,
            events=events,
            expected_version=proposal_context.deliberation_version,
        )

        return NodeResult(events=events)
