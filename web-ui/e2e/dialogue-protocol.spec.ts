import { expect, test, type APIRequestContext, type Page } from "@playwright/test"

const PROBLEM =
  "Should antibiotics be prescribed broadly? I suspect the faster cure trades off against resistance and gut-flora harm."

const DEMO_QUERY =
  "broad-spectrum antibiotic use antimicrobial resistance population"

async function requestJson(
  request: APIRequestContext,
  path: string,
  method: "get" | "post",
  data?: unknown,
) {
  const response = await request[method](
    path,
    data === undefined ? {} : { data },
  )
  expect(response.ok(), `${method.toUpperCase()} ${path}`).toBeTruthy()
  const payload = await response.json()
  return payload.active ?? payload
}

/** Demo workspace with three Perspectives, corpus seeded through the API. */
async function dialogueWorkspace(page: Page) {
  const view = await page.request.post("/api/focused/workspaces", {
    data: { problem: PROBLEM, research_questions: [], demo: true },
  })
  expect(view.ok()).toBeTruthy()
  const payload = await view.json()
  const workspaceId = payload.workspace.id as string
  const rootId = payload.active.id as string
  let state = await requestJson(
    page.request,
    `/api/focused/sessions/${rootId}/search`,
    "post",
    { queries: [DEMO_QUERY] },
  )
  for (const cluster of state.clusters.slice(0, 3)) {
    state = await requestJson(
      page.request,
      `/api/focused/sessions/${rootId}/perspectives`,
      "post",
      { cluster_id: cluster.id },
    )
  }
  expect(state.perspectives.length).toBe(3)
  await page.goto(`/focused?workspace=${workspaceId}`)
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeEnabled()
  return { workspaceId, rootId }
}

test("runs the thread dialogue protocol end to end", async ({ page }) => {
  const { workspaceId } = await dialogueWorkspace(page)

  // Continue opens the informatory modal instead of swapping the stage.
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  const intro = page.getByRole("dialog", { name: "Set up the panel" })
  await expect(intro).toBeVisible()
  await expect(
    page.getByRole("button", { name: "Load demo queries" }),
  ).toHaveCount(0) // searched workspace: the modal floats over the summary

  // Opening phase: proposals -> peer review -> refinement.
  await intro.getByRole("button", { name: "Start deliberation" }).click()
  await expect(page.getByText("Choose the directions")).toBeVisible({
    timeout: 30_000,
  })
  await expect(intro).toHaveCount(0)
  const cards = page.locator("label", { hasText: "Peer review" })
  await expect(cards).toHaveCount(3)
  await expect(page.getByText("3 of 3 selected")).toBeVisible()

  // Selection -> Working Document with suggested Threads.
  await page
    .getByRole("button", { name: "Create Working Document" })
    .click()
  await expect(page.getByTestId("dialogue-document-panel")).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByTestId("dialogue-thread-card")).toHaveCount(3)
  await expect(page.getByText("Working Document · v1")).toBeVisible()

  // Open a Thread: every Perspective answers, the panel exchanges,
  // and a pending resolution awaits the researcher.
  const firstCard = page.getByTestId("dialogue-thread-card").first()
  const threadTitle = (
    await firstCard.locator("p").first().textContent()
  )?.trim()
  await firstCard.getByRole("button", { name: "Open Thread" }).click()
  const conversation = page.getByTestId("dialogue-conversation")
  await expect(conversation).toBeVisible({ timeout: 30_000 })
  if (threadTitle) {
    await expect(
      conversation.getByRole("heading", { name: threadTitle }),
    ).toBeVisible()
  }
  await expect(conversation.getByText("Answers the question")).toHaveCount(3)
  await expect(conversation.getByText(/Reply · to /).first()).toBeVisible()
  const resolution = page.getByTestId("dialogue-resolution-card")
  await expect(resolution).toBeVisible()
  await expect(resolution.getByText("Consensus.")).toBeVisible()

  // The researcher challenges; the targeted panelist replies and the
  // pending resolution is re-synthesized.
  await conversation
    .getByRole("textbox", { name: "Message the panel" })
    .fill("Why should the narrower boundary hold across settings?")
  await conversation.getByRole("button", { name: "Send" }).click()
  await expect(conversation.getByText("Challenge · to ")).toBeVisible({
    timeout: 30_000,
  })
  await expect(conversation.getByText("Reply · to Researcher")).toBeVisible()

  // Accept & close: document folds, reflections run, open questions
  // return as new suggested Threads.
  await resolution.getByRole("button", { name: "Accept & close" }).click()
  await expect(page.getByText("Resolved", { exact: true })).toBeVisible({
    timeout: 30_000,
  })
  await expect(
    page.getByTestId("dialogue-thread-card").first(),
  ).toBeVisible()
  const remaining = await page.getByTestId("dialogue-thread-card").count()
  expect(remaining).toBeGreaterThanOrEqual(3)
  await expect(page.getByText(/Working Document · v[2-9]/)).toBeVisible()

  // The moderator's final Document.
  await page.getByRole("button", { name: "Final report" }).click()
  const report = page.getByRole("dialog", { name: "Final report" })
  await expect(report).toBeVisible()
  await expect(report.getByText("Hypotheses")).toBeVisible({
    timeout: 15_000,
  })
  await expect(report.getByText("H1.")).toBeVisible()
  await expect(report.getByText("Open Questions")).toBeVisible()
  await page.keyboard.press("Escape")

  // The dialogue survives a reload.
  await page.reload()
  await expect(page.getByTestId("dialogue-document-panel")).toBeVisible()
  await expect(page.getByText("Resolved", { exact: true })).toBeVisible()

  // The workspace still reports the canonical state over the API.
  const state = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}`,
    "get",
  )
  expect(state.dialogue.stage).toBe("deliberation")
  expect(
    state.dialogue.threads.some(
      (thread: { status: string }) => thread.status === "closed",
    ),
  ).toBeTruthy()
})

test("keep open continues the discussion before closing", async ({
  page,
}) => {
  await dialogueWorkspace(page)
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await page
    .getByRole("dialog", { name: "Set up the panel" })
    .getByRole("button", { name: "Start deliberation" })
    .click()
  await expect(page.getByText("Choose the directions")).toBeVisible({
    timeout: 30_000,
  })
  await page.getByRole("button", { name: "Create Working Document" }).click()
  await expect(page.getByTestId("dialogue-thread-card").first()).toBeVisible({
    timeout: 30_000,
  })
  await page
    .getByTestId("dialogue-thread-card")
    .first()
    .getByRole("button", { name: "Open Thread" })
    .click()
  const resolution = page.getByTestId("dialogue-resolution-card")
  await expect(resolution).toBeVisible({ timeout: 30_000 })

  // Keep the Thread open: the resolution is set aside, the discussion
  // stays live, and a later message re-pends a fresh resolution.
  await resolution.getByRole("button", { name: "Keep open" }).click()
  await expect(resolution).toHaveCount(0, { timeout: 30_000 })
  const conversation = page.getByTestId("dialogue-conversation")
  await expect(conversation).toBeVisible()
  await conversation
    .getByRole("textbox", { name: "Message the panel" })
    .fill("Name the strongest counter-evidence before we close.")
  await conversation.getByRole("button", { name: "Send" }).click()
  await expect(page.getByTestId("dialogue-resolution-card")).toBeVisible({
    timeout: 30_000,
  })
  await page
    .getByTestId("dialogue-resolution-card")
    .getByRole("button", { name: "Accept & close" })
    .click()
  await expect(page.getByText("Resolved", { exact: true })).toBeVisible({
    timeout: 30_000,
  })
})
