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
        // Load both issued and available certificates
        const [certsResponse, availableResponse] = await Promise.all([
            fetch(`/api/v1/domains/${DOMAIN_ID}/certificates`, {
                headers: { 'Authorization': `Bearer ${getToken()}` }
            }),
            fetch(`/api/v1/domains/${DOMAIN_ID}/certificates/available`, {
                headers: { 'Authorization': `Bearer ${getToken()}` }
            })
        ]);
        
        if (!certsResponse.ok) throw new Error('Failed to load certificates');
        
        const certs = await certsResponse.json();
        const available = availableResponse.ok ? await availableResponse.json() : [];
        
        renderCertificates(certs, available);
    } catch (error) {
        console.error('Error loading certificates:', error);
        document.getElementById('certificates-list').innerHTML = 
            '<p style="color: var(--error); text-align: center;">Failed to load certificates</p>';
    }
}

function renderCertificates(certs, available = []) {
    const container = document.getElementById('certificates-list');
    
    let html = '';
    
    // Show available certificates to issue
    if (available.length > 0) {
        html += `
        <div style="margin-bottom: 24px;">
            <h3 style="font-size: 16px; font-weight: 600; margin-bottom: 12px; color: var(--text-secondary);">
                <i class="fas fa-plus-circle"></i> Available to Issue
            </h3>
        `;
        
        available.forEach(avail => {
            html += `
            <div class="glass-card glass-card-sm mb-2" style="background: var(--bg-tertiary);">
                <div class="flex-between">
                    <div style="flex: 1;">
                        <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                            <span class="badge" style="background: var(--accent-light); color: var(--accent-primary);">
                                <i class="fas fa-certificate"></i> Not Issued
                            </span>
                            <strong>${escapeHtml(avail.fqdn)}</strong>
                        </div>
                        <div style="font-size: 13px; color: var(--text-secondary);">
                            Subdomain: ${avail.subdomain === '@' ? 'Root domain' : avail.subdomain}
                        </div>
                    </div>
                    <button class="btn btn-primary btn-sm" 
                            onclick="showIssueCertificateModal('${avail.subdomain}', '${avail.fqdn}')" 
                            title="Issue Certificate">
                        <i class="fas fa-play"></i> Issue
                    </button>
                </div>
            </div>
            `;
        });
        
        html += '</div>';
    }
    
    // Show issued/pending/failed certificates
    if (certs.length > 0) {
        html += `
        <div>
            <h3 style="font-size: 16px; font-weight: 600; margin-bottom: 12px; color: var(--text-secondary);">
                <i class="fas fa-certificate"></i> Issued & Processing
            </h3>
        `;
        
        certs.forEach(cert => {
            const statusBadge = cert.status === 'issued' 
                ? '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Active</span>'
                : cert.status === 'pending'
                ? '<span class="badge badge-orange"><i class="fas fa-clock"></i> Pending</span>'
                : '<span class="badge badge-error"><i class="fas fa-times-circle"></i> Failed</span>';
            
            const expiryDate = cert.not_after ? new Date(cert.not_after).toLocaleDateString() : 'N/A';
            const isExpiringSoon = cert.not_after && new Date(cert.not_after) < new Date(Date.now() + 30*24*60*60*1000);
            
            html += `
            <div class="glass-card glass-card-sm mb-2">
                <div class="flex-between">
                    <div style="flex: 1;">
                        <div class="flex gap-2" style="align-items: center; margin-bottom: 8px;">
                            ${statusBadge}
                            <strong>${escapeHtml(cert.common_name || 'Unknown')}</strong>
                            ${cert.status === 'issued' ? `
                                <span style="font-size: 12px; color: ${isExpiringSoon ? 'var(--error)' : 'var(--text-secondary)'};">
                                    ${isExpiringSoon ? '⚠️ ' : ''}Expires: ${expiryDate}
                                </span>
                            ` : ''}
                        </div>
                        <div style="font-size: 13px; color: var(--text-secondary);">
                            ${cert.issuer ? `Issuer: ${escapeHtml(cert.issuer)}` : 'Processing...'}
                        </div>
                    </div>
                    <div class="flex gap-1">
                        ${cert.status !== 'issued' ? `
                            <button class="btn btn-icon btn-sm btn-secondary" 
                                    onclick="showCertificateLogs(${cert.id})" 
                                    title="View Logs">
                                <i class="fas fa-file-alt"></i>
                            </button>
                        ` : ''}
                        <button class="btn btn-icon btn-sm" style="background: var(--error); color: white;" 
                                onclick="deleteCertificate(${cert.id})" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
            `;
        });
        
        html += '</div>';
    }
    
    if (certs.length === 0 && available.length === 0) {
        html = '<p style="text-align: center; color: var(--text-muted); padding: 16px;">No certificates or subdomains available</p>';
    }
    
    container.innerHTML = html;
}

async function requestACME() {
    if (!confirm('Request Let\'s Encrypt certificate for this domain? This may take a few minutes.')) return;
    
    showNotification('Requesting Let\'s Encrypt certificate...', 'info');
    
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/ssl/certificates/acme`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${getToken()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                wildcard: false // Default to non-wildcard for now
            })
        });
        
        if (!response.ok) throw new Error('Failed to request certificate');
        
        const result = await response.json();
        showNotification('Certificate request submitted. It will be issued in background.', 'success');
        
        // Reload certificates list after delay
        setTimeout(loadCertificates, 5000);
    } catch (error) {
        showNotification('Failed to request certificate', 'error');
        console.error(error);
    }
}

function showUploadCertModal() {
    alert('Upload certificate modal - to be implemented');
}

async function deleteCertificate(certId) {
    if (!confirm('Delete this certificate?')) return;
    
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/certificates/${certId}`, {
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

function showIssueCertificateModal(subdomain, fqdn) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 500px;">
            <div class="modal-header">
                <h3><i class="fas fa-certificate"></i> Issue SSL Certificate</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label class="form-label">Domain</label>
                    <input type="text" class="form-input" value="${escapeHtml(fqdn)}" readonly>
                </div>
                
                <div class="form-group">
                    <label class="form-label">Email for notifications (optional)</label>
                    <input type="email" class="form-input" id="cert-email" 
                           placeholder="your@email.com (uses default if empty)">
                    <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">
                        Used for certificate expiry notifications from Let's Encrypt
                    </p>
                </div>
                
                <div style="background: var(--bg-tertiary); padding: 12px; border-radius: 8px; margin-bottom: 16px;">
                    <p style="font-size: 13px; color: var(--text-secondary); margin: 0;">
                        <i class="fas fa-info-circle"></i> The certificate will be issued automatically via Let's Encrypt. 
                        This process may take 1-3 minutes. You can view the progress in the logs.
                    </p>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="issueCertificate('${subdomain}')">
                    <i class="fas fa-play"></i> Issue Certificate
                </button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Close on outside click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });
}

async function issueCertificate(subdomain) {
    const email = document.getElementById('cert-email')?.value.trim() || 
                  localStorage.getItem('acme_default_email') || null;
    
    closeModal();
    showNotification('Starting certificate issuance...', 'info');
    
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/certificates/issue?subdomain=${encodeURIComponent(subdomain)}${email ? `&email=${encodeURIComponent(email)}` : ''}`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${getToken()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ subdomain, email })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to issue certificate');
        }
        
        const result = await response.json();
        showNotification('Certificate issuance started! Check logs for progress.', 'success');
        
        // Reload certificates after a delay
        setTimeout(loadCertificates, 2000);
        
        // Show logs modal automatically if certificate_id is returned
        if (result.certificate_id) {
            setTimeout(() => showCertificateLogs(result.certificate_id), 3000);
        }
    } catch (error) {
        showNotification(error.message || 'Failed to issue certificate', 'error');
        console.error(error);
    }
}

async function showCertificateLogs(certId) {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/certificates/${certId}/logs`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load logs');
        
        const logs = await response.json();
        
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 700px;">
                <div class="modal-header">
                    <h3><i class="fas fa-file-alt"></i> Certificate Issuance Logs</h3>
                    <button class="modal-close" onclick="closeModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div id="cert-logs-container" style="max-height: 400px; overflow-y: auto;">
                        ${logs.length === 0 ? '<p style="text-align: center; color: var(--text-muted);">No logs yet</p>' : 
                            logs.map(log => {
                                const levelColors = {
                                    'info': 'var(--text-secondary)',
                                    'success': 'var(--success)',
                                    'warning': 'var(--warning)',
                                    'error': 'var(--error)'
                                };
                                const levelIcons = {
                                    'info': 'fa-info-circle',
                                    'success': 'fa-check-circle',
                                    'warning': 'fa-exclamation-triangle',
                                    'error': 'fa-times-circle'
                                };
                                
                                return `
                                <div class="glass-card glass-card-sm mb-2" style="background: var(--bg-tertiary);">
                                    <div style="display: flex; gap: 12px;">
                                        <div style="color: ${levelColors[log.level]}; font-size: 16px; padding-top: 2px;">
                                            <i class="fas ${levelIcons[log.level]}"></i>
                                        </div>
                                        <div style="flex: 1;">
                                            <div style="font-size: 13px; color: var(--text-primary); margin-bottom: 4px;">
                                                ${escapeHtml(log.message)}
                                            </div>
                                            <div style="font-size: 11px; color: var(--text-muted);">
                                                ${new Date(log.created_at).toLocaleString()}
                                            </div>
                                            ${log.details ? `
                                                <div style="font-size: 12px; color: var(--text-secondary); margin-top: 4px; font-family: monospace;">
                                                    ${escapeHtml(log.details)}
                                                </div>
                                            ` : ''}
                                        </div>
                                    </div>
                                </div>
                                `;
                            }).join('')
                        }
                    </div>
                    
                    <div style="margin-top: 16px; display: flex; gap: 8px; justify-content: center;">
                        <button class="btn btn-secondary btn-sm" onclick="refreshCertificateLogs(${certId})">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                        <button class="btn btn-secondary btn-sm" onclick="copyCertificateLogs(${certId})">
                            <i class="fas fa-copy"></i> Copy Logs
                        </button>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-primary" onclick="closeModal()">Close</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Auto-scroll to bottom
        setTimeout(() => {
            const container = document.getElementById('cert-logs-container');
            if (container) container.scrollTop = container.scrollHeight;
        }, 100);
        
        // Close on outside click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    } catch (error) {
        showNotification('Failed to load logs', 'error');
        console.error(error);
    }
}

async function refreshCertificateLogs(certId) {
    closeModal();
    setTimeout(() => showCertificateLogs(certId), 100);
}

async function copyCertificateLogs(certId) {
    try {
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/certificates/${certId}/logs`, {
            headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        
        if (!response.ok) throw new Error('Failed to load logs');
        
        const logs = await response.json();
        
        // Format logs as text
        const logsText = logs.map(log => {
            const timestamp = new Date(log.created_at).toLocaleString();
            let text = `[${timestamp}] ${log.level.toUpperCase()}: ${log.message}`;
            if (log.details) {
                text += `\n  Details: ${log.details}`;
            }
            return text;
        }).join('\n\n');
        
        // Copy to clipboard
        await navigator.clipboard.writeText(logsText);
        showNotification('Logs copied to clipboard!', 'success');
    } catch (error) {
        showNotification('Failed to copy logs', 'error');
        console.error(error);
    }
}

function closeModal() {
    const modals = document.querySelectorAll('.modal-overlay');
    modals.forEach(modal => modal.remove());
}

async function saveACMESettings() {
    const email = document.getElementById('acme-default-email')?.value.trim();
    
    if (!email) {
        showNotification('Please enter an email address', 'warning');
        return;
    }
    
    // Save to localStorage for now (in production, save to backend)
    localStorage.setItem('acme_default_email', email);
    showNotification('ACME settings saved', 'success');
}

// Load ACME settings on page load
function loadACMESettings() {
    const email = localStorage.getItem('acme_default_email') || '';
    const emailInput = document.getElementById('acme-default-email');
    if (emailInput) {
        emailInput.value = email;
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
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/rate-limits`, {
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
        const response = await fetch(`/api/v1/domains/${DOMAIN_ID}/ip-rules`, {
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
    // Try to get token from localStorage (access_token is the main key)
    return localStorage.getItem('access_token') || localStorage.getItem('auth_token') || '';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
