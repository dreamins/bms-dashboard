#!/usr/bin/env python
"""Test runner that uses the venv Python executable."""
import os
import subprocess
import sys

def run_tests():
    repo_root = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.join(repo_root, 'dashboard_app')
    venv_python = os.path.join(repo_root, '.venv', 'Scripts', 'python.exe')
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable
    result = subprocess.run(
        [python_exe, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        cwd=app_dir,
        capture_output=True,
        text=True
    )
    print(result.stdout)
    print(result.stderr)
    return result.returncode

if __name__ == '__main__':
    sys.exit(run_tests())