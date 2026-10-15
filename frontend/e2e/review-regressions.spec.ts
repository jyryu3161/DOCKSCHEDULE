import { test, expect, Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const job = (id: string) => ({
  id,
  owner_id: 1,
  owner_name: "Test",
  receptor_id: "receptor",
  kind: "screen",
  name: `Job ${id}`,
  status: "completed",
  total: 1,
  completed: 0,
  failed: 1,
  cpu_ids: [],
  parameters: {},
  created_at: "2026-10-15T00:00:00",
});

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me")
      return route.fulfill({ json: { id: 1, name: "Test", role: "admin", status: "approved" } });
    if (path === "/api/settings")
      return route.fulfill({ json: { values: { cpu_budget: 8, max_students: 2 }, allocated_cpus: 0, active_students: 0, queued: 0 } });
    if (path === "/api/jobs/summary")
      return route.fulfill({ json: { total: 1, running: 0, done: 1, counts: {} } });
    if (path === "/api/jobs")
      return route.fulfill({ json: { rows: [job("A")], total: 1 } });
    if (/\/jobs\/[^/]+\/results$/.test(path))
      return route.fulfill({ json: { total: 1, page: 1, rows: [{ id: 1, cid: "compound A", status: "failed", error: "test failure", row_number: 1 }] } });
    if (path.endsWith("/interactions"))
      return route.fulfill({ json: { engine: "ProLIF", engine_version: "2.2.3", interactions: [], warnings: [] } });
    if (/\/jobs\/[^/]+$/.test(path))
      return route.fulfill({ json: job(path.split("/").pop()!) });
    return route.fulfill({ json: [] });
  });
}

test("slow polling responses are displayed without overlapping requests", async ({ page }) => {
  await mockApi(page);
  let requests = 0;
  await page.route("**/api/jobs?**", async (route) => {
    requests++;
    await new Promise((resolve) => setTimeout(resolve, 5500));
    await route.fulfill({ json: { rows: [job("slow")], total: 1 } });
  });
  await page.goto("/");
  await expect(page.getByText("Job slow", { exact: true })).toBeVisible({ timeout: 10000 });
  // Development StrictMode can cancel its first mount's request immediately.
  expect(requests).toBeLessThanOrEqual(2);
});

test("changing jobs clears previous results and selected compound while loading", async ({ page }) => {
  await mockApi(page);
  let release: () => void = () => {};
  const delayed = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/jobs/B", async (route) => {
    await delayed;
    await route.fulfill({ json: job("B") });
  });
  await page.goto("/#job/A");
  await expect(page.getByRole("heading", { name: "Job A", exact: true })).toBeVisible();
  await page.getByRole("cell", { name: "compound A" }).click();
  await expect(page.getByRole("heading", { name: "compound A", exact: true })).toBeVisible();
  await page.evaluate(() => { location.hash = "job/B"; });
  await expect(page.getByText("작업을 불러오는 중…")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Job A", exact: true })).toHaveCount(0);
  release();
  await expect(page.getByRole("heading", { name: "Job B", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Docking pose", exact: true })).toBeVisible();
});

test("dashboard loads without downloading the 3D viewer", async ({ page }) => {
  await mockApi(page);
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Screening 대시보드" })).toBeVisible();
  expect(requests.some((url) => /\/Viewer[.-]/.test(url))).toBe(false);
});

test("pose viewer loads on demand and recovers after a failed pose request", async ({ page }) => {
  await mockApi(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/jobs/A/results?**", (route) => route.fulfill({
    json: {
      total: 2,
      page: 1,
      rows: [1, 2].map((id) => ({ id, cid: `pose ${id}`, status: "succeeded", affinity: -4, row_number: id })),
    },
  }));
  await page.route("**/api/receptors/receptor/file/pdb", (route) => route.fulfill({
    contentType: "text/plain",
    body: readFileSync("../tests/fixtures/1L83.pdb", "utf8"),
  }));
  let firstPoseRequests = 0;
  await page.route("**/api/jobs/A/compounds/1/sdf", (route) => {
    firstPoseRequests++;
    return route.fulfill({ status: 404, body: "missing" });
  });
  await page.route("**/api/jobs/A/compounds/2/sdf", (route) => route.fulfill({
    contentType: "chemical/x-mdl-sdfile",
    body: "Ethane\n  test\n\n  2  1  0  0  0  0  0  0  0  0999 V2000\n    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n    1.5000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n  1  2  1  0  0  0  0\nM  END\n$$$$\n",
  }));
  await page.goto("/#job/A");
  await page.getByRole("cell", { name: "pose 1" }).click();
  await expect(page.locator(".viewer-error")).toContainText("Pose 파일을 불러오지 못했습니다.", { timeout: 15000 });
  expect(firstPoseRequests).toBe(1);
  const poseResponse = page.waitForResponse("**/api/jobs/A/compounds/2/sdf");
  await page.getByRole("cell", { name: "pose 2" }).click();
  expect((await poseResponse).status()).toBe(200);
  await expect(page.locator(".viewer-error")).toHaveCount(0);
  await expect(page.locator(".viewer canvas")).toBeVisible();
  await page.screenshot({ path: "../test-results/browser/review-pose.png" });
  expect(errors).toEqual([]);
});
