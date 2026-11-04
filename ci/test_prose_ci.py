import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_ci import changed_paths, main, prose_only


class ProseScopeTests(unittest.TestCase):
    def test_reviewed_prose_is_lightweight(self):
        self.assertTrue(prose_only(["AGENTS.md", "README.md", "docs/adr/0001-runtime.md"]))

    def test_mixed_unknown_release_and_proof_inputs_need_full_ci(self):
        for path in (
            "src/lib.rs",
            "Cargo.lock",
            ".github/workflows/ci.yml",
            "ci/prose_ci.py",
            "CHANGELOG.md",
            "formal/README.md",
            "docs/MATHEMATICAL_VALIDATION.md",
            "docs/fixture.json",
            "examples/example.ipynb",
            "new-unclassified-input",
            "README.md\nsrc/lib.rs",
            "docs/adr/note.md\n",
        ):
            with self.subTest(path=path):
                self.assertFalse(prose_only(["AGENTS.md", path]))
        self.assertFalse(prose_only([]))

    def test_git_rename_out_of_source_retains_both_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            try:
                os.chdir(directory)

                def git(*args):
                    return (
                        subprocess.check_output(
                            ["git", "-c", "commit.gpgsign=false", *args], stderr=subprocess.DEVNULL
                        )
                        .decode()
                        .strip()
                    )

                git("init")
                git("config", "user.name", "CI fixture")
                git("config", "user.email", "ci-fixture@example.invalid")
                Path("source.py").write_text("print('fixture')\n")
                git("add", ".")
                git("commit", "-m", "fixture: source")
                base = git("rev-parse", "HEAD")
                git("mv", "source.py", "README.md")
                git("commit", "-m", "fixture: renamed source")
                paths = changed_paths(base, "HEAD")
                self.assertEqual(set(paths), {"source.py", "README.md"})
                self.assertFalse(prose_only(paths))
                with self.assertRaises(subprocess.CalledProcessError):
                    changed_paths("missing-revision", "HEAD")
            finally:
                os.chdir(old)

    def test_missing_comparison_cannot_report_prose_success(self):
        with patch.dict(
            os.environ,
            {
                "CI_PROSE_BASE": "",
                "CI_PROSE_HEAD": "HEAD",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_REF": "refs/pull/1/merge",
            },
        ):
            with self.assertRaises(SystemExit):
                main()

    def test_tags_and_operational_events_keep_full_ci(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            for event, ref in (("push", "refs/tags/v1.0.0"), ("schedule", "refs/heads/main")):
                with self.subTest(event=event, ref=ref):
                    output.write_text("")
                    with patch.dict(
                        os.environ,
                        {
                            "GITHUB_EVENT_NAME": event,
                            "GITHUB_REF": ref,
                            "GITHUB_OUTPUT": str(output),
                        },
                    ):
                        main()
                    self.assertEqual(output.read_text(), "prose_only=false\n")


if __name__ == "__main__":
    unittest.main()
