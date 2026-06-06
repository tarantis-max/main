const express = require('express');
const bcrypt  = require('bcryptjs');
const jwt     = require('jsonwebtoken');
const fs      = require('fs');
const path    = require('path');

const router    = express.Router();
const USERS_FILE = path.join(__dirname, '../../config/users.json');

router.post('/login', async (req, res, next) => {
  try {
    const { username, password } = req.body;
    if (!username || !password) {
      return res.status(400).json({ error: 'Username and password required' });
    }

    let users;
    try {
      users = JSON.parse(fs.readFileSync(USERS_FILE, 'utf8'));
    } catch {
      return res.status(500).json({ error: 'User store unavailable — run npm run hash-user to create it' });
    }

    const user = users.find(u => u.username === username.toLowerCase().trim());
    if (!user || !(await bcrypt.compare(password, user.hash))) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const token = jwt.sign(
      { sub: user.username, role: user.role, name: user.name },
      process.env.JWT_SECRET,
      { expiresIn: '8h' }
    );

    res.json({ token, role: user.role, name: user.name });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
