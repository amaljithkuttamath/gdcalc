# Python package releases

The Python distribution includes the engine SDK, CLI, web server/assets and calculator bridge source. The calculator runtime is installed separately. GitHub's ordinary CI uploads build artifacts and publishes a tested container; a published versioned GitHub Release triggers `.github/workflows/release.yml` for PyPI.

## One-time account setup

An owner must register a [PyPI pending Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) (or an active publisher if the project already exists):

| Field | Value |
| --- | --- |
| PyPI project | `mcdxkit` |
| GitHub owner | `amaljithkuttamath` |
| Repository | `mcdxkit` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Configure the GitHub `pypi` environment to accept release tags matching `v*`. The release job also checks that the commit belongs to `main` and the tag matches the package version. Registering a publisher is an account-side action; committing YAML alone does not authorize PyPI uploads. GitHub authentication and an earlier project's publisher do not automatically grant access to this new package. No long-lived PyPI token is required.

## Release procedure

For the 0.3.0 identity change, register the `mcdxkit` publisher against the renamed repository before publishing. Account-side publisher settings do not follow a GitHub repository rename automatically. This is a clean namespace change: commands, imports, environment variables, configuration directories, browser sessions and calculator installation use `mcdxkit` / `MCDXKIT_*`. Install the calculator again under the new name and configure private template paths explicitly. No aliases, automatic data migration or old-installation cleanup are performed.

1. Update the version in `pyproject.toml` and `src/mcdxkit/cli.py` through an issue/PR. Update versioned install examples. Review compatibility and release notes.
2. Merge after required checks pass. Check CI on the exact main commit. Private reports, templates and secrets must remain excluded.
3. Create a GitHub Release with tag `v<version>` targeting that tested main commit. Preview notes as a draft if account configuration is incomplete; publish only when ready to upload.
4. The workflow builds wheel/sdist, validates metadata/assets, installs the wheel and executes real calculator/SDK/CLI/server tests. A separate job downloads these same artifacts and uses OIDC Trusted Publishing with attestations.
5. Verify the release-triggered repository audit and resolve any confirmed regression tickets. Verify the publishing workflow and `https://pypi.org/project/mcdxkit/<version>/`, then install that exact version into a clean environment. Verify the SDK import and CLI before announcing availability.

PyPI versions are immutable. Fix a failed publication's setup and rerun only if the version was not uploaded; inspect PyPI first after a partial upload. For a code fix after publication, issue a new version through the normal PR workflow. Never hide an upload failure with `skip-existing`.

Current distribution validation targets Linux and local macOS checks. A Windows desktop installer is a separate feature; a Python wheel is not a bundled native desktop app. PyPI does not provide a Mathcad runtime or a general standards-compliance database.
