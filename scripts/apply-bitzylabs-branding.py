#!/usr/bin/env python3
"""Re-apply the BitzyLabs overlay on top of the upstream Bitronics flasher.

The repository tracks BitMaker-hub/bitronics-web-flasher, merging upstream
into main on every sync. The fork's own files survive that merge untouched
(never present upstream), but everything the fork changes *inside upstream's
files* -- the branding, the DevBoard Tests section, and the curation of
upstream's device catalogue (only DevBoard Tests and NerdMiner in the
picker, no Tools, no photographs behind the page) -- is re-applied here
after each sync.

It is designed to be run twice:

  * after every upstream sync, so `main` is always a complete, runnable,
    branded tree; and
  * as the first step of every deploy build, so a deploy can never ship
    Bitronics branding or a dead device picker even if somebody pushes an
    unpatched commit straight to main (the firmware bot does exactly that,
    daily).

Two kinds of edit, deliberately held to different standards:

  * Structure -- the logo, the sections, the palette, the DevBoard anchors --
    is anchored on the exact upstream text. If the anchor is gone the script
    stops and names it, because a half-applied rebrand that builds cleanly is
    far worse than a failed build.
  * Anything upstream rewrites constantly -- device lists, buy links, prose --
    is matched as a pattern instead. Upstream adds a board to devices.ts
    every few weeks; that must never be able to break a deploy. Patterns that
    no longer match mean there is nothing to do, not that the script is stale.

The fork's own files (src/lib/bitzy/*, src/components/bitzy/*, the device
pictures, the firmware folders) are paths upstream has never had, so the
merge carries them and this script only checks they arrived.

What ties it together is validation: it runs last and asserts the *end
state* (no old-brand string anywhere it can ship -- tokens, prose, URLs,
filenames, image metadata alike -- our logo, favicon and palette, the
picker scoped to DevBoard Tests + NerdMiner, Features rendered, both
DevBoard devices catalogued and wired to flash). A patch
that quietly finds nothing to do can only get past it if the result is
genuinely correct, so failing to match an anchor cannot leak Bitronics
branding or a dead device into a build.

Idempotent: running it on an already-patched tree is a no-op.

    python3 scripts/apply-bitzylabs-branding.py          # patch
    python3 scripts/apply-bitzylabs-branding.py --check  # verify only

Exit codes: 0 clean / patched, 1 anchor missing or validation failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- The brand -------------------------------------------------------------

# Bitzy Crimson as the brand guide locks it (docs/BRAND.md, the same file the
# store ships -- "do not substitute"): #DC143C, not the #DB092A this fork
# first sampled from the logo artwork. The store wins; it is the authority,
# and the flasher has to read as the same house.
CRIMSON = "#DC143C"
CRIMSON_PREV = "#DB092A"  # this fork's first crimson; the palette carries both forms
CRIMSON_DEEP = "#B01030"  # the store's gradient's dark end, legible on light
INK_ON_CRIMSON = "#FFFFFF"

# The rest of the store's locked anchors, taken from bitzystore's styles.css
# so the two sites are one scheme rather than two takes on the same red.
STORE_BG = "#F7F6F3"  # the warm off-white ground
STORE_INK = "#222222"  # Bitzy Dark Grey
STORE_LINE = "#E7E4DE"
STORE_MUTED = "#6D6A64"

SITE = "https://www.bitzylabs.com"
DOMAIN = "flasher.bitzylabs.com"
BRAND = "Bitzy Labs"

ASSETS = ROOT / ".bitzylabs-overlay" / "assets"
LOGO_DARK = "bitzylabs-logo-dark.png"  # crimson mark + white wordmark
LOGO_LIGHT = "bitzylabs-logo-light.png"  # crimson mark + ink wordmark

# Every string that must not survive into a deploy. #DB092A is this fork's
# first crimson: the store's guide overrode it, so it is as dead as the
# yellow was.
FORBIDDEN = ("bitronics.store", "#ECD400", "#4A4200", "#7A6D00", "#DB092A")

# Any Bitronics URL, however it was written: subdomain, path, query. Anchored
# on the domain rather than on surrounding code so upstream restructuring a
# component cannot slip a new link past it.
BITRONICS_URL = re.compile(
    r"""https?://(?:[a-z0-9-]+\.)*bitronics\.store[^\s'"`)\\]*""", re.IGNORECASE
)

# Whole word-marks only. Word boundaries matter: bitronics-web-flasher in
# the footer credit and in this repo's own tooling has to survive for
# validation to allow it, and a filename must fail loudly rather than be
# rewritten into a path that does not exist.
WORD_MARK = re.compile(r"\bBitronics\b")
UPPER_MARK = re.compile(r"\bBITRONICS\b")

# The black gradient this fork shipped before the store's scheme arrived.
# Kept only as an anchor: patch_backgrounds finds it in the working tree and
# carries it to the new state, where CSS paints the canvas and JS paints
# nothing at all.
PAGE_GRADIENT = "linear-gradient(180deg, #0e0e13 0%, #0a0a0d 55%, #070709 100%)"

# The firmware folders the picker can actually reach. Everything else under
# public/firmware is a device this fork does not offer and is pruned before
# every build: the sync (-X theirs on a delete) and the nightly updater can
# both bring folders back, and one of them carries the old brand name
# inside its bytes.
SERVED_FIRMWARE = ("esp32s3-smoothblinky", "nerdminer", "stm32-bluepill")

# The upstream repository's real name. It is the only old-brand string
# allowed to survive the zero-trace scan, and only where the reader asked
# for a credit linking to it (the footer, and sync's own description of
# what it syncs).
UPSTREAM_REPO_PATH = "BitMaker-hub/bitronics-web-flasher"


class PatchError(RuntimeError):
    """Upstream moved the ground; refuse to guess."""


def log(msg: str) -> None:
    print(f"  {msg}")


def note(changed: bool, msg: str) -> None:
    log(msg if changed else f"{msg}  (already applied)")


def replace_once(path: Path, old: str, new: str, *, required: bool = True) -> bool:
    """Replace `old` with `new`, exactly once. Returns True if it changed."""
    text = path.read_text()
    # Wrapping patches keep the original anchor inside the replacement (the
    # old text survives in an `else` branch), so "anchor is gone" is not the
    # only sign of having run: if the whole replacement is already there and
    # the anchor only exists inside it, this is a second run and re-wrapping
    # would nest the patch one level deeper each time. Removals (new == '')
    # keep the old behaviour: an empty replacement is trivially "in the text",
    # so a vanished anchor reads as already applied rather than as an error.
    if new in text and (old not in text or old in new):
        return False  # already applied
    if old not in text:
        if required:
            raise PatchError(
                f"{path.relative_to(ROOT)}: anchor not found -- upstream changed this file.\n"
                f"  anchor was: {old.splitlines()[0][:90]!r}"
                f"{'...' if len(old.splitlines()) > 1 else ''}"
            )
        return False
    if text.count(old) != 1:
        raise PatchError(
            f"{path.relative_to(ROOT)}: anchor matched {text.count(old)} times, expected 1"
        )
    path.write_text(text.replace(old, new, 1))
    return True


def inject_once(path: Path, marker: str, old: str, new: str) -> bool:
    """Apply an injection unless its own output is already in the file.

    replace_once recognises an applied patch by finding the whole
    replacement verbatim (or the anchor inside it, for wrappers). Neither
    holds when upstream also edited *around* the anchor: a device row added
    between our rows and the original neighbour means the replacement no
    longer appears anywhere, while the anchor is gone because we consumed
    it -- a correct merged state that would read as a missing anchor. The
    marker is a line only this patch writes, so its presence settles the
    question either way. Absent marker plus absent anchor still fails
    loudly through replace_once: then the work is genuinely not done and
    the file has moved out from under us.
    """
    if marker in path.read_text():
        return False
    return replace_once(path, old, new)


def inject_rows(path: Path, decl: str, block: str, marker: str) -> bool:
    """Insert `block` straight after the declaration line `decl`.

    Marker-gated like inject_once, but the anchor is the declaration
    itself: upstream's own additions land after ours without disturbing
    it, so nothing here depends on who currently holds the first row --
    and ours being first is the whole point, because the picker renders
    these lists in order. The sync resolves conflicts toward upstream
    (-X theirs), so when upstream rewrites one of these files our rows
    can come back gone; marker absent then means re-insert them.
    """
    text = path.read_text()
    if marker in text:
        return False
    if decl not in text:
        raise PatchError(
            f"{path.relative_to(ROOT)}: anchor not found -- upstream changed this file.\n"
            f"  anchor was: {decl.splitlines()[0][:90]!r}"
        )
    if text.count(decl) != 1:
        raise PatchError(
            f"{path.relative_to(ROOT)}: anchor matched {text.count(decl)} times, expected 1"
        )
    path.write_text(text.replace(decl, decl + block, 1))
    return True


def inject_category_type() -> bool:
    """Append our value to the DeviceCategory union, however they wrote it."""
    path = ROOT / "src" / "lib" / "devices.ts"
    text = path.read_text()
    match = re.search(r"^export type DeviceCategory = ([^;\n]+);$", text, re.M)
    if not match:
        raise PatchError(
            "src/lib/devices.ts: anchor not found -- upstream changed this file.\n"
            "  anchor was: 'export type DeviceCategory ='"
        )
    if "'devboards'" in match.group(1):
        return False
    path.write_text(text[: match.end(1)] + " | 'devboards'" + text[match.end(1) :])
    return True


def inject_mcu_field() -> bool:
    """Give DeviceSource the field that says which flasher a device needs."""
    path = ROOT / "src" / "lib" / "devices.ts"
    text = path.read_text()
    if "mcu?: 'esp32' | 'stm32';" in text:
        return False
    anchor = re.search(r"^  detectChip\?: boolean;$", text, re.M)
    if not anchor:
        raise PatchError(
            "src/lib/devices.ts: anchor not found -- upstream changed this file.\n"
            "  anchor was: '  detectChip?: boolean;'"
        )
    block = (
        "\n  /**\n"
        "   * Which silicon the device's flasher talks to. Absent means the esptool\n"
        "   * path every miner and tool takes; 'stm32' takes the ROM bootloader path.\n"
        "   */\n"
        "  mcu?: 'esp32' | 'stm32';"
    )
    path.write_text(text[: anchor.end()] + block + text[anchor.end() :])
    return True


def inject_picker_tiles() -> bool:
    """Add the two devboard tiles to whatever JSON style the file wears.

    Upstream regenerates this table whenever it publishes firmware, and
    the sync resolves that rewrite in their own favour -- the whole file
    comes back in their formatting with our rows gone, which the sync
    harness caught in its first run. The markers say whether our rows
    survived; the `"devices": [` line, however it is indented, says where
    they go.
    """
    path = ROOT / "src" / "components" / "firmware_data.json"
    text = path.read_text()

    tiles = (("ESP 32 N16R8", "esp32-n16r8"), ("STM 32 BluePill", "stm32-bluepill"))
    missing = [(n, p) for n, p in tiles if f'"name": "{n}",' not in text]
    if not missing:
        return False

    head = re.search(r'^([ \t]*)"devices": \[\n', text, re.M)
    if not head:
        raise PatchError(
            "src/components/firmware_data.json: anchor not found -- upstream "
            "changed this file.\n  anchor was: '\"devices\": ['"
        )
    level1 = head.group(1)
    level2 = level1 + level1
    level3 = level2 + level1
    rows = "".join(
        f"{level2}{{\n"
        f'{level3}"name": "{name}",\n'
        f'{level3}"picture": "pictures/{picture}.png",\n'
        f'{level3}"boards": []\n'
        f"{level2}}},\n"
        for name, picture in missing
    )
    path.write_text(text[: head.end()] + rows + text[head.end() :])
    return True


def replace_if_present(path: Path, old: str, new: str) -> bool:
    """Replace `old` with `new`, but stay quiet when `old` is simply gone.

    Used where upstream may reasonably reword the text: a missing anchor then
    means there is nothing left to rebrand, which is the outcome we wanted.
    Validation decides whether the end state is acceptable either way.
    """
    return replace_once(path, old, new, required=False)


def replace_everywhere(path: Path, old: str, new: str) -> bool:
    """Replace every occurrence of `old`, quiet when there are none.

    For strings that appear more than once by design -- the footer's credit
    links all hover the same way, and the header's nav and instructions
    button are styled identically -- where replace_once's single-match rule
    would raise on a count we *want* to be plural.
    """
    text = path.read_text()
    if old not in text:
        return False
    path.write_text(text.replace(old, new))
    return True


def drop_lines(path: Path, predicate) -> bool:
    """Delete every line for which predicate(line) is true. Returns True if any went."""
    lines = path.read_text().splitlines(keepends=True)
    kept = [line for line in lines if not predicate(line)]
    if len(kept) == len(lines):
        return False
    path.write_text("".join(kept))
    return True


# --- The individual patches ------------------------------------------------


def patch_cname() -> None:
    path = ROOT / "public" / "CNAME"
    target = DOMAIN + "\n"
    changed = path.read_text() != target
    path.write_text(target)
    note(changed, f"CNAME -> {DOMAIN}")


def patch_assets() -> None:
    dest = ROOT / "public" / "pictures"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (LOGO_DARK, LOGO_LIGHT):
        source = ASSETS / name
        if not source.is_file() or source.stat().st_size == 0:
            raise PatchError(f"missing logo asset: {source.relative_to(ROOT)}")
        target = dest / name
        changed = not target.is_file() or target.read_bytes() != source.read_bytes()
        if changed:
            shutil.copyfile(source, target)
        note(changed, f"assets: {name} -> public/pictures/")
    # The favicon: upstream ships its own at this path, so ours overwrites it
    # the same way the logos do; the .ico is the file every browser falls
    # back to when it cannot read an SVG. The logo tile is this fork's own
    # file (no upstream path to collide with) and globals.css points at it
    # by name, so a missing copy would ship as a background that 404s.
    for name, target in (
        ("favicon.svg", dest / "favicon.svg"),
        ("favicon.ico", ROOT / "public" / "favicon.ico"),
        ("logo-tile.svg", dest / "logo-tile.svg"),
    ):
        source = ASSETS / name
        if not source.is_file() or source.stat().st_size == 0:
            raise PatchError(f"missing favicon asset: {source.relative_to(ROOT)}")
        changed = not target.is_file() or target.read_bytes() != source.read_bytes()
        if changed:
            shutil.copyfile(source, target)
        note(changed, f"assets: {name} -> {target.relative_to(ROOT)}")
    # The upstream wordmarks are not ours and are no longer referenced; the
    # dark tile went the band's way -- the light one now tiles that too --
    # and its copy would ship as an orphaned 40k file if left behind.
    for stale in ("bitronics-logo-dark.svg", "bitronics-logo-light.svg", "logo-tile-dark.svg"):
        stale_path = dest / stale
        if stale_path.exists():
            stale_path.unlink()
            log(f"assets: removed public/pictures/{stale}")


def patch_header() -> None:
    path = ROOT / "src" / "components" / "Header.tsx"
    # The nav and the logo's own href may be reworded freely -- the sweep
    # catches their URLs whatever they are -- but the logo itself is
    # structural: miss it and the site renders a wordmark we just deleted.
    changed = replace_if_present(
        path,
        "  { label: 'Shop', href: 'https://bitronics.store/collections/best-sellers' },\n"
        "  { label: 'Pool', href: 'https://pool.bitronics.store' },\n"
        "  { label: 'Wiki', href: 'https://bitronics.store/pages/knowledge-base' },\n"
        "  { label: 'Blog', href: 'https://bitronics.store/blogs/knowledge-base' },\n",
        f"  {{ label: 'Shop', href: '{SITE}' }},\n",
    )
    changed |= replace_if_present(path, 'href="https://bitronics.store"', f'href="{SITE}"')
    # The logo is the way back to the flasher itself; the Shop entry in the
    # nav array above is what points at the store.
    changed |= replace_once(
        path,
        '          href="https://www.bitzylabs.com"\n',
        f'          href="https://{DOMAIN}"\n',
    )
    # The bar went to the store's white, so the wordmark goes to the ink
    # one. Two source forms because upstream ships a bitronics svg and this
    # fork has already shipped the dark PNG on top of it; whichever is
    # found lands on the light PNG, and a third run skips over all of them.
    light_logo = (
        "            src={`${basePath}/pictures/bitzylabs-logo-light.png`}\n"
        f'            alt="{BRAND}"\n'
        '            className="h-8 w-auto object-contain"\n'
    )
    changed |= replace_if_present(
        path,
        "            src={`${basePath}/pictures/bitronics-logo-dark.svg`}\n"
        '            alt="Bitronics"\n'
        '            className="h-7 w-auto"\n',
        light_logo,
    )
    changed |= replace_if_present(
        path,
        "            src={`${basePath}/pictures/bitzylabs-logo-dark.png`}\n"
        f'            alt="{BRAND}"\n'
        '            className="h-8 w-auto object-contain"\n',
        light_logo,
    )
    changed |= replace_if_present(
        path,
        "{/* The BITRONICS + FLASHER lockup, the same shape the pool site uses */}",
        "{/* The Bitzy Labs + FLASHER lockup */}",
    )
    # The bar's own comment, which upstream ships in the same words we do.
    changed |= replace_once(
        path,
        "{/* The bar is always dark, so the wordmark is always the light one */}",
        "{/* The bar is the store's white blur, so the wordmark is the ink one */}",
    )
    # The nav itself: the reader wants both links bigger and both *in the
    # middle* of the bar, so the instructions button moves out of the
    # right-hand slot into the centred nav beside Shop. What stays right
    # is a small-screen copy (the nav is hidden below md, and the drawer
    # has to remain reachable), which is why the right slot keeps its
    # flex-1 -- without it the centred nav would drift off centre. The
    # reveal is untouched: the panel still slides from the same right
    # edge wherever its trigger now sits. Two source forms: upstream's
    # white-on-dark pair, and this fork's first muted pair.
    final_nav = (
        '        <nav className="hidden flex-1 items-center justify-center gap-7 md:flex">\n'
        "          {SITE_LINKS.map((link) => (\n"
        "            <a\n"
        "              key={link.label}\n"
        "              href={link.href}\n"
        '              target="_blank"\n'
        '              rel="noopener noreferrer"\n'
        '              className="text-base font-medium text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)]"\n'
        "            >\n"
        "              {link.label}\n"
        "            </a>\n"
        "          ))}\n"
        "          <button\n"
        "            onClick={onOpenPanel}\n"
        '            className="text-base font-medium text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)]"\n'
        "          >\n"
        "            {t('header.instructions')}\n"
        "          </button>\n"
        "        </nav>\n"
        "\n"
        '        <div className="flex flex-1 items-center justify-end gap-4 sm:gap-5">\n'
        "          <button\n"
        "            onClick={onOpenPanel}\n"
        '            className="text-sm font-medium text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)] md:hidden"\n'
        "          >\n"
        "            {t('header.instructions')}\n"
        "          </button>\n"
        "        </div>\n"
    )
    changed |= replace_if_present(
        path,
        '        <nav className="hidden flex-1 items-center justify-center gap-7 md:flex">\n'
        "          {SITE_LINKS.map((link) => (\n"
        "            <a\n"
        "              key={link.label}\n"
        "              href={link.href}\n"
        '              target="_blank"\n'
        '              rel="noopener noreferrer"\n'
        '              className="text-sm font-medium text-white/70 transition-colors '
        'hover:text-white"\n'
        "            >\n"
        "              {link.label}\n"
        "            </a>\n"
        "          ))}\n"
        "        </nav>\n"
        "\n"
        '        <div className="flex flex-1 items-center justify-end gap-4 sm:gap-5">\n'
        "          <button\n"
        "            onClick={onOpenPanel}\n"
        '            className="text-sm font-medium text-white/70 transition-colors '
        'hover:text-white"\n'
        "          >\n"
        "            {t('header.instructions')}\n"
        "          </button>\n"
        "        </div>\n",
        final_nav,
    )
    changed |= replace_if_present(
        path,
        '        <nav className="hidden flex-1 items-center justify-center gap-7 md:flex">\n'
        "          {SITE_LINKS.map((link) => (\n"
        "            <a\n"
        "              key={link.label}\n"
        "              href={link.href}\n"
        '              target="_blank"\n'
        '              rel="noopener noreferrer"\n'
        '              className="text-sm font-medium text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)]"\n'
        "            >\n"
        "              {link.label}\n"
        "            </a>\n"
        "          ))}\n"
        "        </nav>\n"
        "\n"
        '        <div className="flex flex-1 items-center justify-end gap-4 sm:gap-5">\n'
        "          <button\n"
        "            onClick={onOpenPanel}\n"
        '            className="text-sm font-medium text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)]"\n'
        "          >\n"
        "            {t('header.instructions')}\n"
        "          </button>\n"
        "        </div>\n",
        final_nav,
    )
    # Safety net for any other identical link/button styling a reword
    # leaves behind; quiet once the block above has landed.
    changed |= replace_everywhere(
        path,
        'className="text-sm font-medium text-white/70 transition-colors hover:text-white"',
        'className="text-sm font-medium text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)]"',
    )
    note(
        changed,
        "Header.tsx: light wordmark, centred nav at store size, logo, site link",
    )


def patch_instruction_panel() -> None:
    """The steps drawer leaves the dark half behind with everything else.

    It was upstream's dark card -- chrome ground, white text -- the one
    piece of chrome that still read as the old site once the bar, the
    canvas and the footer all went light. Now it is the store's own
    pairing: white ground, ink headings, store-muted body copy,
    hairline-light dividers, the crimson step numbers staying crimson
    (they are a fill's hue, used here as text on white the same way the
    store uses it on its light ground). Only the surface moves; the
    reveal is the same slide from the same right edge.
    """
    path = ROOT / "src" / "components" / "InstructionPanel.tsx"
    changed = replace_if_present(
        path,
        "flex-col border-l border-[var(--color-hairline)] "
        "bg-[var(--color-chrome)] text-white shadow-2xl",
        "flex-col border-l border-[var(--color-hairline-light)] "
        "bg-white text-[var(--color-ink)] shadow-2xl",
    )
    changed |= replace_everywhere(
        path,
        "border-b border-[var(--color-hairline)]",
        "border-b border-[var(--color-hairline-light)]",
    )
    changed |= replace_everywhere(
        path,
        "border-t border-[var(--color-hairline)]",
        "border-t border-[var(--color-hairline-light)]",
    )
    # Everything the dark ground was carrying: the close button's white
    # (to store-muted, crimson on the hover the whole bar now uses), the
    # step copy (to ink), the footnote (to the muted of a light surface).
    changed |= replace_if_present(
        path,
        "rounded-lg p-1.5 text-white/50 transition-colors hover:bg-white/5 hover:text-white",
        "rounded-lg p-1.5 text-[var(--color-muted-warm)] transition-colors "
        "hover:bg-black/5 hover:text-[var(--color-bitzy)]",
    )
    changed |= replace_if_present(
        path,
        'className="text-sm leading-relaxed text-white/70"',
        'className="text-sm leading-relaxed text-[var(--color-ink)]/70"',
    )
    changed |= replace_if_present(
        path,
        "px-6 py-4 text-xs leading-relaxed text-white/40",
        "px-6 py-4 text-xs leading-relaxed text-[var(--color-muted-warm)]",
    )
    note(changed, "InstructionPanel.tsx: white drawer, light dividers, ink text")


def patch_instructions_toggle() -> None:
    """The bar's Instructions control opens the drawer and shuts it again.

    Upstream's wiring is one-way -- the trigger forces the state open and
    only the drawer's own close button ever resets it -- so a second click
    on Instructions did nothing at all while the drawer sat over the page.
    Nothing structural stands in the way: the drawer starts below the bar
    (top-20) and its backdrop is z-40 against the bar's z-50, so the control
    stays reachable while open. What needs changing is the handler (flip
    rather than force), the prop that names it (it no longer only opens),
    and the state riding down to the triggers so aria-expanded can say
    whether the next click closes or opens. Both trigger copies -- the
    centred nav's and the small-screen one -- take it from the same line.

    Header's own chains land first (patch_header owns that file's text);
    this runs after them and carries what they land, whichever of the
    three shipped forms it finds.
    """
    header = ROOT / "src" / "components" / "Header.tsx"
    landing = ROOT / "src" / "components" / "LandingHero.tsx"

    changed = replace_if_present(
        header,
        "interface HeaderProps {\n  onOpenPanel: () => void;\n}",
        "interface HeaderProps {\n"
        "  onTogglePanel: () => void;\n"
        "  /** Whether the steps drawer is showing, for aria-expanded on the triggers. */\n"
        "  panelOpen: boolean;\n"
        "}",
    )
    changed |= replace_if_present(
        header,
        "export default function Header({ onOpenPanel }: HeaderProps) {",
        "export default function Header({ onTogglePanel, panelOpen }: HeaderProps) {",
    )
    # Both triggers sit on the same indented line, so one replacement moves
    # the pair together: the rename and the state report in a single pass,
    # and the anchor -- the old name is part of it -- cannot match its own
    # output on a second run.
    changed |= replace_everywhere(
        header,
        "            onClick={onOpenPanel}\n",
        "            onClick={onTogglePanel}\n"
        "            aria-expanded={panelOpen}\n",
    )
    # Whatever shape the two forms above did not name: the one-way name is
    # the part that must not survive, whichever line it sits on.
    changed |= replace_everywhere(header, "onOpenPanel", "onTogglePanel")
    # The state itself: force-open becomes a flip, and the open flag rides
    # down for aria-expanded.
    changed |= replace_if_present(
        landing,
        "<Header onOpenPanel={() => setIsPanelOpen(true)} />",
        "<Header onTogglePanel={() => setIsPanelOpen((wasOpen) => !wasOpen)} "
        "panelOpen={isPanelOpen} />",
    )
    note(
        changed,
        "Header.tsx: Instructions toggles the drawer open and shut, state reported",
    )


def patch_footer() -> None:
    path = ROOT / "src" / "components" / "Footer.tsx"
    changed = replace_if_present(
        path,
        "  { label: 'Shop', href: 'https://bitronics.store/collections/best-sellers' },\n"
        "  { label: 'Pool', href: 'https://pool.bitronics.store' },\n"
        "  { label: 'Wiki', href: 'https://bitronics.store/pages/knowledge-base' },\n"
        "  { label: 'Blog', href: 'https://bitronics.store/blogs/knowledge-base' },\n"
        "  { label: 'Contact', href: 'https://bitronics.store/pages/contact-form' },\n",
        f"  {{ label: 'Shop', href: '{SITE}' }},\n",
    )
    # The wordmark goes with the header's: light on the store's white
    # ground. Upstream ships a bitronics svg, this fork has already shipped
    # the dark PNG; whichever is found lands on the light PNG.
    light_logo = (
        "                src={`${basePath}/pictures/bitzylabs-logo-light.png`}\n"
        f'                alt="{BRAND}"\n'
        '                className="h-7 w-auto object-contain"\n'
    )
    changed |= replace_if_present(
        path,
        "                src={`${basePath}/pictures/bitronics-logo-dark.svg`}\n"
        '                alt="Bitronics"\n'
        '                className="h-6 w-auto"\n',
        light_logo,
    )
    changed |= replace_if_present(
        path,
        "                src={`${basePath}/pictures/bitzylabs-logo-dark.png`}\n"
        f'                alt="{BRAND}"\n'
        '                className="h-7 w-auto object-contain"\n',
        light_logo,
    )
    changed |= replace_if_present(path, ">Bitronics</h3>", ">BitzyLabs</h3>")
    changed |= replace_if_present(
        path, "<span>© {new Date().getFullYear()} Bitronics</span>",
        "<span>© {new Date().getFullYear()} BitzyLabs</span>",
    )
    # The firmware column credits other projects' repos rather than linking to
    # Bitronics, but it is a column of the store's navigation and it goes with
    # the rest of the navigation. The comment goes with the array: without the
    # links beneath it, "where each firmware actually comes from" says nothing.
    changed |= replace_if_present(
        path,
        "// Where each firmware actually comes from. Saying so in the footer is the\n"
        "// cheapest form of honesty: this site only re-serves other people's builds.\n",
        "",
    )
    changed |= replace_once(
        path,
        "const FIRMWARE_LINKS = [\n"
        "  { label: 'Bitaxe', href: 'https://github.com/bitaxeorg/ESP-Miner' },\n"
        "  { label: 'NerdQaxe & Octaxe', href: 'https://github.com/shufps/ESP-Miner-NerdQAxePlus' },\n"
        "  { label: 'NerdMiner', href: 'https://github.com/BitMaker-hub/NerdMiner_v2' },\n"
        "  { label: 'Seeder', href: 'https://github.com/BitMaker-hub/Seeder' },\n"
        "];\n"
        "\n",
        "",
    )
    changed |= replace_once(
        path,
        "          <div>\n"
        "            <h3 className=\"font-display text-sm font-bold tracking-tight\">Firmware</h3>\n"
        "            <ul className=\"mt-4 space-y-2.5\">\n"
        "              {FIRMWARE_LINKS.map((link) => (\n"
        "                <li key={link.label}>\n"
        "                  <a\n"
        "                    href={link.href}\n"
        "                    target=\"_blank\"\n"
        "                    rel=\"noopener noreferrer\"\n"
        "                    className={linkClass}\n"
        "                  >\n"
        "                    {link.label}\n"
        "                  </a>\n"
        "                </li>\n"
        "              ))}\n"
        "            </ul>\n"
        "          </div>\n"
        "\n",
        "",
    )
    # The reader asked for these by name: the flasher this fork is built on,
    # and -- from the moment the Blue Pill's path moved to WebUSB -- the
    # ST-Link donor the reader picked, Hypothesis-Magic/stm32-web-flasher.
    # The first trade still writes the upstream-era credits: it is what a
    # fresh sync starts from. The second, run after the class sweep above
    # has carried those links to the store's footer, swaps the two Web
    # Serial names for that donor -- so both syncs land on the same three
    # names. The upstream repo's name inside the BitMaker link is the one
    # old-brand string validation lets survive, and only in here.
    changed |= inject_once(
        path,
        "              <span>Credits to</span>\n",
        "            <a\n"
        '              href="https://github.com/WantClue"\n'
        "              target=\"_blank\"\n"
        "              rel=\"noopener noreferrer\"\n"
        '              className="transition-colors hover:text-white/70"\n'
        "            >\n"
        "              Credits to WantClue\n"
        "            </a>\n",
        '            <div className="flex flex-wrap items-center gap-x-3">\n'
        "              <span>Credits to</span>\n"
        "              <a\n"
        '                href="https://github.com/WantClue"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-white/70"\n'
        "              >\n"
        "                WantClue\n"
        "              </a>\n"
        '              <span aria-hidden="true">·</span>\n'
        "              <a\n"
        f'                href="https://github.com/{UPSTREAM_REPO_PATH}"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-white/70"\n'
        "              >\n"
        "                BitMaker\n"
        "              </a>\n"
        '              <span aria-hidden="true">·</span>\n'
        "              <a\n"
        '                href="https://github.com/Gamadril/stm-serial-flasher"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-white/70"\n'
        "              >\n"
        "                Gamadril\n"
        "              </a>\n"
        '              <span aria-hidden="true">·</span>\n'
        "              <a\n"
        '                href="https://github.com/yanxke/stm32webflash"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-white/70"\n'
        "              >\n"
        "                Yanxke\n"
        "              </a>\n"
        "            </div>\n",
    )
    # Two columns remain, so two columns is what the grid must ask for.
    changed |= replace_once(path, "md:grid-cols-3", "md:grid-cols-2")
    # The footer goes to the store's own: white ground, ink text, muted
    # links that turn crimson on hover -- styles.css does exactly this on
    # its footer -- and the hairline above the bottom bar. The Notice
    # dialog keeps its dark surface; it is an overlay, and overlays are
    # dark in the store too. Its inherited mt-16 goes with it: 64px of
    # margin stacked on the band above's own bottom padding is the blank
    # space the reader keeps pointing at, and the colour change already
    # separates the two without it. Two source forms, upstream's dark
    # footer and this fork's white one, both landing on mt-8.
    changed |= replace_if_present(
        path,
        '<footer className="mt-16 w-full border-t border-[var(--color-hairline)] '
        'bg-[var(--color-chrome)] text-white">',
        '<footer className="mt-8 w-full border-t border-[var(--color-hairline-light)] '
        'bg-white text-[var(--color-ink)]">',
    )
    changed |= replace_if_present(
        path,
        '<footer className="mt-16 w-full border-t border-[var(--color-hairline-light)] '
        'bg-white text-[var(--color-ink)]">',
        '<footer className="mt-8 w-full border-t border-[var(--color-hairline-light)] '
        'bg-white text-[var(--color-ink)]">',
    )
    changed |= replace_once(
        path,
        "const linkClass = 'text-sm text-white/60 transition-colors hover:text-white';",
        "const linkClass = 'text-sm text-[var(--color-muted-warm)] "
        "transition-colors hover:text-[var(--color-bitzy)]';",
    )
    changed |= replace_once(
        path,
        '<p className="mt-4 max-w-xs text-sm leading-relaxed text-white/60">',
        '<p className="mt-4 max-w-xs text-sm leading-relaxed text-[var(--color-muted-warm)]">',
    )
    changed |= replace_once(
        path,
        '<div className="border-t border-[var(--color-hairline)]">',
        '<div className="border-t border-[var(--color-hairline-light)]">',
    )
    changed |= replace_once(
        path,
        "text-xs text-white/40",
        "text-xs text-[var(--color-muted-warm)]",
    )
    # Terms, Privacy and every credit share one class string upstream and
    # in the block injected above; one sweep carries all of them to the
    # store's footer behaviour -- muted at rest, crimson on hover.
    changed |= replace_everywhere(
        path,
        'className="transition-colors hover:text-white/70"',
        'className="transition-colors hover:text-[var(--color-bitzy)]"',
    )
    # The terms, privacy and credits now carry the store's class strings,
    # so the credit swap runs against the same text on a fresh sync and on
    # this fork's current footer: the Web Serial pair goes, the ST-Link
    # donor the reader chose takes their place.
    changed |= inject_once(
        path,
        "Hypothesis-Magic",
        "              <span aria-hidden=\"true\">·</span>\n"
        "              <a\n"
        '                href="https://github.com/Gamadril/stm-serial-flasher"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-[var(--color-bitzy)]"\n'
        "              >\n"
        "                Gamadril\n"
        "              </a>\n"
        "              <span aria-hidden=\"true\">·</span>\n"
        "              <a\n"
        '                href="https://github.com/yanxke/stm32webflash"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-[var(--color-bitzy)]"\n'
        "              >\n"
        "                Yanxke\n"
        "              </a>\n",
        "              <span aria-hidden=\"true\">·</span>\n"
        "              <a\n"
        '                href="https://github.com/Hypothesis-Magic/stm32-web-flasher"\n'
        '                target="_blank"\n'
        '                rel="noopener noreferrer"\n'
        '                className="transition-colors hover:text-[var(--color-bitzy)]"\n'
        "              >\n"
        "                Hypothesis-Magic\n"
        "              </a>\n",
    )
    # The privacy/terms notice is a small dialog over the page; the page is
    # light now, so it reads like every other surface -- white card, ink
    # title, store-muted body, crimson on the close. The scrim behind it
    # stays: a scrim is not a surface.
    changed |= replace_if_present(
        path,
        '<div className="relative w-full max-w-md rounded-xl border '
        'border-[var(--color-hairline)] bg-[var(--color-surface)] p-6 text-white">',
        '<div className="relative w-full max-w-md rounded-xl border '
        'border-[var(--color-hairline-light)] bg-white p-6 text-[var(--color-ink)]">',
    )
    changed |= replace_if_present(
        path,
        'className="absolute right-4 top-4 text-white/50 transition-colors hover:text-white"',
        'className="absolute right-4 top-4 text-[var(--color-muted-warm)] '
        'transition-colors hover:text-[var(--color-bitzy)]"',
    )
    changed |= replace_if_present(
        path,
        '<p className="mt-2 text-sm text-white/60">{body}</p>',
        '<p className="mt-2 text-sm text-[var(--color-muted-warm)]">{body}</p>',
    )
    note(
        changed,
        "Footer.tsx: store's white ground, light wordmark, credits, footer colours",
    )


def patch_shop_strip() -> None:
    path = ROOT / "src" / "components" / "ShopStrip.tsx"
    changed = replace_if_present(
        path, 'href="https://bitronics.store/collections/best-sellers"', f'href="{SITE}"'
    )
    # The band reads as an offer, not a shout: white with a crimson edge and
    # crimson text instead of a solid crimson fill. The reader then asked for
    # more presence: a border ~80% thicker and a taller band around it. The
    # border is 2px, not the literal 1.8px: browsers floor fractional border
    # widths to whole device pixels (a computed 1.8px reads back as 1px at
    # standard DPI, i.e. no change at all), and 2px is the first width that
    # actually renders heavier -- at retina scale it snaps to the same
    # physical thickness 1.8px would have. -bitzy spelled directly so the
    # sweep below leaves these anchors alone; three source forms because
    # this fork has already shipped two of them, and whichever is found is
    # carried to one state.
    final_class = (
        '      className="group flex w-full items-center justify-center gap-2 '
        'border-[2px] border-[var(--color-bitzy)] bg-white px-6 py-5 text-center '
        'text-[var(--color-bitzy)] transition-opacity hover:opacity-90"\n'
    )
    for source in (
        # Upstream: the solid crimson (band-gold) fill.
        '      className="band-gold group flex w-full items-center justify-center gap-2 px-4 py-3 text-center transition-opacity hover:opacity-90"\n',
        # This fork's first white band: 1px border, py-3.
        '      className="group flex w-full items-center justify-center gap-2 border border-[var(--color-bitzy)] bg-white px-4 py-3 text-center text-[var(--color-bitzy)] transition-opacity hover:opacity-90"\n',
        # Then the same band with a fractional 1.8px border.
        '      className="group flex w-full items-center justify-center gap-2 border-[1.8px] border-[var(--color-bitzy)] bg-white px-6 py-5 text-center text-[var(--color-bitzy)] transition-opacity hover:opacity-90"\n',
    ):
        changed |= replace_if_present(path, source, final_class)
    note(changed, "ShopStrip.tsx: white band, crimson border at 2px, taller")


def patch_features() -> None:
    """The Key Features band keeps its content and loses its air.

    Two passes over the same section: first the ends (the strip's crimson
    border sits directly above, the footer directly below), then the
    interior on the reader's second look: the heading's drop to the cards,
    the gutters between them, the card insets and the icon's lead-in.
    Every anchor carries two source forms -- upstream's original and this
    fork's first tightening -- so a tree at either state lands on the
    tight one instead of raising on a stale anchor. Kicker, heading and
    card content keep upstream's rhythm.
    """
    path = ROOT / "src" / "components" / "Features.tsx"
    changed = replace_if_present(
        path,
        'className="band-light w-full py-16 md:py-24"',
        'className="band-light w-full py-6 md:py-8"',
    )
    changed |= replace_if_present(
        path,
        'className="band-light w-full py-8 md:py-12"',
        'className="band-light w-full py-6 md:py-8"',
    )
    for old, new in (
        ('className="mb-10 text-center"', 'className="mb-4 text-center"'),
        ('className="mb-6 text-center"', 'className="mb-4 text-center"'),
        (
            'className="grid gap-4 md:grid-cols-3"',
            'className="grid gap-2.5 md:grid-cols-3"',
        ),
        (
            'className="grid gap-3 md:grid-cols-3"',
            'className="grid gap-2.5 md:grid-cols-3"',
        ),
        (
            'className="rounded-xl border border-[var(--color-hairline-light)] bg-white p-6"',
            'className="rounded-xl border border-[var(--color-hairline-light)] bg-white p-3"',
        ),
        (
            'className="rounded-xl border border-[var(--color-hairline-light)] bg-white p-4"',
            'className="rounded-xl border border-[var(--color-hairline-light)] bg-white p-3"',
        ),
        (
            'className="font-display mt-4 font-bold tracking-tight text-[var(--color-ink)]"',
            'className="font-display mt-2.5 font-bold tracking-tight text-[var(--color-ink)]"',
        ),
        (
            'className="font-display mt-3 font-bold tracking-tight text-[var(--color-ink)]"',
            'className="font-display mt-2.5 font-bold tracking-tight text-[var(--color-ink)]"',
        ),
        # The card's own interior, untouched until the second look: a
        # smaller icon box and less lead-in beneath it.
        (
            'className="flex h-10 w-10 items-center justify-center rounded-lg '
            'bg-[var(--color-bitzy)] text-[var(--color-gold-ink)]"',
            'className="flex h-9 w-9 items-center justify-center rounded-lg '
            'bg-[var(--color-bitzy)] text-[var(--color-gold-ink)]"',
        ),
        (
            'className="mt-1.5 text-sm leading-relaxed text-[var(--color-ink)]/60"',
            'className="mt-1 text-sm leading-relaxed text-[var(--color-ink)]/60"',
        ),
    ):
        changed |= replace_if_present(path, old, new)
    note(
        changed,
        "Features.tsx: py-6/8 ends, mb-4 heading, gap-2.5 gutters, p-3 cards, "
        "h-9 icon",
    )


def patch_page() -> None:
    """Keep Features (the reader asked it back); drop only Releases.

    Upstream's page is LandingHero -> ShopStrip -> Features -> Releases ->
    Footer. Releases is their firmware changelog with nowhere to point now
    that releases.json is pruned, so it goes. Features -- "the key features"
    band -- stays, and if an earlier rebrand of ours removed it, the markers
    say so and the anchors below put it back where upstream keeps it.
    """
    path = ROOT / "src" / "app" / "page.tsx"

    changed = drop_lines(
        path,
        lambda line: line.strip()
        in {"import Releases from '@/components/Releases'", "<Releases />"},
    )
    changed |= inject_once(
        path,
        "<Features />",
        "        <ShopStrip />\n",
        "        <ShopStrip />\n        <Features />\n",
    )
    changed |= inject_once(
        path,
        "import Features from",
        "import ShopStrip from '@/components/ShopStrip'\n",
        "import ShopStrip from '@/components/ShopStrip'\n"
        "import Features from '@/components/Features'\n",
    )
    text = path.read_text()
    if "components/Releases'" in text or "<Releases />" in text:
        raise PatchError("page.tsx: the Releases band is still referenced")
    note(changed, "page.tsx: Features rendered, Releases gone")


def patch_layout() -> None:
    path = ROOT / "src" / "app" / "layout.tsx"
    changed = replace_if_present(
        path, "title: 'Bitronics flasher',", f"title: '{BRAND} Flasher',"
    )
    changed |= replace_if_present(
        path,
        "description: 'Flash your Bitronics devices directly from the web',",
        "description: 'Flash your mining hardware directly from the web',",
    )
    # The store ships <meta name="theme-color" content="#DC143C">; this is
    # Next 13, where the metadata export is where theme-color belongs. After
    # the title replace above, so the anchor exists on a fresh run too.
    changed |= replace_if_present(
        path,
        f"  title: '{BRAND} Flasher',\n",
        f"  themeColor: '{CRIMSON}',\n  title: '{BRAND} Flasher',\n",
    )
    note(changed, "layout.tsx: page title, description, theme-color")


def patch_palette() -> None:
    """One line per colour rather than the whole block.

    Upstream rewrites comments; they restate rarely, if ever. Anchoring each
    value alone means a reworded comment above them cannot stop the palette
    from being patched, while a genuinely changed value still fails loudly.

    The values themselves are the store's locked anchors (docs/BRAND.md,
    bitzystore's styles.css): crimson #DC143C, ink #222, warm ground
    #F7F6F3, line #E7E4DE. The flasher ships the same scheme so the two
    sites read as one house; the dark half of the palette (chrome, surface)
    moves to the store's ink, and the CTA buttons take the store's crimson.
    """
    path = ROOT / "src" / "app" / "globals.css"
    # The brand token is also *renamed* -- --color-bitronics to --color-bitzy
    # -- because "no old-brand string ships" is the end state validation
    # judges. Three forms: upstream's yellow, upstream-if-they-go-crimson,
    # and this fork's first crimson (#DB092A), whichever is found lands on
    # the store's #DC143C; the sweep afterwards renames every use, so by
    # build time define and uses agree. replace_if_present, quietly: after
    # the first run the old forms are left for the second to skip over.
    changed = replace_if_present(
        path, "--color-bitronics: #ECD400;", f"--color-bitzy: {CRIMSON};"
    )
    changed |= replace_if_present(
        path, f"--color-bitronics: {CRIMSON};", f"--color-bitzy: {CRIMSON};"
    )
    changed |= replace_once(
        path, "--color-gold-ink: #4A4200;", f"--color-gold-ink: {INK_ON_CRIMSON};"
    )
    # This fork's own comment on the token, updated when the value moved to
    # the brand guide's lock. Upstream's comment rides the same way.
    changed |= replace_if_present(
        path,
        "/* brand gold */",
        "/* brand crimson, locked by the guide the store ships */",
    )
    changed |= replace_if_present(
        path,
        "/* brand crimson, sampled from the logo */",
        "/* brand crimson, locked by the guide the store ships */",
    )
    # Two forms: upstream's yellow-brown, and this fork's first deep crimson.
    changed |= replace_if_present(
        path, "--color-gold-deep: #7A6D00;", f"--color-gold-deep: {CRIMSON_DEEP};"
    )
    changed |= replace_if_present(
        path, "--color-gold-deep: #B00722;", f"--color-gold-deep: {CRIMSON_DEEP};"
    )
    # The store's anchors, value by value. Single-match anchors: a value
    # that appears twice or not at all raises here, which is the point.
    for old, new in (
        (f"--color-bitzy: {CRIMSON_PREV};", f"--color-bitzy: {CRIMSON};"),
        ("--color-surface: #161618;", f"--color-surface: {STORE_INK};"),
        ("--color-chrome: #1B1B1D;", f"--color-chrome: {STORE_INK};"),
        ("--color-chrome-light: #26262A;", "--color-chrome-light: #3A3A3A;"),
        ("--color-ink: #1D1D1F;", f"--color-ink: {STORE_INK};"),
        ("--color-band-light: #FAFAFA;", f"--color-band-light: {STORE_BG};"),
        ("--color-hairline-light: #E2E0DA;", f"--color-hairline-light: {STORE_LINE};"),
    ):
        changed |= replace_once(path, old, new)
    # Comment only: chrome now names the panels and pickers, because the
    # header and footer went to the store's white.
    changed |= replace_if_present(
        path, "/* header and footer */", "/* the dark chrome: panels and pickers */"
    )
    # The muted of the store's light half, for text on the warm ground.
    changed |= inject_once(
        path,
        "--color-muted-warm",
        "  --color-muted-ink: #8A8A8F;\n",
        "  --color-muted-ink: #8A8A8F;\n"
        f"  --color-muted-warm: {STORE_MUTED};   /* muted text on a light surface */\n",
    )
    # The CTA buttons. forcedTheme=dark means the .dark block is the one
    # that ships, so this is where "primary" becomes the store's crimson
    # with white on it, and the focus ring takes the same hue -- the store
    # outlines focus in crimson too. Exact percentages (348 83.33% 47.06%
    # is #DC143C to the pixel): rounded to whole percents the value lands
    # a shade off, and the swatch and the button end up disagreeing. Two
    # forms: upstream's white, and this fork's first rounded crimson.
    changed |= replace_if_present(
        path,
        "    --primary: 348 83% 47%;\n    --primary-foreground: 0 0% 100%;",
        "    --primary: 348 83.33% 47.06%;\n    --primary-foreground: 0 0% 100%;",
    )
    changed |= replace_if_present(
        path,
        "    --primary: 210 40% 98%;\n    --primary-foreground: 222.2 47.4% 11.2%;",
        "    --primary: 348 83.33% 47.06%;\n    --primary-foreground: 0 0% 100%;",
    )
    changed |= replace_if_present(
        path,
        "    --ring: 348 83% 47%;",
        "    --ring: 348 83.33% 47.06%;",
    )
    changed |= replace_if_present(
        path,
        "    --ring: 212.7 26.8% 83.9%;",
        "    --ring: 348 83.33% 47.06%;",
    )
    # The rest of that block still speaks in upstream's dark scheme, and
    # forcedTheme=dark puts its class on <html>, so this is where the
    # light half of the store's palette has to be said: white where the
    # shadcn surfaces sit (the select's trigger, its list, a card), the
    # store's ink for text on them, the store's line for borders, the
    # store's muted for anything quiet. One line per token, upstream's
    # dark value as the anchor -- a value that appears twice or not at
    # all raises here, and a fresh sync brings the dark form straight
    # back for this to catch again.
    for old, new in (
        ("    --background: 0 84% 4.9%;", "    --background: 0 0% 100%;"),
        ("    --foreground: 210 40% 98%;", "    --foreground: 0 0% 13.33%;"),
        ("    --card: 0 84% 4.9%;", "    --card: 0 0% 100%;"),
        ("    --card-foreground: 210 40% 98%;", "    --card-foreground: 0 0% 13.33%;"),
        ("    --popover: 0 84% 4.9%%;", "    --popover: 0 0% 100%;"),
        ("    --popover-foreground: 210 40% 98%;", "    --popover-foreground: 0 0% 13.33%;"),
        ("    --secondary: 217.2 32.6% 17.5%;", "    --secondary: 40 20% 94%;"),
        ("    --secondary-foreground: 210 40% 98%;", "    --secondary-foreground: 0 0% 13.33%;"),
        ("    --muted: 217.2 32.6% 17.5%;", "    --muted: 40 14% 90%;"),
        ("    --muted-foreground: 215 20.2% 65.1%;", "    --muted-foreground: 41 4.3% 41%;"),
        ("    --accent: 217.2 32.6% 17.5%;", "    --accent: 40 20% 94%;"),
        ("    --accent-foreground: 210 40% 98%;", "    --accent-foreground: 0 0% 13.33%;"),
        ("    --destructive: 0 62.8% 30.6%;", "    --destructive: 0 84.2% 60.2%;"),
        # 40 15.8% 88.8% is #E7E4DE, the store's line, to the pixel.
        ("    --border: 217.2 32.6% 17.5%;", "    --border: 40 15.8% 88.8%;"),
        ("    --input: 217.2 32.6% 17.5%;", "    --input: 40 15.8% 88.8%;"),
    ):
        changed |= replace_once(path, old, new)
    # Comments only: upstream is free to restate them, the colours are not.
    # Whole block first, then the opening line on its own, so a reworded
    # middle line leaves the rest of upstream's wording behind.
    changed |= replace_if_present(
        path,
        "  /* Bitronics design system, kept in step with the store theme's brand.css.\n"
        "     Rules that come with it: one accent per block, gold is a hit and not a\n"
        "     background, mono only for figures, and gold is never text on a light\n"
        "     surface (there it is a fill or a border). */\n",
        "  /* Bitzy Labs palette on upstream's structure, values locked by the brand\n"
        "     guide the store ships. The accent rules survive: one accent per block,\n"
        "     crimson is a hit and not a background, mono only for figures, and\n"
        "     crimson is never text on a light surface (there it is a fill or a\n"
        "     border). */\n",
    )
    changed |= replace_if_present(
        path,
        "  /* Bitronics design system, kept in step with the store theme's brand.css.",
        "  /* Bitzy Labs palette on upstream's structure, values locked by the brand",
    )
    changed |= replace_if_present(
        path,
        "/* The BITRONICS + FLASHER lockup, the same shape as the POOL badge */",
        "/* The Bitzy Labs + FLASHER lockup */",
    )
    note(changed, f"globals.css: palette -> the store's anchors (crimson {CRIMSON}, ink {STORE_INK}, warm ground {STORE_BG})")


# The flasher's band, kept as its own constant: patch_chrome trades an
# already-injected tree's dark version for this one by anchoring on the
# old text, and the injection below needs the same bytes -- one definition
# for both, so they cannot drift.
HERO_CSS = (
    "/* The flasher's own band: the store's ground under the store's glow,\n"
    "   our mark tiled at the page's 512px cell, and a lift off white at\n"
    "   the top so the band separates from the fixed bar without going\n"
    "   dark -- the tool room turned into another room of the house. The\n"
    "   glow drifts on a slow loop; the reduce block below stops it. */\n"
    ".bitzy-hero {\n"
    f"  background-color: {STORE_BG};\n"
    "  background-image:\n"
    "    url('/pictures/logo-tile.svg'),\n"
    "    radial-gradient(900px 480px at 85% -20%, rgba(220, 20, 60, 0.10), transparent 60%),\n"
    "    radial-gradient(760px 520px at -12% 115%, rgba(220, 20, 60, 0.06), transparent 55%),\n"
    f"    linear-gradient(180deg, #ffffff 0%, {STORE_BG} 62%, {STORE_BG} 100%);\n"
    "  background-repeat: repeat, no-repeat, no-repeat, no-repeat;\n"
    "  background-size: 512px auto, auto, auto, auto;\n"
    "  animation: bitzy-glow 14s ease-in-out infinite alternate;\n"
    "}\n"
)

# What the band was until the flasher joined the light scheme: the dark
# tool room, on the mark's dark tile. Named only so patch_chrome can find
# it in a tree that has not run since; nothing points at it any more.
OLD_HERO_CSS = (
    "/* The hero keeps the flasher's dark identity -- the tool room the store\n"
    "   links out to -- but it is no longer flat black: the same two glows in\n"
    "   store crimson, the mark again on the dark ground, and a lift off pure\n"
    "   black so the band reads as ink rather than as an absence. The glow\n"
    "   drifts on a slow loop; the reduce block below stops it. */\n"
    ".bitzy-hero {\n"
    "  background-color: #0f0f13;\n"
    "  background-image:\n"
    "    url('/pictures/logo-tile-dark.svg'),\n"
    "    radial-gradient(900px 480px at 85% -20%, rgba(220, 20, 60, 0.16), transparent 60%),\n"
    "    radial-gradient(760px 520px at -12% 115%, rgba(220, 20, 60, 0.10), transparent 55%),\n"
    "    linear-gradient(180deg, #16161c 0%, #0f0f13 55%, #0c0c10 100%);\n"
    "  background-repeat: repeat, no-repeat, no-repeat, no-repeat;\n"
    "  background-size: 512px auto, auto, auto, auto;\n"
    "  animation: bitzy-glow 14s ease-in-out infinite alternate;\n"
    "}\n"
)

# The select's parts, pinned dark by upstream with !important because Radix
# paints its own list that would beat any token. The store's light scheme
# has to be said on this rule itself: white cards, ink text, the hairline
# edge, and a crimson wash under the cursor -- kept !important for the same
# reason upstream used it.
SELECT_LIGHT_CSS = (
    "/* Custom selector styling - more specific: the store's light scheme.\n"
    "   Radix ships its own dark list that beats the tokens, so the trigger\n"
    "   and its parts keep the !important -- white cards on the warm band,\n"
    "   ink text, the hairline edge, crimson washing the row under the\n"
    "   cursor (the chips keep their solid crimson, not the rows). */\n"
    "[data-radix-select-trigger],\n"
    'button[data-radix-select-trigger],\n'
    'button[role="combobox"] {\n'
    "  background-color: #ffffff !important;\n"
    f"  color: {STORE_INK} !important;\n"
    f"  border: 1px solid {STORE_LINE} !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-content],\n"
    "div[data-radix-select-content],\n"
    "[data-radix-popper-content-wrapper] > div,\n"
    "div[data-radix-popper-content-wrapper] {\n"
    "  background-color: #ffffff !important;\n"
    f"  color: {STORE_INK} !important;\n"
    f"  border: 1px solid {STORE_LINE} !important;\n"
    "  box-shadow: 0 10px 38px -10px rgba(0, 0, 0, 0.35), "
    "0 10px 20px -15px rgba(0, 0, 0, 0.2) !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-item],\n"
    "div[data-radix-select-item],\n"
    '[role="option"] {\n'
    "  background-color: #ffffff !important;\n"
    f"  color: {STORE_INK} !important;\n"
    "  padding: 8px 12px !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-item]:hover,\n"
    "[data-radix-select-item]:focus,\n"
    "div[data-radix-select-item]:hover,\n"
    "div[data-radix-select-item]:focus,\n"
    '[role="option"]:hover,\n'
    '[role="option"]:focus {\n'
    "  background-color: rgba(220, 20, 60, 0.08) !important;\n"
    "  outline: none !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-item][data-highlighted],\n"
    "div[data-radix-select-item][data-highlighted],\n"
    '[role="option"][data-highlighted] {\n'
    "  background-color: rgba(220, 20, 60, 0.08) !important;\n"
    "}\n"
    "\n"
    "/* Radix Select viewport and scrollarea */\n"
    "[data-radix-select-viewport] {\n"
    "  background-color: #ffffff !important;\n"
    "}\n"
    "\n"
    "[data-radix-scroll-area-viewport] {\n"
    "  background-color: #ffffff !important;\n"
    "}\n"
    "\n"
    "/* Fallback with higher specificity */\n"
    ".select-content,\n"
    'div[class*="select"] {\n'
    "  background-color: #ffffff !important;\n"
    f"  color: {STORE_INK} !important;\n"
    "}\n"
    "\n"
    ".select-item,\n"
    'div[class*="select"] > div {\n'
    "  background-color: #ffffff !important;\n"
    f"  color: {STORE_INK} !important;\n"
    "}\n"
)

# What that rule shipped as: upstream's dark pins, which is also what a
# fresh sync brings back -- named only so patch_chrome can trade it.
OLD_SELECT_CSS = (
    "/* Custom selector styling - more specific */\n"
    "[data-radix-select-trigger],\n"
    'button[data-radix-select-trigger],\n'
    'button[role="combobox"] {\n'
    "  background-color: #212121 !important;\n"
    "  color: white !important;\n"
    "  border: 1px solid #374151 !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-content],\n"
    "div[data-radix-select-content],\n"
    "[data-radix-popper-content-wrapper] > div,\n"
    "div[data-radix-popper-content-wrapper] {\n"
    "  background-color: #212121 !important;\n"
    "  color: white !important;\n"
    "  border: 1px solid #374151 !important;\n"
    "  box-shadow: 0 10px 38px -10px rgba(0, 0, 0, 0.35), "
    "0 10px 20px -15px rgba(0, 0, 0, 0.2) !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-item],\n"
    "div[data-radix-select-item],\n"
    '[role="option"] {\n'
    "  background-color: #212121 !important;\n"
    "  color: white !important;\n"
    "  padding: 8px 12px !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-item]:hover,\n"
    "[data-radix-select-item]:focus,\n"
    "div[data-radix-select-item]:hover,\n"
    "div[data-radix-select-item]:focus,\n"
    '[role="option"]:hover,\n'
    '[role="option"]:focus {\n'
    "  background-color: #374151 !important;\n"
    "  outline: none !important;\n"
    "}\n"
    "\n"
    "[data-radix-select-item][data-highlighted],\n"
    "div[data-radix-select-item][data-highlighted],\n"
    '[role="option"][data-highlighted] {\n'
    "  background-color: #374151 !important;\n"
    "}\n"
    "\n"
    "/* Radix Select viewport and scrollarea */\n"
    "[data-radix-select-viewport] {\n"
    "  background-color: #212121 !important;\n"
    "}\n"
    "\n"
    "[data-radix-scroll-area-viewport] {\n"
    "  background-color: #212121 !important;\n"
    "}\n"
    "\n"
    "/* Fallback with higher specificity */\n"
    ".select-content,\n"
    'div[class*="select"] {\n'
    "  background-color: #212121 !important;\n"
    "  color: white !important;\n"
    "}\n"
    "\n"
    ".select-item,\n"
    'div[class*="select"] > div {\n'
    "  background-color: #212121 !important;\n"
    "  color: white !important;\n"
    "}\n"
)

# The canvas and the motion, appended to globals.css after upstream's own
# last rule. Written as concatenation because the few colours it names come
# from the same constants the palette above patches -- one source for each
# value, so the two can never disagree. The band rides between the two
# halves from its own constant above.
CANVAS_CSS = (
    "\n\n"
    "/* --- The Bitzy canvas --------------------------------------------------\n"
    "   The store's ground, tiled with our own mark: warm off-white, the two\n"
    "   crimson radials bitzystore paints behind its hero (rgba(220,20,60) is\n"
    "   #DC143C), and the mark a few percent so it reads as texture rather\n"
    "   than as a pattern. The tile itself carries the mark twice, on a\n"
    "   diagonal half-drop, and the 512px cell halves the density again --\n"
    "   the reader found a straight grid of four too busy. On body rather\n"
    "   than html, because body's background is what propagates to the\n"
    "   canvas here -- the same element the old JS gradient used to paint,\n"
    "   now painted once and for good. */\n"
    "body {\n"
    f"  background-color: {STORE_BG};\n"
    "  background-image:\n"
    "    url('/pictures/logo-tile.svg'),\n"
    "    radial-gradient(800px 420px at 88% -10%, rgba(220, 20, 60, 0.10), transparent 60%),\n"
    "    radial-gradient(700px 500px at -10% 110%, rgba(220, 20, 60, 0.06), transparent 55%);\n"
    "  background-repeat: repeat, no-repeat, no-repeat;\n"
    "  background-size: 512px auto, auto, auto;\n"
    "  background-attachment: fixed, fixed, fixed;\n"
    "}\n"
    "\n"
) + HERO_CSS + (
    "\n"
    "/* --- Motion -------------------------------------------------------------\n"
    "   Small on purpose: the store's two-pixel button lift and crimson shadow,\n"
    "   the strip and the cards rising to meet the pointer, sections arriving\n"
    "   on the way in, and the hero's glow drifting. All of it stops for\n"
    "   readers who ask for less motion -- the scroll-timed reveals included,\n"
    "   which is why the reduce block resets `animation` itself rather than\n"
    "   its duration: a duration does not stop a view timeline. */\n"
    "@media (prefers-reduced-motion: no-preference) {\n"
    "  body {\n"
    "    animation: bitzy-settle 0.5s ease-out both;\n"
    "  }\n"
    "\n"
    "  button.bg-primary,\n"
    "  a.bg-primary,\n"
    '  button[class*="bg-[var(--color-bitzy)]"] {\n'
    "    transition:\n"
    "      transform 0.15s ease,\n"
    "      box-shadow 0.15s ease,\n"
    "      background-color 0.15s ease;\n"
    "  }\n"
    "\n"
    "  button.bg-primary:hover:not(:disabled),\n"
    "  a.bg-primary:hover:not(:disabled),\n"
    '  button[class*="bg-[var(--color-bitzy)]"]:hover:not(:disabled) {\n'
    "    transform: translateY(-2px);\n"
    "    background-color: #e8455f;\n"
    "    box-shadow: 0 10px 26px rgba(220, 20, 60, 0.32);\n"
    "  }\n"
    "\n"
    "  main > a.group {\n"
    "    transition:\n"
    "      transform 0.18s ease,\n"
    "      box-shadow 0.18s ease,\n"
    "      opacity 0.18s ease;\n"
    "  }\n"
    "\n"
    "  main > a.group:hover {\n"
    "    transform: translateY(-2px);\n"
    "    box-shadow: 0 10px 26px rgba(220, 20, 60, 0.18);\n"
    "  }\n"
    "\n"
    "  #features .grid > * {\n"
    "    transition:\n"
    "      transform 0.22s ease,\n"
    "      box-shadow 0.22s ease,\n"
    "      border-color 0.22s ease;\n"
    "  }\n"
    "\n"
    "  #features .grid > *:hover {\n"
    "    transform: translateY(-4px);\n"
    "    border-color: rgba(220, 20, 60, 0.35);\n"
    "    box-shadow:\n"
    "      0 8px 20px rgba(34, 34, 34, 0.08),\n"
    "      0 30px 70px rgba(34, 34, 34, 0.12);\n"
    "  }\n"
    "}\n"
    "\n"
    "/* Sections arrive mapped to the scroll itself where the browser can do\n"
    "   that, and not at all where it cannot: outside @supports these rules\n"
    "   are never written and everything simply renders in place. */\n"
    "@supports (animation-timeline: view()) {\n"
    "  @media (prefers-reduced-motion: no-preference) {\n"
    "    #features > div,\n"
    "    main > a.group {\n"
    "      animation: bitzy-rise linear both;\n"
    "      animation-timeline: view();\n"
    "      animation-range: entry 6% cover 26%;\n"
    "    }\n"
    "  }\n"
    "}\n"
    "\n"
    "@keyframes bitzy-settle {\n"
    "  from {\n"
    "    opacity: 0;\n"
    "  }\n"
    "  to {\n"
    "    opacity: 1;\n"
    "  }\n"
    "}\n"
    "\n"
    "@keyframes bitzy-rise {\n"
    "  from {\n"
    "    opacity: 0;\n"
    "    translate: 0 16px;\n"
    "  }\n"
    "  to {\n"
    "    opacity: 1;\n"
    "    translate: 0 0;\n"
    "  }\n"
    "}\n"
    "\n"
    "@keyframes bitzy-glow {\n"
    "  from {\n"
    "    background-position: 0 0, 0 0, 0 0, 0 0;\n"
    "  }\n"
    "  to {\n"
    "    background-position: 0 0, 36px -22px, -30px 18px, 0 0;\n"
    "  }\n"
    "}\n"
    "\n"
    "@media (prefers-reduced-motion: reduce) {\n"
    "  *,\n"
    "  *::before,\n"
    "  *::after {\n"
    "    animation: none !important;\n"
    "    transition: none !important;\n"
    "  }\n"
    "\n"
    "  button.bg-primary:hover,\n"
    "  a.bg-primary:hover,\n"
    '  button[class*="bg-[var(--color-bitzy)]"]:hover,\n'
    "  main > a.group:hover,\n"
    "  #features .grid > *:hover,\n"
    '  [class*="translate"]:hover {\n'
    "    transform: none !important;\n"
    "    translate: none !important;\n"
    "  }\n"
    "}\n"
)


def patch_chrome() -> None:
    """The store's header, and everything the palette alone cannot say.

    globals.css carries three things this pass needs beyond token values:
    the header rule (its own surface -- now the store's white at 85% over a
    14px blur), the canvas the JS gradient used to paint, and the motion.
    All three anchor on text upstream actually ships, so a fresh sync grows
    them back the moment the patcher runs.
    """
    path = ROOT / "src" / "app" / "globals.css"

    # The whole rule rather than its values: if upstream edits inside it,
    # the anchor moves and validation fails, which is correct -- the
    # header's surface is now ours, not theirs. The blur lives in
    # @supports blocks after the rule rather than inside it: the CSS
    # minifier collapses a bare backdrop-filter to its -webkit- alias, and
    # Chrome -- every Chrome this page is aimed at, Web Serial being
    # Chromium's -- reads neither that alias nor a declaration it has
    # folded away. Each @supports names the form it guards, so neither
    # can be merged out. Two source forms: upstream's dark rule, and this
    # fork's first white rule with the blur inside it.
    final_header = (
        ".header-custom {\n"
        "  background-color: rgba(255, 255, 255, 0.85);\n"
        "  border-bottom: 1px solid var(--color-hairline-light);\n"
        "  width: 100vw;\n"
        "  position: fixed;\n"
        "  top: 0;\n"
        "  left: 0;\n"
        "  right: 0;\n"
        "  z-index: 50;\n"
        "  color: var(--color-ink);\n"
        "}\n"
        "\n"
        "@supports (backdrop-filter: blur(12px)) {\n"
        "  .header-custom {\n"
        "    backdrop-filter: blur(14px);\n"
        "  }\n"
        "}\n"
        "\n"
        "@supports (-webkit-backdrop-filter: blur(12px)) {\n"
        "  .header-custom {\n"
        "    -webkit-backdrop-filter: blur(14px);\n"
        "  }\n"
        "}\n"
    )
    changed = replace_if_present(
        path,
        ".header-custom {\n"
        "  background-color: rgba(255, 255, 255, 0.85);\n"
        "  backdrop-filter: blur(14px);\n"
        "  -webkit-backdrop-filter: blur(14px);\n"
        "  border-bottom: 1px solid var(--color-hairline-light);\n"
        "  width: 100vw;\n"
        "  position: fixed;\n"
        "  top: 0;\n"
        "  left: 0;\n"
        "  right: 0;\n"
        "  z-index: 50;\n"
        "  color: var(--color-ink);\n"
        "}\n",
        final_header,
    )
    changed |= replace_if_present(
        path,
        ".header-custom {\n"
        "  background-color: var(--color-chrome);\n"
        "  border-bottom: 1px solid var(--color-hairline);\n"
        "  width: 100vw;\n"
        "  position: fixed;\n"
        "  top: 0;\n"
        "  left: 0;\n"
        "  right: 0;\n"
        "  z-index: 50;\n"
        "  color: #ffffff;\n"
        "}\n",
        final_header,
    )

    # Canvas + motion, after upstream's last rule (.band-dark).
    changed |= inject_once(
        path,
        "/* --- The Bitzy canvas",
        ".band-dark {\n  background-color: #111113;\n  color: #ffffff;\n}",
        ".band-dark {\n  background-color: #111113;\n  color: #ffffff;\n}" + CANVAS_CSS,
    )
    # The tile grew from a single mark per 256px cell to the diagonal pair
    # per 512px cell; inject_once only writes CANVAS_CSS into a fresh
    # tree, so an already-injected tree gets the new cell size here.
    changed |= replace_if_present(
        path,
        "  background-size: 256px auto, auto, auto;\n",
        "  background-size: 512px auto, auto, auto;\n",
    )
    changed |= replace_if_present(
        path,
        "  background-size: 256px auto, auto, auto, auto;\n",
        "  background-size: 512px auto, auto, auto, auto;\n",
    )
    # The band itself moved from the flasher's dark room to the store's
    # light ground; inject_once only writes CANVAS_CSS into a fresh tree,
    # so an already-injected tree trades the whole rule here.
    changed |= replace_if_present(path, OLD_HERO_CSS, HERO_CSS)
    # The select's !important pins are upstream's, so this chain is the
    # only thing that can move them: tokens cannot beat !important.
    changed |= replace_if_present(path, OLD_SELECT_CSS, SELECT_LIGHT_CSS)
    note(changed, "globals.css: store header bar, warm canvas + logo tile, motion")


def patch_selector() -> None:
    path = ROOT / "src" / "components" / "Selector.tsx"
    # Built by concatenation on purpose: Tailwind v4 scans every file in the
    # project for class candidates, so this script writing the class literally
    # would ship the dead yellow utility in the CSS bundle.
    old_chip = "text-[#" "4A4200]"
    changed = replace_once(path, old_chip, "text-white")
    # The neutral badge sits in the dropdown's list, and that list is the
    # store's white now -- white-on-white would take the badge off the page.
    changed |= replace_if_present(
        path,
        'className="ml-2 rounded border border-white/25 px-1.5 py-0.5 text-[10px] '
        'font-semibold text-white/60 align-middle"',
        'className="ml-2 rounded border border-[var(--color-hairline-light)] px-1.5 '
        'py-0.5 text-[10px] font-semibold text-[var(--color-muted-warm)] align-middle"',
    )
    note(changed, "Selector.tsx: latest chip white on crimson, badge on the white list")


def patch_picker_panels() -> None:
    """The two pickers open off the flasher band, so they judge light with it.

    Same treatment the steps drawer got: white ground, hairline-light
    dividers, ink headings, store-muted supporting copy, crimson for the
    hit (the Latest chip, the active filter, the selected tile's edge).
    The dim behind them stays -- a scrim is not a surface, and it is what
    gives a white panel its contrast over the page.
    """
    modal = ROOT / "src" / "components" / "DeviceModal.tsx"
    board = ROOT / "src" / "components" / "BoardPicker.tsx"

    changed = False
    for path in (modal, board):
        # Panel, then sticky head: two anchors whose old text shares a
        # tail, so each is checked against the full phrase it lives in.
        changed |= replace_if_present(
            path,
            "rounded-2xl border border-[var(--color-hairline)] "
            "bg-[var(--color-chrome)] shadow-2xl",
            "rounded-2xl border border-[var(--color-hairline-light)] "
            "bg-white shadow-2xl",
        )
        changed |= replace_if_present(
            path,
            "border-b border-[var(--color-hairline)] bg-[var(--color-chrome)] px-6 py-5",
            "border-b border-[var(--color-hairline-light)] bg-white px-6 py-5",
        )
        changed |= replace_if_present(
            path,
            'className="font-display text-xl font-bold tracking-tight text-white"',
            'className="font-display text-xl font-bold tracking-tight '
            'text-[var(--color-ink)]"',
        )
        changed |= replace_if_present(
            path,
            "rounded-lg p-1.5 text-white/50 transition-colors hover:bg-white/5 hover:text-white",
            "rounded-lg p-1.5 text-[var(--color-muted-warm)] transition-colors "
            "hover:bg-black/5 hover:text-[var(--color-bitzy)]",
        )
        changed |= replace_if_present(
            path,
            'className="mt-0.5 text-sm text-white/40"',
            'className="mt-0.5 text-sm text-[var(--color-muted-warm)]"',
        )

    # The device tiles: cards on white, the crimson edge kept for the hover
    # and the warm ground taking the old dark fill's place.
    changed |= replace_if_present(
        modal,
        'className="font-display text-base font-bold tracking-tight text-white"',
        'className="font-display text-base font-bold tracking-tight '
        'text-[var(--color-ink)]"',
    )
    changed |= replace_if_present(
        modal,
        "group flex flex-col items-center rounded-xl border "
        "border-[var(--color-hairline)] bg-[var(--color-surface)] p-3 text-center "
        "transition-all duration-200 hover:-translate-y-0.5 "
        "hover:border-[var(--color-bitzy)] hover:bg-[var(--color-chrome-light)]",
        "group flex flex-col items-center rounded-xl border "
        "border-[var(--color-hairline-light)] bg-white p-3 text-center "
        "transition-all duration-200 hover:-translate-y-0.5 "
        "hover:border-[var(--color-bitzy)] hover:bg-[var(--color-band-light)]",
    )
    changed |= replace_if_present(
        modal,
        'className="mt-2 font-display text-[13px] font-semibold leading-tight text-white"',
        'className="mt-2 font-display text-[13px] font-semibold leading-tight '
        'text-[var(--color-ink)]"',
    )
    changed |= replace_if_present(
        modal,
        'className="font-data mt-0.5 text-[10px] leading-tight text-white/40 '
        'group-hover:text-[var(--color-bitzy)]"',
        'className="font-data mt-0.5 text-[10px] leading-tight '
        'text-[var(--color-muted-warm)] group-hover:text-[var(--color-bitzy)]"',
    )

    # The board grid: inactive chips, the search field, the empty state and
    # the tiles themselves -- selected goes to the warm ground under its
    # crimson edge, unselected to white with a crimson hover.
    changed |= replace_if_present(
        board,
        "'border-[var(--color-hairline)] text-white/60 hover:border-white/30 hover:text-white'",
        "'border-[var(--color-hairline-light)] text-[var(--color-muted-warm)] "
        "hover:border-[var(--color-ink)]/50 hover:text-[var(--color-ink)]'",
    )
    changed |= replace_if_present(
        board,
        'className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 '
        '-translate-y-1/2 text-white/30"',
        'className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 '
        '-translate-y-1/2 text-[var(--color-muted-warm)]"',
    )
    changed |= replace_if_present(
        board,
        'className="w-44 rounded-full border border-[var(--color-hairline)] '
        'bg-black/30 py-1 pl-8 pr-3 text-xs text-white placeholder:text-white/30 '
        'focus:border-[var(--color-bitzy)] focus:outline-none"',
        'className="w-44 rounded-full border border-[var(--color-hairline-light)] '
        'bg-white py-1 pl-8 pr-3 text-xs text-[var(--color-ink)] '
        'placeholder:text-[var(--color-muted-warm)] focus:border-[var(--color-bitzy)] '
        'focus:outline-none"',
    )
    changed |= replace_if_present(
        board,
        'className="font-data mt-3 text-[11px] text-white/50"',
        'className="font-data mt-3 text-[11px] text-[var(--color-muted-warm)]"',
    )
    changed |= replace_if_present(
        board,
        'className="py-10 text-center text-sm text-white/40"',
        'className="py-10 text-center text-sm text-[var(--color-muted-warm)]"',
    )
    changed |= replace_if_present(
        board,
        "'border-[var(--color-bitzy)] bg-[var(--color-chrome-light)]'",
        "'border-[var(--color-bitzy)] bg-[var(--color-band-light)]'",
    )
    changed |= replace_if_present(
        board,
        "'border-[var(--color-hairline)] bg-[var(--color-surface)] hover:border-white/25'",
        "'border-[var(--color-hairline-light)] bg-white "
        "hover:border-[var(--color-bitzy)]/50'",
    )
    changed |= replace_if_present(
        board,
        'className="mt-3 text-sm font-medium leading-tight text-white"',
        'className="mt-3 text-sm font-medium leading-tight text-[var(--color-ink)]"',
    )
    changed |= replace_if_present(
        board,
        'className="font-data mt-1.5 text-[10px] uppercase tracking-wide text-white/35"',
        'className="font-data mt-1.5 text-[10px] uppercase tracking-wide '
        'text-[var(--color-muted-warm)]"',
    )
    note(changed, "DeviceModal/BoardPicker: white panels, ink text, store edges")


def patch_device_shops() -> None:
    """Point the store links and the secure-boot explainer at us.

    devices.ts is where upstream adds a board every few weeks, so nothing
    here may depend on their wording: a pattern that stops matching means
    upstream removed the thing we were patching, which needs no work from
    us. The URL sweep afterwards is what actually guarantees no Bitronics
    link survives, whatever shape upstream gives it.
    """
    path = ROOT / "src" / "lib" / "devices.ts"
    text = path.read_text()

    # `const SHOP = 'https://bitronics.store/collections'` and any sibling
    # URL, whatever path they carry.
    new = BITRONICS_URL.sub(SITE, text)

    # The code appends a slug (`${SHOP}/nerdminer`) that only makes sense
    # against their collection pages, so drop the suffixes and land every
    # buy button on our root rather than on a path we may not serve.
    new = re.sub(r"(`\$\{SHOP\})/[^`]+`", r"\1`", new)

    # The secure-boot explainer stays factually as upstream wrote it; only
    # the vendor it names changes.
    new, n_prose = re.subn(r"pre-flashed by Bitronics", "pre-flashed by BitzyLabs", new)

    changed = new != text
    if changed:
        path.write_text(new)
    detail = ", secure-boot explainer reworded" if n_prose else ""
    note(changed, f"devices.ts: shop links -> BitzyLabs{detail}")


# --- The DevBoard Tests overlay ---------------------------------------------

# The fork's own files. These are paths upstream has never had, so the merge
# carries them untouched; all they need is to be noticed when they go missing.
DEVBOARD_FILES = (
    "src/lib/bitzy/devboards.ts",
    "src/lib/bitzy/stlink.ts",
    "src/components/bitzy/DevBoardPanel.tsx",
    "public/pictures/esp32-n16r8.png",
    "public/pictures/stm32-bluepill.png",
    # The middle column looks up board art by board name; without these the
    # flow still works but every selection logs a 404.
    "public/pictures/boards/ESP32S3-N16R8.png",
    "public/pictures/boards/STM32F103C8-BluePill.png",
)


def patch_devboards() -> None:
    """Add the DevBoard Tests section: two devices, one new flash path.

    Upstream owns the three files this touches, and they divide into two
    standards. The tables upstream *appends to* -- the category list, the
    device sources, the picker's JSON -- self-heal: the sync resolves
    upstream's rewrites of those files in their own favour (formatting
    and all, -X theirs), so these patch from the declaration line, gated
    on markers only this script writes, and put our rows back wherever
    theirs landed. The flow wiring in LandingHero stays exact-text and    fails loudly, because a moved anchor there means upstream changed how
    flashing works and a human has to look. The overlay's own code
    (lib/bitzy, components/bitzy, the pictures, the firmware folders)
    needs no patching; the merge brings it.
    """
    changed_devices = False
    changed_devices |= inject_category_type()
    changed_devices |= inject_mcu_field()
    changed_devices |= inject_rows(
        ROOT / "src" / "lib" / "devices.ts",
        "export const CATEGORIES: { id: DeviceCategory; title: string; blurb: string }[] = [\n",
        "  {\n"
        "    id: 'devboards',\n"
        "    title: 'DevBoard Tests',\n"
        "    blurb: 'Blinky builds for the boards on our own bench.',\n"
        "  },\n",
        "id: 'devboards',",
    )
    changed_devices |= inject_rows(
        ROOT / "src" / "lib" / "devices.ts",
        "export const DEVICE_SOURCES: DeviceSource[] = [\n",
        "  // DevBoard Tests come first: these are the boards this fork bench-tests\n"
        "  // firmware on, and the picker should offer them before the miners.\n"
        "  {\n"
        "    device: 'ESP 32 N16R8',\n"
        "    category: 'devboards',\n"
        "    mcu: 'esp32',\n"
        "    tagline: 'ESP32-S3 bench test',\n"
        "    slug: 'esp32s3-smoothblinky',\n"
        "  },\n"
        "  {\n"
        "    device: 'STM 32 BluePill',\n"
        "    category: 'devboards',\n"
        "    mcu: 'stm32',\n"
        "    tagline: 'STM32F103 bench test',\n"
        "    slug: 'stm32-bluepill',\n"
        "  },\n",
        "device: 'ESP 32 N16R8',",
    )
    note(changed_devices, "devices.ts: DevBoard Tests category + two devices")

    note(inject_picker_tiles(), "firmware_data.json: tiles for both devboards")

    patch_devboard_flows()


def patch_devboard_flows() -> None:
    """LandingHero: the Continue button, the STM32 path, the instructions.

    A chain of anchors in one file, split out so a failure names the step
    rather than the file. Every one is exact text and every call carries a marker
    this patch alone writes: a second run -- or a merge that stacked
    upstream's edits around ours -- sees the work as done instead of
    demanding anchors the file no longer has. The wrapping ones still keep
    the original inside an `else`, so the verbatim check agrees.
    """
    path = ROOT / "src" / "components" / "LandingHero.tsx"
    changed = False

    changed |= inject_once(
        path,
        "import DevBoardPanel from './bitzy/DevBoardPanel';",
        "import BoardArt from './BoardArt';\nimport DeviceIntro from './DeviceIntro';",
        "import BoardArt from './BoardArt';\n"
        "import DeviceIntro from './DeviceIntro';\n"
        "import DevBoardPanel from './bitzy/DevBoardPanel';\n"
        "import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';",
    )

    # The probe client: its device-id phrasing for the connect status and
    # the entry point, stacked on the import line the chain above writes.
    # The Blue Pill's serial implementation is gone -- the ST-Link path is
    # the STM32 path now -- so nothing else rides along.
    changed |= inject_once(
        path,
        "from '@/lib/bitzy/stlink';",
        "import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';",
        "import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';\n"
        "import {\n"
        "  describeDeviceId,\n"
        "  flashBluePillSwd,\n"
        "  openStlink,\n"
        "  type StlinkConnection,\n"
        "} from '@/lib/bitzy/stlink';",
    )

    changed |= inject_once(
        path,
        "const continueToFlash = () => {",
        "  const handleStartFlashing = async () => {",
        "  // DevBoard Tests: one board and one firmware each, so the middle step is\n"
        "  // a single button rather than a picker. Pressing it picks both and leaves\n"
        "  // nothing between the user and the Connect button.\n"
        "  const continueToFlash = () => {\n"
        "    const boards = device.boards as Board[];\n"
        "    const only = boards[0];\n"
        "    if (!only) return;\n"
        "    setSelectedBoardVersion(only.name);\n"
        "    setSelectedFirmware(only.supported_firmware[0]?.version ?? '');\n"
        "  };\n"
        "\n"
        "  // The Blue Pill flashes through its ROM bootloader -- AN3155 over the same\n"
        "  // open serial port -- not through esptool. The file was hash-checked when\n"
        "  // the version was picked, so the bytes are reused when they are still to\n"
        "  // hand and fetched fresh otherwise.\n"
        "  const flashBluePillFlow = async () => {\n"
        "    const path = imageFor(firmware.path, false);\n"
        "    if (!path) throw new Error('No firmware is available for this device.');\n"
        "\n"
        "    const cached = checkedBytesRef.current;\n"
        "    let bytes: ArrayBuffer;\n"
        "\n"
        "    if (cached && cached.path === path) {\n"
        "      bytes = cached.bytes;\n"
        "    } else {\n"
        "      const response = await fetch(path);\n"
        "      if (!response.ok) throw new Error('Failed to load the firmware file.');\n"
        "      bytes = await response.arrayBuffer();\n"
        "    }\n"
        "\n"
        "    await flashBluePill({\n"
        "      port: serialPortRef.current,\n"
        "      data: new Uint8Array(bytes),\n"
        "      onProgress: (percent, phase) => {\n"
        "        if (phase === 'write') {\n"
        "          setProgress(percent);\n"
        "          setStatus(t('status.flashing', { percent }));\n"
        "        } else if (phase === 'verify') {\n"
        "          setProgress(100);\n"
        "          setStatus('Verifying what was written...');\n"
        "        } else if (phase === 'erase') {\n"
        "          setStatus('Erasing flash...');\n"
        "        } else {\n"
        "          setStatus('Talking to the bootloader...');\n"
        "        }\n"
        "      },\n"
        "    });\n"
        "  };\n"
        "\n"
        "  const handleStartFlashing = async () => {",
    )

    # One image, one link: the flow above is traded for a shared fetch
    # helper and the SWD flow that consumes it. The serial arm is gone --
    # the kit ships an ST-Link and the STM32 path never touches Web
    # Serial. The trade anchors on the text the previous chain writes,
    # so a fresh sync lands it in order.
    changed |= inject_once(
        path,
        "const flashBluePillSwdFlow = async () => {",
        "  // The Blue Pill flashes through its ROM bootloader -- AN3155 over the same\n"
        "  // open serial port -- not through esptool. The file was hash-checked when\n"
        "  // the version was picked, so the bytes are reused when they are still to\n"
        "  // hand and fetched fresh otherwise.\n"
        "  const flashBluePillFlow = async () => {\n"
        "    const path = imageFor(firmware.path, false);\n"
        "    if (!path) throw new Error('No firmware is available for this device.');\n"
        "\n"
        "    const cached = checkedBytesRef.current;\n"
        "    let bytes: ArrayBuffer;\n"
        "\n"
        "    if (cached && cached.path === path) {\n"
        "      bytes = cached.bytes;\n"
        "    } else {\n"
        "      const response = await fetch(path);\n"
        "      if (!response.ok) throw new Error('Failed to load the firmware file.');\n"
        "      bytes = await response.arrayBuffer();\n"
        "    }\n"
        "\n"
        "    await flashBluePill({\n"
        "      port: serialPortRef.current,\n"
        "      data: new Uint8Array(bytes),\n"
        "      onProgress: (percent, phase) => {\n"
        "        if (phase === 'write') {\n"
        "          setProgress(percent);\n"
        "          setStatus(t('status.flashing', { percent }));\n"
        "        } else if (phase === 'verify') {\n"
        "          setProgress(100);\n"
        "          setStatus('Verifying what was written...');\n"
        "        } else if (phase === 'erase') {\n"
        "          setStatus('Erasing flash...');\n"
        "        } else {\n"
        "          setStatus('Talking to the bootloader...');\n"
        "        }\n"
        "      },\n"
        "    });\n"
        "  };\n",
        "  // One image, two links. The file was hash-checked when the version was\n"
        "  // picked, so the bytes are reused when they are still to hand and\n"
        "  // fetched fresh otherwise -- whichever transport carries them.\n"
        "  const bluePillImage = async (): Promise<Uint8Array> => {\n"
        "    const path = imageFor(firmware.path, false);\n"
        "    if (!path) throw new Error('No firmware is available for this device.');\n"
        "\n"
        "    const cached = checkedBytesRef.current;\n"
        "    if (cached && cached.path === path) return new Uint8Array(cached.bytes);\n"
        "\n"
        "    const response = await fetch(path);\n"
        "    if (!response.ok) throw new Error('Failed to load the firmware file.');\n"
        "    return new Uint8Array(await response.arrayBuffer());\n"
        "  };\n"
        "\n"
        "  // Over SWD: the same bytes through the probe. The core stops first, the\n"
        "  // F1 flash controller is driven the way st-flash drives it -- unlock,\n"
        "  // erase every page the image touches, program, read every byte back --\n"
        "  // and only then the chip is reset. No BOOT0 jumper: no bootloader is\n"
        "  // involved at all.\n"
        "  const flashBluePillSwdFlow = async () => {\n"
        "    const probe = stlinkRef.current;\n"
        "    if (!probe) throw new Error('The ST-Link is not connected.');\n"
        "    const data = await bluePillImage();\n"
        "    await flashBluePillSwd({\n"
        "      probe,\n"
        "      data,\n"
        "      onProgress: (percent, phase) => {\n"
        "        if (phase === 'write') {\n"
        "          setProgress(percent);\n"
        "          setStatus(t('status.flashing', { percent }));\n"
        "        } else if (phase === 'verify') {\n"
        "          setProgress(100);\n"
        "          setStatus('Verifying what was written...');\n"
        "        } else if (phase === 'erase') {\n"
        "          setStatus('Erasing flash...');\n"
        "        } else {\n"
        "          setStatus('Stopping the core...');\n"
        "        }\n"
        "      },\n"
        "    });\n"
        "  };\n",
    )


    # The flash step for the Blue Pill: SWD, and only SWD. The anchor is
    # upstream's own try-head; the marker is the success line this branch
    # writes -- a string no later trade removes, so the retired serial arm
    # cannot creep back in on a re-run the way its old marker could.
    changed |= inject_once(
        path,
        "'Flash complete and verified over SWD. The chip was reset -- the LED should blink.',",
        "    try {\n"
        "      // Stop logging if it's active\n"
        "      if (isLogging) {\n"
        "        await stopSerialLogging();\n"
        "      }",
        "    try {\n"
        "      // Stop logging if it's active\n"
        "      if (isLogging) {\n"
        "        await stopSerialLogging();\n"
        "      }\n"
        "\n"
        "      // DevBoard Tests: the Blue Pill flashes over the debug port and\n"
        "      // nothing else -- SWD through the probe, every byte read back before\n"
        "      // done, and then the chip is reset. No bootloader is involved, so\n"
        "      // there is no jumper to move either way.\n"
        "      if (isStm32(selectedDevice)) {\n"
        "        await flashBluePillSwdFlow();\n"
        "        setStatus(\n"
        "          'Flash complete and verified over SWD. The chip was reset -- the LED should blink.',\n"
        "        );\n"
        "        return;\n"
        "      }",
    )

    # The gate answers for the link the device type actually got: the STM32
    # path connects the probe over WebUSB and never holds a serial port, so
    # judging it by serial would answer "connect first" to somebody whose
    # ST-Link is already connected. Anchored on the head the Continue-chain
    # writes (or upstream's, before any of this ran).
    changed |= inject_once(
        path,
        "The gate asks for the link this device type actually got",
        "  const handleStartFlashing = async () => {\n"
        "    if (!serialPortRef.current) {\n"
        "      setStatus(t('status.connectFirst'));\n"
        "      return;\n"
        "    }",
        "  const handleStartFlashing = async () => {\n"
        "    // The gate asks for the link this device type actually got: the STM32\n"
        "    // path connects the ST-Link over WebUSB and never holds a serial port,\n"
        "    // so judging it by serial would answer \"connect first\" to somebody\n"
        "    // whose probe is already connected.\n"
        "    if (isStm32(selectedDevice)) {\n"
        "      if (!stlinkRef.current) {\n"
        "        setStatus(t('status.connectFirst'));\n"
        "        return;\n"
        "      }\n"
        "    } else if (!serialPortRef.current) {\n"
        "      setStatus(t('status.connectFirst'));\n"
        "      return;\n"
        "    }",
    )

    # Wrapping patch: the original Button survives inside the else branch,
    # which is how replace_once knows it already ran.
    changed |= inject_once(
        path,
        "onClick={continueToFlash}",
        "                <Button\n"
        "                  onClick={() => setIsBoardPickerOpen(true)}\n"
        "                  disabled={isConnecting || isFlashing || selectedDevice === ''}\n"
        "                >\n"
        "                  {selectedBoardVersion === '' ? t('hero.selectBoard') : selectedBoardVersion}\n"
        "                </Button>",
        "                {isDevBoard(selectedDevice) ? (\n"
        "                  <Button\n"
        "                    onClick={continueToFlash}\n"
        "                    disabled={isConnecting || isFlashing || selectedDevice === ''}\n"
        "                  >\n"
        "                    Continue To Flash\n"
        "                  </Button>\n"
        "                ) : (\n"
        "                <Button\n"
        "                  onClick={() => setIsBoardPickerOpen(true)}\n"
        "                  disabled={isConnecting || isFlashing || selectedDevice === ''}\n"
        "                >\n"
        "                  {selectedBoardVersion === '' ? t('hero.selectBoard') : selectedBoardVersion}\n"
        "                </Button>\n"
        "                )}",
    )

    # The dropdown is otherwise uncontrolled, so Continue To Flash would set
    # the firmware without the menu showing it.
    changed |= inject_once(
        path,
        "value={selectedFirmware}",
        "                <Selector\n"
        "                  placeholder={t('hero.selectFirmware')}\n"
        "                  values={board.supported_firmware.map((f: any) => f.version)}\n"
        "                  onValueChange={setSelectedFirmware}",
        "                <Selector\n"
        "                  placeholder={t('hero.selectFirmware')}\n"
        "                  value={selectedFirmware}\n"
        "                  values={board.supported_firmware.map((f: any) => f.version)}\n"
        "                  onValueChange={setSelectedFirmware}",
    )

    # The one line above the Connect button: the Blue Pill's BOOT0 jumper.
    changed |= inject_once(
        path,
        "<DevBoardPanel device={selectedDevice}",
        '            <div className="w-full max-w-sm space-y-4">',
        '            <DevBoardPanel device={selectedDevice} download={firmware.path} />\n'
        '            <div className="w-full max-w-sm space-y-4">',
    )

    # The miners' next step (join its WiFi AP) is a lie for a board whose
    # whole job is blinking an LED.
    changed |= inject_once(
        path,
        "=== 'devboards'",
        "  const nextStep = !finished\n"
        "    ? null\n"
        "    : heroSource?.category === 'tools'\n"
        "      ? 'Unplug it and plug it back in. To check the chip really holds this build, run the verify command from the project README.'\n"
        "      : 'Unplug it and plug it back in. It will come up as its own WiFi access point: join that to set your pool and wallet.';",
        "  const nextStep = !finished\n"
        "    ? null\n"
        "    : heroSource?.category === 'devboards'\n"
        "      ? heroSource?.mcu === 'stm32'\n"
        "        ? 'Flash complete. The chip was reset over SWD -- the LED should blink.'\n"
        "        : 'Flash complete. Unplug the board and plug it back in -- the LED should blink.'\n"
        "      : heroSource?.category === 'tools'\n"
        "        ? 'Unplug it and plug it back in. To check the chip really holds this build, run the verify command from the project README.'\n"
        "        : 'Unplug it and plug it back in. It will come up as its own WiFi access point: join that to set your pool and wallet.';",
    )

    # The probe's slot: one ref shared by connect, flash and disconnect, so
    # the main button keeps being the way out of whichever link is open.
    changed |= inject_once(
        path,
        "const handleConnectStlink = async () => {",
        "  const handleConnect = async () => {\n"
        "    setIsConnecting(true);",
        "  // The other way onto a Blue Pill: the SWD probe already on the bench.\n"
        "  // No BOOT0 jumper and no crossed wires -- the probe reaches the flash\n"
        "  // through the debug port, and connecting is also the chip check: the\n"
        "  // device id comes back before anything is written.\n"
        "  const stlinkRef = useRef<StlinkConnection | null>(null);\n"
        "\n"
        "  const handleConnectStlink = async () => {\n"
        "    setIsConnecting(true);\n"
        "    setStatus('Looking for an ST-Link...');\n"
        "\n"
        "    try {\n"
        "      const probe = await openStlink();\n"
        "      stlinkRef.current = probe;\n"
        "      setIsConnected(true);\n"
        "      setStatus(\n"
        "        `ST-Link connected: ${probe.version}, ${describeDeviceId(probe.deviceId)}. `\n"
        "          + 'Press Start Flashing.',\n"
        "      );\n"
        "    } catch (error) {\n"
        "      console.error('ST-Link connection failed:', error);\n"
        "      setStatus(\n"
        "        `ST-Link connection failed: ${error instanceof Error ? error.message : String(error)}`,\n"
        "      );\n"
        "    } finally {\n"
        "      setIsConnecting(false);\n"
        "    }\n"
        "  };\n"
        "\n"
        "  const handleConnect = async () => {\n"
        "    setIsConnecting(true);",
    )

    # The STM32 connect itself: WebUSB first, serial for the rest. The
    # anchor is the head the chain above writes, so on a fresh sync this
    # lands directly after the probe client it calls -- and it must land
    # after it, or the chain above would find its own anchor already
    # rearranged. On this fork's file both markers are present and both
    # simply stand down.
    changed |= inject_once(
        path,
        "// The STM32 path is WebUSB, not Web Serial:",
        "  const handleConnect = async () => {\n"
        "    setIsConnecting(true);",
        "  const handleConnect = async () => {\n"
        "    // The STM32 path is WebUSB, not Web Serial: the kit ships an ST-Link,\n"
        "    // so this one click opens the device chooser and the probe client\n"
        "    // above takes it from there. Serial is every other device's door.\n"
        "    if (isStm32(selectedDevice)) {\n"
        "      await handleConnectStlink();\n"
        "      return;\n"
        "    }\n"
        "    setIsConnecting(true);",
    )

    # Logging reads a serial console, and an ST-Link's SWD link has none to
    # read. Without this the button would light up for a connected probe and
    # then answer "connect first" to somebody who already is.
    changed |= inject_once(
        path,
        "Serial logging is not available on this board",
        "  const startSerialLogging = async () => {\n"
        "    if (!serialPortRef.current) {\n"
        "      setStatus(t('status.connectFirst'));\n"
        "      return;\n"
        "    }",
        "  const startSerialLogging = async () => {\n"
        "    if (isStm32(selectedDevice)) {\n"
        "      setStatus(\n"
        "        'Serial logging is not available on this board: it is connected over the ' +\n"
        "          \"ST-Link's SWD link, which carries no console output.\",\n"
        "      );\n"
        "      return;\n"
        "    }\n"
        "    if (!serialPortRef.current) {\n"
        "      setStatus(t('status.connectFirst'));\n"
        "      return;\n"
        "    }",
    )

    # Disconnect has to mean the same thing for both links, so the probe is
    # released in the same try block that closes the serial port.
    changed |= inject_once(
        path,
        "stlinkRef.current.close()",
        "    try {\n"
        "      if (serialPortRef.current?.readable) {\n"
        "        await serialPortRef.current.close();\n"
        "      }",
        "    try {\n"
        "      if (stlinkRef.current) {\n"
        "        await stlinkRef.current.close();\n"
        "        stlinkRef.current = null;\n"
        "      }\n"
        "      if (serialPortRef.current?.readable) {\n"
        "        await serialPortRef.current.close();\n"
        "      }",
    )

    note(changed, "LandingHero.tsx: Continue To Flash, STM32 path (ST-Link over WebUSB), instructions")


def _filter_array_rows(
    text: str, decl: str, keep_row
) -> tuple[str, list[str]] | None:
    """Drop rows of the array after `decl` for which keep_row(block) is false.

    A row is the `  {` ... `  },` block at the array's own two-space
    indentation (nested structures indent deeper, so they stay inside);
    comment lines directly above a row travel with it, and anything before
    the first row or after the last is kept verbatim. Returns the new text
    plus the dropped blocks, or None when `decl` is not in the text so the
    caller can raise the anchor error it owes.
    """
    start = text.find(decl)
    if start < 0:
        return None
    body = start + len(decl)
    close = text.find("\n];", body)
    if close < 0:
        raise PatchError(
            "src/lib/devices.ts: the array after "
            f"{decl.splitlines()[0][:60]!r} never closes"
        )
    lines = text[body:close].splitlines(keepends=True)
    out: list[str] = []
    loose: list[str] = []
    row: list[str] | None = None
    dropped: list[str] = []
    for line in lines:
        if row is None:
            if line.startswith("  {"):
                row = [line]
            else:
                loose.append(line)
            continue
        row.append(line)
        if line.rstrip() in ("  }", "  },"):
            block_text = "".join(row)
            if keep_row(block_text):
                out.extend(loose)
                out.extend(row)
            else:
                dropped.append("".join(loose + row))
            loose, row = [], None
    if row is None:
        out.extend(loose)  # trailing lines after the last row
    else:  # unterminated row: leave the tail exactly as found
        out.extend(loose)
        out.extend(row)
    return text[:body] + "".join(out) + text[close:], dropped


def patch_picker_scope() -> None:
    """The picker offers DevBoard Tests and NerdMiner; nothing else.

    Upstream owns every row of these two tables and adds to them over time,
    so this is a policy applied to data, not a list of deletions: rows
    outside the policy go on every run -- whoever wrote them, however they
    are worded, including categories that do not exist yet. The NerdMiner
    additionally gets an allowlist for its boards, turning upstream's
    thirty-two-manifest wall into the five boards this flasher has actually
    been bench-verified against (the three 2432S02x units plus both S3
    devkits). The sync brings upstream's full tables back with `-X theirs`;
    this puts the fork's view on top before every build.
    """
    path = ROOT / "src" / "lib" / "devices.ts"
    text = path.read_text()

    def keep_category(block: str) -> bool:
        match = re.search(r"id:\s*'([^']+)'", block)
        return bool(match) and match.group(1) in ("devboards", "miners")

    def keep_source(block: str) -> bool:
        match = re.search(r"category:\s*'([^']+)'", block)
        if not match:
            return False
        if match.group(1) == "devboards":
            return True
        if match.group(1) == "miners":
            device = re.search(r"device:\s*'([^']+)'", block)
            return bool(device) and device.group(1) == "NerdMiner"
        return False

    changed = False
    for decl, keep in (
        (
            "export const CATEGORIES: { id: DeviceCategory; title: string; blurb: string }[] = [\n",
            keep_category,
        ),
        ("export const DEVICE_SOURCES: DeviceSource[] = [\n", keep_source),
    ):
        result = _filter_array_rows(text, decl, keep)
        if result is None:
            raise PatchError(
                "src/lib/devices.ts: anchor not found -- upstream changed this file.\n"
                f"  anchor was: {decl.splitlines()[0][:90]!r}"
            )
        text, dropped = result
        if dropped:
            changed = True

    # NerdMiner's board allowlist, dropped in after its slug line.
    if "esp32-s3-devkitc1-n32r8" not in text:
        anchor = re.search(r"^    slug: 'nerdminer',$", text, re.M)
        if not anchor:
            raise PatchError(
                "src/lib/devices.ts: anchor not found -- upstream changed this file.\n"
                "  anchor was: \"    slug: 'nerdminer',\""
            )
        block = (
            "\n"
            "    // The boards this flasher is bench-verified against: the three\n"
            "    // 2432S02x units and both S3 devkits. Thirty-two boards is a list\n"
            "    // nobody can choose from, and every one of them would be a guess.\n"
            "    includes: (board) =>\n"
            "      [\n"
            "        'ESP32-2432S024',\n"
            "        'ESP32-2432S028R',\n"
            "        'ESP32_2432S028_2USB',\n"
            "        'ESP32-S3-devKitv1',\n"
            "        'esp32-s3-devkitc1-n32r8',\n"
            "      ].includes(board),"
        )
        text = text[: anchor.end()] + block + text[anchor.end() :]
        changed = True

    if changed:
        path.write_text(text)
    note(
        changed,
        "devices.ts: picker scoped to DevBoard Tests + NerdMiner (Tools dropped)",
    )


def patch_backgrounds() -> None:
    """The canvas moves out of JavaScript and into CSS.

    Upstream paints a store photograph behind the document at start-up and
    again on every device selection, with NerdMiner swapping in its own
    wallpaper and an Image() probe to fall back when a banner is missing.
    This fork's first answer to that was one dark gradient on the same two
    hooks. The store's scheme then moved the whole thing to globals.css --
    warm ground, crimson glows, our mark tiled through both, the hero's own
    dark band from the same file -- so the hooks go too. Three source forms
    per site (upstream's photograph, this fork's gradient, nothing), one
    state each, and a guard after the chains that raises if any JS painting
    survives in a shape the anchors do not know.
    """
    path = ROOT / "src" / "components" / "LandingHero.tsx"

    # Start-up: what used to be two paint calls is now a note pointing at
    # the stylesheet that owns it.
    start_comment = (
        "    // The canvas is painted in CSS now: the store's warm ground with our\n"
        "    // mark tiled through it. Nothing to set per load.\n"
    )
    changed = replace_if_present(
        path,
        "    // Initialize default background\n"
        "    document.body.style.background = `linear-gradient(rgba(0, 0, 0, 0.9), "
        "rgba(0, 0, 0, 0.85)), url('${basePath}/pictures/Bitronics_hw.png')`;\n"
        "    document.body.style.backgroundSize = 'cover';\n"
        "    document.body.style.backgroundPosition = 'center';\n"
        "    document.body.style.backgroundAttachment = 'fixed';\n",
        start_comment,
    )
    changed |= replace_if_present(
        path,
        "    // Initialize default background: a dark gradient, no photograph.\n"
        f"    document.body.style.background = '{PAGE_GRADIENT}';\n"
        "    document.body.style.backgroundAttachment = 'fixed';\n",
        start_comment,
    )
    # Per selection: upstream's probe machinery, then this fork's gradient
    # block, both carried to the same one-line note. The dead
    # classList.remove went with the wallpaper class it guarded; nothing
    # adds that class anywhere any more.
    select_comment = (
        "    // Every device shares the same canvas; CSS painted it once at load.\n"
    )
    changed |= replace_if_present(
        path,
        "    // A device paints the page behind it. Its own banner if it has one, the\n"
        "    // NerdMiner keeps the picture it always had, everything else the default.\n"
        "    // Doing it as a backdrop rather than a band costs no vertical space, which\n"
        "    // is what was pushing the rest of the page below the fold.\n"
        "    const source = sourceFor(name);\n"
        "    const backdrop =\n"
        "      source?.banner ??\n"
        "      (name === 'NerdMiner' ? '/pictures/fondoNM3.png' : '/pictures/Bitronics_hw.png');\n"
        "\n"
        "    const paint = (image: string) => {\n"
        "      document.body.style.background = `linear-gradient(rgba(0, 0, 0, 0.9), "
        "rgba(0, 0, 0, 0.85)), url('${basePath}${image}')`;\n"
        "      document.body.style.backgroundSize = 'cover';\n"
        "      document.body.style.backgroundPosition = 'center';\n"
        "      document.body.style.backgroundAttachment = 'fixed';\n"
        "    };\n"
        "\n"
        "    // A banner that has not been added yet should not leave the page bare.\n"
        "    const probe = new Image();\n"
        "    probe.onload = () => paint(backdrop);\n"
        "    probe.onerror = () => paint('/pictures/Bitronics_hw.png');\n"
        "    probe.src = `${basePath}${backdrop}`;\n"
        "\n"
        "    document.body.classList.remove('nerdminer-bg');\n",
        select_comment,
    )
    changed |= replace_if_present(
        path,
        "    // Every device shares the same dark gradient behind the page: there is\n"
        "    // no photograph to probe and nothing to fall back to.\n"
        f"    document.body.style.background = '{PAGE_GRADIENT}';\n"
        "    document.body.style.backgroundAttachment = 'fixed';\n"
        "\n"
        "    document.body.classList.remove('nerdminer-bg');\n",
        select_comment,
    )
    # If either chain above missed -- upstream reworded its paint block into
    # a shape no source form recognises -- the calls are still in there and
    # would repaint the CSS canvas on every selection. Fail here rather
    # than ship two backgrounds fighting over the page.
    text = path.read_text()
    if "document.body.style.background" in text or "document.body.style.backgroundAttachment" in text:
        raise PatchError(
            "LandingHero.tsx: JavaScript still paints the page background in a "
            "shape the canvas patch does not know -- read what it does now and "
            "carry it to the CSS canvas before shipping."
        )
    # The hero sits on its own band from globals.css now (.bitzy-hero), so
    # the class line carries it and the comment above says why. Three
    # comment forms because the reason was restated once in this fork and
    # once more when the band went from the dark tool room to the store's
    # light ground -- every form that ever shipped lands on the last.
    final_section = (
        '<section className="bitzy-hero w-full py-10 text-[var(--color-ink)] md:py-14">'
    )
    changed |= replace_if_present(
        path,
        '<section className="dark w-full py-10 text-white md:py-14">',
        final_section,
    )
    changed |= replace_if_present(
        path,
        '<section className="bitzy-hero dark w-full py-10 text-white md:py-14">',
        final_section,
    )
    light_comment = (
        "      {/* The hero sits on the store's own light band -- warm ground, crimson\n"
        "          glow and our mark tiled through it -- so its contents render in ink\n"
        "          like every other band on the page. */}\n"
    )
    changed |= replace_if_present(
        path,
        "      {/* The hero always sits on a dark photograph, whatever the page theme is\n"
        "          set to, so its contents always render in the dark palette. Without\n"
        "          this the headline turns near-black on a near-black background. */}\n",
        light_comment,
    )
    changed |= replace_if_present(
        path,
        "      {/* The hero sits on a dark gradient, whatever the page theme is set to,\n"
        "          so its contents always render in the dark palette. Without this the\n"
        "          headline turns near-black on a near-black background. */}\n",
        light_comment,
    )
    changed |= replace_if_present(
        path,
        "      {/* The hero sits on its own dark band -- store crimson glow and our mark\n"
        "          tiled through it -- whatever the page behind it is painted, so its\n"
        "          contents always render in the dark palette. */}\n",
        light_comment,
    )
    note(changed, "LandingHero.tsx: canvas owned by CSS, bitzy-hero band class")


def patch_hero_light() -> None:
    """The flasher band joins the page on the light scheme.

    The band's own surface is CSS -- patch_chrome owns the rule -- so this
    is every dark-palette word inside it: white text becomes ink or the
    store's muted on what is now the warm ground, the shadcn dark: utilities
    drop away (patch_palette already moved the .dark tokens they read, so
    the checkboxes and the AP input fall back to their light forms), and the
    status card leaves the dark surface token for white with hairline-light
    edges. The log terminal keeps its black on purpose: ANSI colours only
    carry on dark, and a terminal is a terminal wherever it sits. Section
    line and band comment ride patch_backgrounds, which runs first -- one
    owner for each anchor, and validate judges the end state.
    """
    path = ROOT / "src" / "components" / "LandingHero.tsx"
    ink = "text-[var(--color-ink)]"
    muted = "text-[var(--color-muted-warm)]"

    # Headings and status lines sit directly on the band; supporting copy
    # takes the store's muted, which is what it is for.
    changed = replace_if_present(
        path,
        '<p className="mx-auto max-w-[700px] text-white/60 md:text-xl">',
        f'<p className="mx-auto max-w-[700px] {muted} md:text-xl">',
    )
    changed |= replace_if_present(
        path,
        '<h1 className="font-display text-3xl font-bold tracking-tighter '
        'text-white sm:text-4xl md:text-5xl">',
        f'<h1 className="font-display text-3xl font-bold tracking-tighter '
        f'{ink} sm:text-4xl md:text-5xl">',
    )
    changed |= replace_if_present(
        path,
        '<p className="mx-auto max-w-[700px] text-white/60 md:text-lg">',
        f'<p className="mx-auto max-w-[700px] {muted} md:text-lg">',
    )
    changed |= replace_if_present(
        path,
        '<h1 className="font-display text-3xl font-bold tracking-tight '
        'text-white sm:text-4xl">',
        f'<h1 className="font-display text-3xl font-bold tracking-tight '
        f'{ink} sm:text-4xl">',
    )
    changed |= replace_if_present(
        path,
        '<div className="flex items-center justify-center gap-2 text-xs text-white/50">',
        f'<div className="flex items-center justify-center gap-2 text-xs {muted}">',
    )
    # The error chip keeps its danger tint and icon; only the copy on that
    # tint moves, to ink at the weight white held.
    changed |= replace_if_present(
        path,
        "px-3 py-2 text-xs text-white/80\">",
        f'px-3 py-2 text-xs {ink}/80">',
    )
    changed |= replace_if_present(
        path,
        '<span className="text-sm font-semibold text-white">',
        f'<span className="text-sm font-semibold {ink}">',
    )
    changed |= replace_if_present(
        path,
        '<p className="mt-1 text-center text-[11px] leading-relaxed text-white/50">',
        f'<p className="mt-1 text-center text-[11px] leading-relaxed {muted}">',
    )
    # The digest footnote was barely-there white on black; ink at 40 keeps
    # it a footnote on light without dissolving it into the ground.
    changed |= replace_if_present(
        path,
        '<p className="font-data mt-1.5 break-all text-center text-[10px] text-white/25">',
        f'<p className="font-data mt-1.5 break-all text-center text-[10px] {ink}/40">',
    )
    # The two checkboxes and their labels: dark: variants only exist to
    # serve the dark band, and forcedTheme=dark would otherwise keep them
    # on even with the band light.
    changed |= replace_everywhere(
        path,
        'className="w-4 h-4 accent-bitzy bg-gray-100 border-gray-300 rounded '
        "focus:ring-bitzy dark:focus:ring-bitzy dark:ring-offset-gray-800 "
        'focus:ring-2 dark:bg-gray-700 dark:border-gray-600"',
        'className="w-4 h-4 accent-bitzy bg-gray-100 border-gray-300 rounded '
        'focus:ring-bitzy focus:ring-2"',
    )
    changed |= replace_everywhere(
        path,
        'className="text-sm font-medium text-gray-900 dark:text-gray-300"',
        f'className="text-sm font-medium {ink}"',
    )
    changed |= replace_if_present(
        path,
        'className="w-64 px-3 py-2 text-sm border border-gray-300 rounded-md '
        "focus:outline-none focus:ring-2 focus:ring-bitzy focus:border-transparent "
        'dark:bg-gray-700 dark:border-gray-600 dark:text-white dark:placeholder-gray-400"',
        'className="w-64 px-3 py-2 text-sm border '
        'border-[var(--color-hairline-light)] bg-white rounded-md text-[var(--color-ink)] '
        'placeholder:text-[var(--color-muted-warm)] focus:outline-none focus:ring-2 '
        'focus:ring-bitzy focus:border-transparent"',
    )
    changed |= replace_if_present(
        path,
        '<p className="mx-auto max-w-[400px] text-white/50 md:text-m">',
        f'<p className="mx-auto max-w-[400px] {muted} md:text-m">',
    )
    # The status card's idle branch: off the dark surface token and onto
    # white, the same pairing the rest of the page's panels use. The error
    # and done branches keep their tinted borders; the copy inside them is
    # shared with the idle one, so it moves here.
    changed |= replace_if_present(
        path,
        ": 'border-[var(--color-hairline)] bg-[var(--color-surface)]'",
        ": 'border-[var(--color-hairline-light)] bg-white'",
    )
    changed |= replace_if_present(
        path,
        '<p className="text-sm font-medium leading-snug text-white">',
        f'<p className="text-sm font-medium leading-snug {ink}">',
    )
    changed |= replace_if_present(
        path,
        '<div className="mt-3 h-1 w-full overflow-hidden rounded-full bg-white/10">',
        '<div className="mt-3 h-1 w-full overflow-hidden rounded-full '
        'bg-[var(--color-hairline-light)]">',
    )
    changed |= replace_if_present(
        path,
        '<div className="mt-3 border-t border-white/10 pt-2.5">',
        '<div className="mt-3 border-t border-[var(--color-hairline-light)] pt-2.5">',
    )
    # The two next-step paragraphs share a class; quiet on the second pass.
    changed |= replace_everywhere(
        path,
        '<p className="text-xs leading-relaxed text-white/60">',
        f'<p className="text-xs leading-relaxed {muted}">',
    )
    changed |= replace_if_present(
        path,
        '<p className="font-data mt-1.5 break-all text-[10px] text-white/30">',
        f'<p className="font-data mt-1.5 break-all text-[10px] {ink}/40">',
    )
    changed |= replace_if_present(
        path,
        '<p className="mt-2.5 text-xs leading-relaxed text-white/50">',
        f'<p className="mt-2.5 text-xs leading-relaxed {muted}">',
    )
    note(changed, "LandingHero.tsx: the flasher band reads light -- ink, muted, white card")


# The Blue Pill's whole setup surface, written as one file: this is the
# fork's own component, upstream cannot conflict with it, and rewriting beats
# carrying an anchor for every sentence a later pass cuts. `download` stays
# in the props so the existing JSX anchor upstream's flows render -- which
# passes firmware.path -- does not have to change.
PANEL_SOURCE = '''import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';

type DevBoardPanelProps = {
  device: string;
  /** Passed by the flash controls; accepted so the anchor that renders the
   *  panel does not have to change when the panel stops using it. */
  download?: string;
};

/**
 * The one line the Blue Pill needs before flashing.
 *
 * The ESP32 devkit flashes like every other board on this site -- plug it
 * in and the flasher finds boot mode on its own -- so it shows nothing.
 * The Blue Pill has no such door: its ROM bootloader sits behind a BOOT0
 * jumper and speaks through an external serial adapter, and this page
 * never opens that door at all. The kit ships an ST-Link V2, so the board
 * is reached through its debug port instead -- wires and nothing else.
 * The line carries the wiring and the one constraint worth stating up
 * front: ST-Link V2 only.
 */
export default function DevBoardPanel({ device }: DevBoardPanelProps) {
  if (!isDevBoard(device) || !isStm32(device)) return null;

  return (
    <p className="mx-auto w-full max-w-xl text-sm leading-relaxed text-[var(--color-muted-warm)]">
      <span className="font-semibold text-[var(--color-ink)]">Blue Pill:</span> wire an
      ST-Link V2 to the board (SWDIO → SWDIO, SWCLK → SWCLK, GND → GND, 3V3
      → 3V3), then press Connect and pick it in the list. This path works
      with an ST-Link V2 only -- no BOOT0 jumper, no serial adapter.
    </p>
  );
}
'''


def patch_devboard_panel() -> None:
    """Setup panels and manual flashing instructions are gone.

    The ESP32 had two instruction panels (web flashing and esptool.py); both
    are dropped entirely -- the board flashes straight from the picker now.
    The STM32 keeps one compact line: the wiring for its ST-Link and the
    one thing Connect cannot work without.
    """
    path = ROOT / "src" / "components" / "bitzy" / "DevBoardPanel.tsx"
    current = path.read_text() if path.exists() else ""
    changed = current != PANEL_SOURCE
    if changed:
        path.write_text(PANEL_SOURCE)
    note(changed, "DevBoardPanel.tsx: one Blue Pill connection line, no panels")


def prune_dead_assets() -> None:
    """Files nothing renders any more, and firmware nothing can reach.

    The photographs died with the gradient backdrop, releases.json died
    with the Releases band (and the updater no longer commits it), and the
    firmware folders of devices the picker does not offer only grow the
    deploy -- one of them even carries the old brand name inside its bytes.
    The sync (-X theirs on a delete) and the nightly updater can both bring
    any of this back, so it is pruned before every build rather than once.
    """
    removed = []
    for rel in (
        "public/pictures/Bitronics_hw.png",
        "public/pictures/fondoNM3.png",
        "public/releases.json",
    ):
        path = ROOT / rel
        if path.exists():
            path.unlink()
            removed.append(rel)
    note(bool(removed), "pruned dead assets (photographs, releases.json)")
    for rel in removed:
        log(f"      {rel}")

    pruned = []
    firmware = ROOT / "public" / "firmware"
    if firmware.is_dir():
        for folder in sorted(firmware.iterdir()):
            if folder.is_dir() and folder.name not in SERVED_FIRMWARE:
                shutil.rmtree(folder)
                pruned.append(folder.name)
    note(bool(pruned), "pruned firmware for devices the picker does not offer")
    for name in pruned:
        log(f"      public/firmware/{name}")


PNG_TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")


def strip_png_metadata() -> None:
    """Drop PNG text chunks that name the old brand.

    The miner photographs were exported through the store's image tooling
    and carry its XMP as invisible metadata. Not shown on the page, but it
    is bytes in the deploy, so it goes: the whole chunk is removed (readers
    treat a file with no XMP as untagged) and a clean file passes through
    untouched. A match inside pixel data would survive here -- validation's
    byte scan is what fails loudly on it.
    """
    cleaned = []
    for png in sorted((ROOT / "public").rglob("*.png")):
        data = png.read_bytes()
        if b"bitronics" not in data.lower():
            continue
        out = bytearray(data[:8])
        pos = 8
        while pos + 12 <= len(data):
            length = int.from_bytes(data[pos : pos + 4], "big")
            kind = data[pos + 4 : pos + 8]
            payload = data[pos + 8 : pos + 8 + length]
            chunk_end = pos + 12 + length
            drop = kind in PNG_TEXT_CHUNKS and b"bitronics" in payload.lower()
            if not drop:
                out += data[pos:chunk_end]
            pos = chunk_end
            if kind == b"IEND":
                break
        if bytes(out) != data:
            png.write_bytes(bytes(out))
            cleaned.append(str(png.relative_to(ROOT)))
    note(bool(cleaned), "PNG metadata: old-brand XMP removed")
    for rel in cleaned:
        log(f"      {rel}")


def sweep_marks() -> None:
    """The net: every remaining old-brand reference, whatever shape it has.

    Four passes in order, each seeing what the last left:
      * URLs -- a link added in a file we have never seen;
      * the -bitronics token -- the CSS variable and every Tailwind utility
        built from it (--color-, text-, bg-, accent-, ring-);
      * word-marks, lower and upper case -- prose and comments, whole words
        only so bitronics-web-flasher in the footer credit and in this
        repo's own descriptions survives for validation to allow, and a
        filename fails loudly instead of being rewritten into a path that
        does not exist.
    .github rides along (those workflows are ours: sync keeps them). Docs
    get one extra pass for the old docker tag, which is ours to rename.
    """
    roots = [
        (ROOT / "src", False),
        (ROOT / ".github", False),
        (ROOT / "readme.md", True),
        (ROOT / "FIRMWARE_AUTOMATION.md", True),
    ]
    hits = []
    for root, is_doc in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            new = BITRONICS_URL.sub(SITE, text)
            new = new.replace("-bitronics", "-bitzy")
            new = WORD_MARK.sub("Bitzy Labs", new)
            new = UPPER_MARK.sub("BITZY LABS", new)
            if is_doc:
                new = new.replace("bitronics-web-flasher", "nmv2-web-flasher")
            if new != text:
                path.write_text(new)
                hits.append(str(path.relative_to(ROOT)))
    note(bool(hits), "sweep: URLs, -bitronics tokens, word-marks -> BitzyLabs")
    for hit in hits:
        log(f"      {hit}")


# --- Validation ------------------------------------------------------------


def validate() -> None:
    problems: list[str] = []

    if (ROOT / "public" / "CNAME").read_text().strip() != DOMAIN:
        problems.append(f"public/CNAME is not {DOMAIN}")

    for name in (LOGO_DARK, LOGO_LIGHT):
        logo = ROOT / "public" / "pictures" / name
        if not logo.is_file() or logo.stat().st_size == 0:
            problems.append(f"public/pictures/{name} missing or empty")

    # The favicon is upstream's file at upstream's path, so both halves of
    # the pair are checked: the overlay originals and the copies that ship.
    # The logo tile is this fork's own, pointed at by globals.css.
    favicon_copies = {
        "favicon.svg": ROOT / "public" / "pictures" / "favicon.svg",
        "favicon.ico": ROOT / "public" / "favicon.ico",
        "logo-tile.svg": ROOT / "public" / "pictures" / "logo-tile.svg",
    }
    for name, copy in favicon_copies.items():
        original = ASSETS / name
        if not original.is_file() or original.stat().st_size == 0:
            problems.append(f".bitzylabs-overlay/assets/{name} missing or empty")
        elif not copy.is_file() or copy.read_bytes() != original.read_bytes():
            problems.append(f"{copy.relative_to(ROOT)} missing or differs from the overlay")
    if (ASSETS / "logo-tile-dark.svg").exists() or (
        ROOT / "public" / "pictures" / "logo-tile-dark.svg"
    ).exists():
        problems.append("logo-tile-dark.svg: the dark band's tile is still on disk")
    # The tile carries the mark twice, on a diagonal: one mark is the grid
    # the reader found too busy, three is clutter.
    tile = ASSETS / "logo-tile.svg"
    if tile.is_file() and tile.read_text().count("<image") != 2:
        problems.append(
            ".bitzylabs-overlay/assets/logo-tile.svg: expected the two-mark diagonal tile"
        )
    layout = (ROOT / "src" / "app" / "layout.tsx").read_text()
    if "'/pictures/favicon.svg'" not in layout:
        problems.append("layout.tsx: the favicon link is gone")
    if f"themeColor: '{CRIMSON}'" not in layout:
        problems.append(f"layout.tsx: no themeColor pinned to {CRIMSON} (the store's)")

    if (ROOT / "public" / "pictures" / "bitronics-logo-dark.svg").exists():
        problems.append("the upstream Bitronics wordmark is still on disk")

    scanned = [
        ROOT / "src",
        ROOT / "public" / "CNAME",
        ROOT / "next.config.js",
    ]
    for path in scanned:
        files = [path] if path.is_file() else sorted(path.rglob("*"))
        for f in files:
            if not f.is_file() or f.suffix in {".png", ".webp", ".jpg", ".woff2", ".bin"}:
                continue
            try:
                text = f.read_text()
            except UnicodeDecodeError:
                continue
            for needle in FORBIDDEN:
                if needle in text:
                    problems.append(f"{f.relative_to(ROOT)}: still contains {needle!r}")

    css = (ROOT / "src" / "app" / "globals.css").read_text()
    if f"--color-bitzy: {CRIMSON};" not in css:
        problems.append(f"globals.css: --color-bitzy is not {CRIMSON}")
    if f"--color-bitzy: {CRIMSON_PREV};" in css:
        problems.append(f"globals.css: the first crimson {CRIMSON_PREV} is still defined")
    if "-bitronics" in css:
        problems.append("globals.css: still defines the -bitronics token")
    # The store's scheme and this flasher's motion: every one of these is
    # something the patcher puts in and a fresh upstream sync would take
    # straight back out, so the end state is judged on their presence and
    # not only on the old brand's absence.
    for needle, what in (
        (f"--color-band-light: {STORE_BG};", "the store's warm ground"),
        (f"--color-ink: {STORE_INK};", "the store's ink"),
        (f"--color-hairline-light: {STORE_LINE};", "the store's line"),
        (f"--color-muted-warm: {STORE_MUTED};", "muted text for light surfaces"),
        (f"--color-chrome: {STORE_INK};", "the dark chrome on the store's ink"),
        ("--primary: 348 83.33% 47.06%;", "the crimson CTA, exact"),
        ("    --ring: 348 83.33% 47.06%;", "the crimson focus ring, exact"),
        ("background-color: rgba(255, 255, 255, 0.85)", "the store's white header"),
        ("backdrop-filter: blur(14px)", "the header's blur"),
        (".bitzy-hero {", "the flasher's own light band"),
        (
            f"linear-gradient(180deg, #ffffff 0%, {STORE_BG} 62%, {STORE_BG} 100%)",
            "the band lifting off white into the ground",
        ),
        ("background-color: #ffffff !important;", "the select's white pins"),
        ("border: 1px solid #E7E4DE !important;", "the select's hairline pin"),
        ("rgba(220, 20, 60, 0.08)", "the select's crimson row wash"),
        ("url('/pictures/logo-tile.svg')", "the mark tiled on the warm ground"),
        (
            "background-size: 512px auto, auto, auto;",
            "the half-density diagonal tile cell",
        ),
        ("animation-timeline: view()", "the scroll-timed reveal"),
        ("@keyframes bitzy-glow", "the hero's drifting glow"),
        ("box-shadow: 0 10px 26px rgba(220, 20, 60, 0.32)", "the store's button glow"),
        ("@media (prefers-reduced-motion: reduce)", "the reduce-motion stop"),
    ):
        if needle not in css:
            problems.append(f"globals.css: {needle!r} missing ({what})")
    if "#0e0e13" in css:
        problems.append("globals.css: the old black gradient is still defined")
    if "#0f0f13" in css:
        problems.append("globals.css: the flasher band's dark ground is still defined")
    if "logo-tile-dark" in css:
        problems.append("globals.css: the band still points at the dark tile")
    for gone in ("#212121", "#374151"):
        if gone in css:
            problems.append(f"globals.css: the select's dark pin {gone} is still there")
    if "256px auto" in css:
        problems.append("globals.css: the old single-mark 256px tile cell is still there")
    # The rounded HSL is a shade off #DC143C; the exact one must be what
    # ships, and the exact one must not contain the rounded one as a string.
    if "348 83% 47%" in css:
        problems.append("globals.css: the rounded crimson HSL is still there")
    # forcedTheme=dark puts this block's values on <html>, so with the whole
    # site light it is here the light scheme has to be said: the shadcn
    # surfaces (the select's trigger and list, borders, inherited text) all
    # read from it, and upstream's dark values ship again on every sync.
    dark_block = re.search(r"\.dark \{(.*?)\n  \}", css, re.S)
    if not dark_block:
        problems.append("globals.css: the .dark block is gone")
    else:
        block = dark_block.group(1)
        for needle, what in (
            ("--background: 0 0% 100%;", "white shadcn surfaces"),
            ("--foreground: 0 0% 13.33%;", "ink for inherited text"),
            ("--popover: 0 0% 100%;", "the select's white list"),
            ("--border: 40 15.8% 88.8%;", "the store's line as the default border"),
            ("--muted-foreground: 41 4.3% 41%;", "the store's muted"),
            ("--primary: 348 83.33% 47.06%;", "the crimson CTA"),
        ):
            if needle not in block:
                problems.append(f"globals.css: .dark {needle!r} missing ({what})")
        for gone in ("0 84% 4.9%", "217.2 32.6% 17.5%"):
            if gone in block:
                problems.append(f"globals.css: .dark still carries upstream's {gone}")

    # --- Zero traces --------------------------------------------------------
    # Nothing old-brand may ship in any case: tokens, prose, URLs, filenames
    # or image metadata. Byte scan, over src, the workflows we keep, the root
    # docs, and every last byte of public/ -- the PNG XMP and the firmware
    # binaries included, since "0 traces" was asked for with a grep in mind.
    # Two exemptions, both on purpose: scripts/ (the tool that removes a
    # thing has to be able to name it), and the upstream repository's own
    # path, which survives only where the reader asked for a credit linking
    # to it -- the footer, and sync's description of what it syncs.
    scan_roots = [ROOT / "src", ROOT / ".github", ROOT / "public", ROOT / "next.config.js"]
    for root in (ROOT / "readme.md", ROOT / "FIRMWARE_AUTOMATION.md", ROOT / "Dockerfile"):
        if root.exists():
            scan_roots.append(root)
    tracked = UPSTREAM_REPO_PATH.encode()
    for root in scan_roots:
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for f in files:
            if not f.is_file():
                continue
            try:
                data = f.read_bytes()
            except OSError as error:
                problems.append(f"{f.relative_to(ROOT)}: unreadable ({error})")
                continue
            if b"bitronics" in data.replace(tracked, b"").lower():
                problems.append(f"{f.relative_to(ROOT)}: still contains 'bitronics'")
            if b"bitronics" in f.name.encode().lower() and f.is_file():
                problems.append(f"{f.relative_to(ROOT)}: old-brand filename on disk")
    # Root-level files the loop above does not recurse into (package.json,
    # tsconfig, the workflow scripts' neighbours): cheap to cover completely.
    for f in sorted(ROOT.iterdir()):
        if not f.is_file() or f.name in {"Dockerfile", "readme.md", "FIRMWARE_AUTOMATION.md", "next.config.js"}:
            continue
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if b"bitronics" in data.replace(tracked, b"").lower():
            problems.append(f"{f.name}: still contains 'bitronics'")

    footer = ROOT / "src" / "components" / "Footer.tsx"
    if footer.exists():
        footer_text = footer.read_text()
        if "FIRMWARE_LINKS" in footer_text:
            problems.append("Footer.tsx: the firmware links column is still present")
        # The notice dialog is a surface like any other: white card, and
        # no white-on-anything copy left anywhere in the file.
        if "bg-white p-6 text-[var(--color-ink)]" not in footer_text:
            problems.append("Footer.tsx: the notice dialog is not the white card")
        for gone in ("text-white", "bg-[var(--color-surface)]"):
            if gone in footer_text:
                problems.append(f"Footer.tsx: the notice dialog's {gone!r} is still there")

    # Tailwind v4 scans every file in the project for class candidates, so a
    # yellow utility spelled out anywhere -- including in this script -- would
    # ship in the CSS bundle.
    yellow_chip = "text-[#" "4A4200]"
    for script in sorted((ROOT / "scripts").rglob("*.py")):
        if yellow_chip in script.read_text():
            problems.append(
                f"{script.relative_to(ROOT)}: spells out the old yellow utility class, "
                "which Tailwind will emit into the built CSS"
            )

    page = (ROOT / "src" / "app" / "page.tsx").read_text()
    if "<Features />" not in page:
        problems.append("page.tsx: the Features band is not rendered")
    if "<Releases />" in page or "components/Releases'" in page:
        problems.append("page.tsx: the Releases section is still rendered")

    # --- Curation -----------------------------------------------------------
    # The picker's tables are upstream's data, re-filtered on every run: what
    # is judged is the offer the reader can actually see.
    catalog = (ROOT / "src" / "lib" / "devices.ts").read_text()
    categories_block = re.search(
        r"export const CATEGORIES:.*? = \[\n(.*?)\n\];", catalog, re.S
    )
    category_ids = re.findall(
        r"id: '([^']+)'", categories_block.group(1) if categories_block else ""
    )
    if category_ids != ["devboards", "miners"]:
        problems.append(
            f"devices.ts: categories are {category_ids}, expected ['devboards', 'miners']"
        )
    sources_block = re.search(
        r"export const DEVICE_SOURCES: DeviceSource\[\] = \[\n(.*?)\n\];", catalog, re.S
    )
    sources_text = sources_block.group(1) if sources_block else ""
    miner_devices = re.findall(r"device: '([^']+)',\s*\n\s*category: 'miners',", sources_text)
    if miner_devices != ["NerdMiner"]:
        problems.append(
            f"devices.ts: the miners section offers {miner_devices}, expected ['NerdMiner']"
        )
    if re.search(r"category: 'tools'", sources_text) or re.search(r"id: 'tools'", catalog):
        problems.append("devices.ts: the Tools section is still offered")
    for board in (
        "ESP32-2432S024",
        "ESP32-2432S028R",
        "ESP32_2432S028_2USB",
        "ESP32-S3-devKitv1",
        "esp32-s3-devkitc1-n32r8",
    ):
        if f"'{board}'" not in catalog:
            problems.append(f"devices.ts: NerdMiner allowlist misses {board!r}")
    if "includes: (board) =>" not in catalog:
        problems.append("devices.ts: NerdMiner has no board allowlist")

    firmware_root = ROOT / "public" / "firmware"
    present_folders = (
        sorted(p.name for p in firmware_root.iterdir() if p.is_dir())
        if firmware_root.is_dir()
        else []
    )
    if present_folders != sorted(SERVED_FIRMWARE):
        problems.append(
            f"public/firmware: {present_folders} != {sorted(SERVED_FIRMWARE)} "
            "(only the picker's devices may ship)"
        )
    for rel in (
        "public/pictures/Bitronics_hw.png",
        "public/pictures/fondoNM3.png",
        "public/releases.json",
    ):
        if (ROOT / rel).exists():
            problems.append(f"{rel}: should have been pruned")

    # --- Appearance ---------------------------------------------------------
    hero = (ROOT / "src" / "components" / "LandingHero.tsx").read_text()
    if "document.body.style.background" in hero:
        problems.append("LandingHero.tsx: JavaScript still paints the page background")
    if (
        '<section className="bitzy-hero w-full py-10 text-[var(--color-ink)] md:py-14">'
        not in hero
    ):
        problems.append("LandingHero.tsx: the band is not the light one")
    if "store's own light band" not in hero:
        problems.append("LandingHero.tsx: the CSS-canvas comment above the hero is gone")
    if "own dark band" in hero or "dark palette" in hero:
        problems.append("LandingHero.tsx: the comment still describes a dark band")
    # The band is light, so nothing inside it may still speak for the dark
    # one: white copy, dark: utilities (forcedTheme keeps them live page-
    # wide), or the dark surface token. The terminal keeps its own black.
    if "text-white" in hero:
        problems.append("LandingHero.tsx: the band still carries white text")
    if "dark:" in hero:
        problems.append("LandingHero.tsx: dark: utilities remain on the light band")
    if "bg-[var(--color-surface)]" in hero:
        problems.append("LandingHero.tsx: the status card still sits on the dark surface")
    if "#0e0e13" in hero:
        problems.append("LandingHero.tsx: the old black gradient is still spelled out")
    for photo in ("Bitronics_hw", "fondoNM3"):
        if photo in hero:
            problems.append(f"LandingHero.tsx: still references {photo}.png")

    strip = (ROOT / "src" / "components" / "ShopStrip.tsx").read_text()
    if "band-gold" in strip:
        problems.append("ShopStrip.tsx: still uses the crimson fill")
    for cls in (
        "bg-white",
        "border-[2px]",
        "border-[var(--color-bitzy)]",
        "text-[var(--color-bitzy)]",
        "px-6 py-5",
    ):
        if cls not in strip:
            problems.append(
                f"ShopStrip.tsx: missing {cls!r} (white band, 2px crimson border, taller)"
            )
    features = (ROOT / "src" / "components" / "Features.tsx").read_text()
    if "band-light w-full py-6 md:py-8" not in features:
        problems.append("Features.tsx: the tightened end padding py-6/8 is missing")
    for gone in ("py-16 md:py-24", "py-8 md:py-12"):
        if gone in features:
            problems.append(f"Features.tsx: the loose end padding {gone!r} is still there")
    for gone, tight in (
        ("mb-10 text-center", "mb-4 text-center"),
        ("mb-6 text-center", "mb-4 text-center"),
        ("gap-4 md:grid-cols-3", "gap-2.5 md:grid-cols-3"),
        ("gap-3 md:grid-cols-3", "gap-2.5 md:grid-cols-3"),
        ("bg-white p-6", "bg-white p-3"),
        ("bg-white p-4", "bg-white p-3"),
        ("font-display mt-4 font-bold", "font-display mt-2.5 font-bold"),
        ("font-display mt-3 font-bold", "font-display mt-2.5 font-bold"),
        ("h-10 w-10 items-center", "h-9 w-9 items-center"),
        ('className="mt-1.5 text-sm', 'className="mt-1 text-sm'),
    ):
        if gone in features:
            problems.append(f"Features.tsx: loose interior spacing {gone!r} still there")
        if tight not in features:
            problems.append(f"Features.tsx: tight interior spacing {tight!r} missing")
    header = (ROOT / "src" / "components" / "Header.tsx").read_text()
    if f'href="https://{DOMAIN}"' not in header:
        problems.append("Header.tsx: the logo does not link to the flasher")
    if "bitzylabs-logo-light.png" not in header:
        problems.append("Header.tsx: the light wordmark is not on the white bar")
    if "text-white/70" in header:
        problems.append("Header.tsx: the nav still carries the dark bar's white")
    if "text-[var(--color-muted-warm)]" not in header:
        problems.append("Header.tsx: the nav is not store-muted")
    # Both links bigger and both centred: Shop *and* Instructions in the
    # nav block, the nav itself carrying the larger size, and the
    # small-screen copy still there because the nav hides below md.
    if "text-base font-medium text-[var(--color-muted-warm)]" not in header:
        problems.append("Header.tsx: the nav links are not at the larger store size")
    try:
        nav_block = header[header.index("<nav") : header.index("</nav>")]
    except ValueError:
        nav_block = ""
        problems.append("Header.tsx: the centred nav is gone")
    if "onTogglePanel" not in nav_block:
        problems.append("Header.tsx: Instructions is not in the centred nav")
    if "aria-expanded={panelOpen}" not in nav_block:
        problems.append("Header.tsx: the drawer's trigger does not report its state")
    if "onOpenPanel" in header:
        problems.append("Header.tsx: the one-way prop name is still there")
    if "md:hidden" not in header:
        problems.append("Header.tsx: no small-screen instructions button left for mobile")

    # The steps drawer opens off that bar, so it is judged light with it.
    drawer = (ROOT / "src" / "components" / "InstructionPanel.tsx").read_text()
    for needle, what in (
        ("bg-white text-[var(--color-ink)]", "the white drawer"),
        ("border-[var(--color-hairline-light)]", "the light dividers"),
        ("text-[var(--color-muted-warm)]", "store-muted body text"),
    ):
        if needle not in drawer:
            problems.append(f"InstructionPanel.tsx: {needle!r} missing ({what})")
    for gone in ("text-white", "bg-[var(--color-chrome)]"):
        if gone in drawer:
            problems.append(f"InstructionPanel.tsx: the dark drawer's {gone!r} is still there")

    # The bar's control is a toggle: first click opens, second shuts, and
    # the one-way wiring that could only ever open must be gone.
    if "setIsPanelOpen((wasOpen) => !wasOpen)" not in hero:
        problems.append("LandingHero.tsx: Instructions does not toggle the drawer")
    if "setIsPanelOpen(true)" in hero:
        problems.append("LandingHero.tsx: the one-way open wiring is still there")
    if "panelOpen={isPanelOpen}" not in hero:
        problems.append("LandingHero.tsx: the drawer's state does not reach the bar")

    # The two pickers open off the same band, so they are judged with it:
    # white panels with light dividers, and no dark-chrome leftover.
    for rel in ("DeviceModal.tsx", "BoardPicker.tsx"):
        picker = (ROOT / "src" / "components" / rel).read_text()
        for needle, what in (
            ("bg-white", "the white panel"),
            ("border-[var(--color-hairline-light)]", "the light dividers"),
            ("text-[var(--color-muted-warm)]", "store-muted supporting text"),
            ("text-[var(--color-ink)]", "ink headings"),
        ):
            if needle not in picker:
                problems.append(f"{rel}: {needle!r} missing ({what})")
        for gone in ("bg-[var(--color-chrome)]", "bg-[var(--color-surface)]", "text-white"):
            if gone in picker:
                problems.append(f"{rel}: the dark picker's {gone!r} is still there")

    # --- Credits ------------------------------------------------------------
    footer_text = (ROOT / "src" / "components" / "Footer.tsx").read_text()
    # The store's footer: white ground, ink text, light wordmark, muted
    # links with a crimson hover, and no leftover of the dark one.
    for needle, what in (
        ('<footer className="mt-8 w-full border-t border-[var(--color-hairline-light)] bg-white text-[var(--color-ink)]">', "the white ground, without the inherited 64px of air"),
        ("bitzylabs-logo-light.png", "the light wordmark"),
        ("text-[var(--color-muted-warm)]", "muted links and text"),
        ('hover:text-[var(--color-bitzy)]', "the crimson hover"),
    ):
        if needle not in footer_text:
            problems.append(f"Footer.tsx: {needle!r} missing ({what})")
    for gone in ("hover:text-white/70", "bg-[var(--color-chrome)]"):
        if gone in footer_text:
            problems.append(f"Footer.tsx: the dark footer's {gone} is still there")
    for href in (
        "https://github.com/WantClue",
        f"https://github.com/{UPSTREAM_REPO_PATH}",
        "https://github.com/Hypothesis-Magic/stm32-web-flasher",
    ):
        if href not in footer_text:
            problems.append(f"Footer.tsx: no credit link to {href}")
    for name in ("WantClue", "BitMaker", "Hypothesis-Magic"):
        if f"\n                {name}\n" not in footer_text:
            problems.append(f"Footer.tsx: {name} is not credited by name")

    # --- The panel ----------------------------------------------------------
    # Setup instructions and the manual flashing route are gone; one Blue
    # Pill connection line is all that is left, and it still has to say the
    # two things Connect cannot work without.
    panel = (ROOT / "src" / "components" / "bitzy" / "DevBoardPanel.tsx").read_text()
    for gone in (
        "Or flash it yourself",
        "st-flash",
        "esptool.py",
        "Getting ready",
        "Before you connect",
        "<Download",
    ):
        if gone in panel:
            problems.append(f"DevBoardPanel.tsx: instruction panel remnant {gone!r}")
    for needed in ("ST-Link V2", "SWDIO", "SWCLK", "isStm32"):
        if needed not in panel:
            problems.append(f"DevBoardPanel.tsx: {needed!r} missing (one-line panel)")
    if "text-white" in panel:
        problems.append("DevBoardPanel.tsx: the line still speaks for the dark band")

    # --- DevBoard Tests ----------------------------------------------------
    # The end state being guarded: the picker offers both devboards, they are
    # wired into the flash flow, and each manifest hashes to the binary it
    # ships. A half-applied injection here would build green and still put a
    # device on the page that cannot flash -- the same failure mode the
    # branding patches are judged on, for the same reason.
    for rel in DEVBOARD_FILES:
        asset = ROOT / rel
        if not asset.is_file() or asset.stat().st_size == 0:
            problems.append(f"{rel} missing or empty (DevBoard Tests overlay)")

    for needle in (
        "'devboards'",
        "DevBoard Tests",
        "ESP 32 N16R8",
        "STM 32 BluePill",
        "esp32s3-smoothblinky",
        "stm32-bluepill",
        "mcu?: 'esp32' | 'stm32'",
    ):
        if needle not in catalog:
            problems.append(f"devices.ts: {needle!r} missing (DevBoard Tests)")

    # The picker's tiles come from this table, so a device left out of it is
    # unreachable no matter what devices.ts claims.
    try:
        picker = json.loads(
            (ROOT / "src" / "components" / "firmware_data.json").read_text()
        )
        tile_names = {entry.get("name") for entry in picker.get("devices", [])}
    except ValueError:
        tile_names = set()
        problems.append("firmware_data.json is no longer valid JSON")
    for name in ("ESP 32 N16R8", "STM 32 BluePill"):
        if name not in tile_names:
            problems.append(f"firmware_data.json: no tile for {name!r}")

    for needle in (
        "Continue To Flash",
        "DevBoardPanel",
        "=== 'devboards'",
        "value={selectedFirmware}",
        # The STM32 path: Connect routes to WebUSB, the gate judges the
        # probe rather than a port that will never open, and the SWD flow
        # is the only Blue Pill flash arm left.
        "// The STM32 path is WebUSB, not Web Serial:",
        "The gate asks for the link this device type actually got",
        "Serial logging is not available on this board",
        "flashBluePillSwdFlow",
        "handleConnectStlink",
    ):
        if needle not in hero:
            problems.append(f"LandingHero.tsx: {needle!r} missing (DevBoard flow)")

    # Each manifest's recorded hash must match the binary beside it, or the
    # flasher refuses its own firmware at the door -- and this is the only
    # place that notices a swapped-in build without a browser to try it.
    for slug in ("esp32s3-smoothblinky", "stm32-bluepill"):
        folder = ROOT / "public" / "firmware" / slug
        try:
            main_manifest = json.loads((folder / "manifest.json").read_text())
            for version in main_manifest.get("versions", []):
                per_version = json.loads(
                    (folder / version / "manifest.json").read_text()
                )
                for board, expected in per_version.get("sha256", {}).items():
                    blob = folder / version / f"{board}_factory.bin"
                    if not blob.is_file():
                        problems.append(f"{slug}/{version}: {blob.name} is missing")
                    elif (
                        hashlib.sha256(blob.read_bytes()).hexdigest() != expected
                    ):
                        problems.append(
                            f"{slug}/{version}: {blob.name} does not match the "
                            "hash recorded in its manifest"
                        )
        except (OSError, ValueError) as error:
            problems.append(f"public/firmware/{slug}: unreadable manifest ({error})")

    if problems:
        raise PatchError("overlay validation failed:\n  - " + "\n  - ".join(problems))

    print(
        "\nValidation passed: zero old-brand traces ship, the picker offers only "
        "DevBoard Tests + NerdMiner, the DevBoard Tests section is complete, and "
        "the store's scheme (crimson, warm ground, white bar and footer) carries "
        "the page."
    )


# --- Entry point -----------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate only; never write"
    )
    args = parser.parse_args()

    print("Applying BitzyLabs branding...")
    try:
        if not args.check:
            patch_cname()
            patch_assets()
            patch_header()
            patch_instruction_panel()
            # After the header: it carries what patch_header lands and turns
            # the Instructions control into a toggle.
            patch_instructions_toggle()
            patch_footer()
            patch_shop_strip()
            patch_features()
            patch_page()
            patch_layout()
            patch_palette()
            # After the palette: the header rule, the canvas and the motion
            # are globals.css text built from the same colour constants.
            patch_chrome()
            patch_selector()
            patch_device_shops()
            patch_devboards()
            # The picker filter runs after the rows are injected, so it sees
            # the fork's own additions alongside upstream's and keeps both.
            patch_picker_scope()
            patch_backgrounds()
            # After the backgrounds pass: it lands the band's line and
            # comment, and these finish what sits inside the band and the
            # pickers that open off it.
            patch_hero_light()
            patch_picker_panels()
            patch_devboard_panel()
            prune_dead_assets()
            strip_png_metadata()
            # Last write, so every targeted patch gets first refusal on the
            # anchors it knows and the sweep only sees what they left.
            sweep_marks()
        validate()
    except PatchError as error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
