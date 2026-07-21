"""多根工作区支持

解析 VS Code .code-workspace 文件，支持 --workspace 显式指定 + 自动发现。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceProject:
    """工作区中的一个项目"""
    name: str                      # 目录名（如 "xcj-trade"）
    root: Path                     # 绝对路径
    db_path: Path                  # .roam/index.db 路径
    has_index: bool = False        # 是否已 roam init
    workspace_name: str = ""       # 所属工作区文件名


def parse_workspace(ws_path: str | Path) -> list[WorkspaceProject]:
    """解析 .code-workspace 文件 → 项目列表

    Args:
        ws_path: .code-workspace 文件路径

    Returns:
        WorkspaceProject 列表，每个元素对应 folders 中一个项目

    Raises:
        ValueError: JSON 解析失败或格式错误
    """
    ws_path = Path(ws_path).resolve()
    if not ws_path.exists():
        raise ValueError(f"Workspace file not found: {ws_path}")

    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid workspace JSON: {ws_path}: {e}")

    folders = data.get("folders", [])
    if not isinstance(folders, list):
        raise ValueError(f"Invalid workspace format: 'folders' must be a list")

    ws_dir = ws_path.parent
    ws_name = ws_path.stem
    projects: list[WorkspaceProject] = []

    for item in folders:
        if not isinstance(item, dict):
            continue
        rel_path = item.get("path", "")
        if not rel_path:
            continue

        root = (ws_dir / rel_path).resolve()
        db_path = root / ".roam" / "index.db"
        has_index = db_path.exists()
        name = root.name or rel_path.rstrip("/").split("/")[-1]

        projects.append(WorkspaceProject(
            name=name,
            root=root,
            db_path=db_path,
            has_index=has_index,
            workspace_name=ws_name,
        ))

    logger.info("Parsed workspace %s: %d projects", ws_name, len(projects))
    return projects


def discover_workspace(start_dir: str | Path = ".") -> Path | None:
    """从 start_dir 向上搜索 *.code-workspace 文件

    搜索策略:
    - 从 start_dir 开始，逐级向上
    - 每个目录中 glob *.code-workspace
    - 找到第一个匹配文件立即返回
    - 直到根目录仍未找到则返回 None

    Args:
        start_dir: 起始搜索目录

    Returns:
        找到的工作区文件绝对路径，或 None
    """
    current = Path(start_dir).resolve()
    if current.is_file():
        current = current.parent

    while True:
        candidates = sorted(current.glob("*.code-workspace"))
        if candidates:
            logger.info("Auto-discovered workspace: %s", candidates[0])
            return candidates[0]

        parent = current.parent
        if parent == current:  # 到达根目录
            break
        current = parent

    return None


def resolve_workspace(
    workspace_path: str | None = None,
    start_dir: str | Path = ".",
) -> list[WorkspaceProject]:
    """统一入口: 解析工作区项目列表

    优先级:
    1. workspace_path 显式指定 → 直接解析
    2. 自动发现 → 找到恰好 1 个工作区文件则使用
    3. 降级 → 返回空列表（调者按单项目模式处理）

    Args:
        workspace_path: 显式指定的 .code-workspace 路径
        start_dir: 自动发现时的起始目录

    Returns:
        项目列表，空列表表示"无工作区，降级为单项目模式"
    """
    # 显式指定
    if workspace_path:
        return parse_workspace(workspace_path)

    # 自动发现
    found = discover_workspace(start_dir)
    if found:
        return parse_workspace(found)

    # 降级
    return []
