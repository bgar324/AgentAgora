import { expect, test, type APIRequestContext, type Page } from "@playwright/test"

const PROBLEM =
  "Should antibiotics be prescribed broadly? I suspect the faster cure trades off against resistance and gut-flora harm."

const DEMO_QUERY =
  "broad-spectrum antibiotic use antimicrobial resistance population"

const POSITION = {
  framing: "Prescribing breadth is an evolutionary-pressure problem.",
  prior: "Cohorts link broad days to resistance without pricing benefit.",
  method: "Compare severity-matched cohorts on resistome and time-to-cure.",
  expected: "Narrower first-line holds outcomes outside sepsis.",
}

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

/** Demo workspace carrying a four-part position and three Perspectives. */
async function notepadWorkspace(page: Page, arm: "baseline" | "guided") {
  const view = await page.request.post("/api/focused/workspaces", {
    data: {
      problem: PROBLEM,
      research_questions: [],
      position: POSITION,
      arm,
      demo: true,
    },
  })
  expect(view.ok()).toBeTruthy()
  const payload = await view.json()
  const workspaceId = payload.workspace.id as string
  const rootId = payload.active.id as string
  expect(payload.active.arm).toBe(arm)
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

async function openGroupChat(page: Page) {
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await page.getByRole("button", { name: /Open the group chat/ }).click()
  await expect(page.getByTestId("notepad-conversation")).toBeVisible({
    timeout: 30_000,
  })
}

test("the input screen collects the problem and a four-part position", async ({
  page,
}) => {
  await page.goto("/focused")
  for (const label of [
    "Framing",
    "Previous work",
    "Methodology",
    "Expected results",
  ]) {
    await expect(page.getByLabel(label, { exact: true })).toBeVisible()
  }
  // The arm is a visible choice, and only one is active at a time.
  const guided = page.getByRole("button", { name: "Perspective-guided" })
  const baseline = page.getByRole("button", { name: "Unguided baseline" })
  await expect(guided).toHaveAttribute("aria-pressed", "true")
  await baseline.click()
  await expect(baseline).toHaveAttribute("aria-pressed", "true")
  await expect(guided).toHaveAttribute("aria-pressed", "false")
})

test("three columns carry the notepad, the chat, and the Perspectives", async ({
  page,
}) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)

  await expect(page.getByTestId("notepad-panel")).toBeVisible()
  await expect(page.getByTestId("notepad-perspectives")).toBeVisible()

  // v1 is seeded from the input screen, not blank.
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    POSITION.framing,
  )
  await expect(page.getByTestId("notepad-part-expected")).toHaveValue(
    POSITION.expected,
  )
  await expect(page.getByTestId("notepad-version-v1")).toHaveAttribute(
    "aria-pressed",
    "true",
  )

  // Every Perspective starts in the chat, so each has a remove control.
  await expect(
    page.getByTestId("notepad-conversation").getByRole("button", {
      name: /^Remove /,
    }),
  ).toHaveCount(3)
  // The rail collapses and comes back.
  await page
    .getByRole("button", { name: "Collapse the perspectives" })
    .click()
  await expect(page.getByTestId("notepad-perspectives")).toBeHidden()
  await page.getByRole("button", { name: "Expand the perspectives" }).click()
  await expect(page.getByTestId("notepad-perspectives")).toBeVisible()
})

test("versions fork and stay independent", async ({ page }) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)

  await page.getByRole("button", { name: "Version" }).click()
  await expect(page.getByTestId("notepad-version-v2")).toBeVisible()

  await page
    .getByTestId("notepad-part-framing")
    .fill("v2 wording only, typed with nothing to save.")
  // Edits take effect as typed; the debounce lands without a save button.
  await expect(async () => {
    const state = await requestJson(
      page.request,
      `/api/focused/workspaces/${new URL(page.url()).searchParams.get("workspace")}`,
      "get",
    )
    const notepad = state.notepad
    const active = notepad.versions.find(
      (version: { id: string }) => version.id === notepad.active_version_id,
    )
    expect(active.doc.framing).toBe(
      "v2 wording only, typed with nothing to save.",
    )
    expect(notepad.versions[0].doc.framing).toBe(POSITION.framing)
  }).toPass({ timeout: 15_000 })

  // Switching back shows the original wording, untouched.
  await page.getByTestId("notepad-version-v1").click()
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    POSITION.framing,
  )
})

test("the guided arm cites evidence and gates the notepad behind review", async ({
  page,
}) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)

  await page.getByRole("button", { name: /Let agents discuss/ }).click()
  const conversation = page.getByTestId("notepad-conversation")
  // Grounded turns carry an evidence marker and quote the researcher back.
  await expect(conversation).toContainText("[1]", { timeout: 30_000 })
  await expect(conversation).toContainText(
    /You framed it as|Your methodology reads|You expect/,
  )

  await page
    .getByLabel("Which part the summary goes to")
    .selectOption("prior")
  await page.getByRole("button", { name: /Summarize so far/ }).click()

  const proposal = page.getByTestId("notepad-proposal")
  await expect(proposal).toBeVisible({ timeout: 30_000 })
  // The guided seam is reviewable: a reason and the evidence it rests on.
  await expect(proposal).toContainText("The discussion bears on Previous work")
  await expect(proposal).toContainText(/Cites p/)
  // And the notepad has not moved yet.
  await expect(page.getByTestId("notepad-part-prior")).toHaveValue(
    POSITION.prior,
  )

  await proposal.getByRole("button", { name: "Approve", exact: true }).click()
  await expect(proposal).toBeHidden({ timeout: 30_000 })
  await expect(page.getByTestId("notepad-part-prior")).not.toHaveValue(
    POSITION.prior,
  )
})

test("editing a proposal lands the researcher's wording verbatim", async ({
  page,
}) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  await page.getByRole("button", { name: /Let agents discuss/ }).click()
  await expect(page.getByTestId("notepad-conversation")).toContainText("[1]", {
    timeout: 30_000,
  })
  await page
    .getByLabel("Which part the summary goes to")
    .selectOption("expected")
  await page.getByRole("button", { name: /Summarize so far/ }).click()

  const proposal = page.getByTestId("notepad-proposal")
  await expect(proposal).toBeVisible({ timeout: 30_000 })
  await proposal.getByRole("button", { name: "Edit", exact: true }).click()
  await proposal
    .getByLabel("Your wording")
    .fill("Only the wording I accepted survives.")
  await proposal
    .getByRole("button", { name: /Accept with this wording/ })
    .click()
  await expect(page.getByTestId("notepad-part-expected")).toHaveValue(
    "Only the wording I accepted survives.",
    { timeout: 30_000 },
  )
})

test("rejecting a proposal leaves the notepad and returns the reason", async ({
  page,
}) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  await page.getByRole("button", { name: /Let agents discuss/ }).click()
  await expect(page.getByTestId("notepad-conversation")).toContainText("[1]", {
    timeout: 30_000,
  })
  await page
    .getByLabel("Which part the summary goes to")
    .selectOption("framing")
  await page.getByRole("button", { name: /Summarize so far/ }).click()

  const proposal = page.getByTestId("notepad-proposal")
  await expect(proposal).toBeVisible({ timeout: 30_000 })
  await proposal
    .getByLabel("Why you are rejecting")
    .fill("Wrong endpoint for this claim.")
  await proposal.getByRole("button", { name: "Reject", exact: true }).click()

  await expect(proposal).toBeHidden({ timeout: 30_000 })
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    POSITION.framing,
  )
  // The panel reads the rejection back into the chat.
  await expect(page.getByTestId("notepad-conversation")).toContainText(
    "Wrong endpoint for this claim.",
  )
})

test("the baseline arm cites nothing and offers one blind append", async ({
  page,
}) => {
  await notepadWorkspace(page, "baseline")
  await openGroupChat(page)

  await page.getByRole("button", { name: /Let agents discuss/ }).click()
  const conversation = page.getByTestId("notepad-conversation")
  await expect(conversation).toContainText("That is what I am weighing here.", {
    timeout: 30_000,
  })
  await expect(conversation).not.toContainText("[1]")

  await page.getByRole("button", { name: /Summarize so far/ }).click()
  const proposal = page.getByTestId("notepad-proposal")
  await expect(proposal).toBeVisible({ timeout: 30_000 })
  // One button, no diff, no reason, no evidence: Youngseung's single seam.
  await expect(
    proposal.getByRole("button", { name: "Copy into the notepad" }),
  ).toBeVisible()
  await expect(proposal.getByRole("button")).toHaveCount(1)
  await expect(proposal).not.toContainText("Cites")

  await proposal
    .getByRole("button", { name: "Copy into the notepad" })
    .click()
  await expect(proposal).toBeHidden({ timeout: 30_000 })
  await expect(page.getByTestId("notepad-part-framing")).not.toHaveValue(
    POSITION.framing,
  )
})

test("a reload lands back in the group chat", async ({ page }) => {
  const { workspaceId } = await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  await page.goto(`/focused?workspace=${workspaceId}`)
  // Stage restore reads the notepad, not just deliberations.
  await expect(page.getByTestId("notepad-conversation")).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    POSITION.framing,
  )
})

test("the rollback flag still serves the Thread board", async ({ page }) => {
  const { workspaceId } = await notepadWorkspace(page, "guided")
  await page.goto(`/focused?workspace=${workspaceId}&surface=threads`)
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Set up the panel" })).toBeVisible()
  await expect(page.getByTestId("notepad-panel")).toHaveCount(0)
})
