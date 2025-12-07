import subprocess
import sys
import os
import argparse

def deploy(host, user="root", dest="/opt/cdn_waf", key_path=None):
    """Deploy edge node code via SCP/SSH"""
    print(f"[*] Deploying to {user}@{host}:{dest}...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src_file = os.path.join(base_dir, "edge_config_updater.py")
    req_file = os.path.join(base_dir, "requirements.txt")
    
    if not os.path.exists(src_file):
        print(f"[!] Error: {src_file} not found!")
        return False

    ssh_opts = "-o StrictHostKeyChecking=no"
    if key_path:
        ssh_opts += f" -i {key_path}"

    # 1. Copy files
    files = f"{src_file} {req_file}"
    cmd_copy = f"scp {ssh_opts} {files} {user}@{host}:{dest}/"
    
    print(f"[*] Copying files...")
    if subprocess.run(cmd_copy, shell=True).returncode != 0:
        print("[!] Failed to copy files via SCP.")
        return False

    # 2. Update dependencies & Restart service
    # We assume venv is at {dest}/venv as per setup.sh
    remote_cmds = [
        f"cd {dest}",
        f"./venv/bin/pip install -r requirements.txt",
        "systemctl restart cdn-waf-agent",
        "systemctl status cdn-waf-agent --no-pager"
    ]
    
    remote_cmd_str = " && ".join(remote_cmds)
    cmd_exec = f"ssh {ssh_opts} {user}@{host} '{remote_cmd_str}'"
    
    print(f"[*] Updating dependencies and restarting service...")
    if subprocess.run(cmd_exec, shell=True).returncode != 0:
        print("[!] Failed to execute remote commands.")
        return False
        
    print("[+] Deployment successful!")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Edge Node Agent")
    parser.add_argument("host", help="Edge node IP address or hostname")
    parser.add_argument("--user", default="root", help="SSH user (default: root)")
    parser.add_argument("--dest", default="/opt/cdn_waf", help="Destination directory")
    parser.add_argument("--key", help="Path to SSH private key")
    
    args = parser.parse_args()
    
    deploy(args.host, args.user, args.dest, args.key)
