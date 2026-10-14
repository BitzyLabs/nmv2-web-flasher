/**
 * ST-Link over WebUSB -- the "STM 32 Blue Pill" path, and the only one
 * this site has: the kit ships an ST-Link V2, so the board is reached
 * through its debug port. No BOOT0 jumper, no serial adapter, no crossed
 * wires, and no Web Serial picker anywhere in the flow.
 *
 * WebUSB lets the page open the dongle itself and send the same packets
 * st-flash sends from the shell. Every opcode and packet layout below is
 * taken from the stlink-org/stlink sources (BSD-3-Clause):
 * inc/stlink_cmd.h for the commands, src/stlink-lib/usb.c for the
 * transfers -- a 16-byte command out, a fixed reply in, and two memory
 * operations that reach every register on the chip. The connect sequence
 * mirrors what stlink's own open does, and matches the one inspected in
 * Hypothesis-Magic/stm32-web-flasher -- the donor this fork's STM32 path
 * was rebuilt from when the reader pointed at it.
 *
 * That is the whole trick: the ST-Link firmware does the SWD protocol, so
 * stopping the core, unlocking the flash controller, erasing pages and
 * programming halfwords are all plain memory reads and writes. Halting and
 * running go through DHCSR exactly the way stlink's own APIv2 step/run
 * emulation does, so nothing here depends on which command dialect the
 * dongle speaks beyond entering SWD mode -- which is negotiated, with the
 * older API as the fallback.
 *
 * Programming follows RM0008 for the F103: unlock with the two keys, set
 * PER and hand each 1 KiB page address to STR, set PG while halfwords are
 * written (a 32-bit store carries two, the same as st-flash's SRAM
 * loader), and poll FLASH_SR's BSY after every step -- one millisecond
 * first, so the operation is latched before the first sample, then check
 * the error bits. Nothing is trusted: every byte is read back and
 * compared before the chip is released, and a mismatch is reported with
 * the address it broke at.
 *
 * WebUSB needs the device node to be openable (udev/0666 -- checked on
 * the bench machine), no kernel driver claiming the debug interface (the
 * `stlink` module must stay unloaded), and a user gesture for the
 * chooser. The Connect button supplies the gesture; the failures that
 * remain say which of the other two they were.
 */

const CMD_SIZE = 16;

/** ST-Link command bytes -- inc/stlink_cmd.h (stlink-org/stlink). */
const CMD_GET_VERSION = 0xf1;
const CMD_DEBUG = 0xf2;
const CMD_DFU = 0xf3;
const CMD_GET_CURRENT_MODE = 0xf5;
const DEBUG_ENTER_V1 = 0x20;
const DEBUG_ENTER_V2 = 0x30;
const DEBUG_ENTER_SWD = 0xa3;
const DEBUG_READ_IDCODES_V1 = 0x22;
const DEBUG_READ_IDCODES_V2 = 0x31;
const DEBUG_READMEM32 = 0x07;
const DEBUG_WRITEMEM32 = 0x08;
const DEBUG_RWSTATUS = 0x3b;
const DEBUG_RWSTATUS2 = 0x3e;
const DEBUG_EXIT = 0x21;
const DEBUG_SET_SWCLK_FREQ = 0x43;
const DFU_EXIT = 0x07;

/** What GET_CURRENT_MODE answers first: the mode the probe was left in. */
const MODE_DFU = 0;
const MODE_DEBUG = 2;

/**
 * STLINK_SWDCLK_950KHZ_DIVISOR, the divisor stlink sends when it wants a
 * bench clock that long jumper wires survive: 950 kHz.
 */
const SWCLK_DIVISOR_950KHZ = 3;

/** The one value every status-checked reply opens with: "all well". */
const STATUS_OK = 0x80;
const STATUS_MEANING: Record<number, string> = {
  0x81: 'the debug logic faulted',
  0x0c: 'the write was rejected',
  0x0d: 'the write failed verification on the probe',
  0x10: 'the access port is busy',
  0x11: 'the access port faulted',
  0x12: 'the access port reported an error',
  0x14: 'the debug port is busy',
  0x15: 'the debug port faulted',
  0x16: 'the debug port reported an error',
};

/** ARMv7-M debug and STM32F1 flash registers (ARMv7-M ARM / RM0008). */
const DHCSR = 0xe000edf0;
const DBGKEY = 0xa05f0000;
const C_HALT = 0x00000002;
const C_DEBUGEN = 0x00000001;
const S_HALT = 0x20000000;
const AIRCR = 0xe000ed0c;
const SYSRESETREQ = 0x05fa0004;
const DBGMCU_IDCODE = 0xe0042000;

const FLASH_KEYR = 0x40022004;
const FLASH_SR = 0x4002200c;
const FLASH_CR = 0x40022010;
const FLASH_AR = 0x40022014;
const FLASH_KEY1 = 0x45670123;
const FLASH_KEY2 = 0xcdef89ab;
const SR_BSY = 0x01;
const SR_PGERR = 0x04;
const SR_WRPRTERR = 0x10;
const SR_EOP = 0x20;
const SR_CLEAR = SR_EOP | SR_PGERR | SR_WRPRTERR; // write-1-to-clear
const CR_PG = 0x01;
const CR_PER = 0x02;
const CR_STRT = 0x40;
const CR_LOCK = 0x80000000;
const FLASH_BASE = 0x08000000;
const PAGE_SIZE = 0x400;

/** The part this site serves over SWD: the F103C8 medium-density (Blue Pill). */
const DEVICE_ID_F103_MD = 0x410;

const TRANSFER_TIMEOUT = 3000;
const HALT_TIMEOUT = 2000;
const READY_TIMEOUT = 15_000; // an F1 page erase takes ~40 ms; this is slack, not expectation
const CHUNK = 1024;

/**
 * What the chooser offers: the ST-Link V2 family, and only that family.
 * The instructions above the button promise an ST-Link V2, the kit ships
 * one, and a chooser that also listed a V1 or a V3 would offer probes
 * this path has never been checked against.
 */
const STLINK_FILTERS = [
  { vendorId: 0x0483, productId: 0x3748 }, // ST-Link V2 -- the dongle on this bench
  { vendorId: 0x0483, productId: 0x374a }, // ST-Link V2-1 without mass storage
  { vendorId: 0x0483, productId: 0x374b }, // ST-Link V2-1
];

export type StlinkPhase = 'halt' | 'erase' | 'write' | 'verify';

export type StlinkFlashOptions = {
  probe: StlinkConnection;
  data: Uint8Array;
  onProgress?: (percent: number, phase: StlinkPhase) => void;
};

export type StlinkFlashResult = {
  /** The chip's own ID: 0x410 is an STM32F103x8/xB, i.e. a Blue Pill. */
  deviceId: number;
  /** True only after every written byte was read back and matched. */
  verified: boolean;
};

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const le32 = (bytes: Uint8Array, offset: number): number =>
  (bytes[offset] |
    (bytes[offset + 1] << 8) |
    (bytes[offset + 2] << 16) |
    (bytes[offset + 3] << 24)) >>>
  0;

const hex = (value: number): string => `0x${(value >>> 0).toString(16)}`;

function withTimeout<T>(promise: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${what}.`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

// WebUSB's own types are not in the TypeScript lib; these are the fields
// the code below touches, structurally -- enough for the compiler, with
// no dependency on a package the site does not otherwise carry.
type UsbEndpoint = {
  endpointNumber: number;
  direction: 'in' | 'out';
  type: string;
};
type UsbInterface = {
  interfaceNumber: number;
  alternates: { interfaceClass: number; endpoints: UsbEndpoint[] }[];
};
type UsbDevice = {
  vendorId: number;
  productId: number;
  productName?: string;
  configurations: { interfaces: UsbInterface[] }[];
  open(): Promise<void>;
  selectConfiguration(value: number): Promise<void>;
  claimInterface(number: number): Promise<void>;
  releaseInterface(number: number): Promise<void>;
  close(): Promise<void>;
  transferIn(endpoint: number, length: number): Promise<{ status: string; data?: DataView }>;
  transferOut(endpoint: number, data: Uint8Array): Promise<{ status: string }>;
};
type UsbApi = {
  requestDevice(options: { filters: { vendorId: number; productId: number }[] }): Promise<UsbDevice>;
};

/**
 * One open ST-Link, claimed and in debug mode. The public surface is
 * deliberately the two memory operations plus halt -- everything the
 * flasher needs and nothing it does not.
 */
export class StlinkConnection {
  /** Which status dialect the firmware answers GETLASTRWSTATUS in. */
  private statusRoute: 'v2' | 'v1' | null = null;
  /** The dialect, settled in start() from the version and what entered. */
  private api: 1 | 2 = 1;
  /** "V2J48S7", parsed like st-info prints it; shown in the status line. */
  version = '';
  /** The DBGMCU device id read on entry; 0x410 is a Blue Pill. */
  deviceId = 0;

  private constructor(
    private readonly device: UsbDevice,
    private readonly epIn: number,
    private readonly epOut: number,
  ) {}

  /**
   * The chooser (user gesture), claim, SWD entry, chip id. The chip id is
   * read here so that a green "connected" means the probe really is on a
   * target, not merely on the bench. A failure after the claim closes what
   * it took, so the next attempt starts from a clean interface instead of
   * complaining that something else holds the dongle.
   */
  static async open(): Promise<StlinkConnection> {
    const usb = (navigator as Navigator & { usb?: UsbApi }).usb;
    if (!usb) throw new Error('This browser cannot open USB devices -- use Chrome or Brave.');
    let device: UsbDevice;
    try {
      device = await usb.requestDevice({ filters: STLINK_FILTERS });
    } catch (error) {
      if (error instanceof Error && error.name === 'NotFoundError') {
        throw new Error('ST-Link selection was canceled.');
      }
      throw error;
    }

    try {
      await device.open();
    } catch (error) {
      throw new Error(
        `Could not open ${device.productName ?? 'the ST-Link'}: ${
          error instanceof Error ? error.message : String(error)
        }. On Linux that is a missing udev permission on its device node; ` +
          'on Windows the probe must be bound to the WinUSB driver -- install it with Zadig.',
      );
    }
    if (!device.configurations.length) throw new Error('The ST-Link reported no configuration.');
    await device.selectConfiguration(1);

    // The debug interface is the vendor-specific one; a V2-1's storage and
    // CDC interfaces are other people's business and stay unclaimed.
    let target: { iface: number; epIn: number; epOut: number } | null = null;
    for (const iface of device.configurations[0].interfaces) {
      for (const alternate of iface.alternates) {
        if (alternate.interfaceClass !== 0xff) continue;
        const epIn = alternate.endpoints.find((e) => e.direction === 'in' && e.type === 'bulk');
        const epOut = alternate.endpoints.find((e) => e.direction === 'out' && e.type === 'bulk');
        if (epIn && epOut) {
          target = { iface: iface.interfaceNumber, epIn: epIn.endpointNumber, epOut: epOut.endpointNumber };
          break;
        }
      }
      if (target) break;
    }
    if (!target) {
      throw new Error('The ST-Link has no vendor debug interface with bulk endpoints.');
    }
    try {
      await device.claimInterface(target.iface);
    } catch (error) {
      throw new Error(
        `The ST-Link's debug interface is already in use: ${
          error instanceof Error ? error.message : String(error)
        }. On Linux, close st-flash or OpenOCD and make sure no stlink kernel module ` +
          'has claimed it; on Windows, close STM32CubeProgrammer and bind the probe ' +
          'to the WinUSB driver (Zadig).',
      );
    }

    const connection = new StlinkConnection(device, target.epIn, target.epOut);
    try {
      await connection.start();
    } catch (error) {
      await connection.close();
      throw error;
    }
    return connection;
  }

  /**
   * Version, whatever mode the firmware was left in, the SWD clock, the
   * dialect entry (either one), the debug port, chip id -- in that order,
   * on the one instance that outlives them. The dialect is recorded here
   * rather than at construction: everything after the entry, from the
   * core-id command to the write-status dialect, has to run on whichever
   * one actually answered, and the fallback can swap it.
   */
  private async start(): Promise<void> {
    this.version = await this.getVersion();
    await this.leaveStaleMode();
    await this.setSwdClock();
    let api = this.apiFromVersion(this.version);
    let entered = await this.tryEnterSwd(api);
    if (!entered) {
      api = api === 1 ? 2 : 1;
      entered = await this.tryEnterSwd(api);
    }
    if (!entered) {
      throw new Error(
        `The ST-Link (${this.version}) did not accept either SWD entry command -- it may need the stlink tools first.`,
      );
    }
    this.api = api;
    await this.checkDebugPort();
    this.deviceId = (await this.read32(DBGMCU_IDCODE)) & 0xfff;
  }

  /**
   * stlink's own open asks the firmware which mode it is sitting in and
   * exits a stale one before touching SWD: DFU gets DFU_EXIT, a debug
   * session left behind gets DEBUG_EXIT. Both commands are send-only --
   * neither firmware path replies, and reading for a reply would hand its
   * bytes to the next transfer and desync everything after it.
   */
  private async leaveStaleMode(): Promise<void> {
    const reply = await this.command([CMD_GET_CURRENT_MODE], 2, null, 'reading the probe mode');
    if (!reply || reply.length < 1) return;
    const mode = reply[0];
    if (mode === MODE_DFU) {
      await this.command([CMD_DFU, DFU_EXIT], 0, null, 'exiting the probe DFU mode');
    } else if (mode === MODE_DEBUG) {
      await this.command([CMD_DEBUG, DEBUG_EXIT], 0, null, 'exiting the probe\'s stale debug session');
    }
  }

  /**
   * 950 kHz, the conservative divisor stlink sends for bench wiring.
   * Probes older than J22 have no set-frequency command (stlink skips
   * them too, keyed on the same version numbers), and a probe that
   * refuses the command keeps its own default clock -- none of which is
   * worth failing a connection over.
   */
  private async setSwdClock(): Promise<void> {
    if (this.apiFromVersion(this.version) !== 2) return;
    try {
      await this.command(
        [CMD_DEBUG, DEBUG_SET_SWCLK_FREQ, SWCLK_DIVISOR_950KHZ, 0],
        2,
        { status: true, retry: true },
        'setting the SWD clock',
      );
    } catch {
      // The firmware's own clock stands.
    }
  }

  /** "V2J48S7" -> the dialect; the same numbers stlink keys its rules on. */
  private apiFromVersion(version: string): 1 | 2 {
    const match = /^V(\d+)J(\d+)/.exec(version);
    if (!match) return 1;
    const major = Number(match[1]);
    const jtag = Number(match[2]);
    return major >= 3 || (major === 2 && jtag >= 22) ? 2 : 1;
  }

  private async getVersion(): Promise<string> {
    const reply = await this.command([CMD_GET_VERSION], 6, null, 'reading the ST-Link version');
    if (!reply || reply.length < 3) throw new Error('The ST-Link sent a short version reply.');
    const major = reply[0] >= 0x10 ? reply[0] >> 4 : reply[0];
    return `V${major}J${reply[1]}S${reply[2]}`;
  }

  private async tryEnterSwd(api: 1 | 2): Promise<boolean> {
    try {
      if (api === 2) {
        await this.command(
          [CMD_DEBUG, DEBUG_ENTER_V2, DEBUG_ENTER_SWD],
          2,
          { retry: true },
          'entering SWD mode',
        );
      } else {
        await this.command([CMD_DEBUG, DEBUG_ENTER_V1, DEBUG_ENTER_SWD], 0, null, 'entering SWD mode');
      }
      return true;
    } catch {
      return false;
    }
  }

  /** DPIDR across the wire: all-ones means SWDIO is floating. */
  private async checkDebugPort(): Promise<void> {
    const id = await this.readCoreId();
    if (id === 0xffffffff || id === 0) {
      throw new Error(
        'The debug port did not answer -- check the probe is wired to SWDIO and SWCLK (and GND, and 3V3 for the target).',
      );
    }
  }

  private async readCoreId(): Promise<number> {
    if (this.api === 2) {
      const reply = await this.command(
        [CMD_DEBUG, DEBUG_READ_IDCODES_V2],
        12,
        { status: true },
        'reading the debug port id',
      );
      if (!reply) return 0;
      return le32(reply, 4);
    }
    const reply = await this.command(
      [CMD_DEBUG, DEBUG_READ_IDCODES_V1],
      4,
      null,
      'reading the debug port id',
    );
    return reply && reply.length >= 4 ? le32(reply, 0) : 0;
  }

  /** Send `cmd` padded to 16 bytes, read `replyLength` back (0 for none). */
  private async command(
    cmd: number[],
    replyLength: number,
    opts: { status?: boolean; retry?: boolean } | null,
    what: string,
  ): Promise<Uint8Array | null> {
    for (let attempt = 0; ; attempt++) {
      const packet = new Uint8Array(CMD_SIZE);
      packet.set(cmd);
      const sent = await withTimeout(
        this.device.transferOut(this.epOut, packet),
        TRANSFER_TIMEOUT,
        `sending "${what}"`,
      );
      if (sent.status !== 'ok') {
        throw new Error(`The ST-Link rejected "${what}" (${sent.status}).`);
      }
      if (replyLength === 0) return null;

      const reply = await this.receive(replyLength, what);
      if (!opts?.status || reply.length < 1) return reply;

      const code = reply[0];
      if (code === STATUS_OK) return reply;
      const meaning = STATUS_MEANING[code] ?? `status ${hex(code)}`;
      if (opts.retry && attempt < 2 && (code === 0x10 || code === 0x14)) {
        await sleep(1 << attempt);
        continue;
      }
      throw new Error(`The ST-Link failed while ${what}: ${meaning}.`);
    }
  }

  private async receive(replyLength: number, what: string): Promise<Uint8Array> {
    const result = await withTimeout(
      this.device.transferIn(this.epIn, replyLength),
      TRANSFER_TIMEOUT,
      `the reply to "${what}"`,
    );
    if (result.status !== 'ok' || !result.data) {
      throw new Error(`No reply to "${what}" (${result.status}).`);
    }
    const view = result.data;
    return new Uint8Array(view.buffer, view.byteOffset, view.byteLength).slice();
  }

  /** READMEM_32BIT: the one read primitive, no status byte in the reply. */
  async read32(address: number): Promise<number> {
    const reply = await this.command(
      [CMD_DEBUG, DEBUG_READMEM32, address & 0xff, (address >>> 8) & 0xff, (address >>> 16) & 0xff, (address >>> 24) & 0xff, 4, 0, 0],
      4,
      null,
      `reading ${hex(address)}`,
    );
    if (!reply || reply.length < 4) throw new Error(`Short read at ${hex(address)}.`);
    return le32(reply, 0);
  }

  /** WRITEMEM_32BIT: command out, four data bytes out, then the status. */
  async write32(address: number, value: number): Promise<void> {
    await this.command(
      [CMD_DEBUG, DEBUG_WRITEMEM32, address & 0xff, (address >>> 8) & 0xff, (address >>> 16) & 0xff, (address >>> 24) & 0xff, 4, 0, 0],
      0,
      null,
      `writing ${hex(address)}`,
    );
    const data = new Uint8Array(4);
    data[0] = value & 0xff;
    data[1] = (value >>> 8) & 0xff;
    data[2] = (value >>> 16) & 0xff;
    data[3] = (value >>> 24) & 0xff;
    const sent = await withTimeout(
      this.device.transferOut(this.epOut, data),
      TRANSFER_TIMEOUT,
      `writing ${hex(address)}`,
    );
    if (sent.status !== 'ok') throw new Error(`The write to ${hex(address)} was rejected.`);
    if (this.api === 2) await this.checkWriteStatus();
  }

  /**
   * GETLASTRWSTATUS2 when this firmware knows it, the shorter form when
   * it does not, and neither when it answers neither -- in which case the
   * flash handshake below is the real check anyway, as it was before.
   */
  private async checkWriteStatus(): Promise<void> {
    if (this.statusRoute !== 'v1') {
      try {
        const reply = await this.command(
          [CMD_DEBUG, DEBUG_RWSTATUS2],
          12,
          null,
          'checking the last write',
        );
        if (reply && reply.length >= 12) {
          this.statusRoute = 'v2';
          this.assertWriteOk(reply[0]);
          return;
        }
      } catch {
        // fall through to the shorter dialect
      }
      this.statusRoute = 'v1';
    }
    try {
      const reply = await this.command([CMD_DEBUG, DEBUG_RWSTATUS], 2, null, 'checking the last write');
      if (reply && reply.length >= 1) this.assertWriteOk(reply[0]);
    } catch {
      // The firmware keeps no status surface; FLASH_SR will tell the tale.
    }
  }

  private assertWriteOk(code: number): void {
    if (code === STATUS_OK) return;
    throw new Error(`The ST-Link could not complete a write: ${STATUS_MEANING[code] ?? hex(code)}.`);
  }

  /** A block of 32-bit reads; the tail is padded to a word by the caller. */
  async readBlock(address: number, length: number): Promise<Uint8Array> {
    const out = new Uint8Array(length);
    for (let offset = 0; offset < length; offset += CHUNK) {
      const want = Math.min(CHUNK, length - offset);
      const aligned = (want + 3) & ~3;
      const at = address + offset;
      const reply = await this.command(
        [CMD_DEBUG, DEBUG_READMEM32, at & 0xff, (at >>> 8) & 0xff, (at >>> 16) & 0xff, (at >>> 24) & 0xff, aligned & 0xff, (aligned >>> 8) & 0xff, 0],
        aligned,
        null,
        `reading ${hex(at)}`,
      );
      if (!reply || reply.length < want) throw new Error(`Short block read at ${hex(at)}.`);
      out.set(reply.subarray(0, want), offset);
    }
    return out;
  }

  /** Stop the core through DHCSR -- stlink's own APIv2 emulation does this. */
  async halt(): Promise<void> {
    await this.write32(DHCSR, DBGKEY | C_HALT | C_DEBUGEN);
    const deadline = performance.now() + HALT_TIMEOUT;
    while (performance.now() < deadline) {
      if ((await this.read32(DHCSR)) & S_HALT) return;
      await sleep(10);
    }
    throw new Error('The core would not stop: DHCSR never reported the halt.');
  }

  /** Close what was claimed. Safe to call twice. */
  async close(): Promise<void> {
    try {
      await this.device.close();
    } catch {
      // Already gone -- unplugged mid-session or the browser let go.
    }
  }
}

/** Open the chooser and land in debug mode on an STM32. */
export async function openStlink(): Promise<StlinkConnection> {
  return StlinkConnection.open();
}

const F103_NAMES: Record<number, string> = {
  0x410: 'STM32F103 medium-density (Blue Pill)',
  0x420: 'STM32F103 connectivity-line',
  0x428: 'STM32F103 high-density',
  0x430: 'STM32F103 XL-density',
};

/** How the connect status names what the probe found. */
export function describeDeviceId(deviceId: number): string {
  return F103_NAMES[deviceId] ?? `STM32 family id ${hex(deviceId)}`;
}

/**
 * Halt, unlock, erase every page the image touches, program, read every
 * byte back, lock, reset. Phases are reported as they are: the erase and
 * the write are slow enough to watch, the rest is a heartbeat.
 */
export async function flashBluePillSwd(options: StlinkFlashOptions): Promise<StlinkFlashResult> {
  const { probe, data, onProgress } = options;
  const progress = onProgress ?? (() => undefined);
  if (data.length === 0) throw new Error('There is no firmware image to write.');

  const deviceId = (await probe.read32(DBGMCU_IDCODE)) & 0xfff;
  if (deviceId !== DEVICE_ID_F103_MD) {
    throw new Error(
      `The probe is on a part this build does not target: device id ${hex(deviceId)}, ` +
        `not the STM32F103 (${hex(DEVICE_ID_F103_MD)}) a Blue Pill carries.`,
    );
  }

  progress(0, 'halt');
  await probe.halt();

  await probe.write32(FLASH_KEYR, FLASH_KEY1);
  await probe.write32(FLASH_KEYR, FLASH_KEY2);
  await probe.write32(FLASH_SR, SR_CLEAR);
  const cr = await probe.read32(FLASH_CR);
  if (cr & CR_LOCK) {
    throw new Error(
      `The flash controller will not unlock (FLASH_CR ${hex(cr)}). ` +
        'If the option bytes hold readout protection, it has to be cleared from the stlink tools first.',
    );
  }

  // Erase: one page per 1 KiB of image, RM0008's PER -> AR -> STR.
  const pages = Math.ceil(data.length / PAGE_SIZE);
  for (let page = 0; page < pages; page++) {
    const at = FLASH_BASE + page * PAGE_SIZE;
    const before = await probe.read32(FLASH_CR);
    await probe.write32(FLASH_CR, before | CR_PER);
    await probe.write32(FLASH_AR, at);
    const armed = await probe.read32(FLASH_CR);
    await probe.write32(FLASH_CR, armed | CR_STRT);
    await waitFlashReady(probe, `erasing the page at ${hex(at)}`);
    const after = await probe.read32(FLASH_CR);
    await probe.write32(FLASH_CR, after & ~CR_PER);
    progress(Math.round(((page + 1) / pages) * 100), 'erase');
  }

  // Program: a 32-bit store carries two halfwords; odd tails are padded
  // with the erased value so the last write is still word-aligned.
  const padded = new Uint8Array((data.length + 3) & ~3).fill(0xff);
  padded.set(data);
  await probe.write32(FLASH_CR, (await probe.read32(FLASH_CR)) | CR_PG);
  for (let offset = 0; offset < padded.length; offset += 4) {
    const at = FLASH_BASE + offset;
    await probe.write32(at, le32(padded, offset));
    await waitFlashReady(probe, `writing ${hex(at)}`);
    progress(Math.min(99, Math.floor(((offset + 4) / padded.length) * 100)), 'write');
  }
  await probe.write32(FLASH_CR, CR_LOCK);

  // Verify: every byte of the file, read back out of flash.
  progress(100, 'verify');
  const readBack = await probe.readBlock(FLASH_BASE, padded.length);
  for (let i = 0; i < data.length; i++) {
    if (readBack[i] !== data[i]) {
      throw new Error(
        `Verification failed at ${hex(FLASH_BASE + i)}: the file holds ${hex(data[i])}, ` +
          `the chip holds ${hex(readBack[i])}. The write did not land cleanly.`,
      );
    }
  }

  // Reset into the new build, then drop the halt request the way stlink's
  // own "run" does, so the LED starts blinking without a power cycle. The
  // reset lands between the write and the probe's status reply, so a late
  // error from these two writes is not a flash error: the bytes are
  // already verified and the chip is on its way up either way.
  try {
    await probe.write32(AIRCR, SYSRESETREQ);
  } catch {
    // The write reached the register before the status reply raced it.
  }
  await sleep(250);
  try {
    await probe.write32(DHCSR, DBGKEY | C_DEBUGEN);
  } catch {
    // Already running -- or the debug link dropped with the reset.
  }

  return { deviceId, verified: true };
}

/**
 * FLASH_SR's handshake: BSY is the truth (EOP's interrupt coupling on the
 * F1 makes it a bonus rather than a gate). One millisecond first so the
 * operation is latched before the first sample, then the error bits are
 * read off the very sample that showed the controller idle.
 */
async function waitFlashReady(probe: StlinkConnection, what: string): Promise<void> {
  await sleep(1);
  const deadline = performance.now() + READY_TIMEOUT;
  for (;;) {
    const sr = await probe.read32(FLASH_SR);
    if (!(sr & SR_BSY)) {
      await probe.write32(FLASH_SR, SR_CLEAR);
      if (sr & (SR_PGERR | SR_WRPRTERR)) {
        throw new Error(
          `Flash refused to ${what}: FLASH_SR ${hex(sr)} ` +
            `${sr & SR_PGERR ? '(programming error) ' : ''}` +
            `${sr & SR_WRPRTERR ? '(write protection)' : ''}`.trim(),
        );
      }
      return;
    }
    if (performance.now() > deadline) {
      throw new Error(`Timed out while ${what}: FLASH_SR stuck at ${hex(sr)}.`);
    }
    await sleep(1);
  }
}
