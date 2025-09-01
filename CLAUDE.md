# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

- `npm run dev` - Start development server on http://localhost:3000
- `npm run build` - Build for production (creates static export)
- `npm run start` - Start production server
- `npm run lint` - Run Next.js linting

## Docker Commands

```bash
# Build Docker image
docker build . -f Dockerfile -t bitaxe-web-flasher

# Run container locally
docker run --rm -d -p 3000:3000 bitaxe-web-flasher
```

## Architecture Overview

This is a Next.js 13+ web application for flashing firmware to Bitaxe/ESP32 mining devices. The app uses Web Serial API through the `esptool-js` library to communicate with ESP32 devices directly from the browser.

### Key Architecture Components

**Core Libraries:**
- `esptool-js` - ESP32 flashing functionality via Web Serial API
- `@xterm/xterm` - Terminal interface for flashing progress
- `web-serial-polyfill` - Ensures Web Serial API compatibility

**Project Structure:**
- `src/app/` - Next.js App Router pages and layouts
- `src/components/` - React components including UI components in `ui/` subdirectory
- `src/i18n/` - Internationalization setup with i18next
- `src/lib/` - Shared utilities and type definitions
- `public/firmware/` - Binary firmware files for different device models

**Device Configuration:**
- Device models and firmware versions are defined in `src/components/firmware_data.json`
- Supports multiple device types: Max, Ultra, Supra, Gamma, UltraHex, NerdMiner, NerdNOS
- Each device has multiple board versions with specific firmware files

**Styling & UI:**
- Tailwind CSS with custom configuration supporting dark/light themes
- Radix UI components for accessible UI primitives
- Custom UI components built with `class-variance-authority` and `clsx`

**Production Deployment:**
- Static export configuration in `next.config.js`
- Configured with `basePath` and `assetPrefix` for GitHub Pages deployment
- All images are unoptimized for static hosting compatibility

**Internationalization:**
- i18next with browser language detection
- JSON translation files in `src/i18n/locales/`
- Currently only English is active (other languages commented out in config)

### Key Files to Understand

- `src/components/firmware_data.json` - Central configuration for all supported devices and firmware
- `src/lib/types.ts` - TypeScript type definitions for device models
- `src/components/DeviceModal.tsx` - Core flashing interface component
- `next.config.js` - Build and deployment configuration