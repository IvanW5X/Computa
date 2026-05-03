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

async function classifyAndRoute(userMessage) {
  console.log(`[Router] Message: "${userMessage}"`);

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

  if (classification.route !== 'local' && classification.route !== 'escalate') {
    classification.route = (classification.score || 0) >= 2 ? 'escalate' : 'local';
  }

  console.log(`[Classifier] Score: ${classification.score} | Route: ${classification.route}`);
  return classification;
}

module.exports = { classifyAndRoute, runPythonSkill, getPythonPath };
