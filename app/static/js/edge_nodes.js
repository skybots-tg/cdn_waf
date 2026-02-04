// Edge Nodes Management JavaScript

let currentNodeId = null;
let resetPasswordFlag = false;
let resetSshKeyFlag = false;

// Load edge nodes
async function loadNodes() {
    const status = document.getElementById('filter-status').value;
    const location = document.getElementById('filter-location').value;
    
    let url = '/api/v1/edge-nodes/?';
    if (status) url += `status=${status}&`;
    if (location) url += `location=${location}&`;
    
    try {
        const response = await fetch(url, {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load nodes');
        
        const nodes = await response.json();
        renderNodes(nodes);
    } catch (error) {
        console.error('Error loading nodes:', error);
        showNotification('Failed to load edge nodes', 'error');
    }
}

// Load stats
async function loadStats() {
    try {
        const response = await fetch('/api/v1/edge-nodes/stats', {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load stats');
        
        const stats = await response.json();
        document.getElementById('stat-total').textContent = stats.total_nodes;
        document.getElementById('stat-online').textContent = stats.online_nodes;
        document.getElementById('stat-offline').textContent = stats.offline_nodes;
        document.getElementById('stat-maintenance').textContent = stats.maintenance_nodes;
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Render nodes table
function renderNodes(nodes) {
    const tbody = document.getElementById('nodes-table-body');
    
    if (nodes.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" style="text-align: center; padding: 32px; color: var(--text-muted);">
                    <i class="fas fa-inbox"></i><br>
                    No edge nodes found
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = nodes.map(node => `
        <tr>
            <td>
                <div style="font-weight: 600;">${escapeHtml(node.name)}</div>
                <div style="font-size: 12px; color: var(--text-secondary);">${escapeHtml(node.datacenter || 'N/A')}</div>
            </td>
            <td>
                <span class="badge badge-info">${escapeHtml(node.location_code)}</span>
            </td>
            <td>
                <div style="font-family: monospace; font-size: 13px;">${escapeHtml(node.ip_address)}</div>
                ${node.ipv6_address ? `<div style="font-family: monospace; font-size: 11px; color: var(--text-muted);">${escapeHtml(node.ipv6_address)}</div>` : ''}
            </td>
            <td>${getStatusBadge(node.status)}</td>
            <td>${node.cpu_usage !== null ? `${node.cpu_usage.toFixed(1)}%` : '-'}</td>
            <td>${node.memory_usage !== null ? `${node.memory_usage.toFixed(1)}%` : '-'}</td>
            <td>${node.disk_usage !== null ? `${node.disk_usage.toFixed(1)}%` : '-'}</td>
            <td>
                ${node.last_heartbeat ? formatDateTime(node.last_heartbeat) : 
                    '<span style="color: var(--text-muted);">Never</span>'}
            </td>
            <td>
                <div class="flex gap-1">
                    <a href="/edge-nodes/${node.id}" class="btn btn-icon btn-sm btn-secondary" title="Manage">
                        <i class="fas fa-edit"></i>
                    </a>
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="checkNodeHealth(${node.id})" title="Health Check">
                        <i class="fas fa-heartbeat"></i>
                    </button>
                    <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                            onclick="deleteNode(${node.id})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

// Get status badge HTML
function getStatusBadge(status) {
    const badges = {
        'online': '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Online</span>',
        'offline': '<span class="badge badge-error"><i class="fas fa-times-circle"></i> Offline</span>',
        'maintenance': '<span class="badge badge-warning"><i class="fas fa-wrench"></i> Maintenance</span>',
        'unknown': '<span class="badge" style="background: var(--bg-tertiary); color: var(--text-muted);">Unknown</span>'
    };
    return badges[status] || badges['unknown'];
}

// Show add node modal
function showAddNodeModal() {
    currentNodeId = null;
    resetPasswordFlag = false;
    resetSshKeyFlag = false;
    
    document.getElementById('modal-title').textContent = 'Add Edge Node';
    document.getElementById('node-form').reset();
    document.getElementById('node-id').value = '';
    document.getElementById('node-ssh-port').value = '22';
    document.getElementById('node-enabled').checked = true;
    
    // Reset auth method to password and toggle
    document.querySelector('input[name="auth_method"][value="password"]').checked = true;
    toggleAuthMethod();
    
    // Hide credential status and reset buttons for new nodes
    const passwordStatus = document.getElementById('password-status');
    const keyStatus = document.getElementById('key-status');
    const resetPasswordBtn = document.getElementById('reset-password-btn');
    const resetKeyBtn = document.getElementById('reset-key-btn');
    
    if (passwordStatus) passwordStatus.innerHTML = '';
    if (keyStatus) keyStatus.innerHTML = '';
    if (resetPasswordBtn) resetPasswordBtn.style.display = 'none';
    if (resetKeyBtn) resetKeyBtn.style.display = 'none';
    
    document.getElementById('node-modal').style.display = 'flex';
}

// Edit node
async function editNode(nodeId) {
    try {
        const response = await fetch(`/api/v1/edge-nodes/${nodeId}`, {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load node');
        
        const node = await response.json();
        currentNodeId = nodeId;
        
        // Reset flags for credential reset
        resetPasswordFlag = false;
        resetSshKeyFlag = false;
        
        document.getElementById('modal-title').textContent = 'Edit Edge Node';
        document.getElementById('node-id').value = node.id;
        document.getElementById('node-name').value = node.name;
        document.getElementById('node-ip').value = node.ip_address;
        document.getElementById('node-ipv6').value = node.ipv6_address || '';
        document.getElementById('node-location').value = node.location_code;
        document.getElementById('node-city').value = node.city || '';
        document.getElementById('node-datacenter').value = node.datacenter || '';
        document.getElementById('node-ssh-host').value = node.ssh_host || '';
        document.getElementById('node-ssh-port').value = node.ssh_port || 22;
        document.getElementById('node-ssh-user').value = node.ssh_user || '';
        document.getElementById('node-enabled').checked = node.enabled;
        
        // Clear password and key fields (we don't show stored credentials)
        document.getElementById('node-ssh-password').value = '';
        document.getElementById('node-ssh-key').value = '';
        
        // Handle auth method and show credential status
        if (node.has_ssh_key) {
            document.querySelector('input[name="auth_method"][value="key"]').checked = true;
            toggleAuthMethod();
            updateCredentialStatus('key', true);
        } else if (node.has_ssh_password) {
            document.querySelector('input[name="auth_method"][value="password"]').checked = true;
            toggleAuthMethod();
            updateCredentialStatus('password', true);
        } else {
            document.querySelector('input[name="auth_method"][value="password"]').checked = true;
            toggleAuthMethod();
            updateCredentialStatus('password', false);
        }
        
        document.getElementById('node-modal').style.display = 'flex';
    } catch (error) {
        console.error('Error loading node:', error);
        showNotification('Failed to load node details', 'error');
    }
}

// Update credential status display
function updateCredentialStatus(type, hasCredential) {
    const passwordStatus = document.getElementById('password-status');
    const keyStatus = document.getElementById('key-status');
    const resetPasswordBtn = document.getElementById('reset-password-btn');
    const resetKeyBtn = document.getElementById('reset-key-btn');
    
    if (type === 'password' && passwordStatus) {
        if (hasCredential && !resetPasswordFlag) {
            passwordStatus.innerHTML = '<span style="color: var(--success);"><i class="fas fa-check-circle"></i> Password is set</span>';
            if (resetPasswordBtn) resetPasswordBtn.style.display = 'inline-flex';
        } else if (resetPasswordFlag) {
            passwordStatus.innerHTML = '<span style="color: var(--warning);"><i class="fas fa-exclamation-circle"></i> Will be cleared on save</span>';
            if (resetPasswordBtn) resetPasswordBtn.style.display = 'none';
        } else {
            passwordStatus.innerHTML = '<span style="color: var(--text-muted);"><i class="fas fa-minus-circle"></i> Not set</span>';
            if (resetPasswordBtn) resetPasswordBtn.style.display = 'none';
        }
    }
    
    if (type === 'key' && keyStatus) {
        if (hasCredential && !resetSshKeyFlag) {
            keyStatus.innerHTML = '<span style="color: var(--success);"><i class="fas fa-check-circle"></i> SSH Key is set</span>';
            if (resetKeyBtn) resetKeyBtn.style.display = 'inline-flex';
        } else if (resetSshKeyFlag) {
            keyStatus.innerHTML = '<span style="color: var(--warning);"><i class="fas fa-exclamation-circle"></i> Will be cleared on save</span>';
            if (resetKeyBtn) resetKeyBtn.style.display = 'none';
        } else {
            keyStatus.innerHTML = '<span style="color: var(--text-muted);"><i class="fas fa-minus-circle"></i> Not set</span>';
            if (resetKeyBtn) resetKeyBtn.style.display = 'none';
        }
    }
}

// Reset password function
function resetPassword() {
    if (confirm('Are you sure you want to clear the SSH password? The password will be removed when you save.')) {
        resetPasswordFlag = true;
        document.getElementById('node-ssh-password').value = '';
        updateCredentialStatus('password', true);
    }
}

// Reset SSH key function
function resetSshKey() {
    if (confirm('Are you sure you want to clear the SSH key? The key will be removed when you save.')) {
        resetSshKeyFlag = true;
        document.getElementById('node-ssh-key').value = '';
        updateCredentialStatus('key', true);
    }
}

// Close node modal
function closeNodeModal() {
    document.getElementById('node-modal').style.display = 'none';
    currentNodeId = null;
    resetPasswordFlag = false;
    resetSshKeyFlag = false;
}

// Save node
async function saveNode(event) {
    event.preventDefault();
    
    const authMethod = document.querySelector('input[name="auth_method"]:checked').value;
    const sshPassword = document.getElementById('node-ssh-password').value;
    const sshKey = document.getElementById('node-ssh-key').value;
    
    const nodeData = {
        name: document.getElementById('node-name').value,
        ip_address: document.getElementById('node-ip').value,
        ipv6_address: document.getElementById('node-ipv6').value || null,
        location_code: document.getElementById('node-location').value,
        city: document.getElementById('node-city').value || null,
        datacenter: document.getElementById('node-datacenter').value || null,
        ssh_host: document.getElementById('node-ssh-host').value || null,
        ssh_port: parseInt(document.getElementById('node-ssh-port').value) || 22,
        ssh_user: document.getElementById('node-ssh-user').value || null,
        enabled: document.getElementById('node-enabled').checked
    };
    
    // Handle credentials based on mode (create vs update)
    if (currentNodeId) {
        // UPDATE mode: only send credentials if they're explicitly set or being reset
        if (authMethod === 'password') {
            // If password is filled in, send it. If reset flag is set, send empty string to clear it.
            if (sshPassword) {
                nodeData.ssh_password = sshPassword;
            } else if (resetPasswordFlag) {
                nodeData.ssh_password = '';  // Explicitly clear
            }
            // Don't include ssh_password at all if empty and not resetting (keeps existing)
        } else if (authMethod === 'key') {
            // If key is filled in, send it. If reset flag is set, send empty string to clear it.
            if (sshKey) {
                nodeData.ssh_key = sshKey;
            } else if (resetSshKeyFlag) {
                nodeData.ssh_key = '';  // Explicitly clear
            }
            // Don't include ssh_key at all if empty and not resetting (keeps existing)
        }
    } else {
        // CREATE mode: always send credentials as entered
        nodeData.ssh_key = authMethod === 'key' ? sshKey : null;
        nodeData.ssh_password = authMethod === 'password' ? sshPassword : null;
    }
    
    try {
        const url = currentNodeId 
            ? `/api/v1/edge-nodes/${currentNodeId}` 
            : '/api/v1/edge-nodes/';
        
        const method = currentNodeId ? 'PATCH' : 'POST';
        
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getToken()}`
            },
            body: JSON.stringify(nodeData)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save node');
        }
        
        showNotification(
            currentNodeId ? 'Edge node updated successfully' : 'Edge node created successfully',
            'success'
        );
        closeNodeModal();
        loadNodes();
        loadStats();
    } catch (error) {
        console.error('Error saving node:', error);
        showNotification(error.message, 'error');
    }
}

// Delete node
async function deleteNode(nodeId) {
    if (!confirm('Are you sure you want to delete this edge node?')) return;
    
    try {
        const response = await fetch(`/api/v1/edge-nodes/${nodeId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to delete node');
        
        showNotification('Edge node deleted successfully', 'success');
        loadNodes();
        loadStats();
    } catch (error) {
        console.error('Error deleting node:', error);
        showNotification('Failed to delete edge node', 'error');
    }
}

// Check node health
async function checkNodeHealth(nodeId) {
    try {
        const response = await fetch(`/api/v1/edge-nodes/${nodeId}/health-check`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Health check failed');
        
        const health = await response.json();
        showNotification('Health check completed', 'success');
        loadNodes(); // Reload to show updated metrics
    } catch (error) {
        console.error('Error checking health:', error);
        showNotification('Health check failed', 'error');
    }
}

// Show component management modal
async function showComponentModal(nodeId) {
    document.getElementById('component-node-id').value = nodeId;
    
    const components = ['nginx', 'redis', 'certbot'];
    const componentsList = document.getElementById('components-list');
    
    componentsList.innerHTML = components.map(component => `
        <div class="component-item">
            <div class="flex-between mb-2">
                <h4 style="font-weight: 600; text-transform: capitalize;">${component}</h4>
                <div id="status-${component}-${nodeId}">
                    <i class="fas fa-spinner fa-spin"></i>
                </div>
            </div>
            <div class="component-actions">
                <button class="btn btn-sm btn-secondary" onclick="manageComponent(${nodeId}, '${component}', 'status')">
                    <i class="fas fa-info-circle"></i> Status
                </button>
                <button class="btn btn-sm btn-secondary" onclick="manageComponent(${nodeId}, '${component}', 'start')">
                    <i class="fas fa-play"></i> Start
                </button>
                <button class="btn btn-sm btn-secondary" onclick="manageComponent(${nodeId}, '${component}', 'stop')">
                    <i class="fas fa-stop"></i> Stop
                </button>
                <button class="btn btn-sm btn-secondary" onclick="manageComponent(${nodeId}, '${component}', 'restart')">
                    <i class="fas fa-redo"></i> Restart
                </button>
                ${component === 'nginx' ? `
                    <button class="btn btn-sm btn-secondary" onclick="manageComponent(${nodeId}, '${component}', 'reload')">
                        <i class="fas fa-sync"></i> Reload
                    </button>
                ` : ''}
                <button class="btn btn-sm" style="background: var(--info); color: white;" 
                        onclick="manageComponent(${nodeId}, '${component}', 'install')">
                    <i class="fas fa-download"></i> Install
                </button>
            </div>
        </div>
    `).join('');
    
    document.getElementById('component-modal').style.display = 'flex';
    
    // Load status for each component
    for (const component of components) {
        loadComponentStatus(nodeId, component);
    }
}

// Close component modal
function closeComponentModal() {
    document.getElementById('component-modal').style.display = 'none';
}

// Load component status
async function loadComponentStatus(nodeId, component) {
    try {
        const response = await fetch(`/api/v1/edge-nodes/${nodeId}/component/${component}`, {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load status');
        
        const status = await response.json();
        const statusEl = document.getElementById(`status-${component}-${nodeId}`);
        
        if (status.running) {
            statusEl.innerHTML = '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Running</span>';
        } else if (status.installed) {
            statusEl.innerHTML = '<span class="badge badge-warning"><i class="fas fa-pause-circle"></i> Stopped</span>';
        } else {
            statusEl.innerHTML = '<span class="badge" style="background: var(--bg-tertiary); color: var(--text-muted);">Not Installed</span>';
        }
        
        if (status.version) {
            statusEl.innerHTML += ` <span style="font-size: 11px; color: var(--text-muted);">v${status.version}</span>`;
        }
    } catch (error) {
        console.error('Error loading component status:', error);
        const statusEl = document.getElementById(`status-${component}-${nodeId}`);
        if (statusEl) {
            statusEl.innerHTML = '<span class="badge badge-error">Error</span>';
        }
    }
}

// Manage component
async function manageComponent(nodeId, component, action) {
    try {
        const response = await fetch(`/api/v1/edge-nodes/${nodeId}/component`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getToken()}`
            },
            body: JSON.stringify({ component, action })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Action failed');
        }
        
        const result = await response.json();
        
        if (result.success) {
            showNotification(`${component} ${action} completed successfully`, 'success');
            if (result.stdout) {
                console.log('Command output:', result.stdout);
            }
        } else {
            showNotification(`${component} ${action} failed: ${result.stderr}`, 'error');
        }
        
        // Reload component status
        loadComponentStatus(nodeId, component);
    } catch (error) {
        console.error('Error managing component:', error);
        showNotification(error.message, 'error');
    }
}

// Utility: Get auth token
function getToken() {
    return localStorage.getItem('auth_token') || '';
}

// Utility: Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Utility: Format date time
function formatDateTime(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function toggleAuthMethod() {
    const method = document.querySelector('input[name="auth_method"]:checked').value;
    if (method === 'password') {
        document.getElementById('auth-password').style.display = 'block';
        document.getElementById('auth-key').style.display = 'none';
    } else {
        document.getElementById('auth-password').style.display = 'none';
        document.getElementById('auth-key').style.display = 'block';
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadNodes();
    loadStats();
    
    // Auto-refresh every 30 seconds
    setInterval(() => {
        loadNodes();
        loadStats();
    }, 30000);
});
