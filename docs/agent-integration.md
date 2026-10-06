# Agent-neutral integration

mcdxkit is standalone software with CLI, Python API and browser server interfaces. The skill is a thin workflow layer. It does not contain a separate engine or depend on a model provider.

The repository root is the skill directory: `SKILL.md` has `name` and `description` frontmatter, links to resources relative to the root, and uses ordinary shell commands. This matches the [Agent Skills specification](https://agentskills.io/specification). Install the complete repository, not only `SKILL.md`, because helper scripts import `src/mcdxkit` and instructions reference local docs.

## Clients with skill discovery

Place the repository in a directory named `mcdxkit` under a skill directory supported by the client. A commonly supported personal location is `~/.agents/skills/mcdxkit`; project discovery may use `.agents/skills`, `.github/skills` or `.claude/skills`, depending on the host. GitHub documents these locations for [Copilot](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills). Check your specific client's discovery rules rather than assuming every path works everywhere.

Install the CLI with `uv tool install /path/to/mcdxkit`, then run `mcdxkit setup-engine` once. Skill discovery alone does not install Python dependencies or the calculator. Use the client's normal skill selection; `$mcdxkit` is not a universal invocation syntax.

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
