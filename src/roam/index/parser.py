"""Tree-sitter parsing coordinator."""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

from tree_sitter_language_pack import get_language, get_parser

# Map file extensions to tree-sitter language names
EXTENSION_MAP = {
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
