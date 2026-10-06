# Agent-neutral integration

mcdxkit is standalone software with CLI, Python API and browser server interfaces. The skill is a thin workflow layer. It does not contain a separate engine or depend on a model provider.

The repository root is the skill directory: `SKILL.md` has `name` and `description` frontmatter, links to resources relative to the root, and uses ordinary shell commands. This matches the [Agent Skills specification](https://agentskills.io/specification). Install the complete repository, not only `SKILL.md`, because helper scripts import `src/mcdxkit` and instructions reference local docs.

## Clients with skill discovery

Place the repository in a directory named `mcdxkit` under a skill directory supported by the client. A commonly supported personal location is `~/.agents/skills/mcdxkit`; project discovery may use `.agents/skills`, `.github/skills` or `.claude/skills`, depending on the host. GitHub documents these locations for [Copilot](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills). Check your specific client's discovery rules rather than assuming every path works everywhere.

Install the CLI with `uv tool install /path/to/mcdxkit`, then run `mcdxkit setup-engine` once. Skill discovery alone does not install Python dependencies or the calculator. Use the client's normal skill selection; `$mcdxkit` is not a universal invocation syntax.

### Install with optional workflow interview

From a Git checkout, copy the committed skill into a **new** directory supported by your agent:

```bash
python scripts/install_skill.py --destination /path/to/skills/mcdxkit
# Explicit interview, including when input is piped:
python scripts/install_skill.py --destination /another/path/mcdxkit --interview
# Unattended installation:
python scripts/install_skill.py --destination /new/path/mcdxkit --no-interview
```

An interactive terminal offers a seven-question interview; noninteractive installation skips it unless `--interview` is set. Each question can be skipped. Choices cover workflow, source formats, template status, units, standards, reviewer availability and operating mode. They cannot configure formulas, select load cases or establish approval. The [review guide](../references/reviews.md) explains how agents use the answers and validate subsequent work.

The installer requires Python 3.10+ and Git. It copies **committed HEAD**, without history, untracked files or uncommitted edits, and prints that commit. Commit intended skill changes first. It rejects existing destinations and symlinks in the snapshot; upgrades use a new directory so local context cannot be overwritten. Review the repository you install—committed files are still included. The snapshot retains docs/scripts/source for offline use, but initial CLI/dependency/calculator setup remains separate and may need network access.

Answers remain in the installed skill's `.mcdxkit/profile.json` (directory mode 0700 and file mode 0600 on POSIX; on Windows use the account's normal directory ACLs). `.mcdxkit/` is Git-ignored. The file contains no validation evidence, secrets or client paths, and is never uploaded by installation. It is not automatically sent to a model; an agent following the skill may read it, so follow your agent host's data policy. Inspect/edit or delete it locally to change/remove context. Missing or stale answers must not override the current request or source evidence.

Installation does not install the CLI, build the calculator or modify an existing environment. After choosing the installed directory, use the CLI setup above. For updates, repeat installation to a fresh destination and intentionally carry over only still-relevant local context; there is no automatic background update.

`agents/openai.yaml` supplies optional UI metadata for compatible OpenAI clients. It is not needed to run the skill, CLI, server, tests or contribution workflow. No host-specific tool names are required by the skill's execution path.

## Clients without skill discovery

Give the agent the checkout path and ask it to read `SKILL.md` before a conversion. For development, ask it to read `AGENTS.md` and the linked architecture/testing/standards documents. If the client supports a different repository-instructions file, it can point to `AGENTS.md` without duplicating its contents.

```text
Use the mcdxkit repository at /path/to/mcdxkit.
Read SKILL.md for conversion, or AGENTS.md for repository changes.
Use the existing CLI and shared engine. Preserve original inputs and report
the exact validation performed. Do not publish private engineering data.
```

An agent can run `mcdxkit ...`, `python -m mcdxkit ...` after installation, or `python /path/to/mcdxkit/scripts/cli.py ...` with dependencies available. Use absolute source/template/output paths when the agent's working directory is elsewhere.

For unattended scripts, inspect exit codes and JSON output. For browser inspection, start `mcdxkit serve --no-open --port 0`, keep the process/session alive and open its printed URL. The agent host controls its own shell, process and browser tools; mcdxkit does not assume particular tool names.

## Scope and verification

The current skill covers the supported GROUP-to-worksheet pipeline. It does not promise all Prime features. Cross-client behavior has not been tested in every named agent application; format compatibility and host-independent CLI operation are separate from client-specific discovery verification.

No skill text grants new permissions. Publication, external messaging and deployment follow the user's authorization and the host's controls. Keep the software's source-selection, file-preservation and calculation-verification invariants intact across agents.
