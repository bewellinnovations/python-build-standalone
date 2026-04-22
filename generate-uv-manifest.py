# /// script
# requires-python = ">=3.11"
# ///
"""
Generate a uv-compatible download-metadata.json from a GitHub release's SHA256SUMS file.

Reads SHA256SUMS from stdin (or a file path arg) and writes JSON to stdout.
Each line of SHA256SUMS is: <sha256>  <filename>

Usage:
    gh release download <tag> -p SHA256SUMS -O - | uv run generate-uv-manifest.py <tag> <repo>
"""

from __future__ import annotations

import json
import re
import sys
from urllib.parse import quote

# Matches install_only_stripped filenames:
#   cpython-3.8.20+20260422-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
#   cpython-3.10.20+20260422-x86_64-unknown-linux-gnu-pgo+lto-install_only_stripped.tar.gz
FILENAME_RE = re.compile(
    r"""(?x)
    ^
        cpython-
        (?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)
        (?P<prerelease>(?:a|b|rc)\d+)?
        \+(?P<build>\d+)-
        (?P<arch>[a-z\d_]+)-
        (?P<vendor>[a-z\d]+)-
        (?P<sys>[a-z\d]+)-
        (?:(?P<build_opts>[^-]+)-)?
        install_only_stripped\.tar\.gz
    $
    """
)

TRIPLE_TO_UV = {
    # (sys, arch, vendor) -> (os, arch_family, arch_variant, libc)
    ("linux", "x86_64",  None):        ("linux",  "x86_64",  None,   "gnu"),
    ("linux", "x86_64",  "gnu"):       ("linux",  "x86_64",  None,   "gnu"),
    ("linux", "x86_64",  "musl"):      ("linux",  "x86_64",  None,   "musl"),
    ("linux", "aarch64", "gnu"):       ("linux",  "aarch64", None,   "gnu"),
    ("linux", "aarch64", "musl"):      ("linux",  "aarch64", None,   "musl"),
    ("darwin", "x86_64", None):        ("darwin", "x86_64",  None,   "none"),
    ("darwin", "aarch64", None):       ("darwin", "aarch64", None,   "none"),
    ("windows", "x86_64", "msvc"):     ("windows","x86_64",  None,   "none"),
    ("windows", "x86_64", "gnu"):      ("windows","x86_64",  None,   "none"),
}


def triple_to_uv(arch: str, vendor: str, sys_: str) -> tuple[str, str, str | None, str]:
    # Try exact match first, then with libc stripped from sys
    libc = None
    base_sys = sys_
    if sys_.startswith("linux"):
        base_sys = "linux"
        if vendor in ("gnu", "musl"):
            libc = vendor
        elif sys_.endswith("gnu"):
            libc = "gnu"
        elif sys_.endswith("musl"):
            libc = "musl"
        else:
            libc = "gnu"

    os_map = {
        "linux": "linux",
        "darwin": "darwin",
        "windows": "windows",
    }
    os_ = os_map.get(base_sys, base_sys)

    arch_family = arch
    arch_variant = None
    if "_v2" in arch:
        arch_family = arch.replace("_v2", "")
        arch_variant = "v2"
    elif "_v3" in arch:
        arch_family = arch.replace("_v3", "")
        arch_variant = "v3"
    elif "_v4" in arch:
        arch_family = arch.replace("_v4", "")
        arch_variant = "v4"

    if libc is None:
        libc = "none"

    return os_, arch_family, arch_variant, libc


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <release-tag> <owner/repo>", file=sys.stderr)
        sys.exit(1)

    tag = sys.argv[1]
    repo = sys.argv[2]
    url_prefix = f"https://github.com/{repo}/releases/download/{tag}/"

    manifest: dict[str, object] = {}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        sha256, filename = line.split(maxsplit=1)
        filename = filename.lstrip("*")

        m = FILENAME_RE.match(filename)
        if m is None:
            continue

        major = int(m.group("major"))
        minor = int(m.group("minor"))
        patch = int(m.group("patch"))
        prerelease = m.group("prerelease") or ""
        build = m.group("build")
        arch = m.group("arch")
        vendor = m.group("vendor")
        sys_ = m.group("sys")
        build_opts = m.group("build_opts")  # e.g. "pgo+lto", or None

        os_, arch_family, arch_variant, libc = triple_to_uv(arch, vendor, sys_)

        # uv variant is only for freethreaded/debug, not pgo+lto
        uv_variant = None
        if build_opts:
            parts = set(build_opts.split("+"))
            if "freethreaded" in parts:
                uv_variant = "freethreaded+debug" if "debug" in parts else "freethreaded"
            elif "debug" in parts:
                uv_variant = "debug"

        # Key format matches uv's download-metadata.json
        key_parts = [f"cpython-{major}.{minor}.{patch}"]
        if prerelease:
            key_parts[0] += prerelease
        if uv_variant:
            key_parts[0] += f"+{uv_variant}"
        key_parts += [os_, f"{arch_family}{'_' + arch_variant if arch_variant else ''}", libc]
        key = "-".join(key_parts)

        manifest[key] = {
            "name": "cpython",
            "arch": {
                "family": arch_family,
                "variant": arch_variant,
            },
            "os": os_,
            "libc": libc,
            "major": major,
            "minor": minor,
            "patch": patch,
            "prerelease": prerelease,
            "url": url_prefix + quote(filename, safe=""),
            "sha256": sha256,
            "variant": uv_variant,
            "build": build,
        }

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
