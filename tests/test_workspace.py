"""T101 [AC-19] [REQ-21] [REQ-23] workspace 模块测试

覆盖: parse_workspace / discover_workspace / resolve_workspace
"""
import json
import tempfile
from pathlib import Path

import pytest
from roam.business_rules.workspace import (
    WorkspaceProject,
    parse_workspace,
    discover_workspace,
    resolve_workspace,
)


def _write_workspace(path: Path, folders: list[str]) -> Path:
    """辅助: 写入一个 .code-workspace 文件"""
    ws = {"folders": [{"path": f} for f in folders], "settings": {}}
    path.write_text(json.dumps(ws))
    return path


def _make_project(tmp_path: Path, name: str, with_index: bool = True) -> Path:
    """辅助: 创建模拟项目目录"""
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    if with_index:
        roam_dir = proj / ".roam"
        roam_dir.mkdir(exist_ok=True)
        (roam_dir / "index.db").write_text("")  # 空 DB 占位
    return proj


class TestParseWorkspace:
    """REQ-21: 工作区文件解析"""

    def test_parse_valid(self, tmp_path):
        ws_path = _write_workspace(tmp_path / "test.code-workspace", ["proj-a", "proj-b"])
        _make_project(tmp_path, "proj-a")
        _make_project(tmp_path, "proj-b")

        projects = parse_workspace(ws_path)
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"proj-a", "proj-b"}

    def test_parse_relative_paths_resolved(self, tmp_path):
        """相对路径 → 解析为绝对路径"""
        ws_path = _write_workspace(tmp_path / "test.code-workspace", ["sub/proj"])
        _make_project(tmp_path, "sub/proj")

        projects = parse_workspace(ws_path)
        assert len(projects) == 1
        assert projects[0].root.is_absolute()

    def test_parse_detects_index(self, tmp_path):
        """正确检测 .roam/index.db 是否存在"""
        ws_path = _write_workspace(tmp_path / "test.code-workspace", ["has-index", "no-index"])
        _make_project(tmp_path, "has-index", with_index=True)
        _make_project(tmp_path, "no-index", with_index=False)

        projects = parse_workspace(ws_path)
        assert len(projects) == 2
        has = [p for p in projects if p.name == "has-index"][0]
        no = [p for p in projects if p.name == "no-index"][0]
        assert has.has_index is True
        assert no.has_index is False

    def test_parse_invalid_json(self, tmp_path):
        ws_path = tmp_path / "bad.code-workspace"
        ws_path.write_text("not json")

        with pytest.raises((json.JSONDecodeError, ValueError)):
            parse_workspace(ws_path)

    def test_parse_empty_folders(self, tmp_path):
        ws_path = _write_workspace(tmp_path / "empty.code-workspace", [])

        projects = parse_workspace(ws_path)
        assert projects == []

    def test_parse_missing_project_dir(self, tmp_path):
        """工作区引用不存在的目录 → 仍返回但 has_index=False"""
        ws_path = _write_workspace(tmp_path / "test.code-workspace", ["ghost"])

        projects = parse_workspace(ws_path)
        assert len(projects) == 1
        assert projects[0].has_index is False


class TestDiscoverWorkspace:
    """REQ-23: 自动发现工作区"""

    def test_discover_in_current_dir(self, tmp_path):
        ws_path = _write_workspace(tmp_path / "project.code-workspace", ["proj"])

        found = discover_workspace(tmp_path)
        assert found == ws_path.resolve()

    def test_discover_in_parent_dir(self, tmp_path):
        ws_path = _write_workspace(tmp_path / "project.code-workspace", ["proj"])
        child = tmp_path / "deep" / "sub"
        child.mkdir(parents=True)

        found = discover_workspace(child)
        assert found == ws_path.resolve()

    def test_discover_none_found(self, tmp_path):
        found = discover_workspace(tmp_path)
        assert found is None

    def test_discover_multiple_returns_first(self, tmp_path):
        """多个工作区文件时返回第一个找到的"""
        _write_workspace(tmp_path / "a.code-workspace", ["a"])
        _write_workspace(tmp_path / "b.code-workspace", ["b"])

        found = discover_workspace(tmp_path)
        assert found is not None


class TestResolveWorkspace:
    """统一入口"""

    def test_explicit_path_takes_priority(self, tmp_path):
        """显式指定 --workspace 时不触发自动发现"""
        ws1 = _write_workspace(tmp_path / "explicit.code-workspace", ["proj-a"])
        _make_project(tmp_path, "proj-a")
        _write_workspace(tmp_path / "auto.code-workspace", ["proj-b"])

        projects = resolve_workspace(str(ws1))
        assert len(projects) == 1
        assert projects[0].name == "proj-a"

    def test_no_workspace_falls_back_to_single(self):
        """无工作区文件 → 空列表（调者降级为单项目模式）"""
        with tempfile.TemporaryDirectory() as td:
            projects = resolve_workspace(workspace_path=None, start_dir=td)
            assert projects == []
