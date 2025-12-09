// Global Auth Helper
function getToken() {
    return localStorage.getItem('access_token') || '';
}

// Global Auth Check
function checkAuth() {
    const publicPages = ['/login', '/signup', '/'];
    const currentPath = window.location.pathname;
    
    // Skip auth check for public pages
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

// Global Fetch Interceptor for 401 handling
(function() {
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        return originalFetch.apply(this, args).then(response => {
            if (response.status === 401) {
                // Unauthorized - redirect to login
                const currentPath = window.location.pathname;
                const publicPages = ['/login', '/signup', '/'];
                
                if (!publicPages.includes(currentPath)) {
                    localStorage.removeItem('access_token');
                    console.warn('Unauthorized request detected, redirecting to login');
                    window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
                }
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
            if (response.status === 401) {
                this.clearToken();
                window.location.href = '/login';
                return;
            }
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
    
    async delete(endpoint) {
        return this.request(endpoint, {
            method: 'DELETE',
        });
    }
    
    setToken(token) {
        this.token = token;
        localStorage.setItem('access_token', token);
    }
    
    clearToken() {
        this.token = null;
        localStorage.removeItem('access_token');
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
        setTimeout(() => notification.remove(), 300);
    }, 3000);
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
        api.setToken(response.access_token);
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
                <h3>${domain.name}</h3>
                <span class="badge badge-${getStatusBadge(domain.status)}">${domain.status}</span>
            </div>
            <div class="flex gap-2">
                <a href="/domains/${domain.id}" class="btn btn-secondary btn-sm">Manage</a>
                <a href="/domains/${domain.id}/dns" class="btn btn-secondary btn-sm">DNS</a>
                <a href="/domains/${domain.id}/settings" class="btn btn-secondary btn-sm">Settings</a>
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
            <td>${record.name}</td>
            <td>${record.content}</td>
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
                <button onclick="editRecord(${record.id})" class="btn btn-sm btn-secondary">Edit</button>
                <button onclick="deleteRecord(${record.id})" class="btn btn-sm btn-secondary">Delete</button>
            </td>
        </tr>
    `).join('');
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    
    // Check authorization on all pages
    checkAuth();
});


