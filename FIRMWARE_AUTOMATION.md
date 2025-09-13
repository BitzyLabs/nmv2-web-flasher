# Firmware Automation

This document explains how the automated firmware update system works for the Bitronics Web Flasher.

## Overview

The system automatically checks for new firmware releases from GitHub repositories and updates the web flasher with the latest versions. Currently configured for:

- **NerdQAxe**: Monitors `shufps/ESP-Miner-NerdQAxePlus` repository

## Files Structure

```
.github/workflows/update-firmware.yml    # GitHub Actions workflow
scripts/update-firmware.js               # Main update script
scripts/test-update.js                   # Local testing script
scripts/package.json                     # Dependencies for scripts
public/firmware/nerdqaxe/               # NerdQAxe firmware storage
```

## How It Works

### 1. GitHub Actions Workflow (.github/workflows/update-firmware.yml)

- **Runs daily at 2 AM UTC**
- Can be triggered manually via GitHub Actions
- Installs dependencies and runs the update script
- Automatically commits and pushes changes if new firmware is found

### 2. Update Script (scripts/update-firmware.js)

The script performs these steps:

1. **Check Latest Release**: Uses GitHub API to get the latest release
2. **Compare Versions**: Uses semantic versioning to check if update is needed  
3. **Download Firmware**: Downloads the factory firmware binary
4. **Create Structure**: 
   - Creates version directory (e.g., `v1.2.3/`)
   - Downloads firmware as `NerdQAxe_factory.bin`
   - Creates `NerdQAxe_firmware.bin` (copy for now)
   - Generates `manifest.json`
5. **Update Configuration**: Updates `src/components/firmware_data.json`

### 3. Repository Configuration

Each repository is configured in `FIRMWARE_REPOS` object:

```javascript
nerdqaxe: {
  owner: 'shufps',                          // GitHub owner
  repo: 'ESP-Miner-NerdQAxePlus',          // Repository name
  assetPattern: 'esp-miner-factory-NerdQAxe++', // Asset name pattern
  firmwarePath: 'public/firmware/nerdqaxe', // Local storage path
  deviceName: 'NerdQaxe',                   // Device name in UI
  boardName: '++ (4.8THs)'                 // Specific board to update
}
```

## Testing Locally

To test the automation locally:

```bash
cd scripts
npm install
npm test
```

Or run directly:
```bash
node scripts/update-firmware.js
```

## Adding New Repositories

To add a new repository for automation:

1. **Add configuration** in `scripts/update-firmware.js`:
```javascript
mynewdevice: {
  owner: 'github-owner',
  repo: 'repository-name',
  assetPattern: 'firmware-file-pattern',
  firmwarePath: 'public/firmware/mynewdevice',
  deviceName: 'MyNewDevice',
  boardName: 'Board Name' // optional
}
```

2. **Create directory structure**:
```bash
mkdir -p public/firmware/mynewdevice
```

3. **Add device to firmware_data.json** if it doesn't exist:
```json
{
  "name": "MyNewDevice",
  "picture": "pictures/mynewdevice.png",
  "boards": [{
    "name": "Board Name",
    "supported_firmware": []
  }]
}
```

## Directory Structure Generated

For each new version found, the script creates:

```
public/firmware/nerdqaxe/v1.2.3/
├── NerdQaxe_factory.bin      # Full factory firmware
├── NerdQaxe_firmware.bin     # Firmware-only version
└── manifest.json             # Version metadata
```

## Error Handling

The script includes comprehensive error handling:
- Network timeouts (30 seconds)
- Missing assets (warns but continues)
- File system errors
- API rate limits
- Invalid version formats

## Security

- Uses read-only GitHub API (no authentication required for public repos)
- Only downloads from trusted repositories configured in the script
- Validates file patterns before download
- Creates proper directory structure to prevent path traversal

## Monitoring

Check the GitHub Actions tab for:
- Daily run results
- Error logs
- Manual trigger history

The script outputs detailed logs showing:
- Current vs latest versions
- Download progress  
- File creation status
- Update results