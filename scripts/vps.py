"""Talk to the droplet. One entry point for provisioning, deploying and looking.

    uv run --with paramiko python scripts/vps.py <command>

    info        what the box is and what it is running
    provision   install and tune (idempotent — safe to re-run)
    keys        install an SSH key so password auth can be retired
    push-env    copy .env to /srv/scipio/.env  (0600, never committed anywhere)
    sync        upload the working tree (what deploy builds from)
    bootstrap   place the compose file, Caddyfile and update.sh on the box
    deploy      sync + build + restart + verify  (the everyday command)
    logs        tail the stack
    exec "..."  run an arbitrary command

**Why a Python script and not ssh in a shell script.** The droplet is reached
with a password from `.env` — `sshpass` is not installed on the dev machine and
installing it needs a sudo password nobody is around to type. Paramiko needs no
system package and runs from an ephemeral `uv run --with` environment, so this
touches neither the project venv nor the lockfile.

Credentials are read from `.env` and never printed. `push-env` streams the file
over the existing SSH transport rather than shelling out, so the contents never
appear in a command line, in shell history, or in a process list on either end.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = "/srv/scipio"
KEY_PATH = Path.home() / ".ssh" / "scipio_droplet"


def _client():
    import paramiko
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
    try:
        host = os.environ["digital_ocean_ipv4"].strip()
        user = os.environ["digital_ocean_user"].strip()
    except KeyError as exc:
        sys.exit(f"{exc} missing from .env")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Key first. Once `keys` has run, the password in .env stops being the way
    # in, which is the point of having run it.
    if KEY_PATH.exists():
        try:
            client.connect(host, username=user, key_filename=str(KEY_PATH),
                           timeout=25, look_for_keys=False, allow_agent=False)
            return client, host
        except Exception:  # noqa: BLE001 — fall through to the password
            pass

    password = os.environ.get("digital_ocean_pw", "").strip()
    if not password:
        sys.exit("no usable SSH key and digital_ocean_pw is not set in .env")
    client.connect(host, username=user, password=password,
                   timeout=25, look_for_keys=False, allow_agent=False)
    return client, host


def run(client, command: str, *, echo: bool = True) -> int:
    """Stream output as it arrives. A provision takes minutes and a progress bar
    that only appears at the end is indistinguishable from a hang."""
    channel = client.get_transport().open_session()
    channel.get_pty()
    channel.exec_command(command)
    while True:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            if echo:
                sys.stdout.write(chunk)
                sys.stdout.flush()
        elif channel.exit_status_ready():
            break
    while channel.recv_ready():
        if echo:
            sys.stdout.write(channel.recv(4096).decode("utf-8", errors="replace"))
    return channel.recv_exit_status()


def put(client, local: Path, remote: str, mode: int = 0o644) -> None:
    sftp = client.open_sftp()
    try:
        sftp.putfo(local.open("rb"), remote)
        sftp.chmod(remote, mode)
    finally:
        sftp.close()


# ── commands ──────────────────────────────────────────────────────────────


def cmd_info(client) -> int:
    return run(client, r"""
echo "== host =="; . /etc/os-release; echo "$PRETTY_NAME  $(uname -r)  $(nproc) vCPU"
echo; echo "== memory =="; free -h
echo; echo "== swap =="; swapon --show 2>/dev/null || echo "  none"
echo "swappiness=$(cat /proc/sys/vm/swappiness)"
echo; echo "== disk =="; df -h / | tail -1
echo; echo "== docker =="; command -v docker >/dev/null && docker --version || echo "  not installed"
command -v docker >/dev/null && docker compose version --short 2>/dev/null | sed 's/^/  compose /'
echo; echo "== containers =="
command -v docker >/dev/null && docker ps --format '  {{.Names}}  {{.Status}}  {{.Image}}' || true
echo; echo "== firewall =="; ufw status 2>/dev/null | head -6 || echo "  ufw absent"
""")


def cmd_provision(client) -> int:
    script = REPO_ROOT / "deploy" / "provision-droplet.sh"
    put(client, script, "/root/provision-droplet.sh", 0o700)
    return run(client, "bash /root/provision-droplet.sh")


def cmd_keys(client) -> int:
    """Install a key, then verify it before anyone disables the password.

    Deliberately does NOT turn off password authentication. Doing that in the
    same run as installing the key means a mistake locks the operator out of the
    box entirely, and the recovery is DigitalOcean's web console. The command to
    disable it is printed instead, to be run once a key login has been seen to
    work.
    """
    import paramiko

    if not KEY_PATH.exists():
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = paramiko.Ed25519Key.generate()  # type: ignore[attr-defined]
        key.write_private_key_file(str(KEY_PATH))
        KEY_PATH.chmod(0o600)
        public = f"ssh-ed25519 {key.get_base64()} scipio-deploy"
        KEY_PATH.with_suffix(".pub").write_text(public + "\n", encoding="utf-8")
        print(f"generated {KEY_PATH}")
    else:
        public = KEY_PATH.with_suffix(".pub").read_text(encoding="utf-8").strip()
        print(f"reusing {KEY_PATH}")

    rc = run(client, "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                     f"grep -qxF {shlex.quote(public)} ~/.ssh/authorized_keys 2>/dev/null || "
                     f"echo {shlex.quote(public)} >> ~/.ssh/authorized_keys; "
                     "chmod 600 ~/.ssh/authorized_keys; echo installed")
    if rc == 0:
        print(
            "\nVerify the key works BEFORE disabling passwords — open a second\n"
            "session and confirm it connects. Then, and only then:\n\n"
            "  uv run --with paramiko python scripts/vps.py exec \\\n"
            "    \"sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin prohibit-password/;\"\\\n"
            "    \"s/^#\\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config \\\n"
            "     && systemctl restart ssh && echo done\"\n\n"
            "The droplet password is in .env and .env has been shared over chat\n"
            "before, so it should stop being a way in.\n"
        )
    return rc


def cmd_push_env(client) -> int:
    """The one file that cannot be in git.

    Sent over SFTP rather than `echo ... > file`, so no value ever reaches a
    command line, a shell history or a process list.
    """
    env = REPO_ROOT / ".env"
    if not env.is_file():
        sys.exit(".env not found")
    run(client, f"install -d -m 0750 {REMOTE_DIR}", echo=False)
    put(client, env, f"{REMOTE_DIR}/.env", 0o600)
    print(f"copied .env -> {REMOTE_DIR}/.env (0600)")
    # Read back only the KEYS, never the values, as proof it landed intact.
    return run(client, f"echo 'keys present:' && grep -oE '^[A-Za-z_]+=' {REMOTE_DIR}/.env "
                       "| tr -d '=' | tr '\\n' ' ' && echo")


#: What Dockerfile.api actually needs. An allowlist rather than an exclude list:
#: the repo carries .venv, node_modules, .git and a Foundry `out/` — hundreds of
#: megabytes the build must not receive — and a forgotten exclusion is silent,
#: it just makes every sync slow.
#:
#: `web` is NOT here. The dApp is built and served by Vercel; uploading it would
#: put a Next.js tree on a 961 MiB box for nothing.
SYNC_PATHS = (
    "pyproject.toml", "uv.lock", ".dockerignore",
    "agent", "venues", "data", "packages", "deployments", "deploy",
    # The flat ABIs the harness reads (`agent/chain/abi.py`). Omitting these does
    # NOT fail loudly: `load_abi` falls back to a bundled minimal ABI and logs a
    # warning nobody reads, so the API starts, /health is green, /venues answers,
    # and only a call touching a newer function fails — the deployed API returned
    # 500 on every vault read with `ABIFunctionNotFound: 'paused'`, which reads
    # like a contract problem and is a packaging one.
    "contracts/abis",
)


def cmd_sync(client) -> int:
    """Upload the source the droplet builds from.

    One tarball rather than file-by-file SFTP. The tree is ~1,500 files and each
    SFTP `put` is a round trip; over a link to a datacentre that is minutes
    against seconds, and the difference is felt on every single deploy.

    `git archive` is deliberately NOT used. It ships HEAD, and the entire point
    of this command is to deploy what is in the working tree right now —
    including changes that have not been committed yet. A sync that silently
    deployed the last commit instead would be the worst kind of wrong.
    """
    import io
    import tarfile

    missing = [p for p in SYNC_PATHS if not (REPO_ROOT / p).exists()]
    if missing:
        sys.exit(f"missing from the repo: {', '.join(missing)}")

    excluded_dirs = {".venv", "node_modules", "__pycache__", ".next", ".next-build",
                     ".git", ".pytest_cache", ".ruff_cache", "out", "cache", "lib", "broadcast"}

    def keep(info: "tarfile.TarInfo"):
        parts = set(info.name.replace("\\", "/").split("/"))
        if parts & excluded_dirs or info.name.endswith((".pyc", ".log")):
            return None
        # Uploading .env here would put it in the build context, where a stray
        # COPY could bake it into an image layer — and an image layer survives
        # every later deletion. It goes over SFTP to a path outside the context,
        # by `push-env`.
        if info.name.endswith(".env") or "/.env" in info.name:
            return None
        return info

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in SYNC_PATHS:
            tar.add(REPO_ROOT / path, arcname=path, filter=keep)
    size = buf.tell()
    buf.seek(0)

    sftp = client.open_sftp()
    try:
        run(client, f"install -d -m 0750 {REMOTE_DIR}/src", echo=False)
        sftp.putfo(buf, f"{REMOTE_DIR}/src.tar.gz")
    finally:
        sftp.close()
    print(f"uploaded {size / 1_048_576:.1f} MiB")

    # --delete-first equivalent: wipe the tree so a file removed locally does not
    # linger on the box and get compiled into the next image.
    return run(client, f"rm -rf {REMOTE_DIR}/src && install -d -m 0750 {REMOTE_DIR}/src && "
                       f"tar xzf {REMOTE_DIR}/src.tar.gz -C {REMOTE_DIR}/src && "
                       f"rm -f {REMOTE_DIR}/src.tar.gz && "
                       # The shell scripts are written on Windows; a CRLF shebang
                       # fails as `bash\r: No such file or directory`.
                       f"find {REMOTE_DIR}/src -name '*.sh' -exec sed -i 's/\\r$//' {{}} + && "
                       f"echo 'extracted:' && du -sh {REMOTE_DIR}/src | cut -f1")


def cmd_bootstrap(client) -> int:
    """Place the three files the droplet needs, and nothing else.

    There is deliberately no git checkout on the box. A checkout is a fourth
    copy of the repo that can be edited in place, drift from main, and then be
    silently reverted by the next `git pull` — and it would put the source of a
    project holding real keys on an internet-facing host for no benefit, since
    nothing there builds anything.
    """
    run(client, f"install -d -m 0750 {REMOTE_DIR}", echo=False)
    for local, remote, mode in (
        (REPO_ROOT / "deploy" / "docker-compose.yml", "docker-compose.yml", 0o644),
        (REPO_ROOT / "deploy" / "Caddyfile", "Caddyfile", 0o644),
        (REPO_ROOT / "deploy" / "update.sh", "update.sh", 0o750),
    ):
        put(client, local, f"{REMOTE_DIR}/{remote}", mode)
        print(f"  -> {REMOTE_DIR}/{remote}")
    # CRLF is the failure this repo has already had twice: a shell script
    # written from a Windows tool gets `#!/usr/bin/env bash\r`, and the kernel
    # reports `bash\r: No such file or directory`, which reads as a missing
    # interpreter rather than as a line ending.
    return run(client, f"sed -i 's/\\r$//' {REMOTE_DIR}/update.sh && "
                       f"bash -n {REMOTE_DIR}/update.sh && echo 'update.sh parses'")


def cmd_deploy(client) -> int:
    """Sync the tree, then build and restart. The everyday command.

    Sync is not a separate step you can forget: a build from a stale tree
    succeeds, restarts cleanly, reports healthy, and serves the previous
    version — which is the most confusing possible outcome of a deploy.
    """
    rc = cmd_bootstrap(client)
    if rc != 0:
        return rc
    rc = cmd_sync(client)
    if rc != 0:
        return rc
    return run(client, f"cd {REMOTE_DIR} && bash update.sh")


def cmd_logs(client) -> int:
    return run(client, f"cd {REMOTE_DIR} && docker compose logs --tail=120")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    command, rest = sys.argv[1], sys.argv[2:]
    client, host = _client()
    print(f"— {host} —\n")
    try:
        if command == "info":
            return cmd_info(client)
        if command == "provision":
            return cmd_provision(client)
        if command == "keys":
            return cmd_keys(client)
        if command == "push-env":
            return cmd_push_env(client)
        if command == "sync":
            return cmd_sync(client)
        if command == "bootstrap":
            return cmd_bootstrap(client)
        if command == "deploy":
            return cmd_deploy(client)
        if command == "logs":
            return cmd_logs(client)
        if command == "exec":
            if not rest:
                sys.exit('exec needs a command: vps.py exec "uptime"')
            return run(client, " ".join(rest))
        print(__doc__)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
