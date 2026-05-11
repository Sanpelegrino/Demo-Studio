"""Tests for install script portability and app startup resilience.

Validates that install.sh uses only Bash 3.2-compatible syntax (macOS default)
and that the app starts gracefully in degraded environments (no XLS, no data).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"


# ─── Bash 3.2 Compatibility Tests ──────────────────────────────────────────

class TestBash32Compat:
    """Ensure install.sh avoids Bash 4+ syntax that breaks on macOS."""

    def _read_script(self) -> str:
        return INSTALL_SH.read_text(encoding="utf-8")

    def test_no_lowercase_expansion(self):
        """${var,,} requires Bash 4+"""
        content = self._read_script()
        matches = re.findall(r'\$\{[^}]+,,\}', content)
        assert matches == [], f"Bash 4+ lowercase syntax found: {matches}"

    def test_no_uppercase_expansion(self):
        """${var^^} requires Bash 4+"""
        content = self._read_script()
        matches = re.findall(r'\$\{[^}]+\^\^\}', content)
        assert matches == [], f"Bash 4+ uppercase syntax found: {matches}"

    def test_no_associative_arrays(self):
        """declare -A requires Bash 4+"""
        content = self._read_script()
        matches = re.findall(r'declare\s+-A\b', content)
        assert matches == [], f"Bash 4+ associative arrays found: {matches}"

    def test_no_mapfile_readarray(self):
        """mapfile/readarray require Bash 4+"""
        content = self._read_script()
        matches = re.findall(r'\b(mapfile|readarray)\b', content)
        assert matches == [], f"Bash 4+ mapfile/readarray found: {matches}"

    def test_no_coproc(self):
        """coproc requires Bash 4+"""
        content = self._read_script()
        matches = re.findall(r'\bcoproc\b', content)
        assert matches == [], f"Bash 4+ coproc found: {matches}"

    def test_no_ampersand_redirect(self):
        """|& requires Bash 4+; use 2>&1 | instead"""
        content = self._read_script()
        # Match |& but not &> (which is fine in bash 3.2 with some caveats)
        matches = re.findall(r'\|\&', content)
        assert matches == [], f"Bash 4+ |& pipe found: {matches}"

    def test_no_negative_array_index(self):
        """${array[-1]} requires Bash 4.2+"""
        content = self._read_script()
        matches = re.findall(r'\$\{[^}]+\[-\d+\]\}', content)
        assert matches == [], f"Bash 4.2+ negative array index found: {matches}"

    def test_no_nameref(self):
        """declare -n requires Bash 4.3+"""
        content = self._read_script()
        matches = re.findall(r'declare\s+-n\b', content)
        assert matches == [], f"Bash 4.3+ nameref found: {matches}"

    def test_shebang_is_env_bash(self):
        """Script should use #!/usr/bin/env bash for portability"""
        first_line = self._read_script().split("\n")[0]
        assert first_line.strip() == "#!/usr/bin/env bash"

    def test_no_regex_match_with_quotes(self):
        """[[ $x =~ "pattern" ]] broke in Bash 3.2; pattern must be unquoted"""
        content = self._read_script()
        matches = re.findall(r'=~\s+["\']', content)
        assert matches == [], f"Quoted regex in [[ =~ ]] found: {matches}"


# ─── Install Script Structural Tests ───────────────────────────────────────

class TestInstallStructure:
    """Validate install.sh handles edge cases."""

    def _read_script(self) -> str:
        return INSTALL_SH.read_text(encoding="utf-8")

    def test_env_example_exists(self):
        """install.sh copies .env.example — it must exist in the repo"""
        assert (ROOT / ".env.example").exists()

    def test_env_example_has_placeholder(self):
        """install.sh seds 'your-bedrock-bearer-token' — it must be present"""
        content = (ROOT / ".env.example").read_text()
        assert "your-bedrock-bearer-token" in content

    def test_data_dir_has_superstore(self):
        """Bundled Superstore XLS must be present for zero-config installs"""
        xls = ROOT / "data" / "Sample - Superstore.xls"
        assert xls.exists(), "data/Sample - Superstore.xls missing from repo"
        assert xls.stat().st_size > 1_000_000, "XLS looks too small / corrupted"

    def test_requirements_no_exact_pins(self):
        """All deps should use >= not == for Python version flexibility"""
        content = (ROOT / "requirements.txt").read_text()
        exact_pins = re.findall(r'^[a-zA-Z].*==', content, re.MULTILINE)
        assert exact_pins == [], f"Exact version pins found (use >=): {exact_pins}"

    def test_script_uses_seq_or_brace(self):
        """for i in $(seq ...) is fine on macOS; {1..15} also works in bash 3"""
        content = self._read_script()
        assert "seq" in content or "{1.." in content, "Loop wait logic missing"


# ─── App Startup Resilience Tests ──────────────────────────────────────────

class TestAppStartupResilience:
    """Verify the app handles missing resources without crashing at import."""

    def test_seed_superstore_path_resolution(self):
        """XLS_PATH should resolve to bundled file when it exists"""
        from seed_superstore import _BUNDLED_XLS, _resolve_xls_path

        # Clear env override if set
        env_backup = os.environ.pop("SUPERSTORE_XLS_PATH", None)
        try:
            path = _resolve_xls_path()
            assert path == _BUNDLED_XLS or path.exists()
        finally:
            if env_backup:
                os.environ["SUPERSTORE_XLS_PATH"] = env_backup

    def test_seed_superstore_env_override(self):
        """SUPERSTORE_XLS_PATH env var should take priority"""
        from seed_superstore import _resolve_xls_path

        fake_path = str(ROOT / "data" / "fake.xls")
        os.environ["SUPERSTORE_XLS_PATH"] = fake_path
        try:
            path = _resolve_xls_path()
            assert str(path) == fake_path
        finally:
            del os.environ["SUPERSTORE_XLS_PATH"]

    def test_app_imports_without_db(self):
        """app.py module-level code should not crash if DB is unreachable.

        This test validates that import-time failures are handled, but
        since _ensure_seeded() runs at module scope and requires a DB,
        we just verify the seeding modules themselves import cleanly.
        """
        from seed_superstore import seed_superstore, XLS_PATH, _resolve_xls_path
        assert callable(seed_superstore)
        assert callable(_resolve_xls_path)


# ─── Shellcheck (optional, if installed) ───────────────────────────────────

class TestShellcheck:
    """Run shellcheck if available — non-fatal if not installed."""

    @pytest.fixture(autouse=True)
    def _check_shellcheck(self):
        try:
            result = subprocess.run(
                ["shellcheck", "--version"],
                capture_output=True,
            )
        except FileNotFoundError:
            pytest.skip("shellcheck not installed")
        if result.returncode != 0:
            pytest.skip("shellcheck not installed")

    def test_shellcheck_passes(self):
        """shellcheck should report no errors (warnings OK)"""
        result = subprocess.run(
            ["shellcheck", "-s", "bash", "-S", "error", str(INSTALL_SH)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"shellcheck errors:\n{result.stdout}"
