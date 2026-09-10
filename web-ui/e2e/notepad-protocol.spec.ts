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

async function chooseTurns(page: Page, count: number) {
  await page.getByRole("combobox", { name: "Turns" }).click()
  await page.getByRole("option", {
    name: `${count} ${count === 1 ? "turn" : "turns"}`,
    exact: true,
  }).click()
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

test("Start over preserves a finished study and clears browser resume state", async ({
  page,
}) => {
  const { workspaceId } = await baselineWorkspace(page, 1)
  await openDiscussion(page)
  await page.getByLabel("Message the panel").fill("Which uncertainty matters most?")
  await page.getByLabel("Message the panel").press("Enter")
  await expect(page.getByTestId("notepad-turn-direct_reply")).toHaveCount(1)
  await page.getByRole("button", { name: "Finish study" }).click()
  await expect(page.getByRole("button", { name: "Study finished" })).toBeVisible()
  const before = await page.request.get(`/api/focused/workspaces/${workspaceId}`)
  expect(before.ok()).toBeTruthy()
  const savedStudy = await before.json()

  await page.getByRole("button", { name: "Start over", exact: true }).click()
  await page.getByRole("button", { name: "Start new study", exact: true }).click()
  await expect(page.getByLabel("Problem", { exact: true })).toBeVisible()
  expect(new URL(page.url()).searchParams.has("workspace")).toBe(false)
  expect(await page.evaluate(() => localStorage.getItem("focused-workspace"))).toBeNull()
  const after = await page.request.get(`/api/focused/workspaces/${workspaceId}`)
  expect(after.ok()).toBeTruthy()
  expect(await after.json()).toEqual(savedStudy)

  await page.reload()
  await expect(page.getByLabel("Problem", { exact: true })).toBeVisible()
  await page.goto(`/focused?workspace=${workspaceId}`)
  await expect(page.getByRole("button", { name: "Study finished" })).toBeVisible()
  await expect(page.getByTestId("notepad-turn-researcher")).toContainText(
    "Which uncertainty matters most?",
  )
})

test("Continue submits visible restored fields without React input events", async ({
  page,
  baseURL,
}) => {
  if (!baseURL) throw new Error("The browser test server must be configured")
  const liveUrl = new URL("/focused", baseURL)
  liveUrl.hostname = "127.0.0.1"
  await page.goto(liveUrl.href)
  const problem = page.getByLabel("Problem", { exact: true })
  const continueButton = page.getByRole("button", { name: "Continue", exact: true })
  await problem.fill("Initialize the form")
  await expect(continueButton).toBeEnabled()
  await problem.fill("")
  await page.evaluate(({ problem, position }) => {
    for (const [id, value] of [
      ["focused-problem", problem],
      ...Object.entries(position).map(([part, text]) => [`position-${part}`, text]),
    ]) {
      const field = document.getElementById(id)
      if (!(field instanceof HTMLTextAreaElement)) throw new Error(`Missing ${id}`)
      field.value = value
    }
  }, { problem: PROBLEM, position: POSITION })

  await expect(continueButton).toBeEnabled({ timeout: 1000 })
  await continueButton.click()
  const recap = page.getByTestId("search-brief")
  await expect(recap).toBeVisible()
  await expect(recap).toContainText(PROBLEM)
  for (const text of Object.values(POSITION)) {
    await expect(recap).toContainText(text)
  }
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
  const source = page.getByTestId("notepad-perspectives")
    .locator("article").first().locator("button").last()
  await expect(source).toHaveCSS("text-align", "left")
  const footer = await source.evaluate((button) => {
    const count = button.nextElementSibling
    if (!count) throw new Error("Missing related-paper count")
    return {
      separateLine: count.getBoundingClientRect().top >= button.getBoundingClientRect().bottom,
      count: count.textContent,
    }
  })
  expect(footer.separateLine).toBe(true)
  expect(footer.count).not.toMatch(/^\s*·/)
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
  const selectedTurns = await page.getByRole("combobox", { name: "Turns" }).innerText()
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  await expect(page.getByTestId("notepad-turn-feedback")).toHaveCount(3)
  await expect(page.getByTestId("notepad-turn-comparison")).toHaveCount(1)
  await expect(page.getByRole("combobox", { name: "Turns" })).toHaveText(selectedTurns)
  await chooseTurns(page, 2)
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  await expect(page.getByTestId("notepad-turn-comparison")).toHaveCount(3)
  await expect(page.getByText(/Reviewing Previous work · 0\/3/)).toBeVisible()
})

test("the custom turn dropdown supports keyboard selection and stays within the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await baselineWorkspace(page, 2)
  await openDiscussion(page)
  const turns = page.getByRole("combobox", { name: "Turns" })
  const menu = page.getByRole("listbox", { name: "Turns" })

  await turns.click()
  await expect(menu).toBeVisible()
  await expect(menu.getByRole("option")).toHaveCount(8)
  await expect(menu.getByRole("option", { name: "4 turns", exact: true }))
    .toHaveAttribute("aria-selected", "true")
  await expect(menu).toHaveCSS("opacity", "1")
  await page.screenshot({ path: test.info().outputPath("turn-menu.png") })
  await page.getByRole("option", { name: "6 turns", exact: true }).click()
  await expect(turns).toHaveText("6 turns")
  await expect(turns).toBeFocused()
  await expect(menu).toBeHidden()

  await turns.press("ArrowDown")
  await turns.press("Home")
  await turns.press("ArrowDown")
  await turns.press("Enter")
  await expect(turns).toHaveText("2 turns")
  await expect(menu).toBeHidden()
  await turns.press("ArrowDown")
  await turns.press("End")
  await turns.press("Escape")
  await expect(turns).toHaveText("2 turns")
  await expect(turns).toBeFocused()
  await turns.click()
  await page.getByRole("button", { name: "Show who is in the chat" }).click()
  await expect(menu).toBeHidden()

  await page.setViewportSize({ width: 390, height: 844 })
  await turns.click()
  await expect(menu).toBeVisible()
  const bounds = await menu.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
      width: innerWidth, height: innerHeight }
  })
  expect(bounds.left).toBeGreaterThanOrEqual(0)
  expect(bounds.top).toBeGreaterThanOrEqual(0)
  expect(bounds.right).toBeLessThanOrEqual(bounds.width)
  expect(bounds.bottom).toBeLessThanOrEqual(bounds.height)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await expect(menu).toHaveCSS("animation-name", "none")
  await turns.press("Escape")
  await expect(menu).toBeHidden()
})

test("topic suggestions use a pending label while the request runs", async ({
  page,
}) => {
  await baselineWorkspace(page, 1)
  const gates: Array<() => void> = []
  await page.route("**/api/focused/sessions/*/notepad/topics", async (route) => {
    await new Promise<void>((resolve) => gates.push(resolve))
    await route.continue()
  })
  try {
    await openDiscussion(page)
    const suggest = page.getByTestId("notepad-topics-generate")
    await expect(suggest).toHaveText("Suggesting topics…")
    await expect(suggest).toBeDisabled()
    await expect.poll(() => gates.length).toBe(1)
    gates[0]()
    await expect(suggest).toHaveCount(0)
  } finally {
    for (const release of gates) release()
  }
})

test("turns render one at a time while the click is still running", async ({
  page,
}) => {
  await baselineWorkspace(page)
  await openDiscussion(page)
  const gates: Array<() => void> = []
  await page.route("**/api/focused/sessions/*/notepad/discuss", async (route) => {
    await new Promise<void>((resolve) => gates.push(resolve))
    await route.continue()
  })

  await chooseTurns(page, 3)
  await page.getByRole("button", { name: "Let agents discuss" }).click()
  await expect.poll(() => gates.length).toBe(1)
  gates[0]()
  await expect(page.getByTestId("notepad-turn-feedback")).toHaveCount(1)
  await expect(page.getByRole("button", { name: "Let agents discuss" })).toBeDisabled()
  await expect(page.getByRole("combobox", { name: "Turns" })).toBeDisabled()
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

test("a saved reply is recovered after a gateway error without resending", async ({
  page,
}) => {
  const { workspaceId } = await baselineWorkspace(page, 2)
  await openDiscussion(page)
  await page.getByTestId("notepad-topics-toggle").click()
  await page.getByTestId("notepad-topic").first().click()
  const message = page.getByLabel("Message the panel")
  await message.fill("Which   boundary\n should I defend?")
  let sends = 0
  await page.route("**/api/focused/sessions/*/notepad/messages", async (route) => {
    sends++
    const saved = await route.fetch()
    expect(saved.ok()).toBeTruthy()
    await route.fulfill({ status: 502, contentType: "text/plain", body: "Bad Gateway" })
  })
  const reads: Array<() => void> = []
  await page.route(`**/api/focused/workspaces/${workspaceId}`, async (route) => {
    await new Promise<void>((resolve) => reads.push(resolve))
    await route.continue()
  })
  try {
    await page.getByRole("button", { name: "Send", exact: true }).click()
    await expect.poll(() => reads.length, { timeout: 1500 }).toBe(1)
    await expect(message).toBeDisabled()
    await expect(page.getByTestId("notepad-build-perspective")).toBeDisabled()
    await expect(page.getByTestId("notepad-pending-message")).toBeVisible()
    reads[0]()
    await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(1)
    await expect(page.getByTestId("notepad-turn-researcher").locator("p"))
      .toHaveText("Which boundary should I defend?")
    await expect(page.getByTestId("notepad-turn-direct_reply")).toHaveCount(2)
    await expect(page.getByTestId("notepad-pending-message")).toHaveCount(0)
    await expect(page.getByTestId("composer-topic")).toHaveCount(0)
    await expect(message).toHaveValue("")
    await expect(page.getByTestId("notepad-conversation").getByRole("alert")).toHaveCount(0)
    expect(sends).toBe(1)
  } finally {
    for (const release of reads) release()
  }
})

test("an earlier identical prompt does not falsely confirm a failed send", async ({
  page,
}) => {
  await baselineWorkspace(page, 1)
  await openDiscussion(page)
  await page.getByTestId("notepad-topics-toggle").click()
  const topic = page.getByTestId("notepad-topic").first()
  const message = page.getByLabel("Message the panel")
  const question = "What boundary should I defend?"
  await topic.click()
  await message.fill(question)
  await page.getByRole("button", { name: "Send", exact: true }).click()
  await expect(page.getByTestId("notepad-turn-direct_reply")).toHaveCount(1)
  await expect(page.getByTestId("composer-topic")).toHaveCount(0)
  await topic.click()
  await message.fill(question)
  await page.route("**/api/focused/sessions/*/notepad/messages", async (route) => {
    await route.fulfill({ status: 502, contentType: "text/plain", body: "Bad Gateway" })
  })
  await page.getByRole("button", { name: "Send", exact: true }).click()
  await expect(message).toBeEnabled()
  await expect(message).toHaveValue(question)
  await expect(page.getByTestId("composer-topic")).toBeVisible()
  await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(1)
  await expect(page.getByTestId("notepad-conversation").getByRole("alert")).toContainText("502")
})

test("pending messages recover their draft and do not steal reader focus", async ({
  page,
}) => {
  await baselineWorkspace(page, 2)
  await openDiscussion(page)
  await page.getByTestId("notepad-topics-toggle").click()
  await page.getByTestId("notepad-topic").first().click()
  const message = page.getByLabel("Message the panel")
  const buildAnother = page.getByTestId("notepad-build-perspective")
  const question = "What evidence would change the recommendation?"
  await message.fill(question)

  const gates: Array<() => void> = []
  let attempts = 0
  await page.route("**/api/focused/sessions/*/notepad/messages", async (route) => {
    const attempt = attempts++
    await new Promise<void>((resolve) => gates.push(resolve))
    if (attempt === 0) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Reply unavailable." }),
      })
    } else {
      await route.continue()
    }
  })

  try {
    await page.getByRole("button", { name: "Send", exact: true }).click()
    await expect(page.getByTestId("notepad-pending-message")).toContainText(question)
    await expect(page.getByTestId("notepad-pending-activity")).toBeVisible()
    await expect(buildAnother).toBeDisabled()
    await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(0)
    await expect(message).toHaveValue("")
    await expect.poll(() => gates.length).toBe(1)
    gates[0]()
    await expect(page.getByTestId("notepad-pending-message")).toHaveCount(0)
    await expect(message).toHaveValue(question)
    await expect(message).toBeFocused()
    await expect(page.getByTestId("composer-topic")).toBeVisible()
    await expect(buildAnother).toBeEnabled()

    await page.getByRole("button", { name: "Send", exact: true }).click()
    await expect(page.getByTestId("notepad-pending-message")).toBeVisible()
    const perspective = page.getByRole("button", {
      name: "Perspective 1",
      exact: true,
    })
    await perspective.click()
    await expect(perspective).toBeFocused()
    await expect.poll(() => gates.length).toBe(2)
    gates[1]()
    await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(1)
    await expect(page.getByTestId("notepad-turn-direct_reply")).toHaveCount(2)
    await expect(page.getByTestId("notepad-pending-message")).toHaveCount(0)
    await expect(page.getByTestId("composer-topic")).toHaveCount(0)
    await expect(perspective).toBeFocused()
    await expect(buildAnother).toBeEnabled()
  } finally {
    for (const release of gates) release()
  }
})

test("new discussion turns follow the bottom without moving a reader's place", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 800 })
  await baselineWorkspace(page, 2)
  await openDiscussion(page)
  const discuss = page.getByRole("button", { name: "Let agents discuss" })
  const scroller = page
    .getByTestId("notepad-conversation")
    .locator(".overflow-y-auto:not([popover])")

  await discuss.click()
  await expect(page.getByTestId("notepad-turn-comparison")).toHaveCount(2)
  await expect(discuss).toBeEnabled()
  await expect.poll(() => scroller.evaluate((node) =>
    node.scrollHeight - node.scrollTop - node.clientHeight,
  )).toBeLessThanOrEqual(2)
  await expect.poll(() => scroller.evaluate((node) =>
    node.scrollHeight > node.clientHeight,
  )).toBe(true)

  await scroller.hover()
  await page.mouse.wheel(0, -300)
  await expect(page.getByTestId("notepad-jump-latest")).toBeVisible()
  const readingTop = await scroller.evaluate((node) => node.scrollTop)
  await discuss.click()
  await expect(page.getByTestId("notepad-turn-comparison")).toHaveCount(4)
  await expect(discuss).toBeEnabled()
  expect(await scroller.evaluate((node) => node.scrollTop)).toBeCloseTo(readingTop, 0)
  await page.getByTestId("notepad-jump-latest").click()
  await expect.poll(() => scroller.evaluate((node) =>
    node.scrollHeight - node.scrollTop - node.clientHeight,
  )).toBeLessThanOrEqual(2)
})

test("clearing chat requires confirmation and leaves the Document unchanged", async ({
  page,
}) => {
  await baselineWorkspace(page, 1)
  await openDiscussion(page)
  const framing = page.getByTestId("notepad-part-framing")
  const original = await framing.inputValue()
  await page.getByLabel("Message the panel").fill("What should I test?")
  await page.getByLabel("Message the panel").press("Enter")
  await expect(page.getByTestId("notepad-turn-direct_reply")).toHaveCount(1)
  const clear = page.getByRole("button", { name: "Clear chat", exact: true })
  const dialog = page.getByRole("dialog", { name: "Clear chat?" })
  let cleared = 0
  page.on("request", (request) => {
    if (request.method() === "DELETE" && request.url().endsWith("/notepad/chat")) cleared++
  })

  await clear.click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused()
  await page.keyboard.press("Tab")
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press("Escape")
  await expect(dialog).toBeHidden()
  await expect(clear).toBeFocused()
  await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(1)
  expect(cleared).toBe(0)

  await clear.click()
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(cleared).toBe(0)
  await clear.click()
  await dialog.getByRole("button", { name: "Clear chat", exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByTestId("notepad-turn-researcher")).toHaveCount(0)
  await expect(framing).toHaveValue(original)
  expect(cleared).toBe(1)
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
  await chooseTurns(page, 2)
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
  await expect(page.getByTestId("paper-workflow")).toBeVisible()
  await expect(page.getByTestId("built-perspective")).toHaveCount(3)
})
