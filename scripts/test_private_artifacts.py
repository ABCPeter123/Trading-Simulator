"""Tests for the public-repository strategy and credential privacy guard."""
from __future__ import annotations

import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_private_artifacts as privacy
from scripts import install_privacy_hook


class PrivacyCheckTests(unittest.TestCase):
    def test_real_owner_files_are_blocked_by_path(self):
        blocked = (
            "data/strategy_library.sqlite3",
            "data/arcade.sqlite3",
            ".local-state/public-demo/trading.sqlite3",
            "private/my-live-portfolio.json",
            "research/private/performance.json",
            "exports/trade_ledger.csv",
            "backups/strategies.db",
            "models/checkpoints/alpha.pt",
            "experiments/strategy-2026-11-17.json",
            "assets/portfolio-positions.yaml",
            "experiment/prediction-results.parquet",
            "src/personal_strategy.py",
            "src/generated_strategy.ts",
            "notebooks/strategy_research.ipynb",
            "secrets/.env",
            "deploy/.env.production",
            "config/broker-private-key.pem",
        )
        for path in blocked:
            with self.subTest(path=path):
                self.assertIsNotNone(privacy.path_violation(path))

    def test_generic_public_engine_files_remain_allowed(self):
        allowed = (
            "AGENTS.md",
            "docs/PRODUCT_VISION.md",
            "backend/strategy.py",
            "backend/strategy_library.py",
            "backend/tests/test_strategy.py",
            "backend/tests/test_strategy_library.py",
            "src/StrategyLibrary.tsx",
            "src/VisualStrategyBuilder.tsx",
            "src/data/demoMarket.ts",
            ".env.example",
            "package.json",
            "tsconfig.json",
            ".github/workflows/ci.yml",
        )
        for path in allowed:
            with self.subTest(path=path):
                self.assertIsNone(privacy.path_violation(path))

    def test_embedded_credentials_and_serialized_strategy_are_blocked(self):
        # Assemble dummy strings instead of embedding any key-shaped value
        # in the public test source itself.
        tokens = (
            b"sk-" + b"X" * 32,
            b"ghp_" + b"X" * 35,
            b"https://discord.com/api/" + b"webhooks/123456789/" + b"X" * 24,
            b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
        )
        for token in tokens:
            self.assertIsNotNone(privacy.content_violation("misc/config.txt", token))
        strategy = b'{"strategy":"WHEN PRICE ABOVE SMA(20) BUY 30%"}'
        self.assertIsNotNone(privacy.content_violation("sample.json", strategy))
        self.assertIsNone(privacy.content_violation("sample.json", b'{"version":"1.0"}'))
        self.assertIsNone(privacy.content_violation("README.md", b"Generic engine documentation."))

    def test_force_added_gitignored_strategy_is_detected_from_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text("data/\n")
            subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
            (root / "data").mkdir()
            (root / "data" / "private-strategy.json").write_text(
                '{"owner_strategy":"private dummy"}'
            )
            subprocess.run(
                ["git", "add", "-f", "data/private-strategy.json"],
                cwd=root, check=True,
            )
            with patch.object(privacy, "ROOT", root):
                indexed = dict(privacy.candidates(staged=True))
                self.assertIn("data/private-strategy.json", indexed)
                self.assertEqual(privacy.run(staged=True), 1)

    def test_installed_local_hook_blocks_forced_strategy_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(["git","init","-q"],cwd=root,check=True)
            (root / "scripts").mkdir()
            shutil.copy2(privacy.__file__,root / "scripts/check_private_artifacts.py")
            self.assertEqual(install_privacy_hook.install(root),0)
            (root / "data").mkdir()
            (root / ".gitignore").write_text("data/\n")
            (root / "data/real-strategy.json").write_text(
                '{"example":"stand-in private artifact"}'
            )
            subprocess.run(["git","add",".gitignore"],cwd=root,check=True)
            subprocess.run(["git","add","-f","data/real-strategy.json"],cwd=root,check=True)
            result=subprocess.run([
                "git","-c","user.name=PrivacyTest",
                "-c","user.email=test@example.invalid",
                "commit","-m","Should be blocked"
            ],cwd=root,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("PRIVATE TRADING DATA CHECK FAILED",result.stderr)

    def test_index_scan_uses_staged_version_not_unstaged_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            source = root / "engine.py"
            source.write_text("print('safe')\n")
            subprocess.run(["git", "add", "engine.py"], cwd=root, check=True)
            source.write_text("print('private local uncommitted changes')\n")
            with patch.object(privacy, "ROOT", root):
                indexed = dict(privacy.candidates(staged=True))
                self.assertEqual(indexed["engine.py"], b"print('safe')\n")
                self.assertEqual(privacy.run(staged=True), 0)


if __name__ == "__main__":
    unittest.main()
