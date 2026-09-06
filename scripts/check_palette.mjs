/**
 * Validate the chart palettes that ship, and record the result.
 *
 * The palette is read from web/lib/theme.ts rather than restated here, so this checks the colours
 * the browser actually draws. Two shapes are validated separately because they are different
 * problems: a series palette is judged on *adjacent* pairs, since that is what a reader compares,
 * while the three scatter colours can appear in any combination and are judged on all pairs.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const theme = readFileSync("web/lib/theme.ts", "utf8");
const read = (block, mode) => {
  const outer = theme.match(new RegExp(`${block}[^=]*=\\s*\\{([\\s\\S]*?)\\n\\};`));
  const inner = outer[1].match(new RegExp(`${mode}:\\s*\\[([^\\]]+)\\]`));
  return inner[1].replace(/["'\s]/g, "").split(",").filter(Boolean);
};

const checks = [];
for (const [block, pairs] of [["SERIES", "adjacent"], ["SCATTER", "all"]]) {
  for (const mode of ["light", "dark"]) {
    const colours = read(block, mode);
    const args = ["scripts/validate_palette.js", colours.join(","), "--mode", mode];
    if (pairs === "all") args.push("--pairs", "all");
    const output = execFileSync("node", args, { encoding: "utf8" });
    checks.push({
      palette: block,
      mode,
      pairs,
      colours,
      passed: output.includes("ALL CHECKS PASS"),
      // A contrast warning is not dismissable: it obliges the chart to carry a visible label or a
      // table view. Both exist — every chart page renders a DataTable of the same figures — so it
      // is recorded rather than silenced.
      contrast_warning: output.includes("[WARN] Contrast vs surface"),
      report: output.trim(),
    });
  }
}

const failed = checks.filter((c) => !c.passed);
writeFileSync(
  "docs/results/palette.json",
  `${JSON.stringify(
    {
      provenance: "REAL",
      note:
        "Colourblind separation, lightness band, chroma floor and contrast for the palettes in " +
        "web/lib/theme.ts, computed rather than eyeballed. Contrast warnings are answered by the " +
        "table view every chart page carries, which is the relief the standard asks for.",
      checked_at: new Date().toISOString(),
      palettes: checks.length,
      failed: failed.length,
      checks,
    },
    null,
    2,
  )}\n`,
);

for (const c of checks) {
  const mark = c.passed ? "pass" : "FAIL";
  console.log(`${c.palette.padEnd(8)} ${c.mode.padEnd(6)} ${c.pairs.padEnd(9)} ${mark}`);
}
if (failed.length) process.exit(1);
console.log(`\n${checks.length} palettes validated -> docs/results/palette.json`);
