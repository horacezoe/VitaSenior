type Rect = Pick<
  DOMRect,
  "top" | "right" | "bottom" | "left" | "width" | "height"
>;
/** At least a meaningful slice of the actual element, in a foreground page. */
export function actuallyVisible(
  rect: Rect,
  viewport: { width: number; height: number },
  visibility: string,
) {
  if (visibility !== "visible" || rect.width <= 0 || rect.height <= 0)
    return false;
  const width = Math.max(
    0,
    Math.min(rect.right, viewport.width) - Math.max(rect.left, 0),
  );
  const height = Math.max(
    0,
    Math.min(rect.bottom, viewport.height) - Math.max(rect.top, 0),
  );
  return (
    width >= Math.min(24, rect.width) && height >= Math.min(24, rect.height)
  );
}
