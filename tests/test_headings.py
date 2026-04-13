"""
Tests for v1.4 heading extraction and slugify in cortex_common.py.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from cortex_common import extract_headings, slugify


class TestSlugify:
    def test_simple_heading(self):
        assert slugify("Hello World") == "hello-world"

    def test_lowercases(self):
        assert slugify("MixedCase") == "mixedcase"

    def test_strips_punctuation(self):
        assert slugify("Section Two — With Punctuation!") == "section-two-with-punctuation"

    def test_collapses_repeated_hyphens(self):
        assert slugify("Already--Hyphenated") == "already-hyphenated"

    def test_strips_leading_trailing_hyphens(self):
        assert slugify("--leading and trailing--") == "leading-and-trailing"

    def test_em_dash_handled(self):
        assert slugify("A — B") == "a-b"

    def test_unicode_collapsed(self):
        # Non-ascii chars become hyphens (then collapsed)
        assert slugify("café paris") == "caf-paris"


class TestExtractHeadings:
    def test_h1_to_h6(self):
        body = "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6\n"
        headings = extract_headings(body)
        assert len(headings) == 6
        for i, (level, _, _) in enumerate(headings, start=1):
            assert level == i

    def test_position_matches_raw_body(self):
        body = "Intro paragraph.\n\n## Identity\n\nContent."
        headings = extract_headings(body)
        assert len(headings) == 1
        level, text, pos = headings[0]
        assert level == 2
        assert text == "Identity"
        assert body[pos:pos + 11] == "## Identity"

    def test_headings_inside_code_blocks_skipped(self):
        body = "## Real heading\n\n```\n## Fake heading in code\n```\n\n## Another real\n"
        headings = extract_headings(body)
        texts = [t for _, t, _ in headings]
        assert "Real heading" in texts
        assert "Another real" in texts
        assert "Fake heading in code" not in texts

    def test_strips_trailing_whitespace_in_text(self):
        body = "## Trailing space   \n"
        headings = extract_headings(body)
        assert headings[0][1] == "Trailing space"

    def test_no_headings_returns_empty(self):
        assert extract_headings("Just paragraphs, no headings.") == []

    def test_must_have_space_after_hashes(self):
        # `#hashtag` is not a heading
        body = "#hashtag without space\n## real heading"
        headings = extract_headings(body)
        assert len(headings) == 1
        assert headings[0][1] == "real heading"

    def test_seven_or_more_hashes_not_a_heading(self):
        # Markdown only allows H1-H6
        body = "####### too many\n## real"
        headings = extract_headings(body)
        assert len(headings) == 1
        assert headings[0][1] == "real"

    def test_multiple_h2s_with_correct_positions(self):
        body = "## First\n\nA paragraph.\n\n## Second\n\nMore text.\n\n## Third\n"
        headings = extract_headings(body)
        assert [t for _, t, _ in headings] == ["First", "Second", "Third"]
        for level, _, pos in headings:
            assert level == 2
            assert body[pos] == "#"
