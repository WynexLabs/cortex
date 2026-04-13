"""
Tests for v1.4 cortex_lint.py — the 7 deterministic checks.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from cortex_lint import check_note
from cortex_common import find_md_files


def write_note(dir_path: Path, name: str, frontmatter: str, body: str = "") -> Path:
    path = dir_path / name
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return path


@pytest.fixture
def vault(tmp_path):
    """Tiny vault with a few notes used as wikilink targets."""
    write_note(tmp_path, "vps.md", "type: infrastructure\nstatus: active")
    write_note(tmp_path, "strata.md", "type: project\nstatus: active")
    return tmp_path


def rules(warnings):
    return [w["rule"] for w in warnings]


class TestRule1MissingSummary:
    def test_warns_when_no_summary(self, vault):
        note = write_note(vault, "no-summary.md", "type: log\nstatus: active\ncreated: 2026-04-01\nupdated: 2026-04-01")
        warnings = check_note(note, vault, find_md_files(vault))
        assert "missing-summary-frontmatter" in rules(warnings)

    def test_passes_with_summary(self, vault):
        note = write_note(vault, "with-summary.md",
                          "type: log\nstatus: active\nsummary: One sentence summary.\ncreated: 2026-04-01\nupdated: 2026-04-01")
        warnings = check_note(note, vault, find_md_files(vault))
        assert "missing-summary-frontmatter" not in rules(warnings)


class TestRule2MissingSummaryH2:
    def test_warns_long_note_without_summary_h2(self, vault):
        # 600 words triggers it
        body = "## Other\n\n" + ("word " * 600)
        note = write_note(vault, "long.md",
                          "type: log\nstatus: active\nsummary: A summary.\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "missing-summary-h2" in rules(warnings)

    def test_passes_long_note_with_summary_h2_first(self, vault):
        body = "## Summary\n\nMirror text.\n\n## Other\n\n" + ("word " * 600)
        note = write_note(vault, "long-ok.md",
                          "type: log\nstatus: active\nsummary: A summary.\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "missing-summary-h2" not in rules(warnings)

    def test_short_note_doesnt_need_summary_h2(self, vault):
        note = write_note(vault, "short.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          "Short body.")
        warnings = check_note(note, vault, find_md_files(vault))
        assert "missing-summary-h2" not in rules(warnings)


class TestRule3AtomicCeiling:
    def test_warns_too_many_h2(self, vault):
        body = "## A\nx\n## B\nx\n## C\nx\n## D\nx"
        note = write_note(vault, "many-h2.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "atomic-ceiling-exceeded" in rules(warnings)

    def test_warns_too_many_words(self, vault):
        body = "## Summary\n\nMirror.\n\n## One\n\n" + ("word " * 700)
        note = write_note(vault, "wordy.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "atomic-ceiling-exceeded" in rules(warnings)

    def test_passes_within_ceiling(self, vault):
        body = "## A\nx\n## B\nx"
        note = write_note(vault, "small.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "atomic-ceiling-exceeded" not in rules(warnings)


class TestRule4DanglingWikilink:
    def test_flags_dangling(self, vault):
        body = "Linking [[nonexistent-note]] here."
        note = write_note(vault, "danglers.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        dangling = [w for w in warnings if w["rule"] == "dangling-wikilink"]
        assert len(dangling) == 1
        assert "nonexistent-note" in dangling[0]["msg"]

    def test_resolves_existing_target(self, vault):
        body = "Linking [[vps]] which exists."
        note = write_note(vault, "good-link.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "dangling-wikilink" not in rules(warnings)


class TestRule5PronounOpener:
    def test_flags_it_opener(self, vault):
        body = "## Section A\n\nIt is doing the thing.\n\n## Section B\n\nPlain content."
        note = write_note(vault, "pronouns.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        opener_flags = [w for w in warnings if w["rule"] == "pronoun-opener-at-h2"]
        assert len(opener_flags) == 1
        assert "Section A" in opener_flags[0]["msg"]

    def test_passes_named_opener(self, vault):
        body = "## Section A\n\nStrata is doing the thing."
        note = write_note(vault, "ok-opener.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "pronoun-opener-at-h2" not in rules(warnings)


class TestRule6FrontmatterValidation:
    def test_unknown_status(self, vault):
        note = write_note(vault, "bad-status.md",
                          "type: log\nstatus: in-progress\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01")
        warnings = check_note(note, vault, find_md_files(vault))
        assert "unknown-status" in rules(warnings)

    def test_unknown_priority(self, vault):
        note = write_note(vault, "bad-priority.md",
                          "type: log\nstatus: active\npriority: HIGH\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01")
        warnings = check_note(note, vault, find_md_files(vault))
        assert "unknown-priority" in rules(warnings)

    def test_missing_dates(self, vault):
        note = write_note(vault, "no-dates.md",
                          "type: log\nstatus: active\nsummary: x")
        warnings = check_note(note, vault, find_md_files(vault))
        assert "missing-created-date" in rules(warnings)
        assert "missing-updated-date" in rules(warnings)


class TestRule7HeadingSlugCollision:
    def test_flags_in_file_collision(self, vault):
        body = "## Same Heading\n\nA\n\n## Same Heading\n\nB"
        note = write_note(vault, "collision.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "heading-slug-collision" in rules(warnings)

    def test_passes_unique_headings(self, vault):
        body = "## First\n\nA\n\n## Second\n\nB"
        note = write_note(vault, "unique.md",
                          "type: log\nstatus: active\nsummary: x\ncreated: 2026-04-01\nupdated: 2026-04-01",
                          body)
        warnings = check_note(note, vault, find_md_files(vault))
        assert "heading-slug-collision" not in rules(warnings)


class TestNoFrontmatter:
    def test_flags_missing_frontmatter(self, vault):
        path = vault / "raw.md"
        path.write_text("# Raw note\n\nNo frontmatter at all.")
        warnings = check_note(path, vault, find_md_files(vault))
        assert any(w["rule"] == "frontmatter-missing" for w in warnings)
        # Ensure file_path attached even on early-return path
        for w in warnings:
            assert "file_path" in w
