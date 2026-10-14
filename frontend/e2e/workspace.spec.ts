import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
const env = readFileSync("../.env", "utf8");
const password =
  process.env.ADMIN_PASSWORD ||
  env.match(/^ADMIN_PASSWORD=['"]?([^'"\r\n]+)['"]?$/m)![1];

test("login, dashboard, linked residue selection, grid and pose viewer", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "실습 공간에 로그인" }),
  ).toBeVisible();
  mkdirSync("../test-results/screenshots", { recursive: true });
  await page.screenshot({
    path: "../test-results/screenshots/login.png",
    fullPage: true,
  });
  await page.getByLabel("아이디", { exact: true }).fill("admin");
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Screening 대시보드" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../test-results/screenshots/dashboard.png",
    fullPage: true,
  });
  const receptors = await page.request
    .get("/api/receptors")
    .then((r) => r.json());
  const ready = receptors.find((r: any) => r.status === "ready");
  expect(ready).toBeTruthy();
  await page.goto("/#new");
  await page.getByLabel("저장된 단백질").selectOption(ready.id);
  await expect(page.locator(".sequence button").first()).toBeVisible();
  await page.locator(".sequence button").first().click();
  await expect(page.locator(".sequence button.selected")).toHaveCount(1);
  await expect(page.getByLabel("중심 X", { exact: true })).not.toHaveValue("0");
  await expect(page.locator(".viewer canvas")).toBeVisible();
  const canvas = page.locator(".viewer canvas");
  await canvas.scrollIntoViewIfNeeded();
  const box = await canvas.boundingBox();
  expect(box).toBeTruthy();
  for (const [x, y] of [
    [0.5, 0.55],
    [0.55, 0.65],
    [0.46, 0.55],
    [0.6, 0.6],
    [0.48, 0.7],
  ]) {
    await canvas.click({ position: { x: box!.width * x, y: box!.height * y } });
    await page.waitForTimeout(150);
    if ((await page.locator(".sequence button.selected").count()) !== 1) break;
  }
  await expect(page.locator(".sequence button.selected")).not.toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../test-results/screenshots/new-screening.png",
    fullPage: true,
  });
  const jobs = await page.request.get("/api/jobs").then((r) => r.json());
  const task = jobs.find((j: any) => j.kind === "screen" && j.completed > 0);
  expect(task).toBeTruthy();
  await page.goto("/#job/" + task.id);
  await page.locator(".result-list tbody tr").first().click();
  await expect(page.locator(".pose-panel canvas")).toBeVisible();
  await expect(page.locator(".affinity")).toContainText("kcal/mol");
  await expect(page.locator(".viewer-error")).toHaveCount(0);
  await page.screenshot({
    path: "../test-results/screenshots/results.png",
    fullPage: true,
  });
  await page.goto("/#admin");
  await expect(
    page.getByRole("heading", { name: "실습 공간 관리" }),
  ).toBeVisible();
  await expect(page.getByLabel("전체 계산 CPU 한도")).toBeVisible();
  await page.screenshot({
    path: "../test-results/screenshots/admin.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#dashboard");
  await expect(
    page.getByRole("heading", { name: "Screening 대시보드" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../test-results/screenshots/mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "실습 공간에 로그인" }),
  ).toBeVisible();
});
