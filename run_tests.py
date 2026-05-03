#!/usr/bin/env python
"""Test runner that uses the venv Python executable."""
import subprocess
import sys

def run_tests():
    result = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'dashboard_app/tests', '-v'],
        cwd='D:\\projects\\Gemini_EG4_app',
        capture_output=True,
        text=True
    )
    print(result.stdout)
    print(result.stderr)
    return result.returncode

if __name__ == '__main__':
    sys.exit(run_tests())