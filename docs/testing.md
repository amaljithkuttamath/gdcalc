# Testing and validation contract

Tests should demonstrate externally meaningful behavior. Use independently known expected results, synthetic files and explicit tolerances. Do not merely copy implementation logic into expected-value calculations. Avoid adding snapshot churn or tests for trivial static wording where they do not protect behavior.

## Required validation by change

| Change | Tests and evidence to add or update |
| --- | --- |
| Raw report parsing | Synthetic final-summary fixture; earlier/global decoy tables; missing/duplicate/malformed rows; units, signs and nonfinite data; expected selected cases and governing provenance |
| Case selection/envelopes | STR/SER and unknown names, explicit IDs, missing case rejection, selected versus excluded cases, independent component extrema and geometry-capacity checks |
| Template/package generation | Expected native expression dependencies, original-source preservation, stale-cache removal, ambiguous/missing definitions, unsupported layout and invalid ZIP/XML relationships |
| Calculation translation | Independent numerical expectations with units/tolerances; each new construct and unsupported neighbor; dimensional/type mismatch; hidden errors; no stale or partial results published |
| Engine execution | Real calculator integration for supported operations; timeout/error/incomplete output handling; mocks only for hard-to-produce boundary failures and never as the sole calculation proof |
| Check extraction | Real-engine comparisons with independent expected ratios; failing and passing outcomes; no-checks pages; compound/mismatched operands yield no ratio; older audits reported as unrecorded |
| Artifact publication | Existing-file collisions, failure rollback, source preservation, complete four-file bundle and audit-last semantics |
| Batch/resume | Mixed successful/failed inputs, changed source/template/settings, corrupted/missing artifacts, duplicate basenames and concurrency/locking |
| HTTP/auth/storage | Real loopback requests, unauthenticated access, login/session behavior, CSRF/origin/Host checks, traversal/file ID restrictions, upload limits and error statuses |
| Browser interaction | Actual affected workflow in browser; empty/loading/error/disabled states; keyboard focus and narrow viewport when layout changes; verify generated artifacts rather than screenshot appearance alone |
| Packaging/deployment | Wheel asset/license check, Docker build, tests inside image, live health/auth/asset checks; supported environment variables and startup behavior |
| Prime compatibility | Actual supported Prime build, open/recalculate/output retrieval/save/reopen evidence; numerical and visual compatibility tracked separately |

Not every change needs every row. Explain the selected checks in the PR and add regression coverage for the behavior fixed. Reversible copy/style-only changes need appropriate visual/accessibility review rather than artificial tests mirroring text or CSS.

## Local commands

With the development environment activated and the calculator installed:

```bash
# Focused examples while iterating:
python -m unittest discover -s tests -p 'test_calcpad.py' -v
python -m unittest discover -s tests -p 'test_server.py' -v

# Full application checks:
python -m unittest discover -s tests -v
node --check src/gdcalc/web/app.js

# Distribution checks:
python -m pip install build
python -m build
python scripts/check_package.py
git diff --check
```

`scripts/check_package.py` expects one wheel in `dist/`. When testing a version bump, use a clean build output directory or move earlier wheels aside; do not delete unrelated user artifacts. Tests create their own temporary files and HTTP listeners. Do not point tests at production reports or an existing output directory.

## Numerical assertions

State the expected physical quantity, output unit and tolerance. Choose tolerances based on algorithm/precision requirements, not solely to match a failing output. Include dimensional rejection where relevant. Prefer simple analytical cases, independently derived reference values or trusted published examples with citations. Include boundary and sign cases for engineering comparisons.

A design ratio above its limit can be a correct calculation. Assert both the numeric value and intended check outcome; do not alter inputs to make all checks pass. Distinguish a solver's convergence failure from an engineering failure.

## Fixture and evidence rules

- Reuse or extend synthetic factories in `tests/test_pipeline.py`. Keep fixtures small enough that a reviewer can understand the expected output.
- For a reported private-file bug, minimize it into a synthetic reproducer rather than committing the original.
- Record the CLI command, version/revision and relevant result in the PR. Sanitize logs and screenshots.
- A mocked calculator proves orchestration only. A Calcpad test proves that backend's behavior only. A package check proves structure only.
- If a native runtime, browser or platform is unavailable, record the missing verification explicitly. Do not skip required CI silently or mark unsupported behavior as verified.

## CI and merge gate

The required jobs are `Python 3.10`, `Python 3.12`, `Installable package and browser syntax`, and `Test and publish container`. The container job runs the application tests inside the built image and exercises its HTTP boundary. These jobs must succeed on the current PR head before merge.

Pull requests do not publish images. After merge, the `main` run repeats validation and publishes only the tested image. Verify that run before claiming publication. A newer PR commit invalidates reliance on an older successful run.

## PR evidence example

```text
Ticket: #123
Behavior: malformed final-summary rows are rejected without an earlier-table fallback.
Regression: synthetic report includes a valid earlier table and malformed final table.
Checks: focused parser tests and full suite passed; include the actual run/check link.
Not verified: native Prime execution; this change does not claim native verification.
```
