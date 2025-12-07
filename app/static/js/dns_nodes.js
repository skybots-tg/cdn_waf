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
                    <a href="/dns-nodes/${node.id}" class="btn btn-icon btn-sm btn-secondary" title="Manage">
                        <i class="fas fa-edit"></i>
                    </a>
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
