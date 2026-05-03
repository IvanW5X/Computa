// ============================================================
// src/routing.js
// ============================================================
// Role: Tier 2 — Orchestration (router + Python child-process
//        bridge)
// Purpose: Spawns Python skills as child processes, passing the
//          arguments as a JSON string on sys.argv[1] and reading
//          the response from stdout. classifyAndRoute() invokes
//          skills/classify_task.py and decides whether to handle
//          the message locally or escalate to NIM.
// Calls:   skills/classify_task.py (via execFile);
//          downstream callers use runPythonSkill() to invoke
//          skills/summarize_local.py and skills/escalate_to_nim.py.
// Used by: src/discord-handler.js.
// ============================================================

const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');

function getPythonPath() {
  const root = path.join(__dirname, '..');
  const venvPython =
    process.platform === 'win32'
      ? path.join(root, 'venv', 'Scripts', 'python.exe')
      : path.join(root, 'venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  return process.platform === 'win32' ? 'python' : 'python3';
}

const PYTHON = getPythonPath();
const SKILLS_DIR = path.join(__dirname, '..', 'skills');

function runPythonSkill(scriptName, args) {
  const scriptPath = path.join(SKILLS_DIR, scriptName);
  const payload = JSON.stringify(args || {});

  return new Promise((resolve, reject) => {
    const child = execFile(
      PYTHON,
      [scriptPath, payload],
      {
        maxBuffer: 32 * 1024 * 1024,
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
        windowsHide: true,
      },
      (err, stdout, stderr) => {
        if (stderr && stderr.trim()) {
          stderr
            .split(/\r?\n/)
            .filter(Boolean)
            .forEach((line) => console.error(`[skill:${scriptName}] ${line}`));
        }
        if (err) {
          err.stdout = stdout;
          return reject(err);
        }
        resolve((stdout || '').trim());
      }
    );

    child.on('error', reject);
  });
}

const SHORT_MESSAGE_CHAR_LIMIT = 80;
const TRIVIAL_PATTERNS = [
  /^(hi|hey|hello|yo|sup|hola|howdy)\b/i,
  /^(thanks|thank you|thx|ty|cool|nice|great|ok|okay|got it)\b/i,
  /^what\s+(is|are|does|do|was|were)\s+\S{1,40}\??$/i,
  /^(define|explain)\s+\S{1,30}\??$/i,
  /^(who|when|where)\s+(is|are|was|were)\s+\S{1,40}\??$/i,
  /^what\s+(is|are)\s+\d+\s*[\+\-\*x×\/÷]\s*\d+\??$/i,
  /^say\s+(hi|hello)/i,
];

function shouldShortCircuitToLocal(message) {
  const text = String(message || '').trim();
  if (!text) return false;
  if (text.length <= SHORT_MESSAGE_CHAR_LIMIT && TRIVIAL_PATTERNS.some((re) => re.test(text))) {
    return true;
  }
  return false;
}

async function classifyAndRoute(userMessage) {
  console.log(`[Router] Message: "${userMessage}"`);

  if (shouldShortCircuitToLocal(userMessage)) {
    console.log('[Router] Short trivial message — bypassing classifier.');
    const classification = {
      score: 0,
      route: 'local',
      triggered_criteria: ['PREFILTER_TRIVIAL'],
      summary: String(userMessage).slice(0, 100),
      complexity_reason: 'Pre-filter matched a trivial message pattern; classifier skipped.',
    };
    console.log(`[Classifier] Score: ${classification.score} | Route: ${classification.route}`);
    return classification;
  }

  let classification;
  try {
    const stdout = await runPythonSkill('classify_task.py', { message: userMessage });
    classification = JSON.parse(stdout);
  } catch (e) {
    console.error(`[Router] Classifier failed: ${e.message}`);
    classification = {
      score: 3,
      route: 'escalate',
      triggered_criteria: ['ROUTER_ERROR'],
      summary: String(userMessage).slice(0, 100),
      complexity_reason: 'Router exception; defaulting to escalate.',
    };
  }

  const score = Number(classification.score) || 0;
  if (classification.route !== 'local' && classification.route !== 'escalate') {
    classification.route = score >= 5 ? 'escalate' : 'local';
  } else if (classification.route === 'escalate' && score < 5) {
    classification.route = 'local';
  } else if (classification.route === 'local' && score >= 5) {
    classification.route = 'escalate';
  }

  console.log(`[Classifier] Score: ${classification.score} | Route: ${classification.route}`);
  return classification;
}

module.exports = { classifyAndRoute, runPythonSkill, getPythonPath };
