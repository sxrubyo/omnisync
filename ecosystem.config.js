module.exports = {
  apps : [{
    name: "omni-core",
    script: "python3",
    args: "src/omni_core.py watch --interval 600",
    cwd: __dirname,
    autorestart: true,
    watch: false,
    max_memory_restart: "100M",
    env: {
      OMNI_HOME: __dirname
    }
  }]
};
