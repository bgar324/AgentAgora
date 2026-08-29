import { expect, test, type Page } from "@playwright/test"

const POSITION = {
  framing: "Prescribing breadth is an evolutionary-pressure problem.",
  prior: "Cohorts link broad days to resistance without pricing benefit.",
  method: "Compare severity-matched cohorts on resistome carriage.",
  expected: "Narrower first-line holds outcomes outside sepsis.",
}

async function activeView(page: Page, workspaceId: string) {
  const response = await page.request.get(
    `/api/focused/workspaces/${workspaceId}`,
  )
  expect(response.ok()).toBeTruthy()
  return response.json()
}

/** A baseline Demo workspace stopped at Step 2, corpus already searched. */
async function atStepTwo(page: Page) {
  const created = await page.request.post("/api/focused/workspaces", {
    data: {
      problem: "Should antibiotics be prescribed broadly?",
      research_questions: [],
      position: POSITION,
      arm: "baseline",
      demo: true,
    },
  })
  expect(created.ok()).toBeTruthy()
  const payload = await created.json()
  const workspaceId = payload.workspace.id as string
  const searched = await page.request.post(
    `/api/focused/sessions/${payload.active.id}/search`,
    {
      data: {
        queries: [
          "broad-spectrum antibiotic use antimicrobial resistance population",
        ],
      },
    },
  )
  expect(searched.ok()).toBeTruthy()
  await page.goto(`/focused?arm=baseline&workspace=${workspaceId}`)
  await expect(page.getByTestId("paper-result").first()).toBeVisible({
    timeout: 30_000,
  })
  return { workspaceId }
}

async function carryPaper(page: Page, index = 0) {
  const card = page.getByTestId("paper-result").nth(index)
  await card.getByRole("button").first().click()
  await card.getByRole("button", { name: "Carry to Perspective" }).click()
  return card
}

test("Step 2 is the three-column paper workflow and lists every paper", async ({
  page,
}) => {
  const { workspaceId } = await atStepTwo(page)
  const view = await activeView(page, workspaceId)

  await expect(page.getByTestId("paper-workflow")).toBeVisible()
  await expect(page.getByTestId("search-brief")).toBeVisible()
  await expect(page.getByTestId("paper-results-surface")).toBeVisible()
  await expect(page.getByTestId("perspective-editor")).toBeVisible()
  await expect(page.getByTestId("paper-result")).toHaveCount(
    view.active.papers.length,
  )
})

test("Step 2 keeps the problem and four parts on screen, read only", async ({
  page,
}) => {
  await atStepTwo(page)
  const recap = page.getByTestId("search-brief")
  await expect(recap).toContainText("Should antibiotics be prescribed broadly?")
  for (const [label, text] of [
    ["Framing", POSITION.framing],
    ["Previous work", POSITION.prior],
    ["Methodology", POSITION.method],
    ["Expected results", POSITION.expected],
  ] as const) {
    await expect(recap).toContainText(label)
    await expect(recap).toContainText(text)
  }
  await expect(recap.getByRole("textbox")).toHaveCount(0)
})

test("a paper expands inline and carries its abstract into an editable Perspective", async ({
  page,
}) => {
  const { workspaceId } = await atStepTwo(page)
  const view = await activeView(page, workspaceId)
  const paper = view.active.papers[0]

  const card = page.getByTestId("paper-result").first()
  await card.getByRole("button").first().click()
  await expect(card).toContainText("Abstract")
  await expect(card).toContainText(paper.abstract)
  await card.getByRole("button", { name: "Carry to Perspective" }).click()

  const job = page.getByLabel("Job", { exact: true })
  const description = page.getByRole("textbox", {
    name: "Description",
    exact: true,
  })
  await expect(job).toHaveValue(paper.title)
  await expect(description).toHaveValue(paper.abstract)
  await job.fill("Resistance ecologist")
  await description.fill(
    "I weigh prescribing by what accumulates in the population.",
  )
  await expect(job).toHaveValue("Resistance ecologist")
})

test("a build failure is shown beside the Perspective editor", async ({ page }) => {
  await atStepTwo(page)
  await carryPaper(page)
  await page.route(
    "**/api/focused/sessions/*/perspectives",
    async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Perspective model unavailable." }),
      })
    },
  )

  await page.getByRole("button", { name: "Build Perspective" }).click()
  await expect(
    page.getByTestId("perspective-editor").getByRole("alert"),
  ).toHaveText("Perspective model unavailable.")
})

test("a stale successful add clears its optimistic row", async ({ page }) => {
  const { workspaceId } = await atStepTwo(page)
  const before = await activeView(page, workspaceId)
  await carryPaper(page)
  await page.route(
    "**/api/focused/sessions/*/perspectives",
    async (route) => {
      const response = await route.fetch()
      const payload = await response.json()
      payload.workspace.revision = before.workspace.revision - 1
      await route.fulfill({ response, json: payload })
    },
  )

  await page.getByRole("button", { name: "Build Perspective" }).click()
  await expect(page.getByText("Adding…")).toHaveCount(0, { timeout: 5_000 })
})

test("a paper add accepts an authoritative concurrent removal", async ({
  page,
}) => {
  const { workspaceId } = await atStepTwo(page)
  await carryPaper(page)
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await expect(page.getByText("Adding…")).toHaveCount(0, { timeout: 30_000 })

  const before = await activeView(page, workspaceId)
  const sessionId = before.active.id as string
  const removed = before.active.perspectives[0] as {
    id: string
    name: string
  }
  await carryPaper(page, 1)

  let releaseAdd: () => void = () => undefined
  const addHeld = new Promise<void>((resolve) => {
    releaseAdd = resolve
  })
  let observeAdd: () => void = () => undefined
  const addStarted = new Promise<void>((resolve) => {
    observeAdd = resolve
  })
  await page.route(
    "**/api/focused/sessions/*/perspectives",
    async (route) => {
      observeAdd()
      await addHeld
      await route.continue()
    },
  )

  await page.getByRole("button", { name: "Build Perspective" }).click()
  await addStarted
  const removal = await page.request.delete(
    `/api/focused/sessions/${sessionId}/perspectives/${removed.id}`,
  )
  expect(removal.ok()).toBeTruthy()
  releaseAdd()

  const built = page.getByTestId("built-perspectives")
  await expect(built.getByText("Adding…")).toHaveCount(0, { timeout: 30_000 })
  await expect(built).not.toContainText(removed.name)
  await expect(built.locator("article")).toHaveCount(1)
  const after = await activeView(page, workspaceId)
  expect(after.active.perspectives).toHaveLength(1)
})

test("the researcher's wording is built below the editor", async ({ page }) => {
  const { workspaceId } = await atStepTwo(page)
  const initial = await activeView(page, workspaceId)
  const sourceTitle = initial.active.papers[0].title as string
  await carryPaper(page)
  await page.getByLabel("Job", { exact: true }).fill("Resistance ecologist")
  await page
    .getByRole("textbox", { name: "Description", exact: true })
    .fill("I weigh prescribing by what accumulates in the population.")
  await page.getByRole("button", { name: "Build Perspective" }).click()

  await expect(page.getByTestId("built-perspectives")).toContainText(
    "Resistance ecologist",
    { timeout: 30_000 },
  )
  await expect(page.getByTestId("built-perspectives")).toContainText(
    "I weigh prescribing by what accumulates in the population.",
  )
  await expect(page.getByLabel("Job", { exact: true })).toHaveCount(0)
  const built = page.getByTestId("built-perspectives")
  await built.getByRole("button", { name: sourceTitle }).click()
  await expect(page.getByRole("dialog", { name: sourceTitle })).toBeVisible({
    timeout: 30_000,
  })

  await expect(async () => {
    const view = await activeView(page, workspaceId)
    expect(view.active.perspectives).toHaveLength(1)
    expect(view.active.perspectives[0].name).toBe("Resistance ecologist")
    expect(view.active.perspectives[0].summary).toBe(
      "I weigh prescribing by what accumulates in the population.",
    )
  }).toPass({ timeout: 30_000 })
})

test("one Perspective makes Continue open the group chat directly", async ({
  page,
}) => {
  await atStepTwo(page)
  const continueButton = page.getByRole("button", {
    name: "Continue",
    exact: true,
  })
  await expect(continueButton).toBeDisabled()

  await carryPaper(page)
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await expect(continueButton).toBeEnabled({ timeout: 30_000 })
  await continueButton.click()
  await expect(page.getByTestId("notepad-conversation")).toBeVisible({
    timeout: 30_000,
  })
  await expect(
    page.getByRole("button", { name: /Open the discussion/ }),
  ).toHaveCount(0)
})

test("building another Perspective returns to papers and rejoins on return", async ({
  page,
}) => {
  const { workspaceId } = await atStepTwo(page)
  const initial = await activeView(page, workspaceId)
  const firstPaper = initial.active.papers[0]
  const secondPaper = initial.active.papers[1]

  await carryPaper(page, 0)
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(page.getByTestId("notepad-conversation")).toContainText(
    firstPaper.title,
    { timeout: 30_000 },
  )

  await page.getByTestId("notepad-build-perspective").click()
  await carryPaper(page, 1)
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await page.getByRole("button", { name: "Continue", exact: true }).click()

  await expect(page.getByTestId("notepad-conversation")).toContainText(
    secondPaper.title,
    { timeout: 30_000 },
  )
  const view = await activeView(page, workspaceId)
  expect(view.active.perspectives).toHaveLength(2)
})

test("a Perspective links its source paper and shows four Fragments plus synthesis", async ({
  page,
}) => {
  const { workspaceId } = await atStepTwo(page)
  const view = await activeView(page, workspaceId)
  const sourceTitle = view.active.papers[0].title as string

  await carryPaper(page)
  await page.getByRole("button", { name: "Build Perspective" }).click()
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  const rail = page.getByTestId("notepad-perspectives")
  await expect(rail).toBeVisible({ timeout: 30_000 })
  await rail.getByRole("button", { name: sourceTitle }).first().click()
  const sourceLink = rail.getByRole("button", {
    name: `Open source paper: ${sourceTitle}`,
  })
  await expect(sourceLink).toBeVisible()
  for (const fragment of ["Scope", "Explanation", "Approach", "Significance"]) {
    await expect(rail).toContainText(fragment)
  }
  await expect(rail).toContainText("Framing & Position")
  await sourceLink.click()
  await expect(page.getByRole("dialog", { name: sourceTitle })).toBeVisible({
    timeout: 30_000,
  })
})
