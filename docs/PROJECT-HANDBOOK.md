# BitzyLabs Flasher — Project Handbook

**This document exists so you can take over this project cold.** You do not need
any backstory, Slack history, or conversation with the previous maintainer. If
something here is wrong, outdated, or missing, fix this document in the same
commit that fixes the thing — it is versioned in the repo for exactly that
reason. (It is also Notion-import friendly: in Notion use **Import → Markdown**
and pick this file.)

Last written: October 2026, against commit `34ade44`.

---

## 1. What this project is

A **web-based firmware flasher** for Bitzy Labs' dev boards. A visitor plugs a
board into their PC, picks their model in the browser, clicks **Connect**,
picks a firmware version, and clicks **Start Flashing** — no toolchains, no
`esptool.py`, no drivers beyond what the browser needs. It also has a serial
monitor (start logging, download logs) for the boards that speak serial.

It is a **static single-page Next.js app** (no backend, no database, no API).
Everything — the flashing protocols, the device catalog, the firmware
manifests — ships in the JS bundle and `public/`.

- **Live site:** https://flasher.bitzylabs.com (GitHub Pages)
- **This repo:** https://github.com/BitzyLabs/nmv2-web-flasher
- **Upstream:** https://github.com/BitMaker-hub/bitronics-web-flasher
  (git remote is literally named `upstream`; we are a rebranded fork — see §4)
- **Owner / product:** Bitzy Labs (store: https://www.bitzylabs.com)

### What a user does on the page

1. Picks a device (dialog with board tiles) — the picker is scoped to the
   devices Bitzy ships: **ESP 32 N16R8** (ESP32-S3 bench test), **STM 32
   BluePill** (STM32F103 bench test), and **NerdMiner** (under *Miners*).
2. For single-board devices the middle step is one **Continue To Flash**
   button (it picks board + first firmware version in one press). For
   multi-board devices it is a board dialog.
3. Picks a firmware version from a Radix select (populated from
   `src/components/firmware_data.json`).
4. **Connect** opens the browser's device picker:
   - **ESP32/NerdMiner:** Web Serial (`esptool-js` + `web-serial-polyfill`).
   - **STM32 BluePill: WebUSB only, talking to an ST-Link V2 over WebUSB.**
     There is **no serial path for STM32** — this is a deliberate product
     decision, hardware-verified end to end. Do not "add serial for STM32".
5. **Start Flashing**, then optionally **Start Logging** (xterm serial
   monitor) and **Download Logs**.

Phones/tablets can't flash (desktop-browser APIs), so below 768 px a
full-screen poster gate explains that and links the store — see §8.

---

## 2. Facts at a glance

| Thing | Value |
|---|---|
| Stack | Next.js (App Router) + React 18 + TypeScript, **static export** (`output: 'export'` in `next.config.js`) |
| Styling | Tailwind CSS **v4** (`@import 'tailwindcss'` + `@custom-variant dark` in `src/app/globals.css`), shadcn-style tokens, hand-written CSS blocks in `globals.css` |
| Theming | `next-themes`, class-based, Light/Dark/Auto, **default light**, persists in `localStorage["bitzy-theme"]` |
| Fonts | Doto (dot matrix) = `font-data`/`.font-doto`; Plus Jakarta Sans (`font-display`); Inter (body). Doto file served from repo (`public/fonts/Doto.woff2`) |
| Brand colors | Crimson `#DC143C`, ink `#222222`, ground `#F7F6F3`, hairline `#E7E4DE`, muted `#6D6A64` (+ dark-half values, §7) |
| Deploy | GitHub Pages via `.github/workflows/nextjs.yml`, **auto-deploys on every push to `main`** (also after the firmware bot, also manual) |
| Firmware bot | `.github/workflows/update-firmware.yml`, daily 02:00 UTC |
| Upstream sync | `.github/workflows/sync-upstream.yml`, daily 03:30 UTC (deliberately after the firmware bot so they don't collide) |
| Local dev | `npm run dev`; production check = `npx next build` → static files in `out/` |
| Local preview of `out/` | `python3 -m http.server 8931 --directory out` |
| The patcher | `scripts/apply-bitzylabs-branding.py` (~4800 lines) — see §5, **read this before touching anything** |
| Sync harness | `scripts/upstream-mirror-test.sh` (16 assertions, gates CI sync) |
| gh CLI | always `gh … -R BitzyLabs/nmv2-web-flasher` |
| Do **not** | run `npx prettier` (no Prettier config exists; house style is hand-kept single quotes) |

---

## 3. Architecture

### 3.1 The page

One route (`/`). `src/app/layout.tsx` wraps everything in
`I18nProvider` → `ClientThemeWrapper` (next-themes `ThemeProvider` + the
mobile gate). `src/app/page.tsx` renders `LandingHero` (≈1600 lines — the
orchestrator: picker state, connection lifecycle, flashing, serial monitor,
the three-step controls, the terminal) plus `Features` and `Footer`.

`src/app/globals.css` is the design system: Tailwind v4 `@theme` tokens,
the `:root`/`.dark` scheme pair, the header rule, the canvas (tiled logo +
crimson radials), motion, and the Radix-select `!important` pins.

### 3.2 Key files

| File | Role | Ownership |
|---|---|---|
| `src/components/LandingHero.tsx` | The whole flasher page + flow | upstream-owned (chains) |
| `src/components/Header.tsx` | Bar: logo, nav, theme pill, hamburger | upstream-owned (chains) |
| `src/components/BoardPicker.tsx`, `DeviceModal.tsx` | Device/board dialogs (hand-rolled, not Radix) | upstream-owned |
| `src/components/Selector.tsx` | The firmware Radix select | upstream-owned |
| `src/components/{Features,Footer,ShopStrip,InstructionPanel,DeviceIntro}.tsx` | Page furniture | upstream-owned |
| `src/components/ClientThemeWrapper.tsx` | next-themes provider + renders `MobileGate` | **fork-owned** (edit directly) |
| `src/components/bitzy/ThemeSwitch.tsx` | Light/Dark/Auto pill | **fork-owned** |
| `src/components/bitzy/MobileGate.tsx` | Phone gate poster | **fork-owned** |
| `src/components/bitzy/DevBoardPanel.tsx` | Blue Pill wiring line (generated from `PANEL_SOURCE` in the patcher) | patcher-generated |
| `src/lib/devices.ts`, `src/lib/boards.ts` | Device/board catalog + shop links | upstream-owned |
| `src/lib/bitzy/devboards.ts`, `src/lib/bitzy/stlink.ts` | DevBoard data; **ST-Link-over-WebUSB driver** | **fork-owned** |
| `src/components/firmware_data.json` | Firmware tiles manifest (the daily bot rewrites it) | bot-owned |
| `public/firmware/{esp32s3-smoothblinky,nerdminer,stm32-bluepill}/` | The actual `.bin`s | bot-owned |
| `src/components/Releases.tsx` | **Dead code** — removed from the page, kept in tree | ignore |

### 3.3 The two flashing paths

**ESP32 (and NerdMiner, which is ESP32-based):** `esptool-js` over Web Serial.
Standard connect → sync → flash → reset. The serial monitor shares the same
serial port; the monitor is cancelled cleanly for flashing and can be
restarted after (a bug where flashing killed the monitor permanently was
fixed in `d1e0f57` — do not regress it).

**STM32 BluePill (ST-Link V2 over WebUSB):** implemented in
`src/lib/bitzy/stlink.ts` + the flow code in `LandingHero.tsx`. Design facts
you must know before touching it (all hardware-verified; see §17):

- WebUSB only — no Web Serial anywhere on this path.
- Flashing runs a **140-byte Thumb flash loader in RAM at `0x20000000`**,
  with a **mailbox at `0x20000400`** and a **page buffer at `0x20000800`**.
  The loader is written over SWD, then the core runs it; commands/addresses
  go through the mailbox. This replaced an earlier, broken word-by-word
  approach (commit `9b47dc0`).
- F1 debug-unlock: `CR_LOCK` is bit **7** (bits 0–6 first, then 7, per
  RM0008). Getting this bit wrong was one of the root causes of dead STM32
  flashing.
- Owner's hardware verdict, after which nothing on this path has changed:
  **"Everything works perfectly!!"** Treat the STM32 path as frozen unless
  there's a bug report; verify on hardware before and after any change.

---

## 4. The fork model — the one concept you must internalize

This repo is a **rebranded fork**. Upstream (`BitMaker-hub/bitronics-web-flasher`)
ships a dark "Bitronics" UI; we ship a light, warm, Bitzy-branded one. Upstream
keeps developing (daily syncs), so **every file that upstream also owns will be
overwritten on the next sync.**

That gives every file exactly one of two fates:

### A. Upstream-owned files — never hand-edit for branding

`Header.tsx`, `globals.css`, `LandingHero.tsx`, the components, `devices.ts`,
`layout.tsx`, `page.tsx`, workflows you didn't create… If you open one of these
and change branding text/colors/classes directly, **your change dies at the
next nightly sync** (or worse, causes a merge conflict that resolves against
you). All such changes must be expressed as **chains** in
`scripts/apply-bitzylabs-branding.py`, which re-applies them after every sync.

### B. Fork-owned files — edit directly, they survive merges

- Everything under **`src/components/bitzy/`** (`ThemeSwitch.tsx`,
  `MobileGate.tsx`, …)
- **`src/lib/bitzy/`** (`stlink.ts`, `devboards.ts`)
- **`src/components/ClientThemeWrapper.tsx`** (upstream never had it; layout's
  import of it is chain-protected, the file itself is ours)
- **`scripts/`** and **`.github/workflows/`** files listed in the sync
  script's KEEP list (§9)
- **`.bitzylabs-overlay/`** (asset source of truth: logos, Doto font — the
  patcher copies these into `public/`)

The rule of thumb: **if upstream's tree contains a version of the file, it is
theirs and you go through the patcher. If it doesn't, it's ours — own it.**

---

## 5. The branding patcher — full manual

`scripts/apply-bitzylabs-branding.py` is the single source of truth for
branding. It takes a freshly-synced tree and lays the Bitzy skin back on top,
idempotently, and **fails loudly** when upstream moved the text it anchors on.

### 5.1 The ritual (run this after any change to it)

```bash
python3 scripts/apply-bitzylabs-branding.py          # run 1: applies
python3 scripts/apply-bitzylabs-branding.py          # run 2: must be all "(already applied)"
python3 scripts/apply-bitzylabs-branding.py --check  # validate only, never writes
npx next build                                       # the tree must still build
```

Then commit **the script and the tree it produced together**, in one commit.
Never commit one without the other — the audit judges chains against the tree
they just ran on, and CI runs `--check`.

### 5.2 What runs, in order

`main()` calls ~28 `patch_*` functions in a deliberate order. **Order is
load-bearing.** The ones that matter:

- `patch_palette` → `patch_theme_schemes` → `patch_chrome`: the palette's
  `.dark` block must be dressed before the schemes trade it, and
  `@theme`/`:root` values must exist before anything reads them.
- `patch_picker_panels`, `patch_hero_light`, … → **`patch_theme_ui`** →
  **`patch_mobile_menu`**: the later passes trade the `bg-white` surfaces the
  earlier passes land, and the hamburger consumes the pill + mobile
  Instructions button that earlier passes land.
- `validate()` runs at the end of every invocation (including `--check`), and
  `_chain_audit_problems()` runs inside it.

### 5.3 The chain helpers — exact semantics

Every branding change is a "chain": `old` (text upstream ships or a previous
chain landed) → `new` (what should ship).

| Helper | Behavior |
|---|---|
| `replace_once(path, old, new, required=True)` | Replaces exactly one occurrence. **Raises** if `old` is missing (that's the signal upstream moved — go update the chain) or if it matches more than once. Quiet if the replacement is already applied (`new in text`, or a wrapper whose anchor only survives inside `new`). |
| `replace_if_present(path, old, new)` | Same, but **quiet** when `old` is absent. Use for migrations (the text may or may not be there) and for `new`s that a later chain will rewrite. |
| `replace_everywhere(path, old, new)` | All occurrences, quiet when none. For strings that are plural by design (e.g. `bg-white` across a file). |
| `inject_once(path, marker, old, new)` | Writes `new` for `old` **unless `marker` is already present**. ⚠️ **The marker is a *done*-marker: text that exists ONLY AFTER the injection** (a line only your chain writes). A pre-existing line is always "present", so the chain would never fire. This exact mistake has shipped once; don't repeat it. |
| `inject_rows(path, decl, block, marker)` | Inserts rows after a declaration, marker-gated the same way (marker = a row only we write). Used for the device/board lists. |
| `drop_lines(path, predicate)` | Deletes matching lines (dead imports etc.). |

### 5.4 Chain design rules (learned the hard way)

1. **One owner for each anchor.** Two chains must never anchor on the same
   text. Key every marker/anchor on **what your chain leaves behind**, not on
   what it finds — otherwise the first chain to rewrite that text breaks the
   second one silently or loudly.
2. **Migration chains.** When you change what the patcher *produces* (e.g. the
   header rule goes from a literal color to `var(--color-bar)`), keep the old
   produced form as a `replace_if_present` chain so trees already wearing it
   trade forward. Pattern: upstream-form → new (required), old-fork-form →
   new (quiet migration).
3. **The audit only fails when `old in body and new not in body`.** Chains
   whose arguments are non-literal names (module constants like `HERO_CSS`,
   `DARK_BLOCK_LIGHT`) are silently skipped by the audit — the constants are
   resolved at runtime, and the audit is AST-based. This is why validate()
   exists as the second net.
4. **Path resolution in the audit is AST-based.** For the audit to see a
   chain, the target path must be resolvable: `path = ROOT / "src" / …` in the
   same function, or an **inline tuple** in the `for`:
   `for path in (ROOT / "a.tsx", ROOT / "b.tsx"):`. A named tuple variable
   (`panels = (…); for path in panels:`) is **invisible** to the audit and
   fails with *"target path could not be resolved"*. Inline your tuples.
5. **Audit-compat between palette and schemes.** `patch_palette`'s `.dark`
   value-loop has required `replace_once`s whose `new` is the store-light
   values. After `patch_theme_schemes` trades `.dark` to the dark scheme,
   those `new` strings must still exist **somewhere** in the file (they live
   on in `:root`) or the audit flags the palette chain. If you ever rework
   `:root`, keep the light values byte-identical.

### 5.5 validate() — the end-state judge

`validate()` (same file, ~740 lines) is a long list of needles that must
exist in the tree and "gone" strings that must not. It is what catches what
the audit structurally cannot (constants, orderings, cross-file invariants).
Notable groups:

- zero old-brand traces (`bitronics`, `-bitronics`, old URLs, PNG XMP);
- the store's scheme tokens (`--color-bitzy: #DC143C`, warm ground, etc.);
- **`:root` carries the store's light scheme, `.dark` carries the warm dark
  scheme with brand tokens flipped** — both judged block-by-block by regex;
- the header bar reads `var(--color-bar)`, the canvas/gradient read tokens,
  the select pins read `var(--color-panel)` / `var(--color-hairline-light)`;
- **no `bg-white` remains** in the eight themed files (it's the one spelling
  no variable can flip) — components must use
  `bg-[var(--color-panel)]`;
- **no `dark:` utilities in `LandingHero.tsx`** (the band follows tokens; a
  `dark:` utility would double-encode the theme);
- the terminal keeps `h-[400px] bg-black` (the terminal is black in **both**
  themes, always);
- ThemeSwitch/MobileGate behavior needles (fork-owned files are judged here
  because no chain protects them — nothing replaces an absent file);
- Header needles: switcher imported + rendered, dual-logo swap
  (`dark:hidden`/`dark:block`), hamburger state/icons/panel.

**When validate fails, read the message — it names the file and the reason.**
Fix the tree (or the chain that should have produced it), don't delete the
needle.

### 5.6 The chain audit

`_chain_audit_problems()` re-reads the script with `ast` after every run and
judges each chain's fingerprint against the tree: if a chain's `old` is still
in the file it targets but its `new` isn't, the chain didn't do its job —
that's a finding. `AUDIT_EXEMPT` exists (currently empty) for genuinely
unauditable chains; don't grow it casually.

---

## 6. Branding system of record

These decisions are final unless the owner says otherwise. Restoring any of
them is what `validate()` is built to enforce.

- **Name/spelling:** "Bitzy Labs" (with a space) in prose; `BitzyLabs` in
  URLs/org names; never "Bitronics", never `bitronics.store`, never
  `-bitronics` tokens.
- **Crimson:** `#DC143C` exactly (a rounded `348 83% 47%` HSL drift is
  specifically forbidden — it's a different red). The gradient's dark end
  `#B01030`. An older first crimson `#DB092A` must not reappear.
- **Logos:** `public/pictures/bitzylabs-logo-light.png` = crimson mark + **ink**
  wordmark (for light bars); `public/pictures/bitzylabs-logo-dark.png` =
  crimson mark + **white** wordmark (for dark bars). Both ship; the header
  swaps them with `dark:hidden` / `dark:block`. Source of truth:
  `.bitzylabs-overlay/assets/`.
- **The shop link** is `https://www.bitzylabs.com` (header nav, shop strip,
  footer, device intros, mobile gate).
- **Copy voice:** the site talks like a competent shopkeeper — plain,
  confident, a little funny ("Your phone is a lovely camera and a terrible
  flasher"). Dot-matrix (Doto) is used for flourish words, kickers, and the
  gate — not for body text or dense controls.
- **Sweep:** `sweep_marks()` rewrites stray old-brand words in
  `src/`, `.github/`, `readme.md`, `FIRMWARE_AUTOMATION.md` (NOT `scripts/`
  — the script legitimately contains forbidden strings as chain arguments).
  The FORBIDDEN scan must stay clean.

---

## 7. Theme system (Light / Dark / Auto)

**Decisions of record:** default **light**; the reader's choice **persists**
(`localStorage["bitzy-theme"]`); Auto follows `prefers-color-scheme` live.

- **Mechanism:** `next-themes` with `attribute="class" defaultTheme="light"
  enableSystem storageKey="bitzy-theme" disableTransitionOnChange`, in the
  fork-owned `ClientThemeWrapper.tsx`. It adds `class="light"` or
  `class="dark"` to `<html>` and sets `colorScheme` natively.
- **Tokens** (in `@theme`, i.e. the light defaults; overridden inside
  `.dark` which lives in `@layer base` and therefore wins):

  | Token | Light | Dark |
  |---|---|---|
  | `--color-band-light` (the canvas/hero ground) | `#F7F6F3` | `#1C1A16` |
  | `--color-panel` (cards, modals, drawer, footer, menu) | `#FFFFFF` | `#24211C` |
  | `--color-bar` (the fixed header) | `rgba(255,255,255,0.85)` | `rgba(36,33,28,0.85)` |
  | `--color-hero-lift` (gradient top) | `#FFFFFF` | `#2B2823` |
  | `--color-ink` | `#222222` | `#F1EEE7` |
  | `--color-muted-warm` | `#6D6A64` | `#A6A093` |
  | `--color-hairline-light` | `#E7E4DE` | `#3A362E` |
  | crimson `--color-bitzy` / `--primary` / `--ring` | `#DC143C` / `348 83.33% 47.06%` (same in dark) | |

- **`:root` is byte-identical to the light scheme the old forced-dark build
  rendered** — the light page did not move a pixel when themes shipped.
  Don't "clean up" those values.
- **Ink is text-only.** Nothing uses `bg-[var(--color-ink)]`; ink flips to
  near-white in dark, so never use it as a surface.
- **The terminal is always `bg-black`** (a fixed token, never a var) — in
  both themes. Deliberate, owner-loved, validate-pinned.
- **Adding a themed surface:** never write `bg-white` (or a hardcoded light
  color) in a component — use `bg-[var(--color-panel)]` (or band/ink/muted
  vars). If you add a *new* token, add it to `@theme`, override it in
  `.dark`, and extend both validate needle groups + the
  `patch_theme_schemes` trade (§5).

---

## 8. Mobile behavior (gate + hamburger)

Two features share one breakpoint: **768 px** (`md`).

- **`MobileGate`** (fork-owned, rendered under `ClientThemeWrapper`): below
  768 px a full-screen poster — the store's dark ground with crimson
  radials, Doto type: **"THIS FLASHER NEEDS A PC_"** (blinking crimson
  cursor), the funny sub-copy, and a linked **"IN THE MEANTIME → VISIT OUR
  STORE"** CTA. The quiet escape **"or browse anyway"** sets
  `sessionStorage["bitzy-gate-dismissed"]` — dismissed for that tab, a fresh
  tab gets the poster again. Body scroll is locked while it shows. The poster
  uses **fixed colors on purpose** (it's an art layer, same in both themes).
- **Hamburger** (`patch_mobile_menu` chain, upstream-owned file): below
  `md`, the bar is logo + hamburger; the menu panel (hanging off the bar,
  `bg-[var(--color-panel)]`) contains Shop, Instructions, and a centered
  ThemeSwitch. Above `md`, the original centered nav + pill show and the
  hamburger hides (`hidden md:block` wraps the bar's pill).

If you move the breakpoint, move it in **three** places: `MobileGate`'s
`matchMedia`, the hamburger/menu `md:` utilities, and validate's needles.

---

## 9. Syncing upstream

### 9.1 Automated

`sync-upstream.yml` runs daily ~03:30 UTC (after the firmware bot):

1. **Harness gate:** `scripts/upstream-mirror-test.sh` proves the mechanism
   on a *simulated* upstream (churn night, quiet night, two drift-must-fail
   cases) — 16 assertions. If it fails, nothing is pushed; fix the harness or
   the script before touching the sync.
2. `scripts/sync-upstream.sh`: fetch `upstream/main`; if it's already an
   ancestor → `--check` and exit (quiet night, no empty merge commit);
   refuse a dirty tree; **merge with upstream winning same-line conflicts**
   (`-X theirs` on upstream files); restore the **KEEP list** from the
   pre-sync commit; run the patcher; validate + audit; build; push a
   fast-forward **merge commit** (never hard-reset `main` — it would rewrite
   history and be rejected).

**KEEP list** (our tooling, restored after every merge):
`.bitzylabs-overlay/`, `scripts/apply-bitzylabs-branding.py`,
`scripts/sync-upstream.sh`, `scripts/upstream-mirror-test.sh`,
`.github/workflows/{nextjs,update-firmware,sync-upstream}.yml`, and —
since the Oct 2026 dependency pins — `package.json` **and**
`package-lock.json` as a pair (our versions win, and npm ci can never
meet a lock that disagrees with its manifest; `patch_dependency_pins`
plus two validate needles are the second net, §17.9).

### 9.2 When a sync breaks a chain (expect this eventually)

The patcher **raises** (`anchor not found — upstream changed this file`) or
validate fails. That's by design: upstream moved the text. Playbook:

1. `gh run view <run> -R BitzyLabs/nmv2-web-flasher` (or read the local
   error) → which file, which anchor.
2. Look at upstream's new shape: `git log -p upstream/main -- <file>` or the
   merge commit.
3. Update the chain's `old` to the new upstream text (and, if the *product
   shape* changed, re-derive `new`). Keep a migration chain if trees may
   already wear either form.
4. Run the ritual (§5.1), extend validate needles if the end state changed,
   commit script+tree together.

### 9.3 Doing a manual sync

```bash
git status --porcelain    # must be clean
bash scripts/sync-upstream.sh
```

---

## 10. Firmware automation

- `update-firmware.yml` (daily 02:00 UTC) pulls releases **straight from
  the external firmware projects** — the source repos configured in
  `scripts/update-firmware.js` (e.g. `NerdMiner_v2`,
  `shufps/ESP-Miner-NerdQAxePlus`) — **never from upstream's code repo**.
  It downloads the matching `.bin`s into `public/firmware/<device>/`,
  rewrites `src/components/firmware_data.json` (tiles: version, size, hash,
  "Latest"), and commits with `GITHUB_TOKEN`; the commit step stages only
  the firmware this picker still serves. The bench-test firmwares
  (`esp32s3-smoothblinky`, `stm32-bluepill`) are **not** bot-managed — they
  are static files committed by us.
- **Firmware and the code sync (§9) are fully independent paths.** You can
  keep, pause, or retire either without affecting the other. (Decision of
  record, Oct 2026: keep both — see §17.8.)
- **Trap (already bitten once):** pushes made with the repo `GITHUB_TOKEN`
  do **not** trigger other workflows. `nextjs.yml` therefore also triggers
  on `workflow_run` of *Update Firmware Releases* — without it the live
  site sat on eight-month-old firmware while the bot reported success daily.
  If you add bot-driven commits, remember this.
- Details of the bot's data shape: see `FIRMWARE_AUTOMATION.md` in the repo
  root (it is sweep-scanned; keep it brand-clean).

---

## 11. Operations

- **Deploy:** push to `main` → `nextjs.yml` builds and publishes GitHub
  Pages. No manual step. (Also triggers: firmware-bot completion, manual
  dispatch.)
- **Verify a deploy:** wait for the Actions run, then confirm the live HTML
  references new chunk hashes, e.g.
  `curl -s https://flasher.bitzylabs.com/ | grep -o '_next/static/chunks/[^"]*'`
  and grep a chunk for a string your change introduced
  (`"Ready To Flash"`, `"THIS FLASHER"`, `"bitzy-theme"`…).
- **Roll back:** `git revert <sha> && git push` (Pages republishes). Never
  force-push `main`.
- **Local end-to-end check:**
  `npx next build && python3 -m http.server 8931 --directory out` →
  http://localhost:8931 — plus a device on hardware if you touched flashing.
- **Browser testing:** Playwright/`playwright-cli` works against the local
  bench. Two quirks: hand-rolled dialogs are `position: fixed`, so
  `offsetParent` is always null — test visibility via the `opacity-0` class
  or `checkVisibility()`; and the picker dialogs stay mounted (fade
  animation), so "both dialogs in the DOM" is normal.

---

## 12. House rules

1. **No Prettier.** There is no config; `npx prettier --write` reflows the
   world and creates noise merges with upstream. Match surrounding style:
   **single quotes**, two-space indent, semicolons as the file has them.
2. **Tailwind scans the repo for class candidates — including the patcher
   `.py` files.** A utility spelled as a literal string anywhere (even in a
   chain argument) gets generated into the CSS bundle. This shipped a
   forbidden yellow once. When adding class-string literals to the patcher,
   ask whether that class *should* exist in the bundle.
3. **Commit voice:** full-sentence subjects in the codebase's register
   ("Give the phone a hamburger and a poster"), body explains the *why*.
4. **Script + tree together** (§5.1). CI runs `--check` and the harness.
5. **Hardware before and after** any change to `stlink.ts` / STM32 flow /
   esptool flow. Emulators lie; the owner's bench is the truth.
6. **Don't fight the terminal.** It's black in both themes by design.

---

## 13. Playbooks (common tasks)

**Change a brand color / token.**
→ Update the constants at the top of the patcher (`CRIMSON`, `STORE_*`),
the `@theme`/`:root`/`.dark` chain outputs (`patch_palette`,
`patch_theme_schemes`), and the validate needles that pin the old value.
Run the ritual. Search validate for the old hex first — it will tell you
every place it's pinned.

**Add UI to the header (desktop + mobile).**
→ It's an upstream file: add a chain in `patch_theme_ui` (or a new
`patch_*` with a `main()` call in the right order), anchored on text the
tree verifiably has (run the script once to see what earlier chains land).
Mind mobile: the bar is logo + hamburger below 768 — put mobile items in
the menu panel chain (`patch_mobile_menu`). Add validate needles.

**Change hero copy / add a component to the page.**
→ `LandingHero.tsx`/`page.tsx` are upstream-owned: chain it
(`patch_hero_light`/`patch_page`), anchor on unique existing text, add
needles. If the component itself is new, put it in `src/components/bitzy/`
and render it from a fork-owned parent or a chain-protected import.

**Add a device to the picker.**
→ Data lives in `src/lib/devices.ts` (+ `src/lib/bitzy/devboards.ts` for
DevBoard entries) and the firmware dirs + `firmware_data.json` (the bot
maintains those). The picker scope is re-asserted by `patch_picker_scope`
after every sync — if you add a device upstream doesn't have, make sure
that chain's KEEP-filter keeps it (it keys on category names; read it
before editing).

**Respond to an upstream release.**
→ Syncs are automatic; if nightly is red, §9.2. If upstream ships something
you want to keep, it arrives with the merge — build, eyeball the local
bench, done. If it fights the brand (e.g. new dark-only UI), add/extend a
chain + needles.

**The build is red after a sync and you're overwhelmed.**
→ Reproduce locally: `git pull && bash scripts/sync-upstream.sh` (or merge
`upstream/main` yourself), run the patcher, read the first `PatchError`.
Fix chains top-down; validate output is your checklist.

---

## 14. Pre-push checklist

- [ ] `python3 scripts/apply-bitzylabs-branding.py` ×2 → run 2 all
      "(already applied)"
- [ ] `python3 scripts/apply-bitzylabs-branding.py --check` → exit 0
- [ ] `npx next build` → success
- [ ] If flashing changed: **hardware test on the bench** (ESP32 + BluePill)
- [ ] If UI changed: local bench + a look at 1280 px **and** 375 px, both
      themes, and (if you touched it) a fresh tab for the gate
- [ ] Script + tree in the same commit; brand sweep clean (validate covers
      it); commit subject in full-sentence voice

---

## 15. Known sharp edges

- `inject_once` markers are **done-markers** (absent before, present after).
  Using a pre-existing line as a marker = the chain never fires, silently.
- The audit can't resolve `for path in named_tuple` — inline the tuple.
- Radix Select ships its own dark list that beats tokens; the `!important`
  pins in `globals.css` are the only thing that can move them. If you restyle
  the select, restyle the pins.
- The hand-rolled picker dialogs are always mounted (for fade); don't
  "fix" the double-dialog DOM or the empty never-opened board dialog — both
  are by design (single-board devices auto-pick the board via
  `continueToFlash`).
- `Releases.tsx` is dead but harmless; the `bg-white` trade deliberately
  excludes it (and `BoardArt`'s `bg-white/[0.02]` fallback, which sits on
  the dark art frame in both themes).
- Tablets ≥768 px get the desktop site (no gate). Deliberate-for-now; see
  §16.
- Two storage keys exist: `bitzy-theme` (localStorage, the theme) and
  `bitzy-gate-dismissed` (sessionStorage, the poster escape). Renaming
  either strands returning readers.
- The firmware bot's pushes don't trigger workflows (§10) — don't "simplify"
  the `workflow_run` trigger away.

---

## 16. Open threads / future work

- **iPad question:** portrait iPads (≥768 px) see the desktop site and no
  gate, though they can't flash. If the owner wants the gate to cover
  tablets, change the breakpoint in the three places listed in §8.
- **This handbook → Notion:** the owner wanted a Notion doc; no Notion
  integration was reachable from the tooling, so this file *is* the
  canonical document (Notion: Import → Markdown). If a Notion workspace
  connection is set up later, import this file and keep the repo copy as
  source of truth.
- Anything you learn that isn't here: write it here.

---

## 17. History / decisions of record

Condensed, so you know *why* things are the way they are:

1. **The fork began** as a rebrand of Bitronics' web flasher (crimson Bitzy
   skin over a dark upstream UI). Early state was forced-dark
   (`forcedTheme="dark"` + a light `.dark` block) — a hack that made
   `dark:` utilities fire against a light page. Replaced by the real theme
   system (§7) in `84b7490`.
2. **STM32 flashing was broken, then frozen after fix.** Root causes: the
   `CR_LOCK` bit-7 unlock and the flash approach. The shipped design is the
   140-byte RAM loader (§3.3), commit `9b47dc0`. Hardware-verified; the
   owner's verdict closed the topic.
3. **The serial monitor used to die after a flash** (it was cancelled for
   flashing and never came back). Fixed in `d1e0f57`; the monitor lifecycle
   in `LandingHero` now survives the flash that cancels it. Hardware-
   verified.
4. **Sync drift was existential.** The replica had drifted until it stopped
   building; the resync was manual and unrepeatable. The answer was the
   patcher + KEEP list + nightly workflow + simulated-upstream harness
   (`7b87839`). The harness is the reason you can trust the nightly.
5. **The firmware bot silently didn't publish for eight months** (bot pushes
   don't trigger workflows). Fixed with the `workflow_run` trigger (§10).
6. **Theme modes shipped as a fully-patched, audited, idempotent extension**
   (`84b7490`) — light default, persistence, dark palette tuned warm to sit
   beside the crimson, terminal untouched. Followed by the phone poster +
   hamburger (`34ade44`), owner-approved copy included.
7. **STM32 = WebUSB/ST-Link only** is a product decision, not an omission.
   The mobile gate exists for the same reason: the browser APIs this thing
   needs live on desktop.
8. **The code sync stays fully automatic** (reviewed Oct 2026 when the
   question "can't we just take firmware?" was raised — firmware was never
   on the sync path, §10). Upstream's real commits land green through the
   patcher (e.g. `34e24db`, a shared flash-flow fix, merged and deployed by
   the nightly), while about half their commit volume is firmware-bot noise
   the patcher prunes right back out. Retire or downgrade the sync only if
   the nightlies start going red routinely.
9. **Next.js stays on 13.5.x** (Oct 2026, Aikido scan, owner's call —
   "let's not make it a project"). The scan's axios and workflow findings
   were fixed outright; the Next advisories that remain all want 14 or 15.
   They are accepted knowingly: this is a **static export on GitHub Pages**
   — no Next server, no middleware, no SSR runtime in the deployment — and
   most of those advisories describe attacks against exactly that absent
   server. The pins are durable (KEEP pair + `patch_dependency_pins` +
   validate needles, §9.1). Revisit **only** if the deployment shape ever
   gains a server, or when upstream's own line makes 15.x a small step
   rather than a migration. Note: the SAST/IaC engines were unavailable in
   the scan environment, so `src/` has had secrets-coverage only.

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **The patcher** | `scripts/apply-bitzylabs-branding.py` — re-applies branding after syncs |
| **Chain** | One `old → new` branding rule inside the patcher |
| **Marker** | For `inject_once`: text that exists only *after* the injection (a done-marker) |
| **The harness** | `scripts/upstream-mirror-test.sh` — proves the sync mechanism on a simulated upstream |
| **KEEP list** | Files the sync restores from our side after merging upstream (§9) |
| **The band** | The hero strip (`bitzy-hero`) the flasher controls sit on |
| **The bar** | The fixed header (`header-custom`), `--color-bar` |
| **The canvas** | The page ground: tiled logo + two crimson radials, `body` rule in `globals.css` |
| **The terminal** | The xterm output pane, always `bg-black` |
| **Doto** | The dot-matrix font (`font-data`), used for flourish/kickers/gate |
| **ST-Link / SWD** | The debug probe protocol the STM32 path speaks (over WebUSB) |
| **The mailbox** | RAM word at `0x20000400` the RAM loader polls for commands (§3.3) |

---

*You now know everything the previous maintainer knew that matters. The tree
is green, the site is live, the nightly is watching. Go flash something.*
