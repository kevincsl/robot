#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { spawnSync } = require('child_process');

const ROBOTS_DIR = '.robots';
const DEFAULT_PROVIDER = 'claude';
const DEFAULT_MODEL = 'claude-sonnet-4-6';
const PROVIDER_API_KEY_ENV = {
  codex: 'OPENAI_API_KEY',
  openai: 'OPENAI_API_KEY',
  claude: 'ANTHROPIC_API_KEY',
  gemini: 'GOOGLE_API_KEY'
};

let rl;

const getReadline = () => {
  if (!rl) {
    rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });
  }
  return rl;
};

const closeReadline = () => {
  if (rl) {
    rl.close();
    rl = undefined;
  }
};

const ask = (question) => new Promise(resolve => getReadline().question(question, resolve));

const askYesNo = async (question, defaultValue = false) => {
  const suffix = defaultValue ? ' [Y/n]: ' : ' [y/N]: ';
  const answer = (await ask(`${question}${suffix}`)).trim().toLowerCase();
  if (!answer) return defaultValue;
  return ['y', 'yes', '1', 'true', 'on'].includes(answer);
};

const fail = (message) => {
  console.error(message);
  closeReadline();
  process.exit(1);
};

const robotEnvFile = (robotId) => path.join(ROBOTS_DIR, `${robotId}.env`);

const listRobotFiles = () => {
  if (!fs.existsSync(ROBOTS_DIR)) {
    return [];
  }
  return fs.readdirSync(ROBOTS_DIR).filter(file => file.endsWith('.env')).sort();
};

const ensureRobotsDir = () => {
  if (!fs.existsSync(ROBOTS_DIR)) {
    fs.mkdirSync(ROBOTS_DIR);
  }
};

const requireRobotEnvFile = (robotId) => {
  const envFile = robotEnvFile(robotId);
  if (!fs.existsSync(envFile)) {
    fail(`Error: Robot '${robotId}' not found`);
  }
  return envFile;
};

const toApiUrlKey = (provider) => {
  const normalized = String(provider || '').trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_');
  return `ROBOT_${normalized || 'CUSTOM'}_API_URL`;
};

const buildConfigContent = ({
  robotId,
  tgToken,
  tgUserId,
  apiUrl,
  apiKey,
  provider,
  model,
  codexBypassApprovals,
  codexSkipGitRepoCheck
}) => {
  const lines = [
    `TELEAPP_TOKEN=${tgToken}`,
    `TELEAPP_ALLOWED_USER_ID=${tgUserId}`,
    'TELEAPP_APP=robot.py',
    '',
    `ROBOT_ID=${robotId}`,
    `ROBOT_DEFAULT_PROVIDER=${provider}`,
    `ROBOT_DEFAULT_MODEL=${model}`,
    '',
    'ROBOT_CODEX_CMD=codex',
    'ROBOT_CLAUDE_CMD=claude',
    'ROBOT_GEMINI_CMD=gemini',
    `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX=${codexBypassApprovals ? '1' : '0'}`,
    `ROBOT_CODEX_SKIP_GIT_REPO_CHECK=${codexSkipGitRepoCheck ? '1' : '0'}`
  ];

  if (apiUrl || apiKey) {
    lines.push('', '# API Configuration');
  }
  if (apiUrl) {
    lines.push(`${toApiUrlKey(provider)}=${apiUrl}`);
  }
  if (apiKey) {
    lines.push(`${PROVIDER_API_KEY_ENV[provider] || 'API_KEY'}=${apiKey}`);
  }

  return `${lines.join('\n')}\n`;
};

const showHelp = () => {
  console.log(`
Robot Configuration Tool

Usage: node robotctl.js <command> [robot_id]

Commands:
  add [robot_id]     - Add a new robot (interactive)
  edit <robot_id>    - Edit existing robot config
  delete <robot_id>  - Delete a robot config
  list               - List all configured robots
  show <robot_id>    - Show robot configuration

Examples:
  node robotctl.js add robot1
  node robotctl.js edit robot1
  node robotctl.js delete robot1
  node robotctl.js list
`);
};

const listRobots = () => {
  console.log('Configured robots:\n');
  const files = listRobotFiles();
  if (files.length === 0) {
    console.log('  (none)');
    return;
  }
  files.forEach(file => {
    console.log(`  - ${file.replace('.env', '')}`);
  });
};

const showRobot = (robotId) => {
  const envFile = requireRobotEnvFile(robotId);
  console.log(`Configuration for: ${robotId}\n`);
  console.log(fs.readFileSync(envFile, 'utf8'));
};

const addRobot = async (robotId) => {
  const resolvedRobotId = (robotId || await ask('Robot ID: ')).trim();
  if (!resolvedRobotId) {
    fail('Error: Robot ID cannot be empty');
  }

  ensureRobotsDir();

  const envFile = robotEnvFile(resolvedRobotId);
  if (fs.existsSync(envFile)) {
    fail(`Error: Robot '${resolvedRobotId}' already exists\nUse 'edit' command to modify it`);
  }

  console.log(`Creating robot: ${resolvedRobotId}\n`);

  const tgToken = (await ask('Telegram Bot Token: ')).trim();
  const tgUserId = (await ask('Telegram User ID: ')).trim();
  const apiUrl = (await ask('API URL (optional, press Enter to skip): ')).trim();
  const apiKey = (await ask('API Key (optional, press Enter to skip): ')).trim();
  const provider = ((await ask(`Default Provider [${DEFAULT_PROVIDER}]: `)).trim().toLowerCase()) || DEFAULT_PROVIDER;
  const model = (await ask(`Default Model [${DEFAULT_MODEL}] (or "default"): `)).trim() || DEFAULT_MODEL;
  const codexBypassApprovals = await askYesNo('Enable Codex bypass approvals and sandbox?');
  const codexSkipGitRepoCheck = await askYesNo('Enable Codex skip git repo check?');

  const content = buildConfigContent({
    robotId: resolvedRobotId,
    tgToken,
    tgUserId,
    apiUrl,
    apiKey,
    provider,
    model,
    codexBypassApprovals,
    codexSkipGitRepoCheck
  });

  fs.writeFileSync(envFile, content);
  console.log(`\nRobot '${resolvedRobotId}' created successfully!`);
  console.log(`Config file: ${envFile}`);
};

const editRobot = (robotId) => {
  const envFile = requireRobotEnvFile(robotId);
  const editor = process.env.EDITOR || (process.platform === 'win32' ? 'notepad' : 'nano');
  spawnSync(editor, [envFile], { stdio: 'inherit' });
  console.log(`Robot '${robotId}' updated`);
};

const deleteRobot = async (robotId) => {
  const envFile = requireRobotEnvFile(robotId);
  const confirm = await ask(`Delete robot '${robotId}'? (y/N): `);
  if (confirm.trim().toLowerCase() === 'y') {
    fs.unlinkSync(envFile);
    console.log(`Robot '${robotId}' deleted`);
    return;
  }
  console.log('Cancelled');
};

const requireRobotId = (robotId) => {
  if (!robotId) {
    fail('Error: Specify robot_id');
  }
  return robotId;
};

const main = async () => {
  const [,, command, robotId] = process.argv;

  switch (command) {
    case 'add':
      await addRobot(robotId);
      break;
    case 'edit':
      editRobot(requireRobotId(robotId));
      break;
    case 'delete':
    case 'del':
    case 'rm':
      await deleteRobot(requireRobotId(robotId));
      break;
    case 'list':
    case 'ls':
      listRobots();
      break;
    case 'show':
    case 'cat':
      showRobot(requireRobotId(robotId));
      break;
    default:
      showHelp();
  }
};

main()
  .catch(err => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(closeReadline);
