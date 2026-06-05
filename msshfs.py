#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
msshfs — Mount SSHFS paths under ~/mnt/sshfs/<host>/<absolute-remote-path>

Examples:
  msshfs raspi4 repos/project
  msshfs mount raspi4 ~/repos/project
  msshfs umount raspi4 ~/repos/project
  msshfs path raspi4 /var/www
  msshfs status raspi4 /var/www
  msshfs list

Dependencies:
  sudo apt install sshfs python3-argcomplete

Install:
  install -Dm755 msshfs ~/.local/bin/msshfs

Enable Bash completion:
  mkdir -p ~/.local/share/bash-completion/completions
  register-python-argcomplete msshfs > ~/.local/share/bash-completion/completions/msshfs
  source ~/.local/share/bash-completion/completions/msshfs

Recommended SSH config for fast remote completion:
  Host *
      ControlMaster auto
      ControlPath ~/.ssh/control-%C
      ControlPersist 10m
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

try:
    import argcomplete
except ImportError:
    argcomplete = None  # type: ignore[assignment]


APP = "msshfs"
DEFAULT_BASE = Path.home() / "mnt" / "sshfs"
DEFAULT_REMOTE_PATH = "~"
SSH_TIMEOUT_SECONDS = 3
COMPLETE_TIMEOUT_SECONDS = 1

COMMANDS = {
    "mount",
    "umount",
    "list",
    "status",
    "path",
    "help",
}

COMMANDS_WITH_TARGET = {
    "mount",
    "umount",
    "status",
    "path",
}


REMOTE_RESOLVE_SCRIPT = r'''
set -euo pipefail

p="${1:-~}"

case "$p" in
  ""|"~")
    target="$HOME"
    ;;
  ~/*)
    target="$HOME/${p#~/}"
    ;;
  /*)
    target="$p"
    ;;
  *)
    target="$HOME/$p"
    ;;
esac

if command -v realpath >/dev/null 2>&1; then
  realpath -m -- "$target"
elif command -v readlink >/dev/null 2>&1; then
  readlink -m -- "$target"
else
  case "$target" in
    //*) printf "%s\n" "/${target##/}" ;;
    *) printf "%s\n" "$target" ;;
  esac
fi
'''


REMOTE_COMPLETE_SCRIPT = r'''
set -euo pipefail

p="${1:-}"

case "$p" in
  ""|"~")
    base="$HOME"
    prefix=""
    display_prefix=""
    ;;
  ~/*)
    raw="$HOME/${p#~/}"
    base="$(dirname -- "$raw")"
    prefix="$(basename -- "$raw")"
    display_prefix="$(dirname -- "$p")/"
    [[ "$display_prefix" == "./" ]] && display_prefix=""
    ;;
  /*)
    base="$(dirname -- "$p")"
    prefix="$(basename -- "$p")"
    display_prefix="$base/"
    [[ "$display_prefix" == "//" ]] && display_prefix="/"
    ;;
  *)
    raw="$HOME/$p"
    base="$(dirname -- "$raw")"
    prefix="$(basename -- "$raw")"
    display_prefix="$(dirname -- "$p")/"
    [[ "$display_prefix" == "./" ]] && display_prefix=""
    ;;
esac

[[ -d "$base" ]] || exit 0

find "$base" -mindepth 1 -maxdepth 1 -type d -name "$prefix*" -printf '%f/\n' 2>/dev/null \
  | LC_ALL=C sort \
  | sed "s#^#${display_prefix}#"
'''


@dataclass(frozen=True)
class Target:
    host: str
    input_path: str
    remote_path: PurePosixPath
    local_path: Path


class MsshfsError(RuntimeError):
    pass


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()

    if argcomplete is not None:
        argcomplete.autocomplete(parser)

    args = parser.parse_args(argv)
    command, host, remote_path = normalize_args(args)

    try:
        if command == "help":
            parser.print_help()
            return 0

        if command == "list":
            return cmd_list(args)

        if command == "mount":
            require_host(host)
            return cmd_mount(args, host, remote_path)

        if command == "umount":
            require_host(host)
            return cmd_umount(args, host, remote_path)

        if command == "path":
            require_host(host)
            return cmd_path(args, host, remote_path)

        if command == "status":
            require_host(host)
            return cmd_status(args, host, remote_path)

        raise MsshfsError(f"unknown command: {command}")

    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except MsshfsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Error: command failed: {format_cmd(exc.cmd)}", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return exc.returncode or 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP,
        description="Mount SSHFS paths below ~/mnt/sshfs/<host>/<remote-absolute-path>.",
    )

    parser.add_argument(
        "--base",
        default=str(DEFAULT_BASE),
        help=f"base mount directory; default: {DEFAULT_BASE}",
    ).completer = complete_local_dirs_for_argcomplete

    parser.add_argument(
        "--sshfs-option",
        "-o",
        action="append",
        default=[],
        metavar="OPT",
        help="extra sshfs -o option; may be repeated",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be done without mounting/unmounting",
    )

    parser.add_argument(
        "--open",
        action="store_true",
        help="open the local path with xdg-open after mounting",
    )

    parser.add_argument(
        "--print",
        action="store_true",
        help="print only the local path after mounting",
    )

    parser.add_argument(
        "--allow-non-empty",
        action="store_true",
        help="allow mounting over a non-empty directory",
    )

    parser.add_argument(
        "--lazy",
        "-z",
        action="store_true",
        help="lazy unmount via fusermount3 -uz",
    )

    first = parser.add_argument(
        "first",
        nargs="?",
        default="help",
        help="command or SSH host. Commands: mount, umount, list, status, path, help",
    )
    first.completer = complete_first_for_argcomplete

    rest = parser.add_argument(
        "rest",
        nargs="*",
        help="HOST [REMOTE_PATH] for commands, or [REMOTE_PATH] in short form",
    )
    rest.completer = complete_rest_for_argcomplete

    return parser


def normalize_args(args: argparse.Namespace) -> tuple[str, str | None, str]:
    first = args.first
    rest = list(args.rest or [])

    if first in COMMANDS:
        command = first

        if command in {"help", "list"}:
            return command, None, DEFAULT_REMOTE_PATH

        host = rest[0] if len(rest) >= 1 else None
        remote_path = rest[1] if len(rest) >= 2 else DEFAULT_REMOTE_PATH

        if len(rest) > 2:
            raise MsshfsError(f"too many arguments for {command!r}")

        return command, host, remote_path

    # Short form:
    #   msshfs HOST [REMOTE_PATH]
    command = "mount"
    host = first
    remote_path = rest[0] if len(rest) >= 1 else DEFAULT_REMOTE_PATH

    if len(rest) > 1:
        raise MsshfsError("too many arguments for short form; use: msshfs HOST [REMOTE_PATH]")

    return command, host, remote_path


def require_host(host: str | None) -> None:
    if not host:
        raise MsshfsError("missing SSH host")


def should_print_mount_path(args: argparse.Namespace) -> bool:
    return bool(args.print or not sys.stdout.isatty())


def cmd_mount(args: argparse.Namespace, host: str | None, remote_path: str) -> int:
    assert host is not None

    target = make_target(host, remote_path, Path(args.base).expanduser())
    print_path = should_print_mount_path(args)

    if is_mountpoint(target.local_path):
        if print_path:
            print(target.local_path)
        else:
            print(f"Already mounted: {target.local_path}")
        return 0

    ensure_mountpoint_dir(target.local_path, allow_non_empty=args.allow_non_empty)

    sshfs_options = default_sshfs_options() + list(args.sshfs_option or [])
    cmd = [
        "sshfs",
        f"{target.host}:{target.remote_path.as_posix()}",
        str(target.local_path),
    ]

    for opt in sshfs_options:
        cmd += ["-o", opt]

    if args.dry_run:
        print(format_cmd(cmd))
        return 0

    subprocess.run(cmd, check=True)

    if args.open:
        subprocess.Popen(
            ["xdg-open", str(target.local_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if print_path:
        print(target.local_path)
    else:
        print(f"Mounted: {target.host}:{target.remote_path} -> {target.local_path}")

    return 0


def cmd_umount(args: argparse.Namespace, host: str | None, remote_path: str) -> int:
    assert host is not None

    target = make_target(host, remote_path, Path(args.base).expanduser())

    if not is_mountpoint(target.local_path):
        print(f"Not mounted: {target.local_path}")
        return 0

    fusermount = find_executable(["fusermount3", "fusermount"])

    if fusermount:
        cmd = [fusermount, "-u"]
        if args.lazy:
            cmd[-1] = "-uz"
        cmd.append(str(target.local_path))
    else:
        cmd = ["umount", str(target.local_path)]

    if args.dry_run:
        print(format_cmd(cmd))
        return 0

    subprocess.run(cmd, check=True)
    print(f"Unmounted: {target.local_path}")
    return 0


def cmd_path(args: argparse.Namespace, host: str | None, remote_path: str) -> int:
    assert host is not None

    target = make_target(host, remote_path, Path(args.base).expanduser())
    print(target.local_path)
    return 0


def cmd_status(args: argparse.Namespace, host: str | None, remote_path: str) -> int:
    assert host is not None

    target = make_target(host, remote_path, Path(args.base).expanduser())
    mounted = is_mountpoint(target.local_path)
    state = "mounted" if mounted else "not mounted"
    print(f"{state}: {target.local_path}")
    return 0 if mounted else 1


def cmd_list(args: argparse.Namespace) -> int:
    base = Path(args.base).expanduser()
    mounts = list_msshfs_mounts(base)

    if not mounts:
        print(f"No active msshfs mounts below {base}")
        return 0

    for mount in mounts:
        print(mount)

    return 0


def make_target(host: str, input_path: str, base: Path) -> Target:
    remote_path = resolve_remote_path(host, input_path)
    local_path = local_path_for(base, host, remote_path)
    return Target(
        host=host,
        input_path=input_path,
        remote_path=remote_path,
        local_path=local_path,
    )


def resolve_remote_path(host: str, input_path: str) -> PurePosixPath:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
        host,
        "bash",
        "-s",
        "--",
        input_path,
    ]

    proc = subprocess.run(
        cmd,
        input=REMOTE_RESOLVE_SCRIPT,
        text=True,
        capture_output=True,
        check=False,
    )

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise MsshfsError(f"could not resolve remote path on {host!r}{detail}")

    output = proc.stdout.strip().splitlines()

    if not output:
        raise MsshfsError(f"empty remote path returned by {host!r}")

    path = output[-1].strip()

    if not path.startswith("/"):
        raise MsshfsError(f"remote path is not absolute: {path!r}")

    return PurePosixPath(path)


def local_path_for(base: Path, host: str, remote_path: PurePosixPath) -> Path:
    safe_host = safe_host_segment(host)
    parts = [p for p in remote_path.parts if p != "/"]
    return base / safe_host / Path(*parts) if parts else base / safe_host


def safe_host_segment(host: str) -> str:
    return host.replace("/", "%2F")


def ensure_mountpoint_dir(path: Path, *, allow_non_empty: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)

    if allow_non_empty:
        return

    try:
        next(path.iterdir())
    except StopIteration:
        return
    except FileNotFoundError:
        path.mkdir(parents=True, exist_ok=True)
        return

    raise MsshfsError(f"local mountpoint exists and is not empty: {path}")


def default_sshfs_options() -> list[str]:
    return [
        "reconnect",
        "ServerAliveInterval=15",
        "ServerAliveCountMax=3",
    ]


def is_mountpoint(path: Path) -> bool:
    return subprocess.run(
        ["mountpoint", "-q", str(path)],
        check=False,
    ).returncode == 0


def list_msshfs_mounts(base: Path) -> list[str]:
    proc = subprocess.run(
        ["findmnt", "-rn", "-o", "TARGET,FSTYPE,SOURCE"],
        text=True,
        capture_output=True,
        check=False,
    )

    if proc.returncode != 0:
        return []

    base_str = str(base)
    out: list[str] = []

    for line in proc.stdout.splitlines():
        if not line.startswith(base_str):
            continue

        fields = line.split(maxsplit=2)

        if len(fields) < 2:
            continue

        fstype = fields[1]
        source = fields[2] if len(fields) > 2 else ""

        if "fuse.sshfs" in fstype or source.startswith("sshfs") or ":/" in source:
            out.append(line)

    return out


def find_executable(names: Iterable[str]) -> str | None:
    for name in names:
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

    return None


def format_cmd(cmd: Sequence[str] | str) -> str:
    if isinstance(cmd, str):
        return cmd

    return " ".join(shlex.quote(str(x)) for x in cmd)


# -----------------------------
# argcomplete completers
# -----------------------------

def complete_first_for_argcomplete(
    prefix: str,
    parsed_args: argparse.Namespace,
    **kwargs,
) -> list[str]:
    return prefix_filter(sorted(COMMANDS | set(complete_hosts(""))), prefix)


def complete_rest_for_argcomplete(
    prefix: str,
    parsed_args: argparse.Namespace,
    **kwargs,
) -> list[str]:
    first = getattr(parsed_args, "first", None)
    rest = list(getattr(parsed_args, "rest", []) or [])

    if not first:
        return []

    # Explicit command form:
    #   msshfs mount HOST PATH
    #   msshfs umount HOST PATH
    #   msshfs status HOST PATH
    #   msshfs path HOST PATH
    if first in COMMANDS_WITH_TARGET:
        if len(rest) == 0:
            return complete_hosts(prefix)

        host = rest[0]

        if len(rest) == 1:
            if first == "umount":
                mounted = complete_mounted_remote_paths(host, prefix)
                if mounted:
                    return mounted
            return complete_remote_dirs(host, prefix)

        return []

    # Short form:
    #   msshfs HOST PATH
    if first not in COMMANDS:
        host = first

        if len(rest) == 0:
            return complete_remote_dirs(host, prefix)

        return []

    return []


def complete_local_dirs_for_argcomplete(
    prefix: str,
    parsed_args: argparse.Namespace,
    **kwargs,
) -> list[str]:
    return complete_local_dirs(prefix)


def prefix_filter(items: Iterable[str], prefix: str) -> list[str]:
    return sorted(x for x in items if x.startswith(prefix))


def complete_hosts(prefix: str) -> list[str]:
    hosts = hosts_from_bash_completion(prefix)

    if not hosts:
        hosts = set()
        hosts.update(hosts_from_known_hosts(Path.home() / ".ssh" / "known_hosts"))

    return prefix_filter(hosts, prefix)


def hosts_from_bash_completion(prefix: str) -> set[str]:
    hosts: set[str] = set()

    bash = find_executable(["bash"])
    completion = next(
        (
            path
            for path in (
                "/usr/share/bash-completion/bash_completion",
                "/etc/bash_completion",
            )
            if Path(path).is_file()
        ),
        None,
    )

    if not bash or not completion:
        return hosts

    try:
        proc = subprocess.run(
            [
                bash,
                "-lc",
                (
                    "source \"$1\" >/dev/null 2>&1 || exit 0; "
                    "_comp_compgen_known_hosts__impl -a -- \"$2\" >/dev/null 2>&1 || true; "
                    "printf '%s\\n' \"${known_hosts[@]}\""
                ),
                APP,
                completion,
                prefix,
            ],
            text=True,
            capture_output=True,
            timeout=COMPLETE_TIMEOUT_SECONDS + 1,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return hosts

    if proc.returncode != 0:
        return hosts

    for line in proc.stdout.splitlines():
        line = line.strip()

        if line:
            hosts.add(line)

    return hosts


def hosts_from_known_hosts(path: Path) -> set[str]:
    hosts: set[str] = set()

    if not path.exists():
        return hosts

    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return hosts

    for line in lines:
        if not line or line.startswith("#") or line.startswith("|"):
            continue

        first = line.split(maxsplit=1)[0]

        for host in first.split(","):
            host = host.strip()

            if not host or host.startswith("|"):
                continue

            bracket = re.match(r"^\[([^\]]+)\]:(\d+)$", host)

            if bracket:
                host = bracket.group(1)

            if host and not host.startswith("|"):
                hosts.add(host)

    return hosts


def complete_remote_dirs(host: str, prefix: str) -> list[str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={COMPLETE_TIMEOUT_SECONDS}",
        host,
        "bash",
        "-s",
        "--",
        prefix,
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=REMOTE_COMPLETE_SCRIPT,
            text=True,
            capture_output=True,
            timeout=COMPLETE_TIMEOUT_SECONDS + 1,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if proc.returncode != 0:
        return []

    return proc.stdout.splitlines()


def complete_local_dirs(prefix: str) -> list[str]:
    expanded = os.path.expanduser(prefix)
    base = Path(expanded if expanded else ".")

    if prefix.endswith("/"):
        directory = base
        name_prefix = ""
        display_prefix = prefix
    else:
        directory = base.parent if str(base.parent) else Path(".")
        name_prefix = base.name
        display_prefix = prefix[: len(prefix) - len(name_prefix)]

    try:
        entries = sorted(
            p for p in directory.iterdir()
            if p.is_dir() and p.name.startswith(name_prefix)
        )
    except OSError:
        return []

    return [f"{display_prefix}{p.name}/" for p in entries]


def complete_mounted_remote_paths(host: str, prefix: str) -> list[str]:
    host_dir = DEFAULT_BASE / safe_host_segment(host)

    if not host_dir.exists():
        return []

    results: list[str] = []

    for line in list_msshfs_mounts(DEFAULT_BASE):
        target = line.split(maxsplit=1)[0]

        try:
            rel = Path(target).relative_to(host_dir)
        except ValueError:
            continue

        remote = "/" + rel.as_posix()

        if remote.startswith(prefix):
            results.append(remote)

    return sorted(results)


if __name__ == "__main__":
    raise SystemExit(run())