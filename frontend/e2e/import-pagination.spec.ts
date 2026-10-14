import { test, expect, Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const env = readFileSync("../.env", "utf8");
const password =
  process.env.ADMIN_PASSWORD ||
  env.match(/^ADMIN_PASSWORD=['"]?([^'"\r\n]+)['"]?$/m)![1];

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("아이디", { exact: true }).fill("admin");
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Screening 대시보드" }),
  ).toBeVisible();
}

test("Excel vendor CSV preview finds real header and Catalog ID automatically", async ({
  page,
}) => {
  await login(page);
  await page.goto("/#new");
  await page.locator('input[type="file"][accept*=".csv"]').setInputFiles({
    name: "excel-preview-regression.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      '\ufeffsep=,\r\nSMILES,Catalog ID,note\r\nCCO,001,"valid, quoted"\r\n',
    ),
  });
  await expect(page.locator(".preview-table tbody tr")).toHaveCount(1);
  await expect(page.getByLabel("CID 컬럼", { exact: true })).toHaveValue(
    "Catalog ID",
  );
  await expect(page.getByLabel("SMILES 컬럼", { exact: true })).toHaveValue(
    "SMILES",
  );
  await expect(page.locator(".preview-table tbody tr")).toContainText("001");
  await expect(page.locator(".preview-table tbody tr")).toContainText(
    "valid, quoted",
  );
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("job page size persists and the last full page has no extra next page", async ({
  page,
}) => {
  await page.route("**/api/jobs?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    const limit = Number(query.get("limit") || 100);
    const offset = Number(query.get("offset") || 0);
    const search = (query.get("search") || "").toLowerCase();
    const all = Array.from({ length: 40 }, (_, i) => ({
      id: String(i + 1),
      name: `Pagination row ${i + 1}`,
      owner_name: "Test",
      kind: "screen",
      status: "completed",
      total: 1,
      completed: 1,
      failed: 0,
      cpu_ids: [],
      parameters: {},
      created_at: "2026-10-14T00:00:00",
    })).filter((row) => row.name.toLowerCase().includes(search));
    await route.fulfill({
      json: {
        rows: all.slice(offset, offset + limit),
        total: all.length,
        limit,
        offset,
      },
    });
  });
  await login(page);
  const size = page.getByLabel("페이지당 표시", { exact: true });
  await size.selectOption("10");
  await expect(page.locator(".panel tbody tr")).toHaveCount(10);
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.locator(".panel tbody tr").first()).toContainText(
    "Pagination row 11",
  );
  await size.selectOption("20");
  await expect(page.locator(".panel tbody tr")).toHaveCount(20);
  await expect(page.locator(".panel tbody tr").first()).toContainText(
    "Pagination row 1",
  );
  await page.reload();
  await expect(size).toHaveValue("20");
  await expect(page.locator(".panel tbody tr")).toHaveCount(20);
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.locator(".panel tbody tr").first()).toContainText(
    "Pagination row 21",
  );
  await expect(
    page.getByRole("button", { name: "다음", exact: true }),
  ).toBeDisabled();
  await expect(page.locator(".jobs-pagination")).toContainText("2 / 2");
  await page.getByPlaceholder("작업 이름 검색").fill("row 40");
  await expect(page.locator(".panel tbody tr")).toHaveCount(1);
  await expect(page.locator(".jobs-pagination")).toContainText("1 / 1");
  await expect(
    page.getByRole("button", { name: "다음", exact: true }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBeTruthy();
});
