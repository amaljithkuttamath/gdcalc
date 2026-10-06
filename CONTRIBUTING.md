# Contributing

Start with [AGENTS.md](AGENTS.md), [the architecture](docs/architecture.md) and the [template contract](references/template-contract.md). Use an issue or pull request to describe the concrete behavior being changed, its compatibility scope and how it was verified.

## Tickets, branches and review

1. Open or choose a GitHub issue. Define the problem, acceptance criteria, scope and validation approach. Use the feature or bug form and sanitized synthetic examples.
2. Claim the issue or leave a short implementation note. Break large features into independently reviewable tickets, linking dependencies. Do not silently expand the ticket's scope.
3. Fork the repository if you do not have write access. Start from current `main` and create `feat/<issue>-<description>`, `fix/<issue>-<description>` or `chore/<issue>-<description>`.
4. Implement and run the relevant checks below. Commit the code, tests and documentation together. Open a draft PR early when coordination helps.
5. Link the issue using `Closes #<issue>` and complete the PR template. Resolve review comments and required checks. Branch updates must include the current base when GitHub requires it.
6. A maintainer merges the ready PR using squash merge. Never force-push or delete `main`. The merged commit triggers package/image publication; the linked issue closes automatically.

```bash
git switch main
git pull --ff-only
git switch -c feat/123-descriptive-name
# Make changes, run checks, then commit.
git push -u origin feat/123-descriptive-name
gh pr create --draft --base main
```

For forks, `origin` is your fork and `upstream` is this repository; synchronize your local base from `upstream/main`. Write access is not required to open an issue or propose a PR from a fork. Fork PRs run CI without access to publishing credentials.

Use issue/PR state as the work queue: open issue → claimed work/branch → draft PR → ready for review → merged/closed. Labels describe area or type; an open PR links implementation to its ticket. Required CI protects `main`; maintainers remain responsible for reviewing calculation semantics and acceptance evidence.

## Development setup

Requirements: Python 3.10+, Git; .NET 10 SDK for the initial calculator build; Node.js for JavaScript syntax checks. Docker is needed for container verification.

```bash
git clone https://github.com/amaljithkuttamath/gdcalc.git
cd gdcalc
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
gdcalc setup-engine
gdcalc serve --no-open --port 0 --output-dir ./gdcalc-output
```

Select your own compatible template in the browser. There is no public production template or engineering dataset. Tests generate synthetic inputs and do not need a private template. `setup-engine` builds into a persistent cache and refuses to overwrite it. If already installed, skip setup or build into a new explicit directory.

## Tests and checks

The [testing contract](docs/testing.md) maps each change type to required positive/negative cases. [Repository standards](docs/standards.md) define engineering semantics, code boundaries, data handling and the definition of done. These apply equally to human and coding-agent contributions.

```bash
python -m unittest discover -s tests -v
node --check src/gdcalc/web/app.js
python -m pip install build
python -m build
python scripts/check_package.py
git diff --check
```

Use focused tests while iterating, then run the full suite for changes spanning parsing, calculation, packaging or HTTP behavior. Real-engine tests need the installed calculator; HTTP tests bind loopback. Keep fixtures synthetic. Add behavior-oriented cases for changed unit rules, source selection, unsupported syntax, result validity or publication failure. Do not test only that code reproduces itself.

For container changes:

```bash
docker build -t gdcalc:test .
docker run --rm -v "$PWD:/verify:ro" --entrypoint python \
  gdcalc:test -m unittest discover -s /verify/tests -v
```

The Actions workflow also starts the container, checks health, checks bundled fonts and confirms that unauthenticated API access is rejected.

For UI changes, use the real browser flow: upload → inputs → changes → generated outputs, then inspect the original file and fresh calculation view. Check the affected errors, keyboard focus and narrow layout. A rendered screenshot or syntax check alone does not establish a working conversion.

## Change expectations

- Keep domain calculations and file semantics outside HTTP/UI glue. Reuse the common engine.
- Fail visibly on unsupported expressions or incompatible units. Preserve original source and governing-case provenance.
- Keep old caches distinct from calculated results. Never change native verification flags without actual Prime evidence.
- Update CLI help/docs for new flags; update `SKILL.md` when agent workflow changes.
- Add packaged assets to both package metadata and Docker's context allowlist. Include licenses for bundled dependencies/assets.
- Update dependency locks intentionally. Pin the calculator revision and review its behavior when upgrading. Do not silently fetch newer engines during conversion.
- Exclude reports, templates, source snapshots, credentials and generated engineering outputs from commits and build contexts. Review staged filenames before publishing.

## Pull requests and releases

Describe the problem, resulting behavior, validation and remaining limitations. Separate current features from roadmap work. Include any template or expression compatibility changes so reviewers can assess existing documents.

Every pull request runs checks. Pushes to `main` and manual `main` runs publish Python build artifacts and, after all image tests succeed, a GHCR container. Image tags are `latest` and `sha-<full-commit-sha>`; use the latter for repeatable deployment. Actions uses `GITHUB_TOKEN`, not a repository-stored personal token. Dependabot maintains action update proposals.

When intentionally releasing a new application version, keep `pyproject.toml` and the version in `src/gdcalc/cli.py` aligned. Check the workflow for the exact commit before claiming the package/image is published. Deployment to a live server is a separate operation; follow [deployment guidance](deploy/README.md).

Versioned Python releases use the separate [PyPI release workflow](docs/releasing.md), which tests the installed wheel before Trusted Publishing. Ordinary main CI artifacts are not a PyPI upload.
