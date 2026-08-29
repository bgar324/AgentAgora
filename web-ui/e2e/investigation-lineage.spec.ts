import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test"

async function startWorkspace(page: Page) {
  await page.goto("/focused")
  await expect(page.getByRole("heading", { name: "Hypothesis Studio" })).toBeVisible()
  await expect(page.getByRole("spinbutton", { name: "Panel size" })).toHaveCount(0)
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page).toHaveURL(/workspace=[a-f0-9]+/)
  await expect(
    page.getByRole("button", { name: "Investigation map" }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Initial Investigation", { exact: true }),
  ).toHaveCount(0)
  const workspaceId = new URL(page.url()).searchParams.get("workspace")
  expect(workspaceId).toBeTruthy()
  const workspace = await page.request.get(
    `/api/focused/workspaces/${workspaceId}`,
  )
  const rootId = (await workspace.json()).active.id as string
  return { rootId, workspaceId: workspaceId! }
}

async function searchDemoLiterature(page: Page) {
  await page.getByRole("button", { name: "Suggest queries" }).click()
  const options = page.getByTestId("suggested-query")
  await expect(options).toHaveCount(5)
  for (let index = 0; index < 3; index += 1) {
    await options.nth(index).click()
  }
  await page.getByRole("button", { name: "Search papers (3)" }).click()
  await expect(page.getByTestId("paper-result").first()).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId("search-brief")).toContainText(
    /papers returned\./,
  )
}

async function addPerspective(page: Page, name: string) {
  const cards = page.getByTestId("paper-result")
  let carried = false
  for (let index = 0; index < (await cards.count()); index += 1) {
    const card = cards.nth(index)
    await card.getByRole("button").first().click()
    const carry = card.getByRole("button", { name: "Add to editor" })
    if ((await carry.count()) > 0 && (await carry.isEnabled())) {
      await carry.click()
      carried = true
      break
    }
  }
  expect(carried).toBeTruthy()
  await page.getByLabel("Job", { exact: true }).fill(name)
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await expect(page.getByTestId("built-perspectives")).toContainText(name)
  await expect(
    page.getByRole("button", { name: `Remove ${name}` }),
  ).toBeVisible()
}


async function applyEdits(page: Page) {
  // Researcher-authored edits apply directly; no confirmation dialog.
  await page.getByRole("button", { name: "Apply edits" }).click()
  await expect(page.getByRole("button", { name: "Apply edits" })).toHaveCount(0)
}

async function applySharedGround(page: Page) {
  // Panel proposals confirm through the current/proposed comparison dialog.
  await page.getByRole("button", { name: "Apply shared ground" }).click()
  const confirmation = page.getByRole("dialog", {
    name: "Apply hypothesis changes?",
  })
  await expect(confirmation).toBeVisible()
  await confirmation
    .getByRole("button", { name: "Apply shared ground" })
    .click()
  await expect(confirmation).toHaveCount(0)
}
const DEMO_QUERIES = [
  "broad-spectrum antibiotic use antimicrobial resistance population",
  "broad-spectrum antibiotics gut microbiome recovery",
  "early broad coverage sepsis mortality cure",
]

const ALL_DEMO_QUERIES = [
  ...DEMO_QUERIES,
  "rapid diagnostics antibiotic de-escalation",
  "antibiotic stewardship cost policy phage combination biomarker targeted therapy",
]

type RoundApiState = {
  agents: Array<{ iid: number; perspective_id: string }>
  deliberations: Array<{
    id: string
    lead_perspective_id: string | null
    threads: Array<{ id: string; facets: string[] }>
    rounds: Array<{ n: number }>
    hypothesis: unknown
    hypothesis_confirmed: boolean
  }>
}

async function requestJson(
  request: APIRequestContext,
  path: string,
  method: "get" | "post" | "put" | "patch",
  data?: unknown,
) {
  const response = await request[method](path, data === undefined ? {} : { data })
  expect(response.ok(), `${method.toUpperCase()} ${path}`).toBeTruthy()
  const payload = await response.json()
  return payload.active ?? payload
}

async function acceptResolutionApi(
  request: APIRequestContext,
  investigationId: string,
  deliberationId: string,
  roundN: number,
) {
  return requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberationId}/rounds/${roundN}/resolution`,
    "put",
    { decision: "accept", summary: null, note: "" },
  )
}

async function acceptThreadResolution(page: Page, roundN: number) {
  const review = page.getByTestId(`thread-${roundN}-resolution-review`)
  await expect(review).toContainText("Awaiting your decision")
  await review.getByRole("button", { name: "Accept resolution" }).click()
  await expect(
    page.getByTestId(`thread-${roundN}-resolution-decision`),
  ).toContainText("Resolution accepted")
}
async function prepareConsensusCheckpoint(
  request: APIRequestContext,
  investigationId: string,
  apply = true,
  facet = "scope",
) {
  let state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/search`,
    "post",
    { queries: DEMO_QUERIES },
  )
  const sharedFacets = state.clusters[0].facets.map(
    (facet: {
      facet: string
      text: string
    }) => ({
      facet: facet.facet,
      text: facet.text,
      paper_id: null,
      sentence_index: null,
      sentence: null,
      edited: true,
    }),
  )
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/perspectives`,
    "post",
    {
      cluster_id: state.clusters[0].id,
      facets: sharedFacets,
      name: "Shared boundary",
    },
  )
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/perspectives`,
    "post",
    {
      cluster_id: state.clusters[1].id,
      facets: sharedFacets,
      name: "Corroborating boundary",
    },
  )
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations`,
    "post",
  )
  const deliberation = state.deliberations[0]
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberation.id}/initialize`,
    "post",
    { lead_perspective_id: state.agents[0].perspective_id },
  )
  const thread = state.deliberations[0].threads.find(
    (candidate: { facets: string[] }) => candidate.facets.includes(facet),
  )
  if (!thread) throw new Error(`Expected a Thread for ${facet}.`)
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberation.id}/rounds`,
    "post",
    { lead_iid: state.agents[0].iid, thread_id: thread.id },
  )
  const preparedRound = state.deliberations[0].rounds.at(-1)
  if (!preparedRound) throw new Error("Expected a completed round.")
  state = await acceptResolutionApi(
    request,
    investigationId,
    deliberation.id,
    preparedRound.n,
  )
  const candidate = state.deliberations[0].hypothesis
  expect(candidate).toBeTruthy()
  if (!apply) return state
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberation.id}/hypothesis`,
    "put",
    { hypothesis: candidate, mode: "apply_pending" },
  )
  return requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberation.id}/hypothesis/checkpoint`,
    "post",
  )
}

async function runAndApplyRound(
  request: APIRequestContext,
  state: RoundApiState,
  investigationId: string,
  facet: "scope" | "explanation" | "approach" | "significance",
) {
  const deliberation = state.deliberations[0]
  const lead = state.agents.find(
    (agent: { perspective_id: string }) =>
      agent.perspective_id === deliberation.lead_perspective_id,
  )
  if (!lead) throw new Error("Expected the configured lead Perspective.")
  const thread = deliberation.threads.find(
    (candidate: { facets: string[] }) => candidate.facets.includes(facet),
  )
  if (!thread) throw new Error(`Expected a Thread for ${facet}.`)
  state = await requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberation.id}/rounds`,
    "post",
    { lead_iid: lead.iid, thread_id: thread.id },
  )
  const completedRound = state.deliberations[0].rounds.at(-1)
  if (!completedRound) throw new Error("Expected a completed round.")
  state = await acceptResolutionApi(
    request,
    investigationId,
    deliberation.id,
    completedRound.n,
  )
  const current = state.deliberations[0]
  if (current.hypothesis_confirmed) return state
  return requestJson(
    request,
    `/api/focused/sessions/${investigationId}/deliberations/${deliberation.id}/hypothesis`,
    "put",
    { hypothesis: current.hypothesis, mode: "apply_pending" },
  )
}

test.beforeEach(async ({ page }) => {
  await page.goto("/focused")
  await page.evaluate(() => localStorage.clear())
})

test("starts a custom Investigation from the problem alone", async ({ page }) => {
  await page.getByRole("checkbox", { name: "Demo mode" }).uncheck()
  await page
    .getByRole("textbox", { name: "Problem" })
    .fill(
      "What trade-off exists between prompt compression and obligation preservation?",
    )
  await expect(
    page.getByRole("textbox", { name: "Research questions" }),
  ).toHaveCount(0)
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page).toHaveURL(/workspace=[a-f0-9]+/)
  const workspaceId = new URL(page.url()).searchParams.get("workspace")
  expect(workspaceId).toBeTruthy()
  const view = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}`,
    "get",
  )
  expect(view.research_questions).toEqual([])
  expect(view.problem).toBe(
    "What trade-off exists between prompt compression and obligation preservation?",
  )
})

test("searches selected derived queries and lists papers directly", async ({
  page,
}) => {
  await startWorkspace(page)
  await searchDemoLiterature(page)
  await expect(page.getByTestId("paper-result")).not.toHaveCount(0)
  await expect(page.getByTestId("paper-results-surface")).toBeVisible()
  await expect(page.getByTestId("cluster-results-surface")).toHaveCount(0)
})


test("builds a Perspective from the selected paper", async ({ page }) => {
  const { rootId } = await startWorkspace(page)
  await searchDemoLiterature(page)
  const source: {
    current: { paper_id?: string; cluster_id?: string | null } | null
  } = { current: null }
  await page.route(
    `**/api/focused/sessions/${rootId}/perspectives`,
    async (route) => {
      if (route.request().method() === "POST") {
        source.current = route.request().postDataJSON()
      }
      await route.continue()
    },
  )

  const paper = page.getByTestId("paper-result").first()
  await paper.getByRole("button").first().click()
  await paper.getByRole("button", { name: "Add to editor" }).click()
  await page.getByRole("button", { name: "Build Perspective" }).click()

  await expect.poll(() => source.current?.paper_id ?? null).not.toBeNull()
  expect(source.current?.cluster_id).toBeNull()
  await expect(page.getByTestId("built-perspectives")).toBeVisible()
})

test("returns from a blocked research branch to its parent panel", async ({
  page,
}) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  const parent = await prepareConsensusCheckpoint(page.request, rootId)
  const question = parent.deliberations[0].recommended_questions[0]
  expect(question).toBeTruthy()

  let child = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}/investigations/${rootId}/questions/${question.id}/child`,
    "post",
  )
  const childId = String(child.id)
  child = await requestJson(
    page.request,
    `/api/focused/sessions/${childId}/search`,
    "post",
    { queries: DEMO_QUERIES },
  )
  child = await requestJson(
    page.request,
    `/api/focused/sessions/${childId}/perspectives`,
    "post",
    {
      cluster_id: child.clusters[0].id,
      facets: child.clusters[0].facets,
    },
  )
  const usedPaperIds = new Set(
    child.perspectives.flatMap(
      (perspective: { sources: string[] }) => perspective.sources,
    ),
  )
  const nextPaper = child.papers.find(
    (paper: { id: string }) => !usedPaperIds.has(paper.id),
  )
  if (!nextPaper) throw new Error("Expected another child paper.")

  await page.reload()
  await expect(page.getByText("Research branch", { exact: true })).toBeVisible()
  const backToPanel = page.getByRole("button", { name: "Back to panel" })
  await expect(backToPanel).toBeVisible()

  const responseReady = Promise.withResolvers<void>()
  const releaseResponse = Promise.withResolvers<void>()
  const responseDelivered = Promise.withResolvers<void>()
  await page.route(
    `**/api/focused/sessions/${childId}/perspectives`,
    async (route) => {
      const response = await route.fetch()
      responseReady.resolve()
      await releaseResponse.promise
      await route.fulfill({ response })
      responseDelivered.resolve()
    },
  )
  const nextPaperCard = page
    .getByTestId("paper-result")
    .filter({ hasText: nextPaper.title })
  await nextPaperCard.getByRole("button").first().click()
  await nextPaperCard
    .getByRole("button", { name: "Add to editor" })
    .click()
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await responseReady.promise
  await expect(backToPanel).toBeDisabled()
  releaseResponse.resolve()
  await responseDelivered.promise
  await expect(backToPanel).toBeEnabled()
  await page.unroute(`**/api/focused/sessions/${childId}/perspectives`)

  await page.getByRole("button", { name: "Add to panel" }).click()
  const restartDialog = page.getByRole("dialog", { name: "Start a new panel" })
  await restartDialog.getByRole("button", { name: "Add to panel" }).click()
  await expect(restartDialog.getByRole("alert")).toContainText(
    "Return to the parent panel and end its current deliberation",
  )
  await restartDialog.getByRole("button", { name: "Cancel" }).click()

  await backToPanel.click()
  await expect(page.locator('[data-testid^="panel-node-"]')).toBeVisible()
  const activeParent = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}`,
    "get",
  )
  expect(activeParent.id).toBe(rootId)
  const savedChild = await requestJson(
    page.request,
    `/api/focused/sessions/${childId}`,
    "get",
  )
  expect(savedChild.integrated_into_parent_at).toBeNull()
})

test("continues an open question on the existing canvas", async ({ page }) => {
  const duplicateKeyWarnings: string[] = []
  const reactFlowWarnings: string[] = []
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      message.text().includes("same key")
    ) {
      duplicateKeyWarnings.push(message.text())
    }
    if (message.text().includes("Couldn't create edge")) {
      reactFlowWarnings.push(message.text())
    }
  })
  const { rootId, workspaceId } = await startWorkspace(page)
  await searchDemoLiterature(page)
  await expect(page.getByTestId("built-perspectives")).toHaveCount(0)
  await addPerspective(page, "Resistance ecology")
  await addPerspective(page, "Host and microbiome")
  await expect(page.getByTestId("built-perspectives")).toContainText(
    "Resistance ecology",
  )
  await expect(page.getByTestId("built-perspectives")).toContainText(
    "Host and microbiome",
  )

  // New workspaces route Continue to the Thread dialogue surface; the
  // legacy panel remains for workspaces that already carry deliberations,
  // so seed one through the API and land on it via reload.
  await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/deliberations`,
    "post",
  )
  await page.reload()
  await expect(
    page.getByRole("dialog", { name: "Choose the focused panel" }),
  ).toHaveCount(0)
  await expect(page.locator('[data-testid^="agent-node-"]')).toHaveCount(2)

  await expect(page.getByRole("button", { name: "Join" })).toBeEnabled()
  await page.getByRole("button", { name: "Join" }).click()
  await expect(
    page.getByRole("heading", { name: "Choose the lead Perspective" }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Confirm lead and generate baseline" })
    .click()
  await expect(page.getByText("Applied, not saved", { exact: true })).toBeVisible()
  const questionInput = page.getByPlaceholder("Ask a question at any point…")
  await questionInput.fill("What should the panel clarify before round one?")
  await page.getByRole("button", { name: "Send" }).click()
  await expect(page.getByTestId("panel-chat-transcript")).toContainText(
    "What should the panel clarify before round one?",
  )
  await expect(questionInput).toBeEnabled({ timeout: 10_000 })

  const roundResponseReady = Promise.withResolvers<void>()
  const releaseRoundResponse = Promise.withResolvers<void>()
  const roundResponseDelivered = Promise.withResolvers<void>()
  const roundRoute =
    `**/api/focused/sessions/${rootId}/deliberations/*/rounds`
  await page.route(roundRoute, async (route) => {
    const response = await route.fetch()
    roundResponseReady.resolve()
    await releaseRoundResponse.promise
    await route.fulfill({ response })
    roundResponseDelivered.resolve()
  })
  await page
    .getByRole("button", { name: /Acute benefit versus ecological harm/ })
    .click()
  await page.getByRole("button", { name: "Start Thread" }).click()
  await questionInput.fill("Which uncertainty remains after this exchange?")
  await page.getByRole("button", { name: "Send" }).click()
  await expect(page.getByTestId("panel-chat-transcript")).toContainText(
    "Queued for after this Thread",
  )
  await roundResponseReady.promise
  await expect(page.getByTestId("round-progress")).toContainText(
    "Saving the completed Thread.",
  )
  await expect(page.getByTestId("round-progress")).toContainText("7/7")
  await expect(page.getByTestId("round-progress")).toContainText(
    "Moderator check",
  )
  await expect(page.getByTestId("round-progress")).toContainText("Unanimous")
  await expect(
    page
      .getByTestId("round-progress")
      .getByText("No substantive shared ground yet.", { exact: true }),
  ).toHaveCount(0)
  releaseRoundResponse.resolve()
  await roundResponseDelivered.promise
  await page.unroute(roundRoute)
  await expect(
    page.getByText("Queued for after this Thread", { exact: true }),
  ).toHaveCount(0, { timeout: 10_000 })
  await expect(questionInput).toBeEnabled({ timeout: 10_000 })

  await expect(page.getByText("Open questions", { exact: true })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText("Update ready", { exact: true })).toBeVisible()
  await expect(page.getByTestId("round-1-summary")).toContainText(
    "The panel compared",
  )
  const firstRoundDiscussion = page.getByTestId("round-1-discussion")
  await expect(firstRoundDiscussion).toContainText("Exchange 1")
  await expect(firstRoundDiscussion).toContainText("Exchange 2")
  await expect(firstRoundDiscussion).toContainText("Moderator check")
  await expect(firstRoundDiscussion).toContainText("Unanimous")
  await expect(firstRoundDiscussion).toContainText("Assumption:")
  await expect(firstRoundDiscussion).toContainText("Replying to T")
  await expect(
    firstRoundDiscussion.getByText(/Challenging T\d+/).first(),
  ).toBeVisible()
  const agreementPrompt = page.getByRole("button", {
    name: "Why this agreement?",
  })
  await expect(agreementPrompt).toBeVisible()
  await agreementPrompt.click()
  await expect(questionInput).toHaveValue(/^Why did the panel agree/)
  await questionInput.fill("")
  const moderatorSummary = page.getByTestId("round-1-summary")
  await expect(
    moderatorSummary.getByText("Thread resolution", { exact: true }),
  ).toBeVisible()
  await expect(
    moderatorSummary.getByText("Moderator synthesis", { exact: true }),
  ).toBeVisible()
  const summaryBox = await page.getByTestId("round-1-summary").boundingBox()
  const discussionBox = await page
    .getByTestId("round-1-discussion")
    .boundingBox()
  expect(summaryBox?.y).toBeGreaterThan(
    (discussionBox?.y ?? 0) + (discussionBox?.height ?? 0),
  )
  await expect(page.getByText("Possible solution", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("dialog", { name: "Rate this deliberation" }),
  ).toHaveCount(0)
  const beforeApply = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  // Panel proposals confirm through the comparison dialog; researcher
  // edits (exercised later) apply directly.
  await page.getByRole("button", { name: "Apply shared ground" }).click()
  const applyConfirmation = page.getByRole("dialog", {
    name: "Apply hypothesis changes?",
  })
  await expect(applyConfirmation).toBeVisible()
  await expect(applyConfirmation).toContainText("Current hypothesis")
  await expect(applyConfirmation).toContainText("Proposed hypothesis")
  await expect(applyConfirmation.getByRole("checkbox")).toHaveCount(0)
  await applyConfirmation
    .getByRole("button", { name: "Apply shared ground" })
    .click()
  await expect(applyConfirmation).toHaveCount(0)
  await expect(page.getByText("Applied, not saved", { exact: true })).toBeVisible()
  const afterApply = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  expect(afterApply.deliberations[0].applied_hypothesis).toEqual(
    beforeApply.deliberations[0].hypothesis,
  )
  await page.getByRole("button", { name: "Save hypothesis" }).click()
  await expect(page.getByText("Saved H1", { exact: true })).toBeVisible()
  await acceptThreadResolution(page, 1)
  await page.keyboard.press("Escape")
  await expect(page.locator('[data-testid^="round-result-node-"]')).toHaveCount(0)
  await expect(page.getByTestId("saved-hypothesis-node-H1")).toHaveCount(0)
  await expect(
    page.locator('[data-testid^="research-problem-node-"]'),
  ).toHaveCount(0)

  await page.getByRole("button", { name: "Add Perspective" }).click()
  const addPerspectiveDialog = page.getByRole("dialog", {
    name: "Add a Perspective",
  })
  await expect(addPerspectiveDialog).toContainText(
    "starts a new deliberation from scratch",
  )
  await expect(
    addPerspectiveDialog.getByRole("button", {
      name: "Resistance ecology",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true")
  await addPerspectiveDialog
    .getByRole("button", { name: "Add Acute outcomes" })
    .click()
  await expect(addPerspectiveDialog).toHaveCount(0)
  await expect(page.locator('[data-testid^="agent-node-"]')).toHaveCount(5)
  const restarted = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  expect(restarted.deliberations[0].rounds).toHaveLength(0)
  expect(restarted.deliberations[0].recommended_questions).toHaveLength(0)
  expect(restarted.deliberations[0].hypothesis).toBeNull()
  expect(restarted.deliberations[0].completion_history).toHaveLength(1)
  expect(restarted.deliberations[0].completion_history[0].reason).toBe(
    "restarted",
  )
  expect(restarted.deliberations[0].completion_history[0].rounds).toHaveLength(
    1,
  )
  expect(restarted.applied_hypothesis_version_id).toBe("H1")
  expect(restarted.deliberations[0].agent_iids).toHaveLength(3)
  await expect(page.locator('[data-testid^="round-result-node-"]')).toHaveCount(0)
  await expect(page.locator('[data-testid^="panel-node-"]')).toHaveCount(2)
  await page.getByRole("button", { name: "Review" }).click()
  const archivedPanel = page.getByRole("dialog", { name: "Panel history" })
  await expect(archivedPanel).toBeVisible()
  await expect(
    archivedPanel.getByRole("region", { name: "Archived Thread 1" }),
  ).toBeVisible()
  await expect(archivedPanel).toContainText("Exchange 1")
  await expect(archivedPanel).toContainText("Moderator check")
  await expect(archivedPanel).toContainText("Last working hypothesis")
  await archivedPanel
    .getByRole("button", { name: "Resistance ecology", exact: true })
    .click()
  await expect(
    page.getByRole("dialog", { name: "Resistance ecology" }).getByText(
      /Lead Perspective · Version/,
    ),
  ).toBeVisible()
  await page.keyboard.press("Escape")
  await page.keyboard.press("Escape")

  await page.getByRole("button", { name: "Join" }).click()
  await page
    .getByRole("button", { name: "Confirm lead and generate baseline" })
    .click()
  await expect(page.getByText("Applied, not saved", { exact: true })).toBeVisible()
  await page
    .getByRole("button", { name: /Mechanism of downstream harm/ })
    .click()
  await page.getByRole("button", { name: "Start Thread" }).click()
  await expect(
    page
      .getByRole("dialog", { name: "Focused panel" })
      .getByText("1 completed Thread", { exact: true }),
  ).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText("Working hypothesis", { exact: true })).toBeVisible()
  await expect(page.getByText("Update ready", { exact: true })).toBeVisible()
  await applySharedGround(page)
  await acceptThreadResolution(page, 1)
  await expect(
    page.getByRole("button", { name: /From Thread 1/ }).first(),
  ).toBeVisible()
  for (const [thread, round] of [
    [/Targeting without delayed cure/, 2],
    [/Acute benefit versus ecological harm/, 3],
    [/Mechanism of downstream harm/, 4],
  ] as const) {
    await page.getByRole("button", { name: thread }).first().click()
    await page.getByRole("button", { name: "Start Thread" }).click()
    await expect(
      page
        .getByRole("dialog", { name: "Focused panel" })
        .getByText(`${round} completed Threads`, { exact: true }),
    ).toBeVisible({ timeout: 30_000 })
    if (await page.getByText("Update ready", { exact: true }).isVisible()) {
      await applySharedGround(page)
    }
    await acceptThreadResolution(page, round)
  }
  await page.getByRole("button", { name: "Save hypothesis" }).click()
  await expect(page.getByText("Saved H2", { exact: true })).toBeVisible()
  await expect(page.getByTestId("saved-hypothesis-node-H2")).toHaveCount(0)
  await expect(
    page.locator('[data-testid^="research-problem-node-"]'),
  ).toHaveCount(0)
  expect(duplicateKeyWarnings).toEqual([])

  await page.getByRole("button", { name: "Review and end" }).click()
  const finalReview = page.getByRole("dialog", {
    name: "Review and end deliberation",
  })
  await expect(finalReview).toBeVisible()
  await expect(finalReview.getByRole("checkbox").first()).not.toBeChecked()
  const beforeEnding = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  const staleQuestion =
    beforeEnding.deliberations[0].recommended_questions.at(-1)
  if (!staleQuestion) throw new Error("Expected an open question to review.")
  await finalReview
    .getByRole("checkbox", { name: staleQuestion.question })
    .check()
  await finalReview.getByRole("button", { name: "Cancel" }).click()
  const staleQuestionCard = page
    .getByTestId("working-hypothesis-sidebar")
    .getByText(staleQuestion.question, { exact: true })
    .locator("xpath=ancestor::article[1]")
  await staleQuestionCard.getByRole("button", { name: "Archive" }).click()
  await expect(staleQuestionCard).toContainText("archived")
  await page.getByRole("button", { name: "Review and end" }).click()
  await expect(finalReview).toBeVisible()
  await expect(
    finalReview.getByRole("checkbox", { name: staleQuestion.question }),
  ).toHaveCount(0)
  await finalReview.getByRole("checkbox").first().check()
  await finalReview.getByRole("button", { name: "Confirm and end" }).click()
  const scoring = page.getByRole("dialog", { name: "Rate this deliberation" })
  await expect(scoring).toBeVisible()
  await scoring
    .getByRole("group", { name: "Divergent thinking" })
    .getByRole("radio", { name: "6" })
    .check()
  await scoring
    .getByRole("group", { name: "Convergent thinking" })
    .getByRole("radio", { name: "5" })
    .check()
  await scoring.getByRole("button", { name: "Save scores" }).click()
  await expect(scoring).toHaveCount(0)

  const rated = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  const completed = rated.deliberations[0]
  expect(completed.completed_at).toBeTruthy()
  expect(completed.final_hypothesis_version_id).toBe("H2")
  expect(completed.rating).toMatchObject({ divergent: 6, convergent: 5 })
  expect(completed.rounds[0]).not.toHaveProperty("rating")
  expect(
    completed.rounds.map(
      (round: { participant_iids: number[] }) => round.participant_iids.length,
    ),
  ).toEqual([3, 3, 3, 3])
  expect(
    completed.completion_history[0].rounds.map(
      (round: { participant_iids: number[] }) => round.participant_iids.length,
    ),
  ).toEqual([2])
  const sourceQuestionId = String(completed.recommended_questions[0].id)
  expect(completed.selected_question_ids).toEqual([sourceQuestionId])
  expect(completed.recommended_questions[0].selected_for_followup).toBe(true)
  expect(completed.document).toBeTruthy()
  expect(
    completed.document.sections.map((section: { title: string }) => section.title),
  ).toEqual([
    "Targeting without delayed cure",
    "Acute benefit versus ecological harm",
    "Mechanism of downstream harm",
  ])
  expect(completed.document.open_questions.length).toBeGreaterThan(0)

  await page.keyboard.press("Escape")
  await expect(page.getByTestId("saved-hypothesis-node-H2")).toBeVisible()
  await expect(page.getByTestId("saved-hypothesis-node-H1")).toHaveCount(0)
  await expect(page.locator('[data-testid^="round-result-node-"]')).toHaveCount(0)
  const researchNode = page.getByTestId(
    `research-problem-node-${sourceQuestionId}`,
  )
  await expect(researchNode).toBeVisible()
  await page
    .getByTestId(`panel-node-panel-${completed.id}`)
    .getByRole("button", { name: "Review" })
    .click()
  const endedDrawer = page.getByRole("dialog", { name: "Focused panel" })
  const updateScores = endedDrawer.getByRole("button", { name: "Update scores" })
  await expect(updateScores).toBeVisible()
  const documentSection = endedDrawer.getByTestId("deliberation-document")
  await expect(documentSection).toBeVisible()
  await expect(documentSection).toContainText("Final document")
  await expect(documentSection).toContainText("Hypotheses")
  await expect(documentSection).toContainText("H1.")
  await expect(documentSection).toContainText("Open questions")
  const scoreActionLayout = await updateScores.evaluate((element) => ({
    whiteSpace: getComputedStyle(element).whiteSpace,
    height: element.getBoundingClientRect().height,
  }))
  expect(scoreActionLayout.whiteSpace).toBe("nowrap")
  expect(scoreActionLayout.height).toBeLessThanOrEqual(32)
  const startPaperSearch = endedDrawer
    .getByRole("button", { name: "Start paper search" })
    .first()
  await expect(startPaperSearch).toBeVisible()
  await startPaperSearch.click()
  await expect(page.getByText("Research branch", { exact: true })).toBeVisible()
  await expect(
    page.getByText(/Build Perspectives from fresh papers, then return/),
  ).toBeVisible()
  const activeBranch = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}`,
    "get",
  )
  const childId = String(activeBranch.id)
  expect(childId).not.toBe(rootId)
  await expect(
    page.getByRole("combobox", { name: "Switch Investigation" }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Perspective matrix (0)", { exact: true }),
  ).toHaveCount(0)

  await page.getByRole("button", { name: "Investigation map" }).click()
  await expect(page.locator('[data-testid^="investigation-node-"]')).toHaveCount(2)
  await expect(page.locator(".react-flow__edge")).toHaveCount(1)
  await expect(page.getByTestId(`investigation-node-${childId}`)).toContainText(
    "Open now",
  )
  await expect(page.getByTestId(`investigation-node-${childId}`)).toContainText(
    "0 papers",
  )

  await page.getByRole("button", { name: "Open current Investigation" }).click()
  await searchDemoLiterature(page)
  await addPerspective(page, "Diagnostics and targeting")
  await page.getByRole("button", { name: "Add to panel", exact: true }).click()
  const inviteDialog = page.getByRole("dialog", { name: "Start a new panel" })
  await expect(
    inviteDialog.getByRole("button", {
      name: "Resistance ecology",
      exact: true,
    }),
  ).toHaveAttribute("aria-pressed", "true")
  await inviteDialog.getByRole("button", { name: "Add to panel" }).click()
  const activeParent = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}`,
    "get",
  )
  expect(activeParent.id).toBe(rootId)
  await expect(page.locator('[data-testid^="agent-node-"]')).toHaveCount(9)
  await expect(page.locator('[data-testid^="round-result-node-"]')).toHaveCount(0)
  const continuedState = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  expect(continuedState.applied_hypothesis_version_id).toBe("H2")
  expect(continuedState.deliberations[0].rounds).toHaveLength(0)
  expect(continuedState.deliberations[0].completion_history).toHaveLength(2)
  expect(continuedState.deliberations[0].completed_at).toBeNull()
  expect(continuedState.deliberations[0].agent_iids).toHaveLength(4)
  expect(
    continuedState.deliberations[0].completion_history[1]
      .recommended_questions[0].status,
  ).toBe("addressed")
  const importedPerspective = continuedState.perspectives.find(
    (perspective: { source_question_id: string | null }) =>
      perspective.source_question_id === sourceQuestionId,
  )
  expect(importedPerspective).toBeTruthy()
  const importedAgent = continuedState.agents.find(
    (agent: { perspective_id: string }) =>
      agent.perspective_id === importedPerspective.id,
  )
  expect(importedAgent).toBeTruthy()
  await expect(page.locator('[data-testid^="panel-node-"]')).toHaveCount(3)
  const historicalHypothesis = page.getByTestId("saved-hypothesis-node-H2")
  await expect(historicalHypothesis).toBeVisible()
  await expect
    .poll(() =>
      historicalHypothesis.evaluate(
        (element) => getComputedStyle(element).backgroundColor,
      ),
    )
    .toBe("rgb(236, 253, 243)")
  const sourceProblemBox = await researchNode.boundingBox()
  const importedAgentBox = await page
    .getByTestId(`agent-node-${importedAgent.iid}`)
    .boundingBox()
  expect(importedAgentBox?.x).toBeGreaterThan(
    (sourceProblemBox?.x ?? 0) + (sourceProblemBox?.width ?? 0),
  )
  const integratedChild = await requestJson(
    page.request,
    `/api/focused/sessions/${childId}`,
    "get",
  )
  expect(integratedChild.integrated_into_parent_at).toBeTruthy()
  await page.getByRole("button", { name: "Investigation map" }).click()
  await page.getByTestId(`investigation-node-${childId}`).click()
  await expect(
    page.getByText(
      "This branch has already been added to the parent and is read-only.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Continued", exact: true }),
  ).toBeDisabled()
  await page.getByRole("button", { name: "Investigation map" }).click()
  await page.getByTestId(`investigation-node-${rootId}`).click()
  await page.getByRole("button", { name: "Join" }).click()
  const drawer = page.getByRole("dialog", { name: "Focused panel" })
  await expect(drawer).toBeVisible()
  const conversation = page.getByTestId("panel-conversation-scroll")
  await expect(conversation).toBeVisible()
  await expect(
    drawer.getByText(
      "Complete a Thread before reviewing and ending the deliberation.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(
    drawer.getByRole("button", { name: "Review and end" }),
  ).toBeDisabled()
  const hypothesisSidebar = page.getByTestId("working-hypothesis-sidebar")
  const sidebarLayout = await hypothesisSidebar.evaluate((element) => {
    const styles = getComputedStyle(element)
    return {
      borderLeftWidth: styles.borderLeftWidth,
      overflowY: styles.overflowY,
    }
  })
  expect(sidebarLayout).toEqual({
    borderLeftWidth: "1px",
    overflowY: "auto",
  })
  await expect(page.getByTestId("panel-chat-bar")).toHaveCount(0)
  const sidebarBottomGap = await drawer.evaluate((surface) => {
    const sidebar = surface.querySelector(
      '[data-testid="working-hypothesis-sidebar"]',
    )
    if (!sidebar) return null
    const drawerRect = surface.getBoundingClientRect()
    const sidebarRect = sidebar.getBoundingClientRect()
    return Math.round(drawerRect.bottom - sidebarRect.bottom)
  })
  expect(
    Math.abs(sidebarBottomGap ?? Number.POSITIVE_INFINITY),
  ).toBeLessThanOrEqual(1)
  await expect
    .poll(() => hypothesisSidebar.evaluate((element) => element.scrollTop))
    .toBe(0)
  await expect
    .poll(() => conversation.evaluate((element) => element.scrollTop))
    .toBe(0)
  await expect(
    drawer.getByRole("combobox", { name: /Status for/ }),
  ).toHaveCount(0)
  await expect(
    drawer.locator('[data-hypothesis-part="hypothesis"]'),
  ).toContainText("Not established yet.")
  await page.keyboard.press("Escape")
  await expect(drawer).toHaveCount(0)
  expect(reactFlowWarnings).toEqual([])
})

test("promotes and merges versioned hypotheses through the workspace map", async ({
  page,
}) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  const pendingRoot = await prepareConsensusCheckpoint(
    page.request,
    rootId,
    false,
  )
  expect(pendingRoot.deliberations[0].hypothesis_confirmed).toBe(false)
  await page.goto(`/focused?workspace=${workspaceId}`)
  await page.getByRole("button", { name: "Join" }).click()
  await applySharedGround(page)
  await expect(page.getByText("Applied, not saved", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Save hypothesis" }).click()
  await expect(page.getByText("Saved H1", { exact: true })).toBeVisible()
  await page.keyboard.press("Escape")
  const root = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  expect(root.applied_hypothesis_version_id).toBe("H1")
  const question = root.deliberations[0].recommended_questions[0]
  const childView = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}/investigations/${rootId}/questions/${question.id}/child`,
    "post",
  )
  const childId = childView.id as string
  await page.goto(`/focused?workspace=${workspaceId}`)
  await page.getByRole("button", { name: "Investigation map" }).click()
  await expect(page.getByTestId(`investigation-node-${childId}`)).toContainText(
    "Inherits H1",
  )

  const child = await prepareConsensusCheckpoint(
    page.request,
    childId,
    true,
    "approach",
  )
  expect(child.applied_hypothesis_version_id).toBe("H2")
  await page.reload()
  await expect(page.getByTestId("root-research-problem-node")).toContainText(
    question.question,
  )
  await page.getByRole("button", { name: "Investigation map" }).click()

  const h1 = page.getByTestId("hypothesis-version-H1")
  const h2 = page.getByTestId("hypothesis-version-H2")
  await expect(h1).toBeVisible()
  await expect(h2).toBeVisible()
  await h2.getByRole("button", { name: "Promote" }).click()
  await expect(h2).toContainText("Promoted")

  const parent = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}`,
    "get",
  )
  expect(parent.deliberations[0].recommended_questions[0].status).toBe("addressed")

  await h1.getByRole("button", { name: "Compare and merge" }).click()
  await expect(page.getByText("Compare H1 with H2", { exact: true })).toBeVisible()
  await page
    .getByRole("textbox", { name: "Combined hypothesis" })
    .fill("Combine the parent and child solution candidates in one testable intervention.")
  await page.getByRole("button", { name: "Save merged hypothesis" }).click()

  const h3 = page.getByTestId("hypothesis-version-H3")
  await expect(h3).toBeVisible()
  await expect(h3).toContainText("Promoted")
  await expect(h3).toContainText("from H2 + H1")

  await h2.getByRole("button", { name: "Archive" }).click()
  const archiveDialog = page.getByRole("dialog", { name: "Archive H2?" })
  await expect(archiveDialog).toBeVisible()
  await archiveDialog.getByRole("button", { name: "Cancel" }).click()
  await expect(h2).toBeVisible()
  await h2.getByRole("button", { name: "Archive" }).click()
  await archiveDialog.getByRole("button", { name: "Archive hypothesis" }).click()
  await expect(h2).toHaveCount(0)
  await page.getByRole("button", { name: "Restore" }).click()
  await expect(page.getByTestId("hypothesis-version-H2")).toBeVisible()
})




test("allows ending after one completed area", async ({ page }) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  await prepareConsensusCheckpoint(page.request, rootId, false)
  await page.goto(`/focused?workspace=${workspaceId}`)
  await page.getByRole("button", { name: "Join" }).click()
  await applySharedGround(page)
  await page.getByRole("button", { name: "Save hypothesis" }).click()

  const reviewButton = page.getByRole("button", { name: "Review and end" })
  await expect(reviewButton).toBeEnabled()
  await reviewButton.click()
  const finalReview = page.getByRole("dialog", {
    name: "Review and end deliberation",
  })
  await finalReview.getByRole("button", { name: "Confirm and end" }).click()
  await expect(page.getByText("Deliberation ended", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Why this agreement?" }),
  ).toHaveCount(0)
  await expect(
    page.getByPlaceholder("Ask a question at any point…"),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Start paper search" }),
  ).toHaveCount(0)
  await expect(
    page.getByText("Not selected for follow-up.", { exact: true }),
  ).toBeVisible()
})
test("shows a direct agent reply in the panel conversation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const { rootId, workspaceId } = await startWorkspace(page)
  const state = await prepareConsensusCheckpoint(page.request, rootId, false)
  const agent = state.agents[0]
  const perspective = state.perspectives.find(
    (item: { id: string }) => item.id === agent.perspective_id,
  )
  await page.route(`**/api/focused/sessions/${rootId}/chat`, async (route) => {
    expect(route.request().postDataJSON().target_iid).toBe(agent.iid)
    const response = await route.fetch()
    const payload = await response.json()
    const deliberation = payload.active.deliberations.find(
      (item: { id: string }) => item.id === state.deliberations[0].id,
    )
    deliberation.chat.at(-1).text =
      "**Bounded claim.**\n\n1. First condition\n2. Second condition"
    const { promise: delay, resolve } = Promise.withResolvers<void>()
    setTimeout(resolve, 750)
    await delay
    await route.fulfill({ response, json: payload })
  })


  await page.goto(`/focused?workspace=${workspaceId}`)
  await page.getByRole("button", { name: "Join" }).click()
  await page
    .getByRole("combobox", { name: "Message recipient" })
    .selectOption(String(agent.iid))
  await page
    .getByPlaceholder("Ask a question at any point…")
    .fill("What does *bounded* evidence mean?")
  await page.getByRole("button", { name: "Send" }).click()

  const transcript = page.getByTestId("panel-chat-transcript")
  await expect(transcript).toBeVisible({ timeout: 300 })
  await expect(transcript).toContainText("What does *bounded* evidence mean?")
  await expect(transcript).toContainText("Thinking…")
  await expect(transcript.locator(".animate-spin")).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled()

  const reply = transcript.getByText("Bounded claim.", { exact: true })
  await expect(reply).toBeVisible()
  await expect(reply).toBeInViewport()
  await expect(transcript.locator("strong")).toHaveText("Bounded claim.")
  await expect(transcript.locator("ol > li")).toHaveCount(2)
  await expect(transcript).toContainText(perspective.name)
  await expect(transcript.getByText("Thinking…")).toHaveCount(0)
})


test("edits an applied hypothesis without reusing pending-update semantics", async ({
  page,
}) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  await prepareConsensusCheckpoint(page.request, rootId, false)
  await page.goto(`/focused?workspace=${workspaceId}`)
  await page.getByRole("button", { name: "Join" }).click()
  await applySharedGround(page)
  const boundaryThread = page.getByRole("button", {
    name: /Acute benefit versus ecological harm.*Thread 1/,
  })
  await expect(page.getByText("1/4 discussed", { exact: true })).toBeVisible()
  await expect(boundaryThread).toBeEnabled()
  await boundaryThread.click()
  await expect(boundaryThread).toHaveAttribute("aria-pressed", "true")
  await boundaryThread.click()
  await expect(boundaryThread).toHaveAttribute("aria-pressed", "false")
  await page.getByRole("button", { name: "Save hypothesis" }).click()
  await page.getByRole("button", { name: "Edit hypothesis" }).click()
  await expect(
    page.getByRole("button", { name: "Apply edits" }),
  ).toBeDisabled()
  await page.getByRole("button", { name: "Cancel editing" }).click()
  await expect(page.getByRole("button", { name: "Edit hypothesis" })).toBeVisible()
  await page.getByRole("button", { name: "Edit hypothesis" }).click()
  await page
    .getByRole("textbox", { name: "Possible solution hypothesis step" })
    .fill("Researcher-edited solution candidate")
  await applyEdits(page)
  await page.getByRole("button", { name: "Save hypothesis" }).click()
  await page.keyboard.press("Escape")
  const workspace = await page.request.get(
    `/api/focused/workspaces/${workspaceId}`,
  )
  const workspaceState = (await workspace.json()).workspace
  expect(workspaceState.promoted_hypothesis_version_id).toBe("H2")
  const edited = workspaceState.hypothesis_versions.find(
    (version: { id: string }) => version.id === "H2",
  )
  expect(edited.step_sources).toEqual({ hypothesis: "H2" })
})


test("restores a workspace from its URL and deletes it on reset", async ({ page }) => {
  const { workspaceId } = await startWorkspace(page)
  await expect(page).toHaveURL(new RegExp(`workspace=${workspaceId}`))

  await page.reload()
  await expect(
    page.getByRole("button", { name: "Investigation map" }),
  ).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Suggest queries" })).toBeVisible()
  await expect(page.getByRole("spinbutton", { name: "Panel size" })).toHaveCount(0)

  const startOver = page.getByRole("button", { name: "Start over" })
  await startOver.focus()
  await page.keyboard.press("Enter")
  const resetDialog = page.getByRole("dialog", { name: "Start over?" })
  await expect(resetDialog).toBeVisible()
  await page.keyboard.press("Shift+Tab")
  await expect(
    resetDialog.getByRole("button", { name: "Reset workspace" }),
  ).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(resetDialog).toHaveCount(0)
  await expect(startOver).toBeFocused()

  await startOver.click()
  await resetDialog.getByRole("button", { name: "Reset workspace" }).click()
  await expect(page.getByRole("spinbutton", { name: "Panel size" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
  await expect(page).not.toHaveURL(/workspace=/)

  const response = await page.request.get(
    `/api/focused/workspaces/${workspaceId}`,
  )
  expect(response.status()).toBe(404)
})

test("automatically recovers from a brief API restart", async ({ page }) => {
  const { workspaceId } = await startWorkspace(page)
  const routePattern = `**/api/focused/workspaces/${workspaceId}`
  let attempts = 0
  await page.route(routePattern, (route) => {
    attempts += 1
    if (attempts < 3) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "API restarting" }),
      })
    }
    return route.continue()
  })

  await page.reload()
  await expect(page.getByRole("button", { name: "Suggest queries" })).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "Couldn’t open this workspace" }),
  ).toHaveCount(0)
  expect(attempts).toBe(3)
})


test("preserves a workspace pointer across transient restore failures", async ({
  page,
}) => {
  const { workspaceId } = await startWorkspace(page)
  const routePattern = `**/api/focused/workspaces/${workspaceId}`
  await page.route(routePattern, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "API temporarily unavailable" }),
    }),
  )

  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Couldn’t open this workspace" }),
  ).toBeVisible()
  await expect(
    page.getByText(
      "We couldn’t load it. Try again, or begin a new Investigation.",
      { exact: true },
    ),
  ).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`workspace=${workspaceId}`))
  await expect
    .poll(() =>
      page.evaluate(() => localStorage.getItem("focused-workspace")),
    )
    .toBe(workspaceId)

  await page.unroute(routePattern)
  await page.getByRole("button", { name: "Try again" }).click()
  await expect(page.getByRole("button", { name: "Suggest queries" })).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Investigation map" }),
  ).toHaveCount(0)
})


test("uses one primary header action without an export menu", async ({ page }) => {
  await startWorkspace(page)
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Start over", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Workspace menu" }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Export workspace" }),
  ).toHaveCount(0)
})


test("reloads the authoritative workspace after a revision conflict", async ({
  page,
}) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  const latestResponse = await page.request.get(
    `/api/focused/workspaces/${workspaceId}`,
  )
  const latest = await latestResponse.json()
  latest.workspace.problem = "Reloaded workspace state"
  latest.active.problem = "Reloaded workspace state"

  await page.route(
    `**/api/focused/sessions/${rootId}/suggest-queries`,
    (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail:
            "This workspace changed in another process. Its latest state was reloaded.",
        }),
      }),
  )
  await page.route(
    `**/api/focused/workspaces/${workspaceId}`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(latest),
      }),
  )

  await page.getByRole("button", { name: "Suggest queries" }).click()
  await expect(
    page.getByText(/This workspace changed in another process/),
  ).toBeVisible()
  await expect(
    page.getByText("Reloaded workspace state", { exact: true }),
  ).toBeVisible()
})


test("keeps repeated questions distinct while promoting the selected follow-up", async ({ page }) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  let state = await prepareConsensusCheckpoint(
    page.request,
    rootId,
    true,
    "scope",
  )
  const deliberation = state.deliberations[0]
  const firstQuestion = deliberation.recommended_questions[0]
  expect(firstQuestion.source_round).toBe(1)
  state = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}/investigations/${rootId}/questions/${firstQuestion.id}`,
    "patch",
    { status: "archived" },
  )
  state = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/deliberations/${deliberation.id}/rounds`,
    "post",
    {
      lead_iid: state.agents[0].iid,
      thread_id: state.deliberations[0].threads[0].id,
    },
  )
  state = await acceptResolutionApi(
    page.request,
    rootId,
    deliberation.id,
    2,
  )
  const repeated = state.deliberations[0].recommended_questions.filter(
    (question: { question: string }) =>
      question.question === firstQuestion.question,
  )
  expect(repeated).toHaveLength(2)
  expect(repeated.map((question: { source_round: number }) => question.source_round)).toEqual([
    1,
    2,
  ])
  state = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/deliberations/${deliberation.id}/hypothesis`,
    "put",
    {
      hypothesis: state.deliberations[0].hypothesis,
      mode: "apply_pending",
    },
  )
  for (const facet of ["explanation", "approach", "significance"] as const) {
    state = await runAndApplyRound(page.request, state, rootId, facet)
  }
  state = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/deliberations/${deliberation.id}/hypothesis/checkpoint`,
    "post",
  )
  await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/deliberations/${deliberation.id}/complete`,
    "post",
    { selected_question_ids: [repeated[1].id] },
  )

  await page.goto(`/focused?workspace=${workspaceId}`)
  await expect(
    page
      .locator('[data-testid^="research-problem-node-"]')
      .filter({ hasText: firstQuestion.question }),
  ).toHaveCount(1)
  await expect(
    page.getByTestId(`research-problem-node-${repeated[1].id}`),
  ).toBeVisible()
})


test("allows a focused panel with more than three Perspectives", async ({
  page,
}) => {
  const { rootId, workspaceId } = await startWorkspace(page)
  let state = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/search`,
    "post",
    { queries: ALL_DEMO_QUERIES },
  )
  expect(state.papers.length).toBeGreaterThanOrEqual(5)
  for (const paper of state.papers.slice(0, 5)) {
    state = await requestJson(
      page.request,
      `/api/focused/sessions/${rootId}/perspectives`,
      "post",
      { paper_id: paper.id },
    )
  }

  await page.reload()
  await expect(
    page.getByTestId("built-perspectives").locator("article"),
  ).toHaveCount(5)
  await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/deliberations`,
    "post",
  )
  await page.reload()
  await expect(
    page.getByRole("dialog", { name: "Choose the focused panel" }),
  ).toHaveCount(0)
  await expect(page.locator('[data-testid^="agent-node-"]')).toHaveCount(5)
  await expect(page.getByRole("button", { name: "Join" })).toBeEnabled()
  await expect(page).toHaveURL(new RegExp(`workspace=${workspaceId}`))
})


test("keeps detail and branched map surfaces inside a mobile viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const { rootId, workspaceId } = await startWorkspace(page)
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(390)
  const root = await prepareConsensusCheckpoint(page.request, rootId)
  const question = root.deliberations[0].recommended_questions[0]
  await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}/investigations/${rootId}/questions/${question.id}/child`,
    "post",
  )
  await page.reload()
  await page.getByRole("button", { name: "Map" }).click()
  await expect(page.getByText("Follow questions without flattening the research")).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(390)
  await expect(page.getByTestId(/investigation-node-/)).toHaveCount(2)
})
