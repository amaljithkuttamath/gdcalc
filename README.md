# gdcalc

A CLI-first pipeline that turns ENSOFT GROUP raw reports into executable engineering worksheets. **CalcpadCE is the required open-source calculation engine** for both CLI and browser workflows. Every conversion also exports native Mathcad Prime formulas. A bundled Codex skill uses the same engine.

## Usage

Python 3.10+ is required. Install directly from GitHub:

```bash
uv tool install git+https://github.com/amaljithkuttamath/gdcalc.git
```

From a clone, use `uv tool install .`, or an isolated virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install .

# One-time setup; requires Git and the .NET 10 SDK.
gdcalc setup-engine

gdcalc inspect report.gp11t
gdcalc convert report.gp11t \
  --template reference.mcdx --output outputs/pile-design.mcdx
gdcalc validate outputs/pile-design.mcdx
```

Without installation, `python3 scripts/cli.py` supports the same subcommands after installing `requirements.txt`. Use `gdcalc convert --help` for options. `GDCALC_TEMPLATE` can hold a private default template path.

`setup-engine` builds a pinned MIT-licensed [CalcpadCE](https://github.com/imartincei/CalcpadCE) revision into `~/.cache/gdcalc/calcpad`. Its self-contained executable needs no .NET SDK at runtime. `--dotnet`, `--source` and `--install-dir` support existing build tools/checkouts and custom locations. Set `GDCALC_ENGINE_DIR` for a custom install or `GDCALC_CALCPAD` to an executable. Conversion never downloads code or contacts a calculation service.

Every successful conversion writes four files:

- `.cpd`: executable Calcpad worksheet with inputs and formulas, calculated by CalcpadCE.
- `.html`: the locally calculated result snapshot, viewable in any browser.
- `.mcdx`: native Mathcad inputs/formulas, without stale result caches; open in Prime and press **Ctrl+F5** to recalculate there.
- `.audit.json`: source selection, hashes, retained assumptions, calculation engine revision and region mapping.

The calculator is required, not an optional export. Unsupported expressions, incompatible units and calculation failures stop publication of the output bundle. Existing files are never overwritten. A completed calculation does not mean every design check passes.

The default uses the **final summary only**: axial load from local pile-top reactions, shear/moments from local pile effects. Strength cases are identified by `STR` names. Use `--cases 1-10` when explicit selection is required, or `--load-source reactions` for a deliberate local top-reaction basis.

## Bulk conversion pipeline

```bash
gdcalc batch ./raw-reports --recursive \
  --template reference.mcdx --output-dir ./converted --workers 4

# Repeat the same command with --resume to skip verified completed outputs.
gdcalc batch ./raw-reports --recursive \
  --template reference.mcdx --output-dir ./converted --workers 4 --resume

# Explicit files and multiple folders are also accepted.
gdcalc batch first.gp11t second.txt ./more-reports \
  --template reference.mcdx --output-dir ./converted
```

The same core engine handles every job. Bounded worker processes convert reports independently, with an append-only `batch-manifest.jsonl`, source/template snapshots, package checks and per-file failures. Duplicate basenames get distinct job directories. Job identity includes source path/content, template content, case selection, load basis, overrides and calculator/translator versions. Changed inputs create new outputs. Resume checks identity, all worksheet artifact hashes, calculation evidence and package structure; incomplete or damaged output pairs fail without being overwritten.

Progress is JSON Lines on stderr; stdout is a JSON summary. Exit codes: **0** all succeeded/skipped, **1** one or more jobs failed, **2** invalid setup. Use `--quiet` to suppress progress. The manifest and output directory are reusable by external schedulers; two batches cannot write to the same directory simultaneously. `--cases`, `--load-source` and `--set` apply to every report in a batch; group reports by compatible template/assumptions.

Open the same output directory in the browser with `gdcalc serve --output-dir ./converted`; **Saved outputs** exposes completed files and diffs. Native output calculations remain in the `.mcdx` file and require Mathcad; this pipeline does not insert Python-computed design results.

The library API is `gdcalc.batch.convert_batch(inputs, template, output_dir, workers=4, recursive=True, resume=True)`. For distributed processing, partition jobs across output directories and invoke this command from your scheduler. The browser server itself is a single trusted workspace, not a distributed job queue.

## Browser workflow

```bash
gdcalc serve --template reference.mcdx --output-dir ./outputs
```

This opens the converter with four steps: **Files → Inputs → Changes → Outputs**. Select multiple files or a folder, inspect the original report and template, review cases and load envelopes, compare changed expressions, then generate worksheets and audits. The document viewer stays beside the controls and switches between report, template, worksheet and diff. Existing `.mcdx` files can be uploaded for inspection and package validation.

The primary file view reconstructs the worksheet using its saved region coordinates, page settings, header, formatted text, images and native equations. A collapsible strip of actual page thumbnails, page navigation, zoom and search preserve the document layout. Input review emphasizes the five local load values; case selection stays in an expandable section. Saved Mathcad values are labeled as cached, never as recalculated. A separate Results tab shows fresh CalcpadCE results; Changes compares native expressions. CalcpadCE executes translated scalar formulas locally on the server; the original-file inspector does not reproduce Prime's layout. The `.cpd` and `.mcdx` files retain their executable formulas. Complete outputs and source snapshots persist; Saved outputs restores them after a server restart. The input queue resets on refresh.

For Docker and HTTPS cloud deployment, see [deployment instructions](deploy/README.md). The repository includes a non-root Docker image, Compose with persistent storage, an optional Caddy TLS proxy, and authenticated network mode. Public deployment contains no engineering documents. Cloud mode explicitly identifies that files are uploaded to the server.

## Install as a Codex skill

```bash
git clone https://github.com/amaljithkuttamath/gdcalc.git ~/.codex/skills/gdcalc
```

Then invoke `$gdcalc` with your report and template. A private default template may be placed at `assets/local/reference.mcdx`; that directory is ignored by Git.

## Core engine API

The core API works independently of the CLI or Codex:

```python
from gdcalc.engine import inspect_report, convert, validate

info = inspect_report("report.gp11t")
result = convert("report.gp11t", "reference.mcdx", "outputs/design.mcdx")
checks = validate(result["output"])
```

`convert` accepts keyword options `cases`, `load_source`, `title` and `overrides`. It calculates and stages all four artifacts before creating their final paths, publishing the audit last as the completion marker, and checks layout capacity against pile IDs from **all** final-summary cases. Only selected cases feed the load envelopes. Output storage must support local file hard links; unsupported filesystems return an error without replacing existing files.

Source layout: `src/gdcalc/engine.py` exposes the API, `group_report.py` parses reports, `mcdx.py` builds native worksheets, and `cli.py` provides commands. `SKILL.md` is the agent-facing wrapper; it does not contain a separate calculation implementation.

## Scope

- Inputs: `.gp11t` and text GROUP reports using kip/in units.
- Outputs: executable `.cpd`, calculated `.html`, native `.mcdx` and audit JSON.
- Template: the fixed-head compression-pile profile described in [the template contract](references/template-contract.md).
- Local mode does not upload to the cloud. Hosted mode sends selected files to your configured server. No Excel macros or GROUP execution.
- No bundled engineering data or design template in the public repository.

Geometry, materials, fixity, downdrag, headers and dates are inherited from the user's template. Review them for each project. Component envelopes are independent, not concurrent load combinations. Native Mathcad opening, rendering and calculation must be verified in Mathcad; ZIP/XML checks do not establish native compatibility or engineering adequacy.

## Calculation scope

The strict adapter supports scalar real arithmetic, `min`/`max`/`abs`, powers/roots, `in`/`ft`/`kip`/`ksi`, comparisons (including chains), conditionals, early returns and string check messages. Mathcad zero comparisons adopt the other operand's units. String values use distinct internal symbols and are rendered as their original messages; strings are never silently used as numeric engineering values. Other constructs fail explicitly. This is not a general-purpose Mathcad importer.

CalcpadCE calculates the translated formulas; it does not execute `.mcdx` directly. Its results are separate from Prime-native verification. Text/layout/images remain available in the original-file inspector; the calculated page follows equation order and is not a reproduction of the original page layout. `.html` is a snapshot; open `.cpd` with CalcpadCE to edit and recalculate independently.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Install the calculator with `gdcalc setup-engine` before running tests. Tests execute the real calculator with synthetic text and package fixtures and check source selection, native formula dependencies, validation failures, and overwrite protection. No proprietary report or worksheet is required.
