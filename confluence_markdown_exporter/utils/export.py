import hashlib
import json
import logging
import re
from pathlib import Path

from confluence_markdown_exporter.utils.app_data_store import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
export_options = settings.export


def parse_encode_setting(encode_setting: str) -> dict[str, str]:
    """Parse encoding setting containing character mapping.

    Args:
        encode_setting: JSON object content without braces
            '"char1":"replacement1","char2":"replacement2"'

    Returns:
        Dictionary mapping characters to their replacements

    Examples:
        "" -> {}
        '" ":"%2D","-":"%2D"' -> {" ": "%2D", "-": "%2D"}
        '" ":"dash","-":"%2D"' -> {" ": "dash", "-": "%2D"}
        '"=":" equals "' -> {"=": " equals "}

    Note:
        Uses JSON format for mapping to handle all characters unambiguously.
        Curly braces are added automatically before parsing.
    """
    if not encode_setting:
        return {}

    # Add curly braces to make it valid JSON
    json_str = f"{{{encode_setting}}}"

    # Use JSON parsing for robust and unambiguous parsing
    try:
        mapping = json.loads(json_str)
        if isinstance(mapping, dict):
            return mapping
    except (json.JSONDecodeError, TypeError):
        # Fallback: if parsing fails, return empty mapping
        pass

    return {}


def save_file(file_path: Path, content: str | bytes) -> None:
    """Save content to a file, creating parent directories as needed."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        with file_path.open("wb") as file:
            file.write(content)
    elif isinstance(content, str):
        with file_path.open("w", encoding="utf-8") as file:
            file.write(content)
    else:
        msg = "Content must be either a string or bytes."
        raise TypeError(msg)
    logger.debug("Saved file %s (%d bytes)", file_path, len(content))


# A truncated name keeps a marker plus this many hex characters of a digest of the FULL name,
# so two titles differing only after the cut still land on distinct paths.
TRUNCATION_MARKER = "~"
TRUNCATION_DIGEST_CHARS = 8
# `%2D` and friends come from `export.filename_encoding`; cutting inside one leaves a dangling
# `%` or `%2` that no longer decodes.
DANGLING_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]?$")
# A UTF-8 continuation byte matches 0b10xxxxxx, i.e. `byte & 0xC0 == 0x80`.
UTF8_CONTINUATION_MASK = 0xC0
UTF8_CONTINUATION_PREFIX = 0x80
# A trailing dot-group longer than this is page-title text, not a file extension.
MAX_EXTENSION_BYTES = 16


def _cut_to_bytes(name: str, max_bytes: int) -> str:
    """Return the longest prefix of `name` whose UTF-8 encoding fits `max_bytes`.

    Examples:
        _cut_to_bytes("abc", 2) -> "ab"
        _cut_to_bytes("\u0430\u0431", 3) -> "\u0430"
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    # Walk back off any continuation byte to the start of the straddled character.
    cut = max_bytes
    while cut > 0 and (encoded[cut] & UTF8_CONTINUATION_MASK) == UTF8_CONTINUATION_PREFIX:
        cut -= 1
    return encoded[:cut].decode("utf-8")


def truncate_to_bytes(name: str, max_bytes: int) -> str:
    """Shorten one path segment so its UTF-8 encoding fits `max_bytes`.

    Linux caps a path segment at 255 BYTES, so a character count is the wrong ruler for a
    non-ASCII title: 255 Cyrillic characters are 510 bytes and the file cannot be created at
    all. macOS APFS and NTFS cap at 255 CHARACTERS, which is why such names survive locally
    and fail only on Linux -- inside `actions/checkout`, for one.

    A name that already fits comes back unchanged, byte for byte. A name that does not is cut
    on a character boundary, never inside a percent-escape, and gets `~<8 hex>` of a digest of
    the full name appended.

    Examples:
        truncate_to_bytes("report.md", 255) -> "report.md"
        truncate_to_bytes("\u0430" * 200, 255) -> 246 bytes of "\u0430" plus "~<8 hex>"
    """
    if len(name.encode("utf-8")) <= max_bytes:
        return name

    digest = hashlib.blake2b(
        name.encode("utf-8"), digest_size=TRUNCATION_DIGEST_CHARS // 2
    ).hexdigest()
    suffix = f"{TRUNCATION_MARKER}{digest}"
    budget = max_bytes - len(suffix)
    if budget < 1:
        # No room for the marker: fall back to a plain byte cut on a character boundary.
        return _cut_to_bytes(name, max_bytes)

    head = DANGLING_PERCENT_ESCAPE.sub("", _cut_to_bytes(name, budget)).rstrip(" .")
    return f"{head}{suffix}"


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename for cross-platform compatibility.

    Replaces characters based on encoding mapping, trims trailing spaces and dots, and
    prevents reserved names. Length is NOT capped here: the caller substitutes this into a
    path template that may append an extension, so the cap belongs to the rendered segment
    and is applied by `cap_path_segments`.

    Args:
        filename: The original filename.

    Returns:
        A sanitized filename string.
    """
    sanitized = filename

    # Strip control characters (ASCII 0x00-0x1F, 0x7F) invalid on Windows/Linux
    sanitized = re.sub(r"[\x00-\x1f\x7f]", "", sanitized)

    if export_options.filename_encoding:
        encode_map = parse_encode_setting(export_options.filename_encoding)

        # Create pattern from all characters that have mappings
        if encode_map:
            chars_to_encode = "".join(encode_map.keys())
            encode_re = escape_character_class(chars_to_encode)
            encode_pattern = re.compile(f"[{encode_re}]")

            def map_char(m: re.Match[str]) -> str:
                char = m.group(0)
                return encode_map[char]

            sanitized = re.sub(encode_pattern, map_char, sanitized)

    # Trim spaces and dots from the end
    sanitized = sanitized.rstrip(" .")

    # Reserved Windows names (case-insensitive)
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }

    name = Path(sanitized).stem.upper()
    if name in reserved:
        sanitized = f"{sanitized}_"

    if export_options.filename_lowercase:
        sanitized = sanitized.lower()

    return sanitized


def cap_path_segment(segment: str, max_bytes: int) -> str:
    """Cap one rendered path segment at `max_bytes`, keeping its file extension.

    The extension is what makes this different from `truncate_to_bytes`: a page path template
    ends in `.md`, and a Markdown mirror whose long pages lost their extension is not a
    Markdown mirror. A trailing dot-group counts as an extension only when it is short and
    alphanumeric, so a title ending in `... воспроизведения.)` is not mistaken for one.

    Examples:
        cap_path_segment("note.md", 255) -> "note.md"
        cap_path_segment("\u0430" * 200 + ".md", 255) -> 243 bytes of "\u0430" plus "~<8 hex>.md"
    """
    if len(segment.encode("utf-8")) <= max_bytes:
        return segment

    stem, dot, extension = segment.rpartition(".")
    extension_bytes = len(f"{dot}{extension}".encode())
    if not stem or not dot or not extension.isalnum() or extension_bytes > MAX_EXTENSION_BYTES:
        return truncate_to_bytes(segment, max_bytes)
    return f"{truncate_to_bytes(stem, max_bytes - extension_bytes)}{dot}{extension}"


def cap_path_segments(path: Path) -> Path:
    """Cap every segment of an already-rendered export path at `export.filename_length` bytes.

    Applied once, to the FINAL path, so each segment's digest is taken over that segment's
    whole name. Capping the title instead would hash a name the cap had already cut, and two
    pages differing only past the cut would collide on one file.
    """
    return Path(
        *(cap_path_segment(part, export_options.filename_length) for part in path.parts)
    )


def sanitize_key(s: str, connector: str = "_") -> str:
    """Convert an input string to a valid Python/YAML-compatible key.

    - Lowercase the string.
    - Replace non-alphanumeric characters with underscores.
    - Collapse multiple underscores into one.
    - Trim leading/trailing underscores.
    - Prefix with 'key_' if the first character is not a letter or underscore.
    """
    s = s.lower()
    s = re.sub(f"[^a-z0-9{connector}]", connector, s)
    s = re.sub(f"{connector}+", connector, s)
    s = s.strip(connector)
    if not re.match(r"^[a-z]", s):
        s = f"key{connector}{s}"
    return s


def github_heading_slug(text: str) -> str:
    """Generate a GitHub-compatible heading anchor slug.

    Matches the github-slugger algorithm used by GitHub to render heading anchors,
    so that generated TOC links resolve correctly in GitHub-rendered Markdown.
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)  # drop punctuation; keep letters, digits, spaces, hyphens
    text = re.sub(r"[\s_]+", "-", text)   # whitespace/underscores → hyphens
    return re.sub(r"-{2,}", "-", text)    # collapse runs of hyphens (e.g. "- word" → "-word")


def escape_character_class(s: str) -> str:
    """Escape characters for use in a regex character class.

    Args:
        s: The string containing characters to escape.

    Returns:
        The input string with special regex character class characters escaped.
    """
    # Escape backslash first, then other special characters for character classes
    return s.replace("\\", r"\\").replace("-", r"\-").replace("]", r"\]").replace("^", r"\^")
