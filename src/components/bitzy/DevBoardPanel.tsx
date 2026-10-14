import { Download } from 'lucide-react';
import { isDevBoard, isStm32 } from '@/lib/bitzy/devboards';

type DevBoardPanelProps = {
  device: string;
  /** The firmware file this site serves, for the download fallback. */
  download: string;
};

const fileOf = (path: string): string => {
  try {
    return decodeURIComponent(path.split('/').pop() ?? '');
  } catch {
    return path.split('/').pop() ?? '';
  }
};

/**
 * What sits between picking a DevBoard Tests device and pressing Connect.
 *
 * The ESP32 devkit behaves like every other board on this site — plug it in,
 * the flasher handles boot mode. The Blue Pill cannot: its bootloader lives
 * behind a jumper and speaks to a serial adapter, so those steps are said
 * out loud above the button. Both devices keep a manual route underneath,
 * because "the browser could not do it" should never dead-end: the file is
 * one click away and the commands to write it are on screen.
 */
export default function DevBoardPanel({ device, download }: DevBoardPanelProps) {
  if (!isDevBoard(device)) return null;

  const stm32 = isStm32(device);
  const file = fileOf(download);

  const steps = stm32
    ? [
        'Set the BOOT0 jumper to 1 (the H position) and press Reset. The board now boots into its ROM bootloader instead of your firmware.',
        'Wire a USB-serial adapter: adapter TX → PA10, adapter RX → PA9, GND → GND. Power the board from its own USB cable or 3.3 V.',
        'Click Connect and pick the adapter’s serial port. The flasher writes the firmware, then reads it back to check.',
      ]
    : [
        'Plug the devkit into USB. The flasher puts it into bootloader mode itself — there is nothing to set.',
        'Click Connect and pick the board’s serial port.',
      ];

  const commands = stm32
    ? `# ST-Link over SWD, the way the project README wires it:
st-flash --reset write ${file || '<file>'} 0x08000000

# The ROM serial bootloader (BOOT0 = 1), Linux / macOS:
stm32flash -w ${file || '<file>'} -v /dev/ttyUSB0

# The same, Windows PowerShell or CMD:
stm32flash -w ${file || '<file>'} -v COM5`
    : `# Any shell, board on USB:
esptool.py --chip esp32s3 -b 460800 write_flash 0x0 ${file || '<file>'}`;

  return (
    <div className="mx-auto w-full max-w-xl space-y-3 text-left">
      <div className="rounded-xl border border-[var(--color-hairline)] bg-[var(--color-surface)] p-4">
        <p className="brand-kicker">{stm32 ? 'Before you connect' : 'Getting ready'}</p>
        <ol className="mt-2 list-inside list-decimal space-y-1.5 text-sm leading-relaxed text-white/70">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>

      <div className="rounded-xl border border-[var(--color-hairline)] bg-[var(--color-surface)] p-4">
        <p className="brand-kicker">Or flash it yourself</p>
        {download && (
          <a
            href={download}
            download
            className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-[var(--color-bitronics)] transition-opacity hover:opacity-85"
          >
            <Download className="h-4 w-4" />
            Download {file}
          </a>
        )}
        <pre className="font-data mt-3 overflow-x-auto rounded-lg border border-[var(--color-hairline)] bg-black/40 p-3 text-[11px] leading-relaxed text-white/70">
          {commands}
        </pre>
      </div>
    </div>
  );
}
