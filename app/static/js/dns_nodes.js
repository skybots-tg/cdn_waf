// DNS Nodes Management JavaScript

let currentNodeId = null;

// ---------- Общий врапер над fetch ----------

async function apiRequest(path, { method = 'GET', body = null, signal } = {}) {
    const headers = {
        'Authorization': `Bearer ${getToken()}`
    };

    const options = {
        method,
        headers,
        signal
    };

    if (body !== null && body !== undefined) {
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }

    const response = await fetch(path, options);

    const contentType = response.headers.get('Content-Type') || '';
    let data = null;

    if (contentType.includes('application/json')) {
        try {
            data = await response.json();
        } catch {
            data = null;
        }
    } else {
        try {
            data = await response.text();
        } catch {
            data = null;
        }
    }

    if (!response.ok) {
        const detail =
            (data && (data.detail || data.message || data.error)) ||
            `Request failed with status ${response.status}`;
        throw new Error(detail);
    }

    return data;
}

// ---------- Загрузка данных ----------

// Load DNS nodes
async function loadNodes() {
    try {
        const nodes = await apiRequest('/api/v1/dns-nodes/');
        renderNodes(Array.isArray(nodes) ? nodes : []);
    } catch (error) {
        console.error('Error loading nodes:', error);
        showNotification('Failed to load DNS nodes', 'error');
    }
}

// Load stats
async function loadStats() {
    try {
        const stats = await apiRequest('/api/v1/dns-nodes/stats');

        if (!stats) return;

        const totalEl = document.getElementById('stat-total');
        const onlineEl = document.getElementById('stat-online');
        const offlineEl = document.getElementById('stat-offline');

        if (totalEl) totalEl.textContent = stats.total_nodes ?? '0';
        if (onlineEl) onlineEl.textContent = stats.online_nodes ?? '0';
        if (offlineEl) offlineEl.textContent = stats.offline_nodes ?? '0';
    } catch (error) {
        console.error('Error loading stats:', error);
        // тут можно не шуметь пользователю каждый раз
    }
}

// ---------- Рендер ----------

const STATUS_BADGES = {
    online: '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Online</span>',
    offline: '<span class="badge badge-error"><i class="fas fa-times-circle"></i> Offline</span>',
    unknown: '<span class="badge" style="background: var(--bg-tertiary); color: var(--text-muted);">Unknown</span>'
};

// Render nodes table
function renderNodes(nodes) {
    const tbody = document.getElementById('nodes-table-body');
    if (!tbody) return;

    if (!Array.isArray(nodes) || nodes.length === 0) {
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

    tbody.innerHTML = nodes
        .map(node => `
        <tr>
            <td>
                <div style="font-weight: 600;">${escapeHtml(node.name)}</div>
                <div style="font-size: 12px; color: var(--text-secondary);">
                    ${escapeHtml(node.datacenter || 'N/A')}
                </div>
            </td>
            <td>
                <span class="badge badge-info">${escapeHtml(node.hostname || 'N/A')}</span>
            </td>
            <td>
                <span class="badge">${escapeHtml(node.location_code || 'N/A')}</span>
            </td>
            <td>
                <div style="font-family: monospace; font-size: 13px;">
                    ${escapeHtml(node.ip_address || 'N/A')}
                </div>
                ${
                    node.ipv6_address
                        ? `<div style="font-family: monospace; font-size: 11px; color: var(--text-muted);">
                               ${escapeHtml(node.ipv6_address)}
                           </div>`
                        : ''
                }
            </td>
            <td>${getStatusBadge(node.status)}</td>
            <td>
                ${
                    node.last_heartbeat
                        ? formatDateTime(node.last_heartbeat)
                        : '<span style="color: var(--text-muted);">Never</span>'
                }
            </td>
            <td>
                <div class="flex gap-1">
                    <a href="/dns-nodes/${node.id}" class="btn btn-icon btn-sm btn-secondary" title="Manage">
                        <i class="fas fa-edit"></i>
                    </a>
                    <button class="btn btn-icon btn-sm"
                            style="background: var(--error); color: white;"
                            onclick="deleteNode(${Number(node.id)})"
                            title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `)
        .join('');
}

// Get status badge HTML
function getStatusBadge(status) {
    const key = String(status || 'unknown').toLowerCase();
    return STATUS_BADGES[key] || STATUS_BADGES.unknown;
}

// ---------- Модалка узла ----------

// Show add node modal
function showAddNodeModal() {
    currentNodeId = null;

    const titleEl = document.getElementById('modal-title');
    if (titleEl) titleEl.textContent = 'Add DNS Node';

    const form = document.getElementById('node-form');
    if (form) form.reset();

    const idEl = document.getElementById('node-id');
    if (idEl) idEl.value = '';

    const sshPortEl = document.getElementById('node-ssh-port');
    if (sshPortEl && !sshPortEl.value) sshPortEl.value = '22';

    const enabledEl = document.getElementById('node-enabled');
    if (enabledEl) enabledEl.checked = true;

    const modal = document.getElementById('node-modal');
    if (modal) modal.style.display = 'flex';
}

// Close node modal
function closeNodeModal() {
    const modal = document.getElementById('node-modal');
    if (modal) modal.style.display = 'none';
    currentNodeId = null;
}

// Save node
async function saveNode(event) {
    if (event) event.preventDefault();

    const getVal = id => {
        const el = document.getElementById(id);
        return el ? el.value : '';
    };

    const getChecked = id => {
        const el = document.getElementById(id);
        return el ? el.checked : false;
    };

    const authMethodInput = document.querySelector('input[name="auth_method"]:checked');
    const authMethod = authMethodInput ? authMethodInput.value : 'password';

    const nodeData = {
        name: getVal('node-name'),
        hostname: getVal('node-hostname'),
        ip_address: getVal('node-ip'),
        ipv6_address: getVal('node-ipv6') || null,
        location_code: getVal('node-location'),
        city: getVal('node-city') || null,
        datacenter: getVal('node-datacenter') || null,
        ssh_host: getVal('node-ssh-host') || null,
        ssh_port: parseInt(getVal('node-ssh-port'), 10) || 22,
        ssh_user: getVal('node-ssh-user') || null,
        ssh_key:
            authMethod === 'key'
                ? getVal('node-ssh-key')
                : null,
        ssh_password:
            authMethod === 'password'
                ? (getVal('node-ssh-password') || null)
                : null,
        enabled: getChecked('node-enabled')
    };

    try {
        const url = currentNodeId
            ? `/api/v1/dns-nodes/${currentNodeId}`
            : '/api/v1/dns-nodes/';
        const method = currentNodeId ? 'PATCH' : 'POST';

        await apiRequest(url, { method, body: nodeData });

        showNotification(
            currentNodeId ? 'DNS node updated successfully' : 'DNS node created successfully',
            'success'
        );

        closeNodeModal();
        loadNodes();
        loadStats();
    } catch (error) {
        console.error('Error saving node:', error);
        showNotification(error.message || 'Failed to save node', 'error');
    }
}

// Delete node
async function deleteNode(nodeId) {
    if (!confirm('Are you sure you want to delete this DNS node?')) return;

    try {
        await apiRequest(`/api/v1/dns-nodes/${nodeId}`, { method: 'DELETE' });

        showNotification('DNS node deleted successfully', 'success');
        loadNodes();
        loadStats();
    } catch (error) {
        console.error('Error deleting node:', error);
        showNotification(error.message || 'Failed to delete DNS node', 'error');
    }
}

// ---------- Утилиты ----------

// Utility: Get auth token
function getToken() {
    return localStorage.getItem('access_token') || '';
}

// Utility: Escape HTML
const _escapeDiv = document.createElement('div');
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    _escapeDiv.textContent = String(text);
    return _escapeDiv.innerHTML;
}

// Utility: Format date time
function formatDateTime(dateStr) {
    if (!dateStr) return '-';

    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return '-';

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
    const methodInput = document.querySelector('input[name="auth_method"]:checked');
    const method = methodInput ? methodInput.value : 'password';

    const passwordBlock = document.getElementById('auth-password');
    const keyBlock = document.getElementById('auth-key');

    if (method === 'password') {
        if (passwordBlock) passwordBlock.style.display = 'block';
        if (keyBlock) keyBlock.style.display = 'none';
    } else {
        if (passwordBlock) passwordBlock.style.display = 'none';
        if (keyBlock) keyBlock.style.display = 'block';
    }
}

// ---------- Инициализация ----------

document.addEventListener('DOMContentLoaded', () => {
    loadNodes();
    loadStats();

    // Auto-refresh every 30 seconds
    setInterval(() => {
        loadNodes();
        loadStats();
    }, 30000);
});
