#!/usr/bin/env node
// Usage: node scripts/hashUser.js <username> <password> <role: staff|it> <display name>
// Example: node scripts/hashUser.js jgreene secret123 it "Jane Greene"
// Appends the new user to server/config/users.json (creates file if missing).

const bcrypt = require('bcryptjs');
const fs     = require('fs');
const path   = require('path');

const [,, username, password, role, ...nameParts] = process.argv;
const name = nameParts.join(' ');

if (!username || !password || !role) {
  console.error('Usage: node scripts/hashUser.js <username> <password> <staff|it> <display name>');
  process.exit(1);
}
if (!['staff', 'it'].includes(role)) {
  console.error('Role must be "staff" or "it"');
  process.exit(1);
}

const usersFile = path.join(__dirname, '../config/users.json');
let users = [];
try { users = JSON.parse(fs.readFileSync(usersFile, 'utf8')); } catch {}

if (users.find(u => u.username === username.toLowerCase())) {
  console.error(`User "${username}" already exists. Remove them from users.json first.`);
  process.exit(1);
}

const hash = bcrypt.hashSync(password, 12);
users.push({ username: username.toLowerCase(), hash, role, name: name || username });

fs.mkdirSync(path.dirname(usersFile), { recursive: true });
fs.writeFileSync(usersFile, JSON.stringify(users, null, 2));
console.log(`User "${username}" (${role}) added to config/users.json`);
