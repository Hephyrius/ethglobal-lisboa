#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 droplet to run scipio.capital.
#
#     scripts/vps.sh provision          # from a dev machine
#     bash deploy/provision-droplet.sh  # or directly on the box, as root
#
# Idempotent throughout: every step checks for its own result first, because a
# provision is re-run far more often than it is run — after a resize, after a
# rebuild, after somebody wonders whether it finished.
#
# ─────────────────────────────────────────────────────────────────────────────
# SIZED FOR THE BOX WE ACTUALLY HAVE
# ─────────────────────────────────────────────────────────────────────────────
#
#   1 vCPU · 961 MiB RAM · 24 GB disk · no swap
#
# That is under a gigabyte for Docker, Caddy, a Next.js server and a Python
# process holding web3 and the agent loop. It fits, but only with swap and only
# if nothing large is ever *built* here — see deploy/README.md on why images are
# built in CI and pulled rather than built on the droplet.
#
# Everything below is chosen against those numbers, not from a generic checklist.

set -eu

log()  { printf "\033[36m==>\033[0m %s\n" "$1"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
skip() { printf "  \033[90m·\033[0m %s\n" "$1"; }

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive

# ── 1. swap ───────────────────────────────────────────────────────────────
# The single most valuable change on this box. With 961 MiB and no swap, the
# kernel's only response to a memory spike is the OOM killer, and the OOM killer
# picks by badness score — which on this stack means the Python process holding
# the agent loop, mid-tick. A container that is killed restarts and looks fine
# afterwards, so the symptom is "a tick occasionally vanished", which is close to
# unfindable.
#
# 4 GB rather than the conventional 2x RAM. The multiplier is a rule for boxes
# whose swap absorbs idle pages; here it also has to absorb a transient spike
# several times the size of RAM. Disk is 24 GB with 22 free, so 4 GB is cheap
# insurance and still leaves plenty for images.
SWAPFILE=/swapfile
SWAP_SIZE_MB=4096
log "swap"
if swapon --show 2>/dev/null | grep -q "$SWAPFILE"; then
  skip "$SWAPFILE already active ($(swapon --show=SIZE --noheadings | head -1 | tr -d ' '))"
else
  # fallocate then dd-fallback: fallocate is instant but produces a file with
  # holes on some filesystems, and mkswap refuses those. dd is slow and always
  # works. Try the fast one, fall back rather than fail.
  fallocate -l "${SWAP_SIZE_MB}M" "$SWAPFILE" 2>/dev/null || \
    dd if=/dev/zero of="$SWAPFILE" bs=1M count="$SWAP_SIZE_MB" status=none
  chmod 600 "$SWAPFILE"          # world-readable swap is a memory disclosure
  mkswap "$SWAPFILE" >/dev/null
  swapon "$SWAPFILE"
  ok "created and enabled ${SWAP_SIZE_MB}M at $SWAPFILE"
fi
if grep -q "^$SWAPFILE" /etc/fstab; then
  skip "already in /etc/fstab"
else
  echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
  ok "persisted in /etc/fstab (survives reboot)"
fi

# ── 2. VM tuning for a small box ──────────────────────────────────────────
# swappiness 20, not the default 60 and not the 1 that server guides recommend.
#
#   60 evicts anonymous pages eagerly. On a box whose working set nearly fills
#      RAM that means paging out live process memory to make room for page
#      cache, and the cost lands on request latency.
#    1 tells the kernel to reclaim page cache almost exclusively. That reads as
#      "prefer RAM", but on THIS box it means a build or a memory spike hits the
#      OOM killer instead of using the 4 GB of swap we just created. It defeats
#      the point of step 1.
#   20 leans toward keeping the working set resident while still using swap
#      under real pressure, which is the actual requirement here.
#
# vfs_cache_pressure 50 makes the kernel keep dentry/inode caches a little
# longer. Docker's overlayfs does an enormous amount of path lookup, so this is
# worth more here than on a general server.
#
# overcommit_memory stays at the default 0. Node and Python both reserve far
# more address space than they touch, and strict accounting (2) would refuse
# allocations that would never have been backed by real pages.
log "vm tuning"
cat > /etc/sysctl.d/99-scipio.conf <<'SYSCTL'
# Tuned for a 1 vCPU / 1 GB droplet running Docker. See deploy/provision-droplet.sh.
vm.swappiness = 20
vm.vfs_cache_pressure = 50
# Default is 128; Caddy terminating TLS for two hostnames plus two upstreams
# does not need much, but the default is small enough to drop bursts.
net.core.somaxconn = 1024
SYSCTL
sysctl -q -p /etc/sysctl.d/99-scipio.conf
ok "swappiness=$(cat /proc/sys/vm/swappiness) vfs_cache_pressure=$(cat /proc/sys/vm/vfs_cache_pressure)"

# ── 3. journald cap ───────────────────────────────────────────────────────
# systemd-journald defaults to 10% of the filesystem — 2.4 GB here — and it only
# reclaims when it reaches that. Combined with Docker's own logs (step 5) an
# idle box can eat several gigabytes of a 24 GB disk on logging alone, and the
# failure mode of a full disk is that Docker cannot write layers and Caddy
# cannot write certificates.
log "journal cap"
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/99-scipio.conf <<'JOURNAL'
[Journal]
SystemMaxUse=200M
SystemMaxFileSize=20M
JOURNAL
systemctl restart systemd-journald
ok "journal capped at 200M"

# ── 4. packages ───────────────────────────────────────────────────────────
log "base packages"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades >/dev/null
ok "ufw, fail2ban, unattended-upgrades, ca-certificates"

# ── 5. Docker ─────────────────────────────────────────────────────────────
# From Docker's own repository, not Ubuntu's `docker.io`. The distro package
# lags and, more to the point, does not ship the `compose` v2 plugin, which is
# what deploy/docker-compose.yml is written against.
log "docker"
if command -v docker >/dev/null 2>&1; then
  skip "already installed ($(docker --version))"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin >/dev/null
  ok "installed $(docker --version)"
fi

# Docker's default json-file driver is UNBOUNDED. One chatty container fills a
# 24 GB disk given enough uptime, and nothing warns first.
#
# `live-restore` keeps containers running across a dockerd restart, which
# matters because an unattended-upgrade of docker-ce would otherwise take the
# site down for the length of a daemon restart.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DOCKERD'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}
DOCKERD
systemctl enable -q docker
systemctl restart docker
ok "log rotation 10m x3, live-restore on"

# ── 6. firewall ───────────────────────────────────────────────────────────
# The API and the dApp are NOT opened. They bind to the compose network only
# (`expose:`, not `ports:`) and are reached through Caddy, so 8000 and 3000 are
# unreachable from outside by construction as well as by firewall.
#
# Ordering matters: allow 22 BEFORE enabling, or `ufw enable` drops this session
# and finishes the provision with nobody watching.
log "firewall"
ufw allow 22/tcp   >/dev/null
ufw allow 80/tcp   >/dev/null
ufw allow 443/tcp  >/dev/null
ufw --force default deny incoming >/dev/null
ufw --force default allow outgoing >/dev/null
ufw --force enable >/dev/null
ok "$(ufw status | head -1) — 22, 80, 443 in; all else denied"

# ── 7. fail2ban on sshd ───────────────────────────────────────────────────
# Root password login is enabled on this droplet, and a public IPv4 on port 22
# sees credential-stuffing within minutes of first boot. This does not make a
# password safe; it makes brute force impractical while keys are set up.
log "fail2ban"
cat > /etc/fail2ban/jail.d/sshd.local <<'JAIL'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
JAIL
systemctl enable -q fail2ban
systemctl restart fail2ban
ok "sshd jail active"

# ── 8. unattended security upgrades ───────────────────────────────────────
# Security patches only, and NO automatic reboot. An unscheduled reboot during a
# demo is a worse outcome than a kernel patch applied a day late; the box is
# rebooted by hand.
log "unattended-upgrades"
cat > /etc/apt/apt.conf.d/51scipio-unattended <<'UNATT'
Unattended-Upgrade::Allowed-Origins { "${distro_id}:${distro_codename}-security"; };
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
UNATT
systemctl enable -q unattended-upgrades
ok "security-only, no automatic reboot"

# ── 9. where the deployment lives ─────────────────────────────────────────
install -d -m 0750 /srv/scipio
ok "/srv/scipio ready"

echo
log "result"
free -h | sed 's/^/  /'
echo
swapon --show | sed 's/^/  /'
echo
df -h / | tail -1 | sed 's/^/  /'
echo
printf "  docker  %s\n" "$(docker --version)"
printf "  compose %s\n" "$(docker compose version --short 2>/dev/null || echo missing)"
