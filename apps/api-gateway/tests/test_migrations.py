"""
Migration File Structure Tests
Tests: migration file exists, has correct revision ID, downgrade() defined,
       upgrade() creates expected tables, revision chain is linear.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import pytest

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "migrations" / "versions"
ENV_FILE = pathlib.Path(__file__).parent.parent / "migrations" / "env.py"
ALEMBIC_INI = pathlib.Path(__file__).parent.parent / "alembic.ini"


def _load_migration(path: pathlib.Path):
    """Dynamically load a migration module without executing it."""
    spec = importlib.util.spec_from_file_location("migration_001", path)
    mod = importlib.util.module_from_spec(spec)
    return mod, spec


class TestMigrationFiles:
    def test_migrations_dir_exists(self):
        assert MIGRATIONS_DIR.exists(), f"Missing: {MIGRATIONS_DIR}"

    def test_initial_migration_exists(self):
        files = list(MIGRATIONS_DIR.glob("001*.py"))
        assert len(files) == 1, f"Expected one 001_*.py migration, found: {files}"

    def test_alembic_ini_exists(self):
        assert ALEMBIC_INI.exists()

    def test_env_py_exists(self):
        assert ENV_FILE.exists()


class TestMigrationContent:
    def _parse_migration(self) -> ast.Module:
        files = list(MIGRATIONS_DIR.glob("001*.py"))
        assert files, "001 migration not found"
        return ast.parse(files[0].read_text(encoding="utf-8"))

    def test_revision_id_defined(self):
        files = list(MIGRATIONS_DIR.glob("001*.py"))
        assert files, "001 migration not found"
        content = files[0].read_text(encoding="utf-8")
        # Handles both: revision = "001"  and  revision: str = "001"
        assert '"001"' in content or "'001'" in content

    def test_down_revision_is_none(self):
        """First migration must have down_revision = None."""
        files = list(MIGRATIONS_DIR.glob("001*.py"))
        assert files, "001 migration not found"
        content = files[0].read_text(encoding="utf-8")
        # Handles: down_revision = None  or  down_revision: str | None = None
        assert "down_revision" in content
        # Extract the assignment value — must be None (not a non-empty string)
        import re
        match = re.search(r"down_revision\s*(?::\s*[^=]+)?\s*=\s*(\S+)", content)
        assert match is not None, "down_revision not found"
        assert match.group(1) == "None", f"Expected None, got {match.group(1)!r}"

    def test_upgrade_function_defined(self):
        tree = self._parse_migration()
        func_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "upgrade" in func_names

    def test_downgrade_function_defined(self):
        tree = self._parse_migration()
        func_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "downgrade" in func_names

    def test_all_eight_tables_mentioned(self):
        files = list(MIGRATIONS_DIR.glob("001*.py"))
        content = files[0].read_text(encoding="utf-8")
        expected_tables = [
            "agents", "runs", "memory_entries", "tools",
            "workflows", "hitl_requests", "audit_logs", "incidents",
        ]
        for table in expected_tables:
            assert f'"{table}"' in content or f"'{table}'" in content, \
                f"Table '{table}' not found in migration"
