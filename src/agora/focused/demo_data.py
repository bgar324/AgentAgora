"""Hermetic abstract-grounded corpus for the focused-panel study flow."""

from agora.focused.models import FACETS, ExpPaper, Facet, FacetEvidence, SuggestedQuery

DEMO_RESEARCH_QUESTIONS = [
    "Does broad-spectrum use raise resistance enough to matter at population level?",
    "Does it harm the patient's own flora in ways that outlast the infection?",
    "When does speed to cure outweigh both?",
]

DEMO_SHARED_GROUND: dict[Facet, str] = {
    "scope": (
        "patients and populations exposed to broad antibiotics, stratified by "
        "infection severity and treatment duration"
    ),
    "explanation": (
        "Broader and longer exposure can improve immediate pathogen coverage while "
        "increasing selection pressure and disrupting protective microbial communities."
    ),
    "approach": (
        "The trade-off should be tested by pairing acute cure and mortality outcomes "
        "with longitudinal resistance and microbiome measures, stratified by severity "
        "and exposure."
    ),
    "significance": (
        "The decision connects immediate patient benefit to delayed harms that can "
        "persist beyond the infection and accumulate across populations."
    ),
}

DEMO_QUERY_SUGGESTIONS = [
    SuggestedQuery(
        query="broad-spectrum antibiotic use antimicrobial resistance population",
        rationale="Population-level resistance consequences.",
        kind="question",
        question_index=0,
    ),
    SuggestedQuery(
        query="broad-spectrum antibiotics gut microbiome recovery",
        rationale="Host-microbiome consequences after treatment.",
        kind="question",
        question_index=1,
    ),
    SuggestedQuery(
        query="early broad coverage sepsis mortality cure",
        rationale="Immediate clinical benefit and under-treatment risk.",
        kind="question",
        question_index=2,
    ),
    SuggestedQuery(
        query="rapid diagnostics antibiotic de-escalation",
        rationale="Information and targeting alternatives.",
    ),
    SuggestedQuery(
        query="antibiotic stewardship resistance cost policy",
        rationale="Institutional and societal trade-offs.",
    ),
]

DEMO_CLUSTERS: list[dict[str, object]] = [
    {
        "name": "Resistance ecology",
        "terms": [
            "resistance",
            "genes",
            "resistome",
            "selection",
            "stewardship",
            "spectrum",
        ],
        "blurb": "Reads prescribing as evolutionary pressure and tracks what accumulates across populations.",
    },
    {
        "name": "Host and microbiome",
        "terms": [
            "microbiome",
            "commensal",
            "flora",
            "dysbiosis",
            "diversity",
            "colonization",
        ],
        "blurb": "Treats the patient's microbial ecology as a durable treatment outcome.",
    },
    {
        "name": "Acute outcomes",
        "terms": ["mortality", "sepsis", "survival", "cure", "coverage", "delay"],
        "blurb": "Weighs prescribing by immediate cure, adequate coverage, and survival.",
    },
    {
        "name": "Diagnostics and targeting",
        "terms": [
            "diagnostic",
            "rapid",
            "identification",
            "prediction",
            "model",
            "narrow",
        ],
        "blurb": "Recasts antibiotic breadth as an information and targeting problem.",
    },
    {
        "name": "Systems and policy",
        "terms": [
            "cost",
            "policy",
            "programme",
            "program",
            "agricultural",
            "societal",
            "community",
        ],
        "blurb": "Sets the unit of analysis above one patient or one prescription.",
    },
    {
        "name": "Treatment alternatives",
        "terms": [
            "phage",
            "combination",
            "biomarker",
            "duration",
            "targeted",
            "therapy",
        ],
        "blurb": "Tests whether narrower or shorter interventions can escape the efficacy-harm trade-off.",
    },
]


def _paper(
    paper_id: str,
    title: str,
    year: int,
    scope: str,
    explanation: str,
    approach: str,
    significance: str,
) -> ExpPaper:
    sentences = [scope, explanation, approach, significance]
    return ExpPaper(
        id=paper_id,
        title=title,
        abstract=" ".join(sentences),
        abstract_sentences=sentences,
        year=year,
    )


DEMO_PAPERS: list[ExpPaper] = [
    _paper(
        "p1",
        "Broad-spectrum overuse and the rise of resistance genes",
        2021,
        "This study examines cumulative broad-spectrum exposure across fourteen hospitals.",
        "Longer exposure selects for a higher prevalence of resistance genes.",
        "A longitudinal hospital cohort links antibiotic-days with resistome measurements.",
        "The result makes cumulative resistance a population-level cost of routine broad prescribing.",
    ),
    _paper(
        "p2",
        "Gut microbiome disruption after antibiotic therapy",
        2020,
        "This study follows adult patients' gut microbiomes during and after broad-spectrum therapy.",
        "Broad agents deplete commensal diversity and recovery remains incomplete after treatment.",
        "Repeated 16S sequencing measures within-patient diversity trajectories.",
        "Persistent dysbiosis makes treatment effects beyond pathogen clearance clinically consequential.",
    ),
    _paper(
        "p3",
        "Empiric broad-spectrum therapy and ICU mortality",
        2019,
        "This study covers adults with suspected sepsis in intensive care.",
        "Early broad coverage reduces the chance that the infecting pathogen is initially untreated.",
        "A severity-adjusted ICU cohort compares early coverage with thirty-day mortality.",
        "The association supports prioritizing adequate immediate coverage when delay is life-threatening.",
    ),
    _paper(
        "p4",
        "Rapid diagnostics enable narrow-spectrum choice",
        2023,
        "This study examines hospitalized infections eligible for rapid pathogen identification.",
        "Earlier identification reduces uncertainty and enables safe antibiotic de-escalation.",
        "A prospective implementation study compares time to identification and time to narrowing.",
        "Rapid diagnosis can preserve acute safety without accepting prolonged broad exposure.",
    ),
    _paper(
        "p5",
        "Population-level cost of broad prescribing",
        2020,
        "This analysis covers short-term treatment benefit and long-run societal resistance costs.",
        "Each broad prescription adds selection pressure whose costs accumulate beyond the treated patient.",
        "A decision model combines cure benefits, resistance prevalence, and downstream treatment costs.",
        "Long-run externalities can outweigh the immediate expected benefit of routine broad prescribing.",
    ),
    _paper(
        "p6",
        "Antibiotic stewardship programs reduce resistance rates",
        2020,
        "This study evaluates hospital wards adopting an antibiotic stewardship programme.",
        "Reducing unnecessary broad prescriptions lowers ward-level selection pressure.",
        "A controlled before-and-after analysis tracks prescribing and resistance rates.",
        "Institutional governance can reduce resistance without relying on isolated clinician choices.",
    ),
    _paper(
        "p7",
        "Horizontal gene transfer under sub-inhibitory exposure",
        2019,
        "This study examines bacterial communities exposed to sub-inhibitory antibiotics.",
        "Low-dose exposure accelerates plasmid-mediated horizontal transfer of resistance genes.",
        "Laboratory assays quantify transfer rates across controlled exposure levels.",
        "Even incomplete antibiotic exposure may propagate resistance beyond directly selected mutants.",
    ),
    _paper(
        "p8",
        "Commensal depletion and C. difficile risk",
        2019,
        "This cohort follows patients after broad therapy to measure colonization resistance.",
        "Commensal depletion removes ecological barriers to Clostridioides difficile infection.",
        "Microbiome profiles are linked prospectively to subsequent infection incidence.",
        "Protecting commensals is a safety outcome rather than a secondary biological curiosity.",
    ),
    _paper(
        "p9",
        "Empiric therapy duration and resistance emergence",
        2021,
        "This study covers hospitalized patients receiving empiric broad therapy for varying durations.",
        "Each additional exposure day increases selection for newly resistant isolates.",
        "A multivariable cohort model estimates resistance odds per additional treatment day.",
        "Duration is a modifiable driver even when broad initial coverage is justified.",
    ),
    _paper(
        "p10",
        "Time-to-cure with early broad coverage",
        2021,
        "This study examines adults treated empirically for serious bacterial infection.",
        "Broader initial coverage increases the probability of matching the pathogen immediately.",
        "A matched cohort compares time to clinical cure across initial treatment strategies.",
        "A roughly two-day cure advantage may justify temporary breadth in high-risk cases.",
    ),
    _paper(
        "p11",
        "Narrow-spectrum sparing of gut flora",
        2021,
        "This trial covers patients with identified pathogens eligible for targeted antibiotics.",
        "Narrow agents spare commensal organisms while retaining pathogen-directed activity.",
        "A comparative treatment study measures clinical response and microbial diversity.",
        "Targeted therapy can preserve efficacy while reducing ecological harm when diagnosis is known.",
    ),
    _paper(
        "p12",
        "Under-treatment risk in sepsis",
        2019,
        "This study focuses on patients with severe sepsis before pathogen identity is available.",
        "Delayed adequate coverage permits uncontrolled infection and sharply raises mortality.",
        "A time-to-treatment cohort relates coverage delay to risk-adjusted mortality.",
        "The asymmetric immediate danger supports broad first doses for unstable patients.",
    ),
    _paper(
        "p13",
        "Pediatric antibiotic exposure and later allergy",
        2022,
        "This study follows children exposed to broad antibiotics during infancy.",
        "Early microbiome disruption may alter immune development and later allergy risk.",
        "A birth cohort links prescription records with childhood allergy incidence.",
        "Potential developmental effects extend the relevant harm horizon beyond the treated infection.",
    ),
    _paper(
        "p14",
        "Agricultural antibiotic use and community resistance",
        2020,
        "This ecological study compares regions with different levels of agricultural antibiotic use.",
        "Agricultural selection pressure contributes to resistant organisms carried into communities.",
        "Regional usage estimates are associated with surveillance measures of resistance carriage.",
        "Effective stewardship may need to cross the boundary between farms and clinical care.",
    ),
    _paper(
        "p15",
        "Procalcitonin-guided antibiotic cessation",
        2022,
        "This trial includes hospitalized patients whose response can be monitored with procalcitonin.",
        "Biomarker decline identifies when continued antibiotic exposure is unlikely to add benefit.",
        "A randomized stopping-rule trial compares antibiotic-days and adverse outcomes.",
        "Guided cessation reduces exposure without sacrificing measured clinical safety.",
    ),
    _paper(
        "p16",
        "Delayed prescribing in primary care",
        2019,
        "This study covers mild infections managed in primary care with reliable follow-up.",
        "A wait-and-see prescription changes expectations and avoids unnecessary immediate use.",
        "A pragmatic trial compares dispensing, symptom duration, and complication rates.",
        "Many low-risk infections can avoid antibiotics without increasing complications.",
    ),
    _paper(
        "p17",
        "Combination therapy and resistance suppression",
        2021,
        "This study examines difficult infections exposed to single-drug or two-drug regimens.",
        "Simultaneous mechanisms lower the probability that one resistant mutant escapes treatment.",
        "Laboratory and animal experiments measure resistant-mutant emergence under each regimen.",
        "Combination therapy may trade additional toxicity and cost for slower resistance evolution.",
    ),
    _paper(
        "p18",
        "Phage therapy as a narrow alternative",
        2023,
        "This study covers resistant infections with isolates that can be matched to phage cocktails.",
        "Pathogen-specific phages clear target bacteria while sparing commensal organisms.",
        "A compassionate-use series records clearance, safety, and microbiome preservation.",
        "Target-specific alternatives could displace broad drugs when matching is feasible.",
    ),
    _paper(
        "p19",
        "Antibiotics and chemotherapy response via microbiome",
        2022,
        "This study follows cancer patients receiving antibiotics before immunotherapy.",
        "Antibiotic-driven microbiome shifts may blunt immune responses to cancer treatment.",
        "A clinical cohort relates pre-treatment exposure and microbiome profiles to response.",
        "Antibiotic harm may include reduced effectiveness of an otherwise unrelated therapy.",
    ),
    _paper(
        "p20",
        "Machine-learning prediction of resistant infection",
        2023,
        "This study covers patients needing empiric therapy before culture results arrive.",
        "Patient-specific resistance prediction can narrow coverage without ignoring under-treatment risk.",
        "A multisite EHR model is validated for resistance discrimination and transfer.",
        "Reliable prediction could personalize empiric breadth instead of applying one policy to everyone.",
    ),
]

# Each demo facet is a verbatim abstract sentence. This keeps the provenance
# surface honest while allowing the no-provider path to exercise every stage.
DEMO_FACETS: dict[str, list[FacetEvidence]] = {
    paper.id: [
        FacetEvidence(
            facet=facet,
            text=paper.abstract_sentences[index],
            paper_id=paper.id,
            sentence_index=index,
            sentence=paper.abstract_sentences[index],
        )
        for index, facet in enumerate(FACETS)
    ]
    for paper in DEMO_PAPERS
}
