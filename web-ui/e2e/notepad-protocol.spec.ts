import { expect, test, type APIRequestContext, type Page } from "@playwright/test"

const PROBLEM =
  "Should antibiotics be prescribed broadly? I suspect the faster cure trades off against resistance and gut-flora harm."

const POSITION = {
  framing: "Prescribing breadth is an evolutionary-pressure problem.",
  prior: "Cohorts link broad days to resistance without pricing benefit.",
  method: "Compare severity-matched cohorts on resistome and time-to-cure.",
  expected: "Narrower first-line holds outcomes outside sepsis.",
}

async function requestJson(
  request: APIRequestContext,
  path: string,
  data?: unknown,
) {
  const response = await request.post(
    path,
    data === undefined ? {} : { data },
  )
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy()
  const payload = await response.json()
  return payload.active ?? payload
}

/** A real Demo-backed workspace following the same baseline HTTP contracts. */
async function baselineWorkspace(page: Page, perspectives = 3) {
  const created = await page.request.post("/api/focused/workspaces", {
    data: {
      problem: PROBLEM,
      position: POSITION,
      demo: true,
    },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const payload = await created.json()
  const workspaceId = payload.workspace.id as string
  const sessionId = payload.active.id as string
  let state = await requestJson(
    page.request,
    `/api/focused/sessions/${sessionId}/suggest-queries`,
  )
  state = await requestJson(
    page.request,
    `/api/focused/sessions/${sessionId}/search`,
    { queries: [state.suggested_queries[0].query] },
  )
  expect(state.papers.length).toBeGreaterThanOrEqual(perspectives)
  for (const [index, paper] of state.papers.slice(0, perspectives).entries()) {
    state = await requestJson(
      page.request,
      `/api/focused/sessions/${sessionId}/perspectives`,
      {
        paper_id: paper.id,
        name: `Perspective ${index + 1}`,
        description: `Reviews the evidence around paper ${index + 1}.`,
      },
    )
  }
  expect(state.perspectives).toHaveLength(perspectives)
  await page.goto(`/focused?workspace=${workspaceId}`)
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeEnabled()
  return { workspaceId, sessionId }
}

async function openDiscussion(page: Page) {
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(page.getByTestId("notepad-conversation")).toBeVisible({
    timeout: 30_000,
  })
}

test("the input screen has one baseline form and no participant condition controls", async ({
  page,
}) => {
  await page.goto("/focused")
  await expect(page.getByRole("heading", { name: "Hypothesis Studio" })).toBeVisible()
  await expect(page.getByLabel("Problem")).toBeVisible()
  for (const label of [
    "Framing",
    "Previous work",
    "Methodology",
    "Expected results",
  ]) {
    await expect(page.getByLabel(label)).toBeVisible()
  }
  await expect(page.getByRole("checkbox")).toHaveCount(0)
  await expect(page.getByText(/Demo mode|guided/i)).toHaveCount(0)
})

test("the demo route ignores prior work and shows no badge", async ({
  page,
}) => {
  const prior = await page.request.post("/api/focused/workspaces", {
    data: { problem: "A prior live workspace.", demo: false },
  })
  expect(prior.ok()).toBeTruthy()
  const priorId = (await prior.json()).workspace.id as string
  await page.addInitScript((workspaceId) => {
    window.localStorage.setItem("focused-workspace", workspaceId)
  }, priorId)
  await page.goto("/demo")
  await expect(page).toHaveURL(/\/demo$/)
  await expect(page).not.toHaveURL(/workspace=/)
  await expect(page.getByLabel("Problem")).toHaveValue(/antibiotics/i)
  await expect(page.getByText(/Demo mode|QA mode/i)).toHaveCount(0)
  await expect(page.getByRole("checkbox")).toHaveCount(0)
  await expect(page.getByTestId("paper-workflow")).toHaveCount(0)
})

test("Step 3 is Document, Discussion, and plain Perspective cards", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  await expect(page.getByText("Document", { exact: true })).toBeVisible()
  await expect(page.getByText("Discussion", { exact: true })).toBeVisible()
  await expect(page.getByText("Perspectives", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Perspective 1", exact: true }).click()
  await expect(page.getByText(/related papers?/)).toBeVisible()
  await expect(
    page.getByText(/Scope|Explanation|Approach|Significance|Fragment/i),
  ).toHaveCount(0)
  await expect(page.getByText("Notepad", { exact: true })).toHaveCount(0)
})

test("the baseline discussion stacks without horizontal phone overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await baselineWorkspace(page)
  await openDiscussion(page)
  await expect(page.getByTestId("notepad-panel")).toBeVisible()
  await expect(page.getByTestId("notepad-conversation")).toBeVisible()
  await expect(page.getByTestId("notepad-perspectives")).toBeVisible()
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))
  expect(widths.document).toBeLessThanOrEqual(widths.viewport)
})


test("versions fork independently and a blank version starts empty", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  const framing = page.getByTestId("notepad-part-framing")
  await framing.fill("Researcher wording for v1.")
  await page.getByRole("button", { name: "Add version by copying the current version" }).click()
  await expect(page.getByTestId("notepad-version-v2")).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(framing).toHaveValue("Researcher wording for v1.")
  await framing.fill("Independent wording for v2.")
  await page.getByTestId("notepad-version-v1").click()
  await expect(framing).toHaveValue("Researcher wording for v1.")
  await page.getByRole("button", { name: "Add a blank version" }).click()
  await expect(page.getByTestId("notepad-version-v3")).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(framing).toHaveValue("")
})

test("the review emits the exact budget and resumes its four-element agenda", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  await expect(page.getByTestId("notepad-turn-feedback")).toHaveCount(3)
  await expect(page.getByTestId("notepad-turn-comparison")).toHaveCount(1)
  await page.getByLabel("Turns").selectOption("2")
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  await expect(page.getByTestId("notepad-turn-comparison")).toHaveCount(3)
  await expect(page.getByText(/Reviewing Previous work · 0\/3/)).toBeVisible()
})

test("turns render one at a time while the click is still running", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  const gates: Array<() => void> = []
  await page.route("**/api/focused/sessions/*/notepad/discuss", async (route) => {
    expect(route.request().postDataJSON().turns).toBe(1)
    await new Promise<void>((resolve) => gates.push(resolve))
    await route.continue()
  })

  await page.getByLabel("Turns").selectOption("3")
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  await expect.poll(() => gates.length).toBe(1)
  gates[0]()
  await expect(page.getByTestId("notepad-turn-feedback")).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Let agents discuss" })).toBeDisabled()
  await expect.poll(() => gates.length).toBe(2)
  gates[1]()
  await expect(page.getByTestId("notepad-turn-feedback")).toHaveCount(2)
  await expect.poll(() => gates.length).toBe(3)
  gates[2]()
  await expect(page.getByTestId("notepad-turn-feedback")).toHaveCount(3)
  await expect(page.getByRole("button", { name: "Let agents discuss" })).toBeEnabled()
})

test("one directed question gets one reply from every active Perspective", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  await page.getByLabel("Message the panel").fill("What boundary should I defend?")
  await page.getByLabel("Message the panel").press("Enter")
  await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(1)
  await expect(page.getByTestId("notepad-turn-direct_reply")).toHaveCount(3)
})

test("feedback is clipboard-only and leaves the Document unchanged", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await baselineWorkspace(page)
  await openDiscussion(page)
  const framing = page.getByTestId("notepad-part-framing")
  const original = await framing.inputValue()
  await page.getByLabel("Turns").selectOption("2")
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  const firstFeedback = page.getByTestId("notepad-turn-feedback").first()
  const feedbackText = await firstFeedback.locator("p").textContent()
  await firstFeedback.getByRole("button", { name: "Copy feedback" }).click()
  await expect(firstFeedback.getByRole("button", { name: "Copied" })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    feedbackText,
  )
  await expect(framing).toHaveValue(original)
})

test("Finish study flushes edits, freezes all versions, and survives reload", async ({
  page,
}) => {
  const { workspaceId, sessionId } = await baselineWorkspace(page)
  await openDiscussion(page)
  await page
    .getByRole("button", { name: "Add version by copying the current version" })
    .click()
  await expect(page.getByTestId("notepad-version-v2")).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  const method = page.getByTestId("notepad-part-method")
  await method.fill("Final researcher-authored method.")
  await page.getByRole("button", { name: "Finish study" }).click()
  await expect(page.getByRole("button", { name: "Study finished" })).toBeVisible()
  await expect(method).toBeDisabled()
  await expect(page.getByRole("button", { name: "Papers" })).toBeDisabled()
  await expect(page.getByTestId("notepad-build-perspective")).toHaveCount(0)
  const saved = await page.request.get(`/api/focused/workspaces/${workspaceId}`)
  expect(saved.ok()).toBeTruthy()
  const versionId = (await saved.json()).active.notepad.active_version_id as string
  await page.evaluate(
    ({ sessionId, versionId }) => {
      window.localStorage.setItem(
        "focused-notepad-drafts",
        JSON.stringify([
          {
            sessionId,
            versionId,
            part: "method",
            text: "Stale uncommitted method.",
          },
        ]),
      )
    },
    { sessionId, versionId },
  )
  let rejectedAutosaves = 0
  page.on("request", (request) => {
    if (
      request.method() === "PATCH" &&
      request.url().includes("/notepad/part")
    ) {
      rejectedAutosaves += 1
    }
  })
  await page.reload()
  await expect(page.getByTestId("notepad-conversation")).toBeVisible()
  await expect(method).toHaveValue("Final researcher-authored method.")
  await expect(method).toBeDisabled()
  await page.getByTestId("notepad-version-v1").click()
  await expect(method).toHaveValue(POSITION.method)
  await page.getByTestId("notepad-version-v2").click()
  await expect(method).toHaveValue("Final researcher-authored method.")
  await expect(page.getByRole("button", { name: "Study finished" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Papers" })).toBeDisabled()
  await expect(page.getByTestId("notepad-build-perspective")).toHaveCount(0)
  await page.waitForTimeout(600)
  expect(rejectedAutosaves).toBe(0)
})


test("a stale Papers tab reloads the finished Document on conflict", async ({
  page,
}) => {
  const { sessionId } = await baselineWorkspace(page)
  await openDiscussion(page)
  await page.getByRole("button", { name: "Papers", exact: true }).click()
  const finished = await page.request.post(
    `/api/focused/sessions/${sessionId}/notepad/finish`,
  )
  expect(finished.ok()).toBeTruthy()

  const paper = page.getByTestId("paper-result").nth(3)
  await paper.getByRole("button").first().click()
  await paper.getByRole("button", { name: "Add to editor" }).click()
  await page.getByRole("button", { name: "Build Perspective" }).click()

  await expect(page.getByTestId("notepad-conversation")).toBeVisible()
  await expect(page.getByRole("button", { name: "Study finished" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Papers" })).toBeDisabled()
})

test("Build another Perspective returns to the same paper workflow", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  await page.getByTestId("notepad-build-perspective").click()
  await expect(page.getByText("Papers", { exact: true })).toBeVisible()
  await expect(page.getByText("Built Perspectives", { exact: true })).toBeVisible()
  await expect(page.getByText("3 / 6", { exact: true })).toBeVisible()
})
