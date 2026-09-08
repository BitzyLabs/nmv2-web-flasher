#!/usr/bin/env python3
"""Apply the BitzyLabs CYD flasher overlay idempotently.

This script is intentionally small and fail-fast. It supports both the older
BitzyLabs flasher UI (which reads firmware_data.json directly) and the newer
Bitronics UI (which also requires a DEVICE_SOURCES registry entry).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEVICE_NAME = "BitzyLabs CYD"
BOARD_FILE = "BitzyLabs-CYD"
BOARD_LABEL = "ESP32-2432S028R (2.8in CYD)"
DEVICE_PICTURE = "pictures/bitzylabs-cyd.webp"
SLUG = "bitzylabs-cyd"
VERSION = os.environ.get("BITZY_VERSION", "v0.1.0-rc1")


def patch_firmware_data() -> None:
    path = Path("src/components/firmware_data.json")
    if not path.is_file():
        raise RuntimeError(f"Missing required device registry: {path}")

    data = json.loads(path.read_text())
    devices = data.setdefault("devices", [])

    device = {
        "name": DEVICE_NAME,
        "picture": DEVICE_PICTURE,
        # This static board is used by the older UI. The newer UI replaces it
        # at runtime with boards loaded from our manifests.
        "boards": [
            {
                "name": BOARD_LABEL,
                "file": BOARD_FILE,
                "supported_firmware": [
                    {
                        "version": VERSION,
                        "path": f"firmware/{SLUG}/{VERSION}/{BOARD_FILE}_factory.bin",
                    }
                ],
            }
        ],
    }

    devices[:] = [d for d in devices if d.get("name") != DEVICE_NAME]
    devices.append(device)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Patched {path}: exactly one {DEVICE_NAME!r} entry")


def patch_new_device_sources() -> None:
    path = Path("src/lib/devices.ts")
    if not path.exists():
        print("Older flasher UI detected: src/lib/devices.ts absent; static registry is sufficient")
        return

    text = path.read_text()
    if "device: 'BitzyLabs CYD'" in text:
        print(f"{path}: BitzyLabs source already present")
        return

    marker = "export const DEVICE_SOURCES: DeviceSource[] = [\n"
    if marker not in text:
        raise RuntimeError(
            "Bitronics changed the DEVICE_SOURCES declaration; refusing to guess where to patch it"
        )

    entry = """  {
    device: 'BitzyLabs CYD',
    category: 'miners',
    tagline: 'ESP32 CYD solo miner',
    keepsConfiguration: true,
    slug: 'bitzylabs-cyd',
    label: { 'BitzyLabs-CYD': 'ESP32-2432S028R (2.8in CYD)' },
  },
"""
    text = text.replace(marker, marker + entry, 1)
    path.write_text(text)
    print(f"Patched {path}: registered {DEVICE_NAME} with the current Bitronics picker")


def validate() -> None:
    data = json.loads(Path("src/components/firmware_data.json").read_text())
    matches = [d for d in data.get("devices", []) if d.get("name") == DEVICE_NAME]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {DEVICE_NAME} entry, got {len(matches)}")

    device = matches[0]
    if device.get("picture") != DEVICE_PICTURE:
        raise RuntimeError("BitzyLabs device picture was not applied correctly")

    factory = Path("public") / device["boards"][0]["supported_firmware"][0]["path"]
    update = Path("public/firmware") / SLUG / VERSION / f"{BOARD_FILE}_firmware.bin"
    device_art = Path("public/pictures/bitzylabs-cyd.webp")
    board_art = Path("public/pictures/boards") / f"{BOARD_LABEL}.png"

    for required in (factory, update, device_art, board_art):
        if not required.is_file() or required.stat().st_size == 0:
            raise RuntimeError(f"Required BitzyLabs overlay file missing or empty: {required}")

    devices_ts = Path("src/lib/devices.ts")
    if devices_ts.exists() and "device: 'BitzyLabs CYD'" not in devices_ts.read_text():
        raise RuntimeError("New Bitronics UI detected but BitzyLabs DEVICE_SOURCES entry is missing")

    print("BitzyLabs flasher overlay validation passed")


def main() -> None:
    patch_firmware_data()
    patch_new_device_sources()
    validate()


if __name__ == "__main__":
    main()
