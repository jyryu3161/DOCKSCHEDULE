import { test, expect, Page } from "@playwright/test";

const gnina = (extra = {}) => ({ active: null, status: null, scored: 2, failed: 1, pending: 0, top_n: 3, can_resume: true, ...extra });
const job = (g: object | null) => ({
  id: "A", owner_id: 1, owner_name: "Test", receptor_id: "receptor", kind: "screen", name: "GNINA test",
  status: "completed", total: 4, completed: 4, failed: 0, cpu_ids: [], parameters: {}, created_at: "2026-10-16T00:00:00",
  ...(g ? { gnina: g } : {}),
});
const rank = (consensus: number) => ({ vina: consensus, cnn_affinity: consensus, cnn_score: consensus, cnn_vs: consensus, consensus });
const noRank = { vina: null, cnn_affinity: null, cnn_score: null, cnn_vs: null, consensus: null };
const rows = [
  { id: 1, cid: "scored 1", status: "succeeded", affinity: -9.1, row_number: 1,
    gnina: { status: "succeeded", cnn_score: 0.812, cnn_affinity: 6.25, cnn_vs: 5.075, gnina_vina: -8.8, error: null, rank: rank(1) } },
  { id: 2, cid: "failed 2", status: "succeeded", affinity: -8.7, row_number: 2,
    gnina: { status: "failed", cnn_score: null, cnn_affinity: null, cnn_vs: null, gnina_vina: null, error: "시간 초과", rank: noRank } },
  { id: 3, cid: "pending 3", status: "succeeded", affinity: -8.1, row_number: 3,
    gnina: { status: "pending", cnn_score: null, cnn_affinity: null, cnn_vs: null, gnina_vina: null, error: null, rank: noRank } },
  { id: 4, cid: "outside 4", status: "succeeded", affinity: -6.0, row_number: 4, gnina: null },
];

async function mockApi(page: Page, g: object | null, requests: URL[] = []) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 1, name: "Test", role: "admin", status: "approved" } });
    if (path === "/api/jobs/A") return route.fulfill({ json: job(g) });
    if (path === "/api/jobs/A/interaction-index") return route.fulfill({ json: {
      eligible: 4, analyzed: 0, failed: 0, remaining: 4, busy: false, job: null, failures: [], residues: [] } });
    if (path === "/api/jobs/A/results") { requests.push(url); return route.fulfill({ json: { total: rows.length, page: 1, rows } }); }
    return route.fulfill({ json: [] });
  });
}

test("GNINA columns, statuses, sort/weight/min score parameters and resume button", async ({ page }) => {
  const requests: URL[] = [];
  await mockApi(page, gnina(), requests);
  await page.goto("/#job/A");
  await expect(page.getByRole("heading", { name: "GNINA 재점수화" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "CNNaffinity" })).toBeVisible();
  const scored = page.getByRole("row", { name: /scored 1/ });
  await expect(scored).toContainText("0.812");
  await expect(scored).toContainText("6.25");
  await expect(page.getByRole("row", { name: /failed 2/ })).toContainText("GNINA 실패");
  await expect(page.getByRole("row", { name: /pending 3/ })).toContainText("미계산");
  await expect(page.getByRole("row", { name: /outside 4/ })).toContainText("미계산");
  await expect(page.getByRole("button", { name: "GNINA 이어서 계산" })).toBeVisible();

  const request = page.waitForRequest((r) => r.url().includes("sort=consensus"));
  await page.getByLabel("정렬").selectOption("consensus");
  expect(new URL((await request).url()).searchParams.get("w")).toBe("0.5");
  const weighted = page.waitForRequest((r) => r.url().includes("w=0.75"));
  await page.locator('input[type="range"]').fill("0.75");
  await weighted;
  const filtered = page.waitForRequest((r) => r.url().includes("min_cnn_score=0.4"));
  await page.getByLabel("최소 CNNscore").fill("0.4");
  await filtered;
  const last = requests[requests.length - 1].searchParams;
  expect(last.get("sort")).toBe("consensus");
});

test("resume posts to the gnina endpoint, hides while active and the panel is absent without GNINA data", async ({ page }) => {
  let posted = false;
  await mockApi(page, gnina());
  await page.route("**/api/jobs/A/gnina", (route) => { posted = true; return route.fulfill({ status: 201, json: { id: "G" } }); });
  await page.goto("/#job/A");
  await page.getByRole("button", { name: "GNINA 이어서 계산" }).click();
  await expect.poll(() => posted).toBe(true);

  const active = await page.context().newPage();
  await mockApi(active, gnina({ active: "G", status: "running", can_resume: false }));
  await active.goto("/#job/A");
  await expect(active.getByText("순위는 현재까지 계산된 결과 기준입니다.")).toBeVisible();
  await expect(active.getByRole("button", { name: "GNINA 이어서 계산" })).toHaveCount(0);
  await expect(active.getByRole("row", { name: /pending 3/ })).toContainText("계산 중");
  let cancelled = false;
  await active.route("**/api/jobs/G/cancel", (route) => { cancelled = true; return route.fulfill({ json: {} }); });
  await active.getByRole("button", { name: "GNINA 계산 취소" }).click();
  await expect.poll(() => cancelled).toBe(true);

  const none = await page.context().newPage();
  await mockApi(none, gnina({ scored: 0, failed: 0, pending: 0, can_resume: false }));
  await none.goto("/#job/A");
  await expect(none.getByRole("columnheader", { name: "Affinity" })).toBeVisible();
  await expect(none.getByRole("heading", { name: "GNINA 재점수화" })).toHaveCount(0);
});
