# GitHub workflow

Use the [MCDXKit roadmap](https://github.com/users/amaljithkuttamath/projects/2)
to follow public issues from backlog through implementation and review. Its
repository import and built-in workflows keep new issues and linked PR work
visible. An item in progress is not a promised release date.

## Triage and contribution

- Use [Issues](https://github.com/amaljithkuttamath/mcdxkit/issues) for concrete bugs and acceptance criteria; use [Discussions](https://github.com/amaljithkuttamath/mcdxkit/discussions) for questions and workflow exploration.
- Type labels (`bug`, `enhancement`, `documentation`) describe the change. Area labels identify calculation, parser, UI, release, security or project work. Do not label unconfirmed vulnerabilities in public; use [private reporting](../SECURITY.md).
- The **Correctness and reliability** milestone groups current defects and infrastructure. **Offline engineering workspace** groups future project/provenance work. Neither sets a delivery date.
- Claim a ticket, branch from current main, add relevant tests, open a PR and link the issue. Follow [CONTRIBUTING.md](../CONTRIBUTING.md). CODEOWNERS routes review to the current maintainer; more owners can be added as contributors join.
- Reuse existing implementations first. Record the actual capability gap, license and offline implications before creating a subsystem. See [3D reuse research](research/template-driven-3d.md).

## Configured controls

As checked on 2026-10-06, main requires a PR, a current base, resolved review
conversations and the four existing CI jobs: Python 3.10, Python 3.12, package/browser
checks and the tested container. Administrators are subject to protection. Force
pushes and deletion are blocked; squash merge and automatic branch cleanup are
enabled. The sole-maintainer setup does not require an approving review count;
add independent review requirements when another maintainer can supply them.

CodeQL default setup scans Python and GitHub Actions. Dependabot alerts and
security updates, secret scanning/push protection and private vulnerability
reporting are enabled. Dependabot proposes weekly Actions updates. A successful
scan means the analysis ran; findings still need triage. The initial CodeQL scan
reported an all-interface socket binding in the explicit network deployment
path; do not describe the repository as having no security findings.

## Release and evidence

Main CI builds package artifacts and publishes the container after its tests.
Versioned releases use the separately configured PyPI Trusted Publisher, restricted
to the `pypi` environment and version tags. Follow [releasing.md](releasing.md);
do not confuse a CI artifact with a public package release. Automatic GitHub
release notes group labeled PRs, but maintainers must still explain material
compatibility or numerical changes.

Keep tests, decisions and documentation in the repository. The wiki is not a
second source of product documentation. Only synthetic examples belong in public
issues, PRs and Actions artifacts. Never attach client reports, templates or
generated engineering deliverables.
