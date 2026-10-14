import { sourceFor } from '@/lib/devices';

/**
 * The DevBoard Tests section: bench boards with their own SmoothBlinky
 * firmware, offered before the miners because that is the order somebody
 * at a workbench wants them in.
 *
 * These two are the fork's own devices rather than upstream's, so the flow
 * around them is ours too: one board and one firmware per device means the
 * middle step is a single "Continue To Flash" button instead of a picker,
 * and the Blue Pill takes a flashing path upstream has never had (see
 * lib/bitzy/stm32flash.ts).
 */
export const isDevBoard = (device: string): boolean =>
  sourceFor(device)?.category === 'devboards';

/** A devboard whose ROM bootloader speaks AN3155 rather than esptool. */
export const isStm32 = (device: string): boolean => sourceFor(device)?.mcu === 'stm32';
