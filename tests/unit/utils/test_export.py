"""Unit tests for export module."""

import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from confluence_markdown_exporter.utils.export import cap_path_segment
from confluence_markdown_exporter.utils.export import cap_path_segments
from confluence_markdown_exporter.utils.export import escape_character_class
from confluence_markdown_exporter.utils.export import github_heading_slug
from confluence_markdown_exporter.utils.export import parse_encode_setting
from confluence_markdown_exporter.utils.export import sanitize_filename
from confluence_markdown_exporter.utils.export import sanitize_key
from confluence_markdown_exporter.utils.export import save_file
from confluence_markdown_exporter.utils.export import truncate_to_bytes


class TestParseEncodeSetting:
    """Test cases for parse_encode_setting function."""

    def test_empty_string(self) -> None:
        """Test parsing empty string returns empty dict."""
        result = parse_encode_setting("")
        assert result == {}

    def test_simple_mapping(self) -> None:
        """Test parsing simple character mapping."""
        result = parse_encode_setting('" ":"%2D","-":"%2D"')
        expected = {" ": "%2D", "-": "%2D"}
        assert result == expected

    def test_mixed_mapping(self) -> None:
        """Test parsing mixed character mapping."""
        result = parse_encode_setting('" ":"dash","-":"%2D"')
        expected = {" ": "dash", "-": "%2D"}
        assert result == expected

    def test_equals_mapping(self) -> None:
        """Test parsing equals sign mapping."""
        result = parse_encode_setting('"=":" equals "')
        expected = {"=": " equals "}
        assert result == expected

    def test_special_characters(self) -> None:
        """Test parsing special characters."""
        result = parse_encode_setting('"\\"":" quote ","\\\\":" backslash "')
        expected = {'"': " quote ", "\\": " backslash "}
        assert result == expected

    def test_invalid_json(self) -> None:
        """Test that invalid JSON returns empty dict."""
        result = parse_encode_setting("invalid json")
        assert result == {}

    def test_non_dict_json(self) -> None:
        """Test that non-dict JSON returns empty dict."""
        result = parse_encode_setting('"this is a string"')
        assert result == {}

    def test_malformed_json(self) -> None:
        """Test that malformed JSON returns empty dict."""
        result = parse_encode_setting('"key":"value",')
        assert result == {}


class TestSaveFile:
    """Test cases for save_file function."""

    def test_save_string_content(self) -> None:
        """Test saving string content to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            content = "Hello, World!"

            save_file(file_path, content)

            assert file_path.exists()
            assert file_path.read_text(encoding="utf-8") == content

    def test_save_bytes_content(self) -> None:
        """Test saving bytes content to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.bin"
            content = b"Binary content"

            save_file(file_path, content)

            assert file_path.exists()
            assert file_path.read_bytes() == content

    def test_create_parent_directories(self) -> None:
        """Test that parent directories are created when needed."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "subdir" / "nested" / "test.txt"
            content = "Test content"

            save_file(file_path, content)

            assert file_path.exists()
            assert file_path.read_text(encoding="utf-8") == content

    def test_overwrite_existing_file(self) -> None:
        """Test overwriting an existing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"
            original_content = "Original content"
            new_content = "New content"

            save_file(file_path, original_content)
            save_file(file_path, new_content)

            assert file_path.read_text(encoding="utf-8") == new_content

    def test_invalid_content_type(self) -> None:
        """Test that invalid content type raises TypeError."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "test.txt"

            with pytest.raises(TypeError, match=r"Content must be either a string or bytes\."):
                save_file(file_path, 123)  # type: ignore[arg-type]


class TestSanitizeFilename:
    """Test cases for sanitize_filename function."""

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_no_encoding_specified(self, mock_export_options: MagicMock) -> None:
        """Test sanitizing filename with no encoding specified."""
        mock_export_options.filename_encoding = ""
        mock_export_options.filename_length = 255
        mock_export_options.filename_lowercase = False

        result = sanitize_filename("Test File.txt")
        assert result == "Test File.txt"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_with_encoding_mapping(self, mock_export_options: MagicMock) -> None:
        """Test sanitizing filename with encoding mapping."""
        mock_export_options.filename_encoding = '" ":"_",":":"_"'
        mock_export_options.filename_length = 255
        mock_export_options.filename_lowercase = False

        result = sanitize_filename("Test File: Name.txt")
        assert result == "Test_File__Name.txt"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_with_encoding_mapping_lowercase(self, mock_export_options: MagicMock) -> None:
        """Test sanitizing filename with encoding mapping."""
        mock_export_options.filename_encoding = '" ":"_",":":"_"'
        mock_export_options.filename_length = 255
        mock_export_options.filename_lowercase = True

        result = sanitize_filename("Test File: Name.txt")
        assert result == "test_file__name.txt"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_trim_trailing_spaces_and_dots(self, mock_export_options: MagicMock) -> None:
        """Test that trailing spaces and dots are trimmed."""
        mock_export_options.filename_encoding = ""
        mock_export_options.filename_length = 255
        mock_export_options.filename_lowercase = False

        result = sanitize_filename("filename . . ")
        assert result == "filename"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_reserved_windows_names(self, mock_export_options: MagicMock) -> None:
        """Test that reserved Windows names are handled."""
        mock_export_options.filename_encoding = ""
        mock_export_options.filename_length = 255
        mock_export_options.filename_lowercase = False

        reserved_names = ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]
        for name in reserved_names:
            result = sanitize_filename(name)
            assert result == f"{name}_"

            # Test case insensitive
            result = sanitize_filename(name.lower())
            assert result == f"{name.lower()}_"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_complex_filename_sanitization(self, mock_export_options: MagicMock) -> None:
        """Test complex filename sanitization with multiple rules."""
        mock_export_options.filename_encoding = '" ":"_","?":"_",":":"_"'
        mock_export_options.filename_length = 50
        mock_export_options.filename_lowercase = False

        filename = "My Document: What? How?  . ."
        result = sanitize_filename(filename)
        # Character replacements happen first, then rstrip of spaces and dots
        assert result == "My_Document__What__How___._"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_control_characters_removed(self, mock_export_options: MagicMock) -> None:
        """Control characters (e.g. backspace) should be stripped."""
        mock_export_options.filename_encoding = ""
        mock_export_options.filename_length = 255

        result = sanitize_filename("on-pr\x08emise")
        assert result == "on-premise"

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_multiple_control_characters(self, mock_export_options: MagicMock) -> None:
        """Multiple control characters should all be stripped."""
        mock_export_options.filename_encoding = ""
        mock_export_options.filename_length = 255

        result = sanitize_filename("test\x00\x08\x1fname")
        assert result == "testname"


class TestTruncateToBytes:
    """Test cases for truncate_to_bytes function."""

    def test_short_name_unchanged(self) -> None:
        """A name inside the cap is returned identical."""
        assert truncate_to_bytes("report.md", 255) == "report.md"

    def test_name_exactly_at_the_cap_unchanged(self) -> None:
        """The cap is inclusive, so a name of exactly max_bytes is not touched."""
        name = "a" * 255
        assert truncate_to_bytes(name, 255) == name

    def test_cut_lands_on_a_character_boundary(self) -> None:
        """A multi-byte character is never split in half."""
        result = truncate_to_bytes("б" * 200, 255)  # noqa: RUF001 -- Cyrillic is the point
        assert len(result.encode("utf-8")) <= 255
        assert result.encode("utf-8").decode("utf-8") == result

    def test_never_cuts_inside_a_percent_escape(self) -> None:
        """A dangling `%` or `%2` left by the cut is dropped rather than kept."""
        # 84 escapes of 3 bytes each = 252 bytes; the 82nd lands across the 246-byte budget.
        result = truncate_to_bytes("%2D" * 84, 255)
        head = result[:-9]
        assert not head.endswith("%")
        assert not re.search(r"%[0-9A-Fa-f]$", head)
        assert len(result.encode("utf-8")) <= 255

    def test_distinct_inputs_stay_distinct(self) -> None:
        """The digest suffix comes from the full name, so a shared prefix is not a collision."""
        shared = "ц" * 300
        assert truncate_to_bytes(f"{shared}1", 255) != truncate_to_bytes(f"{shared}2", 255)

    def test_cap_too_small_for_the_suffix(self) -> None:
        """Below the suffix width there is no room for a digest; the cut still holds."""
        result = truncate_to_bytes("ю" * 50, 8)
        assert len(result.encode("utf-8")) <= 8
        assert "~" not in result


class TestCapPathSegment:
    """Test cases for cap_path_segment -- the byte cap on ONE rendered path segment."""

    def test_segment_under_the_cap_is_untouched(self) -> None:
        """A name that already fits comes back byte for byte."""
        name = "Quarterly Report 2026-Q1.md"
        assert cap_path_segment(name, 255) == name

    def test_cyrillic_page_name_fits_the_byte_cap(self) -> None:
        """A 300-character Cyrillic title plus `.md` must fit 255 BYTES, not 255 characters."""
        segment = "Отчёт о нагрузке " * 18 + ".md"  # noqa: RUF001 -- Cyrillic is the point
        assert len(segment) > 300

        result = cap_path_segment(segment, 255)

        assert len(result.encode("utf-8")) <= 255
        assert result.endswith(".md")

    def test_names_differing_after_the_cut_stay_distinct(self) -> None:
        """Two long names sharing a prefix must not collapse onto one file."""
        shared = "Требования к витрине " * 15
        first = cap_path_segment(f"{shared} вариант А.md", 255)  # noqa: RUF001
        second = cap_path_segment(f"{shared} вариант Б.md", 255)

        assert first != second
        assert first.endswith(".md")
        assert second.endswith(".md")
        assert max(len(first.encode("utf-8")), len(second.encode("utf-8"))) <= 255

    def test_title_punctuation_is_not_taken_for_an_extension(self) -> None:
        """A trailing `.)` is page-title punctuation, so nothing is preserved as an extension."""
        segment = "Итерация 2 - Реализовать_ громкость озвучки, тон речи." * 6 + ".)"
        result = cap_path_segment(segment, 255)

        assert len(result.encode("utf-8")) <= 255
        assert not result.endswith(".)")

    def test_extensionless_segment_falls_back_to_the_plain_rule(self) -> None:
        """A directory segment has no extension and is cut by truncate_to_bytes."""
        segment = "ц" * 300
        assert cap_path_segment(segment, 255) == truncate_to_bytes(segment, 255)


class TestCapPathSegments:
    """Test cases for cap_path_segments -- the cap applied across a whole rendered path."""

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_every_segment_is_capped_independently(self, mock_export_options: MagicMock) -> None:
        """Directory segments are capped by the same rule as the file name."""
        mock_export_options.filename_length = 255
        long_directory = "д" * 200
        path = Path(long_directory) / f"{'я' * 200}.md"

        result = cap_path_segments(path)

        assert [len(part.encode("utf-8")) <= 255 for part in result.parts] == [True, True]
        assert result.name.endswith(".md")

    @patch("confluence_markdown_exporter.utils.export.export_options")
    def test_a_path_already_inside_the_cap_is_unchanged(
        self, mock_export_options: MagicMock
    ) -> None:
        """An ASCII export keeps exactly the paths it had before."""
        mock_export_options.filename_length = 255
        path = Path("Space Name") / "Homepage" / "Ancestor" / "Page Title.md"

        assert cap_path_segments(path) == path


class TestSanitizeKey:
    """Test cases for sanitize_key function."""

    def test_basic_string(self) -> None:
        """Test sanitizing basic string."""
        result = sanitize_key("Test String")
        assert result == "test_string"

    def test_special_characters(self) -> None:
        """Test sanitizing string with special characters."""
        result = sanitize_key("Test-Key: With @ Special % Characters!")
        assert result == "test_key_with_special_characters"

    def test_multiple_underscores_collapse(self) -> None:
        """Test that multiple consecutive underscores are collapsed."""
        result = sanitize_key("test___multiple___underscores")
        assert result == "test_multiple_underscores"

    def test_trim_leading_trailing_underscores(self) -> None:
        """Test that leading and trailing underscores are trimmed."""
        result = sanitize_key("__test_key__")
        assert result == "test_key"

    def test_starts_with_number(self) -> None:
        """Test that string starting with number gets key_ prefix."""
        result = sanitize_key("123test")
        assert result == "key_123test"

    def test_starts_with_special_character(self) -> None:
        """Test that string starting with special character becomes valid after processing."""
        result = sanitize_key("@test")
        # "@test" -> "@test" (lowercase) -> "_test" (replace @) -> "test" (strip _)
        # Since "test" starts with 't' (a letter), no key_ prefix is added
        assert result == "test"

    def test_custom_connector(self) -> None:
        """Test using custom connector character."""
        result = sanitize_key("Test String", connector="-")
        assert result == "test-string"

    def test_already_valid_key(self) -> None:
        """Test that already valid key remains unchanged."""
        result = sanitize_key("valid_key")
        assert result == "valid_key"

    def test_empty_string(self) -> None:
        """Test sanitizing empty string."""
        result = sanitize_key("")
        assert result == "key_"

    def test_only_special_characters(self) -> None:
        """Test string with only special characters."""
        result = sanitize_key("@#$%")
        assert result == "key_"


class TestGithubHeadingSlug:
    """Test cases for github_heading_slug function."""

    def test_leading_hyphen_preserved(self) -> None:
        """Heading starting with hyphen keeps it — the reported bug."""
        assert github_heading_slug("- Final State") == "-final-state"

    def test_plain_heading(self) -> None:
        assert github_heading_slug("Final State") == "final-state"

    def test_uppercase(self) -> None:
        assert github_heading_slug("Hello World") == "hello-world"

    def test_special_chars_removed(self) -> None:
        assert github_heading_slug("Hello, World!") == "hello-world"

    def test_multiple_spaces_collapsed(self) -> None:
        assert github_heading_slug("Hello  World") == "hello-world"

    def test_trailing_hyphen(self) -> None:
        assert github_heading_slug("Hello -") == "hello-"

    def test_empty_string(self) -> None:
        assert github_heading_slug("") == ""


class TestEscapeCharacterClass:
    """Test cases for escape_character_class function."""

    def test_escape_backslash(self) -> None:
        """Test escaping backslash character."""
        result = escape_character_class("\\")
        assert result == "\\\\"

    def test_escape_dash(self) -> None:
        """Test escaping dash character."""
        result = escape_character_class("-")
        assert result == "\\-"

    def test_escape_right_bracket(self) -> None:
        """Test escaping right bracket character."""
        result = escape_character_class("]")
        assert result == "\\]"

    def test_escape_caret(self) -> None:
        """Test escaping caret character."""
        result = escape_character_class("^")
        assert result == "\\^"

    def test_escape_multiple_characters(self) -> None:
        """Test escaping multiple special characters."""
        result = escape_character_class("\\-]^")
        assert result == "\\\\\\-\\]\\^"

    def test_no_special_characters(self) -> None:
        """Test string with no special characters."""
        result = escape_character_class("abc123")
        assert result == "abc123"

    def test_mixed_characters(self) -> None:
        """Test string with mix of special and normal characters."""
        result = escape_character_class("a-b]c^d\\e")
        assert result == "a\\-b\\]c\\^d\\\\e"

    def test_empty_string(self) -> None:
        """Test escaping empty string."""
        result = escape_character_class("")
        assert result == ""
