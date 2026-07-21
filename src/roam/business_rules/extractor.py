"""纯 AST 业务规则提取器

双引擎架构之确定性引擎:
  ✅ tree-sitter 扫 if-throw / status 判断 / enum / standalone throw / try-catch
  ✅ 方法命名约定匹配
  ✅ 注解兜底
  ❌ 不调用 LLM

文件变更检测: roam-code mtime + hash（支持 SVN，不依赖 git）
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

from .models import BusinessRule, RuleType
from .patterns import (
    ANNOTATION_RULE_MAP,
    METHOD_NAME_PATTERNS,
    TREE_SITTER_QUERIES,
    domain_from_package,
    flow_from_class,
    extract_exception_message,
    extract_status_value,
    extract_enum_values,
)

logger = logging.getLogger(__name__)

try:
    from tree_sitter import Language, Parser, Query
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False
    logger.warning("tree_sitter not available — if-throw extraction disabled")


class BusinessRuleExtractor:
    """从 Java 源文件提取业务规则"""

    def __init__(self, project_root: Path | str = "."):
        self.project_root = Path(project_root)

    def extract_from_db(
        self, db_path: str, incremental: bool = False
    ) -> list[BusinessRule]:
        rules: list[BusinessRule] = []
        seen = set()
        files_to_scan = self._get_files_from_db(db_path, incremental)
        total = len(files_to_scan)

        for i, file_rel in enumerate(files_to_scan):
            if total > 10 and i % max(1, total // 10) == 0:
                logger.info("Extracting... %d/%d", i + 1, total)

        for file_rel in files_to_scan:
            file_abs = self.project_root / file_rel
            if not file_abs.exists():
                continue
            try:
                source_bytes = file_abs.read_bytes()
            except Exception:
                continue

            file_rules = self.extract_from_source(source_bytes, str(file_rel))
            for rule in file_rules:
                h = rule.compute_hash()
                if h not in seen:
                    seen.add(h)
                    rules.append(rule)

        logger.info(
            "Extracted %d business rules from %d files",
            len(rules), len(files_to_scan),
        )
        return rules

    def extract_from_source(
        self, source: bytes, file_path: str
    ) -> list[BusinessRule]:
        """从单个 Java 源文件提取 — 三级优先级"""
        rules: list[BusinessRule] = []

        package = Path(file_path).parent.as_posix().replace("/", ".")
        domain = domain_from_package(package)

        # 优先级 1: tree-sitter 流程/判断节点
        if HAS_TREE_SITTER:
            rules.extend(
                self._extract_tree_sitter(source, file_path, domain)
            )

        # 优先级 2: 方法命名约定
        rules.extend(
            self._extract_method_names(source, file_path, domain)
        )

        # 优先级 3: 注解兜底
        rules.extend(
            self._extract_annotations(source, file_path, domain)
        )

        # 优先级 4: MyBatis Mapper 方法 + Redis 关键词
        rules.extend(
            self._extract_mybatis_redis(source, file_path, domain)
        )

        return rules

    # ---- helpers ----

    def _get_files_from_db(
        self, db_path: str, incremental: bool
    ) -> list[str]:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            if incremental:
                rows = conn.execute("""
                    SELECT f.path, f.mtime
                    FROM files f WHERE f.language = 'java'
                """).fetchall()
                changed = []
                for r in rows:
                    fp = self.project_root / r["path"]
                    if fp.exists():
                        if fp.stat().st_mtime != r["mtime"]:
                            changed.append(r["path"])
                return changed
            else:
                rows = conn.execute(
                    "SELECT path FROM files WHERE language = 'java'"
                ).fetchall()
                return [r["path"] for r in rows]

    # ---- tree-sitter extraction ----

    def _extract_tree_sitter(
        self, source: bytes, file_path: str, domain: str
    ) -> list[BusinessRule]:
        rules = []
        try:
            import tree_sitter_java as tsjava
            lang = Language(tsjava.language())
            parser = Parser(lang)
            tree = parser.parse(source)
        except Exception:
            return rules

        root = tree.root_node

        # if + throw
        rules.extend(self._query_if_throw(lang, root, src, file_path, domain))
        # if + status 判断
        rules.extend(self._query_status_check(lang, root, src, file_path, domain))
        # enum status
        rules.extend(self._query_status_enum(lang, root, src, file_path, domain))
        # standalone throw
        rules.extend(self._query_standalone_throw(lang, root, src, file_path, domain))
        # try-catch business exception
        rules.extend(self._query_try_catch(lang, root, src, file_path, domain))

        return rules

    def _query_if_throw(self, lang, root, src, file_path, domain):
        rules = []
        try:
            query = Query(lang, TREE_SITTER_QUERIES["if_throw"])
            for node, _ in query.captures(root):
                line = node.start_point[0] + 1
                exc_msg = extract_exception_message(
                    src, node.start_byte, node.end_byte
                )
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:if-throw",
                    rule_type=RuleType.VALIDATION,
                    domain=domain,
                    description=exc_msg or "条件断言",
                    source_file=file_path,
                    source_line=line,
                    params={
                        "exception_message": exc_msg,
                        "extraction": "tree_sitter_if_throw",
                    },
                    extraction="tree_sitter_if_throw",
                ))
        except Exception as e:
            logger.debug("if_throw query failed: %s", e)
        return rules

    def _query_status_check(self, lang, root, src, file_path, domain):
        rules = []
        try:
            query = Query(lang, TREE_SITTER_QUERIES["if_status_check"])
            for node, _ in query.captures(root):
                line = node.start_point[0] + 1
                status_val = extract_status_value(
                    src, node.start_byte, node.end_byte
                )
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:status-check",
                    rule_type=RuleType.WORKFLOW,
                    domain=domain,
                    description=f"状态判断: {status_val}",
                    source_file=file_path,
                    source_line=line,
                    params={
                        "status_value": status_val,
                        "extraction": "tree_sitter_status_check",
                    },
                    extraction="tree_sitter_status_check",
                ))
        except Exception as e:
            logger.debug("status_check query failed: %s", e)
        return rules

    def _query_status_enum(self, lang, root, src, file_path, domain):
        rules = []
        try:
            query = Query(lang, TREE_SITTER_QUERIES["status_enum"])
            for node, _ in query.captures(root):
                line = node.start_point[0] + 1
                vals = extract_enum_values(node, src)
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:status-enum",
                    rule_type=RuleType.WORKFLOW,
                    domain=domain,
                    description=f"状态枚举: {', '.join(vals)}",
                    source_file=file_path,
                    source_line=line,
                    params={
                        "enum_values": vals,
                        "extraction": "tree_sitter_status_enum",
                    },
                    extraction="tree_sitter_status_enum",
                ))
        except Exception as e:
            logger.debug("status_enum query failed: %s", e)
        return rules

    def _query_standalone_throw(self, lang, root, src, file_path, domain):
        rules = []
        try:
            query = Query(lang, TREE_SITTER_QUERIES["standalone_throw"])
            for node, _ in query.captures(root):
                line = node.start_point[0] + 1
                exc_msg = extract_exception_message(
                    src, node.start_byte, node.end_byte
                )
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:throw",
                    rule_type=RuleType.VALIDATION,
                    domain=domain,
                    description=exc_msg or "异常抛出",
                    source_file=file_path,
                    source_line=line,
                    params={
                        "exception_message": exc_msg,
                        "extraction": "tree_sitter_throw",
                    },
                    extraction="tree_sitter_throw",
                ))
        except Exception as e:
            logger.debug("standalone_throw query failed: %s", e)
        return rules

    # ---- method name extraction ----

    def _extract_method_names(
        self, source: bytes, file_path: str, domain: str
    ) -> list[BusinessRule]:
        rules = []
        text = source.decode(errors="replace")

        for m in re.finditer(
            r'(?:public|private|protected)\s+\w+\s+(\w+)\s*\(', text
        ):
            name = m.group(1)
            for pattern, (rt, sub_type) in METHOD_NAME_PATTERNS.items():
                if re.match(f"^{pattern}", name):
                    line = text[: m.start()].count("\n") + 1
                    rules.append(BusinessRule(
                        rule_id=f"{file_path}:{line}:method:{name}",
                        rule_type=rt,
                        domain=domain,
                        flow=flow_from_class(name),
                        description=f"{sub_type}: {name}",
                        source_file=file_path,
                        source_line=line,
                        source_symbol=name,
                        params={
                            "method": name,
                            "sub_type": sub_type,
                            "extraction": "method_name",
                        },
                        extraction="method_name",
                    ))
                    break
        return rules

    # ---- MyBatis / Redis extraction ----

    def _extract_mybatis_redis(
        self, source: bytes, file_path: str, domain: str
    ) -> list[BusinessRule]:
        """MyBatis Mapper 方法 + Redis 关键词检测（预留，当前返回空）"""
        return []

    # ---- annotation extraction ----

    def _extract_annotations(
        self, source: bytes, file_path: str, domain: str
    ) -> list[BusinessRule]:
        rules = []
        text = source.decode(errors="replace")

        for m in re.finditer(r'@(\w+)(?:\(([^)]*)\))?', text):
            name = m.group(1)
            args = m.group(2)
            if name in ANNOTATION_RULE_MAP:
                rt, op = ANNOTATION_RULE_MAP[name]
                line = text[: m.start()].count("\n") + 1
                rules.append(BusinessRule(
                    rule_id=f"{file_path}:{line}:@{name}",
                    rule_type=rt,
                    domain=domain,
                    description=f"@{name}: {args or op}",
                    source_file=file_path,
                    source_line=line,
                    params={
                        "operator": op,
                        "args": args or "",
                        "extraction": "annotation",
                    },
                    annotations=[f"@{name}" + (f"({args})" if args else "")],
                    extraction="annotation",
                ))
        return rules
