import { test, expect, Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const pdb = readFileSync("../tests/fixtures/1L83.pdb", "utf8");
const sdf = readFileSync("../tests/fixtures/interaction-pose.sdf", "utf8");
const lines = pdb.split("\n").filter((line) => /^(ATOM  |HETATM)/.test(line));
const atomIndices = lines.flatMap((line, index) => Number(line.slice(22, 26)) === 78 ? [index] : []);
const proteinIndex = atomIndices.find((index) => lines[index].slice(12, 16).trim() === "CG1")!;
const position = [30, 38, 46].map((offset) => Number(lines[proteinIndex].slice(offset, offset+8)));
const contact = {
  id: "hydrophobic-1", kind: "hydrophobic", type: "Hydrophobic", role: "",
  residue: { key: "A:78:", name: "ILE", chain: "A", number: 78, insertion: "", atom_indices: atomIndices },
  protein_atoms: [{ index: proteinIndex, number: Number(lines[proteinIndex].slice(6, 11)), label: "CG1", element: "C", position }],
  ligand_atoms: [{ index: 6, number: 7, label: "C7", element: "C", position: [25.893, 6.045, 6.353] }],
  ligand_position: [25.893, 6.045, 6.353], protein_position: position, distance: 3.363, angles: {},
};
const report = { engine: "ProLIF", engine_version: "2.2.3", interactions: [contact], warnings: ["테스트용 응답"] };
const job = {
  id: "A", owner_id: 1, owner_name: "Test", receptor_id: "receptor", kind: "screen", name: "Interaction test",
  status: "completed", total: 2, completed: 2, failed: 0, cpu_ids: [], parameters: {}, created_at: "2026-10-16T00:00:00",
};

test("library residue/type filters, all residues, candidate export and viewer selection", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#job/A");
  const panel = page.getByRole("region", { name: "잔기별 후보 찾기" });
  await expect(panel.getByRole("button", { name: "후보 찾기", exact: true })).toBeDisabled();
  await panel.getByRole("checkbox", { name: "A:ILE 78", exact: true }).check();
  await panel.getByRole("checkbox", { name: "B:ASN 78", exact: true }).check();
  await panel.getByLabel("여러 잔기 조건").selectOption("all");
  const request = page.waitForRequest((r) => r.url().includes("/results?") && r.url().includes("interaction=true"));
  await panel.getByRole("button", { name: "후보 찾기", exact: true }).click();
  const params = new URL((await request).url()).searchParams;
  expect(params.getAll("residue")).toEqual(["A:78:", "B:78:"]);
  expect(params.getAll("kind")).toEqual(["hydrogen_bond"]);
  expect(params.get("match")).toBe("all");
  await expect(page.getByRole("heading", { name: "상호작용 일치 후보" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "pose 1" })).toHaveCount(0);
  await expect(page.locator(".candidate-matches")).toContainText("수소결합");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "후보 CSV" }).click();
  expect(readFileSync((await (await downloadEvent).path())!, "utf8")).toContain("hydrogen_bond");
  await page.getByRole("cell", { name: "pose 2" }).click();
  await expect(page.locator(".viewer canvas")).toBeVisible();
  await panel.getByRole("checkbox", { name: "수소결합", exact: true }).uncheck();
  await panel.getByRole("checkbox", { name: "염다리", exact: true }).check();
  await panel.getByRole("button", { name: "후보 찾기", exact: true }).click();
  await expect(page.getByText("분석 완료 항목 중 선택한 조건에 일치하는 후보가 없습니다.")).toBeVisible();
  await panel.getByRole("button", { name: "필터 해제" }).click();
  await expect(page.getByRole("cell", { name: "pose 1" })).toBeVisible();
});

test("library backfill reports queued work and supports cancellation on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  let started = false, cancelled = false;
  await page.route("**/api/jobs/A/interaction-index", (route) => {
    if (route.request().method() === "POST") { started = true; return route.fulfill({ status: 201, json: { id: "analysis" } }); }
    return route.fulfill({ json: { eligible: 2, analyzed: 0, remaining: 2, failed: 0, busy: started && !cancelled,
      residues: [contact.residue], failures: [], job: started ? { ...job, id: "analysis", status: cancelled ? "cancelled" : "queued", completed: 0 } : null,
    } });
  });
  await page.route("**/api/jobs/analysis/cancel", (route) => { cancelled = true; return route.fulfill({ json: {} }); });
  await page.goto("/#job/A");
  const panel = page.getByRole("region", { name: "잔기별 후보 찾기" });
  await panel.getByRole("button", { name: "라이브러리 상호작용 분석" }).click();
  await expect(panel).toContainText("최근 분석: 대기 중");
  await expect(panel.getByRole("button", { name: "미분석·실패 항목 분석" })).toBeDisabled();
  await panel.getByRole("button", { name: "분석 취소", exact: true }).click();
  await expect(panel).toContainText("최근 분석: 취소");
  await expect(panel.getByRole("button", { name: "미분석·실패 항목 분석" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: 1, name: "Test", role: "admin", status: "approved" } });
    if (path === "/api/settings") return route.fulfill({ json: { values: { cpu_budget: 8 }, allocated_cpus: 0, active_students: 0, queued: 0 } });
    if (path === "/api/jobs/A") return route.fulfill({ json: job });
    if (path === "/api/jobs/A/interaction-index") return route.fulfill({ json: {
      eligible: 2, analyzed: 2, failed: 0, remaining: 0, busy: false, job: null, failures: [],
      residues: [contact.residue, { ...contact.residue, key: "B:78:", chain: "B", name: "ASN" },
        { ...contact.residue, key: "A:78:A", insertion: "A", name: "LYS" }],
    } });
    if (path === "/api/jobs/A/results" && url.searchParams.has("interaction")) {
      const ids = url.searchParams.getAll("kind").includes("hydrogen_bond")
        ? url.searchParams.get("match") === "all" ? [2] : [1, 2] : [];
      return route.fulfill({ json: { total: ids.length, page: 1, rows: ids.map((id) => ({ id, cid: `pose ${id}`, status: "succeeded", affinity: -5.4, row_number: id,
        matched_interactions: [{ residue: contact.residue, kind: "hydrogen_bond", count: 2, distance: 3 }],
      })) } });
    }
    if (path.endsWith("/interaction-candidates.csv")) return route.fulfill({
      contentType: "text/csv", headers: { "Content-Disposition": 'attachment; filename="candidates.csv"' },
      body: 'CID,matched_interactions\npose 2,A:ILE 78 | hydrogen_bond\n',
    });
    if (path === "/api/jobs/A/results") return route.fulfill({ json: {
      total: 2, page: 1, rows: [1, 2].map((id) => ({ id, cid: `pose ${id}`, status: "succeeded", affinity: -5.4, row_number: id })),
    } });
    if (path.endsWith("/file/pdb")) return route.fulfill({ contentType: "text/plain", body: pdb });
    if (path.endsWith("/sdf")) return route.fulfill({ contentType: "chemical/x-mdl-sdfile", body: sdf });
    if (path.endsWith("/interactions")) return route.fulfill({ json: report });
    return route.fulfill({ json: [] });
  });
}

test("pose interaction table, filters, atom labels, 3D highlight and CSV work together", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mockApi(page);
  await page.goto("/#job/A");
  await page.getByRole("cell", { name: "pose 1" }).click();
  const panel = page.getByRole("region", { name: "단백질–리간드 상호작용" });
  await expect(panel.getByRole("cell", { name: "C7", exact: true })).toBeVisible();
  await expect(panel.getByRole("cell", { name: "A:ILE 78" })).toBeVisible();
  await expect(page.locator(".viewer canvas")).toBeVisible();
  await panel.getByRole("button", { name: "소수성 접촉", exact: true }).click();
  await expect(page.locator(".viewer-interaction")).toContainText("A:ILE 78 · 3.36 Å");
  await panel.getByLabel("리간드 원자 번호").check();
  const downloadEvent = page.waitForEvent("download");
  await panel.getByRole("button", { name: "상호작용 CSV" }).click();
  const download = await downloadEvent;
  const csv = readFileSync((await download.path())!, "utf8");
  expect(csv).toContain('"C7","3.363"');
  expect(csv).toContain('"A","ILE","78"');
  await panel.getByLabel("3D 상호작용 표시").uncheck();
  await expect(page.locator(".viewer-interaction")).toHaveCount(0);
  await panel.getByLabel("3D 상호작용 표시").check();
  await page.screenshot({ path: "../test-results/browser/interactions.png", fullPage: true });
  await panel.getByRole("checkbox", { name: "소수성 접촉" }).uncheck();
  await expect(panel.getByText("선택한 유형의 상호작용이 없습니다.")).toBeVisible();
  await expect(page.locator(".viewer-interaction")).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "상호작용 CSV" })).toBeDisabled();
  expect(errors).toEqual([]);
});

test("changing pose clears previous interactions and late responses cannot replace the current pose", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/jobs/A/compounds/1/interactions", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.fulfill({ json: report });
  });
  await page.route("**/api/jobs/A/compounds/2/interactions", (route) => route.fulfill({ json: { ...report, interactions: [] } }));
  await page.goto("/#job/A");
  await page.getByRole("cell", { name: "pose 1" }).click();
  await expect(page.getByText("선택한 pose의 상호작용을 분석하는 중…")).toBeVisible();
  await page.getByRole("cell", { name: "pose 2" }).click();
  await expect(page.getByText("현재 거리·각도 기준을 만족하는 상호작용이 검출되지 않았습니다.")).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.getByRole("cell", { name: "C7", exact: true })).toHaveCount(0);
  await expect(page.locator(".viewer-interaction")).toHaveCount(0);
});

test("analysis failure keeps pose available and can be retried on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  let failed = true;
  await page.route("**/api/jobs/A/compounds/1/interactions", (route) => failed
    ? route.fulfill({ status: 503, json: { detail: "다른 pose를 분석하고 있습니다." } })
    : route.fulfill({ json: report }));
  await page.goto("/#job/A");
  await page.getByRole("cell", { name: "pose 1" }).click();
  await expect(page.getByRole("alert")).toContainText("다른 pose를 분석하고 있습니다.");
  await expect(page.locator(".viewer canvas")).toBeVisible();
  await expect(page.getByRole("link", { name: "Pose SDF", exact: true })).toBeVisible();
  failed = false;
  await page.getByRole("button", { name: "분석 다시 시도" }).click();
  await expect(page.getByRole("cell", { name: "C7", exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
