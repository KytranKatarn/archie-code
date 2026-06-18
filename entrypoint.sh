#!/bin/sh
# A.R.C.H.I.E. Engine container entrypoint — provisions the build/test workspace
# so the autonomous build loop (#4256) can branch -> edit -> test -> push -> PR.
#
# Why this exists (#4258): the engine runs on a read-only rootfs with cap_drop
# ALL. The build loop's file/git/shell tools use Path.cwd() as their workspace,
# but the /workspace volume ships EMPTY and HOME is read-only, so git could not
# write config and there was no repo to operate on. This script makes the writable
# /workspace volume a live archie-code checkout and points git config at the
# writable /data volume.
#
# Secret handling: the GitHub token is NEVER written to .git/config or a remote
# URL. A credential helper reads ARCHIE_GITHUB_TOKEN from the process env at push
# time only. The clone uses the clean (public) URL.
set -u

WS="${ARCHIE_ENGINE_WORKSPACE:-/workspace}"
REPO="${ARCHIE_ENGINE_REPO:-https://github.com/KytranKatarn/archie-code.git}"
export GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL:-/data/.gitconfig}"
mkdir -p "$(dirname "$GIT_CONFIG_GLOBAL")" 2>/dev/null || true

# --- git identity + safety (HOME is read-only; GIT_CONFIG_GLOBAL lives on /data) ---
git config --global user.name "A.R.C.H.I.E. Engine"
git config --global user.email "engine@kytranempowerment.com"
git config --global --add safe.directory "$WS"
git config --global init.defaultBranch main
# Push auth: a custom helper that emits the token from the env at call time.
# The literal token is NOT stored here — only the helper that reads $ARCHIE_GITHUB_TOKEN.
git config --global credential.helper \
  '!f() { test "$1" = get && printf "username=x-access-token\npassword=%s\n" "${ARCHIE_GITHUB_TOKEN:-}"; }; f'

# --- ensure /workspace is a live archie-code checkout on main ---
if [ ! -d "$WS/.git" ]; then
  echo "[entrypoint] cloning $REPO -> $WS"
  tmp="$(mktemp -d)"
  if git clone --depth 100 "$REPO" "$tmp/repo"; then
    # /workspace is a (possibly non-empty) volume mountpoint; copy the checkout in.
    cp -a "$tmp/repo/." "$WS/" && echo "[entrypoint] clone OK"
  else
    echo "[entrypoint] FATAL: clone failed" >&2
    rm -rf "$tmp"
    exit 1
  fi
  rm -rf "$tmp"
else
  echo "[entrypoint] refreshing $WS -> origin/main"
  git -C "$WS" remote set-url origin "$REPO" || true
  git -C "$WS" fetch origin main || true
  git -C "$WS" checkout main 2>/dev/null || true
  git -C "$WS" reset --hard origin/main || true
fi

cd "$WS" || { echo "[entrypoint] FATAL: cannot cd to $WS" >&2; exit 1; }
echo "[entrypoint] workspace ready @ $(git rev-parse --short HEAD 2>/dev/null || echo none) — launching: $*"

# Hand off to the image CMD (python -m archie_engine) with cwd = the checkout.
exec "$@"
