import { expect, it } from "vitest";
import { actuallyVisible } from "../src/media/visibility";
const viewport = { width: 393, height: 480 };
const rect = {
  left: 20,
  right: 373,
  top: 540,
  bottom: 610,
  width: 353,
  height: 70,
};
it("never marks a below-fold notification as displayed merely because the page is foreground", () => {
  expect(actuallyVisible(rect, viewport, "visible")).toBe(false);
  expect(
    actuallyVisible({ ...rect, top: -200, bottom: -130 }, viewport, "visible"),
  ).toBe(false);
});
it("requires foreground visibility and a meaningful visible slice, including after resize", () => {
  const onscreen = { ...rect, top: 420, bottom: 490 };
  expect(actuallyVisible(onscreen, viewport, "visible")).toBe(true);
  expect(actuallyVisible(onscreen, viewport, "hidden")).toBe(false);
  expect(
    actuallyVisible(onscreen, { ...viewport, height: 430 }, "visible"),
  ).toBe(false);
});
it("does not count zero-sized, horizontal offscreen, or one-pixel fragments", () => {
  expect(
    actuallyVisible({ ...rect, top: 479, bottom: 549 }, viewport, "visible"),
  ).toBe(false);
  expect(
    actuallyVisible(
      { ...rect, top: 10, bottom: 80, left: 500, right: 853 },
      viewport,
      "visible",
    ),
  ).toBe(false);
  expect(
    actuallyVisible(
      { ...rect, top: 0, bottom: 0, height: 0 },
      viewport,
      "visible",
    ),
  ).toBe(false);
});
