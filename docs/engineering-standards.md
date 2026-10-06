# Engineering standards and value provenance

Status: design requirements for a future standards register. The current app checks its parser/template contract and executes supported formulas; it does not implement a general code-compliance database.

Many engineering quantities have governing references, but not every value has a universal code-prescribed number or safe range. Distinguish measured/imported values, catalog properties, project assumptions, code factors and calculated outputs.

## Source categories

| Quantity | Governing source or context | Validation to capture |
| --- | --- | --- |
| Axial force, shears and moments | Analysis report, selected combinations, local axes and sign convention | Source file/table/case/pile, units, factor status, signs and transformation into the design envelope |
| Steel section dimensions/properties | Identified section catalog and edition | Exact section designation, table/version, units and consistency across properties |
| Material strength and other properties | Specified grade/material standard and project specification | Grade, product applicability, applicable edition and source of each property |
| Pile layout, lengths and fixity | Drawings, project design basis and analysis model | Geometry provenance, axes, effective-length assumptions and explicitly reviewed overrides |
| Geotechnical resistance and downdrag | Site-specific investigation/design report and selected method | Report/revision, nominal versus factored/allowable basis, load treatment and supporting assumptions |
| Load/resistance factors and capacity equations | Governing design code, edition, amendments and applicable limit state | Clause/equation/table identifier, applicability and calculation method |
| Capacity/utilization results | The executed worksheet using the declared inputs and rules | Input lineage, calculation revision, valid applicability, units and check outcome |

For steel properties, AISC publishes the Steel Construction Manual and associated Shapes Database. AISC 360 provides structural-steel design requirements including LRFD and ASD. These are distinct sources with different purposes. [AISC Manual/resources](https://www.aisc.org/aisc/publications/steel-construction-manual/), [AISC 360](https://www.aisc.org/aisc/publications/current-standards/aisc-360/)

For bridge work, AASHTO LRFD Bridge Design Specifications is a candidate governing reference; the current published tenth edition is dated 2024 and has published errata. Project adoption and owner amendments determine which edition applies. Do not automatically migrate an existing project to the newest code. [AASHTO publication](https://store.transportation.org/Item/PublicationDetail?ID=5377)

FHWA GEC 12 provides driven-pile foundation guidance and design examples. Guidance and project-specific geotechnical evidence need to be distinguished from the governing specification. [FHWA GEC 12](https://www.fhwa.dot.gov/engineering/geotech/pubs/gec12/index.cfm)

## Project design basis

Before asserting compliance, the project must identify jurisdiction/owner, governing code and edition, amendments/errata, design method, limit states, material and section references, geotechnical basis, and applicable units/axis conventions. These are project choices, not facts to infer from a filename.

A rule record should contain a stable rule ID and version, cited authority/edition/clause, applicability conditions, expected value type and dimension, required dependencies, calculation/check expression, severity, and reviewer/approval state. A value record should contain its variable ID, quantity/unit, source reference, transformation history, linked rule IDs and review state.

Example conceptual record (not an implemented schema or an engineering recommendation):

```json
{
  "variable": "P_a",
  "dimension": "force",
  "display_unit": "kip",
  "source_kind": "analysis_report",
  "source_reference": null,
  "load_basis": "factored_compression_before_downdrag",
  "governing_code": null,
  "code_edition": null,
  "applicable_rule_ids": [],
  "review_state": "needs_project_basis"
}
```

The name/basis above follows the current template adapter. Another template must explicitly map its own conventions. The null fields intentionally prevent a guessed code reference from appearing authoritative.

## Execution and UI requirements

- Separate data validity (type/unit/source), rule applicability, numerical execution and design-check outcome.
- Display value → source → governing reference → check result in the worksheet inspector. Each citation should name edition and clause/table, not just “per code.”
- Return explicit `missing_basis`, `not_applicable`, `unsupported`, `calculation_error`, `pass` or `fail` states as appropriate. Missing standards evidence must never become a green compliance indicator.
- Bind rules and source datasets to versions/hashes so later code/catalog updates do not silently alter a past calculation.
- Record reviewed overrides with reasons. Do not silently cap imported loads or replace project inputs with generic “standard” values.
- Keep code-compliance status separate from professional review/approval. A passing numerical check is evidence about that check, not approval of the entire design.
- Link to licensed standards and store permitted references/metadata; do not bundle copyrighted rulebooks or assume every downloadable catalog permits redistribution.

## Tests required for implementation

Test equivalent-unit inputs, incompatible dimensions, missing/ambiguous references, wrong grade/shape/edition, incompatible nominal/factored bases, rule applicability boundaries, pass/fail thresholds, changed errata/version invalidation and override provenance. Use synthetic fixtures and independently reviewed reference calculations. A domain reviewer must approve encoded engineering clauses before the app labels them supported.
