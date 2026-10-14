import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';

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
