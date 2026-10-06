"""Install a committed, agent-neutral skill snapshot with optional local onboarding."""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
from zipfile import ZipFile


SOURCE_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = (
    ("workflow", "What will you use MCDXKit for?", (
        ("conversion", "Convert and inspect engineering files"),
        ("development", "Contribute to the software"), ("both", "Both"))),
    ("source_format", "What raw files do you receive?", (
        ("group_text", "ENSOFT GROUP .gp11t / text reports"),
        ("excel", "Excel workbooks (no direct binary import yet)"),
        ("mixed", "Mixed or other formats; assess support first"))),
    ("template_status", "What is the status of your Mathcad template?", (
        ("reviewed", "Team-reviewed template; evidence must be checked per task"),
        ("draft", "Draft template awaiting review"), ("missing", "No template yet"))),
    ("units", "Which units do your source reports use?", (
        ("kip_kip_in", "kip and kip-in"),
        ("metric", "Metric; current GROUP adapter needs compatibility review"),
        ("mixed", "Mixed; verify each source before conversion"))),
    ("standards_basis", "Do you have a project-specific standards basis?", (
        ("reviewed_register", "Reviewed register with editions and clauses"),
        ("awaiting_review", "A draft or list awaiting engineering review"),
        ("missing", "Not established yet"))),
    ("engineering_reviewer", "Who will review engineering assumptions and results?", (
        ("assigned", "A qualified reviewer is assigned"),
        ("needed", "We still need to assign a reviewer"),
        ("software_only", "Software development only; no design approval in scope"))),
    ("operation", "Where should the workflow run?", (
        ("offline", "Offline after dependencies and calculator are provisioned"),
        ("local", "Local CLI or browser server"),
        ("hosted", "Hosted server; assess access, storage and deployment separately"))),
)


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def interview(enabled):
    answers = {key: None for key, _, _ in QUESTIONS}
    if not enabled:
        return "skipped", answers
    print("Optional workflow interview. Enter skips a question; Ctrl+D ends it.\n"
          "Use choices only: no client data, credentials or private file paths.\n"
          "Answers are local preferences, never calculation or engineering approval.")
    for key, question, choices in QUESTIONS:
        print("\n" + question)
        for index, (_, label) in enumerate(choices, start=1):
            print(f"  {index}. {label}")
        while True:
            answer = ask("Choice [Enter = unknown]: ")
            if answer is None:
                return "partial", answers
            if not answer:
                break
            if answer.isascii() and answer.isdigit() and 1 <= int(answer) <= len(choices):
                answers[key] = choices[int(answer) - 1][0]
                break
            print("Choose a listed number, or press Enter to skip.")
    return "completed", answers


def committed_snapshot(source):
    """Use Git's committed tree, excluding ignored/untracked/local modifications."""
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args])

    commit = git("rev-parse", "HEAD").decode().strip()
    archive = git("archive", "--format=zip", commit)
    with ZipFile(io.BytesIO(archive)) as bundle:
        names = set(bundle.namelist())
        if not {"SKILL.md", "pyproject.toml"}.issubset(names):
            raise ValueError("The committed checkout must contain SKILL.md and pyproject.toml")
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
                raise ValueError("Unsafe path in skill snapshot")
            if path.parts and path.parts[0] in {".git", ".mcdxkit"}:
                raise ValueError("Local configuration must not be committed into the skill")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("A skill snapshot must not contain a symlink")
    return commit, archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Requires a Git checkout. Installs committed HEAD only, without Git history. "
        "Does not install dependencies, build the calculator or contact the network."))
    parser.add_argument("--destination", required=True, type=Path,
                        help="New mcdxkit directory in your agent's supported skill location")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--interview", action="store_true", help="Ask optional setup questions")
    mode.add_argument("--no-interview", action="store_true", help="Skip setup questions")
    args = parser.parse_args(argv)
    # Check existence before resolving so a dangling symlink also cannot be replaced.
    destination = args.destination.expanduser().absolute()
    if os.path.lexists(destination):
        raise FileExistsError(f"Destination exists; choose a new directory: {destination}")
    destination = destination.resolve()
    source = SOURCE_ROOT.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Choose a destination outside the source checkout")
    commit, archive = committed_snapshot(source)
    enabled = args.interview
    if not enabled and not args.no_interview and sys.stdin.isatty():
        enabled = (ask("Offer the optional 7-question workflow interview? [y/N]: ") or "").lower() in {"y", "yes"}
    state, answers = interview(enabled)
    profile = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": commit,
        "interview": state,
        "answers": answers,
        "validation_evidence": [],
    }
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(destination)  # All archive entries checked above; no symlinks.
        local = destination / ".mcdxkit"
        local.mkdir(mode=0o700)
        with (local / "profile.json").open("x", encoding="utf-8") as stream:
            os.chmod(stream.name, 0o600)
            json.dump(profile, stream, indent=2)
            stream.write("\n")
    except BaseException:
        shutil.rmtree(destination)
        raise
    print(f"\nInstalled committed skill {commit[:12]} at {destination}")
    print(f"Interview: {state}. Local context: {local / 'profile.json'}")
    print("Read docs/agent-integration.md for CLI and calculator setup. "
          "Existing CLI installations and calculation settings were not changed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Skill installation failed: {exc}", file=sys.stderr)
        sys.exit(1)
