"""Tests for the read-only football-quant-fusion skill mirror verifier."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from verify_fusion_skill_mirror import compare_trees  # noqa: E402


class CompareTreesTests(unittest.TestCase):
    def _write(self, root: Path, relative_path: str, content: str) -> None:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))

    def test_compare_trees_reports_matching_allowed_files_with_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            primary = temporary_path / "primary"
            mirror = temporary_path / "mirror"
            for root in (primary, mirror):
                self._write(root, "SKILL.md", "skill contents\n")
                self._write(root, "scripts/check.py", "print('ok')\n")
                self._write(root, "scripts/nested/ignored.py", "print('ignored')\n")
                self._write(root, "scripts/cache.pyc", "compiled cache\n")
                self._write(root, "config/settings.json", '{"enabled": true}\n')
                self._write(root, "ignored.txt", "ignored\n")

            result = compare_trees(primary, mirror)

            expected_hashes = {
                "SKILL.md": hashlib.sha256(b"skill contents\n").hexdigest(),
                "config/settings.json": hashlib.sha256(b'{"enabled": true}\n').hexdigest(),
                "scripts/check.py": hashlib.sha256(b"print('ok')\n").hexdigest(),
            }
            self.assertEqual("same", result["status"])
            self.assertEqual(str(primary), result["primary_path"])
            self.assertEqual(str(mirror), result["mirror_path"])
            self.assertEqual(expected_hashes, result["same_files"])
            self.assertEqual({}, result["different_files"])
            self.assertEqual([], result["only_primary"])
            self.assertEqual([], result["only_mirror"])
            self.assertIsNotNone(datetime.fromisoformat(result["checked_at"].replace("Z", "+00:00")))

    def test_compare_trees_reports_content_and_path_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            primary = temporary_path / "primary"
            mirror = temporary_path / "mirror"
            self._write(primary, "SKILL.md", "primary skill\n")
            self._write(mirror, "SKILL.md", "mirror skill\n")
            self._write(primary, "scripts/primary_only.py", "pass\n")
            self._write(mirror, "config/mirror_only.json", "{}\n")

            result = compare_trees(primary, mirror)

            self.assertEqual("different", result["status"])
            self.assertEqual(
                {
                    "SKILL.md": {
                        "primary_sha256": hashlib.sha256(b"primary skill\n").hexdigest(),
                        "mirror_sha256": hashlib.sha256(b"mirror skill\n").hexdigest(),
                    }
                },
                result["different_files"],
            )
            self.assertEqual(["scripts/primary_only.py"], result["only_primary"])
            self.assertEqual(["config/mirror_only.json"], result["only_mirror"])

    def test_cli_returns_nonzero_and_json_for_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            primary = temporary_path / "primary"
            mirror = temporary_path / "mirror"
            self._write(primary, "SKILL.md", "one\n")
            self._write(mirror, "SKILL.md", "two\n")

            completed = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "verify_fusion_skill_mirror.py"), str(primary), str(mirror)],
                capture_output=True,
                check=False,
                text=True,
            )

            self.assertEqual(1, completed.returncode)
            self.assertEqual("different", json.loads(completed.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
