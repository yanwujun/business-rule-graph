"""Import and call resolution into graph edges."""

import os


def resolve_references(
    references: list[dict],
    symbols_by_name: dict[str, list[dict]],
    files_by_path: dict[str, int],
) -> list[dict]:
    """Resolve references to concrete symbol edges.

    Args:
        references: List of reference dicts with source_name, target_name, kind, line.
        symbols_by_name: Mapping from symbol name -> list of symbol dicts
            (each with at least 'id', 'file_id', 'file_path', 'qualified_name').
        files_by_path: Mapping from file path -> file_id.

    Returns:
        List of edge dicts with source_id, target_id, kind, line.
    """
    # Build a lookup: qualified_name -> symbol for exact matches
    symbols_by_qualified = {}
    for name, sym_list in symbols_by_name.items():
        for sym in sym_list:
            qn = sym.get("qualified_name")
            if qn:
                symbols_by_qualified[qn] = sym

    # Build fallback map: file_path -> sorted list of symbols for line-based lookup
    # Used when source_name is None/empty (top-level code, e.g. Vue <script setup>)
    _file_symbols: dict[str, list[dict]] = {}
    for sym_list in symbols_by_name.values():
        for sym in sym_list:
            fp = sym.get("file_path", "")
            if fp:
                _file_symbols.setdefault(fp, []).append(sym)
    # Sort each file's symbols by line_start for binary-search-style lookup
    for fp in _file_symbols:
        _file_symbols[fp].sort(key=lambda s: s.get("line_start") or 0)

    # Also index source symbols by name for finding the caller
    edges = []
    seen = set()

    for ref in references:
        source_name = ref.get("source_name", "")
        target_name = ref.get("target_name", "")
        kind = ref.get("kind", "call")
        line = ref.get("line")
        source_file = ref.get("source_file", "")

        if not target_name:
            continue

        # Find source symbol (the caller)
        source_sym = _best_match(source_name, source_file, symbols_by_name)
        if source_sym is None:
            # Fallback for top-level code (e.g. Vue <script setup>, Python module scope):
            # pick the closest symbol at or before the reference line
            source_sym = _closest_symbol(source_file, line, _file_symbols)
        if source_sym is None:
            continue

        # Find target symbol
        # 1. Try qualified name exact match
        target_sym = symbols_by_qualified.get(target_name)
        # 2. Try by simple name with disambiguation
        if target_sym is None:
            target_sym = _best_match(target_name, source_file, symbols_by_name, ref_kind=kind)

        if target_sym is None:
            continue

        source_id = source_sym["id"]
        target_id = target_sym["id"]

        if source_id == target_id:
            continue

        edge_key = (source_id, target_id, kind)
        if edge_key in seen:
            continue
        seen.add(edge_key)

        edges.append({
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "line": line,
        })

    return edges


def _best_match(name: str, source_file: str, symbols_by_name: dict, ref_kind: str = "") -> dict | None:
    """Find the best matching symbol for a name, preferring locality."""
    candidates = symbols_by_name.get(name, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # For call references with an uppercase name, prefer class (constructor call pattern)
    if ref_kind == "call" and name and name[0].isupper():
        class_candidates = [c for c in candidates if c.get("kind") == "class"]
        if class_candidates:
            for sym in class_candidates:
                if sym.get("file_path") == source_file:
                    return sym
            source_dir = os.path.dirname(source_file) if source_file else ""
            for sym in class_candidates:
                if os.path.dirname(sym.get("file_path", "")) == source_dir:
                    return sym
            return class_candidates[0]

    # Prefer same file
    for sym in candidates:
        if sym.get("file_path") == source_file:
            return sym

    # Prefer same directory
    source_dir = os.path.dirname(source_file) if source_file else ""
    for sym in candidates:
        sym_dir = os.path.dirname(sym.get("file_path", ""))
        if sym_dir == source_dir:
            return sym

    # Fall back to first candidate
    return candidates[0]


def _closest_symbol(
    source_file: str,
    ref_line: int | None,
    file_symbols: dict[str, list[dict]],
) -> dict | None:
    """Find the closest symbol at or before ref_line in the same file.

    Falls back to the first symbol in the file if ref_line is None or
    no symbol precedes the reference.
    """
    syms = file_symbols.get(source_file)
    if not syms:
        return None
    if ref_line is None:
        return syms[0]
    # Find the last symbol whose line_start <= ref_line
    best = syms[0]
    for sym in syms:
        if (sym.get("line_start") or 0) <= ref_line:
            best = sym
        else:
            break
    return best


def build_file_edges(
    symbol_edges: list[dict],
    symbols: dict[int, dict],
) -> list[dict]:
    """Aggregate symbol-level edges into file-level edges.

    Args:
        symbol_edges: List of edge dicts with source_id, target_id.
        symbols: Mapping from symbol_id -> symbol dict (with 'file_id').

    Returns:
        List of file edge dicts with source_file_id, target_file_id, kind, symbol_count.
    """
    file_edge_counts: dict[tuple[int, int], int] = {}

    for edge in symbol_edges:
        src_sym = symbols.get(edge["source_id"])
        tgt_sym = symbols.get(edge["target_id"])
        if src_sym is None or tgt_sym is None:
            continue

        src_fid = src_sym["file_id"]
        tgt_fid = tgt_sym["file_id"]
        if src_fid == tgt_fid:
            continue

        key = (src_fid, tgt_fid)
        file_edge_counts[key] = file_edge_counts.get(key, 0) + 1

    return [
        {
            "source_file_id": src,
            "target_file_id": tgt,
            "kind": "imports",
            "symbol_count": count,
        }
        for (src, tgt), count in file_edge_counts.items()
    ]
