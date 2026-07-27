import { readFileSync } from 'fs';
import { join } from 'path';

const requiredVars = ['VITE_BASE_URL', 'VITE_BASE_PROTOCOL'];

console.log('🔍 Validating client environment variables...');

// Load .env file manually (Node.js doesn't auto-load like Vite does)
try {
  const envFile = readFileSync('.env', 'utf8');
  envFile.split('\n').forEach(line => {
    const [key, value] = line.split('=');
    if (key && value) {
      process.env[key.trim()] = value.trim();
    }
  });
} catch (err) {
  // .env file doesn't exist, which is fine - we'll catch missing vars below
}

let hasErrors = false;

requiredVars.forEach(varName => {
  if (!process.env[varName]) {
    console.error(`❌ Missing required environment variable: ${varName}`);
    hasErrors = true;
  } else {
    console.log(`✅ ${varName}=${process.env[varName]}`);
  }
});

if (hasErrors) {
  console.error('\n💡 Create a .env file in the client/ directory with:');
  console.error('VITE_BASE_URL=localhost:8000');
  console.error('VITE_BASE_PROTOCOL=http');
  console.error('\nFor more details, see the setup instructions in the README.');
  process.exit(1);
}

console.log('✅ All required environment variables are present\n');