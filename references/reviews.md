# MCDXKit reviews

Use these reviews at the relevant workflow stage. Conversion needs the first four; changes to the software also need the affected implementation reviews. Deployment adds operational review. Do not force a repository/security audit onto an ordinary local conversion, or run unrelated review tools just because they are installed. These instructions work with ordinary files, CLI tools and any capable coding agent.

Record each applicable review as **pass**, **fail**, **unverified** or **not applicable**, with the source/artifact/commit inspected and a short reason. “Not applicable” needs a scope reason; missing evidence is “unverified.” Calculation success and design acceptance are separate outcomes. A checklist, installer answer, mock or screenshot cannot substitute for execution evidence. Save detailed review records only in an authorized output/project location, outside the generated worksheet and public source tree when they contain client data.

## Source and units — before mapping loads

- Inspect the actual source's final local-load summary. Confirm selected cases, load basis, unit headers, sign conventions and governing pile/case/line. Cross-check representative extracted values against source lines; parsing success alone is insufficient.
- Reject missing/incompatible units or ambiguous case selection. Ask for needed project information instead of silently choosing earlier/global values or guessing conversion factors.
- Preserve the original and its hash. Independent component maxima are an envelope, not concurrent combinations. Geometry and pile count must come from a reviewed basis, not the largest reported ID.
- Use [the template contract](template-contract.md) and the CLI's supported formats; onboarding answers about Excel or metric files do not add adapter support.

## Template and formulas — before generation

- Inspect the full supplied template and actual input regions. Check mapping, retained geometry/materials/fixity, units and authorized overrides. Surface source/template mismatches.
- Reuse template formulas through the shared engine. Keep dependencies executable and remove stale native caches. Unsupported constructs fail explicitly; saved values must not masquerade as new calculations.
- Inspect the original file and the change preview. Changes belong in requested input definitions, not fabricated result constants. Progress belongs in CLI/browser UI, never worksheet content.

## Calculation evidence — after execution

- Inspect exit status, errors and generated audit/output files. Distinguish package integrity, Calcpad execution, native Prime execution and engineering review in the result.
- For changed parsing/calculation logic, use independently expected synthetic values and real-engine regression tests. A mocked calculator validates orchestration only.
- Check all design failures and unresolved expressions, not just successful job status. Report per-file failures in a batch; verify resume hashes and settings before trusting existing outputs.
- Keep `native_execution_verified` false without actual Prime execution evidence. Opening a ZIP or rendering the file does not establish native calculation. See [the testing contract](../docs/testing.md).

## Engineering basis — before design acceptance

- Identify applicable project basis, code editions/clauses, catalog/geotechnical sources, design method and reviewer evidence. Link each claimed rule to its source, scope and version; avoid invented universal limits.
- An interview answer saying “reviewed template/register” is a declaration to investigate, not approval. Rules without an established basis or qualified review remain awaiting engineering review. Preserve missing/unsupported/not-applicable states instead of turning them into passes.
- Software verification can proceed while engineering review is pending. Do not label the output code-compliant, approved or safe on that basis. Read [engineering standards](../docs/engineering-standards.md) for the register's current scope.

## Architecture and reuse — when changing software

- Read [architecture](../docs/architecture.md) and [design principles](../docs/design-principles.md). Inspect existing engine/adapters before introducing another implementation. Record reused projects, licenses, offline fit and concrete gaps in the ticket/PR.
- Keep one calculation implementation for CLI, SDK, server and skill. Renderers and future simulations consume calculated values with provenance; a geometry view is not a validated physical solver.
- Keep task scope concrete and testable. Identify unsupported capabilities and roadmap work honestly. Avoid introducing distributed services without an actual deployment/storage/concurrency need.

## UI and accessibility — when changing browser workflows

- Exercise Files → Inputs → Changes → Outputs with synthetic files. Ensure the original complete template remains discoverable; distinguish actual-file reconstruction from calculated results and Prime rendering.
- Check progress, error recovery, partial batches, keyboard/focus behavior and narrow layouts relevant to the change. Keep source values/document content central, labels concrete, and navigation clear.
- Verify in a real browser. Record viewport and tested actions; do not claim mobile verification from a desktop screenshot. Use [design principles](../docs/design-principles.md), not a second UI calculation model.

## Security and privacy — when boundaries change

- Review untrusted report/XML/ZIP/upload paths, aggregate expansion limits, traversal/symlinks, rendered HTML isolation, engine timeout/file access and dependency licenses where touched.
- Hosted changes require authentication, Host/Origin and CSRF checks, secret handling, persistent storage and explicit tenant assumptions. A shared workspace is not tenant isolation.
- Keep client files, source snapshots, credentials and setup profiles out of commits, public fixtures and build contexts. Inspect staged files before publication. A local interview grants no deployment or publishing permission.

## Tests, contribution and delivery — before claiming completion

- Use a ticket, focused branch and PR. Follow [AGENTS](../AGENTS.md), [contribution](../CONTRIBUTING.md), [standards](../docs/standards.md) and the [testing matrix](../docs/testing.md). Add meaningful regression and negative cases; check the real package/CLI/browser surface affected.
- Run required lint/types, appropriate tests and packaging checks. Record commands, outcomes and unverified limits. Review the diff for accidental private data, stale docs and changes outside scope.
- **After every push**, identify the exact pushed SHA, inspect its Actions runs and follow them through completion. Fix failures and repeat on the new SHA; old-head green checks do not qualify. Merge only when current required checks pass. Verify post-merge publication before claiming deployment/package availability.
- Do not apply cloud resources merely because scaffolding is requested. Before an authorized live deployment, validate configuration, access, persistence, health and rollback against [deployment guidance](../deploy/README.md); distinguish mocks/schema checks from real infrastructure operation.

## Setup interview and follow-up

The installer records seven optional choices: workflow, source format, template status, units, standards basis, reviewer availability and operating mode. It asks no credentials, client names or private paths. Blank answers stay null and EOF leaves remaining answers unknown. Installation copies committed source only; it does not install dependencies, launch the server, change calculation defaults or validate a project.

Use that context to shorten future setup, not to suppress necessary questions. For example, “offline” means check provisioned dependencies before promising offline execution; “reviewed register” means locate current evidence when the task needs a standards decision. Follow-up questions should name the missing decision and why it matters. Do not repeat the full interview on each invocation.
