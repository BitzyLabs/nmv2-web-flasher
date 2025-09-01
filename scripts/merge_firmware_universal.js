#!/usr/bin/env node
/**
 * Script to merge ESP32 firmware files into factory.bin files for v1.7.0
 */

const fs = require('fs');
const path = require('path');

function createFactoryBin(boardName, basePath, outputPath) {
    console.log(`\nProcessing ${boardName}...`);
    
    // Determine ESP type and addresses based on board name (more precise detection)
    const boardLower = boardName.toLowerCase();
    const isS3 = boardLower.includes('s3');
    const isC3 = boardLower.includes('c3');  
    const isS2 = boardLower.includes('s2');
    const isClassicESP32 = !isS3 && !isC3 && !isS2;
    
    let addresses;
    let espType;
    
    if (isC3) {
        // ESP32-C3: Bootloader at 0x0000
        espType = 'ESP32-C3';
        addresses = {
            bootloader: 0x0000,
            partitions: 0x8000,
            firmware: 0x10000
        };
    } else if (isS2) {
        // ESP32-S2: Bootloader at 0x1000 
        espType = 'ESP32-S2';
        addresses = {
            bootloader: 0x1000,
            partitions: 0x8000,
            firmware: 0x10000
        };
    } else if (isS3) {
        // ESP32-S3: Bootloader at 0x0000
        espType = 'ESP32-S3';
        addresses = {
            bootloader: 0x0000,
            partitions: 0x8000,
            firmware: 0x10000
        };
    } else {
        // ESP32 Classic: Bootloader at 0x1000
        espType = 'ESP32';
        addresses = {
            bootloader: 0x1000,
            partitions: 0x8000,
            firmware: 0x10000
        };
    }
    
    console.log(`ESP type: ${espType} (bootloader at 0x${addresses.bootloader.toString(16).padStart(4, '0')})`);
    
    // File paths
    const files = {
        bootloader: path.join(basePath, `${boardName}_bootloader.bin`),
        partitions: path.join(basePath, `${boardName}_partitions.bin`),
        firmware: path.join(basePath, `${boardName}_firmware.bin`)
    };
    
    // Create merged binary - start with 4MB of 0xFF (erased flash)
    const mergedSize = 0x400000; // 4MB for newer boards
    const mergedData = Buffer.alloc(mergedSize, 0xFF);
    
    let maxAddress = 0;
    
    // Merge files at their respective addresses
    for (const [fileType, filePath] of Object.entries(files)) {
        if (fs.existsSync(filePath)) {
            const address = addresses[fileType];
            const data = fs.readFileSync(filePath);
            
            console.log(`Adding ${fileType} at 0x${address.toString(16).padStart(6, '0')}: ${data.length} bytes`);
            
            if (address + data.length <= mergedSize) {
                data.copy(mergedData, address);
                maxAddress = Math.max(maxAddress, address + data.length);
            } else {
                console.log(`Warning: ${fileType} too large, truncating`);
                const remaining = mergedSize - address;
                data.copy(mergedData, address, 0, remaining);
                maxAddress = mergedSize;
            }
        } else {
            console.log(`Warning: ${fileType} file not found: ${filePath}`);
        }
    }
    
    // Find actual end of data (round up to 4K boundary)
    const actualEnd = Math.ceil(maxAddress / 4096) * 4096;
    
    // Write factory file
    const factoryPath = path.join(outputPath, `${boardName}_factory.bin`);
    fs.writeFileSync(factoryPath, mergedData.slice(0, actualEnd));
    
    console.log(`Created: ${factoryPath} (${actualEnd} bytes)`);
    return factoryPath;
}

function copyFirmwareFile(boardName, basePath, outputPath) {
    const src = path.join(basePath, `${boardName}_firmware.bin`);
    const dst = path.join(outputPath, `${boardName}_firmware.bin`);
    
    if (fs.existsSync(src)) {
        console.log(`Firmware file ready: ${dst}`);
    } else {
        console.log(`Warning: Firmware file not found: ${src}`);
    }
}

function main() {
    const basePath = path.join(__dirname, 'public', 'firmware', 'nerdminer', 'v1.7.0');
    
    // Get all unique board names by scanning for _bootloader.bin files
    const files = fs.readdirSync(basePath);
    const boards = files
        .filter(file => file.endsWith('_bootloader.bin'))
        .map(file => file.replace('_bootloader.bin', ''))
        .sort();
    
    console.log(`Found ${boards.length} boards for v1.7.0:`);
    console.log(boards.join(', '));
    console.log('\nMerging ESP32 firmware files...');
    
    for (const board of boards) {
        try {
            createFactoryBin(board, basePath, basePath);
            copyFirmwareFile(board, basePath, basePath);
        } catch (error) {
            console.error(`Error processing ${board}:`, error.message);
        }
    }
    
    console.log('\nMerging complete!');
}

main();