---
name: gdcalc
description: Use when converting ENSOFT GROUP raw .gp11t or text reports into Mathcad Prime .mcdx pile-design worksheets using the final local-load summary and calculations inside the worksheet.
---

# gdcalc

Generate executable CalcpadCE and Mathcad worksheets from the same inputs and equations. CalcpadCE is required for CLI, batch and browser conversions. Every successful job includes `.cpd`, calculated `.html`, native `.mcdx` and `.audit.json`; no precomputed design results are inserted into Mathcad formulas.

## Run

Use a shell and Python 3.10+ with the repository dependencies. This skill follows the Agent Skills format and does not require a particular agent, model, SDK or proprietary tool. Resolve scripts and references relative to this skill directory, not the agent's working directory. See [docs/cli.md](docs/cli.md) for installation and server operation.

```bash
# One-time calculator setup; requires Git and the .NET 10 SDK.
gdcalc setup-engine
gdcalc inspect /path/to/report.gp11t
gdcalc convert /path/to/report.gp11t \
  --template /path/to/reference.mcdx \
  --output /path/to/outputs/pile-design.mcdx
gdcalc validate /path/to/outputs/pile-design.mcdx
gdcalc serve --template /path/to/reference.mcdx --output-dir /path/to/outputs
```

If the command is not installed, install this repository with `uv tool install /path/to/gdcalc`, or use `python3 /path/to/gdcalc/scripts/cli.py` after installing dependencies in an isolated environment. Run `gdcalc convert --help` for all flags. Use the agent host's normal shell/file tools; no Codex-specific tools are needed.

Prefer an explicit `--template` or `GDCALC_TEMPLATE`. Generic user configuration supports `~/.config/gdcalc/reference.mcdx` (or `$XDG_CONFIG_HOME/gdcalc/reference.mcdx`); a source checkout also supports `assets/local/reference.mcdx`. See the CLI guide for fallback order. Public distribution excludes engineering documents. Preserve supplied sources and create new output paths.

For changes to the software itself, read [AGENTS.md](AGENTS.md), follow the ticket/branch/PR workflow and use the repository's testing standards. Conversion permission does not imply permission to publish files or modify a live deployment.

## Bulk conversion

Use `gdcalc batch /path/to/reports --recursive --template /path/to/reference.mcdx --output-dir /path/to/outputs --workers 4` for multiple reports. Add `--resume` to verify and skip completed jobs. Explicit files and multiple folders are accepted. Case/load-basis/override flags apply to the whole batch, so group inputs by compatible template and assumptions. Read `batch-manifest.jsonl` for per-file failures; return the JSON summary and manifest path. Exit 1 means partial failure, not that all jobs failed. Never silently change source selection to make a failed job succeed.

## Browser and deployment

Use `gdcalc serve` when the user wants to select files/folders or inspect sources, worksheet equations and before/after differences in a browser. Keep the document central and guide Files → Inputs → Changes → Outputs. Local mode binds loopback. For Docker or cloud work, read [deploy/README.md](deploy/README.md); hosted mode uploads to that server and requires authentication. Preserve generated outputs and private source snapshots. Do not publish engineering data with source code.

The browser opens the actual-file layout reconstruction by default, with text, diagrams, positions and saved values from the .mcdx. Results is a separate tab for CalcpadCE calculations. Never substitute a reformatted calculation report for the file view or present saved values as newly calculated. The browser reconstruction is not Prime-native rendering. The adapter is strict: unsupported calculation constructs fail the job; they do not fall back to cached results. Read-only inspection can still expose unsupported expressions and their native XML. CalcpadCE execution does not establish Prime-native execution.

## Interpret the input

- Read load values only from the **last SUMMARY FOR LOAD CASES AND COMBINATIONS**. Earlier case names may classify cases; earlier load values and global tables never supply inputs.
- Default: axial compression from **PILE TOP REACTIONS, LOCAL**; Vy/Vz/My/Mz from **EFFECTS FOR LATERALLY LOADED PILE**. `--load-source reactions` explicitly uses the local pile-top reaction table for all components. These sources can give different shear values.
- Automatically select cases named STR; exclude SER. If names are absent/unrecognized, get the intended case IDs and pass `--cases 1-10` or `--cases 1,3,7`. Do not assume the first ten cases are strength cases in an unfamiliar report.
- The current adapter supports kip and kip-in reports, a compatible fixed-head compression pile template, and a single envelope worksheet. It does not import Excel binaries, design uplift, rerun GROUP, or establish concurrent pile/case combinations.

## Template and output

Read [references/template-contract.md](references/template-contract.md) when choosing another template, changing inputs, or interpreting failures. Template geometry, materials, fixity, downdrag, headers and dates remain inherited. Surface material mismatches. A reported pile ID beyond template capacity requires reviewed geometry and explicit count overrides; the highest observed ID does not establish the total pile count.

`--set n_z=15` updates an authorized literal input while preserving its unit. Never invent missing geometry or silently change design assumptions to make a result pass.

Generation writes `.cpd`, `.html`, `.mcdx` plus `.audit.json` with selected cases, source extrema, load basis, hashes and retained assumptions. Report the output links and selection basis. The file contains no old result cache and uses native dependencies; open it in Mathcad Prime and press **Ctrl+F5** to calculate.

The `.cpd` contains executable translated formulas; `.html` is the calculated snapshot. CalcpadCE currently supports the scalar arithmetic, units and conditional programs described in the README. A successful calculation may still contain failing design checks. ZIP/XML validation proves package integrity only. Label native opening, layout and execution as unverified until actually tested in Mathcad. Do not equate an independently evaluated formula or stored pass message with successful native execution or engineering approval.
