# ruff: noqa: I001
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import numpy as _numpy  # noqa: F401 — load before dspy's lazy numpy alias
import dspy

from agora.config.deliberation import DeliberationConfig
from agora.core.errors import Conflict, NotFound
from agora.config.settings import PhaseModel, Settings
from agora.db.store import (
    SqliteDeliberationStore,
    investigation as investigation_row,
    load_workflow_state,
    register_investigation,
    register_perspectives,
    save_workflow_state,
    update_investigation,
)
from agora.db.vector import SnippetIndex, embed_snippets, index_corpus
from agora.deliberation.document import (
    DocumentCreation,
    DraftSection,
    apply_draft,
    apply_suggestion,
    draft_section,
    open_thread,
    renumber_markers,
)
from agora.deliberation.proposal import ProposalGenerator
from agora.deliberation.resolution import (
    SuggestDocumentChange,
    SummarizeThread,
    affected_perspectives,
    decide_resolution,
    resolution_text,
    suggest_document_change,
    summarize_thread,
)
from agora.deliberation.revision import reflect_perspectives
from agora.deliberation.thread import (
    AnswerThread,
    AssignQuestions,
    PolishUtterance,
    ReplyToThread,
    SuggestThread,
    UpdateThreadResponse,
    answer_thread,
    assign_thread,
    contribution_lines,
    perspective_catalogue,
    reply_to_thread,
    thread_text,
    unique_threads,
    update_thread_response,
)
from agora.panel.perspective import (
    PerspectiveFormation,
    ResearchSynthesis,
    form_profiles,
)
from agora.research.cluster import project
from agora.research.corpus import build_corpus
from agora.research.discovery import ResearchDiscovery, distinct_directions
from agora.research.evidence import (
    EvidenceSearch,
    merge_observations,
    observations_by_id,
    text_citations,
)
from agora.research.model import LiteratureModel
from agora.research.rerank import rerank
from agora.research.search import (
    LiteratureSearch,
    RetrievalProgress,
    retrieval_progress_message,
)
from agora.schemas.api import EventEnvelope
from agora.schemas.deliberation import Contribution, Resolution, Suggestion, Thread
from agora.schemas.research import (
    ClusteredLiterature,
    PaperCorpus,
    ResearchDirection,
    ResearchIdea,
    SearchPlan,
)
from agora.workflow.decisions import (
    ProposalSelection,
    SuggestionDecision,
    ThreadDecision,
    VersionRef,
)
from agora.workflow.events import (
    ContributionAdded,
    DocumentRevised,
    EvidenceRequested,
    EvidenceRetrieved,
    ParticipantsAssigned,
    ResolutionProposed,
    ResolutionRequested,
    SuggestionCreated,
    SuggestionDecided,
    ThreadClosed,
    ThreadCreated,
    ThreadOpened,
    WorkflowEvent,
    event_id,
)
from agora.workflow.graph import Graph
from agora.workflow.node import (
    CreateDocument,
    GenerateProposals,
    RefineProposals,
    RequestProposalSelection,
    ReviewProposals,
)
from agora.workflow.router import route
from agora.workflow.state import Work, WorkflowState

logger = logging.getLogger("agora.runner")

RESEARCHER = "researcher"
MODERATOR = "moderator"

PUBLIC_EVENT_TYPES = {
    "proposals_selected": "investigation.updated",
    "document_initialized": "document.revised",
    "thread_created": "thread.created",
    "thread_opened": "thread.created",
    "contribution_added": "contribution.created",
    "evidence_retrieved": "evidence.retrieved",
    "resolution_proposed": "resolution.proposed",
    "thread_closed": "investigation.updated",
    "suggestion_created": "suggestion.created",
    "suggestion_decided": "investigation.updated",
    "document_revised": "document.revised",
    "investigation.updated": "investigation.updated",
    "brief.ready": "brief.ready",
    "perspectives.ready": "perspectives.ready",
    "retrieval.progress": "retrieval.progress",
    "proposals.ready": "proposals.ready",
    "workflow.waiting": "workflow.waiting",
    "workflow.failed": "workflow.failed",
}

PRIVATE_EVENT_FIELDS = {
    "id",
    "run_id",
    "investigation_id",
    "kind",
    "caused_by",
    "created_at",
}


def now() -> datetime:
    return datetime.now(UTC)


class Runner:
    def __init__(self, *, db, settings: Settings, embedder, s2_client):
        self.db = db
        self.store = SqliteDeliberationStore(db)
        self.settings = settings
        self.embedder = embedder
        self.s2 = s2_client
        self.config = DeliberationConfig()
        self.index = SnippetIndex(db, embedder)
        self.evidence_search = EvidenceSearch(self.index, self.config)
        self.tasks: dict[str, asyncio.Task] = {}
        self.queues: dict[str, set[asyncio.Queue]] = {}
        self.pending_evidence: dict[str, object] = {}
        self.lms = {
            "brief": self._lm(settings.models.brief),
            "panel": self._lm(settings.models.panel),
            "deliberation": self._lm(settings.models.deliberation),
        }

    @staticmethod
    def _lm(phase: PhaseModel) -> dspy.LM:
        return dspy.LM(
            phase.model,
            temperature=phase.temperature,
            max_tokens=phase.max_tokens,
        )

    async def shutdown(self) -> None:
        for task in list(self.tasks.values()):
            task.cancel()

        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()

    def busy(self, investigation_id: str) -> bool:
        task = self.tasks.get(investigation_id)
        return task is not None and not task.done()

    def _spawn(self, investigation_id: str, job: Awaitable) -> None:
        if self.busy(investigation_id):
            job.close()
            raise Conflict("busy", "Another operation is already running")

        task = asyncio.create_task(self._guard(investigation_id, job))
        self.tasks[investigation_id] = task

    async def _guard(self, investigation_id: str, job: Awaitable) -> None:
        try:
            await job
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("background job failed: %s", investigation_id)
            self._transition(investigation_id, status="failed")
            self.emit(investigation_id, "workflow.failed", {"error": str(error)})
        finally:
            self.tasks.pop(investigation_id, None)

    def investigation(self, investigation_id: str):
        row = investigation_row(self.db, investigation_id)

        if row is None:
            raise NotFound(f"Unknown investigation: {investigation_id}")

        return row

    def require_version(self, investigation_id: str, version: int) -> None:
        row = self.investigation(investigation_id)

        if row["version"] != version:
            raise Conflict(
                "stale_version",
                "The investigation changed after this view was loaded",
            )

    def _transition(self, investigation_id: str, **fields) -> None:
        row = self.investigation(investigation_id)
        update_investigation(
            self.db,
            investigation_id,
            version=row["version"] + 1,
            **fields,
        )

    def _dir(self, investigation_id: str):
        directory = self.settings.server.data_dir / investigation_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def emit(self, investigation_id: str, type_: str, data: dict) -> None:
        created_at = now().isoformat()

        with self.db:
            cursor = self.db.execute(
                "insert into events"
                " (event_id, investigation_id, kind, payload, created_at)"
                " values (?,?,?,?,?)",
                (
                    f"api:{uuid4().hex}",
                    investigation_id,
                    type_,
                    json.dumps(data),
                    created_at,
                ),
            )

        self._push(
            investigation_id,
            EventEnvelope(
                id=str(cursor.lastrowid),
                type=type_,
                investigation_id=investigation_id,
                created_at=created_at,
                data=data,
            ),
        )

    def _publish(
        self,
        investigation_id: str,
        events: Sequence[WorkflowEvent],
    ) -> None:
        for event in events:
            row = self.db.execute(
                "select rowid, created_at from events where event_id = ?",
                (event.id,),
            ).fetchone()

            if row is None:
                continue

            envelope = self._envelope(
                rowid=row["rowid"],
                kind=event.kind,
                payload=event.model_dump(mode="json"),
                created_at=row["created_at"] or event.created_at.isoformat(),
                investigation_id=investigation_id,
            )

            if envelope is not None:
                self._push(investigation_id, envelope)

    def _envelope(
        self,
        *,
        rowid: int,
        kind: str,
        payload: dict,
        created_at: str,
        investigation_id: str,
    ) -> EventEnvelope | None:
        type_ = PUBLIC_EVENT_TYPES.get(kind)

        if type_ is None:
            return None

        data = {
            key: value
            for key, value in payload.items()
            if key not in PRIVATE_EVENT_FIELDS
        }

        return EventEnvelope(
            id=str(rowid),
            type=type_,
            investigation_id=investigation_id,
            created_at=created_at,
            data=data,
        )

    def events_since(
        self,
        investigation_id: str,
        after: int = 0,
    ) -> list[EventEnvelope]:
        envelopes = []

        for row in self.store.events_after(investigation_id, after):
            envelope = self._envelope(
                rowid=row["rowid"],
                kind=row["kind"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
                investigation_id=investigation_id,
            )

            if envelope is not None:
                envelopes.append(envelope)

        return envelopes

    def _push(self, investigation_id: str, envelope: EventEnvelope) -> None:
        for queue in self.queues.get(investigation_id, set()):
            queue.put_nowait(envelope)

    def open_queue(self, investigation_id: str) -> asyncio.Queue:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        self.queues.setdefault(investigation_id, set()).add(queue)

        return queue

    def close_queue(
        self,
        investigation_id: str,
        queue: asyncio.Queue,
    ) -> None:
        subscribers = self.queues.get(investigation_id, set())
        subscribers.discard(queue)

        if not subscribers:
            self.queues.pop(investigation_id, None)

    def _run_id(self, investigation_id: str) -> str:
        return f"{investigation_id}:api"

    def _load_state(self, investigation_id: str) -> WorkflowState | None:
        payload = load_workflow_state(self.db, investigation_id)
        return WorkflowState.model_validate_json(payload) if payload else None

    def _record_state(self, state: WorkflowState) -> None:
        self._save_state(state)
        self._transition(
            state.investigation_id,
            stage=state.stage,
            status=state.status,
            waiting_for=state.waiting_for,
            active_thread_id=state.active_thread_id,
            document_version=state.document_version,
        )

    def _save_state(self, state: WorkflowState) -> None:
        save_workflow_state(
            self.db,
            state.investigation_id,
            state.model_dump_json(),
        )

    def _question(self, investigation_id: str) -> str:
        row = self.investigation(investigation_id)
        return row["question"] or ""

    def _literature_search(self, investigation_id: str) -> LiteratureSearch:
        async def progress(update: RetrievalProgress) -> None:
            payload = asdict(update)
            if message := retrieval_progress_message(update):
                payload["message"] = message
            self.emit(investigation_id, "retrieval.progress", payload)

        return LiteratureSearch(self.s2, progress=progress)

    def start_brief(self, investigation_id: str, *, idea: str, n: int) -> None:
        self._spawn(
            investigation_id,
            self._run_brief(investigation_id, idea, n),
        )

    async def _run_brief(self, investigation_id: str, idea: str, n: int) -> None:
        self._transition(investigation_id, status="active")
        literature_search = self._literature_search(investigation_id)
        discovery = ResearchDiscovery(literature_search)

        with dspy.context(lm=self.lms["brief"]):
            prediction = await discovery.acall(idea=ResearchIdea(idea=idea), n=n)

        plan: SearchPlan = prediction.search_plan
        directory = self._dir(investigation_id)
        (directory / "search_plan.json").write_text(
            plan.model_dump_json(indent=2)
        )

        self._transition(
            investigation_id,
            title=plan.research_question.title,
            question=plan.research_question.main_question,
            stage="perspectives",
            status="active",
        )
        self.emit(
            investigation_id,
            "brief.ready",
            {
                "title": plan.research_question.title,
                "research_question": plan.research_question.main_question,
            },
        )

    def update_brief(
        self,
        investigation_id: str,
        *,
        version: int,
        title: str | None,
        research_question: str | None,
        research_directions: list[ResearchDirection] | None,
    ) -> None:
        self.require_version(investigation_id, version)
        directory = self._dir(investigation_id)
        plan_path = directory / "search_plan.json"
        fields = {}

        if title is not None:
            fields["title"] = " ".join(title.split())

        if research_question is not None:
            fields["question"] = " ".join(research_question.split())
        if research_directions is not None and not plan_path.exists():
            raise Conflict("wrong_stage", "The Investigation has no search plan yet")
        directions: list[ResearchDirection] = []

        changed = bool(fields) or research_directions is not None
        if plan_path.exists() and changed:
            plan = SearchPlan.model_validate_json(plan_path.read_text())
            question = plan.research_question.model_copy(
                update={
                    key: value
                    for key, value in (
                        ("title", fields.get("title")),
                        ("main_question", fields.get("question")),
                    )
                    if value is not None
                }
            )
            directions = plan.research_directions
            if research_directions is not None:
                try:
                    directions = (
                        distinct_directions(
                            research_directions,
                            seeds=plan.retrieval_seeds,
                            n=len(research_directions),
                        )
                        if research_directions
                        else []
                    )
                except ValueError as error:
                    raise Conflict(
                        "invalid_directions",
                        str(error),
                    ) from error
            plan = plan.model_copy(
                update={
                    "research_question": question,
                    "research_directions": directions,
                }
            )
            plan_path.write_text(plan.model_dump_json(indent=2))

        if changed:
            self._transition(investigation_id, **fields)
            payload = dict(fields)
            if research_directions is not None:
                payload["research_directions"] = [
                    item.model_dump(mode="json") for item in directions
                ]
            self.emit(investigation_id, "investigation.updated", payload)

    def start_perspectives(self, investigation_id: str, *, n: int) -> None:
        directory = self._dir(investigation_id)

        if not (directory / "search_plan.json").exists():
            raise Conflict("wrong_stage", "The Investigation has no brief yet")

        self._spawn(
            investigation_id,
            self._run_perspectives(investigation_id, n),
        )

    async def _run_perspectives(self, investigation_id: str, n: int) -> None:
        self._transition(investigation_id, status="active", waiting_for=None)
        directory = self._dir(investigation_id)
        plan = SearchPlan.model_validate_json(
            (directory / "search_plan.json").read_text()
        )
        corpus_path = directory / "corpus.json"

        if corpus_path.exists():
            corpus = PaperCorpus.model_validate_json(corpus_path.read_text())
        else:
            literature_search = self._literature_search(investigation_id)
            result = await literature_search.search(
                corpus_id=f"corpus_{investigation_id}",
                investigation_id=investigation_id,
                plan=plan,
            )
            corpus = result.corpus
            corpus_path.write_text(corpus.model_dump_json())

        model = LiteratureModel()
        literature = model.fit(corpus.papers)
        kept = sorted(
            literature.clusters,
            key=lambda cluster: len(cluster.source_ids),
            reverse=True,
        )[:n]
        literature = ClusteredLiterature(
            clusters=kept,
            unassigned_source_ids=literature.unassigned_source_ids,
        )
        (directory / "clusters.json").write_text(literature.model_dump_json())

        embeddable = build_corpus(corpus.papers)
        planar = project(embeddable.X, n_components=2)
        coordinates = {
            source_id: [float(point[0]), float(point[1])]
            for source_id, point in zip(
                embeddable.source_ids,
                planar,
                strict=True,
            )
        }
        (directory / "map.json").write_text(json.dumps(coordinates))

        question = plan.research_question.main_question

        with dspy.context(lm=self.lms["panel"]):
            profiles = await form_profiles(
                question=question,
                literature=literature,
                formation=PerspectiveFormation(),
                synthesis=ResearchSynthesis(),
            )

        (directory / "panel.json").write_text(
            json.dumps(
                {key: value.model_dump() for key, value in profiles.items()}
            )
        )

        centroids = {}

        for cluster in literature.clusters:
            points = [
                coordinates[source_id]
                for source_id in cluster.source_ids
                if source_id in coordinates
            ]

            if points:
                centroids[cluster.id] = (
                    sum(point[0] for point in points) / len(points),
                    sum(point[1] for point in points) / len(points),
                )

        register_investigation(
            self.db,
            investigation_id=investigation_id,
            corpus_id=corpus.id,
            question=question,
        )
        index_corpus(self.db, corpus)
        await embed_snippets(self.db, embed=self.embedder)
        register_perspectives(
            self.db,
            investigation_id=investigation_id,
            panel=profiles,
            literature=literature,
            map_positions=centroids,
        )

        self._transition(
            investigation_id,
            stage="ready",
            status="waiting",
            waiting_for="perspective_selection",
        )
        self.emit(
            investigation_id,
            "perspectives.ready",
            {
                "count": sum(
                    1 for result in profiles.values() if result.profile
                )
            },
        )
        self.emit(
            investigation_id,
            "workflow.waiting",
            {"waiting_for": "perspective_selection"},
        )

    def select_perspectives(
        self,
        investigation_id: str,
        *,
        perspective_ids: Sequence[str],
        version: int,
    ) -> None:
        self.require_version(investigation_id, version)

        if self.busy(investigation_id):
            raise Conflict("busy", "Another operation is already running")

        known = {
            row["perspective_id"]
            for row in self.store.perspective_summaries(investigation_id)
        }
        missing = [pid for pid in perspective_ids if pid not in known]

        if missing:
            raise NotFound(f"Unknown perspectives: {missing}")

        if len(perspective_ids) < 2:
            raise Conflict(
                "invalid_selection",
                "Deliberation requires at least two Perspectives",
            )

        self.store.set_perspective_selection(investigation_id, perspective_ids)
        self._transition(investigation_id, status="active", waiting_for=None)
        self.emit(
            investigation_id,
            "investigation.updated",
            {"selected_perspectives": list(perspective_ids)},
        )

    def _graph(self, title: str) -> Graph:
        generator = ProposalGenerator(self.evidence_search)
        graph = Graph()

        for node in (
            GenerateProposals(generator, self.store, self.config),
            ReviewProposals(self.store, self.config),
            RefineProposals(self.store, self.config),
            RequestProposalSelection(self.store),
            CreateDocument(
                self.store,
                DocumentCreation(),
                title=title,
                n_threads=3,
                created_by=MODERATOR,
            ),
        ):
            graph.register(node)

        graph.connect("generate_proposals", "review_proposals")
        graph.connect("review_proposals", "refine_proposals")
        graph.connect("refine_proposals", "request_proposal_selection")
        graph.connect("request_proposal_selection", "create_document")

        return graph

    def start_deliberation(self, investigation_id: str, *, version: int) -> None:
        self.require_version(investigation_id, version)
        row = self.investigation(investigation_id)

        if row["stage"] != "ready":
            raise Conflict(
                "wrong_stage",
                "Deliberation requires formed and selected Perspectives",
            )

        self._spawn(investigation_id, self._run_deliberation(investigation_id))

    async def _run_deliberation(self, investigation_id: str) -> None:
        row = self.investigation(investigation_id)
        state = WorkflowState(
            run_id=self._run_id(investigation_id),
            investigation_id=investigation_id,
            status="active",
            stage="opening",
            current_node="generate_proposals",
        )
        self._record_state(state)
        graph = self._graph(row["title"] or "Investigation")

        with dspy.context(lm=self.lms["deliberation"]):
            state, results = await graph.run(state)

        self._record_state(state)

        for result in results:
            self._publish(investigation_id, result.events)

        if state.waiting_for == "proposal_selection":
            self.emit(investigation_id, "proposals.ready", {})
            self.emit(
                investigation_id,
                "workflow.waiting",
                {"waiting_for": "proposal_selection"},
            )

    def select_proposals(
        self,
        investigation_id: str,
        *,
        proposal_ids: Sequence[str],
        version: int,
    ) -> None:
        self.require_version(investigation_id, version)
        state = self._load_state(investigation_id)

        if state is None or state.waiting_for != "proposal_selection":
            raise Conflict("wrong_stage", "No proposal selection is pending")

        self._spawn(
            investigation_id,
            self._run_selection(investigation_id, list(proposal_ids), state),
        )

    async def _run_selection(
        self,
        investigation_id: str,
        proposal_ids: list[str],
        state: WorkflowState,
    ) -> None:
        proposals = {
            proposal.id: proposal
            for proposal in await self.store.proposals(investigation_id)
        }
        missing = [pid for pid in proposal_ids if pid not in proposals]

        if missing:
            raise NotFound(f"Unknown proposals: {missing}")

        selection = ProposalSelection(
            id=f"{investigation_id}:selection:proposals",
            run_id=state.run_id,
            actor_id=RESEARCHER,
            proposals=[
                VersionRef(id=pid, version=proposals[pid].version)
                for pid in proposal_ids
            ],
            expected_version=self.store.deliberation_version(investigation_id),
            submitted_at=now(),
        )
        selected_event = await self.store.select_proposals(
            investigation_id,
            selection,
        )

        resumed = state.model_copy(
            update={
                "status": "active",
                "waiting_for": None,
            }
        )
        row = self.investigation(investigation_id)
        graph = self._graph(row["title"] or "Investigation")
        works: list[Work] = []

        with dspy.context(lm=self.lms["deliberation"]):
            resumed, results = await graph.run(resumed, event=selected_event)
            self._record_state(resumed)
            self._publish(investigation_id, [selected_event])

            for result in results:
                self._publish(investigation_id, result.events)

                for event in result.events:
                    works.extend(route(event, resumed))

            await self._execute(investigation_id, works)

    async def _execute(self, investigation_id: str, works: list[Work]) -> None:
        state = self._load_state(investigation_id)

        if state is None:
            raise Conflict("wrong_stage", "Deliberation has not started")

        handlers: dict[str, Callable[[str, Work], Awaitable[list]]] = {
            "assign_thread": self._work_assign,
            "answer_thread": self._work_answer,
            "reply_to_thread": self._work_reply,
            "retrieve_evidence": self._work_retrieve,
            "update_thread_response": self._work_update,
            "summarize_thread": self._work_summarize,
            "reflect_perspectives": self._work_complete,
        }
        queue = list(works)
        discussed: dict[str, None] = {}

        with dspy.context(lm=self.lms["deliberation"]):
            while queue:
                work = queue.pop(0)
                handler = handlers.get(work.kind)

                if handler is None:
                    continue

                events = await handler(investigation_id, work)
                self._publish(investigation_id, events)

                for event in events:
                    if isinstance(event, ContributionAdded):
                        discussed[event.thread_id] = None

                    queue.extend(route(event, state))

            if discussed:
                await self._draft_sections(investigation_id, list(discussed))

    async def _draft_sections(
        self,
        investigation_id: str,
        thread_ids: list[str],
    ) -> None:
        document = await self.store.document(investigation_id)

        if document is None:
            return

        _, pool, names = await self._panel(investigation_id)
        question = self._question(investigation_id)
        run_id = self._run_id(investigation_id)

        for thread_id in thread_ids:
            thread = await self.store.thread(investigation_id, thread_id)

            if thread.status != "open" or not thread.section_id:
                continue

            section = next(
                (s for s in document.sections if s.id == thread.section_id),
                None,
            )

            if section is None:
                continue

            contributions = await self.store.contributions(
                investigation_id,
                thread_id,
            )

            if not contributions:
                continue

            thread_observations = observations_by_id(
                list(
                    dict.fromkeys(
                        observation_id
                        for contribution in contributions
                        for observation_id in contribution.observation_ids
                    )
                ),
                pool,
            )
            text = await draft_section(
                dspy.Predict(DraftSection),
                question=question,
                thread=thread,
                section=section,
                discussion=contribution_lines(contributions, names),
                observations=thread_observations,
            )

            if not text:
                continue

            if thread_observations and not text_citations(text):
                logger.warning(
                    "draft for %s has no [n] markers; keeping current text",
                    section.id,
                )
                continue

            text, references = renumber_markers(
                text,
                thread_observations,
                document.references,
            )
            document = apply_draft(document, section.id, text, references)
            event = DocumentRevised(
                id=event_id(
                    run_id,
                    "document_revised",
                    f"{section.id}:{document.version}",
                ),
                run_id=run_id,
                investigation_id=investigation_id,
                created_at=now(),
                document_id=document.id,
                document_version=document.version,
                revision_id="",
            )
            await self.store.save_document(
                investigation_id,
                document=document,
                threads=[],
                events=[event],
                expected_version=self.store.deliberation_version(
                    investigation_id
                ),
            )
            self._publish(investigation_id, [event])
            self._transition(
                investigation_id,
                document_version=document.version,
            )

    def _next_speaker(
        self,
        thread,
        contributions,
        *,
        avoid: str | None = None,
    ) -> str:
        assigned = [a.perspective_id for a in thread.assignments]
        last_turn = {perspective_id: -1 for perspective_id in assigned}

        for index, contribution in enumerate(contributions):
            if contribution.author_id in last_turn:
                last_turn[contribution.author_id] = index

        candidates = [
            perspective_id
            for perspective_id in assigned
            if perspective_id != avoid
        ] or assigned

        return min(candidates, key=lambda pid: last_turn[pid])

    async def _grounded(
        self,
        state,
        query: str,
        cited,
        *,
        top_k: int = 8,
        cap: int = 12,
    ):
        merged = {observation.id: observation for observation in cited}
        ranked = await rerank(
            query,
            [observation.text for observation in state.observations],
            top_k=top_k,
        )

        for index in ranked:
            candidate = state.observations[index]

            if len(merged) >= cap:
                break

            merged.setdefault(candidate.id, candidate)

        return list(merged.values())

    async def _panel(self, investigation_id: str):
        states = {
            state.id: state
            for state in await self.store.perspectives(investigation_id)
        }
        pool = merge_observations(
            *[state.observations for state in states.values()]
        )
        names = {
            **{pid: state.profile.focus for pid, state in states.items()},
            RESEARCHER: "researcher",
        }
        return states, pool, names

    async def _selected_ids(self, investigation_id: str) -> list[str]:
        selected = await self.store.selected_refinements(investigation_id)
        return [r.proposal.perspective_id for r in selected]

    async def _work_assign(self, investigation_id: str, work: Work):
        thread = await self.store.thread(investigation_id, work.thread_id)

        if thread.status != "open":
            return []

        states, _, _ = await self._panel(investigation_id)
        selected = await self._selected_ids(investigation_id)
        participants = [pid for pid in selected if pid in states] or list(states)

        prediction = await dspy.Predict(AssignQuestions).acall(
            thread=thread_text(thread),
            perspectives=perspective_catalogue(
                [states[pid].profile for pid in participants]
            ),
        )
        questions = [" ".join(q.split()) for q in prediction.questions]

        if len(questions) != len(participants):
            questions = None

        assigned = assign_thread(thread, participants, questions=questions)
        event = ParticipantsAssigned(
            id=event_id(
                self._run_id(investigation_id),
                "participants_assigned",
                assigned.id,
            ),
            run_id=self._run_id(investigation_id),
            investigation_id=investigation_id,
            created_at=now(),
            thread_id=assigned.id,
            perspective_ids=[a.perspective_id for a in assigned.assignments],
        )
        await self.store.save_thread(
            investigation_id,
            thread=assigned,
            events=[event],
            expected_version=self.store.deliberation_version(investigation_id),
        )
        self._transition(investigation_id, active_thread_id=assigned.id)

        return [event]

    async def _work_answer(self, investigation_id: str, work: Work):
        thread = await self.store.thread(investigation_id, work.thread_id)
        states, pool, names = await self._panel(investigation_id)
        proposals = {
            proposal.perspective_id: proposal
            for proposal in await self.store.proposals(investigation_id)
        }
        question = self._question(investigation_id)
        first_id = thread.assignments[0].perspective_id
        answers: list[Contribution] = []

        final_events: list[WorkflowEvent] = []

        for position, assignment in enumerate(thread.assignments):
            state = states[assignment.perspective_id]
            proposal_cited = observations_by_id(
                [
                    evidence.observation_id
                    for evidence in proposals[
                        assignment.perspective_id
                    ].argument.evidence
                ],
                pool,
            )
            contribution = await answer_thread(
                dspy.Predict(AnswerThread),
                contribution_id=(
                    f"{thread.id}:answer:{assignment.perspective_id}"
                ),
                created_at=now(),
                question=question,
                thread=thread,
                assignment=assignment,
                profile=state.profile,
                observations=await self._grounded(
                    state,
                    assignment.question,
                    proposal_cited,
                ),
                discussion=contribution_lines(answers, names),
                polish=dspy.Predict(PolishUtterance),
            )
            answers.append(contribution)
            last = position == len(thread.assignments) - 1
            uptake = last and contribution.author_id != first_id
            event = ContributionAdded(
                id=event_id(
                    self._run_id(investigation_id),
                    "contribution_added",
                    contribution.id,
                ),
                run_id=self._run_id(investigation_id),
                investigation_id=investigation_id,
                created_at=contribution.created_at,
                thread_id=thread.id,
                contribution_id=contribution.id,
                contribution_kind="answer",
                requires_response=uptake,
                target_author_id=first_id if uptake else None,
            )
            await self.store.save_contributions(
                investigation_id,
                contributions=[contribution],
                evidence=None,
                events=[event],
                expected_version=self.store.deliberation_version(
                    investigation_id
                ),
            )

            if last:
                final_events.append(event)
            else:
                self._publish(investigation_id, [event])

        return final_events

    async def _work_reply(self, investigation_id: str, work: Work):
        thread = await self.store.thread(investigation_id, work.thread_id)
        contributions = await self.store.contributions(
            investigation_id,
            work.thread_id,
        )
        by_id = {c.id: c for c in contributions}
        states, pool, _ = await self._panel(investigation_id)
        responder = work.perspective_ids[0]
        message = by_id[work.target_id]
        own_target = None

        if message.reply_to and message.reply_to in by_id:
            candidate = by_id[message.reply_to]

            if candidate.author_id == responder:
                own_target = candidate

        if own_target is None:
            own = [c for c in contributions if c.author_id == responder]

            if not own:
                return []

            own_target = own[-1]

        reply_count = sum(
            1
            for c in contributions
            if c.author_id == responder and c.kind == "reply"
        )
        reply = await reply_to_thread(
            dspy.Predict(ReplyToThread),
            contribution_id=f"{thread.id}:reply:{responder}:{reply_count + 1}",
            perspective_id=responder,
            created_at=now(),
            thread=thread,
            target=own_target,
            message=message.text,
            reply_to=message.id,
            profile=states[responder].profile,
            observations=await self._grounded(
                states[responder],
                message.text,
                observations_by_id(
                    list(
                        dict.fromkeys(
                            [
                                *own_target.observation_ids,
                                *message.observation_ids,
                            ]
                        )
                    ),
                    pool,
                ),
            ),
            polish=dspy.Predict(PolishUtterance),
        )
        events: list[WorkflowEvent] = [
            ContributionAdded(
                id=event_id(
                    self._run_id(investigation_id),
                    "contribution_added",
                    reply.id,
                ),
                run_id=self._run_id(investigation_id),
                investigation_id=investigation_id,
                created_at=reply.created_at,
                thread_id=thread.id,
                contribution_id=reply.id,
                contribution_kind="reply",
            )
        ]

        if reply.evidence_requests:
            events.append(
                EvidenceRequested(
                    id=event_id(
                        self._run_id(investigation_id),
                        "evidence_requested",
                        reply.id,
                    ),
                    run_id=self._run_id(investigation_id),
                    investigation_id=investigation_id,
                    created_at=reply.created_at,
                    thread_id=thread.id,
                    perspective_id=responder,
                    query=reply.evidence_requests[0].query,
                    target_id=reply.id,
                )
            )

        await self.store.save_contributions(
            investigation_id,
            contributions=[reply],
            evidence=None,
            events=events,
            expected_version=self.store.deliberation_version(investigation_id),
        )

        return events

    async def _work_retrieve(self, investigation_id: str, work: Work):
        states, _, _ = await self._panel(investigation_id)
        responder = work.perspective_ids[0]
        row = self.investigation(investigation_id)
        result = (
            await self.evidence_search.acall(
                query=work.query or "",
                question=self._question(investigation_id),
                investigation_id=investigation_id,
                corpus_id=row["corpus_id"],
                source_ids=states[responder].source_ids,
            )
        ).result
        event = EvidenceRetrieved(
            id=event_id(
                self._run_id(investigation_id),
                "evidence_retrieved",
                f"{work.thread_id}:{responder}:{work.target_id}",
            ),
            run_id=self._run_id(investigation_id),
            investigation_id=investigation_id,
            created_at=now(),
            perspective_id=responder,
            query=work.query or "",
            snippet_ids=result.snippet_ids,
            thread_id=work.thread_id,
            target_id=work.target_id,
        )
        self.pending_evidence[investigation_id] = result
        await self.store.save_contributions(
            investigation_id,
            contributions=[],
            evidence=result,
            events=[event],
            expected_version=self.store.deliberation_version(investigation_id),
        )

        return [event]

    async def _work_update(self, investigation_id: str, work: Work):
        thread = await self.store.thread(investigation_id, work.thread_id)
        contributions = await self.store.contributions(
            investigation_id,
            work.thread_id,
        )
        states, pool, names = await self._panel(investigation_id)
        responder = work.perspective_ids[0]
        by_id = {c.id: c for c in contributions}
        previous = by_id.get(work.target_id) if work.target_id else None

        if previous is None or previous.author_id != responder:
            own = [c for c in contributions if c.author_id == responder]

            if not own:
                return []

            previous = own[-1]

        prompted_by = (
            previous.evidence_requests[0].need
            if previous.evidence_requests
            else thread.question
        )
        retrieved = self.pending_evidence.pop(investigation_id, None)
        observations = (
            retrieved.observations
            if retrieved is not None and retrieved.observations
            else observations_by_id(previous.observation_ids, pool)
        )
        reply_count = sum(
            1
            for c in contributions
            if c.author_id == responder and c.kind == "reply"
        )
        followup = await update_thread_response(
            dspy.Predict(UpdateThreadResponse),
            contribution_id=f"{thread.id}:reply:{responder}:{reply_count + 1}",
            perspective_id=responder,
            created_at=now(),
            thread=thread,
            previous=previous,
            prompted_by=prompted_by,
            profile=states[responder].profile,
            observations=observations,
            discussion=contribution_lines(contributions, names),
            polish=dspy.Predict(PolishUtterance),
        )
        event = ContributionAdded(
            id=event_id(
                self._run_id(investigation_id),
                "contribution_added",
                followup.id,
            ),
            run_id=self._run_id(investigation_id),
            investigation_id=investigation_id,
            created_at=followup.created_at,
            thread_id=thread.id,
            contribution_id=followup.id,
            contribution_kind="reply",
        )
        await self.store.save_contributions(
            investigation_id,
            contributions=[followup],
            evidence=None,
            events=[event],
            expected_version=self.store.deliberation_version(investigation_id),
        )

        return [event]

    async def _work_summarize(self, investigation_id: str, work: Work):
        thread = await self.store.thread(investigation_id, work.thread_id)
        contributions = await self.store.contributions(
            investigation_id,
            work.thread_id,
        )
        states, pool, names = await self._panel(investigation_id)
        cited = {
            observation_id
            for contribution in contributions
            for observation_id in contribution.observation_ids
        }
        observations = [o for o in pool if o.id in cited]
        previous = await self.store.resolution_for(
            investigation_id,
            work.thread_id,
        )
        ordinal = 2 if previous is not None else 1
        resolution = await summarize_thread(
            dspy.Predict(SummarizeThread),
            resolution_id=f"{thread.id}:resolution:{ordinal}",
            thread=thread,
            contributions=contributions,
            observations=observations,
            names=names,
        )
        event = ResolutionProposed(
            id=event_id(
                self._run_id(investigation_id),
                "resolution_proposed",
                resolution.id,
            ),
            run_id=self._run_id(investigation_id),
            investigation_id=investigation_id,
            created_at=now(),
            thread_id=thread.id,
            resolution_id=resolution.id,
        )
        await self.store.save_resolution(
            investigation_id,
            thread=thread,
            resolution=resolution,
            decision=None,
            events=[event],
            expected_version=self.store.deliberation_version(investigation_id),
        )
        self._transition(
            investigation_id,
            status="waiting",
            waiting_for="resolution_decision",
        )
        self.emit(
            investigation_id,
            "workflow.waiting",
            {"waiting_for": "resolution_decision"},
        )

        return [event]

    async def _work_complete(self, investigation_id: str, work: Work):
        thread = await self.store.thread(investigation_id, work.thread_id)
        resolution = await self.store.resolution_for(
            investigation_id,
            work.thread_id,
        )
        states, pool, _ = await self._panel(investigation_id)
        document = await self.store.document(investigation_id)
        question = self._question(investigation_id)
        run_id = self._run_id(investigation_id)
        reflections = await reflect_perspectives(
            question=question,
            thread=thread,
            resolution=resolution,
            perspective_ids=[
                pid for pid in work.perspective_ids if pid in states
            ],
            perspectives=states,
            max_parallel=self.config.max_parallel,
        )
        suggestion = None
        section = next(
            (
                section
                for section in (document.sections if document else [])
                if section.id == thread.section_id
            ),
            None,
        )

        resolution_ids = set(resolution.observation_ids)
        resolution_observations = [
            observation
            for observation in pool
            if observation.id in resolution_ids
        ]

        if section is not None:
            suggestion = await suggest_document_change(
                dspy.Predict(SuggestDocumentChange),
                suggestion_id=f"{thread.id}:suggestion:1",
                author_id=MODERATOR,
                question=question,
                section=section,
                thread=thread,
                resolution=resolution,
                observations=resolution_observations,
            )

        threads = await self.store.threads(investigation_id)
        used_ids: set[str] = set(resolution.observation_ids)

        for row in await self.store.proposals(investigation_id):
            used_ids.update(
                evidence.observation_id
                for evidence in row.argument.evidence
            )

        for existing in threads:
            for contribution in await self.store.contributions(
                investigation_id,
                existing.id,
            ):
                used_ids.update(contribution.observation_ids)

        unused = [
            observation
            for observation in pool
            if observation.id not in used_ids
        ]
        ranked = await rerank(
            question,
            [observation.text for observation in unused],
            top_k=8,
            instruction="Prefer findings the discussion has not yet used.",
        )
        unused_lines = [unused[index].text for index in ranked]
        drafts = (
            await dspy.Predict(SuggestThread).acall(
                research_question=question,
                objectives=[
                    objective.text
                    for objective in (document.objectives if document else [])
                ],
                perspectives=perspective_catalogue(
                    [
                        states[pid].profile
                        for pid in work.perspective_ids
                        if pid in states
                    ]
                    or [state.profile for state in states.values()]
                ),
                open_questions=(
                    [r.open_question for r in reflections if r.open_question]
                    + (
                        [resolution.open_question]
                        if resolution.open_question
                        else []
                    )
                ),
                existing_questions=[
                    f"{t.title}: {t.question}" for t in threads
                ],
                resolution=resolution_text(resolution),
                unused_observations=unused_lines,
                n=2,
            )
        ).threads[:2]
        kept = unique_threads(
            drafts,
            [t.question for t in threads],
            [t.title for t in threads],
        )
        followups = [
            Thread(
                id=f"{investigation_id}:thread:{len(threads) + i}",
                version=1,
                status="suggested",
                title=" ".join(draft.title.split()),
                question=" ".join(draft.question.split()),
                context=" ".join(draft.context.split()),
                created_by=MODERATOR,
                created_at=now(),
            )
            for i, draft in enumerate(kept, start=1)
        ]
        events: list[WorkflowEvent] = []

        if suggestion is not None:
            events.append(
                SuggestionCreated(
                    id=event_id(run_id, "suggestion_created", suggestion.id),
                    run_id=run_id,
                    investigation_id=investigation_id,
                    created_at=now(),
                    thread_id=thread.id,
                    suggestion_id=suggestion.id,
                )
            )

        events.extend(
            ThreadCreated(
                id=event_id(run_id, "thread_created", followup.id),
                run_id=run_id,
                investigation_id=investigation_id,
                created_at=followup.created_at,
                thread_id=followup.id,
            )
            for followup in followups
        )
        revised_document = None
        revision = None
        apply_decision = None

        if suggestion is not None:
            renumbered_text, references = renumber_markers(
                suggestion.proposed_text,
                resolution_observations,
                document.references,
            )
            suggestion = suggestion.model_copy(
                update={"proposed_text": renumbered_text}
            )
            document = document.model_copy(
                update={"references": references}
            )
            apply_decision = SuggestionDecision(
                id=f"{suggestion.id}:decision:{uuid4().hex[:8]}",
                run_id=run_id,
                actor_id=MODERATOR,
                suggestion=VersionRef(
                    id=suggestion.id,
                    version=suggestion.version,
                ),
                section_version=suggestion.section_version,
                action="accept",
                expected_version=self.store.deliberation_version(
                    investigation_id
                ),
                submitted_at=now(),
            )
            revised_document, suggestion, revision = apply_suggestion(
                document,
                suggestion,
                action="accept",
                decision_id=work.decision_id or apply_decision.id,
                revision_id=f"{document.id}:revision:{uuid4().hex[:8]}",
                created_at=now(),
            )
            events.append(
                SuggestionDecided(
                    id=event_id(run_id, "suggestion_decided", suggestion.id),
                    run_id=run_id,
                    investigation_id=investigation_id,
                    created_at=now(),
                    suggestion_id=suggestion.id,
                    action="accept",
                )
            )

            if revision is not None:
                events.append(
                    DocumentRevised(
                        id=event_id(run_id, "document_revised", revision.id),
                        run_id=run_id,
                        investigation_id=investigation_id,
                        created_at=now(),
                        document_id=revised_document.id,
                        document_version=revised_document.version,
                        revision_id=revision.id,
                    )
                )

        await self.store.save_completion(
            investigation_id,
            reflections=list(reflections),
            suggestion=suggestion,
            threads=followups,
            events=events,
            expected_version=self.store.deliberation_version(investigation_id),
        )

        if revised_document is not None and apply_decision is not None:
            await self.store.save_revision(
                investigation_id,
                document=revised_document,
                suggestion=suggestion,
                revision=revision,
                decision=apply_decision,
                events=[],
                expected_version=self.store.deliberation_version(
                    investigation_id
                ),
            )
            self._transition(
                investigation_id,
                document_version=revised_document.version,
            )

        return events

    def open_suggested(
        self,
        investigation_id: str,
        thread_id: str,
        *,
        version: int,
    ) -> None:
        self.require_version(investigation_id, version)

        if self.busy(investigation_id):
            raise Conflict("busy", "Another operation is already running")

        self._spawn(
            investigation_id,
            self._run_open_suggested(investigation_id, thread_id),
        )

    async def _run_open_suggested(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> None:
        thread = await self.store.thread(investigation_id, thread_id)

        if thread.status != "suggested":
            raise Conflict(
                "wrong_stage",
                "Only a suggested Thread can be opened",
            )

        document = await self.store.document(investigation_id)

        if document is None:
            raise Conflict("wrong_stage", "The Working Document does not exist")

        run_id = self._run_id(investigation_id)
        revised_document, opened = open_thread(document, thread)
        event = ThreadOpened(
            id=event_id(run_id, "thread_opened", thread.id),
            run_id=run_id,
            investigation_id=investigation_id,
            created_at=now(),
            thread_id=thread.id,
        )
        await self.store.save_document(
            investigation_id,
            document=revised_document,
            threads=[opened],
            events=[event],
            expected_version=self.store.deliberation_version(investigation_id),
        )
        self._publish(investigation_id, [event])
        self._transition(investigation_id, active_thread_id=thread.id)

        state = self._load_state(investigation_id)
        await self._execute(
            investigation_id,
            route(event, state) if state else [],
        )

    def create_thread(
        self,
        investigation_id: str,
        *,
        title: str,
        question: str,
        context: str,
        version: int,
    ) -> Thread:
        self.require_version(investigation_id, version)
        thread = Thread(
            id=f"{investigation_id}:thread:researcher:{uuid4().hex[:8]}",
            version=1,
            status="suggested",
            title=" ".join(title.split()),
            question=" ".join(question.split()),
            context=" ".join(context.split()) or question,
            created_by=RESEARCHER,
            created_at=now(),
        )
        self._spawn(
            investigation_id,
            self._run_open_thread(investigation_id, thread),
        )

        return thread

    async def _run_open_thread(
        self,
        investigation_id: str,
        thread: Thread,
    ) -> None:
        document = await self.store.document(investigation_id)

        if document is None:
            raise Conflict("wrong_stage", "The Working Document does not exist")

        run_id = self._run_id(investigation_id)
        revised_document, opened = open_thread(document, thread)
        events: list[WorkflowEvent] = [
            ThreadCreated(
                id=event_id(run_id, "thread_created", thread.id),
                run_id=run_id,
                investigation_id=investigation_id,
                created_at=thread.created_at,
                thread_id=thread.id,
            ),
            ThreadOpened(
                id=event_id(run_id, "thread_opened", thread.id),
                run_id=run_id,
                investigation_id=investigation_id,
                created_at=now(),
                thread_id=thread.id,
            ),
        ]
        await self.store.save_document(
            investigation_id,
            document=revised_document,
            threads=[opened],
            events=events,
            expected_version=self.store.deliberation_version(investigation_id),
        )
        self._publish(investigation_id, events)
        self._transition(investigation_id, active_thread_id=thread.id)

        state = self._load_state(investigation_id)
        works: list[Work] = []

        for event in events:
            works.extend(route(event, state) if state else [])

        await self._execute(investigation_id, works)

    def add_contribution(
        self,
        investigation_id: str,
        thread_id: str,
        *,
        kind: str,
        text: str,
        reply_to: str | None,
    ) -> Contribution:
        contribution = Contribution(
            id=f"{thread_id}:{kind}:{RESEARCHER}:{uuid4().hex[:8]}",
            thread_id=thread_id,
            author_id=RESEARCHER,
            kind=kind,
            text=" ".join(text.split()),
            observation_ids=[],
            reply_to=reply_to,
            created_at=now(),
        )
        self._spawn(
            investigation_id,
            self._run_contribution(investigation_id, contribution),
        )

        return contribution

    async def _run_contribution(
        self,
        investigation_id: str,
        contribution: Contribution,
    ) -> None:
        contributions = await self.store.contributions(
            investigation_id,
            contribution.thread_id,
        )
        by_id = {c.id: c for c in contributions}
        target_author = None

        if contribution.reply_to and contribution.reply_to in by_id:
            target_author = by_id[contribution.reply_to].author_id

        run_id = self._run_id(investigation_id)
        event = ContributionAdded(
            id=event_id(run_id, "contribution_added", contribution.id),
            run_id=run_id,
            investigation_id=investigation_id,
            created_at=contribution.created_at,
            thread_id=contribution.thread_id,
            contribution_id=contribution.id,
            contribution_kind=contribution.kind,
            target_author_id=target_author,
            requires_response=(
                contribution.kind in ("challenge", "reply")
                and target_author is not None
                and target_author != RESEARCHER
            ),
        )
        await self.store.save_contributions(
            investigation_id,
            contributions=[contribution],
            evidence=None,
            events=[event],
            expected_version=self.store.deliberation_version(investigation_id),
        )
        self._publish(investigation_id, [event])

        state = self._load_state(investigation_id)
        await self._execute(
            investigation_id,
            route(event, state) if state else [],
        )

    def continue_thread(self, investigation_id: str, thread_id: str) -> None:
        self._spawn(
            investigation_id,
            self._run_continuation(investigation_id, thread_id),
        )

    async def _run_continuation(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> None:
        thread = await self.store.thread(investigation_id, thread_id)

        if thread.status != "open":
            raise Conflict("wrong_stage", "Only an open Thread can continue")

        contributions = await self.store.contributions(
            investigation_id,
            thread_id,
        )

        if not contributions or not thread.assignments:
            raise Conflict("wrong_stage", "The Thread has no discussion yet")

        newest = contributions[-1]
        speaker = self._next_speaker(
            thread,
            contributions,
            avoid=newest.author_id if newest.author_id != RESEARCHER else None,
        )
        await self._execute(
            investigation_id,
            [
                Work(
                    kind="reply_to_thread",
                    thread_id=thread_id,
                    perspective_ids=[speaker],
                    target_id=newest.id,
                )
            ],
        )

    def request_evidence(
        self,
        investigation_id: str,
        thread_id: str,
        *,
        need: str,
        query: str,
    ) -> None:
        self._spawn(
            investigation_id,
            self._run_evidence_request(
                investigation_id,
                thread_id,
                need,
                query,
            ),
        )

    async def _run_evidence_request(
        self,
        investigation_id: str,
        thread_id: str,
        need: str,
        query: str,
    ) -> None:
        thread = await self.store.thread(investigation_id, thread_id)
        contributions = await self.store.contributions(
            investigation_id,
            thread_id,
        )
        agents = [c for c in contributions if c.author_id != RESEARCHER]

        if not agents:
            raise Conflict("wrong_stage", "The Thread has no contributions yet")

        if thread.assignments:
            speaker = self._next_speaker(
                thread,
                contributions,
                avoid=agents[-1].author_id,
            )
            own = [c for c in agents if c.author_id == speaker]
            target = own[-1] if own else agents[-1]
        else:
            target = agents[-1]

        run_id = self._run_id(investigation_id)
        event = EvidenceRequested(
            id=event_id(
                run_id,
                "evidence_requested",
                f"{thread_id}:{RESEARCHER}:{uuid4().hex[:8]}",
            ),
            run_id=run_id,
            investigation_id=investigation_id,
            created_at=now(),
            thread_id=thread_id,
            perspective_id=target.author_id,
            query=query or need,
            target_id=target.id,
        )

        with self.db:
            self.db.execute(
                "insert or ignore into events"
                " (event_id, investigation_id, kind, payload, created_at)"
                " values (?,?,?,?,?)",
                (
                    event.id,
                    investigation_id,
                    event.kind,
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                ),
            )

        self._publish(investigation_id, [event])
        state = self._load_state(investigation_id)
        await self._execute(
            investigation_id,
            route(event, state) if state else [],
        )

    def request_resolution(self, investigation_id: str, thread_id: str) -> None:
        self._spawn(
            investigation_id,
            self._run_resolution_request(investigation_id, thread_id),
        )

    async def _run_resolution_request(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> None:
        run_id = self._run_id(investigation_id)
        event = ResolutionRequested(
            id=event_id(run_id, "resolution_requested", thread_id),
            run_id=run_id,
            investigation_id=investigation_id,
            created_at=now(),
            thread_id=thread_id,
        )
        state = self._load_state(investigation_id)
        await self._execute(
            investigation_id,
            route(event, state) if state else [],
        )

    def decide_resolution(
        self,
        investigation_id: str,
        resolution: Resolution,
        *,
        action: str,
        version: int,
        consensus: str | None,
        disagreement: str | None,
        open_question: str | None,
    ) -> None:
        if resolution.version != version:
            raise Conflict(
                "stale_version",
                "The Resolution changed after this view was loaded",
            )

        internal = {
            "accept_and_close": "close",
            "edit_and_close": "edit_close",
            "keep_open": "keep_open",
            "request_evidence": "request_evidence",
        }[action]
        self._spawn(
            investigation_id,
            self._run_resolution_decision(
                investigation_id,
                resolution,
                internal,
                consensus,
                disagreement,
                open_question,
            ),
        )

    async def _run_resolution_decision(
        self,
        investigation_id: str,
        resolution: Resolution,
        action: str,
        consensus: str | None,
        disagreement: str | None,
        open_question: str | None,
    ) -> None:
        thread = await self.store.thread(investigation_id, resolution.thread_id)
        contributions = await self.store.contributions(
            investigation_id,
            resolution.thread_id,
        )
        decided_thread, decided = decide_resolution(
            thread,
            resolution,
            action=action,
            consensus=consensus,
            disagreement=disagreement,
            open_question=open_question,
        )
        run_id = self._run_id(investigation_id)
        decision = ThreadDecision(
            id=f"{resolution.id}:decision:{uuid4().hex[:8]}",
            run_id=run_id,
            actor_id=RESEARCHER,
            thread=VersionRef(id=thread.id, version=thread.version),
            resolution=VersionRef(id=resolution.id, version=resolution.version),
            action=action,
            expected_version=self.store.deliberation_version(investigation_id),
            submitted_at=now(),
        )
        events: list[WorkflowEvent] = []

        if action in ("close", "edit_close"):
            affected = affected_perspectives(
                contributions,
                extra=[
                    c.author_id
                    for c in contributions
                    if c.author_id != RESEARCHER and c.kind == "reply"
                ],
            )
            events.append(
                ThreadClosed(
                    id=event_id(run_id, "thread_closed", thread.id),
                    run_id=run_id,
                    investigation_id=investigation_id,
                    created_at=now(),
                    caused_by=decision.id,
                    thread_id=thread.id,
                    resolution_id=resolution.id,
                    perspective_ids=affected,
                )
            )

        await self.store.save_resolution(
            investigation_id,
            thread=decided_thread,
            resolution=decided,
            decision=decision,
            events=events,
            expected_version=decision.expected_version,
        )
        self._publish(investigation_id, events)
        self._transition(
            investigation_id,
            status="active",
            waiting_for=None,
            active_thread_id=(
                None if action in ("close", "edit_close") else thread.id
            ),
        )

        state = self._load_state(investigation_id)
        works: list[Work] = []

        for event in events:
            works.extend(route(event, state) if state else [])

        await self._execute(investigation_id, works)

    def decide_suggestion(
        self,
        investigation_id: str,
        suggestion: Suggestion,
        *,
        action: str,
        version: int,
        text: str | None,
    ) -> None:
        if suggestion.version != version:
            raise Conflict(
                "stale_version",
                "The Suggestion changed after this view was loaded",
            )

        if action == "defer":
            self._transition(investigation_id, status="active", waiting_for=None)
            return

        self._spawn(
            investigation_id,
            self._run_suggestion_decision(
                investigation_id,
                suggestion,
                action,
                text,
            ),
        )

    async def _run_suggestion_decision(
        self,
        investigation_id: str,
        suggestion: Suggestion,
        action: str,
        text: str | None,
    ) -> None:
        document = await self.store.document(investigation_id)

        if document is None:
            raise Conflict("wrong_stage", "The Working Document does not exist")

        run_id = self._run_id(investigation_id)
        decision = SuggestionDecision(
            id=f"{suggestion.id}:decision:{uuid4().hex[:8]}",
            run_id=run_id,
            actor_id=RESEARCHER,
            suggestion=VersionRef(id=suggestion.id, version=suggestion.version),
            section_version=suggestion.section_version,
            action=action,
            expected_version=self.store.deliberation_version(investigation_id),
            submitted_at=now(),
        )
        revised_document, decided, revision = apply_suggestion(
            document,
            suggestion,
            action=action,
            decision_id=decision.id,
            revision_id=f"{document.id}:revision:{uuid4().hex[:8]}",
            created_at=now(),
            text=text,
        )
        events: list[WorkflowEvent] = [
            SuggestionDecided(
                id=event_id(run_id, "suggestion_decided", suggestion.id),
                run_id=run_id,
                investigation_id=investigation_id,
                created_at=now(),
                suggestion_id=suggestion.id,
                action=action,
            )
        ]

        if revision is not None:
            events.append(
                DocumentRevised(
                    id=event_id(run_id, "document_revised", revision.id),
                    run_id=run_id,
                    investigation_id=investigation_id,
                    created_at=now(),
                    document_id=revised_document.id,
                    document_version=revised_document.version,
                    revision_id=revision.id,
                )
            )

        await self.store.save_revision(
            investigation_id,
            document=revised_document,
            suggestion=decided,
            revision=revision,
            decision=decision,
            events=events,
            expected_version=decision.expected_version,
        )
        self._publish(investigation_id, events)
        self._transition(
            investigation_id,
            status="active",
            waiting_for=None,
            document_version=revised_document.version,
        )

    async def edit_section(
        self,
        investigation_id: str,
        section_id: str,
        *,
        text: str,
        version: int,
    ):
        document = await self.store.document(investigation_id)

        if document is None:
            raise NotFound("The Working Document does not exist")

        section = next(
            (s for s in document.sections if s.id == section_id),
            None,
        )

        if section is None:
            raise NotFound(f"Unknown section: {section_id}")

        if section.version != version:
            raise Conflict(
                "stale_version",
                "The section changed after this view was loaded",
            )

        synthetic = Suggestion(
            id=f"{section_id}:edit:{uuid4().hex[:8]}",
            version=1,
            status="pending",
            author_id=RESEARCHER,
            thread_id="",
            resolution_id="",
            section_id=section.id,
            section_version=section.version,
            current_text=section.text,
            proposed_text=text,
            reason="researcher edit",
            observation_ids=[],
        )
        await self._run_suggestion_decision(
            investigation_id,
            synthetic,
            "edit",
            text,
        )
        revised = await self.store.document(investigation_id)

        return next(s for s in revised.sections if s.id == section_id)
