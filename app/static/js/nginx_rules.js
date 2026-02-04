/**
 * Nginx Rules Management for Edge Nodes
 * Handles loading, editing, and applying Nginx configuration rules
 */

// ============================================
// Nginx Rules Data Management
// ============================================

// Track loading state
let nginxRulesLoaded = false;

/**
 * Show loading overlay on nginx tab
 */
function showNginxLoading() {
    const nginxTab = document.getElementById('tab-nginx');
    if (!nginxTab) return;
    
    // Create loading overlay if it doesn't exist
    let overlay = document.getElementById('nginx-loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'nginx-loading-overlay';
        overlay.className = 'nginx-loading-overlay';
        overlay.innerHTML = `
            <div class="nginx-loading-spinner">
                <i class="fas fa-spinner fa-spin"></i>
                <span>Загрузка настроек с ноды...</span>
            </div>
        `;
        nginxTab.style.position = 'relative';
        nginxTab.appendChild(overlay);
    }
    
    overlay.classList.add('visible');
}

/**
 * Hide loading overlay on nginx tab
 */
function hideNginxLoading() {
    const overlay = document.getElementById('nginx-loading-overlay');
    if (overlay) {
        overlay.classList.remove('visible');
    }
}

/**
 * Load current Nginx rules from the server
 */
async function loadNginxRules() {
    // Show loading overlay
    showNginxLoading();
    
    try {
        const response = await api.get(`/edge-nodes/${NODE_ID}/nginx-rules`);
        if (response && response.config) {
            populateNginxForm(response.config);
            nginxRulesLoaded = true;
        }
    } catch (error) {
        console.error('Failed to load nginx rules:', error);
        // Use defaults if can't load
    } finally {
        // Hide loading overlay after a small delay for smooth transition
        setTimeout(() => {
            hideNginxLoading();
        }, 300);
    }
}

/**
 * Populate form fields with config data
 */
function populateNginxForm(config) {
    // Client settings
    if (config.client) {
        setVal('nginx-client-max-body-size', config.client.client_max_body_size, '100m');
        setVal('nginx-client-body-timeout', config.client.client_body_timeout, 60);
        setVal('nginx-client-header-timeout', config.client.client_header_timeout, 60);
        setVal('nginx-client-body-buffer-size', config.client.client_body_buffer_size, '128k');
    }
    
    // WebSocket settings
    if (config.websocket) {
        setChecked('nginx-ws-enabled', config.websocket.enabled !== false);
        setVal('nginx-ws-read-timeout', config.websocket.read_timeout, 3600);
        setVal('nginx-ws-send-timeout', config.websocket.send_timeout, 3600);
        setVal('nginx-ws-connect-timeout', config.websocket.connect_timeout, 60);
    }
    
    // Proxy settings
    if (config.proxy) {
        setVal('nginx-proxy-connect-timeout', config.proxy.proxy_connect_timeout, 60);
        setVal('nginx-proxy-send-timeout', config.proxy.proxy_send_timeout, 60);
        setVal('nginx-proxy-read-timeout', config.proxy.proxy_read_timeout, 60);
        setVal('nginx-proxy-buffer-size', config.proxy.proxy_buffer_size, '4k');
        setVal('nginx-proxy-buffers', config.proxy.proxy_buffers, '8 4k');
    }
    
    // Gzip settings
    if (config.gzip) {
        setChecked('nginx-gzip-enabled', config.gzip.enabled !== false);
        setVal('nginx-gzip-level', config.gzip.comp_level, 6);
        const levelDisplay = document.getElementById('gzip-level-value');
        if (levelDisplay) levelDisplay.textContent = config.gzip.comp_level || 6;
        setVal('nginx-gzip-min-length', config.gzip.min_length, 1000);
    }
    
    // Keepalive settings
    if (config.keepalive) {
        setVal('nginx-keepalive-timeout', config.keepalive.timeout, 65);
        setVal('nginx-keepalive-requests', config.keepalive.requests, 1000);
        setVal('nginx-keepalive-upstream', config.keepalive.upstream_connections, 32);
    }
    
    // HTTP/2 settings
    if (config.http2) {
        setChecked('nginx-http2-enabled', config.http2.enabled !== false);
        setVal('nginx-http2-streams', config.http2.max_concurrent_streams, 128);
    }
    
    // Rate limiting
    if (config.rate_limit) {
        setChecked('nginx-rate-enabled', config.rate_limit.enabled === true);
        setVal('nginx-rate-limit', config.rate_limit.rate, '100r/s');
        setVal('nginx-rate-burst', config.rate_limit.burst, 200);
    }
    
    // Security settings
    if (config.security) {
        setChecked('nginx-hide-version', config.security.server_tokens === false);
        setChecked('nginx-x-frame-options', config.security.add_x_frame_options !== false);
        setChecked('nginx-x-content-type', config.security.add_x_content_type_options !== false);
        setChecked('nginx-x-xss', config.security.add_x_xss_protection !== false);
    }
    
    // SSL settings
    if (config.ssl) {
        const protocols = config.ssl.protocols || ['TLSv1.2', 'TLSv1.3'];
        setChecked('nginx-tls12', protocols.includes('TLSv1.2'));
        setChecked('nginx-tls13', protocols.includes('TLSv1.3'));
        setChecked('nginx-ocsp-stapling', config.ssl.stapling !== false);
        setVal('nginx-ssl-session-timeout', config.ssl.session_timeout, '1d');
    }
    
    // Cache settings
    if (config.cache) {
        setChecked('nginx-cache-enabled', config.cache.enabled !== false);
        setVal('nginx-cache-max-size', config.cache.max_size, '10g');
        setVal('nginx-cache-inactive', config.cache.inactive, '7d');
    }
}

// Helper functions for form population
function setVal(id, value, defaultValue) {
    const el = document.getElementById(id);
    if (el) el.value = value !== undefined && value !== null ? value : defaultValue;
}

function setChecked(id, checked) {
    const el = document.getElementById(id);
    if (el) el.checked = checked;
}

function getVal(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
}

function getInt(id) {
    return parseInt(getVal(id)) || 0;
}

function isChecked(id) {
    const el = document.getElementById(id);
    return el ? el.checked : false;
}

/**
 * Collect all form values into Nginx rules config object
 */
function collectNginxRules() {
    const protocols = [];
    if (isChecked('nginx-tls12')) protocols.push('TLSv1.2');
    if (isChecked('nginx-tls13')) protocols.push('TLSv1.3');
    
    return {
        client: {
            client_max_body_size: getVal('nginx-client-max-body-size'),
            client_body_timeout: getInt('nginx-client-body-timeout'),
            client_header_timeout: getInt('nginx-client-header-timeout'),
            client_body_buffer_size: getVal('nginx-client-body-buffer-size'),
            large_client_header_buffers: "4 16k"
        },
        websocket: {
            enabled: isChecked('nginx-ws-enabled'),
            read_timeout: getInt('nginx-ws-read-timeout'),
            send_timeout: getInt('nginx-ws-send-timeout'),
            connect_timeout: getInt('nginx-ws-connect-timeout')
        },
        proxy: {
            proxy_connect_timeout: getInt('nginx-proxy-connect-timeout'),
            proxy_send_timeout: getInt('nginx-proxy-send-timeout'),
            proxy_read_timeout: getInt('nginx-proxy-read-timeout'),
            proxy_buffer_size: getVal('nginx-proxy-buffer-size'),
            proxy_buffers: getVal('nginx-proxy-buffers'),
            proxy_busy_buffers_size: "8k"
        },
        gzip: {
            enabled: isChecked('nginx-gzip-enabled'),
            comp_level: getInt('nginx-gzip-level'),
            min_length: getInt('nginx-gzip-min-length'),
            types: [
                "text/plain", "text/css", "text/javascript",
                "application/javascript", "application/json",
                "application/xml", "image/svg+xml"
            ],
            vary: true
        },
        ssl: {
            protocols: protocols,
            prefer_server_ciphers: true,
            session_timeout: getVal('nginx-ssl-session-timeout'),
            session_cache: "shared:SSL:50m",
            stapling: isChecked('nginx-ocsp-stapling')
        },
        rate_limit: {
            enabled: isChecked('nginx-rate-enabled'),
            zone_name: "cdn_limit",
            zone_size: "10m",
            rate: getVal('nginx-rate-limit'),
            burst: getInt('nginx-rate-burst'),
            nodelay: true
        },
        cache: {
            enabled: isChecked('nginx-cache-enabled'),
            path: "/var/cache/nginx/cdn",
            zone_name: "cdn_cache",
            zone_size: "100m",
            max_size: getVal('nginx-cache-max-size'),
            inactive: getVal('nginx-cache-inactive'),
            use_stale: ["error", "timeout", "updating", "http_500", "http_502", "http_503", "http_504"],
            valid_codes: {"200": "1d", "301": "1h", "302": "1h", "404": "1m"}
        },
        keepalive: {
            timeout: getInt('nginx-keepalive-timeout'),
            requests: getInt('nginx-keepalive-requests'),
            upstream_connections: getInt('nginx-keepalive-upstream')
        },
        http2: {
            enabled: isChecked('nginx-http2-enabled'),
            max_concurrent_streams: getInt('nginx-http2-streams'),
            max_field_size: "4k",
            max_header_size: "16k"
        },
        security: {
            server_tokens: !isChecked('nginx-hide-version'),
            add_x_frame_options: isChecked('nginx-x-frame-options'),
            add_x_content_type_options: isChecked('nginx-x-content-type'),
            add_x_xss_protection: isChecked('nginx-x-xss')
        }
    };
}

// ============================================
// Nginx Rules Actions
// ============================================

/**
 * Apply Nginx rules to the edge node
 */
async function applyNginxRules() {
    const rules = collectNginxRules();
    
    showNotification('Применение правил Nginx...', 'info');
    
    try {
        const response = await api.put(`/edge-nodes/${NODE_ID}/nginx-rules`, rules);
        
        if (response.success) {
            showNotification('Правила Nginx применены успешно!', 'success');
            if (typeof log === 'function') {
                log('Nginx rules applied successfully', 'success');
                if (response.config_test_output) {
                    log(response.config_test_output);
                }
            }
        } else {
            showNotification(`Ошибка: ${response.message}`, 'error');
            if (typeof log === 'function') {
                log(`Failed to apply nginx rules: ${response.message}`, 'error');
                if (response.config_test_output) {
                    log(response.config_test_output, 'error');
                }
            }
        }
    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
        if (typeof log === 'function') {
            log(`Error applying nginx rules: ${error.message}`, 'error');
        }
    }
}

/**
 * Test Nginx configuration without applying
 */
async function testNginxRules() {
    const rules = collectNginxRules();
    
    showNotification('Тестирование конфигурации...', 'info');
    
    try {
        const response = await api.put(`/edge-nodes/${NODE_ID}/nginx-rules?test_only=true`, rules);
        
        if (response.success) {
            showNotification('Конфигурация корректна!', 'success');
            if (typeof log === 'function' && response.config_test_output) {
                log('Nginx config test: ' + response.config_test_output, 'success');
            }
        } else {
            showNotification(`Ошибка конфигурации: ${response.message}`, 'error');
            if (typeof log === 'function' && response.config_test_output) {
                log('Config test failed: ' + response.config_test_output, 'error');
            }
        }
    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

/**
 * Reset Nginx rules to defaults
 */
async function resetNginxRules() {
    if (!confirm('Сбросить все настройки Nginx на значения по умолчанию?')) {
        return;
    }
    
    showNotification('Сброс настроек...', 'info');
    
    try {
        const response = await api.post(`/edge-nodes/${NODE_ID}/nginx-rules/reset`);
        
        if (response.success) {
            showNotification('Настройки сброшены', 'success');
            await loadNginxRules();
        } else {
            showNotification(`Ошибка: ${response.message}`, 'error');
        }
    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

/**
 * Preview generated Nginx configuration
 */
async function previewNginxConfig() {
    const rules = collectNginxRules();
    const previewEl = document.getElementById('nginx-config-preview');
    
    if (!previewEl) return;
    
    try {
        const response = await api.post(`/edge-nodes/${NODE_ID}/nginx-rules/preview`, rules);
        
        if (response.main_config) {
            previewEl.textContent = response.main_config + 
                '\n\n# === Location snippet (include in server blocks) ===\n' + 
                response.location_snippet;
            previewEl.style.display = 'block';
        }
    } catch (error) {
        previewEl.textContent = `Error: ${error.message}`;
        previewEl.style.display = 'block';
    }
}

// ============================================
// UI Initialization
// ============================================

/**
 * Initialize Nginx rules UI elements
 */
function initNginxRulesUI() {
    // Update gzip level display on slider change
    const gzipSlider = document.getElementById('nginx-gzip-level');
    if (gzipSlider) {
        gzipSlider.addEventListener('input', function() {
            const display = document.getElementById('gzip-level-value');
            if (display) display.textContent = this.value;
        });
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNginxRulesUI);
} else {
    initNginxRulesUI();
}
