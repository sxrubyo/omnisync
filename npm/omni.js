#!/usr/bin/env node

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const packageRoot = path.resolve(__dirname, "..");
const omniHome = process.env.OMNI_INSTALL_HOME || path.join(os.homedir(), ".omni");
const entrypoint = path.join(omniHome, "src", "omni_core.py");
const sanitizedBaseEnv = (() => {
  const base = { ...process.env };
  for (const key of [
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

function runtimeCandidates() {
  return [
    path.join(omniHome, "runtime", "bin", "python"),
    path.join(omniHome, "runtime", "bin", "python3"),
    path.join(omniHome, "runtime", "Scripts", "python.exe"),
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

function run(command, args, extraEnv) {
  const result = runAndReturn(command, args, extraEnv);
  if (typeof result.status === "number") {
    process.exit(result.status);
  }
  process.exit(1);
}

function bootstrapWithInstallScript() {
  if (process.platform === "win32") {
    console.error("ERR OmniSync npm bootstrap on Windows is not enabled yet.");
    console.error("Use WSL or the direct install script instead.");
    process.exit(1);
  }

  const installScript = path.join(packageRoot, "install.sh");
  if (!fs.existsSync(installScript)) {
    console.error(`ERR install.sh not found in package root: ${installScript}`);
    process.exit(1);
  }

  const result = runAndReturn("bash", [installScript], {
    OMNI_INSTALL_LOCAL_REPO: packageRoot,
    OMNI_INSTALL_HOME: omniHome,
    OMNI_PREEXISTING_OMNI: "",
  });
  if (typeof result.status === "number" && result.status !== 0) {
    process.exit(result.status);
  }
}

function execInstalledOmni(argv) {
  const runtime = resolveRuntime();
  if (!runtime || !fs.existsSync(entrypoint)) {
    return false;
  }
  run(runtime, [entrypoint, ...argv], { OMNI_HOME: omniHome });
  return true;
}

if (!execInstalledOmni(process.argv.slice(2))) {
  bootstrapWithInstallScript();
  execInstalledOmni(process.argv.slice(2));
}
