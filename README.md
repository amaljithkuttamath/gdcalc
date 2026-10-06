# gdcalc

A CLI-first Python conversion engine that turns ENSOFT GROUP raw reports into Mathcad Prime pile-design worksheets. The output contains native inputs and equations so **Mathcad calculates the design outputs inside the file**. A bundled Codex skill uses the same engine.

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

gdcalc inspect report.gp11t
gdcalc convert report.gp11t \
  --template reference.mcdx --output outputs/pile-design.mcdx
gdcalc validate outputs/pile-design.mcdx
```

Without installation, `python3 scripts/cli.py` supports the same subcommands after installing `requirements.txt`. Use `gdcalc convert --help` for options. `GDCALC_TEMPLATE` can hold a private default template path.

Open the result in Mathcad Prime and press **Ctrl+F5**. Generation produces an audit JSON alongside the worksheet. Existing output files are never overwritten.

The default uses the **final summary only**: axial load from local pile-top reactions, shear/moments from local pile effects. Strength cases are identified by `STR` names. Use `--cases 1-10` when explicit selection is required, or `--load-source reactions` for a deliberate local top-reaction basis.

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

`convert` accepts keyword options `cases`, `load_source`, `title` and `overrides`. It stages the worksheet and audit before creating their final paths, and checks layout capacity against pile IDs from **all** final-summary cases. Only selected cases feed the load envelopes. Output storage must support local file hard links; unsupported filesystems return an error without replacing existing files.

Source layout: `src/gdcalc/engine.py` exposes the API, `group_report.py` parses reports, `mcdx.py` builds native worksheets, and `cli.py` provides commands. `SKILL.md` is the agent-facing wrapper; it does not contain a separate calculation implementation.

## Scope

- Inputs: `.gp11t` and text GROUP reports using kip/in units.
- Outputs: native `.mcdx` inputs, envelope formulas, and retained template design equations.
- Template: the fixed-head compression-pile profile described in [the template contract](references/template-contract.md).
- No cloud upload, Excel macros, or GROUP analysis execution.
- No bundled engineering data or design template in the public repository.

Geometry, materials, fixity, downdrag, headers and dates are inherited from the user's template. Review them for each project. Component envelopes are independent, not concurrent load combinations. Native Mathcad opening, rendering and calculation must be verified in Mathcad; ZIP/XML checks do not establish native compatibility or engineering adequacy.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use synthetic text and package fixtures and check source selection, native formula dependencies, validation failures, and overwrite protection. No proprietary report or worksheet is required.
