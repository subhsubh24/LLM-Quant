#!/usr/bin/env node
/**
 * validate-computation — the deterministic COMPUTATION-INTEGRITY gate (FACTORY_STANDARD §22).
 * Twin of validate-gtm: validate-gtm proves a metric is SOURCED; this proves any COMMITTED
 * quantitative figure is CORRECTLY COMPUTED + REPRODUCIBLE. Fails CLOSED on a real mismatch,
 * and PASSES vacuously when nothing is registered (the pre-launch norm) so it can never block
 * a merge until real analyses exist.
 *
 * Contract (see analysis/README.md): register each computed figure in `analysis/figures.json`:
 *   { "figures": [
 *       { "id": "ltv_cac", "script": "analysis/ltv_cac.mjs", "value": 3.2, "tolerance": 0.01 }
 *   ] }
 * The referenced script computes from COMMITTED inputs and prints its result as the last
 * numeric token on stdout (or a JSON object with a numeric `value`). This gate:
 *   1. runs each script (node/.mjs·.js, python3/.py, bash/.sh) with a timeout,
 *   2. asserts the printed value == the cited `value` (within `tolerance`, default 1e-9),
 *   3. re-runs it and asserts the output is IDENTICAL (determinism — §22 requires it),
 *   4. FAILs on any missing script, run error, mismatch, or nondeterminism.
 * Figures sourced from LIVE analytics (not committed inputs) belong to validate-gtm, not here.
 *
 * Usage: node scripts/validate-computation.mjs      Reads only committed files. Never prints secrets.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MANIFEST = path.join(ROOT, "analysis/figures.json");
const TIMEOUT_MS = 60_000;
const errors = [];

function readManifest() {
  if (!fs.existsSync(MANIFEST)) return null;
  let raw;
  try { raw = JSON.parse(fs.readFileSync(MANIFEST, "utf8")); }
  catch (e) { errors.push(`analysis/figures.json is not valid JSON: ${e.message}`); return { figures: [] }; }
  const figs = Array.isArray(raw?.figures) ? raw.figures : [];
  return { figures: figs };
}

function runner(scriptPath) {
  const ext = path.extname(scriptPath).toLowerCase();
  if (ext === ".mjs" || ext === ".js") return ["node", [scriptPath]];
  if (ext === ".py") return ["python3", [scriptPath]];
  if (ext === ".sh") return ["bash", [scriptPath]];
  return null;
}

function runOnce(cmd, args) {
  const r = spawnSync(cmd, args, { cwd: ROOT, timeout: TIMEOUT_MS, encoding: "utf8" });
  if (r.error) return { ok: false, err: `${r.error.code || r.error.message}` };
  if (r.status !== 0) return { ok: false, err: `exit ${r.status}: ${(r.stderr || "").trim().slice(0, 200)}` };
  return { ok: true, out: (r.stdout || "").trim() };
}

// last numeric token, or JSON {value:N}
function parseValue(out) {
  try { const j = JSON.parse(out); if (j && typeof j.value === "number") return j.value; } catch {}
  const m = out.match(/-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?/g);
  return m ? Number(m[m.length - 1]) : NaN;
}

const manifest = readManifest();
if (manifest === null || manifest.figures.length === 0) {
  console.log("validate-computation: no registered figures (analysis/figures.json absent/empty) — nothing to verify. PASS.");
  process.exit(errors.length ? 1 : 0);
}

for (const f of manifest.figures) {
  const id = f?.id ?? "(unnamed)";
  if (!f || typeof f.script !== "string" || typeof f.value !== "number") {
    errors.push(`figure "${id}": needs string "script" + numeric "value".`); continue;
  }
  const abs = path.join(ROOT, f.script);
  if (!fs.existsSync(abs)) { errors.push(`figure "${id}": script not found: ${f.script}`); continue; }
  const run = runner(f.script);
  if (!run) { errors.push(`figure "${id}": unsupported script type: ${f.script}`); continue; }
  const a = runOnce(run[0], run[1]);
  if (!a.ok) { errors.push(`figure "${id}": ${f.script} failed to run — ${a.err}`); continue; }
  const b = runOnce(run[0], run[1]);
  if (!b.ok || a.out !== b.out) { errors.push(`figure "${id}": ${f.script} is NON-DETERMINISTIC (two runs differ).`); continue; }
  const got = parseValue(a.out);
  const tol = typeof f.tolerance === "number" ? f.tolerance : 1e-9;
  if (!Number.isFinite(got)) { errors.push(`figure "${id}": could not parse a number from ${f.script} output.`); continue; }
  if (Math.abs(got - f.value) > tol) {
    errors.push(`figure "${id}": cited ${f.value} but ${f.script} computes ${got} (|Δ|=${Math.abs(got - f.value)} > tol ${tol}).`);
  }
}

if (errors.length) {
  console.error("validate-computation FAILED — a committed figure is mis-computed or non-reproducible (§22):");
  for (const e of errors) console.error("  - " + e);
  process.exit(1);
}
console.log(`validate-computation: ${manifest.figures.length} figure(s) verified against their scripts. PASS.`);
process.exit(0);
