#!/usr/bin/env bash
#
# Sync this fork with upstream BitMaker-hub/bitronics-web-flasher and re-apply
# the BitzyLabs branding.
#
# The fork tracks upstream as content-identical, not as identical history: the
# goal is that `main` always holds exactly upstream's tree plus our tooling
# and branding, regenerated from upstream's files rather than hand-carried
# across from the previous sync.
#
# A hard reset was the obvious way to do that and it is the wrong one. Our
# branding commits are never ancestors of upstream's tip, so pushing the reset
# result is always a non-fast-forward push and always rejected -- the sync
# would "run", rewrite the branch locally, then die at the push, nightly. A
# merge instead records upstream's content while keeping our previous commits
# as ancestors, so the push that follows is a fast-forward. Where both sides
# edited the same line upstream wins outright (-X theirs), because our side is
# regenerated from scratch immediately afterwards; keeping our stale copy of a
# line we are about to overwrite would only be a conflict waiting to happen.
# Where one side deleted a file the other edited there is no line to pick, so
# -X theirs stops the merge; the resolution below settles those by policy too
# -- the pruner's deletions win, their deletions lose to our edited copies --
# which keeps firmware-bot nights hands-off.
#
# Our own tooling (the overlay, this script, the workflows) is not in upstream,
# so it would otherwise be lost. It is restored from the pre-sync commit.
#
# Usage:   ./scripts/sync-upstream.sh [--push]
#          --push   commit and push to origin after a successful sync
#
# Env:     UPSTREAM_REMOTE   remote to sync from (default: upstream, created
#                            from UPSTREAM_URL if it does not exist)
#          UPSTREAM_URL      https URL of the upstream repository
#          UPSTREAM_BRANCH   branch to track (default: main)
#          SKIP_BUILD=1      skip the build check (tests, quick runs)
#
set -euo pipefail

cd "$(dirname "$0")/.."

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/BitMaker-hub/bitronics-web-flasher.git}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
PUSH=0
[[ "${1:-}" == "--push" ]] && PUSH=1

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

# `git clone` only ever creates origin; gh adds upstream for forks, and CI
# starts from a checkout with nothing else. Create the remote rather than
# failing on one nobody has a reason to have added.
if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "==> Adding remote ${UPSTREAM_REMOTE} -> ${UPSTREAM_URL}"
  git remote add "$UPSTREAM_REMOTE" "$UPSTREAM_URL"
fi

# The merge and the re-brand both commit, and CI runners have no identity.
if ! git config user.email >/dev/null 2>&1; then
  git config user.email "github-actions[bot]@users.noreply.github.com"
  git config user.name "github-actions[bot]"
fi

# Our tooling must survive the sync. Save it before the tree is disturbed.
SAVED="$(git rev-parse HEAD)"
KEEP=(
  .bitzylabs-overlay
  scripts/apply-bitzylabs-branding.py
  scripts/sync-upstream.sh
  scripts/upstream-mirror-test.sh
  .github/workflows/nextjs.yml
  .github/workflows/update-firmware.yml
  .github/workflows/sync-upstream.yml
  # Upstream owns these two, but our pins (axios, next -- Aikido CVE
  # remediations) live in them and the pair must always ship together:
  # restore both from our side so npm ci never meets a lock that
  # disagrees with the manifest, and let the patcher's chains re-land
  # anything a merge still manages to trade back.
  package.json
  package-lock.json
)

echo "==> Fetching ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BRANCH"

UPSTREAM_SHA="$(git rev-parse "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}")"

# Upstream's tip is already in our history, so we have everything it has.
# This is the common case on a quiet night, and it must leave the branch
# exactly as it was rather than recording a sync that changed nothing.
if git merge-base --is-ancestor "$UPSTREAM_SHA" HEAD; then
  echo "Already in step with upstream (${UPSTREAM_SHA:0:12}). Nothing to do."
  python3 scripts/apply-bitzylabs-branding.py --check
  exit 0
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "==> Working tree is not clean; commit or stash first:" >&2
  git status --short >&2
  exit 1
fi

BEHIND="$(git rev-list --count "HEAD..${UPSTREAM_SHA}")"
AHEAD="$(git rev-list --count "${UPSTREAM_SHA}..HEAD")"
echo "==> Upstream is ${BEHIND} commit(s) ahead; we are ${AHEAD} commit(s) ahead"
echo "==> Merging ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} (${UPSTREAM_SHA:0:12})"

if ! git merge --no-edit -X theirs "$UPSTREAM_SHA"; then
  # -X theirs picks a winner per line, but there is no line to pick when
  # one side deleted a file the other edited: the merge stops with those
  # paths unmerged. That is the shape of every firmware-bot night -- the
  # pruner dropped dead-device firmware (and releases.json), upstream's
  # bot then touched those very files -- and eleven red nights (Oct 30 -
  # Nov 8, 2026) proved that waiting for a human to re-run a script is
  # not a plan. The direction is the fork's: a path we deleted stays
  # deleted (the pruner's call, and it re-runs below anyway), a path they
  # deleted keeps our edited copy, and content still on both sides --
  # which -X theirs should have settled -- stops the sync with the paths
  # named. Nothing here aborts the merge any more; it is finished below.
  if ! git rev-parse --verify -q MERGE_HEAD >/dev/null; then
    echo "==> The merge failed before leaving a merge to finish;" >&2
    echo "    git's own message is above. Nothing was changed." >&2
    exit 1
  fi
  settled=0
  while IFS= read -r -d '' path; do
    stages=" $(git ls-files -u -- "$path" | awk '{print $3}' | tr '\n' ' ') "
    if [[ "$stages" != *" 2 "* ]]; then
      # No stage 2: our side deleted it. Keep it gone.
      git rm -f -- "$path" >/dev/null || true
    elif [[ "$stages" != *" 3 "* ]]; then
      # Stage 2 but no stage 3: they deleted a file we edited. Keep ours,
      # restoring it first if the conflict left the worktree bare.
      if [ -e "$path" ] || git checkout --ours -- "$path" 2>/dev/null; then
        git add -- "$path" || true
      fi
    fi
    # Stages 2 and 3 both present: content -X theirs did not settle.
    # Leave it unmerged; the check below names it and stops the sync.
    settled=$((settled + 1))
  done < <(git diff --name-only -z --diff-filter=U)
  if [ -n "$(git ls-files -u)" ]; then
    echo "==> Conflicts this script will not settle (content on both sides):" >&2
    git ls-files -u | awk -F'\t' '{split($1,a," "); print "    " $2 "  (stage " a[3] ")"}' >&2
    echo "    Resolve them, commit the result, then re-run this script." >&2
    exit 1
  fi
  echo "==> Settled ${settled} delete/edit conflict(s) (our deletions win); committing the merge"
  git commit --no-edit >/dev/null || {
    echo "==> Conflicts settled, but the merge commit failed;" >&2
    echo "    run 'git status' and commit the merge by hand." >&2
    exit 1
  }
fi

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

# The merge itself is committed; this only fires when the branding had to be
# put back after upstream's version of a file won the merge.
if [[ -n "$(git status --porcelain)" ]]; then
  git add -A
  git commit -m "chore: re-brand after upstream ${UPSTREAM_SHA:0:12}" \
             -m "Upstream: https://github.com/BitMaker-hub/bitronics-web-flasher/commit/${UPSTREAM_SHA}
Branding re-applied by scripts/apply-bitzylabs-branding.py"
fi

echo "==> Synced. Recent history:"
git log --oneline -4

if [[ "$PUSH" -eq 1 ]]; then
  TARGET="$BRANCH"
  [[ "$TARGET" == "HEAD" ]] && TARGET=main
  git push origin "HEAD:${TARGET}"
  echo "==> Pushed. Deployment follows via the Pages workflow."
else
  echo
  echo "Not pushed. Review with 'git log -p -1', then either:"
  echo "  ./scripts/sync-upstream.sh --push"
  echo "  git push"
fi
