#!/usr/bin/env python3
import subprocess
import os
import json
import logging
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("omni.system")

class SystemFixer:
    """
    Handles system-level maintenance and fixes for Ubuntu.
    """
    
    def run_cmd(self, cmd: str, shell=True) -> Tuple[int, str, str]:
        """Runs a shell command and returns (returncode, stdout, stderr)."""
        try:
            proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate()
            return proc.returncode, stdout.strip(), stderr.strip()
        except Exception as e:
            logger.error(f"Error running command '{cmd}': {e}")
            return -1, "", str(e)

    def check_disk_space(self, threshold_percent=90) -> Dict:
        """Checks disk usage and cleans up if critical."""
        code, out, err = self.run_cmd("df -h /")
        if code != 0:
            return {"status": "error", "message": f"Failed to check disk: {err}"}
        
        # Parse output (Filesystem Size Used Avail Use% Mounted on)
        lines = out.splitlines()
        if len(lines) < 2:
            return {"status": "error", "message": "Unexpected df output"}
            
        try:
            parts = lines[1].split()
            use_percent_str = parts[4].replace('%', '')
            use_percent = int(use_percent_str)
            
            result = {
                "status": "ok",
                "usage_percent": use_percent,
                "free": parts[3],
                "message": f"Disk usage: {use_percent}%"
            }
            
            if use_percent > threshold_percent:
                result["status"] = "warning"
                result["message"] += " - CRITICAL USAGE"
                # Auto-fix: Clean apt cache and logs
                logger.warning("Disk usage critical. Attempting cleanup...")
                self.run_cmd("sudo apt-get clean")
                self.run_cmd("journalctl --vacuum-time=3d")
                # Re-check
                code, out, _ = self.run_cmd("df -h /")
                parts = out.splitlines()[1].split()
                new_use = int(parts[4].replace('%', ''))
                result["new_usage_percent"] = new_use
                result["actions_taken"] = ["apt-get clean", "journalctl vacuum"]
                
            return result
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse df output: {e}"}

    def check_memory(self) -> Dict:
        """Checks memory usage."""
        code, out, _ = self.run_cmd("free -m")
        if code != 0:
            return {"status": "error"}
            
        try:
            lines = out.splitlines()
            mem_line = lines[1].split()
            total = int(mem_line[1])
            used = int(mem_line[2])
            available = int(mem_line[6]) # accurate available memory
            percent = (used / total) * 100
            
            return {
                "status": "ok", 
                "total_mb": total,
                "used_mb": used,
                "available_mb": available,
                "percent": percent,
                "message": f"Memory: {used}/{total}MB ({percent:.1f}%)"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def check_and_fix_pm2(self) -> Dict:
        """Checks PM2 processes and restarts any that are stopped/errored."""
        code, out, err = self.run_cmd("pm2 jlist")
        if code != 0:
            return {"status": "error", "message": "PM2 not found or error"}
            
        try:
            processes = json.loads(out)
            restarted = []
            
            for p in processes:
                name = p.get('name')
                status = p.get('pm2_env', {}).get('status')
                
                if status in ['stopped', 'errored']:
                    logger.warning(f"PM2 process '{name}' is {status}. Restarting...")
                    self.run_cmd(f"pm2 restart {name}")
                    restarted.append(name)
            
            return {
                "status": "ok",
                "total_processes": len(processes),
                "restarted": restarted,
                "message": f"PM2 check complete. Restarted: {restarted}" if restarted else "All PM2 processes healthy."
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse PM2 output: {e}"}

    def update_system(self) -> Dict:
        """Updates system packages (apt-get)."""
        logger.info("Checking for system updates...")
        # Update lists
        self.run_cmd("sudo apt-get update")
        
        # Check upgradable
        code, out, _ = self.run_cmd("apt list --upgradable")
        lines = out.splitlines()
        # First line is usually "Listing..."
        upgradable_count = max(0, len(lines) - 1)
        
        actions = []
        if upgradable_count > 0:
            logger.info(f"Found {upgradable_count} updates. Upgrading...")
            # Non-interactive upgrade
            self.run_cmd("sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y")
            actions.append("upgrade")
            self.run_cmd("sudo apt-get autoremove -y")
            actions.append("autoremove")
            
        return {
            "status": "ok",
            "updates_found": upgradable_count,
            "actions": actions,
            "message": f"System updated. {upgradable_count} packages upgraded." if actions else "System up to date."
        }
    
    def check_git_repos(self, paths: List[str]) -> Dict:
        """Checks status of git repositories."""
        results = {}
        for path in paths:
            if not os.path.exists(path):
                continue
                
            code, out, _ = self.run_cmd(f"cd {path} && git status --porcelain")
            has_changes = len(out.strip()) > 0
            
            code, branch, _ = self.run_cmd(f"cd {path} && git rev-parse --abbrev-ref HEAD")
            
            # Auto-pull if clean
            pull_status = "skipped"
            if not has_changes:
                code, pull_out, _ = self.run_cmd(f"cd {path} && git pull")
                pull_status = "pulled" if "Already up to date" not in pull_out else "up_to_date"
            
            results[os.path.basename(path)] = {
                "branch": branch,
                "has_changes": has_changes,
                "pull_status": pull_status
            }
            
        return {"status": "ok", "repos": results}

if __name__ == "__main__":
    fixer = SystemFixer()
    print(json.dumps(fixer.check_disk_space(), indent=2))
    print(json.dumps(fixer.check_memory(), indent=2))
    print(json.dumps(fixer.check_and_fix_pm2(), indent=2))
    # print(json.dumps(fixer.update_system(), indent=2)) # Commented out to avoid long run
