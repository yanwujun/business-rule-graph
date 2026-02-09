"""Tree-sitter parsing coordinator."""

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

from tree_sitter_language_pack import get_language, get_parser

# Map file extensions to tree-sitter language names
EXTENSION_MAP = {
    ".vue": "vue",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".lua": "lua",
    ".zig": "zig",
    ".el": "elisp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    ".dart": "dart",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".css": "css",
    ".scss": "scss",
    ".html": "html",
    ".htm": "html",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".md": "markdown",
    ".sql": "sql",
    ".tf": "hcl",
    ".hcl": "hcl",
}

# Track parse error stats
parse_errors = {"no_grammar": 0, "parse_error": 0, "unreadable": 0}


def detect_language(file_path: str) -> str | None:
    """Detect the tree-sitter language name from a file path."""
    _, ext = os.path.splitext(file_path)
    return EXTENSION_MAP.get(ext)


def read_source(path: Path) -> bytes | None:
    """Read file bytes, trying utf-8 then latin-1."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        # Validate it's decodable text
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                raw.decode("latin-1")
            except UnicodeDecodeError:
                return None
        return raw
    except OSError:
        return None


def _preprocess_vue(source: bytes) -> tuple[bytes, str]:
    """Extract <script> blocks from a Vue SFC and return (processed_source, effective_language).

    Handles both <script> and <script setup> blocks.
    Preserves line numbers by replacing non-script regions with blank lines.
    """
    text = source.decode("utf-8", errors="replace")
    lines = text.split("\n")
    effective_lang = "javascript"

    # Find all <script...>...</script> regions
    script_pattern = re.compile(
        r'<script(\s[^>]*)?>.*?</script>',
        re.DOTALL,
    )

    # Track which lines belong to script blocks
    script_line_flags = [False] * len(lines)

    for match in script_pattern.finditer(text):
        attrs = match.group(1) or ""
        if 'lang="ts"' in attrs or "lang='ts'" in attrs or 'lang="tsx"' in attrs:
            effective_lang = "typescript"

        # Find the line range for the script content (excluding the tags)
        block_start = text[:match.start()].count("\n")
        block_end = text[:match.end()].count("\n")

        # Find the opening tag end line and closing tag start line
        inner_text = match.group(0)
        opening_tag_end = inner_text.index(">") + 1
        opening_lines = inner_text[:opening_tag_end].count("\n")
        closing_tag_start = inner_text.rfind("</script>")
        closing_lines = inner_text[:closing_tag_start].count("\n")

        content_start = block_start + opening_lines
        content_end = block_start + closing_lines

        for i in range(content_start, min(content_end + 1, len(lines))):
            script_line_flags[i] = True

    # Build output: keep script lines, blank out everything else
    output_lines = []
    for i, line in enumerate(lines):
        if script_line_flags[i]:
            output_lines.append(line)
        else:
            output_lines.append("")

    processed = "\n".join(output_lines)
    return processed.encode("utf-8"), effective_lang


def parse_file(path: Path, language: str | None = None):
    """Parse a file with tree-sitter and return (tree, source_bytes, language).

    Returns (None, None, None) if parsing fails.
    Failure categories:
    - no_grammar: language detected but no tree-sitter grammar available (expected skip)
    - parse_error: grammar exists but parsing failed (warning)
    - unreadable: file could not be read (error)
    """
    if language is None:
        language = detect_language(str(path))
    if language is None:
        return None, None, None  # Not a supported extension, expected skip

    source = read_source(path)
    if source is None:
        parse_errors["unreadable"] += 1
        log.warning("Unreadable file: %s", path)
        return None, None, None

    # Vue SFC: extract <script> blocks and route to TS/JS
    if language == "vue":
        source, language = _preprocess_vue(source)

    try:
        parser = get_parser(language)
    except Exception:
        parse_errors["no_grammar"] += 1
        return None, None, None  # Grammar not available, expected skip

    try:
        tree = parser.parse(source)
    except Exception as e:
        parse_errors["parse_error"] += 1
        log.warning("Parse error in %s: %s", path, e)
        return None, None, None

    return tree, source, language


def get_parse_error_summary() -> str:
    """Return a summary of parse errors for logging."""
    parts = []
    if parse_errors["unreadable"]:
        parts.append(f"{parse_errors['unreadable']} unreadable")
    if parse_errors["parse_error"]:
        parts.append(f"{parse_errors['parse_error']} parse errors")
    if parse_errors["no_grammar"]:
        parts.append(f"{parse_errors['no_grammar']} no grammar")
    return ", ".join(parts) if parts else ""
