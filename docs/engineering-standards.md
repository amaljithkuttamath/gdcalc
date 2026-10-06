# Engineering standards and value provenance

Status: versioned metadata register shipped. Engineering rules await qualified review. No approved code clauses, universal limits or licensed rulebooks are bundled.

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

## Use the register

After generating outputs, select **Sources & standards** on an output card. It shows the imported quantities, source versions and hashes, selected cases, transformations, worksheet mappings and missing project basis. Download the JSON record, add project references locally, then use **Load register** to inspect that revision against the same output. Loading a register does not change the worksheet or save over a previous record.

```bash
mcdxkit standards init output.audit.json --output engineering-register.json
mcdxkit standards inspect engineering-register.json --audit output.audit.json
```

The CLI writes a new file exclusively; it refuses to overwrite. Exit zero means inspection completed, not that the design passed. SDK callers use `mcdxkit.standards.from_audit(audit)`, `validate(register)` and `assess(register, audit)`.

Schema `engineering-register/1` records:

- Positive integer `revision` and `calculation_sha256`, binding the entire audit revision.
- `project_basis`: owner, jurisdiction, governing code/edition, amendments, design method, material grade, section reference, geotechnical basis, units/axes and load source. Unknowns remain null.
- `sources`: stable `id`, `kind`, `version`, `reference`, `edition` and optional file `sha256`.
- `values`: stable variable `id`, `quantity`, `unit`, `dimension`, `source_id`, `source_version`, `source_locator`, `transformations` and `template_mapping`.
- `rules`: stable `id`, `version`, source ID/version, `clause`, `dimension`, `value_ids`, `applicability`, `check` and optional `review`.
- `overrides`: actual audited variable/quantity, reason and declared review state. Missing reasons remain pending.

Generated values cover five imported load components. Geometry, materials, capacities and factors inherited from the template are not automatically sourced or approved; add their references after engineering review. Vz is retained as evidence and is not silently mapped to a template input. Component extrema are independent, not concurrent load combinations.

## Rule and review records

A rule's `applicability` contains exact project-basis field/value matches. Its `check` names the exact `region_id` and `expression` from an existing calculated audit check. No expressions are evaluated by this register, and no design factors are inserted. A unique check must already have a consistent boolean outcome and numeric 0/1 result.

A qualified reviewer can supply an external `review` record with `decision: "reviewed"`, `reviewer`, timezone-qualified ISO `reviewed_at`, `reason` and `content_sha256`. Compute the latter using `mcdxkit.standards.content_hash(register)` after substantive edits. It excludes rule review records themselves; source, basis, value, rule, override or revision changes invalidate all previous review hashes. Review metadata is **not a digital signature or authenticated professional approval**. MCDXKit does not create or infer the attestation.

Assessment reports `missing_basis`, `not_applicable`, `unsupported`, `calculation_error`, `awaiting_engineering_review`, `pass` or `fail`. Pass/fail are linked numerical outcomes only, after the required metadata and external review are recorded. The overall register never asserts code compliance, and `engineering_approval_verified` and `native_execution_verified` remain false. A CLI audit is user-supplied evidence; the browser additionally checks the actual worksheet and calculated HTML hashes before assessment.

Unit normalization supports force (kip, lbf, N, kN), moment (kip-in, N-m, kN-m, kN-mm), length (m, mm, in, ft), stress (ksi, MPa) and dimensionless values (1). Other units are explicit unsupported states. This is dimensional/provenance inspection, not a second calculation engine.

## Contribution and verification

Use synthetic sources and checks in tests. Test equivalent units, incompatible dimensions, missing references, source-version mismatch, applicability mismatch, stale attestations, changed load basis/quantity, override omissions and tampered calculation artifacts. A domain reviewer must approve the applicability and reference calculations of any encoded engineering clause before it can be called supported. Link licensed standards and store permitted references/metadata; do not redistribute rulebooks.
