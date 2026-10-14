/** Where an upstream release published this exact file, when we know. */
export type Upstream = { repo: string; tag: string; asset: string };

export type Firmware = {
  version: string;
  path: string;
  /** What the file should hash to, recorded when it was fetched. */
  sha256?: string;
  upstream?: Upstream;
  /**
   * One word for a version that needs explaining. An old build kept on the
   * list on purpose says why it is there instead of looking like an oversight.
   * It comes from the version's own manifest.
   */
  badge?: string;
};
export type Board = { name: string; file: string; supported_firmware: Firmware[] };

export type DeviceCategory = 'miners' | 'tools' | 'devboards';

/**
 * What a device says for itself. Swapping the background was never enough:
 * somebody arriving at a seed generator deserves to be told what it is before
 * being handed a Flash button.
 */
export type DeviceIntro = {
  kicker: string;
  /** The last word is set in gold, so end on the word that matters. */
  headline: string;
  body: string;
  points: { title: string; body: string }[];
  cta?: { label: string; href: string; note?: string };
};

/**
 * Every device is served the same way: a main manifest lists the versions, and
 * each version's manifest lists the boards that version was built for. The only
 * things that change from one device to the next are which boards belong to it,
 * how they are spelled on screen, and how the device is presented. Adding a
 * device is adding a row.
 */
export type DeviceSource = {
  device: string; // name in firmware_data.json
  slug: string; // folder under public/firmware
  category: DeviceCategory;
  /** One line under the name in the picker. Figures belong in mono. */
  tagline?: string;
  /**
   * A wide hero image for this device. Compose it with the subject on the
   * right and quiet space on the left: the headline sits over the left third.
   * Missing files are not an error, the page just falls back to the plain
   * headline, so a banner can be dropped in later without a code change.
   */
  banner?: string;
  intro?: DeviceIntro;
  /** Where to buy it, when we sell it */
  shop?: string;
  keepsConfiguration?: boolean; // ships a firmware-only image to flash at 0x10000
  /** Boards this device claims out of a shared folder */
  includes?: (board: string) => boolean;
  /**
   * Extra firmware folders whose boards join this device's list. A device is
   * usually one folder, but a board we build ourselves keeps its own folder
   * and its own version numbers while still sitting with its siblings.
   */
  also?: string[];
  /** How a board is spelled in the selector */
  label?: Record<string, string>;
  sort?: (a: Board, b: Board) => number;
  /**
   * Ask the chip what it is before offering boards. Worth it where a device has
   * more boards than anyone can scan, and pointless where it has two.
   */
  detectChip?: boolean;
  /**
   * Which silicon the device's flasher talks to. Absent means the esptool
   * path every miner and tool takes; 'stm32' takes the ROM bootloader path.
   */
  mcu?: 'esp32' | 'stm32';
};

export const CATEGORIES: { id: DeviceCategory; title: string; blurb: string }[] = [
  {
    id: 'devboards',
    title: 'DevBoard Tests',
    blurb: 'Blinky builds for the boards on our own bench.',
  },
  {
    id: 'miners',
    title: 'Miners',
    blurb: 'Solo mining hardware, from lottery odds to multi-terahash.',
  },

];

const SHOP = 'https://www.bitzylabs.com';

export const NERDMINER_ORIGINAL = 'NerdMinerV2 original board (T-Display-S3)';

export const DEVICE_SOURCES: DeviceSource[] = [
  // DevBoard Tests come first: these are the boards this fork bench-tests
  // firmware on, and the picker should offer them before the miners.
  {
    device: 'ESP 32 N16R8',
    category: 'devboards',
    mcu: 'esp32',
    tagline: 'ESP32-S3 bench test',
    slug: 'esp32s3-smoothblinky',
  },
  {
    device: 'STM 32 BluePill',
    category: 'devboards',
    mcu: 'stm32',
    tagline: 'STM32F103 bench test',
    slug: 'stm32-bluepill',
  },
  {
    device: 'NerdMiner',
    category: 'miners',
    tagline: '78 Kh/s',
    shop: `${SHOP}`,
    keepsConfiguration: true,
    detectChip: true, // thirty-two boards across four different chips
    slug: 'nerdminer',
    // The boards this flasher is bench-verified against: the three
    // 2432S02x units and both S3 devkits. Thirty-two boards is a list
    // nobody can choose from, and every one of them would be a guess.
    includes: (board) =>
      [
        'ESP32-2432S024',
        'ESP32-2432S028R',
        'ESP32_2432S028_2USB',
        'ESP32-S3-devKitv1',
        'esp32-s3-devkitc1-n32r8',
      ].includes(board),
    label: { NerdminerV2: NERDMINER_ORIGINAL },
    // The original board goes first, the rest alphabetically.
    sort: (a, b) =>
      a.name === NERDMINER_ORIGINAL
        ? -1
        : b.name === NERDMINER_ORIGINAL
          ? 1
          : a.name.localeCompare(b.name),
  },

];

export const sourceFor = (device: string) => DEVICE_SOURCES.find((s) => s.device === device);
