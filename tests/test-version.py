#!/usr/bin/env python3
"""One version number, read by everything.

Before this, the version was written down in three places and they had
already drifted: the installer said 1.1.2, the Inno container said 1.1.2,
and the compiled host still said 1.1.1 — so the Apps & features entry and
the exe's own file properties disagreed about what was installed. Nothing
catches that; it is three literals that have to be edited together and
silently do not have to match.

Now there is a `VERSION` file at the repo root and four consumers read it:

  * `installer/Install.ps1`  — Apps & features entry, setup welcome page
  * `build/Frivo.iss`        — the Inno container's own version
  * `build/Build-Installer.ps1` — generates the assembly attributes
  * `app/app.py`             — what /diagnose reports

This checks each of them resolves to the same string, and that none of them
has quietly grown a literal again.

Usage:  python3 tests/test-version.py     (run from the repo root)
Needs:  pwsh or powershell for the PowerShell halves.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PATH = os.path.join(ROOT, "VERSION")

failures = []


def check(name, condition, got=None):
    print(("  PASS  " if condition else "  FAIL  ") + name
          + ("" if condition else "   got=%s" % (got,)))
    if not condition:
        failures.append(name)


def find_powershell():
    for name in ("pwsh", "powershell.exe", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_powershell(shell, script):
    result = subprocess.run([shell, "-NoProfile", "-Command", script],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return "ERROR: " + (result.stdout + result.stderr).strip()
    return result.stdout.strip()


def extract(path, start_marker, end_marker):
    with open(path, encoding="utf-8-sig") as handle:
        text = handle.read()
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def main():
    print("--- the file itself ---")
    check("VERSION exists at the repo root", os.path.exists(VERSION_PATH), VERSION_PATH)
    if not os.path.exists(VERSION_PATH):
        return 1

    raw = open(VERSION_PATH, "rb").read()
    version = raw.decode("utf-8-sig").strip()
    check("it holds a version number", bool(re.match(r"^\d+(\.\d+){1,3}$", version)), version)
    # Inno's preprocessor reads this file as plain text. A BOM would end up
    # inside the version string and produce an installer with a mangled
    # name, so it must not be written with one.
    check("and no byte-order mark, which Inno would read as part of it",
          not raw.startswith(b"\xef\xbb\xbf"), "BOM present")

    print()
    print("--- nobody kept a private copy ---")
    # The exact failure this replaces: literals that must be edited together
    # and silently do not have to.
    literal = re.compile(r"\b\d+\.\d+\.\d+(\.\d+)?\b")
    # Comment markers per language, because they differ in the way that
    # matters here: `#` starts a comment in PowerShell but starts the
    # *preprocessor* in an .iss file — which is exactly where a version
    # literal would live. Treating them the same made this scan pass over
    # a reintroduced literal without noticing.
    comment_markers = {
        ".ps1": ("#",),
        ".iss": (";",),
        ".cs": ("//",),
    }
    for name in ("installer/Install.ps1", "build/Frivo.iss", "build/FrivoHost.cs"):
        path = os.path.join(ROOT, *name.split("/"))
        markers = comment_markers[os.path.splitext(path)[1]]
        with open(path, encoding="utf-8-sig") as handle:
            body = "\n".join(
                line for line in handle.read().splitlines()
                if not line.lstrip().startswith(markers)
            )
        found = [m.group(0) for m in literal.finditer(body)
                 if m.group(0) not in ("10.0",)]      # MinVersion=10.0 is Windows
        check("%s has no version literal" % name, not found, found)

    check("Frivo.iss reads the VERSION file",
          "FileRead" in open(os.path.join(ROOT, "build", "Frivo.iss"), encoding="utf-8").read(),
          "no FileRead")

    print()
    print("--- app.py ---")
    # Exercised with a fake __file__ so both layouts are covered: the repo,
    # where VERSION sits one level above app/, and an install, where app.py
    # and VERSION are side by side.
    source = extract(os.path.join(ROOT, "app", "app.py"),
                     "def app_version():", "APP_VERSION = app_version()")
    workspace = tempfile.mkdtemp(prefix="frivo-version-")

    def app_version_at(app_dir, version_dir):
        os.makedirs(app_dir, exist_ok=True)
        os.makedirs(version_dir, exist_ok=True)
        with open(os.path.join(version_dir, "VERSION"), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")
        namespace = {"os": os, "__file__": os.path.join(app_dir, "app.py")}
        exec(source, namespace)
        return namespace["app_version"]()

    installed = os.path.join(workspace, "installed")
    check("finds it beside app.py, the way it is installed",
          app_version_at(installed, installed) == version, "mismatch")

    repo = os.path.join(workspace, "repo")
    check("finds it one level up, the way the repo is laid out",
          app_version_at(os.path.join(repo, "app"), repo) == version, "mismatch")

    empty = os.path.join(workspace, "empty", "app")
    os.makedirs(empty, exist_ok=True)
    namespace = {"os": os, "__file__": os.path.join(empty, "app.py")}
    exec(source, namespace)
    check("says unknown rather than crashing when it is missing",
          namespace["app_version"]() == "unknown", namespace["app_version"]())

    shell = find_powershell()
    if shell is None:
        print()
        print("SKIP: no PowerShell; the installer and build halves were not run.")
    else:
        print()
        print("--- installer/Install.ps1 ---")
        install_fn = extract(os.path.join(ROOT, "installer", "Install.ps1"),
                             "function Get-FrivoVersion {", "$AppVersion = Get-FrivoVersion")
        # Planted two levels up, which is where the setup payload keeps it
        # relative to installer\Install.ps1.
        payload = os.path.join(workspace, "payload")
        os.makedirs(os.path.join(payload, "installer"), exist_ok=True)
        with open(os.path.join(payload, "VERSION"), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")
        # Written to a real script at the path Install.ps1 occupies, and
        # run as a file. The function locates VERSION relative to
        # $PSCommandPath, which only has a real value when a real script is
        # running — faking it in -Command tests nothing.
        def probe_at(directory):
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, "probe.ps1")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write(install_fn + "\nGet-FrivoVersion\n")
            result = subprocess.run([shell, "-NoProfile", "-File", probe],
                                    capture_output=True, text=True)
            return result.stdout.strip()

        check("reads it from the setup payload",
              probe_at(os.path.join(payload, "installer")) == version,
              probe_at(os.path.join(payload, "installer")))

        # The repo layout too: Install.bat runs installer\Install.ps1 with
        # VERSION at the root, one level up.
        repo_like = os.path.join(workspace, "repo-like")
        os.makedirs(repo_like, exist_ok=True)
        with open(os.path.join(repo_like, "VERSION"), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")
        check("and from the repo, the way Install.bat runs it",
              probe_at(os.path.join(repo_like, "installer")) == version,
              probe_at(os.path.join(repo_like, "installer")))

        check("falls back to unknown instead of failing the install",
              probe_at(os.path.join(workspace, "nopayload", "installer")) == "unknown",
              probe_at(os.path.join(workspace, "nopayload", "installer")))

        print()
        print("--- build/Build-Installer.ps1 ---")
        build_fns = extract(os.path.join(ROOT, "build", "Build-Installer.ps1"),
                            "function Get-FrivoVersion {", "function Build-FrivoHost {")
        build_dir = os.path.join(workspace, "build-ok", "build")
        os.makedirs(build_dir, exist_ok=True)
        with open(os.path.join(workspace, "build-ok", "VERSION"), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")
        prelude = "$here = '%s'; %s; " % (build_dir.replace("'", "''"), build_fns)
        got = run_powershell(shell, prelude + "Get-FrivoVersion")
        check("the build script reads the same file", got == version, got)

        # csc and Inno both reject a malformed version with errors that say
        # nothing about this file, so it is rejected here instead.
        with open(os.path.join(workspace, "build-ok", "VERSION"), "w", encoding="utf-8") as handle:
            handle.write("next-release\n")
        got = run_powershell(shell, prelude + "Get-FrivoVersion")
        check("and refuses a version that is not a number", got.startswith("ERROR"), got)
        with open(os.path.join(workspace, "build-ok", "VERSION"), "w", encoding="utf-8") as handle:
            handle.write(version + "\n")

        generated = os.path.join(workspace, "Version.generated.cs")
        run_powershell(shell, prelude + (
            "New-FrivoVersionSource -Version '%s' -Path '%s'"
            % (version, generated.replace("'", "''"))
        ))
        attributes = ""
        if os.path.exists(generated):
            attributes = open(generated, encoding="utf-8-sig").read()
        padded = ".".join((version.split(".") + ["0", "0", "0"])[:4])
        check("the assembly attributes are generated", bool(attributes), "no file")
        check("padded to the four parts .NET wants",
              'AssemblyFileVersion("%s")' % padded in attributes, attributes.strip())
        check("and the unpadded version is kept as the informational one",
              'AssemblyInformationalVersion("%s")' % version in attributes, attributes.strip())

    shutil.rmtree(workspace, ignore_errors=True)

    print()
    if failures:
        print("%d failure(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("Every consumer agrees on %s." % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
