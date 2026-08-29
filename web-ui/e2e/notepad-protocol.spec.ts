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
  // The participant is never shown their condition, let alone offered a
  // choice of it: self-selection would destroy random assignment, and
  // naming the manipulation invites them to perform it.
  await expect(
    page.getByRole("button", { name: "Perspective-guided" }),
  ).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "Unguided baseline" }),
  ).toHaveCount(0)
  await expect(page.getByText(/propose notepad changes you review/)).toHaveCount(
    0,
  )
})

// One test per case: a fresh context starts with empty localStorage, so the
// workspace-restore effect cannot race a mid-test clear.
for (const [query, expected] of [
  ["", "guided"],
  ["?arm=baseline", "baseline"],
  ["?arm=nonsense", "guided"],
] as const) {
  test(`the session link assigns ${expected} for "${query || "no query"}"`, async ({
    page,
  }) => {
    await page.goto(`/focused${query}`)
    await page.getByRole("button", { name: "Continue" }).click()
    await expect(page).toHaveURL(/workspace=[a-f0-9]+/)
    const workspaceId = new URL(page.url()).searchParams.get("workspace")
    const view = await requestJson(
      page.request,
      `/api/focused/workspaces/${workspaceId}`,
      "get",
    )
    expect(view.arm).toBe(expected)
  })
}

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

  await page
    .getByRole("button", { name: "Add version by copying the current version" })
    .click()
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

test("a blank version starts empty", async ({ page }) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)

  await page.getByRole("button", { name: "Add a blank version" }).click()
  await expect(page.getByTestId("notepad-version-v2")).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  for (const part of ["framing", "prior", "method", "expected"]) {
    await expect(page.getByTestId(`notepad-part-${part}`)).toHaveValue("")
  }
})


test("a queued edit stays with the version where it was typed", async ({
  page,
}) => {
  const { workspaceId } = await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  await page
    .getByRole("button", { name: "Add version by copying the current version" })
    .click()

  await page.getByTestId("notepad-part-framing").fill("Late v2 wording.")
  await page.getByTestId("notepad-version-v1").click()
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    POSITION.framing,
  )

  await expect(async () => {
    const state = await requestJson(
      page.request,
      `/api/focused/workspaces/${workspaceId}`,
      "get",
    )
    expect(state.notepad.versions[0].doc.framing).toBe(POSITION.framing)
    expect(state.notepad.versions[1].doc.framing).toBe("Late v2 wording.")
  }).toPass({ timeout: 15_000 })
})

test("copy waits for the active version's queued edit", async ({ page }) => {
  const { workspaceId } = await notepadWorkspace(page, "guided")
  await openGroupChat(page)

  await page
    .getByTestId("notepad-part-framing")
    .fill("Wording that must be present in both versions.")
  await page
    .getByRole("button", { name: "Add version by copying the current version" })
    .click()

  await expect(page.getByTestId("notepad-version-v2")).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    "Wording that must be present in both versions.",
  )
  const state = await requestJson(
    page.request,
    `/api/focused/workspaces/${workspaceId}`,
    "get",
  )
  expect(
    state.notepad.versions.map(
      (version: { doc: { framing: string } }) => version.doc.framing,
    ),
  ).toEqual([
    "Wording that must be present in both versions.",
    "Wording that must be present in both versions.",
  ])
})

test("copy retries a queued edit after a failed autosave", async ({ page }) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  let failFirst: () => void = () => undefined
  const firstMayFail = new Promise<void>((resolve) => {
    failFirst = resolve
  })
  let patchCount = 0
  await page.route("**/api/focused/sessions/*/notepad/part", async (route) => {
    patchCount += 1
    if (patchCount === 1) {
      await firstMayFail
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Autosave failed." }),
      })
      return
    }
    await route.continue()
  })

  await page
    .getByTestId("notepad-part-framing")
    .fill("Retry this wording before copying.")
  await expect.poll(() => patchCount).toBe(1)
  const copy = page.getByRole("button", {
    name: "Add version by copying the current version",
  })
  await copy.click()
  failFirst()
  await expect(
    page.getByTestId("notepad-panel").getByRole("alert"),
  ).toHaveText("Autosave failed.")
  await expect(page.getByTestId("notepad-version-v2")).toHaveCount(0)

  await copy.click()
  await expect(page.getByTestId("notepad-version-v2")).toBeVisible()
  await expect(page.getByTestId("notepad-part-framing")).toHaveValue(
    "Retry this wording before copying.",
  )
})

test("autosave ordering survives leaving and reopening the chat", async ({
  page,
}) => {
  const { workspaceId } = await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  let releaseFirst: () => void = () => undefined
  const firstHeld = new Promise<void>((resolve) => {
    releaseFirst = resolve
  })
  let patchCount = 0
  await page.route("**/api/focused/sessions/*/notepad/part", async (route) => {
    patchCount += 1
    if (patchCount === 1) await firstHeld
    await route.continue()
  })

  await page.getByTestId("notepad-part-framing").fill("First in-flight wording.")
  await expect.poll(() => patchCount).toBe(1)
  await page.getByTestId("notepad-part-framing").fill("Older queued wording.")
  await page
    .getByRole("button", { name: "Build another Perspective" })
    .click()
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await page.getByTestId("notepad-part-framing").fill("Newest wording.")

  await page.waitForTimeout(600)
  expect(patchCount).toBe(1)
  releaseFirst()
  await expect.poll(() => patchCount).toBe(3)
  await expect(async () => {
    const state = await requestJson(
      page.request,
      `/api/focused/workspaces/${workspaceId}`,
      "get",
    )
    expect(state.notepad.versions[0].doc.framing).toBe("Newest wording.")
  }).toPass({ timeout: 15_000 })
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

test("the edit draft opens from your latest wording, not a frozen copy", async ({
  page,
}) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  await page.getByRole("button", { name: /Let agents discuss/ }).click()
  await expect(page.getByTestId("notepad-conversation")).toContainText("[1]", {
    timeout: 30_000,
  })
  await page.getByLabel("Which part the summary goes to").selectOption("prior")
  await page.getByRole("button", { name: /Summarize so far/ }).click()

  const proposal = page.getByTestId("notepad-proposal")
  await expect(proposal).toBeVisible({ timeout: 30_000 })

  // Type after the card is already on screen, then take the edit path.
  const typed = `${POSITION.prior} Typed after the card appeared.`
  await page.getByTestId("notepad-part-prior").fill(typed)
  await expect(proposal).toContainText("Typed after the card appeared.", {
    timeout: 15_000,
  })

  await proposal.getByRole("button", { name: "Edit", exact: true }).click()
  // The draft is created when the editor opens, so it carries the newer
  // wording; a draft frozen at first render would clobber it on accept.
  await expect(proposal.getByLabel("Your wording")).toHaveValue(
    /Typed after the card appeared\./,
  )
  await proposal
    .getByRole("button", { name: /Accept with this wording/ })
    .click()

  await expect(proposal).toBeHidden({ timeout: 30_000 })
  await expect(page.getByTestId("notepad-part-prior")).toHaveValue(
    /Typed after the card appeared\./,
  )
})


test("approving after your own edit keeps both", async ({ page }) => {
  await notepadWorkspace(page, "guided")
  await openGroupChat(page)
  await page.getByRole("button", { name: /Let agents discuss/ }).click()
  await expect(page.getByTestId("notepad-conversation")).toContainText("[1]", {
    timeout: 30_000,
  })
  await page.getByLabel("Which part the summary goes to").selectOption("prior")
  await page.getByRole("button", { name: /Summarize so far/ }).click()

  const proposal = page.getByTestId("notepad-proposal")
  await expect(proposal).toBeVisible({ timeout: 30_000 })

  // Keep typing while the card waits: the notepad is always editable.
  const edit = `${POSITION.prior} And my own qualification.`
  await page.getByTestId("notepad-part-prior").fill(edit)
  // The card's diff follows the live wording rather than a frozen copy.
  await expect(proposal).toContainText("And my own qualification.", {
    timeout: 15_000,
  })

  await proposal.getByRole("button", { name: "Approve", exact: true }).click()
  await expect(proposal).toBeHidden({ timeout: 30_000 })

  const prior = page.getByTestId("notepad-part-prior")
  // Both survive: approval folds the panel's addition onto the newer text
  // instead of restoring the wording the proposal was raised against.
  await expect(prior).toHaveValue(/And my own qualification\./)
  await expect(prior).toHaveValue(/The discussion so far/)
  await expect(page.getByTestId("notepad-conversation")).toContainText(
    "folded into your newer wording",
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
    proposal.getByRole("button", { name: "Copy into the document" }),
  ).toBeVisible()
  await expect(proposal.getByRole("button")).toHaveCount(1)
  await expect(proposal).not.toContainText("Cites")

  await proposal
    .getByRole("button", { name: "Copy into the document" })
    .click()
  await expect(proposal).toBeHidden({ timeout: 30_000 })
  await expect(page.getByTestId("notepad-part-framing")).not.toHaveValue(
    POSITION.framing,
  )
})

test("a reload lands back in the discussion", async ({ page }) => {
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

test("there is one surface: no flag reaches the old Thread board", async ({
  page,
}) => {
  const { workspaceId } = await notepadWorkspace(page, "guided")
  // The rollback route is gone, so a stale link lands on the document stage
  // rather than a second, competing surface.
  await page.goto(`/focused?workspace=${workspaceId}&surface=threads`)
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(page.getByTestId("notepad-conversation")).toBeVisible({
    timeout: 30_000,
  })
  await expect(
    page.getByRole("dialog", { name: "Set up the panel" }),
  ).toHaveCount(0)
})
