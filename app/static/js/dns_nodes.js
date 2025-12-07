// DNS Nodes Management JavaScript

let currentNodeId = null;

// Load DNS nodes
async function loadNodes() {
    let url = '/api/v1/dns-nodes/';
    
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
        showNotification('Failed to load DNS nodes', 'error');
    }
}

// Load stats
async function loadStats() {
    try {
        const response = await fetch('/api/v1/dns-nodes/stats', {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load stats');
        
        const stats = await response.json();
        document.getElementById('stat-total').textContent = stats.total_nodes;
        document.getElementById('stat-online').textContent = stats.online_nodes;
        document.getElementById('stat-offline').textContent = stats.offline_nodes;
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
                <td colspan="7" style="text-align: center; padding: 32px; color: var(--text-muted);">
                    <i class="fas fa-inbox"></i><br>
                    No DNS nodes found
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
                <span class="badge badge-info">${escapeHtml(node.hostname)}</span>
            </td>
            <td>
                <span class="badge">${escapeHtml(node.location_code)}</span>
            </td>
            <td>
                <div style="font-family: monospace; font-size: 13px;">${escapeHtml(node.ip_address)}</div>
                ${node.ipv6_address ? `<div style="font-family: monospace; font-size: 11px; color: var(--text-muted);">${escapeHtml(node.ipv6_address)}</div>` : ''}
            </td>
            <td>${getStatusBadge(node.status)}</td>
            <td>
                ${node.last_heartbeat ? formatDateTime(node.last_heartbeat) : 
                    '<span style="color: var(--text-muted);">Never</span>'}
            </td>
            <td>
                <div class="flex gap-1">
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="editNode(${node.id})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="showComponentModal(${node.id})" title="Components / Install">
                        <i class="fas fa-cogs"></i>
                    </button>
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="showLogModal(${node.id})" title="View Logs">
                        <i class="fas fa-file-alt"></i>
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
        'unknown': '<span class="badge" style="background: var(--bg-tertiary); color: var(--text-muted);">Unknown</span>'
    };
    return badges[status] || badges['unknown'];
}

// Show add node modal
function showAddNodeModal() {
    currentNodeId = null;
    document.getElementById('modal-title').textContent = 'Add DNS Node';
    document.getElementById('node-form').reset();
    document.getElementById('node-id').value = '';
    document.getElementById('node-ssh-port').value = '22';
    document.getElementById('node-enabled').checked = true;
    document.getElementById('node-modal').style.display = 'flex';
}

// Edit node
async function editNode(nodeId) {
    try {
        const response = await fetch(`/api/v1/dns-nodes/${nodeId}`, {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load node');
        
        const node = await response.json();
        currentNodeId = nodeId;
        
        document.getElementById('modal-title').textContent = 'Edit DNS Node';
        document.getElementById('node-id').value = node.id;
        document.getElementById('node-name').value = node.name;
        document.getElementById('node-hostname').value = node.hostname;
        document.getElementById('node-ip').value = node.ip_address;
        document.getElementById('node-ipv6').value = node.ipv6_address || '';
        document.getElementById('node-location').value = node.location_code;
        document.getElementById('node-city').value = node.city || '';
        document.getElementById('node-datacenter').value = node.datacenter || '';
        document.getElementById('node-ssh-host').value = node.ssh_host || '';
        document.getElementById('node-ssh-port').value = node.ssh_port || 22;
        document.getElementById('node-ssh-user').value = node.ssh_user || '';
        document.getElementById('node-enabled').checked = node.enabled;
        
        // Handle auth method
        if (node.has_ssh_key) {
            document.querySelector('input[name="auth_method"][value="key"]').checked = true;
            toggleAuthMethod();
        } else {
            document.querySelector('input[name="auth_method"][value="password"]').checked = true;
            toggleAuthMethod();
        }
        
        document.getElementById('node-modal').style.display = 'flex';
    } catch (error) {
        console.error('Error loading node:', error);
        showNotification('Failed to load node details', 'error');
    }
}

// Close node modal
function closeNodeModal() {
    document.getElementById('node-modal').style.display = 'none';
    currentNodeId = null;
}

// Save node
async function saveNode(event) {
    event.preventDefault();
    
    const nodeData = {
        name: document.getElementById('node-name').value,
        hostname: document.getElementById('node-hostname').value,
        ip_address: document.getElementById('node-ip').value,
        ipv6_address: document.getElementById('node-ipv6').value || null,
        location_code: document.getElementById('node-location').value,
        city: document.getElementById('node-city').value || null,
        datacenter: document.getElementById('node-datacenter').value || null,
        ssh_host: document.getElementById('node-ssh-host').value || null,
        ssh_port: parseInt(document.getElementById('node-ssh-port').value) || 22,
        ssh_user: document.getElementById('node-ssh-user').value || null,
        ssh_key: document.querySelector('input[name="auth_method"]:checked').value === 'key' 
            ? document.getElementById('node-ssh-key').value 
            : null,
        ssh_password: document.querySelector('input[name="auth_method"]:checked').value === 'password'
            ? document.getElementById('node-ssh-password').value
            : null,
        enabled: document.getElementById('node-enabled').checked
    };
    
    try {
        const url = currentNodeId 
            ? `/api/v1/dns-nodes/${currentNodeId}` 
            : '/api/v1/dns-nodes/';
        
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
            currentNodeId ? 'DNS node updated successfully' : 'DNS node created successfully',
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
    if (!confirm('Are you sure you want to delete this DNS node?')) return;
    
    try {
        const response = await fetch(`/api/v1/dns-nodes/${nodeId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to delete node');
        
        showNotification('DNS node deleted successfully', 'success');
        loadNodes();
        loadStats();
    } catch (error) {
        console.error('Error deleting node:', error);
        showNotification('Failed to delete DNS node', 'error');
    }
}

// Show component management modal
async function showComponentModal(nodeId) {
    document.getElementById('component-node-id').value = nodeId;
    currentNodeId = nodeId;
    
    // Detailed components for "nuance tracking"
    const components = [
        { id: 'dependencies', name: 'System Dependencies' },
        { id: 'python_env', name: 'Python Environment' },
        { id: 'app_code', name: 'Application Code' },
        { id: 'config', name: 'Configuration' },
        { id: 'dns_service', name: 'DNS Service' }
    ];
    
    const componentsList = document.getElementById('components-list');
    
    componentsList.innerHTML = components.map(comp => `
        <div class="component-item">
            <div class="flex-between mb-2">
                <h4 style="font-weight: 600; text-transform: capitalize;">${comp.name}</h4>
                <div id="status-${comp.id}-${nodeId}">
                    <i class="fas fa-spinner fa-spin"></i>
                </div>
            </div>
            <div class="component-actions">
                ${getComponentActions(comp.id, nodeId)}
            </div>
        </div>
    `).join('');
    
    document.getElementById('component-modal').style.display = 'flex';
    
    // Load status for each component
    for (const comp of components) {
        loadComponentStatus(nodeId, comp.id);
    }
}

function getComponentActions(component, nodeId) {
    let actions = '';
    
    // Common install/update action
    actions += `
        <button class="btn btn-sm" style="background: var(--info); color: white;" 
                onclick="manageComponent(${nodeId}, '${component}', 'install')" title="Install / Update">
            <i class="fas fa-download"></i> Install
        </button>
    `;

    // Service specific actions
    if (component === 'dns_service') {
        actions = `
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
            ${actions}
        `;
    }
    
    return actions;
}

// Log Viewer Functions
let logRefreshInterval = null;

function showLogModal(nodeId) {
    currentNodeId = nodeId;
    document.getElementById('log-modal').style.display = 'flex';
    refreshLogs();
    
    // Auto refresh logs every 5 seconds
    if (logRefreshInterval) clearInterval(logRefreshInterval);
    logRefreshInterval = setInterval(refreshLogs, 5000);
}

function closeLogModal() {
    document.getElementById('log-modal').style.display = 'none';
    if (logRefreshInterval) {
        clearInterval(logRefreshInterval);
        logRefreshInterval = null;
    }
    currentNodeId = null;
}

async function refreshLogs() {
    if (!currentNodeId) return;
    
    const lines = document.getElementById('log-lines').value;
    const logContent = document.getElementById('log-content');
    
    try {
        const response = await fetch(`/api/v1/dns-nodes/${currentNodeId}/logs?lines=${lines}`, {
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (!response.ok) throw new Error('Failed to load logs');
        
        const data = await response.json();
        logContent.textContent = data.logs || 'No logs available.';
        
        // Auto scroll to bottom if near bottom? For now just stay.
        logContent.scrollTop = logContent.scrollHeight;
    } catch (error) {
        console.error('Error loading logs:', error);
        logContent.textContent = 'Error loading logs: ' + error.message;
    }
}

// Close component modal
function closeComponentModal() {
    document.getElementById('component-modal').style.display = 'none';
}

// Load component status
async function loadComponentStatus(nodeId, component) {
    try {
        const response = await fetch(`/api/v1/dns-nodes/${nodeId}/components/${component}`, {
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
        const response = await fetch(`/api/v1/dns-nodes/${nodeId}/component`, {
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
    return localStorage.getItem('access_token') || '';
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
