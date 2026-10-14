#!/usr/bin/env python3
"""Re-apply the BitzyLabs branding on top of the upstream Bitronics flasher.

The repository tracks BitMaker-hub/bitronics-web-flasher so that syncing is a
hard reset and never a merge. Every trace of the fork's own branding therefore
disappears on each sync, and this script puts it back.

It is designed to be run twice:

  * after every upstream sync, so `main` is always a complete, runnable,
    branded tree; and
  * as the first step of every deploy build, so a deploy can never ship
    Bitronics branding even if somebody pushes an unpatched commit straight
    to main (the firmware bot does exactly that, daily).

Two kinds of edit, deliberately held to different standards:

  * Structure -- the logo, the sections, the palette -- is anchored on the
    exact upstream text. If the anchor is gone the script stops and names it,
    because a half-applied rebrand that builds cleanly is far worse than a
    failed build.
  * Anything upstream rewrites constantly -- device lists, buy links, prose --
    is matched as a pattern instead. Upstream adds a board to devices.ts
    every few weeks; that must never be able to break a deploy. Patterns that
    no longer match mean there is nothing to do, not that the script is stale.

What ties them together is validation: it runs last and asserts the *end
state* (no Bitronics URL, no Bitronics title, our logo, our palette, the
sections gone). A patch that quietly finds nothing to do can only get past it
if the result is genuinely correct, so failing to match an anchor cannot
leak Bitronics branding into a build.

Idempotent: running it on an already-patched tree is a no-op.

    python3 scripts/apply-bitzylabs-branding.py          # patch
    python3 scripts/apply-bitzylabs-branding.py --check  # verify only

Exit codes: 0 clean / patched, 1 anchor missing or validation failed.
"""

from __future__ import annotations

import argparse
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
    if new in text and old not in text:
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

    if problems:
        raise PatchError("branding validation failed:\n  - " + "\n  - ".join(problems))

    print("\nValidation passed: no Bitronics branding survives.")


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
