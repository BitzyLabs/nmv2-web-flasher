#!/usr/bin/env bash
#
# Sync this fork with upstream BitMaker-hub/bitronics-web-flasher and re-apply
# the BitzyLabs branding.
#
# The fork tracks upstream as a hard reset, never a merge: merging 400 commits
# of someone else's code is how the old replica drifted until it stopped
# building. A reset keeps the relationship honest -- `main` is always exactly
# upstream plus one script's worth of branding -- and it is why the branding
# has to be re-applied by hand every single time.
#
# Our own tooling (the overlay, this script, the workflows) is not in upstream,
# so a reset would delete it. It is restored from the pre-reset commit.
#
# Usage:   ./scripts/sync-upstream.sh [--push]
#          --push   commit and push to origin/main after a successful sync
#
set -euo pipefail

cd "$(dirname "$0")/.."

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
PUSH=0
[[ "${1:-}" == "--push" ]] && PUSH=1

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

# Our tooling must survive the reset. Save it before throwing the tree away.
SAVED="$(git rev-parse HEAD)"
KEEP=(
  .bitzylabs-overlay
  scripts/apply-bitzylabs-branding.py
  scripts/sync-upstream.sh
  .github/workflows/nextjs.yml
  .github/workflows/update-firmware.yml
  .github/workflows/sync-upstream.yml
)

echo "==> Fetching ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BRANCH"

UPSTREAM_SHA="$(git rev-parse "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}")"
LOCAL_SHA="$(git rev-parse HEAD)"

if [[ "$UPSTREAM_SHA" == "$(git merge-base HEAD "$UPSTREAM_REMOTE/$UPSTREAM_BRANCH")" && \
      "$LOCAL_SHA" == "$(git rev-parse "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}")" ]]; then
  echo "Already in step with upstream (${UPSTREAM_SHA:0:12}). Nothing to do."
  python3 scripts/apply-bitzylabs-branding.py --check
  exit 0
fi

BEHIND="$(git rev-list --count "HEAD..${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}")"
AHEAD="$(git rev-list --count "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}..HEAD")"
echo "==> Upstream is ${BEHIND} commit(s) ahead; we are ${AHEAD} commit(s) ahead"
echo "==> Resetting ${BRANCH} to ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} (${UPSTREAM_SHA:0:12})"

git reset --hard "$UPSTREAM_SHA"

echo "==> Restoring BitzyLabs tooling from ${SAVED:0:12}"
for path in "${KEEP[@]}"; do
  if git cat-file -e "${SAVED}:${path}" 2>/dev/null; then
    git checkout "$SAVED" -- "$path"
  fi
done

echo "==> Re-applying BitzyLabs branding"
python3 scripts/apply-bitzylabs-branding.py

if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
  echo "==> Skipping the build check (SKIP_BUILD=1)"
elif command -v npm >/dev/null; then
  echo "==> Verifying the build still compiles"
  npm ci --silent
  npx next build >/dev/null && echo "    build OK"
else
  echo "==> npm not found; skipping the build check"
fi

if git diff --quiet; then
  echo "==> No changes: we were already in step with upstream."
  exit 0
fi

echo "==> Synced. Changed files:"
git status --short

if [[ "$PUSH" -eq 1 ]]; then
  git add -A
  git commit -m "chore: sync with upstream ${UPSTREAM_SHA:0:12} and re-brand

Upstream: https://github.com/BitMaker-hub/bitronics-web-flasher/commit/${UPSTREAM_SHA}
Branding re-applied by scripts/apply-bitzylabs-branding.py"
  git push origin "$BRANCH"
  echo "==> Pushed. Deployment follows via the Pages workflow."
else
  echo
  echo "Not pushed. Review with 'git diff', then either:"
  echo "  ./scripts/sync-upstream.sh --push"
  echo "  git add -A && git commit && git push"
fi
