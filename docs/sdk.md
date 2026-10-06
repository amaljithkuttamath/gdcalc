# Python SDK

The `mcdxkit` Python distribution contains the SDK, `mcdxkit` command and browser server. The supported import surface is `mcdxkit.engine`. The CLI and server call this same engine; no agent host is required.

Install the published SDK from PyPI in an isolated Python environment:

```bash
python -m pip install mcdxkit==0.3.0
```

For source development, install a clone with `python -m pip install -e .`. Installation includes web assets and calculator bridge source, but not a compiled Calcpad runtime, Mathcad, engineering standards or a private template. Run `mcdxkit setup-engine` once with Git and .NET 10 SDK available, or point `MCDXKIT_CALCPAD` at a compatible existing calculator. Conversion requires the [supported template](../references/template-contract.md).

## Inspect, convert and validate

```python
from pathlib import Path
from mcdxkit.engine import inspect_report, convert, validate

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
| `inspect_report(report, *, cases=None, load_source='effects')` | Returns cases, selected IDs, unresolved selection reason, envelope and largest observed pile ID. Does not execute the calculator. Explicit invalid selection raises `ValueError`. |
| `convert(report, template, output, *, cases=None, load_source='effects', title=None, overrides=None)` | Calculates and returns the audit dictionary with final artifact paths, source hash, selection/envelope, calculation evidence and `checks`/`check_summary` ([check results](calculation.md#check-results)). Publishes `.mcdx`, `.cpd`, `.html`, `.audit.json`, with audit last. |
| `summarize_report(report, *, cases=None, load_source='effects', origin=None)` | Returns one row dict per final-summary case with per-case loads (kip, kip-in), `selected`, `governs` and `source_sha256`. Unresolved or invalid selection raises `ValueError`. |
| `summarize_audit(audit, *, origin=None)` | Same rows for a completed conversion, re-parsed from its `_source` snapshot after verifying the audited hash, with the audited cases and load basis. |
| `summary_key(rows)` | Identity of one summarized input (source hash, load basis, selected cases), used by the CLI and server to skip identical duplicates. |
| `summary_csv(rows)` | Renders rows as CSV text; columns are listed in [the summary guide](cli.md#summary-csv-across-reports). It does not write files. |
| `validate(worksheet)` | Returns package integrity results. Does not execute Prime or prove engineering compliance. |

Paths accept strings or `pathlib.Path`. `cases` is a list of integer case IDs, not the CLI's comma-separated string. `load_source` is `effects` or `reactions`; see [load semantics](cli.md). `overrides` is a mapping of supported literal template input names to numeric values in that input's existing units, subject to the template contract. Never derive geometry from a desired pass result.

Inputs, templates and existing outputs are not overwritten. Each concurrent conversion must use a distinct output basename. Output storage must support hard links. Source parsing and invalid inputs generally raise `ValueError`; filesystem and calculator failures propagate their corresponding exceptions. Catch exceptions at the application boundary and record a failed job; do not replace results with zero or stale files. A successful conversion can contain failing engineering checks; read `result["check_summary"]["failed"]` and treat `status == "no checks found"` as unknown, not passed.

The SDK is pre-1.0. Pin the package version in integrations; treat other module functions as internal and audit dictionaries as extensible (ignore unfamiliar keys). Do not infer engineering approval from successful return or Prime-native execution from a Calcpad calculation. Large-scale users can use the [batch CLI](cli.md#batch-conversion) for bounded workers, manifests and verified resume.

## Distribution checks

CI tests the installed package with synthetic reports/templates and the real calculator. Release CI installs the actual wheel and runs the full suite before uploading that same distribution to PyPI. See [release setup](releasing.md) and [testing standards](testing.md).
