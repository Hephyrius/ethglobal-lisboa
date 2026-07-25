# shellcheck shell=bash
#
# Load .env as DEFAULTS — the caller's environment always wins.
#
# Why this exists rather than the one-liner it replaces:
#
#     [ -f .env ] && set -a && . ./.env && set +a
#
# `set -a` export-assigns unconditionally, so sourcing .env silently overwrites variables the caller
# already exported. Lane A ran
#
#     ANVIL_RPC_URL=http://127.0.0.1:8541 ./scripts/seed-fork.sh
#
# and it seeded the shared fork on :8540 instead, because .env defines ANVIL_RPC_URL and won
# (request #45). Nothing warned; the script printed the address it had been overridden with.
#
# A per-variable snapshot would fix the one case and leave the trap for the next variable, so the
# semantics are fixed here instead: .env is a default, an explicit environment variable is an
# instruction, and instructions beat defaults.
#
# Usage:
#     . "$(dirname "$0")/lib/load-env.sh"
#     load_dotenv                 # .env at repo root
#     load_dotenv path/to/.env
#
# POSIX-friendly bash, no eval — `export "k=v"` is safe with arbitrary values.

load_dotenv() {
  _env_file="${1:-.env}"
  [ -f "$_env_file" ] || return 0

  # `|| [ -n "$_line" ]` so a final line without a trailing newline is not dropped.
  while IFS= read -r _line || [ -n "$_line" ]; do
    # Strip a trailing CR. .env is gitignored, so .gitattributes cannot normalise it, and it is
    # edited on Windows by several people — it WILL come back as CRLF. Without this the CR rides
    # along inside the value and produces failures that look like anything but a line ending:
    # curl reported "no node at http://localhost:8540" while the same URL worked by hand, because
    # it was really requesting $'http://localhost:8540\r'.
    _line="${_line%$'\r'}"

    case "$_line" in
      '' | '#'*) continue ;;
      *=*) ;;
      *) continue ;;
    esac

    _key="${_line%%=*}"
    _value="${_line#*=}"

    # Reject anything that is not a plain shell name — `export` would fail on it anyway, and a
    # malformed .env line should not abort a script running under `set -e`.
    case "$_key" in
      '' | *[!A-Za-z0-9_]*) continue ;;
    esac

    # Strip one layer of matching quotes, the only quoting .env conventionally carries.
    case "$_value" in
      \"*\") _value="${_value#\"}"; _value="${_value%\"}" ;;
      \'*\') _value="${_value#\'}"; _value="${_value%\'}" ;;
    esac

    # The point of the whole file: set only when the caller has not. Uses `+` so a deliberately
    # empty export still counts as set.
    if [ -z "${!_key+set}" ]; then
      export "$_key=$_value"
    fi
  done < "$_env_file"

  unset _env_file _line _key _value
}
