#!/usr/bin/env bash
# DocuNomNom container entrypoint (v1).
#
# Responsibilities (kept intentionally small):
#   - apply PUID/PGID to the in-image `app` user/group,
#   - re-exec as the `app` user via `gosu`/`su-exec` when running as root,
#   - validate that required bind-mount directories exist and are writable
#     for the resolved UID,
#   - chown writable directories to PUID:PGID with umask 002,
#   - exec the requested command under tini (PID 1, set by Dockerfile).
#
# Filesystem-type checks (rejecting SMB/NFS/FUSE for the SQLite DB,
# verifying same-device for work/output/archive) are performed by the
# Python preflight (`docunomnom.runtime.preflight`) at process start —
# the shell entrypoint deliberately stays minimal so the Python layer
# is the single source of truth for runtime invariants.
set -euo pipefail

log() {
    printf '[entrypoint] %s\n' "$*" >&2
}

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
APP_USER="${APP_USER:-app}"
APP_GROUP="${APP_GROUP:-app}"

# Default mount points; overridable via DOCUNOMNOM__PATHS__* env vars.
INPUT_DIR="${DOCUNOMNOM__PATHS__INPUT_DIR:-/data/input}"
OUTPUT_DIR="${DOCUNOMNOM__PATHS__OUTPUT_DIR:-/data/output}"
WORK_DIR="${DOCUNOMNOM__PATHS__WORK_DIR:-/data/work}"
ARCHIVE_DIR="${DOCUNOMNOM__PATHS__ARCHIVE_DIR:-/data/archive}"
DATA_DIR="${DOCUNOMNOM_DATA_DIR:-/data}"
CONFIG_DIR="${DOCUNOMNOM_CONFIG_DIR:-/config}"

apply_puid_pgid() {
    if [ "$(id -u)" -ne 0 ]; then
        local current_uid current_gid
        current_uid="$(id -u)"
        current_gid="$(id -g)"
        if [ "${current_uid}" != "${PUID}" ] || [ "${current_gid}" != "${PGID}" ]; then
            log "WARNING: container is not root (uid=${current_uid} gid=${current_gid}) but PUID=${PUID} PGID=${PGID}; cannot reassign IDs."
        fi
        return 0
    fi

    if command -v groupmod >/dev/null 2>&1; then
        groupmod -o -g "${PGID}" "${APP_GROUP}" 2>/dev/null || true
    fi
    if command -v usermod >/dev/null 2>&1; then
        usermod -o -u "${PUID}" -g "${PGID}" "${APP_USER}" 2>/dev/null || true
    fi
    log "Applied PUID=${PUID} PGID=${PGID} to user '${APP_USER}'"
}

ensure_dir() {
    local path="$1"
    local label="$2"
    if [ ! -d "${path}" ]; then
        log "Creating ${label} at ${path}"
        mkdir -p "${path}"
    fi
    if [ "$(id -u)" -eq 0 ]; then
        chown "${PUID}:${PGID}" "${path}" 2>/dev/null || \
            log "WARNING: failed to chown ${path} (read-only mount?)"
    fi
}

assert_writable() {
    local path="$1"
    local label="$2"
    local probe="${path}/.docunomnom_writable_probe.$$"
    if (umask 002 && touch "${probe}") 2>/dev/null; then
        rm -f "${probe}" || true
    else
        log "FATAL: ${label} (${path}) is not writable for the resolved UID."
        log "Hint: check the bind-mount and that PUID/PGID match the host user."
        exit 1
    fi
}

ensure_dirs() {
    ensure_dir "${DATA_DIR}"   "data dir"
    ensure_dir "${INPUT_DIR}"  "input dir"
    ensure_dir "${OUTPUT_DIR}" "output dir"
    ensure_dir "${WORK_DIR}"   "work dir"
    ensure_dir "${ARCHIVE_DIR}" "archive dir"
    # Config dir is optional (a YAML file may be mounted in directly), but
    # if it exists we want it readable by the app user.
    if [ -d "${CONFIG_DIR}" ] && [ "$(id -u)" -eq 0 ]; then
        chown -R "${PUID}:${PGID}" "${CONFIG_DIR}" 2>/dev/null || true
    fi
}

drop_privileges_and_exec() {
    if [ "$(id -u)" -ne 0 ]; then
        # Already a non-root user (rootless container). Validate writability
        # in our current identity and exec.
        assert_writable "${DATA_DIR}"   "data dir"
        assert_writable "${INPUT_DIR}"  "input dir"
        assert_writable "${OUTPUT_DIR}" "output dir"
        assert_writable "${WORK_DIR}"   "work dir"
        assert_writable "${ARCHIVE_DIR}" "archive dir"
        log "Starting as uid=$(id -u) gid=$(id -g) cmd=$*"
        exec "$@"
    fi

    local switcher=""
    if command -v gosu >/dev/null 2>&1; then
        switcher="gosu ${APP_USER}"
    elif command -v su-exec >/dev/null 2>&1; then
        switcher="su-exec ${APP_USER}"
    elif command -v runuser >/dev/null 2>&1; then
        switcher="runuser -u ${APP_USER} --"
    else
        log "WARNING: no privilege-drop tool found (gosu/su-exec/runuser); running as root."
        log "Starting as uid=0 gid=0 cmd=$*"
        exec "$@"
    fi

    # shellcheck disable=SC2086
    ${switcher} sh -c '
        for d in "$1" "$2" "$3" "$4" "$5"; do
            probe="$d/.docunomnom_writable_probe.$$"
            if ! ( umask 002 && touch "$probe" ) 2>/dev/null; then
                printf "[entrypoint] FATAL: %s is not writable for app user.\n" "$d" >&2
                exit 1
            fi
            rm -f "$probe" || true
        done
    ' _ "${DATA_DIR}" "${INPUT_DIR}" "${OUTPUT_DIR}" "${WORK_DIR}" "${ARCHIVE_DIR}"

    log "Starting as ${APP_USER} (uid=${PUID} gid=${PGID}) cmd=$*"
    # shellcheck disable=SC2086
    exec ${switcher} "$@"
}

apply_puid_pgid
ensure_dirs
drop_privileges_and_exec "$@"
