"""Build packages and a Windows executable into a fresh output directory."""

from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parent

    def run(*args):
        subprocess.run([sys.executable, *args], cwd=root, check=True)

    try:
        run("-m", "unittest", "discover", "-s", "tests", "-v")
        dist = root / "dist"
        dist.mkdir(exist_ok=True)
        prefix = "build-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-"
        output = Path(tempfile.mkdtemp(prefix=prefix, dir=dist))
        print("Build output: {}".format(output), flush=True)
        run("-m", "build", "--outdir", str(output))
        run("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
            "--name", "SharedClipboard", "--distpath", str(output),
            "--workpath", str(root / "build" / "pyinstaller"),
            "--specpath", str(root / "build"), str(root / "shared_clipboard.py"))
        executable = output / ("SharedClipboard.exe" if sys.platform == "win32" else "SharedClipboard")
        subprocess.run([str(executable), "--help"], cwd=root, check=True)
        print("\nBuild complete: {}".format(executable), flush=True)
        print('Run "{}" to start the app and open the browser.'.format(executable), flush=True)
        return 0
    except subprocess.CalledProcessError as error:
        print("Build failed. Review the command output above.", file=sys.stderr)
        return error.returncode
    except OSError as error:
        print("Build failed: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
