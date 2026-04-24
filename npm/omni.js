#!/usr/bin/env node

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const packageRoot = path.resolve(__dirname, "..");
const packageJsonPath = path.join(packageRoot, "package.json");
const packageMetadata = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const packageVersion = String(packageMetadata.version || "").trim();
const effectivePlatform = process.env.OMNI_FORCE_PLATFORM || process.platform;
const omniHome = process.env.OMNI_INSTALL_HOME || path.join(os.homedir(), ".omni");
const entrypoint = path.join(omniHome, "src", "omni_core.py");
const runtimeDir = path.join(omniHome, "runtime");
const sanitizedBaseEnv = (() => {
  const base = { ...process.env };
  for (const key of [
    "OMNI_HOME",
    "OMNI_CONFIG_DIR",
    "OMNI_STATE_DIR",
    "OMNI_BACKUP_DIR",
    "OMNI_BUNDLE_DIR",
    "OMNI_AUTO_BUNDLE_DIR",
    "OMNI_LOG_DIR",
    "OMNI_WATCH_STATE_FILE",
    "OMNI_ENV_FILE",
    "OMNI_AGENT_CONFIG_FILE",
    "OMNI_TASKS_FILE",
    "OMNI_REPOS_FILE",
    "OMNI_SERVERS_FILE",
    "OMNI_MANIFEST_FILE",
  ]) {
    delete base[key];
  }
  return base;
})();

const SKIP_NAMES = new Set([
  ".git",
  ".pytest_cache",
  ".tmp",
  "__pycache__",
  "backups",
  "data",
  "docs",
  "exports",
  "home_snapshot",
  "home_private_snapshot",
  "logs",
  "node_modules",
  "tests",
]);

function ensureDir(target) {
  fs.mkdirSync(target, { recursive: true });
}

function runtimeCandidates() {
  return [
    path.join(runtimeDir, "bin", "python"),
    path.join(runtimeDir, "bin", "python3"),
    path.join(runtimeDir, "Scripts", "python.exe"),
  ];
}

function resolveRuntime() {
  for (const candidate of runtimeCandidates()) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return "";
}

function runAndReturn(command, args, extraEnv) {
  return spawnSync(command, args, {
    stdio: "inherit",
    env: { ...sanitizedBaseEnv, ...extraEnv },
  });
}

function fail(message) {
  console.error(`ERR ${message}`);
  process.exit(1);
}

function status(message) {
  console.error(`[omni] ${message}`);
}

function run(command, args, extraEnv) {
  const result = runAndReturn(command, args, extraEnv);
  if (typeof result.status === "number") {
    process.exit(result.status);
  }
  process.exit(1);
}

function readInstalledVersion() {
  const installedPackage = path.join(omniHome, "package.json");
  if (!fs.existsSync(installedPackage)) {
    return "";
  }
  try {
    const payload = JSON.parse(fs.readFileSync(installedPackage, "utf8"));
    return String(payload.version || "").trim();
  } catch (_err) {
    return "";
  }
}

function syncPackageTree(sourceDir, targetDir) {
  ensureDir(targetDir);
  for (const entry of fs.readdirSync(sourceDir, { withFileTypes: true })) {
    if (SKIP_NAMES.has(entry.name)) {
      continue;
    }
    if (sourceDir === packageRoot && entry.name === ".claude") {
      const handoffDir = path.join(sourceDir, ".claude", "handoffs");
      if (fs.existsSync(handoffDir)) {
        // handled by skipping while recursing below
      }
    }
    const sourcePath = path.join(sourceDir, entry.name);
    const targetPath = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      if (path.relative(packageRoot, sourcePath) === ".claude/handoffs") {
        continue;
      }
      syncPackageTree(sourcePath, targetPath);
      continue;
    }
    ensureDir(path.dirname(targetPath));
    fs.copyFileSync(sourcePath, targetPath);
  }
}

function findSystemPython() {
  const candidates =
    effectivePlatform === "win32"
      ? [
          ["py", ["-3"]],
          ["python", []],
          ["python3", []],
        ]
      : [
          ["python3", []],
          ["python", []],
        ];
  for (const [command, prefixArgs] of candidates) {
    const probe = spawnSync(command, [...prefixArgs, "-c", "import sys; print(sys.executable)"], {
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
      env: sanitizedBaseEnv,
    });
    if (probe.status === 0) {
      return { command, prefixArgs };
    }
  }
  return null;
}

function ensureRuntime() {
  let runtime = resolveRuntime();
  if (runtime) {
    return runtime;
  }
  status("Preparando runtime local de OmniSync. El primer arranque puede tardar 30-60s.");
  ensureDir(omniHome);
  const python = findSystemPython();
  if (!python) {
    fail(
      effectivePlatform === "win32"
        ? "No encontré Python 3. Instala Python 3.10+ y vuelve a ejecutar `omni`."
        : "No encontré python3/python. Instala Python 3.10+ y vuelve a ejecutar `omni`."
    );
  }
  let result = runAndReturn(python.command, [...python.prefixArgs, "-m", "venv", runtimeDir], {});
  if (typeof result.status === "number" && result.status !== 0) {
    process.exit(result.status);
  }
  runtime = resolveRuntime();
  if (!runtime) {
    fail(`No pude crear el runtime aislado en ${runtimeDir}`);
  }
  if (process.env.OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP === "1") {
    return runtime;
  }
  status("Instalando dependencias base de Python para OmniSync...");
  result = runAndReturn(runtime, ["-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], {});
  if (typeof result.status === "number" && result.status !== 0) {
    process.exit(result.status);
  }
  result = runAndReturn(runtime, ["-m", "pip", "install", "--disable-pip-version-check", "rich", "tqdm", "prompt_toolkit", "paramiko"], {});
  if (typeof result.status === "number" && result.status !== 0) {
    process.exit(result.status);
  }
  return runtime;
}

function bootstrapFromPackage() {
  status(`Sincronizando OmniSync ${packageVersion} en ${omniHome}...`);
  syncPackageTree(packageRoot, omniHome);
  const runtime = ensureRuntime();
  status("Preparando workspace base de OmniSync...");
  const init = runAndReturn(runtime, [entrypoint, "init"], {
    OMNI_HOME: omniHome,
    OMNI_BOOTSTRAP_INIT: "1",
    OMNI_AUTO_BACKUP_ON_CHANGE: "0",
  });
  if (typeof init.status === "number" && init.status !== 0) {
    process.exit(init.status);
  }
}

function needsBootstrap() {
  if (!fs.existsSync(entrypoint)) {
    return true;
  }
  if (!resolveRuntime()) {
    return true;
  }
  if (readInstalledVersion() !== packageVersion) {
    return true;
  }
  return process.env.OMNI_FORCE_SYNC === "1";
}

function execInstalledOmni(argv) {
  const runtime = resolveRuntime();
  if (!runtime || !fs.existsSync(entrypoint)) {
    return false;
  }
  run(runtime, [entrypoint, ...argv], { OMNI_HOME: omniHome });
  return true;
}

if (needsBootstrap()) {
  bootstrapFromPackage();
}

if (!execInstalledOmni(process.argv.slice(2))) {
  fail(`No pude iniciar OmniSync desde ${omniHome}`);
}
