# Engineering workflow and offline project plan

This is the recorded product plan for issue #32, not a claim that desktop installers, persistent project review or a 3D structural solver have shipped. The observed workflow is pile-design calculation using a GROUP report and a private Mathcad template. Validate the proposed review/delivery steps with practicing engineers before encoding firm policy.

| Stage | Engineer's inputs/actions | What works now | Project record to add |
| --- | --- | --- | --- |
| Establish basis | Project/member, code editions, drawings, geotechnical report, materials, geometry | Template inputs and explicit overrides | Versioned references, sources, reasons and reviewer state |
| Analyze | Create loads/cases in external analysis software | Import GROUP final local summary | Tool/version, original export and load/axis conventions |
| Reconcile | Open report/template; select cases; review mapped loads | CLI/SDK inspection and browser input/diff views | Confirmed mapping with exact source locations |
| Calculate | Execute the engineer's formula template | Same engine produces MCDX, CPD, calculated HTML and audit | Immutable run/revision ID, settings and artifact manifest |
| Review | Trace governing values to equations and compare revisions | Source snapshots, audits, rendered equations and changes | Comments and declared reviewer identity tied to a specific revision |
| Issue | Send an approved calculation package | Download existing artifact bundle | Portable package, review record, manifest/hashes and future PDF |
| Revise | Import changed loads or assumptions and recalculate | New output names preserve earlier files | Parent revision, affected dependencies and invalidated reviews |

## What the final product should retain

A local project directory contains a versioned SQLite index plus immutable file blobs and manifests. Reuse existing audit/source hashes and snapshot behavior. Keep project identity separate from filenames. Each run records source/template content hashes, parser/engine revisions, selected cases, load basis, overrides/reasons, results/errors and all output hashes. Review annotations refer to immutable revision IDs; editing an input creates a new revision and invalidates affected approvals. Locally declared names are not verified signatures.

Export/import must produce a portable manifest plus relative content references, reject traversal/duplicate entries, verify hashes, preserve original files and migrate schemas explicitly. Treat project-index and artifact backup/restore as one operation. Recover interrupted writes from a committed manifest; never infer success from a partial worksheet.

The first project-store implementation should cover one local project and one calculation profile. Do not add cloud sync, a separate solver or a code-compliance claim to that storage ticket.

## Offline acceptance

Desktop distribution is a future delivery surface for the existing shared UI/engine. Windows and Linux installers must bundle a platform-compatible runtime/calculator and local assets. End users should not need Python, a .NET SDK, login or a CDN to perform core work after downloading an installer. Current Python installs still need one-time calculator setup; current Linux containers bundle it.

Test installation, import, inspection, supported input edits, calculation, save/reopen, review and export with outbound networking denied. Include spaces/Unicode paths, owned-process cleanup, interrupted publication, project transfer, upgrades and restore. A Linux container check is not Windows installer evidence. Missing optional resources must be explicit, never silently fetched during a calculation. Updates and future sync are opt-in and must not block local use.

## 3D inspection boundary

A future scene displays explicit geometry and imported/calculated results from the same run as the worksheet. It records units, axes, pile/case IDs and provenance. Missing geometry or displacement data remains unavailable. Independent envelope extrema cannot drive a concurrent response animation. Use [the reuse study](research/template-driven-3d.md) to select a renderer; it does not replace an analysis solver or certify template calculations.

## Delivery sequence

1. Validate creator → checker → recipient workflows using consented, sanitized examples. Record accepted submission formats and who approves changes.
2. Implement versioned local project/source records, portable manifests and interruption recovery using the existing audit model.
3. Package the shared app/calculator for Windows and Linux; verify network-denied operation and installation lifecycle on each platform.
4. Add revision-bound comments, review transitions and issue packages; obtain firm-specific review/signature requirements.
5. Add more source/template adapters and provider-specific distributed hosting behind the same engine. Introduce sync only after conflict/recovery semantics are defined.

Open questions: Which files arrive first and from whom? Which values are copied manually? Which code editions and owner amendments apply? Which tools require licenses? Is the accepted submission MCDX, PDF, spreadsheet or a drawing schedule? How are checker comments and revisions reconciled? Who can issue a calculation? These require user/engineer evidence, not guesses from the sample filenames.

See [design basis and standards](engineering-standards.md), [current architecture](architecture.md) and [deployment](../deploy/README.md) for the existing boundaries.
