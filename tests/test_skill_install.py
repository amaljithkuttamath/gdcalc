"""Exercise the skill installer against a synthetic committed repository."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "skill_install", Path(__file__).parents[1] / "scripts" / "install_skill.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@unittest.skipUnless(shutil.which("git"), "Skill snapshot installation requires Git (not a server runtime dependency)")
class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "repo"
        self.source.mkdir()
        self.git("init", "-q")
        (self.source / "SKILL.md").write_text("---\nname: mcdxkit\n---\nOriginal skill\n")
        (self.source / ".gitignore").write_text("*.mcdx\n.mcdxkit/\n")
        (self.source / "pyproject.toml").write_text('[project]\nname = "mcdxkit"\n')
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "Synthetic skill")
        (self.source / "private.mcdx").write_bytes(b"private template")
        (self.source / "notes.txt").write_text("untracked client notes")
        (self.source / "SKILL.md").write_text("uncommitted changes")
        self.destination = self.root / "skills" / "mcdxkit"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], text=True).strip()

    def run_install(self, *args, stdin=None):
        with patch.object(installer, "SOURCE_ROOT", self.source), \
             patch("sys.stdin", stdin or io.StringIO()), patch("sys.stdout", new_callable=io.StringIO):
            return installer.main(["--destination", str(self.destination), *args])

    def profile(self):
        return json.loads((self.destination / ".mcdxkit/profile.json").read_text())

    def test_unattended_install_copies_only_committed_files_and_skips_interview(self):
        self.assertEqual(self.run_install(), 0)
        self.assertIn("Original skill", (self.destination / "SKILL.md").read_text())
        self.assertFalse((self.destination / "private.mcdx").exists())
        self.assertFalse((self.destination / "notes.txt").exists())
        self.assertFalse((self.destination / ".git").exists())
        profile = self.profile()
        self.assertEqual(profile["source_commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(profile["interview"], "skipped")
        self.assertTrue(all(value is None for value in profile["answers"].values()))
        self.assertEqual(profile["validation_evidence"], [])

    def test_interview_records_choices_but_never_grants_approval(self):
        responses = io.StringIO("1\n1\n1\n1\n1\n1\n1\n")
        self.assertEqual(self.run_install("--interview", stdin=responses), 0)
        profile = self.profile()
        self.assertEqual(profile["interview"], "completed")
        self.assertEqual(profile["answers"]["template_status"], "reviewed")
        self.assertEqual(profile["answers"]["standards_basis"], "reviewed_register")
        self.assertEqual(profile["validation_evidence"], [])
        self.assertEqual(profile["answers"]["operation"], "offline")
        if installer.os.name != "nt":
            self.assertEqual((self.destination / ".mcdxkit/profile.json").stat().st_mode & 0o777, 0o600)

    def test_interview_reprompts_invalid_choice_and_eof_leaves_unknowns(self):
        self.run_install("--interview", stdin=io.StringIO("bad\n999\n2\n\n"))
        profile = self.profile()
        self.assertEqual(profile["interview"], "partial")
        self.assertEqual(profile["answers"]["workflow"], "development")
        self.assertIsNone(profile["answers"]["source_format"])
        self.assertIsNone(profile["answers"]["operation"])

    def test_terminal_offers_interview_and_can_decline(self):
        terminal = io.StringIO("n\n")
        terminal.isatty = lambda: True
        self.run_install(stdin=terminal)
        self.assertEqual(self.profile()["interview"], "skipped")

    def test_terminal_can_accept_interview(self):
        terminal = io.StringIO("y\n3\n" + "\n" * 6)
        terminal.isatty = lambda: True
        self.run_install(stdin=terminal)
        self.assertEqual(self.profile()["interview"], "completed")
        self.assertEqual(self.profile()["answers"]["workflow"], "both")

    def test_no_interview_never_consumes_terminal_input(self):
        terminal = io.StringIO("y\n")
        terminal.isatty = lambda: True
        self.run_install("--no-interview", stdin=terminal)
        self.assertEqual(terminal.tell(), 0)

    def test_failed_write_cleans_only_new_installation(self):
        sibling = self.root / "skills" / "other"
        sibling.mkdir(parents=True)
        (sibling / "keep.txt").write_text("Keep this")
        with patch.object(installer.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.run_install("--no-interview")
        self.assertFalse(self.destination.exists())
        self.assertEqual((sibling / "keep.txt").read_text(), "Keep this")

    def test_existing_destination_is_unchanged(self):
        self.destination.mkdir(parents=True)
        sentinel = self.destination / "keep.txt"
        sentinel.write_text("Keep this")
        with self.assertRaises(FileExistsError):
            self.run_install("--no-interview")
        self.assertEqual(sentinel.read_text(), "Keep this")
        self.assertEqual(list(self.destination.iterdir()), [sentinel])

    def test_committed_symlink_is_rejected_without_partial_install(self):
        (self.source / "linked.txt").symlink_to(self.root / "secret.txt")
        self.git("add", "linked.txt")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "Symlink fixture")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.run_install("--no-interview")
        self.assertFalse(self.destination.exists())

    def test_destination_inside_source_is_rejected(self):
        self.destination = self.source / "installed"
        with self.assertRaisesRegex(ValueError, "outside"):
            self.run_install("--no-interview")


if __name__ == "__main__":
    unittest.main()
