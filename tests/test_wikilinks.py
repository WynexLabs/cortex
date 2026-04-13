"""
Tests for v1.4 wikilink and resolve_link functions in cortex_common.py.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from cortex_common import extract_wikilinks, resolve_link, find_md_files


class TestExtractWikilinks:
    def test_simple_wikilink(self):
        result = extract_wikilinks("Some [[strata]] reference.")
        assert result == [("strata", 5)]

    def test_wikilink_with_alias_strips_alias(self):
        result = extract_wikilinks("See [[projects/strata/README|Strata]] now.")
        assert result == [("projects/strata/README", 4)]

    def test_wikilink_with_section_strips_section(self):
        result = extract_wikilinks("Read [[infrastructure/vps#tunnel]] section.")
        assert result == [("infrastructure/vps", 5)]

    def test_wikilink_with_section_and_alias(self):
        result = extract_wikilinks("Read [[infrastructure/vps#tunnel|the tunnel]] section.")
        assert result == [("infrastructure/vps", 5)]

    def test_multiple_wikilinks(self):
        body = "Both [[a]] and [[b]] linked."
        result = extract_wikilinks(body)
        assert len(result) == 2
        assert result[0][0] == "a"
        assert result[1][0] == "b"

    def test_wikilinks_inside_code_block_are_skipped(self):
        body = "Real [[real]] link.\n\n```\n[[fake]] in code\n```\n\nAfter [[after]] block."
        result = extract_wikilinks(body)
        targets = [t for t, _ in result]
        assert "real" in targets
        assert "after" in targets
        assert "fake" not in targets

    def test_positions_match_raw_body(self):
        body = "Prefix [[link]] suffix."
        result = extract_wikilinks(body)
        assert result == [("link", 7)]
        target, pos = result[0]
        assert body[pos:pos + 8] == "[[link]]"

    def test_no_wikilinks_returns_empty(self):
        assert extract_wikilinks("Just plain text without any links.") == []

    def test_strips_whitespace_in_target(self):
        result = extract_wikilinks("With [[ spaced ]] padding.")
        assert result == [("spaced", 5)]


class TestResolveLink:
    @pytest.fixture
    def fake_vault(self, tmp_path):
        (tmp_path / "infrastructure").mkdir()
        (tmp_path / "infrastructure" / "vps.md").write_text("# vps")
        (tmp_path / "infrastructure" / "openclaw.md").write_text("# openclaw")
        (tmp_path / "projects" / "strata").mkdir(parents=True)
        (tmp_path / "projects" / "strata" / "README.md").write_text("# strata")
        (tmp_path / "projects" / "atlas").mkdir(parents=True)
        (tmp_path / "projects" / "atlas" / "README.md").write_text("# atlas")
        return tmp_path

    def test_basename_resolution(self, fake_vault):
        path, found = resolve_link("vps", fake_vault)
        assert found is True
        assert path == "infrastructure/vps.md"

    def test_basename_case_insensitive(self, fake_vault):
        path, found = resolve_link("VPS", fake_vault)
        assert found is True
        assert path == "infrastructure/vps.md"

    def test_path_style_resolution(self, fake_vault):
        path, found = resolve_link("projects/strata/README", fake_vault)
        assert found is True
        assert path == "projects/strata/README.md"

    def test_path_style_no_basename_fallthrough(self, fake_vault):
        # `wrong/path/README` shouldn't fall through to ANY README.md
        path, found = resolve_link("wrong/path/README", fake_vault)
        assert found is False
        assert path == "wrong/path/README"

    def test_dangling_basename_returns_unfound(self, fake_vault):
        path, found = resolve_link("nonexistent-note", fake_vault)
        assert found is False
        assert path == "nonexistent-note"

    def test_md_extension_in_target_handled(self, fake_vault):
        path, found = resolve_link("vps.md", fake_vault)
        assert found is True
        assert path == "infrastructure/vps.md"

    def test_md_files_can_be_passed_to_avoid_rescan(self, fake_vault):
        md_files = find_md_files(fake_vault)
        path, found = resolve_link("openclaw", fake_vault, md_files=md_files)
        assert found is True
        assert path == "infrastructure/openclaw.md"
