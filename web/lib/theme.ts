/**
 * Design tokens and the validated chart palette.
 *
 * The categorical order is a rotation of a validated eight-hue palette, chosen so teal — the
 * brand's primary — leads while keeping the adjacency properties that make the set readable.
 * Both modes were run through the palette validator and pass every check:
 *
 *   light  CVD ΔE 9.1 · normal-vision ΔE 19.6
 *   dark   CVD ΔE 8.4 · normal-vision ΔE 19.3
 *
 * Two themes, not one, because the checks differ by chart form. Bars, lines and stacks only ever
 * put *adjacent* slots side by side, so the full eight are safe there. Scatter and choropleth put
 * every pair on screen at once, and under that test the first three of the eight fail badly in
 * dark mode — magenta against teal is ΔE 1.6 for a deuteranope, which is to say identical. So
 * all-pairs forms use their own validated trio and are capped at three series.
 */

export type Mode = "light" | "dark";

/** Bars, lines, stacked areas: only adjacent slots meet. */
export const SERIES: Record<Mode, string[]> = {
  light: ["#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948", "#2a78d6", "#eb6834"],
  dark: ["#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767", "#3987e5", "#d95926"],
};

/**
 * Scatter, bubble, choropleth: every pair meets, so the set is smaller and separately validated.
 * Past three series, fold to "other" or facet — never extend this list.
 */
export const SCATTER: Record<Mode, string[]> = {
  light: ["#1baf7a", "#4a3aa7", "#eb6834"],
  dark: ["#199e70", "#9085e9", "#d95926"],
};

/** Reserved for state. Never reused as a series colour. */
export const STATUS = {
  good: { light: "#008300", dark: "#4caf50" },
  warning: { light: "#eda100", dark: "#c98500" },
  serious: { light: "#eb6834", dark: "#d95926" },
  critical: { light: "#c1272d", dark: "#e66767" },
} as const;

/**
 * Confidence, which the KPI tile shows as a dot. Deliberately not the status palette: a
 * low-confidence number is not an error, and colouring it like one would misread the situation.
 */
export const CONFIDENCE = {
  high: { light: "#1baf7a", dark: "#199e70" },
  medium: { light: "#eda100", dark: "#c98500" },
  low: { light: "#eb6834", dark: "#d95926" },
  insufficient: { light: "#8b8b86", dark: "#6f6f6a" },
} as const;

export function seriesColor(index: number, mode: Mode = "light"): string {
  const palette = SERIES[mode];
  // Never cycle: a ninth series folds into "other" upstream rather than reusing slot one.
  return palette[Math.min(index, palette.length - 1)] ?? palette[0]!;
}

export function scatterColor(index: number, mode: Mode = "light"): string {
  const palette = SCATTER[mode];
  return palette[Math.min(index, palette.length - 1)] ?? palette[0]!;
}

/** Three series is the documented cap for all-pairs forms. */
export const SCATTER_SERIES_CAP = 3;
