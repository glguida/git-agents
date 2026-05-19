from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def test_wheel_contains_manpage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(REPO_ROOT),
                    "--no-build-isolation",
                    "-w",
                    str(dist),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            wheels = sorted(dist.glob("git_agents-*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as wheel:
                names = set(wheel.namelist())
            self.assertIn(
                "git_agents-0.1.0.data/data/share/man/man1/git-agents.1",
                names,
            )
            self.assertIn("git_agents/runtime/bin/job-kill", names)
            self.assertIn("git_agents/runtime/bin/job-reset", names)


if __name__ == "__main__":
    unittest.main()
