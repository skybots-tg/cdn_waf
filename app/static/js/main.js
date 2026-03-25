// Global Auth Helper
function getToken() {
    return localStorage.getItem('access_token') || '';
}

function getRefreshToken() {
    return localStorage.getItem('refresh_token') || '';
}

// Global Auth Check
function checkAuth() {
    const publicPages = ['/login', '/signup', '/'];
    const currentPath = window.location.pathname;
    
    if (publicPages.includes(currentPath)) {
        return true;
    }
    
    const token = getToken();
    if (!token) {
        console.warn('No auth token found, redirecting to login');
        window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
        return false;
    }
    
    return true;
}

// Silent token refresh via refresh_token
let _refreshPromise = null;

async function silentRefresh() {
    if (_refreshPromise) return _refreshPromise;

    const refreshToken = getRefreshToken();
    if (!refreshToken) return false;

    _refreshPromise = (async () => {
        try {
            const resp = await fetch('/api/v1/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken }),
            });
            if (!resp.ok) return false;

            const data = await resp.json();
            localStorage.setItem('access_token', data.access_token);
            localStorage.setItem('refresh_token', data.refresh_token);
            if (typeof api !== 'undefined') {
                api.token = data.access_token;
            }
            return true;
        } catch {
            return false;
        } finally {
            _refreshPromise = null;
        }
    })();

    return _refreshPromise;
}

// Global Fetch Interceptor — retry once with refreshed token on 401
(function() {
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        return originalFetch.apply(this, args).then(async response => {
            if (response.status === 401) {
                const currentPath = window.location.pathname;
                const publicPages = ['/login', '/signup', '/'];
                if (publicPages.includes(currentPath)) return response;

                // Skip refresh attempt for the refresh endpoint itself
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
                if (url.includes('/auth/refresh')) {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                    window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
                    return response;
                }

                const refreshed = await silentRefresh();
                if (refreshed) {
                    // Retry the original request with the new token
                    const [input, init = {}] = args;
                    const newHeaders = new Headers(init.headers || {});
                    newHeaders.set('Authorization', 'Bearer ' + localStorage.getItem('access_token'));
                    return originalFetch(input, { ...init, headers: newHeaders });
                }

                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
            }
            return response;
        });
    };
})();

// Theme Toggle
function initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    const html = document.documentElement;
    
    // Load saved theme
    const savedTheme = localStorage.getItem('theme') || 'light';
    html.setAttribute('data-theme', savedTheme);
    
    if (themeToggle) {
        themeToggle.checked = savedTheme === 'dark';
        
        themeToggle.addEventListener('change', () => {
            const theme = themeToggle.checked ? 'dark' : 'light';
            html.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
        });
    }
}

// API Helper
class API {
    constructor() {
        this.baseURL = '/api/v1';
        this.token = localStorage.getItem('access_token');
    }
    
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };
        
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        
        const response = await fetch(url, {
            ...options,
            headers,
        });
        
        if (!response.ok) {
            let errorMsg = 'Request failed';
            try {
                const error = await response.json();
                errorMsg = error.detail || error.message || errorMsg;
            } catch (e) {
                errorMsg = `Server Error (${response.status}): ${response.statusText}`;
            }
            throw new Error(errorMsg);
        }
        
        return response.json();
    }
    
    async get(endpoint) {
        return this.request(endpoint);
    }
    
    async post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }
    
    async patch(endpoint, data) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }
    
    async put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }
    
    async delete(endpoint) {
        return this.request(endpoint, {
            method: 'DELETE',
        });
    }
    
    setToken(token, refreshToken) {
        this.token = token;
        localStorage.setItem('access_token', token);
        if (refreshToken) {
            localStorage.setItem('refresh_token', refreshToken);
        }
    }
    
    clearToken() {
        this.token = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }
}

const api = new API();

// Notifications
function showNotification(message, type = 'info') {
    const container = document.getElementById('notifications');
    if (!container) return;
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    container.appendChild(notification);
    
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.addEventListener('transitionend', () => notification.remove(), { once: true });
        setTimeout(() => notification.remove(), 500);
    }, 3000);
}

// HTML Escape
const _escapeEl = document.createElement('div');
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    _escapeEl.textContent = String(text);
    return _escapeEl.innerHTML;
}

// Form Validation
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validateDomain(domain) {
    const re = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/;
    return re.test(domain.toLowerCase());
}

// Login Handler
async function handleLogin(event) {
    event.preventDefault();
    
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    
    try {
        const response = await api.post('/auth/login', { email, password });
        api.setToken(response.access_token, response.refresh_token);
        showNotification('Login successful!', 'success');
        
        // Redirect to the page user was trying to access, or dashboard by default
        const urlParams = new URLSearchParams(window.location.search);
        const redirectTo = urlParams.get('redirect') || '/dashboard';
        window.location.href = redirectTo;
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

// Signup Handler
async function handleSignup(event) {
    event.preventDefault();
    
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const fullName = document.getElementById('full_name').value;
    
    if (!validateEmail(email)) {
        showNotification('Invalid email address', 'error');
        return;
    }
    
    if (password.length < 8) {
        showNotification('Password must be at least 8 characters', 'error');
        return;
    }
    
    try {
        await api.post('/auth/signup', {
            email,
            password,
            full_name: fullName || null,
        });
        showNotification('Account created! Please login.', 'success');
        window.location.href = '/login';
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

// Domain Management
async function loadDomains() {
    try {
        const domains = await api.get('/domains');
        renderDomains(domains);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

function renderDomains(domains) {
    const container = document.getElementById('domains-list');
    if (!container) return;
    
    if (domains.length === 0) {
        container.innerHTML = `
            <div class="glass-card text-center">
                <p class="text-secondary">No domains yet. Add your first domain to get started!</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = domains.map(domain => `
        <div class="glass-card">
            <div class="flex-between mb-2">
                <h3>${escapeHtml(domain.name)}</h3>
                <span class="badge badge-${getStatusBadge(domain.status)}">${escapeHtml(domain.status)}</span>
            </div>
            <div class="flex gap-2">
                <a href="/domains/${encodeURIComponent(domain.id)}" class="btn btn-secondary btn-sm">Manage</a>
                <a href="/domains/${encodeURIComponent(domain.id)}/dns" class="btn btn-secondary btn-sm">DNS</a>
                <a href="/domains/${encodeURIComponent(domain.id)}/settings" class="btn btn-secondary btn-sm">Settings</a>
            </div>
        </div>
    `).join('');
}

function getStatusBadge(status) {
    const badges = {
        'active': 'success',
        'pending': 'warning',
        'suspended': 'error',
        'deleted': 'error',
    };
    return badges[status] || 'info';
}

// DNS Records
async function loadDNSRecords(domainId) {
    try {
        const records = await api.get(`/dns/domains/${domainId}/records`);
        renderDNSRecords(records);
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

function renderDNSRecords(records) {
    const tbody = document.querySelector('#dns-table tbody');
    if (!tbody) return;
    
    if (records.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="text-center text-secondary">No DNS records found</td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = records.map(record => `
        <tr>
            <td><strong>${record.type}</strong></td>
            <td title="${record.name}">${record.name}</td>
            <td title="${record.content}">${record.content}</td>
            <td>${record.ttl}</td>
            <td>
                ${record.proxied ? '<span class="badge badge-orange">Proxied</span>' : '<span class="badge">DNS Only</span>'}
            </td>
            <td>
                ${record.type === 'A' || record.type === 'AAAA' ? `
                    <button onclick="issueCertificate('${record.name}')" class="btn btn-sm btn-primary" title="Issue Let's Encrypt Certificate">
                        <i class="fas fa-certificate"></i>
                    </button>
                ` : '<span class="text-secondary">-</span>'}
            </td>
            <td>
                <div class="flex gap-1">
                    <button onclick="editRecord(${record.id})" class="btn btn-icon btn-sm btn-secondary" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button onclick="deleteRecord(${record.id})" class="btn btn-icon btn-sm" style="background: var(--error); color: white;" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

// API Key Management
function showCreateAPIKeyModal() {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content glass-card" style="max-width: 500px;">
            <div class="flex-between mb-3">
                <h2 style="font-size: 20px; font-weight: 600; margin: 0;">Create API Key</h2>
                <button onclick="closeModal()" class="btn-icon" style="color: var(--text-secondary);">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <form id="create-api-key-form">
                <div class="form-group">
                    <label class="form-label">API Key Name</label>
                    <input type="text" class="form-input" id="api-key-name" placeholder="e.g., Production Server" required>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                        Give your API key a descriptive name to remember its purpose
                    </p>
                </div>
                <div class="flex gap-2" style="justify-content: flex-end;">
                    <button type="button" onclick="closeModal()" class="btn btn-secondary">Cancel</button>
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-plus"></i> Create Key
                    </button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Add modal styles if not exists
    if (!document.getElementById('modal-styles')) {
        const style = document.createElement('style');
        style.id = 'modal-styles';
        style.textContent = `
            .modal {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
                animation: fadeIn 0.2s ease;
            }
            .modal-content {
                animation: slideUp 0.3s ease;
            }
            @keyframes slideUp {
                from {
                    opacity: 0;
                    transform: translateY(20px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }
        `;
        document.head.appendChild(style);
    }
    
    // Handle form submission
    document.getElementById('create-api-key-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await createAPIKey();
    });
    
    // Focus input
    setTimeout(() => document.getElementById('api-key-name').focus(), 100);
}

function closeModal() {
    // Remove both .modal and .modal-overlay elements
    document.querySelectorAll('.modal, .modal-overlay').forEach(modal => modal.remove());
}

async function createAPIKey() {
    const name = document.getElementById('api-key-name').value;
    
    try {
        const response = await api.post('/auth/api-keys', { 
            name: name,
            scopes: null,
            allowed_ips: null,
            expires_at: null
        });
        
        closeModal();
        showNotification('API key created successfully', 'success');
        
        // Show the API key to user (one time only)
        showAPIKeyResult(response);
        
        // Reload API keys list
        if (typeof loadAPIKeys === 'function') {
            loadAPIKeys();
        }
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

function showAPIKeyResult(data) {
    const keyValue = data.token || data.key || 'key_xxxxxxxxxxxxxx';
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content glass-card" style="max-width: 600px;">
            <div class="mb-3">
                <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 8px;">
                    <i class="fas fa-check-circle" style="color: var(--success);"></i> API Key Created
                </h2>
                <p style="color: var(--warning); background: rgba(255, 193, 7, 0.1); padding: 12px; border-radius: 8px; border-left: 3px solid var(--warning);">
                    <i class="fas fa-exclamation-triangle"></i>
                    <strong>Important:</strong> Save this key now! You won't be able to see it again.
                </p>
            </div>
            <div class="form-group">
                <label class="form-label">API Key</label>
                <div style="display: flex; gap: 8px;">
                    <input type="text" class="form-input" id="api-key-value" readonly style="font-family: monospace; font-size: 13px;">
                    <button onclick="copyAPIKey()" class="btn btn-secondary">
                        <i class="fas fa-copy"></i> Copy
                    </button>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Usage Example</label>
                <pre style="background: var(--bg-tertiary); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 12px;">curl -H "Authorization: Bearer ${escapeHtml(keyValue)}" \\
  https://api.flarecloud.ru/api/v1/domains</pre>
            </div>
            <div style="text-align: right;">
                <button onclick="closeModal(); if(typeof loadAPIKeys === 'function') loadAPIKeys();" class="btn btn-primary">Got it</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    const input = document.getElementById('api-key-value');
    if (input) {
        input.value = keyValue;
        setTimeout(() => input.select(), 100);
    }
}

function copyAPIKey() {
    const input = document.getElementById('api-key-value');
    if (!input) return;
    input.select();
    navigator.clipboard.writeText(input.value).then(() => {
        showNotification('API key copied to clipboard', 'success');
    }).catch(() => {
        document.execCommand('copy');
        showNotification('API key copied to clipboard', 'success');
    });
}

async function deleteAPIKey(keyId) {
    if (!confirm('Are you sure you want to delete this API key? This action cannot be undone.')) {
        return;
    }
    
    try {
        await api.delete(`/auth/api-keys/${keyId}`);
        showNotification('API key deleted', 'success');
        loadAPIKeys();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

// Team member management
function showInviteMemberModal() {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
        <div class="modal-content glass-card" style="max-width: 500px;">
            <div class="flex-between mb-3">
                <h2 style="font-size: 20px; font-weight: 600; margin: 0;">Invite Team Member</h2>
                <button onclick="closeModal()" class="btn-icon" style="color: var(--text-secondary);">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <form id="invite-member-form">
                <div class="form-group">
                    <label class="form-label">Email Address</label>
                    <input type="email" class="form-input" id="member-email" placeholder="colleague@example.com" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-input" id="member-role" required>
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
                <div class="flex gap-2" style="justify-content: flex-end;">
                    <button type="button" onclick="closeModal()" class="btn btn-secondary">Cancel</button>
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-user-plus"></i> Send Invite
                    </button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Handle form submission
    document.getElementById('invite-member-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('member-email').value;
        const role = document.getElementById('member-role').value;
        
        try {
            await api.post('/organization/invite', { email, role });
            closeModal();
            showNotification('Invitation sent successfully', 'success');
            loadTeamMembers();
        } catch (error) {
            showNotification(error.message, 'error');
        }
    });
    
    // Focus input
    setTimeout(() => document.getElementById('member-email').focus(), 100);
}

async function removeMember(memberId) {
    if (!confirm('Are you sure you want to remove this team member?')) {
        return;
    }
    
    try {
        await api.delete(`/organization/members/${memberId}`);
        showNotification('Team member removed', 'success');
        loadTeamMembers();
    } catch (error) {
        showNotification(error.message, 'error');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    
    // Check authorization on all pages
    checkAuth();
});


