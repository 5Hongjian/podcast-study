import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / "skills/podcast-study"
        self.state = self.root / "personal"

    def run_install(self, destination=None):
        return installer.install(installer.SOURCE, destination or self.destination, self.state)

    def seed_existing_state(self):
        # Legacy files are inert user-owned history, not active configuration.
        for name in ("preferences.md", "document-format.md", "runs/synthetic.json",
                     "sources/synthetic/transcript.txt", "other-state.txt"):
            path = self.state / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("user-owned synthetic content", encoding="utf-8")
        return {p.relative_to(self.state): p.read_bytes()
                for p in self.state.rglob("*") if p.is_file()}

    def assert_existing_state_unchanged(self, before):
        for relative, content in before.items():
            self.assertEqual(content, (self.state / relative).read_bytes())

    def test_fresh_install_creates_no_preferences_or_episode_records(self):
        self.run_install()
        self.assertTrue((self.destination / "SKILL.md").is_file())
        self.assertTrue(self.state.is_dir())
        self.assertFalse((self.state / "preferences.md").exists())
        self.assertFalse((self.state / "document-format.md").exists())
        self.assertFalse((self.state / "runs").exists())
        self.assertFalse((self.state / "sources").exists())

    def test_transcript_checker_installs_without_runtime_caches(self):
        source = self.root / "source"
        shutil.copytree(installer.SOURCE, source,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        cache = source / "scripts/__pycache__"
        cache.mkdir()
        (cache / "check_transcript.synthetic.pyc").write_bytes(b"synthetic cache")
        installer.install(source, self.destination, self.state)
        self.assertTrue((self.destination / "scripts/check_transcript.py").is_file())
        self.assertFalse((self.destination / "scripts/__pycache__").exists())
        installed_cache = self.destination / "scripts/__pycache__"
        installed_cache.mkdir()
        (installed_cache / "check_transcript.synthetic.pyc").write_bytes(b"changed cache")
        self.assertFalse(installer.install(source, self.destination, self.state)["changed"])

    def test_repeat_install_is_noop_and_preserves_user_files(self):
        self.run_install()
        before = self.seed_existing_state()
        result = self.run_install()
        after = {p.relative_to(self.state): p.read_bytes() for p in self.state.rglob("*") if p.is_file()}
        self.assertFalse(result["changed"])
        self.assertEqual(before, after)

    def test_update_preserves_previous_skill_in_backup(self):
        self.run_install()
        state_before = self.seed_existing_state()
        old = self.destination / "SKILL.md"
        old.write_text(old.read_text() + "\nLocal skill amendment\n")
        previous = old.read_bytes()
        result = self.run_install()
        self.assertEqual(previous, (Path(result["backup"]) / "SKILL.md").read_bytes())
        self.assertEqual(installer.fingerprint(installer.SOURCE), installer.fingerprint(self.destination))
        self.assert_existing_state_unchanged(state_before)

    def test_existing_discovery_symlink_is_preserved(self):
        self.run_install()
        link = self.root / "discovered"
        link.symlink_to(self.destination, target_is_directory=True)
        self.run_install(link)
        self.assertTrue(link.is_symlink())

    def test_refuses_personal_state_inside_repository(self):
        with self.assertRaises(ValueError):
            installer.install(installer.SOURCE, self.destination, ROOT / "local")
        self.assertFalse(self.destination.exists())

    def test_failed_replacement_restores_previous_installation(self):
        self.run_install()
        state_before = self.seed_existing_state()
        old = self.destination / "SKILL.md"
        old.write_text(old.read_text() + "\nPrevious version\n")
        previous = old.read_bytes()
        with patch.object(installer.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.run_install()
        self.assertEqual(previous, old.read_bytes())
        self.assert_existing_state_unchanged(state_before)

    def test_refuses_overlapping_skill_and_state(self):
        with self.assertRaises(ValueError):
            installer.install(installer.SOURCE, self.destination, self.destination / "state")


if __name__ == "__main__":
    unittest.main()
