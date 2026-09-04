#!/usr/bin/env python3
import argparse
import os
import pathlib
import shutil
import subprocess
import sys

SANDBOX_HOME = pathlib.Path.home() / ".config" / "sandbox-code"
CONFIG_DIR = SANDBOX_HOME / "opencode-config"
DATA_DIR = SANDBOX_HOME / "opencode-data"
SSH_DIR = pathlib.Path.home() / ".ssh"
GH_DIR = pathlib.Path.home() / ".config" / "gh"

API_KEY_VARS = [
    "DEEPSEEK_API_KEY",
    "ZAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OPENCODE_API_KEY",
]


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    CAGED_CONF = os.path.join(script_dir, "caged-networks.conf")

    parser = argparse.ArgumentParser(
        description="Start sandbox-code Docker container with OpenCode"
    )
    parser.add_argument(
        "-w", "--workspace",
        default=os.getcwd(),
        help="Directory to mount as /workspace (default: current directory)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print OpenCode version and exit",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all persistent data before starting",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force a full rebuild without Docker layer cache",
    )
    parser.add_argument(
        "--bash",
        action="store_true",
        help="Start with an interactive bash shell instead of opencode",
    )
    parser.add_argument(
        "--ssh",
        action="store_true",
        help="Mount ~/.ssh into the container (read-only)",
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Mount ~/.ssh (read-only) and ~/.config/gh (writable)",
    )
    parser.add_argument(
        "--x11",
        action="store_true",
        help="Mount X11 socket for clipboard support (enables copy/paste)",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Disable all networking (--network none)",
    )
    parser.add_argument(
        "--network",
        type=str,
        default=None,
        help="Docker network to use (default: bridge)",
    )
    parser.add_argument(
        "--caged",
        action="store_true",
        help="Isolate from local network & Tailscale, keep internet access",
    )
    parser.add_argument(
        "--clean-rules",
        action="store_true",
        help="Remove firewall rules created by --caged",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run inside the container (default: opencode .)",
    )

    CAGED_CONF = os.path.join(script_dir, "caged-networks.conf")

    args = parser.parse_args()

    if args.clean_rules:
        _clean_caged_rules(CAGED_CONF)
        return

    if args.caged and args.no_network:
        parser.error("--caged and --no-network are mutually exclusive")
    if args.caged and args.network:
        parser.error("--caged and --network are mutually exclusive")
    if args.no_network and args.network:
        parser.error("--no-network and --network are mutually exclusive")

    if args.version:
        subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "opencode",
             "sandbox-code:latest", "--version"],
            env=os.environ,
            check=True,
        )
        return

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if command == ["."]:
        command = []

    if args.reset:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _project_root = pathlib.Path(script_dir)
    for name in ("opencode.jsonc", "tui.json"):
        dst = CONFIG_DIR / name
        if not dst.exists():
            src = _project_root / name
            if src.exists():
                shutil.copy2(src, dst)

    build_cmd = ["docker", "build", "-t", "sandbox-code:latest"]
    if args.no_cache:
        build_cmd.append("--no-cache")
    build_cmd.append(script_dir)

    subprocess.run(build_cmd, env=os.environ, check=True)

    workspace = os.path.abspath(args.workspace)

    run_mode = ["-it"] if sys.stdin.isatty() else ["-i"]

    docker_cmd = [
        "docker", "run", "--rm",
        *run_mode,
        "--hostname", "sandbox-code",
        "--name", "sandbox-code",
        "-v", f"{workspace}:/workspace",
        "-v", f"{CONFIG_DIR}:/home/ubuntu/.config/opencode",
        "-v", f"{DATA_DIR}:/home/ubuntu/.local/share/opencode",
        "-e", "HOME=/home/ubuntu",
        "-e", f'TERM={os.environ.get("TERM", "xterm-256color")}',
        "-e", f'LANG={os.environ.get("LANG", "C.UTF-8")}',
        "-e", f'LC_ALL={os.environ.get("LC_ALL", "C.UTF-8")}',
        "-w", "/workspace",
    ]

    # X11 support for clipboard
    if args.x11:
        # Pass DISPLAY environment variable
        if "DISPLAY" in os.environ:
            docker_cmd.extend(["-e", f'DISPLAY={os.environ["DISPLAY"]}'])
            docker_cmd.extend(["-v", "/tmp/.X11-unix:/tmp/.X11-unix"])
            print("[INFO] X11 support enabled (DISPLAY={})".format(os.environ["DISPLAY"]))
        else:
            print("[WARNING] --x11 requested but DISPLAY not set in environment", file=sys.stderr)
        
        # Also try to detect and pass XAUTHORITY if available
        if "XAUTHORITY" in os.environ:
            docker_cmd.extend(["-e", f'XAUTHORITY={os.environ["XAUTHORITY"]}'])
            docker_cmd.extend(["-v", f'{os.environ["XAUTHORITY"]}:{os.environ["XAUTHORITY"]}'])
        
        # Additional common Xauthority location
        xauth_path = pathlib.Path.home() / ".Xauthority"
        if xauth_path.exists():
            docker_cmd.extend(["-v", f"{xauth_path}:/home/ubuntu/.Xauthority:ro"])
            docker_cmd.extend(["-e", "XAUTHORITY=/home/ubuntu/.Xauthority"])

        # Wayland support (if using Wayland with XWayland)
        if "WAYLAND_DISPLAY" in os.environ:
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
            wayland_display = os.environ["WAYLAND_DISPLAY"]
            docker_cmd.extend(["-e", f'WAYLAND_DISPLAY={wayland_display}'])
            docker_cmd.extend(["-v", f"{runtime_dir}/{wayland_display}:/tmp/{wayland_display}"])
            docker_cmd.extend(["-e", "XDG_RUNTIME_DIR=/tmp"])
            print("[INFO] Wayland socket mounted for XWayland support")

    # --- Network isolation ---
    caged_network, caged_subnet, caged_cidrs = _load_caged_config(CAGED_CONF)

    if args.no_network:
        docker_cmd.extend(["--network", "none"])
    elif args.caged:
        result = subprocess.run(
            ["docker", "network", "inspect", caged_network],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            subprocess.run(
                ["docker", "network", "create", "-d", "bridge",
                 "--subnet", caged_subnet, caged_network],
                check=True,
            )
            print(f"[INFO] Created Docker network '{caged_network}'")

        _add_caged_rules(caged_network, caged_cidrs)

        docker_cmd.extend(["--network", caged_network])
        docker_cmd.extend(["--dns", "1.1.1.1", "--dns", "8.8.8.8"])
    elif args.network:
        docker_cmd.extend(["--network", args.network])

    mounts = set()

    def add_mount(src, dst, readonly=True):
        if dst not in mounts:
            if readonly:
                docker_cmd.extend(["-v", f"{src}:{dst}:ro"])
            else:
                docker_cmd.extend(["-v", f"{src}:{dst}"])
            mounts.add(dst)

    if args.github:
        if GH_DIR.is_dir():
            add_mount(GH_DIR, "/home/ubuntu/.config/gh", readonly=False)
        if SSH_DIR.is_dir():
            add_mount(SSH_DIR, "/home/ubuntu/.ssh")

    if args.ssh and not args.github:
        if SSH_DIR.is_dir():
            add_mount(SSH_DIR, "/home/ubuntu/.ssh")

    for var in API_KEY_VARS:
        if var in os.environ:
            docker_cmd.extend(["-e", var])

    docker_cmd.append("sandbox-code:latest")

    if command:
        docker_cmd.extend(["-c", " ".join(command)])
    elif args.bash:
        pass
    else:
        docker_cmd.extend(["-c", "opencode ."])

    subprocess.run(["docker", "rm", "-f", "sandbox-code"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        subprocess.run(docker_cmd, env=os.environ, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


def _bridge_iface(network):
    result = subprocess.run(
        ["docker", "network", "inspect", network,
         "--format", "{{index .Options \"com.docker.network.bridge.name\"}}"],
        capture_output=True, text=True, check=True,
    )
    iface = result.stdout.strip()
    if iface:
        return iface
    result = subprocess.run(
        ["docker", "network", "inspect", network,
         "--format", "{{.Id}}"],
        capture_output=True, text=True, check=True,
    )
    return f"br-{result.stdout.strip()[:12]}"


def _nft_available():
    return shutil.which("nft") is not None


def _iptables_available():
    return shutil.which("iptables") is not None


def _add_rules_iptables(bridge_iface, cidrs):
    ok = True
    for chain in ("DOCKER-USER", "INPUT"):
        for cidr in cidrs:
            check = subprocess.run(
                ["sudo", "iptables", "-C", chain,
                 "-i", bridge_iface, "-d", cidr, "-j", "DROP"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if check.returncode != 0:
                rc = subprocess.run(
                    ["sudo", "iptables", "-I", chain, "1",
                     "-i", bridge_iface, "-d", cidr, "-j", "DROP",
                     "-m", "comment", "--comment", "sandbox-code-caged"],
                ).returncode
                if rc != 0:
                    ok = False
    return ok


def _add_rules_nft(bridge_iface, cidrs):
    table = "inet sandbox-code-caged"
    subprocess.run(["sudo", "nft", "add", "table", table],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    for hook in ("forward", "input"):
        chain_hook = f"{hook}_caged"
        subprocess.run(["sudo", "nft", "add", "chain", table, chain_hook,
                        f"{{ type filter hook {hook} priority 0; }}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for cidr in cidrs:
            rc = subprocess.run(
                ["sudo", "nft", "add", "rule", table, chain_hook,
                 f"iifname {bridge_iface} ip daddr {cidr} drop"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode
            if rc != 0:
                ok = False
    return ok


def _add_caged_rules(network, cidrs):
    try:
        iface = _bridge_iface(network)
    except subprocess.CalledProcessError:
        print(f"[ERROR] Cannot inspect network '{network}'", file=sys.stderr)
        return

    if _iptables_available():
        if _add_rules_iptables(iface, cidrs):
            return
        if _nft_available():
            print("[INFO] iptables failed, falling back to nftables")
            if _add_rules_nft(iface, cidrs):
                return

    if _nft_available():
        if _add_rules_nft(iface, cidrs):
            return

    print("[WARNING] Could not apply firewall rules (sudo failed).", file=sys.stderr)
    print("          Add these rules manually to isolate the network:", file=sys.stderr)
    if _iptables_available():
        for cidr in cidrs:
            print(f"          sudo iptables -I DOCKER-USER 1 -i {iface} -d {cidr} -j DROP", file=sys.stderr)
            print(f"          sudo iptables -I INPUT 1 -i {iface} -d {cidr} -j DROP", file=sys.stderr)
    elif _nft_available():
        for cidr in cidrs:
            print(f"          sudo nft add rule inet sandbox-code-caged forward_caged iifname {iface} ip daddr {cidr} drop", file=sys.stderr)
            print(f"          sudo nft add rule inet sandbox-code-caged input_caged iifname {iface} ip daddr {cidr} drop", file=sys.stderr)
    else:
        for cidr in cidrs:
            print(f"          (no firewall tool found, block manually: interface={iface} dst={cidr})", file=sys.stderr)


def _clean_rules_iptables(network, cidrs):
    try:
        iface = _bridge_iface(network)
    except subprocess.CalledProcessError:
        print(f"[INFO] Network '{network}' not found, nothing to clean")
        return
    for chain in ("DOCKER-USER", "INPUT"):
        for cidr in cidrs:
            subprocess.run(
                ["sudo", "iptables", "-D", chain,
                 "-i", iface, "-d", cidr, "-j", "DROP",
                 "-m", "comment", "--comment", "sandbox-code-caged"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )


def _clean_rules_nft():
    subprocess.run(["sudo", "nft", "delete", "table", "inet", "sandbox-code-caged"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _load_caged_config(path):
    if not os.path.isfile(path):
        print(f"[ERROR] Config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    lines = []
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
    if len(lines) < 3:
        print(f"[ERROR] Config file too short ({len(lines)} lines, need at least 3)", file=sys.stderr)
        sys.exit(1)
    return lines[0], lines[1], lines[2:]


def _clean_caged_rules(config_path):
    caged_network, _, caged_cidrs = _load_caged_config(config_path)

    cleaned = False

    if _iptables_available():
        _clean_rules_iptables(caged_network, caged_cidrs)
        cleaned = True

    if _nft_available():
        _clean_rules_nft()
        cleaned = True

    if cleaned:
        print("[INFO] Firewall rules removed")
    else:
        print("[WARNING] No firewall tool (iptables/nft) available, nothing cleaned", file=sys.stderr)


if __name__ == "__main__":
    main()
