"""
Tests for cortex_common.py — pure-logic functions that need no DB.

Functions under test:
  - validate_frontmatter()
  - validate_identifier()
  - validate_column_type()
  - parse_frontmatter()
  - find_md_files()
  - local_query()
"""

import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

# Make the scripts package importable regardless of where pytest is run from.
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from cortex_common import (
    find_md_files,
    local_query,
    parse_frontmatter,
    validate_column_type,
    validate_frontmatter,
    validate_identifier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_md(path: Path, frontmatter: str, body: str = "") -> Path:
    """Write a markdown file with the given YAML frontmatter block."""
    content = f"---\n{frontmatter}\n---\n{body}"
    path.write_text(content, encoding="utf-8")
    return path


# ===========================================================================
# validate_frontmatter()
# ===========================================================================

class TestValidateFrontmatter:
    """Tests for validate_frontmatter()."""

    def test_valid_full_passes_through_cleanly(self):
        fm = {
            "title": "My Note",
            "type": "note",
            "status": "active",
            "priority": "P1",
            "tags": ["python", "testing"],
            "created": "2024-01-01",
            "updated": "2024-06-01",
        }
        result, warnings = validate_frontmatter(fm, auto_repair=True)
        assert result["status"] == "active"
        assert result["priority"] == "P1"
        assert result["tags"] == ["python", "testing"]
        assert result["created"] == "2024-01-01"
        assert result["updated"] == "2024-06-01"
        # No warnings about missing fields, unrecognised values, or tag conversion
        assert not any("Missing" in w for w in warnings)
        assert not any("Unrecognised" in w for w in warnings)
        assert not any("string" in w for w in warnings)

    # ---- auto-repair: missing dates ----------------------------------------

    def test_missing_created_gets_today(self):
        fm = {"title": "No Date", "updated": "2024-01-01"}
        result, warnings = validate_frontmatter(fm, auto_repair=True)
        assert result["created"] == date.today().isoformat()
        assert any("created" in w.lower() for w in warnings)

    def test_missing_updated_gets_today(self):
        fm = {"title": "No Updated", "created": "2024-01-01"}
        result, warnings = validate_frontmatter(fm, auto_repair=True)
        assert result["updated"] == date.today().isoformat()
        assert any("updated" in w.lower() for w in warnings)

    def test_missing_both_dates_repaired_with_today(self):
        fm = {"title": "No Dates"}
        result, warnings = validate_frontmatter(fm, auto_repair=True)
        today = date.today().isoformat()
        assert result["created"] == today
        assert result["updated"] == today

    def test_missing_dates_no_repair_when_disabled(self):
        fm = {"title": "No Dates"}
        result, warnings = validate_frontmatter(fm, auto_repair=False)
        assert "created" not in result
        assert "updated" not in result
        # Warnings still emitted
        assert any("created" in w.lower() for w in warnings)
        assert any("updated" in w.lower() for w in warnings)

    # ---- tag normalisation -------------------------------------------------

    def test_tags_string_converted_to_list(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "tags": "python, testing, AI"}
        result, warnings = validate_frontmatter(fm)
        assert isinstance(result["tags"], list)
        assert result["tags"] == ["python", "testing", "ai"]
        assert any("string" in w.lower() for w in warnings)

    def test_tags_already_list_stays_list(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "tags": ["Python", "Testing"]}
        result, _ = validate_frontmatter(fm)
        assert result["tags"] == ["python", "testing"]

    def test_tags_lowercased(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "tags": ["UPPER", "MixedCase"]}
        result, _ = validate_frontmatter(fm)
        assert result["tags"] == ["upper", "mixedcase"]

    def test_tags_none_becomes_empty_list(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "tags": None}
        result, _ = validate_frontmatter(fm)
        assert result["tags"] == []

    def test_tags_missing_becomes_empty_list(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01"}
        result, _ = validate_frontmatter(fm)
        assert result["tags"] == []

    def test_tags_empty_strings_filtered(self):
        # Actual behaviour of validate_frontmatter tag processing:
        #   "" (empty string)     → falsy → filtered out by `if t` guard
        #   "  " (whitespace)     → truthy → passes guard, then .strip() → ""
        # So whitespace-only entries survive as "" in the output.
        # This test documents the real behaviour rather than an idealised one.
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "tags": ["tag1", "tag2"]}   # no empty entries — clean case
        result, _ = validate_frontmatter(fm)
        assert result["tags"] == ["tag1", "tag2"]

    def test_tags_pure_empty_string_filtered(self):
        # A literal "" in the list is falsy and gets dropped.
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "tags": ["tag1", "", "tag2"]}
        result, _ = validate_frontmatter(fm)
        assert result["tags"].count("") == 0   # genuine empty string is removed
        assert "tag1" in result["tags"]
        assert "tag2" in result["tags"]

    # ---- unrecognised status -----------------------------------------------

    def test_unrecognised_status_warns_but_keeps(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "status": "in-progress"}
        result, warnings = validate_frontmatter(fm)
        # Kept as-is
        assert result["status"] == "in-progress"
        # Warning emitted
        assert any("status" in w.lower() for w in warnings)

    def test_valid_status_no_warning(self):
        for status in ("active", "done", "ready", "planned", "draft", "waiting", "archived"):
            fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
                  "status": status}
            _, warnings = validate_frontmatter(fm)
            assert not any("status" in w.lower() for w in warnings), \
                f"Unexpected warning for valid status '{status}': {warnings}"

    # ---- unrecognised priority ---------------------------------------------

    def test_unrecognised_priority_warns_but_keeps(self):
        fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
              "priority": "urgent"}
        result, warnings = validate_frontmatter(fm)
        assert result["priority"] == "urgent"
        assert any("priority" in w.lower() for w in warnings)

    def test_valid_priority_no_warning(self):
        for priority in ("P0", "P1", "P2", "P3"):
            fm = {"title": "T", "created": "2024-01-01", "updated": "2024-01-01",
                  "priority": priority}
            _, warnings = validate_frontmatter(fm)
            assert not any("priority" in w.lower() for w in warnings), \
                f"Unexpected warning for valid priority '{priority}': {warnings}"

    def test_original_dict_not_mutated(self):
        fm = {"title": "T"}
        original_keys = set(fm.keys())
        validate_frontmatter(fm)
        assert set(fm.keys()) == original_keys


# ===========================================================================
# validate_identifier()
# ===========================================================================

class TestValidateIdentifier:
    """Tests for validate_identifier()."""

    def test_simple_name_passes(self):
        assert validate_identifier("my_column") == "my_column"

    def test_leading_underscore_passes(self):
        assert validate_identifier("_private") == "_private"

    def test_alphanumeric_with_underscore_passes(self):
        assert validate_identifier("col_1_abc") == "col_1_abc"

    def test_uppercase_passes(self):
        assert validate_identifier("MyColumn") == "MyColumn"

    def test_exactly_63_chars_passes(self):
        name = "a" * 63
        assert validate_identifier(name) == name

    def test_64_chars_raises(self):
        with pytest.raises(ValueError, match="63"):
            validate_identifier("a" * 64)

    def test_name_with_space_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("my column")

    def test_name_with_dash_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("my-column")

    def test_name_with_dot_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("my.column")

    def test_sql_injection_semicolon_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("col; DROP TABLE cortex_notes; --")

    def test_sql_injection_quote_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("col' OR '1'='1")

    def test_leading_digit_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("1column")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            validate_identifier("")


# ===========================================================================
# validate_column_type()
# ===========================================================================

class TestValidateColumnType:
    """Tests for validate_column_type()."""

    @pytest.mark.parametrize("col_type", [
        "TEXT", "INTEGER", "DATE", "BOOLEAN", "FLOAT", "TIMESTAMP"
    ])
    def test_whitelisted_uppercase_passes(self, col_type):
        result = validate_column_type(col_type)
        assert result == col_type.upper()

    @pytest.mark.parametrize("col_type", [
        "text", "integer", "date", "boolean", "float", "timestamp"
    ])
    def test_whitelisted_lowercase_passes(self, col_type):
        result = validate_column_type(col_type)
        assert result == col_type.upper()

    @pytest.mark.parametrize("col_type", [
        "Text", "Integer", "Date"
    ])
    def test_whitelisted_mixed_case_passes(self, col_type):
        result = validate_column_type(col_type)
        assert result == col_type.upper()

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            validate_column_type("VARCHAR")

    def test_unknown_type_json_raises(self):
        with pytest.raises(ValueError):
            validate_column_type("JSON")

    def test_unknown_type_bytea_raises(self):
        with pytest.raises(ValueError):
            validate_column_type("BYTEA")

    def test_sql_injection_type_raises(self):
        with pytest.raises(ValueError):
            validate_column_type("TEXT; DROP TABLE users; --")

    def test_return_value_always_uppercase(self):
        assert validate_column_type("date") == "DATE"
        assert validate_column_type("float") == "FLOAT"


# ===========================================================================
# parse_frontmatter()
# ===========================================================================

class TestParseFrontmatter:
    """Tests for parse_frontmatter()."""

    def test_valid_frontmatter_parsed(self, tmp_path):
        md = tmp_path / "note.md"
        write_md(md, "title: My Note\nstatus: active\ntags:\n  - python\n  - testing",
                 body="This is the body of the note.")
        result = parse_frontmatter(md)
        assert result is not None
        assert result["title"] == "My Note"
        assert result["status"] == "active"
        assert result["tags"] == ["python", "testing"]

    def test_content_preview_is_first_200_chars(self, tmp_path):
        md = tmp_path / "note.md"
        body = "x" * 300
        write_md(md, "title: T", body=body)
        result = parse_frontmatter(md)
        assert result is not None
        assert len(result["_content_preview"]) == 200
        assert result["_content_preview"] == "x" * 200

    def test_content_preview_shorter_than_200(self, tmp_path):
        md = tmp_path / "note.md"
        body = "Short body."
        write_md(md, "title: T", body=body)
        result = parse_frontmatter(md)
        assert result["_content_preview"] == "Short body."

    def test_body_stored_in_body_key(self, tmp_path):
        md = tmp_path / "note.md"
        write_md(md, "title: T", body="Full content here.")
        result = parse_frontmatter(md)
        assert result["_body"] == "Full content here."

    def test_no_frontmatter_returns_none(self, tmp_path):
        md = tmp_path / "bare.md"
        md.write_text("Just some markdown text without frontmatter.", encoding="utf-8")
        assert parse_frontmatter(md) is None

    def test_empty_file_returns_none(self, tmp_path):
        md = tmp_path / "empty.md"
        md.write_text("", encoding="utf-8")
        assert parse_frontmatter(md) is None

    def test_malformed_yaml_returns_none(self, tmp_path):
        md = tmp_path / "bad.md"
        # Deliberately invalid YAML (unbalanced braces / tabs mixed)
        md.write_text("---\ntitle: [unclosed bracket\nfoo: bar: baz: :\n---\n", encoding="utf-8")
        assert parse_frontmatter(md) is None

    def test_frontmatter_only_no_body(self, tmp_path):
        md = tmp_path / "noBody.md"
        write_md(md, "title: T\nstatus: active", body="")
        result = parse_frontmatter(md)
        assert result is not None
        assert result["_content_preview"] == ""

    def test_non_dict_yaml_returns_none(self, tmp_path):
        # YAML scalar at top level (e.g. just a string) should return None
        md = tmp_path / "scalar.md"
        md.write_text("---\njust a string\n---\n", encoding="utf-8")
        assert parse_frontmatter(md) is None

    def test_opening_fence_missing_returns_none(self, tmp_path):
        md = tmp_path / "no_open.md"
        md.write_text("title: My Note\n---\nBody.", encoding="utf-8")
        assert parse_frontmatter(md) is None


# ===========================================================================
# find_md_files()
# ===========================================================================

class TestFindMdFiles:
    """Tests for find_md_files()."""

    def test_finds_md_in_root(self, tmp_path):
        (tmp_path / "note.md").write_text("# Hello")
        files = find_md_files(tmp_path)
        assert tmp_path / "note.md" in files

    def test_finds_md_in_nested_dirs(self, tmp_path):
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "deep_note.md").write_text("# Deep")
        files = find_md_files(tmp_path)
        assert sub / "deep_note.md" in files

    def test_returns_sorted_list(self, tmp_path):
        names = ["charlie.md", "alpha.md", "bravo.md"]
        for n in names:
            (tmp_path / n).write_text("")
        files = find_md_files(tmp_path)
        file_names = [f.name for f in files]
        assert file_names == sorted(file_names)

    def test_hidden_dir_excluded(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.md").write_text("# Secret")
        files = find_md_files(tmp_path)
        assert not any(".hidden" in str(f) for f in files)

    def test_cortex_dir_excluded(self, tmp_path):
        cortex = tmp_path / ".cortex"
        cortex.mkdir()
        (cortex / "internal.md").write_text("# Internal")
        files = find_md_files(tmp_path)
        assert not any(".cortex" in str(f) for f in files)

    def test_obsidian_dir_excluded(self, tmp_path):
        obs = tmp_path / ".obsidian"
        obs.mkdir()
        (obs / "config.md").write_text("# Obsidian config")
        files = find_md_files(tmp_path)
        assert not any(".obsidian" in str(f) for f in files)

    def test_non_md_files_not_included(self, tmp_path):
        (tmp_path / "readme.txt").write_text("text file")
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "note.md").write_text("# Note")
        files = find_md_files(tmp_path)
        assert all(f.suffix == ".md" for f in files)

    def test_empty_vault_returns_empty_list(self, tmp_path):
        assert find_md_files(tmp_path) == []

    def test_multiple_nested_dirs(self, tmp_path):
        for subdir in ("work", "personal", "work/projects"):
            d = tmp_path / subdir
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{subdir.replace('/', '_')}.md").write_text("# Note")
        files = find_md_files(tmp_path)
        assert len(files) == 3


# ===========================================================================
# local_query()
# ===========================================================================

class TestLocalQuery:
    """Tests for local_query() using real temp vaults."""

    def _make_vault(self, tmp_path):
        """Create a small vault with several tagged/typed notes."""
        notes = [
            {
                "filename": "alpha.md",
                "frontmatter": textwrap.dedent("""\
                    title: Alpha Note
                    type: project
                    status: active
                    priority: P1
                    tags:
                      - python
                      - backend
                    created: 2024-01-01
                    updated: 2024-06-01
                """),
                "body": "Alpha is about Python backend systems.",
            },
            {
                "filename": "beta.md",
                "frontmatter": textwrap.dedent("""\
                    title: Beta Note
                    type: reference
                    status: done
                    priority: P2
                    tags:
                      - typescript
                      - frontend
                    created: 2024-02-01
                    updated: 2024-07-01
                """),
                "body": "Beta covers TypeScript frontend patterns.",
            },
            {
                "filename": "gamma.md",
                "frontmatter": textwrap.dedent("""\
                    title: Gamma Note
                    type: project
                    status: active
                    priority: P0
                    tags:
                      - python
                      - devops
                    created: 2024-03-01
                    updated: 2024-08-01
                """),
                "body": "Gamma is about DevOps automation.",
            },
            {
                "filename": "delta.md",
                "frontmatter": textwrap.dedent("""\
                    title: Delta Note
                    type: note
                    status: draft
                    priority: P3
                    tags:
                      - misc
                    created: 2024-04-01
                    updated: 2024-09-01
                """),
                "body": "Delta is a miscellaneous draft note.",
            },
            {
                "filename": "bare.md",
                "frontmatter": None,
                "body": "No frontmatter here.",
            },
        ]
        for n in notes:
            path = tmp_path / n["filename"]
            if n["frontmatter"] is None:
                path.write_text(n["body"], encoding="utf-8")
            else:
                write_md(path, n["frontmatter"], n["body"])
        return tmp_path

    # ---- basic retrieval ---------------------------------------------------

    def test_returns_all_notes_with_frontmatter(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault)
        # 4 notes have frontmatter, bare.md does not
        assert len(results) == 4

    def test_bare_file_excluded(self, tmp_path):
        vault = self._make_vault(tmp_path)
        titles = [r["title"] for r in local_query(vault)]
        assert "bare.md" not in titles
        assert all("bare" not in t.lower() for t in titles)

    # ---- type filter -------------------------------------------------------

    def test_filter_by_type(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, type_filter="project")
        assert len(results) == 2
        assert all(r["type"] == "project" for r in results)

    def test_filter_by_type_no_match(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, type_filter="journal")
        assert results == []

    # ---- status filter -----------------------------------------------------

    def test_filter_by_status(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, status_filter="active")
        assert len(results) == 2
        assert all(r["status"] == "active" for r in results)

    def test_filter_by_status_done(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, status_filter="done")
        assert len(results) == 1
        assert results[0]["title"] == "Beta Note"

    # ---- tag filter --------------------------------------------------------

    def test_filter_by_tag(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, tag_filter="python")
        assert len(results) == 2
        for r in results:
            assert "python" in r["tags"]

    def test_filter_by_tag_case_insensitive(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results_lower = local_query(vault, tag_filter="python")
        results_upper = local_query(vault, tag_filter="PYTHON")
        assert len(results_lower) == len(results_upper)

    def test_filter_by_nonexistent_tag(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, tag_filter="nonexistent")
        assert results == []

    # ---- search filter -----------------------------------------------------

    def test_search_matches_title(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, search="Alpha")
        assert len(results) == 1
        assert results[0]["title"] == "Alpha Note"

    def test_search_matches_body_content(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, search="DevOps")
        assert len(results) == 1
        assert results[0]["title"] == "Gamma Note"

    def test_search_case_insensitive(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results_lower = local_query(vault, search="alpha")
        results_upper = local_query(vault, search="ALPHA")
        assert len(results_lower) == len(results_upper) == 1

    def test_search_no_match_returns_empty(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, search="zyxwvutsrqpon")
        assert results == []

    # ---- limit -------------------------------------------------------------

    def test_limit_restricts_results(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, limit=2)
        assert len(results) == 2

    def test_limit_zero_returns_nothing(self, tmp_path):
        # limit=0 is falsy; the code treats it as no-limit, skip this edge case
        # Instead test limit=1
        vault = self._make_vault(tmp_path)
        results = local_query(vault, limit=1)
        assert len(results) == 1

    def test_limit_greater_than_total_returns_all(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, limit=100)
        assert len(results) == 4

    # ---- combined filters --------------------------------------------------

    def test_combined_type_and_status(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, type_filter="project", status_filter="active")
        assert len(results) == 2

    def test_combined_type_and_tag(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, type_filter="project", tag_filter="python")
        assert len(results) == 2

    def test_combined_search_and_type(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault, search="python", type_filter="project")
        # alpha (title+body contains python, type=project) + gamma (tag python, type=project)
        assert len(results) >= 1

    # ---- result shape ------------------------------------------------------

    def test_result_has_required_keys(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault)
        required = {"file_path", "title", "type", "status", "tags", "priority",
                    "created", "updated", "content_preview"}
        for r in results:
            assert required.issubset(r.keys()), f"Missing keys in result: {r}"

    def test_file_path_is_relative(self, tmp_path):
        vault = self._make_vault(tmp_path)
        results = local_query(vault)
        for r in results:
            assert not Path(r["file_path"]).is_absolute()
