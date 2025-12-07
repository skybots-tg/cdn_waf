// Domain Settings Management JavaScript
// Part 1: Cache & CDN

// ==================== Cache Rules ====================

async function loadCacheRules() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/cache/rules`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load cache rules');
        
        const rules = await response.json();
        renderCacheRules(rules);
    } catch (error) {
        console.error('Error loading cache rules:', error);
        document.getElementById('cache-rules-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load cache rules</p>';
    }
}

function renderCacheRules(rules) {
    const container = document.getElementById('cache-rules-list');
    
    if (rules.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No cache rules configured</p>';
        return;
    }
    
    container.innerHTML = rules.map(rule => `
        <div class="glass-card glass-card-sm mb-2">
            <div class="flex-between">
                <div style="flex: 1;">
                    <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                        <code style="background: var(--bg-tertiary); padding: 4px 8px; border-radius: 4px;">
                            ${escapeHtml(rule.pattern)}
                        </code>
                        <span class="badge ${rule.rule_type === 'cache' ? 'badge-success' : 'badge-warning'}">
                            ${rule.rule_type.toUpperCase()}
                        </span>
                        ${rule.enabled ? '' : '<span class="badge" style="background: var(--bg-tertiary);">Disabled</span>'}
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary);">
                        ${rule.ttl ? `TTL: ${rule.ttl}s` : 'No TTL'} 
                        ${rule.respect_origin_headers ? '• Respect Origin' : ''}
                    </div>
                </div>
                <div class="flex gap-1">
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="editCacheRule(${rule.id})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                            onclick="deleteCacheRule(${rule.id})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function showAddCacheRuleModal() {
    // TODO: Implement modal
    alert('Cache rule modal - to be implemented');
}

async function deleteCacheRule(ruleId) {
    if (!confirm('Delete this cache rule?')) return;
    
    try {
        const response = await fetch(`/api/v1/domains/cache/rules/${ruleId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to delete rule');
        
        showNotification('Cache rule deleted', 'success');
        loadCacheRules();
    } catch (error) {
        showNotification('Failed to delete cache rule', 'error');
    }
}

// ==================== Cache Purge ====================

async function purgeCache(type) {
    let purgeData = { purge_type: type };
    
    if (type === 'url') {
        const url = document.getElementById('purge-url').value.trim();
        if (!url) {
            showNotification('Enter a URL to purge', 'warning');
            return;
        }
        purgeData.urls = [url];
    }
    
    if (!confirm(`Purge cache (${type})? This action cannot be undone.`)) return;
    
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/cache/purge`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getToken()}`
            },
            body: JSON.stringify(purgeData)
        });
        
        if (!response.ok) throw new Error('Failed to purge cache');
        
        showNotification('Cache purge initiated', 'success');
        if (type === 'url') document.getElementById('purge-url').value = '';
    } catch (error) {
        showNotification('Failed to purge cache', 'error');
    }
}

// ==================== Dev Mode ====================

async function loadDevModeStatus() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/cache/dev-mode`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load dev mode status');
        
        const status = await response.json();
        renderDevModeStatus(status);
    } catch (error) {
        console.error('Error loading dev mode:', error);
    }
}

function renderDevModeStatus(status) {
    const container = document.getElementById('dev-mode-status');
    
    if (status.enabled && status.expires_at) {
        const expiresAt = new Date(status.expires_at);
        container.innerHTML = `
            <div class="badge badge-warning" style="width: 100%; justify-content: center; padding: 12px; margin-bottom: 12px;">
                <i class="fas fa-clock"></i> Dev Mode Active
            </div>
            <p style="font-size: 12px; text-align: center; color: var(--text-secondary); margin-bottom: 12px;">
                Expires: ${expiresAt.toLocaleTimeString()}
            </p>
            <button class="btn btn-secondary" style="width: 100%;" onclick="toggleDevMode()">
                <i class="fas fa-stop"></i> Disable Dev Mode
            </button>
        `;
    } else {
        container.innerHTML = `
            <button class="btn btn-secondary" style="width: 100%;" onclick="toggleDevMode()">
                <i class="fas fa-play"></i> Enable Dev Mode
            </button>
        `;
    }
}

async function toggleDevMode() {
    try {
        // Check current status
        const statusResponse = await fetch(`/api/v1/domains/${DOMAIN_ID}/cache/dev-mode`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        const status = await statusResponse.json();
        
        if (status.enabled) {
            // Disable
            await fetch(`/api/v1/domains/${DOMAIN_ID}/cache/dev-mode`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${getToken()}` }
            });
            showNotification('Dev mode disabled', 'success');
        } else {
            // Enable
            await fetch(`/api/v1/domains/${DOMAIN_ID}/cache/dev-mode?duration_minutes=10`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${getToken()}` }
            });
            showNotification('Dev mode enabled for 10 minutes', 'success');
        }
        
        loadDevModeStatus();
    } catch (error) {
        showNotification('Failed to toggle dev mode', 'error');
    }
}

// ==================== Origins ====================

async function loadOrigins() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/origins`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load origins');
        
        const origins = await response.json();
        renderOrigins(origins);
    } catch (error) {
        console.error('Error loading origins:', error);
        document.getElementById('origins-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load origins</p>';
    }
}

function renderOrigins(origins) {
    const container = document.getElementById('origins-list');
    
    if (origins.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No origin servers configured</p>';
        return;
    }
    
    container.innerHTML = origins.map(origin => `
        <div class="glass-card glass-card-sm mb-2">
            <div class="flex-between">
                <div style="flex: 1;">
                    <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                        <strong>${escapeHtml(origin.name)}</strong>
                        ${getHealthBadge(origin.health_status)}
                        ${origin.is_backup ? '<span class="badge badge-info">Backup</span>' : ''}
                        ${origin.enabled ? '' : '<span class="badge" style="background: var(--bg-tertiary);">Disabled</span>'}
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary);">
                        ${origin.protocol}://${escapeHtml(origin.origin_host)}:${origin.origin_port} • Weight: ${origin.weight}
                    </div>
                </div>
                <div class="flex gap-1">
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="checkOriginHealth(${origin.id})" title="Health Check">
                        <i class="fas fa-heartbeat"></i>
                    </button>
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="editOrigin(${origin.id})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                            onclick="deleteOrigin(${origin.id})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function getHealthBadge(status) {
    const badges = {
        'healthy': '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Healthy</span>',
        'unhealthy': '<span class="badge badge-error"><i class="fas fa-times-circle"></i> Unhealthy</span>',
        'unknown': '<span class="badge" style="background: var(--bg-tertiary); color: var(--text-muted);">Unknown</span>'
    };
    return badges[status] || badges['unknown'];
}

function showAddOriginModal() {
    alert('Origin modal - to be implemented');
}

async function checkOriginHealth(originId) {
    try {
        const response = await fetch(`/api/v1/domains/origins/${originId}/health-check`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Health check failed');
        
        const result = await response.json();
        showNotification(`Health: ${result.status}`, 'success');
        loadOrigins();
    } catch (error) {
        showNotification('Health check failed', 'error');
    }
}

async function deleteOrigin(originId) {
    if (!confirm('Delete this origin?')) return;
    
    try {
        const response = await fetch(`/api/v1/domains/origins/${originId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to delete origin');
        
        showNotification('Origin deleted', 'success');
        loadOrigins();
    } catch (error) {
        showNotification('Failed to delete origin', 'error');
    }
}

// ==================== SSL/TLS ====================

async function loadTLSSettings() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/ssl/settings`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load TLS settings');
        
        const settings = await response.json();
        
        document.getElementById('tls-mode').value = settings.mode || 'flexible';
        document.getElementById('force-https').checked = settings.force_https || false;
        document.getElementById('hsts-enabled').checked = settings.hsts_enabled || false;
        document.getElementById('hsts-max-age').value = settings.hsts_max_age || 31536000;
        
    } catch (error) {
        console.error('Error loading TLS settings:', error);
    }
}

async function saveTLSSettings() {
    try {
        const data = {
            mode: document.getElementById('tls-mode').value,
            force_https: document.getElementById('force-https').checked,
            hsts_enabled: document.getElementById('hsts-enabled').checked,
            hsts_max_age: parseInt(document.getElementById('hsts-max-age').value)
        };
        
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/ssl/settings`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${getToken()}`
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) throw new Error('Failed to save settings');
        
        showNotification('TLS settings saved', 'success');
    } catch (error) {
        showNotification('Failed to save TLS settings', 'error');
    }
}

async function loadCertificates() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/ssl/certificates`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load certificates');
        
        const certs = await response.json();
        renderCertificates(certs);
    } catch (error) {
        console.error('Error loading certificates:', error);
        document.getElementById('certificates-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load certificates</p>';
    }
}

function renderCertificates(certs) {
    const container = document.getElementById('certificates-list');
    
    if (certs.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No certificates uploaded</p>';
        return;
    }
    
    container.innerHTML = certs.map(cert => `
        <div class="glass-card glass-card-sm mb-2">
            <div class="flex-between">
                <div style="flex: 1;">
                    <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                        <span class="badge badge-success">Active</span>
                        <strong>${cert.common_name || 'Unknown'}</strong>
                        <span style="font-size: 12px; color: var(--text-secondary);">Expires: ${cert.not_after || 'N/A'}</span>
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary);">
                        Issuer: ${cert.issuer || 'Unknown'}
                    </div>
                </div>
                <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                        onclick="deleteCertificate(${cert.id})" title="Delete">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `).join('');
}

async function requestACME() {
    showNotification('Requesting Let\'s Encrypt certificate...', 'info');
    // Implementation would go here
    alert('ACME request not implemented in frontend yet');
}

function showUploadCertModal() {
    alert('Upload certificate modal - to be implemented');
}

async function deleteCertificate(certId) {
    if (!confirm('Delete this certificate?')) return;
    
    try {
        const response = await fetch(`/api/v1/domains/ssl/certificates/${certId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to delete certificate');
        
        showNotification('Certificate deleted', 'success');
        loadCertificates();
    } catch (error) {
        showNotification('Failed to delete certificate', 'error');
    }
}

// ==================== Security / WAF ====================

async function loadWAFRules() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/waf/rules`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load WAF rules');
        
        const rules = await response.json();
        renderWAFRules(rules);
    } catch (error) {
        console.error('Error loading WAF rules:', error);
        document.getElementById('waf-rules-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load WAF rules</p>';
    }
}

function renderWAFRules(rules) {
    const container = document.getElementById('waf-rules-list');
    
    if (rules.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No WAF rules configured</p>';
        return;
    }
    
    container.innerHTML = rules.map(rule => `
        <div class="glass-card glass-card-sm mb-2">
            <div class="flex-between">
                <div style="flex: 1;">
                    <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                        <span class="badge ${rule.enabled ? 'badge-success' : 'badge-secondary'}">
                            ${rule.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        <span class="badge badge-primary">${rule.action}</span>
                        <strong>${escapeHtml(rule.name)}</strong>
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary);">
                        Priority: ${rule.priority}
                    </div>
                </div>
                <div class="flex gap-1">
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="editWAFRule(${rule.id})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                            onclick="deleteWAFRule(${rule.id})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

async function loadRateLimits() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/security/rate-limits`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load rate limits');
        
        const limits = await response.json();
        renderRateLimits(limits);
    } catch (error) {
        console.error('Error loading rate limits:', error);
        document.getElementById('rate-limits-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load rate limits</p>';
    }
}

function renderRateLimits(limits) {
    const container = document.getElementById('rate-limits-list');
    
    if (limits.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No rate limits configured</p>';
        return;
    }
    
    container.innerHTML = limits.map(limit => `
        <div class="glass-card glass-card-sm mb-2">
            <div class="flex-between">
                <div style="flex: 1;">
                    <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                        <span class="badge ${limit.enabled ? 'badge-success' : 'badge-secondary'}">
                            ${limit.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        <strong>${escapeHtml(limit.name)}</strong>
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary);">
                        ${limit.limit_value} req / ${limit.interval_seconds}s • Action: ${limit.action}
                    </div>
                </div>
                <div class="flex gap-1">
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="editRateLimit(${limit.id})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                            onclick="deleteRateLimit(${limit.id})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

async function loadIPRules() {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/security/ip-rules`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load IP rules');
        
        const rules = await response.json();
        renderIPRules(rules);
    } catch (error) {
        console.error('Error loading IP rules:', error);
        document.getElementById('ip-rules-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load IP rules</p>';
    }
}

function renderIPRules(rules) {
    const container = document.getElementById('ip-rules-list');
    
    if (rules.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No IP rules configured</p>';
        return;
    }
    
    container.innerHTML = rules.map(rule => `
        <div class="glass-card glass-card-sm mb-2">
            <div class="flex-between">
                <div style="flex: 1;">
                    <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                        <span class="badge ${rule.rule_type === 'whitelist' ? 'badge-success' : 'badge-error'}">
                            ${rule.rule_type}
                        </span>
                        <code style="font-size: 14px;">${rule.ip_address}</code>
                    </div>
                    <div style="font-size: 13px; color: var(--text-secondary);">
                        ${escapeHtml(rule.description || 'No description')}
                    </div>
                </div>
                <div class="flex gap-1">
                    <button class="btn btn-icon btn-sm btn-secondary" onclick="editIPRule(${rule.id})" title="Edit">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                            onclick="deleteIPRule(${rule.id})" title="Delete">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function showAddWAFRuleModal() { alert('Not implemented'); }
function showAddRateLimitModal() { alert('Not implemented'); }
function showAddIPRuleModal() { alert('Not implemented'); }
function editWAFRule(id) { alert('Not implemented'); }
function deleteWAFRule(id) { alert('Not implemented'); }
function editRateLimit(id) { alert('Not implemented'); }
function deleteRateLimit(id) { alert('Not implemented'); }
function editIPRule(id) { alert('Not implemented'); }
function deleteIPRule(id) { alert('Not implemented'); }

// Utility functions
function getToken() {
    return localStorage.getItem('auth_token') || '';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
