#!/usr/bin/env python3
"""
Update Edge Node code and configuration from control plane
Usage: sudo python3 force_update_config.py
"""
import sys
import yaml
import asyncio
import httpx
import subprocess
import shutil
from pathlib import Path

async def update_code_and_config():
    """Update code from control plane and apply new configuration"""
    
    # Check if running as root
    import os
    if os.geteuid() != 0:
        print("❌ This script must be run as root (use sudo)")
        sys.exit(1)
    
    # Load config
    config_path = Path("/opt/cdn_waf/config.yaml")
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        sys.exit(1)
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    control_plane_url = config["control_plane"]["url"]
    api_key = config["control_plane"]["api_key"]
    node_id = config["edge_node"]["id"]
    
    print("=" * 80)
    print("Edge Node Update Script")
    print("=" * 80)
    print(f"Control Plane: {control_plane_url}")
    print(f"Node ID: {node_id}")
    print("")
    
    # Download latest edge_config_updater.py
    print("[1/4] Downloading latest edge_config_updater.py from control plane...")
    download_url = f"{control_plane_url}/internal/edge/download/edge_config_updater.py"
    
    headers = {
        "X-Edge-Node-Key": api_key
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(download_url, headers=headers)
            
            if response.status_code == 200:
                code_content = response.text
                print(f"✓ Downloaded edge_config_updater.py ({len(code_content)} bytes)")
                
                # Backup old file
                updater_path = Path("/opt/cdn_waf/edge_config_updater.py")
                if updater_path.exists():
                    backup_path = updater_path.with_suffix('.py.backup')
                    shutil.copy(updater_path, backup_path)
                    print(f"✓ Backed up old version to {backup_path}")
                
                # Write new file
                with open(updater_path, 'w', encoding='utf-8') as f:
                    f.write(code_content)
                print(f"✓ Updated {updater_path}")
            else:
                print(f"❌ Failed to download code: HTTP {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                sys.exit(1)
    except Exception as e:
        print(f"❌ Error downloading code: {e}")
        sys.exit(1)
    
    # Fetch new configuration
    print("")
    print("[2/4] Fetching new configuration from control plane...")
    config_url = f"{control_plane_url}/internal/edge/config?node_id={node_id}&version=0"
    
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(config_url, headers=headers)
            
            if response.status_code == 200:
                config_data = response.json()
                print(f"✓ Received configuration (version: {config_data.get('version', 'unknown')})")
                print(f"  Domains: {len(config_data.get('domains', []))}")
            else:
                print(f"❌ Failed to fetch config: HTTP {response.status_code}")
                sys.exit(1)
    except Exception as e:
        print(f"❌ Error fetching config: {e}")
        sys.exit(1)
    
    # Restart agent
    print("")
    print("[3/4] Restarting Edge Agent...")
    result = subprocess.run(
        ["systemctl", "restart", "cdn-waf-agent"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("✓ Agent restarted")
    else:
        print(f"⚠ Agent restart warning: {result.stderr}")
    
    # Wait for agent to apply config
    print("")
    print("Waiting for agent to apply configuration (5 seconds)...")
    await asyncio.sleep(5)
    
    # Check and reload nginx
    print("")
    print("[4/4] Checking and reloading nginx...")
    result = subprocess.run(
        ["nginx", "-t"],
        capture_output=True,
        text=True
    )
    
    if "syntax is ok" in result.stderr:
        print("✓ Nginx configuration is valid")
        
        # Reload nginx
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        print("✓ Nginx reloaded")
        
        # Show ACME config
        print("")
        print("ACME Challenge Configuration:")
        result = subprocess.run(
            ["grep", "-A3", "acme-challenge", "/etc/nginx/conf.d/cdn.conf"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            lines = result.stdout.split('\n')[:10]
            for line in lines:
                print(f"  {line}")
    else:
        print(f"❌ Nginx configuration error:")
        print(result.stderr)
        sys.exit(1)
    
    print("")
    print("=" * 80)
    print("✓✓✓ Update Complete!")
    print("=" * 80)
    print("✓ Code updated from control plane")
    print("✓ Configuration fetched and applied")
    print("✓ Nginx reloaded")
    print("")

if __name__ == "__main__":
    asyncio.run(update_code_and_config())

