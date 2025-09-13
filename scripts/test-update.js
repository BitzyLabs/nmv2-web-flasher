#!/usr/bin/env node

// Test script to run the firmware updater locally
const { spawn } = require('child_process');
const path = require('path');

console.log('🧪 Testing firmware updater...');

// Change to project root directory
process.chdir(path.join(__dirname, '..'));

// Run the update script
const updateProcess = spawn('node', ['scripts/update-firmware.js'], {
  stdio: 'inherit',
  env: { ...process.env, NODE_ENV: 'development' }
});

updateProcess.on('close', (code) => {
  console.log(`\n🏁 Update process finished with code ${code}`);
  
  if (code === 0) {
    console.log('✅ Test completed successfully!');
  } else {
    console.log('❌ Test failed!');
    process.exit(code);
  }
});