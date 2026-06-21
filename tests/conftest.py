"""Pytest configuration — inject .venv/bin into PATH so integration tests
find the `mdnotes` entry point via subprocess."""
import os

# Ensure .venv/bin is in PATH for subprocess calls in integration tests
_venv_bin = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin")
if _venv_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _venv_bin + os.pathsep + os.environ.get("PATH", "")
