# Python SDK

The `gdcalc` Python distribution contains the SDK, `gdcalc` command and browser server. The supported import surface is `gdcalc.engine`. The CLI and server call this same engine; no agent host is required.

Until the first PyPI release is verified, install from GitHub:

```bash
python -m pip install git+https://github.com/amaljithkuttamath/gdcalc.git
```

After publication, the equivalent versioned installation is `python -m pip install gdcalc==0.2.0`. Installation includes web assets and calculator bridge source, but not a compiled Calcpad runtime, Mathcad, engineering standards or a private template. Run `gdcalc setup-engine` once with Git and .NET 10 SDK available, or point `GDCALC_CALCPAD` at a compatible existing calculator. Conversion requires the [supported template](../references/template-contract.md).

## Inspect, convert and validate

```python
from pathlib import Path
from gdcalc.engine import inspect_report, convert, validate

report = Path("inputs/report.gp11t")
info = inspect_report(report)
if info["selection_required"]:
    raise ValueError(info["selection_required"])

result = convert(
    report,
    Path("inputs/reference.mcdx"),
    Path("results/design.mcdx"),
    cases=info["selected_cases"],
    load_source="effects",
)
package_checks = validate(result["output"])
print(result["calculated_worksheet"])
```

| Function | Contract |
| --- | --- |
| `inspect_report(report, *, cases=None, load_source='effects')` | Returns cases, selected IDs, unresolved selection reason, envelope, governing case per component, load outliers (`anomalies`) and largest observed pile ID. Does not execute the calculator. Explicit invalid selection raises `ValueError`. |
| `gdcalc.learn.suggest_cases(report, *, load_source='effects', output_dir=None)` | Offline case-name classification with confidence and evidence, recommended strength cases and outliers; learns from audits under `output_dir`. Advisory: pass the IDs to `cases` explicitly. See [machine learning](machine-learning.md). |
| `convert(report, template, output, *, cases=None, load_source='effects', title=None, overrides=None)` | Calculates and returns the audit dictionary with final artifact paths, source hash, selection/envelope and calculation evidence. Publishes `.mcdx`, `.cpd`, `.html`, `.audit.json`, with audit last. |
| `validate(worksheet)` | Returns package integrity results. Does not execute Prime or prove engineering compliance. |

Paths accept strings or `pathlib.Path`. `cases` is a list of integer case IDs, not the CLI's comma-separated string. `load_source` is `effects` or `reactions`; see [load semantics](cli.md). `overrides` is a mapping of supported literal template input names to numeric values in that input's existing units, subject to the template contract. Never derive geometry from a desired pass result.

Inputs, templates and existing outputs are not overwritten. Each concurrent conversion must use a distinct output basename. Output storage must support hard links. Source parsing and invalid inputs generally raise `ValueError`; filesystem and calculator failures propagate their corresponding exceptions. Catch exceptions at the application boundary and record a failed job; do not replace results with zero or stale files. A successful conversion can contain failing engineering checks.

The SDK is pre-1.0. Pin the package version in integrations; treat other module functions as internal and audit dictionaries as extensible (ignore unfamiliar keys). Do not infer engineering approval from successful return or Prime-native execution from a Calcpad calculation. Large-scale users can use the [batch CLI](cli.md#batch-conversion) for bounded workers, manifests and verified resume.

## Distribution checks

CI tests the installed package with synthetic reports/templates and the real calculator. Release CI installs the actual wheel and runs the full suite before uploading that same distribution to PyPI. See [release setup](releasing.md) and [testing standards](testing.md).
