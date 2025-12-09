-- Check TLS settings for ryabich domain
SELECT 
    d.id,
    d.name,
    d.status,
    t.mode,
    t.force_https,
    t.hsts_enabled,
    t.hsts_max_age,
    t.min_tls_version,
    t.auto_certificate,
    c.status as cert_status,
    c.not_after as cert_expires
FROM domains d
LEFT JOIN domain_tls_settings t ON d.id = t.domain_id
LEFT JOIN certificates c ON d.id = c.domain_id AND c.status = 'issued'
WHERE d.name LIKE '%ryabich%'
ORDER BY d.id;

