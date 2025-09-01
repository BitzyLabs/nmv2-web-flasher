'use client';

import { useState, useEffect, useRef } from 'react';
import { ComputerIcon, Download, Usb, Zap, Cpu, GitCompareIcon, RadioReceiver } from 'lucide-react';
import { Button } from './ui/button';
import { ESPLoader, Transport } from 'esptool-js';
import { useTranslation } from 'react-i18next';
import Header from './Header';
import InstructionPanel from './InstructionPanel';
import DeviceModal from './DeviceModal';
import Selector from './Selector';
import device_data from './firmware_data.json';

import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

export default function LandingHero() {
  const { t } = useTranslation();
  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [selectedBoardVersion, setSelectedBoardVersion] = useState('');
  const [selectedFirmware, setSelectedFirmware] = useState('');
  const [status, setStatus] = useState('');
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isFlashing, setIsFlashing] = useState(false);
  const [isLogging, setIsLogging] = useState(false);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isChromiumBased, setIsChromiumBased] = useState(true);
  const [keepConfiguration, setKeepConfiguration] = useState(false);
  const [nerdminerBoards, setNerdminerBoards] = useState<any[]>([]);
  const serialPortRef = useRef<any>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const terminalContainerRef = useRef<HTMLDivElement>(null);
  const readerRef = useRef<ReadableStreamDefaultReader | null>(null);
  const textDecoderRef = useRef<TextDecoderStream | null>(null);
  const readableStreamClosedRef = useRef<Promise<void> | null>(null);
  const logsRef = useRef<string>('');

  // Function to load all Nerdminer boards from manifests
  const loadNerdminerBoards = async () => {
    try {
      const versions = ['v1.7.1', 'v1.7.0', 'v1.6.3'];
      const allBoards = new Map<string, any>();
      
      for (const version of versions) {
        try {
          const manifestResponse = await fetch(`firmware/nerdminer/${version}/manifest.json`);
          if (!manifestResponse.ok) {
            console.warn(`Manifest not found for ${version}`);
            continue;
          }
          
          const manifest = await manifestResponse.json();
          console.log(`Manifest for ${version}:`, manifest);
          
          if (manifest.boards && Array.isArray(manifest.boards)) {
            for (const boardName of manifest.boards) {
              let displayName = boardName;
              
              // Special case for the original board - make it first
              if (boardName.toUpperCase() === 'NERDMINERV2') {
                displayName = 'NERDMINERV2 ORIGINAL BOARD (TDISPLAY-S3)';
              }
              
              if (!allBoards.has(displayName)) {
                allBoards.set(displayName, {
                  name: displayName,
                  supported_firmware: []
                });
              }
              
              // Add this version to the board's supported firmware
              allBoards.get(displayName).supported_firmware.push({
                version: version,
                path: `firmware/nerdminer/${version}/${boardName}_factory.bin`
              });
            }
          }
        } catch (error) {
          console.error(`Error loading manifest for ${version}:`, error);
        }
      }
      
      // Convert Map to Array and sort: Original board first, then alphabetical
      const boardsArray = Array.from(allBoards.values()).sort((a, b) => {
        if (a.name === 'NERDMINERV2 ORIGINAL BOARD (TDISPLAY-S3)') return -1;
        if (b.name === 'NERDMINERV2 ORIGINAL BOARD (TDISPLAY-S3)') return 1;
        return a.name.localeCompare(b.name);
      });
      
      console.log('All loaded boards:', boardsArray);
      setNerdminerBoards(boardsArray);
    } catch (error) {
      console.error('Error loading Nerdminer boards:', error);
    }
  };

  useEffect(() => {
    const userAgent = navigator.userAgent.toLowerCase();
    const isChromium = /chrome|chromium|crios|edge/i.test(userAgent);
    setIsChromiumBased(isChromium);
    
    // Load Nerdminer boards dynamically
    loadNerdminerBoards();
  }, []);

  useEffect(() => {
    if (terminalContainerRef.current && !terminalRef.current && isLogging) {
      const term = new Terminal({
        cols: 80,
        rows: 24,
        theme: {
          background: '#1a1b26',
          foreground: '#a9b1d6',
        },
      });
      terminalRef.current = term;
      term.open(terminalContainerRef.current);
      term.writeln(t('status.loggingStarted'));
      logsRef.current = t('status.loggingStarted') + '\n';
    }

    return () => {
      if (terminalRef.current) {
        terminalRef.current.dispose();
        terminalRef.current = null;
      }
    };
  }, [isLogging, t]);

  const devices = device_data.devices;
  
  // Get device data with dynamic support for Nerdminer
  const getDeviceData = () => {
    if (selectedDevice === '') return { boards: [] };
    
    const device = devices.find((d) => d.name == selectedDevice);
    if (!device) return { boards: [] };
    
    if (device.name === 'Nerdminer') {
      // Return dynamic boards for Nerdminer
      return { boards: nerdminerBoards };
    }
    
    return device;
  };
  
  const device = getDeviceData();
  const board =
    selectedBoardVersion !== ''
      ? device.boards.find((b) => b.name == selectedBoardVersion)!
      : { supported_firmware: [] };
  const firmware =
    selectedFirmware !== ''
      ? board.supported_firmware.find((f) => f.version == selectedFirmware)!
      : { path: '' };

  const handleConnect = async () => {
    setIsConnecting(true);
    setStatus(t('status.connecting'));

    try {
      const port = await navigator.serial.requestPort();
      await port.open({
        baudRate: 115200,
        dataBits: 8,
        stopBits: 1,
        parity: 'none',
        flowControl: 'none',
      });

      serialPortRef.current = port;
      setIsConnected(true);
      setStatus(t('status.connected'));
    } catch (error) {
      console.error('Connection failed:', error);
      setStatus(
        `${t('status.connectionFailed')}: ${error instanceof Error ? error.message : String(error)}`
      );
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (isLogging) {
      await stopSerialLogging();
    }
    try {
      if (serialPortRef.current?.readable) {
        await serialPortRef.current.close();
      }
      serialPortRef.current = null;
      setIsConnected(false);
      setStatus('');
    } catch (error) {
      console.error('Disconnect error:', error);
      setStatus(
        `${t('status.disconnectError')}: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  };

  const startSerialLogging = async () => {
    if (!serialPortRef.current) {
      setStatus(t('status.connectFirst'));
      return;
    }

    try {
      setIsLogging(true);
      const port = serialPortRef.current;

      // First ensure any existing connections are cleaned up
      if (readerRef.current) {
        await readerRef.current.cancel();
      }
      if (readableStreamClosedRef.current) {
        await readableStreamClosedRef.current;
      }

      // Set up text decoder stream
      const decoder = new TextDecoderStream();
      const inputDone = port.readable.pipeTo(decoder.writable);
      const inputStream = decoder.readable;
      const reader = inputStream.getReader();

      textDecoderRef.current = decoder;
      readableStreamClosedRef.current = inputDone;
      readerRef.current = reader;

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            reader.releaseLock();
            break;
          }
          terminalRef.current?.write(value);
          logsRef.current += value;
        }
      } catch (error) {
        console.error('Error in read loop:', error);
      }
    } catch (error) {
      console.error('Serial logging error:', error);
      setStatus(
        `${t('status.loggingError')}: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    setIsLogging(false);
  };

  const stopSerialLogging = async () => {
    try {
      if (readerRef.current) {
        await readerRef.current.cancel();
        readerRef.current = null;
      }
      if (readableStreamClosedRef.current) {
        await readableStreamClosedRef.current;
        readableStreamClosedRef.current = null;
      }
      if (textDecoderRef.current) {
        textDecoderRef.current = null;
      }
    } catch (error) {
      console.error('Error stopping serial logging:', error);
    } finally {
      setIsLogging(false);
    }
  };

  const downloadLogs = () => {
    const blob = new Blob([logsRef.current], { type: 'text/plain' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    a.href = url;
    a.download = `bitaxe-logs-${timestamp}.txt`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  };

  const handleStartFlashing = async () => {
    if (!serialPortRef.current) {
      setStatus(t('status.connectFirst'));
      return;
    }

    if (!selectedDevice || !selectedBoardVersion) {
      setStatus(t('status.selectBoth'));
      return;
    }

    setIsFlashing(true);
    setStatus(t('status.preparing'));

    try {
      // Stop logging if it's active
      if (isLogging) {
        await stopSerialLogging();
      }

      // Close the current connection
      if (serialPortRef.current.readable) {
        await serialPortRef.current.close();
      }

      // Create transport and ESPLoader for flashing
      const transport = new Transport(serialPortRef.current);
      const loader = new ESPLoader({
        transport,
        baudrate: 115200,
        romBaudrate: 115200,
        terminal: {
          clean() {},
          writeLine(data: string) {
            // setStatus(data);
          },
          write(data: string) {
            // setStatus(data);
          },
        },
      });

      await loader.main();

      if (!firmware) {
        throw new Error('No firmware available for the selected device and board version');
      }

      // Handle single file flashing for all devices (now including Nerdminer)
      let firmwarePath;
      let flashAddress = 0;
      
      if (selectedDevice === 'Nerdminer') {
        // For Nerdminer, construct the path based on keep configuration setting
        let boardName = selectedBoardVersion;
        const version = selectedFirmware;
        
        // Handle the special case of the original board
        if (boardName === 'NERDMINERV2 ORIGINAL BOARD (TDISPLAY-S3)') {
          boardName = 'NerdminerV2';
        }
        
        if (keepConfiguration) {
          // Use firmware-only file and flash to 0x10000
          firmwarePath = `firmware/nerdminer/${version}/${boardName}_firmware.bin`;
          flashAddress = 0x10000;
        } else {
          // Use factory file and flash to 0x0000
          firmwarePath = `firmware/nerdminer/${version}/${boardName}_factory.bin`;
          flashAddress = 0x0000;
        }
      } else {
        // For other devices, use the regular path
        firmwarePath = firmware.path;
        flashAddress = 0;
      }

      const firmwareResponse = await fetch(firmwarePath);
      if (!firmwareResponse.ok) {
        throw new Error('Failed to load firmware file');
      }

      const firmwareArrayBuffer = await firmwareResponse.arrayBuffer();
      const firmwareUint8Array = new Uint8Array(firmwareArrayBuffer);
      const firmwareBinaryString = Array.from(firmwareUint8Array, (byte) =>
        String.fromCharCode(byte)
      ).join('');

      setStatus(t('status.flashing', { percent: 0 }));

      await loader.writeFlash({
        fileArray: [
          {
            data: firmwareBinaryString,
            address: flashAddress,
          },
        ],
        flashSize: 'keep',
        flashMode: 'keep',
        flashFreq: 'keep',
        eraseAll: false,
        compress: true,
        reportProgress: (fileIndex, written, total) => {
          const percent = Math.round((written / total) * 100);
          if (percent == 100) {
            setStatus(t('status.completed'));
          } else {
            setStatus(t('status.flashing', { percent: percent }));
          }
        },
        calculateMD5Hash: () => '',
      });

      setStatus(t('status.completed'));
      await loader.hardReset();

      setStatus(t('status.success'));
    } catch (error) {
      console.error('Flashing failed:', error);
      setStatus(
        `${t('status.flashingFailed')}: ${
          error instanceof Error ? error.message : String(error)
        }. Please try again.`
      );
    } finally {
      setIsFlashing(false);
    }
  };

  const openModal = () => {
    setIsModalOpen(true);
  };

  const selectDevice = (name: string) => {
    setSelectedDevice(name);
    setSelectedBoardVersion('');
    setSelectedFirmware('');
    setIsModalOpen(false);
    
    // Change background for Nerdminer
    if (name === 'Nerdminer') {
      document.body.classList.add('nerdminer-bg');
    } else {
      document.body.classList.remove('nerdminer-bg');
    }
  };

  if (!isChromiumBased) {
    return (
      <div className="container px-4 md:px-6 py-12 text-center">
        <h1 className="text-3xl font-bold tracking-tighter sm:text-4xl md:text-5xl lg:text-6xl/none mb-4">
          {t('errors.browserCompatibility.title')}
        </h1>
        <p className="mx-auto max-w-[700px] text-gray-500 md:text-xl dark:text-gray-400">
          {t('errors.browserCompatibility.description')}
        </p>
      </div>
    );
  }

  return (
    <>
      <Header onOpenPanel={() => setIsPanelOpen(true)} />
      <section className="w-full py-12 md:py-24 lg:py-32 xl:py-48">
        <div className="container px-4 md:px-6">
          <div className="flex flex-col items-center space-y-4 text-center gap-8">
            <div className="space-y-2 mb-14">
              <h1 className="text-3xl font-bold tracking-tighter sm:text-4xl md:text-5xl lg:text-6xl/none">
                {selectedDevice === 'Nerdminer' 
                  ? 'Flash, play and learn with nerdminer'
                  : t('hero.title')
                }
              </h1>
              <p className="mx-auto max-w-[700px] text-gray-500 md:text-xl dark:text-gray-400">
                {t('hero.description')}
              </p>
            </div>
            <div className="flex flex-col justify-between items-center w-3/4 gap-y-20 md:flex-row">
              <div className="flex flex-col justify-center w-52">
                {selectedDevice === '' ? (
                  <RadioReceiver
                    className="h-25 w-25 md:h-29 md:w-29 lg:h-37 lg:w-37 mb-4 m-auto"
                    color="#6B7280"
                    strokeWidth={1}
                  />
                ) : (
                  <img
                    src={devices.find(d => d.name === selectedDevice)?.picture}
                    alt={selectedDevice}
                    className="h-25 w-25 md:h-29 md:w-29 lg:h-37 lg:w-37 mb-4 m-auto object-contain rounded-lg"
                  />
                )}
                <Button onClick={openModal} disabled={isConnecting || isFlashing}>
                  {selectedDevice === '' ? t('hero.selectDevice') : selectedDevice}
                </Button>
              </div>
              <div className="flex flex-col justify-center w-52">
                <Cpu
                  className="h-25 w-25 md:h-29 md:w-29 lg:h-37 lg:w-37 mb-4 m-auto"
                  color="#6B7280"
                  strokeWidth={1}
                />
                <Selector
                  placeholder={t('hero.selectBoard')}
                  values={device.boards.map((b) => b.name)}
                  onValueChange={(value) => {
                    setSelectedBoardVersion(value);
                    setSelectedFirmware('');
                  }}
                  disabled={isConnecting || isFlashing || selectedDevice === ''}
                />
              </div>
              <div className="flex flex-col justify-center w-52">
                <GitCompareIcon
                  className="h-25 w-25 md:h-29 md:w-29 lg:h-37 lg:w-37 mb-4 m-auto"
                  color="#6B7280"
                  strokeWidth={1}
                />
                <Selector
                  placeholder={t('hero.selectFirmware')}
                  values={board.supported_firmware.map((f) => f.version)}
                  onValueChange={setSelectedFirmware}
                  disabled={isConnecting || isFlashing || selectedBoardVersion === ''}
                />
              </div>
            </div>
            
            {/* Keep Configuration Checkbox (only for Nerdminer) */}
            {selectedDevice === 'Nerdminer' && (
              <div className="flex items-center space-x-2 justify-center">
                <input
                  type="checkbox"
                  id="keepConfiguration"
                  checked={keepConfiguration}
                  onChange={(e) => setKeepConfiguration(e.target.checked)}
                  className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 dark:focus:ring-blue-600 dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600"
                />
                <label htmlFor="keepConfiguration" className="text-sm font-medium text-gray-900 dark:text-gray-300">
                  {t('hero.keepConfiguration')}
                </label>
              </div>
            )}
            
            <div className="w-full max-w-sm space-y-4">
              <Button
                className="w-full"
                onClick={isConnected ? handleDisconnect : handleConnect}
                disabled={isConnecting || isFlashing || !selectedDevice || !selectedBoardVersion || !selectedFirmware}
              >
                {isConnected ? t('hero.disconnect') : t('hero.connect')}
                <Usb className="ml-2 h-4 w-4" />
              </Button>
              <Button
                className="w-full mb-4"
                onClick={handleStartFlashing}
                disabled={
                  !selectedDevice ||
                  !selectedBoardVersion ||
                  !selectedFirmware ||
                  isConnecting ||
                  isFlashing ||
                  !isConnected
                }
              >
                {isFlashing ? t('hero.flashing') : t('hero.startFlashing')}
                <Zap className="ml-2 h-4 w-4" />
              </Button>
              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  onClick={isLogging ? stopSerialLogging : startSerialLogging}
                  disabled={!isConnected || isFlashing}
                >
                  {isLogging ? t('hero.stopLogging') : t('hero.startLogging')}
                  <ComputerIcon className="ml-2 h-4 w-4" />
                </Button>
                <Button className="flex-1" onClick={downloadLogs} disabled={!logsRef.current}>
                  {t('hero.downloadLogs')}
                  <Download className="ml-2 h-4 w-4" />
                </Button>
              </div>
              <p className="mx-auto max-w-[400px] text-gray-500 md:text-m dark:text-gray-400">
                {t('hero.loggingDescription')}
              </p>
              {status && <p className="mt-2 text-sm font-medium">{status}</p>}
            </div>
            {isLogging && (
              <div
                ref={terminalContainerRef}
                className="w-full max-w-4xl h-[400px] bg-black rounded-lg overflow-hidden mt-8 border border-gray-700 text-left"
              />
            )}
          </div>
        </div>
      </section>
      <InstructionPanel isOpen={isPanelOpen} onClose={() => setIsPanelOpen(false)} />
      <DeviceModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        selectDevice={(name: string) => selectDevice(name)}
      />
    </>
  );
}
