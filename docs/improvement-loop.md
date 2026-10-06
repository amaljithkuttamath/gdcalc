# Repository improvement loop

The **Repository improvement audit** workflow runs after a GitHub release is published, every Monday at **13:17 UTC**, and on manual dispatch. Release runs verify the released commit belongs to the default branch; scheduled/manual runs inspect the default branch. These are software checks against synthetic fixtures. They do not inspect private projects, certify engineering standards or call an external AI service.

## What runs

The audit reuses the repository's existing unittest suite, real Calcpad calculator, Ruff, mypy, Node syntax/orchestration tests, distribution build, packaged-asset check and strict metadata validation. Each check has a ten-minute timeout and a separate log. The job has a thirty-minute cap. Prerequisite failure is recorded as unavailable; dependent package checks can be skipped only after a failed build. No package or image is published by this workflow.

The JSON evidence includes the exact commit, workflow run/attempt and measured result for every check. Logs and evidence are retained as Actions artifacts for thirty days. Issues link the run instead of copying raw logs. Once the workflow/artifacts expire, retain relevant sanitized reproduction evidence in the fixing PR.

## Ticket lifecycle

A failed, timed-out or unavailable check creates one issue with a stable per-check marker, affected revision, reproduction command, evidence link, acceptance criteria and regression-test expectations. Later observations update that issue's latest evidence; they do not create duplicate issues or repeated comments. A recurrence after closure reopens the matching ticket. A clean run creates no tickets and does not silently close unresolved work.

A contributor triages the evidence first: distinguish code defects, dependency/service failures and runner setup. Reproduce confirmed behavior, claim the issue, use an issue branch, add meaningful regression coverage, submit a PR, and verify exact-head CI and post-merge publishing. Close the ticket through its fixing PR. Avoid speculative tickets, unreviewed auto-merges or repeated tests without new evidence.

## Permissions and limits

Checking has read-only repository access. Reporting runs separately using reporter code from the default branch, with only contents-read and issues-write access. It validates known check IDs, full revision, run and attempt before creating issues. Concurrency serializes audits. No personal access token or cloud credential is needed. Fork pull requests never invoke the reporter.

A failure before a reviewed checkout/evidence artifact is available remains a failed Actions run; it cannot be turned into an evidence-backed product ticket. Maintainers inspect those infrastructure failures in Actions. Running this scheduled workflow requires GitHub Actions to remain enabled; GitHub controls schedule availability and timing.

## Run locally

From a clean development checkout with the usual test dependencies, Node and calculator installed:

```bash
python scripts/audit_repository.py --output .mcdxkit/audit-001
```

The output directory must be new. Evidence stays local. Do not run against a directory containing private output artifacts; the package check expects a clean `dist/` produced by this checkout. The reporter is dry-run by default. Its `--publish` mode is intended for the workflow, requires matching repository/run/revision context, and writes only known check metadata. Synthetic tests cover create/update/reopen, repeated-run idempotence, malformed evidence and quiet successful runs.

Broader product/design, security and engineering reviews remain in [the review guide](../references/reviews.md). Findings outside this automated check set need the same reproduction/evidence discipline and human triage.
