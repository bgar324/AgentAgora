import { expect, test, type Page } from "@playwright/test"

const POSITION = {
  framing: "Prescribing breadth is an evolutionary-pressure problem.",
  prior: "Cohorts link broad days to resistance without pricing benefit.",
  method: "Compare severity-matched cohorts on resistome carriage.",
  expected: "Narrower first-line holds outcomes outside sepsis.",
}

/** A demo workspace stopped at Step 2, corpus already searched. */
async function atStepTwo(page: Page) {
  const created = await page.request.post("/api/focused/workspaces", {
    data: {
      problem: "Should antibiotics be prescribed broadly?",
      research_questions: [],
      position: POSITION,
      arm: "guided",
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
  await page.goto(`/focused?workspace=${workspaceId}`)
  await expect(
    page.getByRole("heading", { name: "Resistance ecology" }),
  ).toBeVisible({ timeout: 30_000 })
  return { workspaceId }
}

async function activePerspectives(page: Page, workspaceId: string) {
  const response = await page.request.get(
    `/api/focused/workspaces/${workspaceId}`,
  )
  expect(response.ok()).toBeTruthy()
  const view = await response.json()
  return view.active.perspectives as {
    id: string
    name: string
    summary: string
  }[]
}

test("Step 2 keeps the four parts on screen, read only", async ({ page }) => {
  await atStepTwo(page)
  const recap = page.getByRole("region", { name: "Your position" })
  await expect(recap).toBeVisible()
  for (const [label, text] of [
    ["Framing", POSITION.framing],
    ["Previous work", POSITION.prior],
    ["Methodology", POSITION.method],
    ["Expected results", POSITION.expected],
  ] as const) {
    await expect(recap).toContainText(label)
    await expect(recap).toContainText(text)
  }
  // Read only here: the parts become editable in Step 3, not on this screen.
  await expect(recap.getByRole("textbox")).toHaveCount(0)
})

test("the Perspective is prefilled from its cluster and stays editable", async ({
  page,
}) => {
  await atStepTwo(page)
  await page.getByRole("heading", { name: "Resistance ecology" }).click()

  const job = page.getByLabel("Job", { exact: true })
  const description = page.getByLabel("Description", { exact: true })
  await expect(job).toHaveValue("Resistance ecology")
  await expect(description).not.toHaveValue("")

  await job.fill("Resistance ecologist")
  await description.fill(
    "I weigh prescribing by what accumulates in the population.",
  )
  await expect(job).toHaveValue("Resistance ecologist")
})

test("the researcher's wording is what gets built", async ({ page }) => {
  const { workspaceId } = await atStepTwo(page)
  await page.getByRole("heading", { name: "Resistance ecology" }).click()
  await page.getByLabel("Job", { exact: true }).fill("Resistance ecologist")
  await page
    .getByLabel("Description", { exact: true })
    .fill("I weigh prescribing by what accumulates in the population.")
  await page
    .getByRole("button", { name: "Build this Perspective" })
    .click()

  await expect(async () => {
    const perspectives = await activePerspectives(page, workspaceId)
    const built = perspectives.filter(
      (perspective) => !perspective.id.startsWith("optimistic:"),
    )
    expect(built).toHaveLength(1)
    expect(built[0].name).toBe("Resistance ecologist")
    expect(built[0].summary).toBe(
      "I weigh prescribing by what accumulates in the population.",
    )
  }).toPass({ timeout: 30_000 })
})

test("one Perspective is enough to continue", async ({ page }) => {
  await atStepTwo(page)
  const continueButton = page.getByRole("button", {
    name: "Continue",
    exact: true,
  })
  await expect(continueButton).toBeDisabled()

  await page.getByRole("heading", { name: "Resistance ecology" }).click()
  await page.getByRole("button", { name: "Build this Perspective" }).click()

  // His spec: "Once at least one exists, Continue to group chat opens."
  await expect(continueButton).toBeEnabled({ timeout: 30_000 })
  await continueButton.click()
  await expect(
    page.getByRole("button", { name: /Open the discussion/ }),
  ).toBeVisible({ timeout: 30_000 })
})

test("a built Perspective stops offering its editor", async ({ page }) => {
  await atStepTwo(page)
  await page.getByRole("heading", { name: "Resistance ecology" }).click()
  await page.getByRole("button", { name: "Build this Perspective" }).click()
  await expect(page.getByRole("button", { name: /Built/ })).toBeVisible({
    timeout: 30_000,
  })
  // The persona fields are gone once it exists: editing it afterwards is a
  // Step 3 concern, not a second build.
  await expect(page.getByLabel("Job", { exact: true })).toHaveCount(0)
})
