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
 * The Blue Pill cannot: its ROM bootloader sits behind a BOOT0 jumper and
 * speaks through an external serial adapter, and those two facts are the
 * whole difference between Connect working and Connect timing out. The
 * manual CLI route lives with the firmware project itself; the page carries
 * one line.
 */
export default function DevBoardPanel({ device }: DevBoardPanelProps) {
  if (!isDevBoard(device) || !isStm32(device)) return null;

  return (
    <p className="mx-auto w-full max-w-xl text-sm leading-relaxed text-[var(--color-muted-warm)]">
      <span className="font-semibold text-[var(--color-ink)]">Blue Pill:</span> set BOOT0
      to 1 and press Reset, wire a USB-serial adapter (TX → PA10, RX → PA9, GND
      → GND), then pick that port when you press Connect.
    </p>
  );
}
