/**
 * STM32 ROM bootloader flashing over Web Serial — the "STM 32 BluePill" path.
 *
 * The STM32F103's system bootloader lives in ROM and speaks the AN3155
 * command set over USART1: the host sends a single 0x7F byte, the chip
 * measures that frame to derive the baud rate, and every command afterwards
 * is a byte followed by its complement, answered with ACK (0x79) /
 * NACK (0x1F) and checksummed by XOR. Per AN2606 for the STM32F101xx/F103xx
 * the link is 8 data bits, EVEN parity, 1 stop bit, on PA9 (TX) / PA10 (RX).
 *
 * Every framing detail below — command bytes, the erase payloads, the
 * 4-byte-aligned write block with its length-minus-one prefix — is matched
 * to three implementations known to flash these boards:
 *
 *   - stm32flash, the canonical C tool (stm32duino/stm32flash);
 *   - Gamadril/stm-serial-flasher, a Web Serial app (MIT);
 *   - yanxke/stm32webflash, also Web Serial (Apache-2.0).
 *
 * What none of them can do for us is run on real hardware from a build, so
 * the flow finishes by reading every byte back and comparing: a write that
 * did not land is reported, never assumed.
 *
 * One thing serial cannot do is move BOOT0. The board has to be in its
 * bootloader before this runs — jumper to 1, press Reset — and the panel
 * next to the flash button says so. If it was skipped, the sync timeout
 * below is where that shows up, so the message says it plainly.
 */

const ACK = 0x79;
const NACK = 0x1f;
const BUSY = 0x76;

const SYNC_BYTE = 0x7f;
const CMD_GET = 0x00;
const CMD_GID = 0x02;
const CMD_READ = 0x11;
const CMD_WRITE = 0x31;
const CMD_ERASE = 0x43;
const CMD_EXT_ERASE = 0x44;
const CMD_EXT_ERASE_NS = 0x45;

const SYNC_TIMEOUT = 700; // per attempt; the chip answers in milliseconds
const SYNC_ATTEMPTS = 6;
const ACK_TIMEOUT = 3000;
const ERASE_TIMEOUT = 30_000; // extended mass erase on big parts is slow
const WRITE_TIMEOUT = 10_000;
const CHUNK = 256; // AN3155: never more than 256 bytes per write

/** Where the F103 boots from (AN2606); the linker script agrees. */
const FLASH_BASE = 0x08000000;

export type Stm32Phase = 'sync' | 'erase' | 'write' | 'verify';

export type Stm32FlashOptions = {
  /** The Web Serial port. It is re-opened below at the bootloader's settings. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  port: any;
  /** The firmware image, written at 0x08000000. */
  data: Uint8Array;
  onProgress?: (percent: number, phase: Stm32Phase) => void;
};

export type Stm32FlashResult = {
  /** The chip's own ID: 0x410 is an STM32F103x8/xB, i.e. a Blue Pill. */
  deviceId: number;
  /** False only when the bootloader does not implement Read Memory. */
  verified: boolean;
};

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const xor = (bytes: number[]) => bytes.reduce((acc, byte) => acc ^ byte, 0);

const equalBytes = (read: number[], expected: Uint8Array) =>
  read.length === expected.length && read.every((byte, i) => byte === expected[i]);

/**
 * One conversation with the bootloader: a background pump collects whatever
 * arrives, and every protocol step pulls exactly the bytes it needs from
 * that collection, with a deadline.
 */
class Link {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private readonly reader: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private readonly writer: any;
  private readonly inbox: number[] = [];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  constructor(port: any) {
    this.reader = port.readable.getReader();
    this.writer = port.writable.getWriter();
    void this.pumpReads();
  }

  private async pumpReads(): Promise<void> {
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) return;
        if (value) for (const byte of value) this.inbox.push(byte);
      }
    } catch {
      // The port went away mid-flash; whoever is waiting times out with a
      // message that names the step, which is the useful thing to know.
    }
  }

  private async send(bytes: number[]): Promise<void> {
    await this.writer.write(Uint8Array.from(bytes));
  }

  /** Take exactly `count` bytes, or null once `ms` has passed. */
  private async take(count: number, ms: number): Promise<number[] | null> {
    const deadline = performance.now() + ms;
    while (this.inbox.length < count) {
      if (performance.now() >= deadline) return null;
      await sleep(5);
    }
    return this.inbox.splice(0, count);
  }

  private async expectAck(ms: number, context: string, hint?: string): Promise<void> {
    const deadline = performance.now() + ms;
    for (;;) {
      const left = deadline - performance.now();
      const got = left > 0 ? await this.take(1, left) : null;
      if (!got) {
        throw new Error(
          `No response from the bootloader while ${context}.${hint ? ` ${hint}` : ''}`,
        );
      }
      const byte = got[0];
      if (byte === ACK) return;
      if (byte === NACK) {
        throw new Error(`The bootloader rejected the command while ${context} (NACK).`);
      }
      if (byte === BUSY) continue;
      throw new Error(
        `Unexpected byte 0x${byte.toString(16)} from the bootloader while ${context}.`,
      );
    }
  }

  /** Wake the bootloader: 0x7F, which it measures to learn the baud rate. */
  async sync(): Promise<void> {
    const hint =
      'The board is not in its ROM bootloader: set the BOOT0 jumper to 1, press Reset, ' +
      'and check the serial wires are crossed (adapter TX to PA10, adapter RX to PA9).';

    for (let attempt = 0; attempt < SYNC_ATTEMPTS; attempt++) {
      this.inbox.length = 0; // drop whatever the line picked up while idle
      await this.send([SYNC_BYTE]);

      const deadline = performance.now() + SYNC_TIMEOUT;
      let synced = false;
      while (!synced && performance.now() < deadline) {
        const got = await this.take(1, deadline - performance.now());
        if (!got) break;
        if (got[0] === ACK) synced = true;
        // Anything else while syncing is line noise; keep scanning.
      }

      if (synced) {
        this.inbox.length = 0; // ignore trailing noise before the first command
        return;
      }
      await sleep(150);
    }

    throw new Error(`No response from the bootloader while syncing (0x7F). ${hint}`);
  }

  private async command(cmd: number, context: string, ms = ACK_TIMEOUT): Promise<void> {
    await this.send([cmd, cmd ^ 0xff]);
    await this.expectAck(ms, context);
  }

  private async sendAddress(address: number): Promise<void> {
    const bytes = [
      (address >>> 24) & 0xff,
      (address >>> 16) & 0xff,
      (address >>> 8) & 0xff,
      address & 0xff,
    ];
    await this.send([...bytes, xor(bytes)]);
    await this.expectAck(ACK_TIMEOUT, 'sending an address');
  }

  /**
   * GET: N, then (version + N commands), then ACK. The command list is what
   * decides which erase form this chip takes, rather than a table of parts.
   */
  async getCommands(): Promise<number[]> {
    await this.command(CMD_GET, 'asking which commands the bootloader has');
    const head = await this.take(1, ACK_TIMEOUT);
    if (!head) throw new Error('No response to GET.');
    const payload = await this.take(head[0] + 1, ACK_TIMEOUT);
    if (!payload) throw new Error('The bootloader began answering GET but did not finish.');
    await this.expectAck(ACK_TIMEOUT, 'finishing GET');
    return payload.slice(1);
  }

  /** GET_ID: N, then a two-byte chip ID, then ACK. */
  async getDeviceId(): Promise<number> {
    await this.command(CMD_GID, 'asking what chip this is');
    const head = await this.take(1, ACK_TIMEOUT);
    if (!head) throw new Error('No response to GET_ID.');
    const payload = await this.take(head[0] + 1, ACK_TIMEOUT);
    if (!payload || payload.length < 2) {
      throw new Error('The bootloader began answering GET_ID but did not finish.');
    }
    await this.expectAck(ACK_TIMEOUT, 'finishing GET_ID');
    return (payload[0] << 8) | payload[1];
  }

  /**
   * Erase everything first, because flash can only clear bits: writing over
   * programmed pages silently corrupts them. Which form the chip takes is
   * read off its own command list — 0x43 takes one page byte (0xFF = all),
   * the extended forms a two-byte page count (0xFFFF = all).
   */
  async erase(commands: number[]): Promise<void> {
    const cmd = [CMD_ERASE, CMD_EXT_ERASE, CMD_EXT_ERASE_NS].find((candidate) =>
      commands.includes(candidate),
    );
    if (cmd === undefined) {
      throw new Error(
        'The bootloader reports no erase command, so the flash cannot be prepared. ' +
          'Refusing to write over pages that were not erased.',
      );
    }

    await this.command(cmd, 'starting the erase');
    await this.send(cmd === CMD_ERASE ? [0xff, 0x00] : [0xff, 0xff, 0x00]);
    await this.expectAck(ERASE_TIMEOUT, 'erasing the flash', 'Mass erase can take a moment.');
  }

  /**
   * One WRITE_MEMORY: command, then the address (big-endian + XOR), then
   * the count byte (length − 1), the data padded to a multiple of four with
   * 0xFF, and the XOR of the lot — exactly the block stm32flash builds.
   */
  async writeBlock(address: number, chunk: Uint8Array): Promise<void> {
    if (address % 4 !== 0) {
      throw new Error(`Internal error: write address 0x${address.toString(16)} is not aligned.`);
    }
    if (chunk.length > CHUNK) {
      throw new Error('Internal error: write block is larger than the protocol allows.');
    }

    await this.command(CMD_WRITE, 'starting a write');
    await this.sendAddress(address);

    const aligned = Math.ceil(chunk.length / 4) * 4;
    const frame: number[] = [aligned - 1];
    for (let i = 0; i < aligned; i++) {
      frame.push(i < chunk.length ? chunk[i] : 0xff);
    }
    frame.push(xor(frame));

    await this.send(frame);
    await this.expectAck(WRITE_TIMEOUT, 'writing a block to flash');
  }

  /** One READ_MEMORY: command, address, count, then the bytes themselves. */
  async readBlock(address: number, length: number): Promise<number[] | null> {
    await this.command(CMD_READ, 'reading the flash back');
    await this.sendAddress(address);
    await this.send([length - 1, (length - 1) ^ 0xff]);
    await this.expectAck(ACK_TIMEOUT, 'reading the flash back');
    return this.take(length, ACK_TIMEOUT);
  }

  async close(): Promise<void> {
    try {
      await this.reader.cancel();
    } catch {
      // already cancelled or released
    }
    for (const lock of [this.reader, this.writer]) {
      try {
        lock.releaseLock();
      } catch {
        // already released
      }
    }
  }
}

export async function flashBluePill(options: Stm32FlashOptions): Promise<Stm32FlashResult> {
  const { port, data, onProgress } = options;
  if (!port) throw new Error('Connect the board first.');
  if (!data.length) throw new Error('There is no firmware to flash.');

  const report = (percent: number, phase: Stm32Phase) => onProgress?.(percent, phase);
  report(0, 'sync');

  // Start from a known line configuration: the bootloader is fixed at 8-E-1
  // (AN2606), and this port may just have been opened for an ESP device at
  // 8-N-1. Closing it first also flushes anything the line picked up while
  // nobody was listening.
  if (port.readable) {
    try {
      await port.close();
    } catch {
      // Not really open; the open below is what reports the real problem.
    }
  }
  await port.open({
    baudRate: 115200,
    dataBits: 8,
    stopBits: 1,
    parity: 'even',
    flowControl: 'none',
  });

  const link = new Link(port);
  try {
    await link.sync();

    const commands = await link.getCommands();
    const deviceId = await link.getDeviceId();

    report(0, 'erase');
    await link.erase(commands);

    for (let offset = 0; offset < data.length; offset += CHUNK) {
      const chunk = data.subarray(offset, Math.min(offset + CHUNK, data.length));
      await link.writeBlock(FLASH_BASE + offset, chunk);
      report(Math.round(((offset + chunk.length) / data.length) * 100), 'write');
    }

    let verified = false;
    if (commands.includes(CMD_READ)) {
      verified = true;
      for (let offset = 0; offset < data.length; offset += CHUNK) {
        const chunk = data.subarray(offset, Math.min(offset + CHUNK, data.length));
        const read = await link.readBlock(FLASH_BASE + offset, chunk.length);
        if (!read || !equalBytes(read, chunk)) {
          throw new Error(
            'The flash does not match the firmware after writing it. Try the flash again; ' +
              'if it keeps failing, the board may be dropping out of its bootloader.',
          );
        }
        report(Math.round(((offset + chunk.length) / data.length) * 100), 'verify');
      }
    }

    return { deviceId, verified };
  } finally {
    await link.close();
  }
}
