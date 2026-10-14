#!/usr/bin/env python3
"""Re-apply the BitzyLabs overlay on top of the upstream Bitronics flasher.

The repository tracks BitMaker-hub/bitronics-web-flasher, merging upstream
into main on every sync. The fork's own files survive that merge untouched
(never present upstream), but everything the fork changes *inside upstream's
files* -- the branding, and the DevBoard Tests section -- is re-applied here
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
state* (no Bitronics URL, no Bitronics title, our logo, our palette, the
sections gone, both DevBoard devices catalogued and wired to flash). A patch
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

CRIMSON = "#DB092A"  # sampled from the logo artwork itself
CRIMSON_DEEP = "#B00722"  # the crimson that stays legible on a light surface
INK_ON_CRIMSON = "#FFFFFF"

SITE = "https://www.bitzylabs.com"
DOMAIN = "flasher.bitzylabs.com"
BRAND = "Bitzy Labs"

ASSETS = ROOT / ".bitzylabs-overlay" / "assets"
LOGO_DARK = "bitzylabs-logo-dark.png"  # crimson mark + white wordmark
LOGO_LIGHT = "bitzylabs-logo-light.png"  # crimson mark + ink wordmark

# Every string that must not survive into a deploy.
FORBIDDEN = ("bitronics.store", "#ECD400", "#4A4200", "#7A6D00")

# Any Bitronics URL, however it was written: subdomain, path, query. Anchored
# on the domain rather than on surrounding code so upstream restructuring a
# component cannot slip a new link past it.
BITRONICS_URL = re.compile(
    r"""https?://(?:[a-z0-9-]+\.)*bitronics\.store[^\s'"`)\\]*""", re.IGNORECASE
)


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


def replace_if_present(path: Path, old: str, new: str) -> bool:
    """Replace `old` with `new`, but stay quiet when `old` is simply gone.

    Used where upstream may reasonably reword the text: a missing anchor then
    means there is nothing left to rebrand, which is the outcome we wanted.
    Validation decides whether the end state is acceptable either way.
    """
    return replace_once(path, old, new, required=False)


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
    # The upstream wordmarks are not ours and are no longer referenced.
    for stale in ("bitronics-logo-dark.svg", "bitronics-logo-light.svg"):
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
    changed |= replace_once(
        path,
        "            src={`${basePath}/pictures/bitronics-logo-dark.svg`}\n"
        '            alt="Bitronics"\n'
        '            className="h-7 w-auto"\n',
        "            src={`${basePath}/pictures/bitzylabs-logo-dark.png`}\n"
        f'            alt="{BRAND}"\n'
        '            className="h-8 w-auto object-contain"\n',
    )
    changed |= replace_if_present(
        path,
        "{/* The BITRONICS + FLASHER lockup, the same shape the pool site uses */}",
        "{/* The Bitzy Labs + FLASHER lockup */}",
    )
    note(changed, "Header.tsx: logo, site link, nav")


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
    changed |= replace_once(
        path,
        "                src={`${basePath}/pictures/bitronics-logo-dark.svg`}\n"
        '                alt="Bitronics"\n'
        '                className="h-6 w-auto"\n',
        "                src={`${basePath}/pictures/bitzylabs-logo-dark.png`}\n"
        f'                alt="{BRAND}"\n'
        '                className="h-7 w-auto object-contain"\n',
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
    # Two columns remain, so two columns is what the grid must ask for.
    changed |= replace_once(path, "md:grid-cols-3", "md:grid-cols-2")
    note(changed, "Footer.tsx: logo, site links, copyright, firmware column dropped")


def patch_shop_strip() -> None:
    path = ROOT / "src" / "components" / "ShopStrip.tsx"
    changed = replace_if_present(
        path, 'href="https://bitronics.store/collections/best-sellers"', f'href="{SITE}"'
    )
    note(changed, "ShopStrip.tsx: 'Rather not build one' link -> BitzyLabs")


def patch_page() -> None:
    """Drop the Features band and the Releases / 'Stay updated' band.

    Upstream's page is LandingHero -> ShopStrip -> Features -> Releases ->
    Footer. Features is the section that sat directly above the footer on the
    site we ship, and Releases is upstream's firmware changelog. Neither
    belongs on ours, leaving hero -> shop strip -> footer.
    """
    path = ROOT / "src" / "app" / "page.tsx"

    def is_dropped(line: str) -> bool:
        stripped = line.strip()
        return stripped in {
            "import Features from '@/components/Features'",
            "import Releases from '@/components/Releases'",
            "<Features />",
            "<Releases />",
        }

    changed = drop_lines(path, is_dropped)
    text = path.read_text()
    for leftover in ("Features", "Releases"):
        if f"components/{leftover}'" in text or f"<{leftover} />" in text:
            raise PatchError(f"page.tsx: {leftover} is still referenced")
    note(changed, "page.tsx: removed Features and Releases sections")


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
    note(changed, "layout.tsx: page title and description")


def patch_palette() -> None:
    """One line per colour rather than the whole block.

    Upstream rewrites comments; they restate rarely, if ever. Anchoring each
    value alone means a reworded comment above them cannot stop the palette
    from being patched, while a genuinely changed value still fails loudly.
    """
    path = ROOT / "src" / "app" / "globals.css"
    changed = replace_once(
        path, "--color-bitronics: #ECD400;", f"--color-bitronics: {CRIMSON};"
    )
    changed |= replace_once(
        path, "--color-gold-ink: #4A4200;", f"--color-gold-ink: {INK_ON_CRIMSON};"
    )
    changed |= replace_once(
        path, "--color-gold-deep: #7A6D00;", f"--color-gold-deep: {CRIMSON_DEEP};"
    )
    # Comments only: upstream is free to restate them, the colours are not.
    # Whole block first, then the opening line on its own, so a reworded
    # middle line leaves the rest of upstream's wording behind.
    changed |= replace_if_present(
        path,
        "  /* Bitronics design system, kept in step with the store theme's brand.css.\n"
        "     Rules that come with it: one accent per block, gold is a hit and not a\n"
        "     background, mono only for figures, and gold is never text on a light\n"
        "     surface (there it is a fill or a border). */\n",
        "  /* Bitzy Labs palette on upstream's structure. The accent rules survive:\n"
        "     one accent per block, crimson is a hit and not a background, mono only\n"
        "     for figures, and crimson is never text on a light surface (there it is\n"
        "     a fill or a border). */\n",
    )
    changed |= replace_if_present(
        path,
        "  /* Bitronics design system, kept in step with the store theme's brand.css.",
        "  /* Bitzy Labs palette on upstream's structure.",
    )
    changed |= replace_if_present(
        path,
        "/* The BITRONICS + FLASHER lockup, the same shape as the POOL badge */",
        "/* The Bitzy Labs + FLASHER lockup */",
    )
    note(changed, f"globals.css: yellow -> crimson {CRIMSON} (text on it -> white)")


def patch_selector() -> None:
    path = ROOT / "src" / "components" / "Selector.tsx"
    # Built by concatenation on purpose: Tailwind v4 scans every file in the
    # project for class candidates, so this script writing the class literally
    # would ship the dead yellow utility in the CSS bundle.
    old_chip = "text-[#" "4A4200]"
    changed = replace_once(path, old_chip, "text-white")
    note(changed, "Selector.tsx: 'latest' chip text -> white on crimson")


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
    "src/lib/bitzy/stm32flash.ts",
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

    Upstream owns three files this touches, so each edit is anchored on the
    exact text as it stands today and fails loudly if upstream moved it --
    the same standard as the branding's structure patches, and for the same
    reason: a device the picker offers but cannot flash is worse than a
    failed sync. The overlay's own code (lib/bitzy, components/bitzy, the
    pictures, the firmware folders) needs no patching; the merge brings it.
    """
    devices_ts = ROOT / "src" / "lib" / "devices.ts"
    changed_devices = False

    changed_devices |= replace_once(
        devices_ts,
        "export type DeviceCategory = 'miners' | 'tools';",
        "export type DeviceCategory = 'miners' | 'tools' | 'devboards';",
    )

    changed_devices |= replace_once(
        devices_ts,
        "  detectChip?: boolean;\n};",
        "  detectChip?: boolean;\n"
        "  /**\n"
        "   * Which silicon the device's flasher talks to. Absent means the esptool\n"
        "   * path every miner and tool takes; 'stm32' takes the ROM bootloader path.\n"
        "   */\n"
        "  mcu?: 'esp32' | 'stm32';\n"
        "};",
    )

    # First in the array, because the picker renders these sections in order
    # and DevBoard Tests belongs before the miners.
    changed_devices |= replace_once(
        devices_ts,
        "export const CATEGORIES: { id: DeviceCategory; title: string; blurb: string }[] = [\n"
        "  {\n"
        "    id: 'miners',",
        "export const CATEGORIES: { id: DeviceCategory; title: string; blurb: string }[] = [\n"
        "  {\n"
        "    id: 'devboards',\n"
        "    title: 'DevBoard Tests',\n"
        "    blurb: 'Blinky builds for the boards on our own bench.',\n"
        "  },\n"
        "  {\n"
        "    id: 'miners',",
    )

    changed_devices |= replace_once(
        devices_ts,
        "export const DEVICE_SOURCES: DeviceSource[] = [\n"
        "  {\n"
        "    device: 'NerdMiner',",
        "export const DEVICE_SOURCES: DeviceSource[] = [\n"
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
        "  },\n"
        "  {\n"
        "    device: 'NerdMiner',",
    )
    note(changed_devices, "devices.ts: DevBoard Tests category + two devices")

    # The picker builds its tiles from this table; a device missing here is a
    # device nobody can reach, no matter what devices.ts says.
    picker = ROOT / "src" / "components" / "firmware_data.json"
    changed_picker = replace_once(
        picker,
        '  "devices": [\n'
        "    {\n"
        '      "name": "NerdMiner",',
        '  "devices": [\n'
        "    {\n"
        '      "name": "ESP 32 N16R8",\n'
        '      "picture": "pictures/esp32-n16r8.png",\n'
        '      "boards": []\n'
        "    },\n"
        "    {\n"
        '      "name": "STM 32 BluePill",\n'
        '      "picture": "pictures/stm32-bluepill.png",\n'
        '      "boards": []\n'
        "    },\n"
        "    {\n"
        '      "name": "NerdMiner",',
    )
    note(changed_picker, "firmware_data.json: tiles for both devboards")

    patch_devboard_flows()


def patch_devboard_flows() -> None:
    """LandingHero: the Continue button, the STM32 path, the instructions.

    Seven anchors in one file, split out so a failure names the step rather
    than the file. Every one is exact text; the wrapping ones re-indent the
    original inside an `else`, which replace_once recognises as already
    applied on a second run.
    """
    path = ROOT / "src" / "components" / "LandingHero.tsx"
    changed = False

    changed |= replace_once(
        path,
        "import BoardArt from './BoardArt';\nimport DeviceIntro from './DeviceIntro';",
        "import BoardArt from './BoardArt';\n"
        "import DeviceIntro from './DeviceIntro';\n"
        "import DevBoardPanel from './bitzy/DevBoardPanel';\n"
        "import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';\n"
        "import { flashBluePill } from '@/lib/bitzy/stm32flash';",
    )

    changed |= replace_once(
        path,
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

    # The Blue Pill needs even parity (AN2606); nothing else on this site
    # does, so only its connect opens the port that way.
    changed |= replace_once(
        path,
        "      const port = await navigator.serial.requestPort();\n"
        "      await port.open({\n"
        "        baudRate: 115200,\n"
        "        dataBits: 8,\n"
        "        stopBits: 1,\n"
        "        parity: 'none',\n"
        "        flowControl: 'none',\n"
        "      });",
        "      const port = await navigator.serial.requestPort();\n"
        "      // The STM32 ROM bootloader runs 8 data bits, even parity, 1 stop bit\n"
        "      // (AN2606); everything else on this site is a plain 8-N-1 link.\n"
        "      await port.open({\n"
        "        baudRate: 115200,\n"
        "        dataBits: 8,\n"
        "        stopBits: 1,\n"
        "        parity: isStm32(selectedDevice) ? 'even' : 'none',\n"
        "        flowControl: 'none',\n"
        "      });",
    )

    changed |= replace_once(
        path,
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
        "      // DevBoard Tests: the Blue Pill talks to its ROM bootloader over the\n"
        "      // port that is already open, so it never touches esptool or the ESP\n"
        "      // reset dance below. What the bootloader did -- including reading every\n"
        "      // byte back -- is said in the status line rather than assumed.\n"
        "      if (isStm32(selectedDevice)) {\n"
        "        await flashBluePillFlow();\n"
        "        setStatus(\n"
        "          'Flash complete and verified. Set the BOOT0 jumper back to 0, press Reset, ' +\n"
        "            'and the LED should blink.',\n"
        "        );\n"
        "        return;\n"
        "      }",
    )

    # Wrapping patch: the original Button survives inside the else branch,
    # which is how replace_once knows it already ran.
    changed |= replace_once(
        path,
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
    changed |= replace_once(
        path,
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

    # Prep steps above the Connect button, plus the manual route underneath.
    changed |= replace_once(
        path,
        '            <div className="w-full max-w-sm space-y-4">',
        '            <DevBoardPanel device={selectedDevice} download={firmware.path} />\n'
        '            <div className="w-full max-w-sm space-y-4">',
    )

    # The miners' next step (join its WiFi AP) is a lie for a board whose
    # whole job is blinking an LED.
    changed |= replace_once(
        path,
        "  const nextStep = !finished\n"
        "    ? null\n"
        "    : heroSource?.category === 'tools'\n"
        "      ? 'Unplug it and plug it back in. To check the chip really holds this build, run the verify command from the project README.'\n"
        "      : 'Unplug it and plug it back in. It will come up as its own WiFi access point: join that to set your pool and wallet.';",
        "  const nextStep = !finished\n"
        "    ? null\n"
        "    : heroSource?.category === 'devboards'\n"
        "      ? heroSource?.mcu === 'stm32'\n"
        "        ? 'Flash complete. Set the BOOT0 jumper back to 0, press Reset, and the LED should blink.'\n"
        "        : 'Flash complete. Unplug the board and plug it back in -- the LED should blink.'\n"
        "      : heroSource?.category === 'tools'\n"
        "        ? 'Unplug it and plug it back in. To check the chip really holds this build, run the verify command from the project README.'\n"
        "        : 'Unplug it and plug it back in. It will come up as its own WiFi access point: join that to set your pool and wallet.';",
    )

    note(changed, "LandingHero.tsx: Continue To Flash, STM32 path, instructions")


def sweep_urls() -> None:
    """The net: any Bitronics URL anywhere becomes ours.

    The targeted patches know the files upstream ships today. This covers
    tomorrow's -- a link added in a file we have never seen still must not
    reach the deploy. Matched on the domain rather than on surrounding code,
    so upstream restructuring a component cannot slip one past it.
    """
    hits = []
    for path in sorted((ROOT / "src").rglob("*")):
        if not path.is_file() or path.suffix not in {".ts", ".tsx", ".css", ".json"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if not BITRONICS_URL.search(text):
            continue
        path.write_text(BITRONICS_URL.sub(SITE, text))
        hits.append(str(path.relative_to(ROOT)))
    note(bool(hits), "sweep: any other bitronics.store URL -> BitzyLabs")
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
    if f"--color-bitronics: {CRIMSON};" not in css:
        problems.append(f"globals.css: --color-bitronics is not {CRIMSON}")

    # Several patches above are patterns that go quiet when the text is gone.
    # This is where "gone" is told apart from "missed": the end state, not the
    # journey, is what the site is judged on.
    reader_facing = {
        "src/app/layout.tsx": ROOT / "src" / "app" / "layout.tsx",
        "src/components/Header.tsx": ROOT / "src" / "components" / "Header.tsx",
        "src/components/Footer.tsx": ROOT / "src" / "components" / "Footer.tsx",
        "src/components/ShopStrip.tsx": ROOT / "src" / "components" / "ShopStrip.tsx",
        "src/lib/devices.ts": ROOT / "src" / "lib" / "devices.ts",
    }
    for label, source in reader_facing.items():
        if source.exists() and "Bitronics" in source.read_text():
            problems.append(f"{label}: still names Bitronics to the reader")

    for source in sorted((ROOT / "src").rglob("*")):
        if source.is_file() and source.suffix in {".ts", ".tsx"}:
            if "bitronics-logo" in source.read_text():
                problems.append(
                    f"{source.relative_to(ROOT)}: still references the Bitronics wordmark"
                )

    footer = ROOT / "src" / "components" / "Footer.tsx"
    if footer.exists() and "FIRMWARE_LINKS" in footer.read_text():
        problems.append("Footer.tsx: the firmware links column is still present")

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
    for section in ("Features", "Releases"):
        if f"<{section} />" in page:
            problems.append(f"page.tsx: the {section} section is still rendered")

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

    catalog = (ROOT / "src" / "lib" / "devices.ts").read_text()
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

    hero = (ROOT / "src" / "components" / "LandingHero.tsx").read_text()
    for needle in (
        "Continue To Flash",
        "flashBluePillFlow",
        "flashBluePill({",
        "DevBoardPanel",
        "parity: isStm32",
        "=== 'devboards'",
        "value={selectedFirmware}",
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

    print("\nValidation passed: no Bitronics branding survives, and the DevBoard Tests section is complete.")


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
            patch_footer()
            patch_shop_strip()
            patch_page()
            patch_layout()
            patch_palette()
            patch_selector()
            patch_device_shops()
            # Branding first, features second: both touch devices.ts, and the
            # branding's URL sweep must still be the last write.
            patch_devboards()
            # Last write, so every targeted patch gets first refusal on the
            # anchors it knows and the sweep only sees what they left.
            sweep_urls()
        validate()
    except PatchError as error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
