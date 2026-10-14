#!/usr/bin/env bash
# Rebuild the DevBoard Tests firmware from source and publish it here.
#
# The two BitzyLabs SmoothBlinky repositories publish no release artifacts,
# so the binaries this site serves are built from their PlatformIO projects
# and committed. Run this after pushing a firmware change, then commit the
# result -- the patcher's validation checks that every manifest hash still
# matches the binary beside it, so a half-updated tree fails the deploy
# rather than shipping a file the flasher will refuse.
#
#   scripts/build-devboard-firmware.sh            # both devices
#   ESP_REPO=/path/to/repo scripts/build-devboard-firmware.sh   # overrides
#
# Needs: pio (PlatformIO), python3 with esptool (the PlatformIO-bundled one
# is used when no system esptool is installed).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIO="${PIO:-$HOME/.platformio/penv/bin/pio}"
ESPTOOL_PY="${ESPTOOL_PY:-$HOME/.platformio/packages/tool-esptoolpy/esptool.py}"

ESP_REPO="${ESP_REPO:-$HOME/Documents/GitHub/ESP32S3_N16R8_SmoothBlinky}"
STM_REPO="${STM_REPO:-$HOME/Documents/GitHub/STM32_BluePill_Blinky}"

ESP_VERSION="ESP 32 SmoothBlinkey v1.00"
ESP_BOARD="ESP32S3-N16R8"
STM_VERSION="STM 32 Smooth Blinkey v1.00"
STM_BOARD="STM32F103C8-BluePill"

build_esp32() {
  echo "==> ESP32-S3: building in $ESP_REPO"
  (cd "$ESP_REPO" && "$PIO" run -e esp32s3dev)

  # Upstream's flasher writes one merged factory image at offset 0x0, so the
  # bootloader (0x0), the partition table (0x8000) and the app (0x10000) have
  # to travel as a single file. S3 bootloaders sit at 0x0, unlike the ESP32.
  local out="$ROOT/public/firmware/esp32s3-smoothblinky/$ESP_VERSION"
  mkdir -p "$out"
  python3 "$ESPTOOL_PY" --chip esp32s3 merge_bin \
    -o "$out/${ESP_BOARD}_factory.bin" \
    --flash_mode keep --flash_freq keep --flash_size keep \
    0x0 "$ESP_REPO/.pio/build/esp32s3dev/bootloader.bin" \
    0x8000 "$ESP_REPO/.pio/build/esp32s3dev/partitions.bin" \
    0x10000 "$ESP_REPO/.pio/build/esp32s3dev/firmware.bin"
}

build_stm32() {
  echo "==> STM32 Blue Pill: building in $STM_REPO"
  (cd "$STM_REPO" && "$PIO" run)

  local out="$ROOT/public/firmware/stm32-bluepill/$STM_VERSION"
  mkdir -p "$out"
  # Already linked for 0x08000000 (the linker script says so); the ROM
  # bootloader is flashed at exactly that address.
  cp "$STM_REPO/.pio/build/bluepill_f103c8_under_reset/firmware.bin" \
    "$out/${STM_BOARD}_factory.bin"
}

write_manifests() {
  python3 - "$ROOT" "$ESP_VERSION" "$ESP_BOARD" "$STM_VERSION" "$STM_BOARD" <<'PY'
import datetime
import hashlib
import json
import sys
from pathlib import Path

root, esp_version, esp_board, stm_version, stm_board = sys.argv[1:6]
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

jobs = (
    (
        "esp32s3-smoothblinky",
        "ESP32-S3 N16R8 SmoothBlinky",
        "BitzyLabs/ESP32S3_N16R8_SmoothBlinky",
        esp_version,
        esp_board,
    ),
    (
        "stm32-bluepill",
        "STM32 Blue Pill SmoothBlinky",
        "BitzyLabs/STM32_BluePill_Blinky",
        stm_version,
        stm_board,
    ),
)

for slug, name, repository, version, board in jobs:
    folder = Path(root) / "public" / "firmware" / slug
    blob = folder / version / f"{board}_factory.bin"
    if not blob.is_file():
        sys.exit(f"{blob} is missing -- run the build steps first")

    digest = hashlib.sha256(blob.read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "name": name,
                "repository": repository,
                "versions": [version],
                "devices": [board],
                "lastUpdated": now,
            },
            indent=2,
        )
        + "\n"
    )
    (folder / version / "manifest.json").write_text(
        json.dumps(
            {"version": version, "boards": [board], "sha256": {board: digest}},
            indent=2,
        )
        + "\n"
    )
    print(f"   {slug}: {blob.name} ({blob.stat().st_size} bytes) sha256={digest}")
PY
}

build_esp32
build_stm32
write_manifests

# The middle column and the device picker art are the same illustration.
cp "$ROOT/public/pictures/esp32-n16r8.png" "$ROOT/public/pictures/boards/${ESP_BOARD}.png"
cp "$ROOT/public/pictures/stm32-bluepill.png" "$ROOT/public/pictures/boards/${STM_BOARD}.png"

echo "==> Done. Now: python3 scripts/apply-bitzylabs-branding.py --check && git add public/firmware public/pictures"
