import os from 'node:os';

const port = Number.parseInt(process.env.PORT || '8787', 10);
const interfaces = os.networkInterfaces();
const urls = [];

for (const [name, entries = []] of Object.entries(interfaces)) {
  for (const entry of entries) {
    if (entry.family === 'IPv4' && !entry.internal) {
      urls.push({ interface: name, url: `http://${entry.address}:${port}` });
    }
  }
}

if (urls.length === 0) {
  console.log('No LAN IPv4 address found. Check Wi-Fi/Ethernet connection.');
  process.exit(1);
}

console.log('Operation JARVIS Dashboard LAN URLs:');
for (const item of urls) {
  console.log(`- ${item.interface}: ${item.url}`);
}
console.log('\nOpen one of these URLs from another device on the same home Wi-Fi.');
