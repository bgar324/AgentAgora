"""Cross-cutting contracts retained by the baseline-only service."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agora.api.focused import focused_router
from agora.focused import agents
from agora.focused.agents import FocusedAgentError
from agora.focused.demo_data import DEMO_PAPERS
from agora.focused.models import FACETS, FacetEvidence, NotepadDoc, Perspective
from agora.focused.service import FocusedPanelService


def test_mutations_advance_the_authoritative_workspace_revision() -> None:
    async def go() -> tuple[int, int]:
        service = FocusedPanelService()
        view = service.create_workspace(
            problem="How should antibiotic breadth be bounded?",
            position={"framing": "Treat breadth as ecological pressure."},
            demo=True,
        )
        before = view.workspace.revision
        await service.suggest_queries(view.active.id)
        after = service.workspace_view(view.workspace.id).workspace.revision
        return before, after

    before, after = asyncio.run(go())
    assert before == 0
    assert after == before + 1


def test_prose_queries_compact_and_relax_to_broad_terms() -> None:
    query = (
        "How can a compiler identify explicit obligations relevant to a request "
        "in a large system prompt?"
    )
    compact = agents.compact_search_query(query)
    relaxed = agents.relaxed_search_query(compact)
    assert len(compact.split()) <= 6
    assert relaxed
    assert len(relaxed.split()) <= 3
    assert "how" not in relaxed.split()


def test_extracts_exactly_four_abstract_grounded_facets() -> None:
    facets = asyncio.run(agents.extract_cluster_facets(DEMO_PAPERS[:4]))
    assert [evidence.facet for evidence in facets] == FACETS
    by_id = {paper.id: paper for paper in DEMO_PAPERS[:4]}
    assert all(evidence.paper_id in by_id for evidence in facets)
    assert all(
        evidence.sentence in by_id[evidence.paper_id].abstract_sentences
        for evidence in facets
        if evidence.paper_id is not None
    )


def test_facet_mapping_uses_only_exact_abstract_sentences() -> None:
    paper = DEMO_PAPERS[0]
    sentence = paper.abstract_sentences[1]
    mapped = agents.map_facet_to_sentence(
        paper,
        FacetEvidence(facet="scope", text=sentence),
    )
    unsupported = agents.map_facet_to_sentence(
        paper,
        FacetEvidence(facet="scope", text="A claim absent from the abstract."),
    )
    assert mapped.sentence == sentence
    assert mapped.sentence_index == 1
    assert unsupported.sentence is None
    assert unsupported.sentence_index is None


def test_framing_and_position_are_derived_from_all_four_fragments() -> None:
    paper = DEMO_PAPERS[0]
    facets = {
        facet: FacetEvidence(
            facet=facet,
            text=f"Distinct {facet} evidence.",
            paper_id=paper.id,
            sentence_index=0,
            sentence=paper.abstract_sentences[0],
        )
        for facet in FACETS
    }
    perspective = Perspective(
        id="persp-1",
        name="Evidence boundary",
        color="#336699",
        facets=facets,
        sources=[paper.id],
        anchor_paper_id=paper.id,
    )
    synthesis = asyncio.run(agents.derive_framing(perspective))
    assert synthesis.framing
    assert synthesis.position
    assert "Distinct scope evidence" in synthesis.framing
    assert "Distinct significance evidence" in synthesis.position


def test_live_provider_failure_is_typed_not_silently_fabricated() -> None:
    class FailingProvider:
        async def generate_structured(self, **kwargs):
            raise RuntimeError("provider unavailable")

    async def go() -> None:
        with pytest.raises(FocusedAgentError):
            await agents.suggest_queries(
                "How should antibiotic breadth be bounded?",
                [],
                position=NotepadDoc(framing="Ecological pressure."),
                provider=FailingProvider(),
            )

    asyncio.run(go())


def test_removed_arm_field_and_legacy_routes_are_rejected() -> None:
    app = FastAPI()
    app.state.focused = FocusedPanelService()
    app.include_router(focused_router)
    client = TestClient(app)
    response = client.post(
        "/focused/workspaces",
        json={
            "problem": "How should antibiotic breadth be bounded?",
            "position": {},
            "demo": True,
            "participant_id": "P-0042",
        },
    )
    assert response.status_code == 422
    created = client.post(
        "/focused/workspaces",
        json={"problem": "How should antibiotic breadth be bounded?"},
    )
    assert created.status_code == 200
    session_id = created.json()["active"]["id"]
    assert app.state.focused.get(session_id).demo is False
    oversized_search = client.post(
        f"/focused/sessions/{session_id}/search",
        json={"queries": ["x" * 501]},
    )
    assert oversized_search.status_code == 422
    assert client.post("/focused/sessions/missing/deliberations").status_code == 404
    assert client.post("/focused/sessions/missing/dialogue/start").status_code == 404
