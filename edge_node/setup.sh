#!/bin/bash
# Edge Node Setup Script
# Supports Ubuntu/Debian and CentOS/RHEL

set -e

# Detect OS
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        DIST=$ID
        VERSION=$VERSION_ID
    else
        echo "Unknown OS"
        exit 1
    fi
}

install_deps() {
    detect_os
    echo "Installing system dependencies for $OS..."
    
    if [[ "$DIST" == "ubuntu" ]] || [[ "$DIST" == "debian" ]]; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y curl git build-essential python3-dev python3-venv python3-pip
    elif [[ "$DIST" == "centos" ]] || [[ "$DIST" == "rhel" ]] || [[ "$DIST" == "fedora" ]]; then
        yum update -y
        yum install -y curl git gcc python3-devel python3-pip
    else
        echo "Unsupported distribution: $DIST"
        exit 1
    fi
}

install_nginx() {
    detect_os
    echo "Installing Nginx/OpenResty for $OS..."
    
    if [[ "$DIST" == "ubuntu" ]] || [[ "$DIST" == "debian" ]]; then
        # Try to install OpenResty first, fallback to Nginx
        if ! command -v openresty &> /dev/null; then
            echo "Installing OpenResty..."
            apt-get -y install wget gnupg
            wget -qO - https://openresty.org/package/pubkey.gpg | apt-key add -
            add-apt-repository -y "deb http://openresty.org/package/ubuntu $(lsb_release -sc) main" || true
            apt-get update
            apt-get install -y openresty || apt-get install -y nginx
        fi
    elif [[ "$DIST" == "centos" ]] || [[ "$DIST" == "rhel" ]]; then
        yum install -y epel-release
        yum install -y nginx
    else
        echo "Unsupported distribution: $DIST"
        exit 1
    fi
    
    # Enable and start
    if systemctl list-unit-files | grep -q openresty; then
        systemctl enable openresty
        systemctl start openresty
    else
        systemctl enable nginx
        systemctl start nginx
    fi
}

install_certbot() {
    detect_os
    echo "Installing Certbot..."
    
    if [[ "$DIST" == "ubuntu" ]] || [[ "$DIST" == "debian" ]]; then
        apt-get update
        apt-get install -y certbot python3-certbot-nginx
    elif [[ "$DIST" == "centos" ]] || [[ "$DIST" == "rhel" ]]; then
        yum install -y certbot python3-certbot-nginx
    else
        echo "Unsupported distribution: $DIST"
        exit 1
    fi
}

install_python_env() {
    echo "Setting up Python environment..."
    mkdir -p /opt/cdn_waf
    cd /opt/cdn_waf
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    if [ -f "requirements.txt" ]; then
        ./venv/bin/pip install -r requirements.txt
    else
        echo "requirements.txt not found, skipping pip install"
    fi
}

install_agent_service() {
    echo "Installing Agent Service..."
    
    # Create systemd service
    cat <<EOF > /etc/systemd/system/cdn-waf-agent.service
[Unit]
Description=CDN WAF Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/cdn_waf
ExecStart=/opt/cdn_waf/venv/bin/python /opt/cdn_waf/edge_config_updater.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable cdn-waf-agent
    systemctl restart cdn-waf-agent
}

# Main dispatcher
case "$1" in
    install_deps)
        install_deps
        ;;
    install_nginx)
        install_nginx
        ;;
    install_certbot)
        install_certbot
        ;;
    install_python)
        install_python_env
        ;;
    install_agent_service)
        install_agent_service
        ;;
    *)
        echo "Usage: $0 {install_deps|install_nginx|install_certbot|install_python|install_agent_service}"
        exit 1
        ;;
esac
