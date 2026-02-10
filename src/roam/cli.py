"""Click CLI entry point with lazy-loaded subcommands."""

import os
import sys

# Fix Unicode output on Windows consoles (cp1253, cp1252, etc.)
if sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click


# Lazy-loading command group: imports command modules only when invoked.
# This avoids importing networkx (~500ms) on every CLI call.
_COMMANDS = {
    "index":    ("roam.commands.cmd_index",    "index"),
    "map":      ("roam.commands.cmd_map",      "map_cmd"),
    "module":   ("roam.commands.cmd_module",   "module"),
    "file":     ("roam.commands.cmd_file",     "file_cmd"),
    "symbol":   ("roam.commands.cmd_symbol",   "symbol"),
    "trace":    ("roam.commands.cmd_trace",    "trace"),
    "deps":     ("roam.commands.cmd_deps",     "deps"),
    "health":   ("roam.commands.cmd_health",   "health"),
    "clusters": ("roam.commands.cmd_clusters", "clusters"),
    "layers":   ("roam.commands.cmd_layers",   "layers"),
    "weather":  ("roam.commands.cmd_weather",  "weather"),
    "dead":     ("roam.commands.cmd_dead",     "dead"),
    "search":   ("roam.commands.cmd_search",   "search"),
    "grep":     ("roam.commands.cmd_grep",     "grep_cmd"),
    "uses":     ("roam.commands.cmd_uses",     "uses"),
    "impact":   ("roam.commands.cmd_impact",   "impact"),
    "owner":    ("roam.commands.cmd_owner",    "owner"),
    "coupling": ("roam.commands.cmd_coupling", "coupling"),
    "fan":      ("roam.commands.cmd_fan",      "fan"),
    "diff":     ("roam.commands.cmd_diff",     "diff_cmd"),
    "describe": ("roam.commands.cmd_describe", "describe"),
    "test-map": ("roam.commands.cmd_testmap",  "test_map"),
    "sketch":   ("roam.commands.cmd_sketch",   "sketch"),
}


class LazyGroup(click.Group):
    """A Click group that lazy-loads command modules on first access."""

    def list_commands(self, ctx):
        return sorted(_COMMANDS.keys())

    def get_command(self, ctx, cmd_name):
        if cmd_name not in _COMMANDS:
            return None
        module_path, attr_name = _COMMANDS[cmd_name]
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)


@click.group(cls=LazyGroup)
@click.version_option(package_name="roam-code")
@click.option('--json', 'json_mode', is_flag=True, help='Output in JSON format')
@click.pass_context
def cli(ctx, json_mode):
    """Roam: Codebase comprehension tool."""
    ctx.ensure_object(dict)
    ctx.obj['json'] = json_mode
