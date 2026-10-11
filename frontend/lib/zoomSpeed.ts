/**
 * How fast a wheel or trackpad pinch zooms the charts. lightweight-charts zooms
 * by deltaY / 100 per wheel event with no speed option, and a Mac trackpad's
 * two-finger swipe or pinch sends deltaY of only 1 to 10, so zoom crawls while
 * the sideways pan (a fixed 80 px per unit) feels fine. The charts multiply
 * deltaY by this factor before the library sees it. A choice of this device
 * (trackpad and mouse differ), so it lives in browser storage, not in the
 * settings shared with the user's other devices.
 */
export const ZOOM_SPEEDS = { slow: 1, normal: 3, fast: 6 } as const;
export type ZoomSpeed = keyof typeof ZOOM_SPEEDS;
export const ZOOM_SPEED_NAMES: Record<ZoomSpeed, string> = { slow: "Slow", normal: "Normal", fast: "Fast" };
export const ZOOM_SPEED_KEY = "tradejournal.charts.zoomSpeed.v1";

let current: ZoomSpeed | null = null;
export function readZoomSpeed(): ZoomSpeed {
  if (current) return current;
  let saved: string | null = null;
  try { saved = localStorage.getItem(ZOOM_SPEED_KEY); } catch { /* device storage is optional */ }
  current = saved === "slow" || saved === "fast" ? saved : "normal";
  return current;
}
export function writeZoomSpeed(speed: ZoomSpeed) {
  current = speed;
  try { localStorage.setItem(ZOOM_SPEED_KEY, speed); } catch { /* remembered for this visit only */ }
}
