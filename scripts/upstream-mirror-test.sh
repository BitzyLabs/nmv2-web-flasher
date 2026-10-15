#!/usr/bin/env bash
#
# End-to-end proof that upstream changes flow into this flasher, and that
# the sync pipeline behaves on every kind of night -- run automatically by
# the Sync upstream workflow before the real sync, and by hand after any
# change to the patcher or the sync script.
#
# Simulated upstream = real upstream/main plus the churn BitMaker-hub
# actually ships: a reworded SHOP path, a new device row carrying a
# bitronics.store link in a shape no targeted patch has ever written, a
# new const with a fresh URL shape, and firmware folders for a device the
# picker does not offer. The fork's picker policy means the new row, its
# firmware and its copy are expected to be FILTERED OUT of the offer
# rather than mirrored into it.
#
# Three nights are played against a bare origin standing in for GitHub:
#
#   churn   merge, re-brand, gates, fast-forward push -- the loud path
#   quiet   already in step: --check only, HEAD does not move, no push
#   drift   the two ways upstream can break us must FAIL, and fail before
#           anything is pushed: a chain marker gone (the silent class the
#           chain audit exists for -- it fails even on a quiet night's
#           --check, where no chain runs at all) and an anchor reworded
#           (the loud class the helpers raise on, at the next real sync)
#
# SKIP_BUILD=1 throughout: the workflow's own sync step build-checks the
# real tree, so what the harness proves is the mechanism -- git, merge,
# branding, validation, audit -- at its own speed.
#
# Usage:   ./scripts/upstream-mirror-test.sh
#          UPSTREAM_URL=... to point the simulated fetch elsewhere.
#
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/BitMaker-hub/bitronics-web-flasher.git}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/bitzy-mirror-test.XXXXXX")"
FAKE="$WORK/upstream-sim"
ORIGIN="$WORK/mirror-origin.git"
TEST="$WORK/mirror-test"
trap 'rm -rf "$WORK"' EXIT

PASS=0
ok() {
  PASS=$((PASS + 1))
  echo "  ok $PASS  $1"
}
die() {
  echo "FAIL: $1" >&2
  exit 1
}

# ---- 1. build the simulated upstream --------------------------------------
echo "==> Building simulated upstream from $UPSTREAM_URL"
git init -q --bare "$ORIGIN"
git clone -q "$SRC" "$FAKE"
git -C "$FAKE" config user.name "mirror-harness"
git -C "$FAKE" config user.email "mirror-harness@bitzylabs.local"
cd "$FAKE"
if git -C "$SRC" show-ref -q --verify refs/remotes/upstream/main; then
  git fetch -q "$SRC" +refs/remotes/upstream/main:refs/remotes/upstream/main
else
  # CI starts from a checkout that never fetched the upstream remote.
  git fetch -q "$UPSTREAM_URL" main:refs/remotes/upstream/main
fi
git checkout -q -B main refs/remotes/upstream/main
UPSTREAM_SHA="$(git rev-parse --short HEAD)"

python3 - <<'PY'
import pathlib

d = pathlib.Path("src/lib/devices.ts")
t = d.read_text()

# (a) upstream rewords the SHOP constant: different path, same domain.
#     The sweep must land our domain whatever path they choose.
old_shop = "const SHOP = 'https://bitronics.store/collections';"
assert old_shop in t, "expected upstream's SHOP constant"
t = t.replace(old_shop, "const SHOP = 'https://bitronics.store/shop/all';", 1)

# (b) a URL in a shape no targeted patch has ever written: the sweep is
#     judged by the class of the URL, not by a list of old constants.
assert "const TRACKING" not in t, "expected no TRACKING constant yet"
t = t.replace(
    "const SHOP = 'https://bitronics.store/shop/all';",
    "const TRACKING = 'https://bitronics.store/track';\n"
    "const SHOP = 'https://bitronics.store/shop/all';",
    1,
)

# (c) upstream adds a device, with a bitronics.store URL on its own row.
#     Row policy drops it; the URL sweep is the belt behind that.
anchor = "export const DEVICE_SOURCES: DeviceSource[] = [\n"
assert anchor in t, "expected DEVICE_SOURCES"
t = t.replace(anchor, anchor + """  {
    device: 'TestBoard',
    category: 'miners',
    tagline: 'Upstream New Device',
    shop: 'https://bitronics.store/collections/testboard',
    slug: 'testboard',
  },
""", 1)
d.write_text(t)

# (d) firmware for a device the picker does not offer.
folder = pathlib.Path("public/firmware/testboard")
folder.mkdir(parents=True, exist_ok=True)
(folder / "manifest.json").write_text('{"versions": ["v9.9.9"]}\n')
(folder / "v9.9.9.bin").write_bytes(b"\x00not real firmware\xff")
PY

git add -A
git commit -qm "simulated upstream churn: reworded SHOP, new URL shape, new device, stray firmware"
ok "simulated upstream built on top of ${UPSTREAM_SHA} (churn committed)"

# ---- 2. seed the GitHub stand-in with our main ----------------------------
git clone -q "$SRC" "$TEST"
git -C "$TEST" config user.name "mirror-harness"
git -C "$TEST" config user.email "mirror-harness@bitzylabs.local"
cd "$TEST"
git remote set-url origin "$ORIGIN"
git push -q origin main
SEED="$(git rev-parse HEAD)"
ok "mirror origin seeded with our main ($(git rev-parse --short HEAD))"

# ---- 3. churn night: merge, re-brand, gates, fast-forward push ------------
echo "==> Churn night: sync --push"
if ! OUTPUT="$(SKIP_BUILD=1 UPSTREAM_URL="$FAKE" ./scripts/sync-upstream.sh --push 2>&1)"; then
  echo "$OUTPUT"
  die "sync --push failed on churn night"
fi
POST="$(git rev-parse HEAD)"
[ "$POST" != "$SEED" ] || die "churn night did not move main"
git merge-base --is-ancestor "$SEED" "$POST" || die "churn night push was not a fast-forward"
ok "churn night: fast-forward push (no rewrite of main)"
[ "$(git -C "$ORIGIN" rev-parse main)" = "$POST" ] || die "mirror origin did not receive the push"
ok "churn night: mirror origin received the push"

# The new device row and its firmware never reach the offer, and no
# bitronics URL survives in any shape upstream chose to write one.
grep -q "TestBoard" src/lib/devices.ts && die "TestBoard survived the picker policy"
ok "churn night: new upstream device filtered out of devices.ts"
[ ! -d public/firmware/testboard ] || die "unoffered firmware folder survived"
ok "churn night: unoffered firmware folder pruned"
grep -q "const SHOP = 'https://www.bitzylabs.com';" src/lib/devices.ts ||
  die "SHOP sweep did not land after upstream reworded the path"
ok "churn night: reworded SHOP swept to our domain"
grep -q "const TRACKING = 'https://www.bitzylabs.com';" src/lib/devices.ts ||
  die "URL sweep missed a URL shape it has never seen"
ok "churn night: unseen bitronics URL shape swept to our domain"
grep -q '${SHOP}/' src/lib/devices.ts && die "collection slug suffix survived the sweep"
ok "churn night: collection slug suffixes dropped"
grep -q "DevBoard Tests" src/lib/devices.ts || die "our own rows did not survive"
ok "churn night: the fork's own device rows survived the merge"

# Tooling the KEEP list exists for must all still be here.
for keep in \
  scripts/apply-bitzylabs-branding.py \
  scripts/sync-upstream.sh \
  scripts/upstream-mirror-test.sh \
  .bitzylabs-overlay/assets/logo-tile.svg \
  .github/workflows/nextjs.yml; do
  [ -e "$keep" ] || die "KEEP lost $keep through the sync"
done
ok "churn night: tooling survived via the KEEP list"

# The end state, judged the way every run judges it: needles, zero-traces,
# picker policy, manifest hashes -- and the chain audit, which reads every
# chain's fingerprint out of the patcher's own source.
if ! CHECK="$(python3 scripts/apply-bitzylabs-branding.py --check 2>&1)"; then
  echo "$CHECK"
  die "validation is red on a correctly synced tree"
fi
ok "churn night: validation + chain audit green on the synced tree"

# ---- 4. quiet night: in step, nothing moves, nothing pushes ---------------
echo "==> Quiet night: sync again"
if ! OUTPUT="$(SKIP_BUILD=1 UPSTREAM_URL="$FAKE" ./scripts/sync-upstream.sh --push 2>&1)"; then
  echo "$OUTPUT"
  die "sync failed on quiet night"
fi
echo "$OUTPUT" | grep -q "Already in step" || die "quiet night did not recognise itself"
[ "$(git rev-parse HEAD)" = "$POST" ] || die "quiet night moved main"
[ "$(git -C "$ORIGIN" rev-parse main)" = "$POST" ] || die "quiet night pushed"
ok "quiet night: --check only, HEAD and origin unmoved"

# ---- 5. drift night: both failure classes must be loud and pre-push -------
# The silent class: a chain's fingerprint vanishes (a hand edit, or a
# successor chain trading the line away). A quiet night's --check runs no
# chain at all, so this is exactly where the audit is the only watch.
echo "==> Drift night, part one: a chain's marker disappears"
sed -i 's/in dot matrix/in-dot-matrix/g' src/components/LandingHero.tsx
if MARKER_OUT="$(python3 scripts/apply-bitzylabs-branding.py --check 2>&1)"; then
  die "a chain with no fingerprint passed validation silently"
fi
echo "$MARKER_OUT" | grep -q "did not land" ||
  die "marker loss failed without naming the chain: $MARKER_OUT"
ok "marker drift: --check fails and names the chain that did not land"
git checkout -- src/components/LandingHero.tsx

# The loud class: a local edit rewords an anchor upstream could reword
# too, and upstream then moves on -- the next real sync must die before
# it pushes anything, carrying the anchor it lost.
echo "==> Drift night, part two: an anchor is reworded, then upstream moves"
sed -i 's/^export type DeviceCategory =/export type DeviceCategoryRenamed =/' src/lib/devices.ts
git commit -qam "local edit that rewords an anchor the chains hold"
git -C "$FAKE" commit -q --allow-empty -m "upstream moves on"
if ANCHOR_OUT="$(SKIP_BUILD=1 UPSTREAM_URL="$FAKE" ./scripts/sync-upstream.sh 2>&1)"; then
  die "a reworded anchor synced as if nothing happened"
fi
echo "$ANCHOR_OUT" | grep -q "anchor not found" ||
  die "anchor drift failed without saying so: $ANCHOR_OUT"
[ "$(git -C "$ORIGIN" rev-parse main)" = "$POST" ] || die "a failed sync pushed"
ok "anchor drift: real sync fails loudly and pushes nothing"
git reset -q --hard "$POST"

if ! FINAL="$(python3 scripts/apply-bitzylabs-branding.py --check 2>&1)"; then
  echo "$FINAL"
  die "tree did not return to green after the drift tests"
fi
ok "restored tree: validation green again"

echo
echo "ALL ASSERTIONS PASSED ($PASS assertions)"
