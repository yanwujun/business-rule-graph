"""Shared test fixtures and helpers for roam tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


def roam(*args, cwd=None):
    """Run a roam CLI command and return (output, returncode)."""
    result = subprocess.run(
        [sys.executable, "-m", "roam"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return result.stdout + result.stderr, result.returncode


def git_init(path):
    """Initialize a git repo, add all files, and commit."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


def git_commit(path, msg="update"):
    """Stage all and commit."""
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=path, capture_output=True)
