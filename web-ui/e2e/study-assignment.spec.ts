import { expect, test, type Page } from "@playwright/test"
type RecordedEvent = {
  participant_id: string | null
  condition: string | null
  action: string
  outcome: string
}


function nextWorkspaceCreation(page: Page) {
  return page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname.endsWith("/focused/workspaces"),
  )
}

test("study assignment bypasses prior work and survives Start over", async ({
  page,
}) => {
  await page.goto("/focused?arm=baseline&demo=1")
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByRole("button", { name: "Start over" })).toBeVisible()
  const priorWorkspaceId = new URL(page.url()).searchParams.get("workspace")
  expect(priorWorkspaceId).not.toBeNull()

  const priorWorkspaceLoads: string[] = []
  page.on("request", (request) => {
    if (
      request.method() === "GET" &&
      new URL(request.url()).pathname.endsWith(
        `/focused/workspaces/${priorWorkspaceId}`,
      )
    ) {
      priorWorkspaceLoads.push(request.url())
    }
  })
  await page.goto(
    "/focused?participant_id=P-0042&condition=baseline-a",
  )
  await page.waitForLoadState("networkidle")
  expect(priorWorkspaceLoads).toEqual([])
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()

  const problem = "How should antibiotic breadth be bounded?"
  await page.getByLabel("Problem").fill(problem)
  const firstCreation = nextWorkspaceCreation(page)
  await page.getByRole("button", { name: "Continue" }).click()
  const firstBody = (await firstCreation).postDataJSON()
  expect(firstBody.participant_id).toBe("P-0042")
  expect(firstBody.condition).toBe("baseline-a")
  await expect(page).toHaveURL(/workspace=/)
  expect(new URL(page.url()).searchParams.has("participant_id")).toBe(false)
  expect(new URL(page.url()).searchParams.has("condition")).toBe(false)

  await page.getByRole("button", { name: "Start over" }).click()
  await expect(page.getByText("Study interaction records remain.")).toBeVisible()
  await page.getByRole("button", { name: "Reset workspace" }).click()
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()

  await page.getByLabel("Problem").fill(problem)
  const secondCreation = nextWorkspaceCreation(page)
  await page.getByRole("button", { name: "Continue" }).click()
  const secondBody = (await secondCreation).postDataJSON()
  expect(secondBody.participant_id).toBe("P-0042")
  expect(secondBody.condition).toBe("baseline-a")
  await expect(page.getByRole("button", { name: "Start over" })).toBeVisible()

  const eventResponse = await page.request.get(
    "http://127.0.0.1:8011/api/v1/testing/study-events",
  )
  expect(eventResponse.ok()).toBeTruthy()
  const events: RecordedEvent[] = await eventResponse.json()
  const participantEvents = events.filter(
    (event) => event.participant_id === "P-0042",
  )
  expect(participantEvents.map((event) => event.action)).toEqual([
    "workspace.create",
    "workspace.delete",
    "workspace.create",
  ])
  expect(participantEvents.map((event) => event.outcome)).toEqual([
    "success",
    "success",
    "success",
  ])
  expect(participantEvents.every((event) => event.condition === "baseline-a")).toBe(
    true,
  )
})
