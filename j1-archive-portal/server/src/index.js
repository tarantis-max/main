require('dotenv').config();
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');

const authRouter    = require('./auth/authRouter');
const studentsRouter  = require('./routes/students');
const academicRouter  = require('./routes/academic');
const transcriptRouter = require('./routes/transcript');
const degreesRouter  = require('./routes/degrees');
const adhocRouter   = require('./routes/adhoc');

const app = express();
const PORT = process.env.PORT || 3001;

app.use(helmet());
app.use(cors({ origin: process.env.CLIENT_ORIGIN || 'http://localhost:5173', credentials: true }));
app.use(express.json());

const loginLimiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 10, standardHeaders: true });

app.use('/api/auth',    loginLimiter, authRouter);
app.use('/api/students', studentsRouter);
app.use('/api/students', academicRouter);
app.use('/api/students', transcriptRouter);
app.use('/api/students', degreesRouter);
app.use('/api/adhoc',   adhocRouter);

app.use((err, req, res, _next) => {
  const status = err.status || 500;
  if (status >= 500) console.error(err);
  res.status(status).json({ error: err.message || 'Internal server error' });
});

app.listen(PORT, () => console.log(`J1 Archive API listening on :${PORT}`));
