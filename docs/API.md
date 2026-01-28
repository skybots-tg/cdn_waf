# API Documentation

## Authentication

All API endpoints (except `/auth/signup` and `/auth/login`) require authentication using JWT Bearer tokens.

Include the token in the `Authorization` header:

```
Authorization: Bearer <your_token>
```

## Endpoints

### Authentication

#### POST `/api/v1/auth/signup`

Register a new user.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "full_name": "John Doe"
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "email": "user@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "is_superuser": false,
  "totp_enabled": false,
  "created_at": "2024-12-07T10:00:00Z",
  "last_login": null
}
```

#### POST `/api/v1/auth/login`

Login and receive tokens.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

#### GET `/api/v1/auth/me`

Get current user information.

**Response:** `200 OK`
```json
{
  "id": 1,
  "email": "user@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "is_superuser": false,
  "totp_enabled": false,
  "created_at": "2024-12-07T10:00:00Z",
  "last_login": "2024-12-07T11:00:00Z"
}
```

---

### Domains

#### GET `/api/v1/domains/`

List all domains for the current user's organization.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "organization_id": 1,
    "name": "example.com",
    "status": "active",
    "ns_verified": true,
    "ns_verified_at": "2024-12-07T10:00:00Z",
    "verification_token": null,
    "created_at": "2024-12-07T09:00:00Z",
    "updated_at": "2024-12-07T10:00:00Z"
  }
]
```

#### POST `/api/v1/domains/`

Add a new domain.

**Request Body:**
```json
{
  "name": "example.com"
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "organization_id": 1,
  "name": "example.com",
  "status": "pending",
  "ns_verified": false,
  "ns_verified_at": null,
  "verification_token": "abc123...",
  "created_at": "2024-12-07T10:00:00Z",
  "updated_at": "2024-12-07T10:00:00Z"
}
```

#### GET `/api/v1/domains/{domain_id}`

Get domain details.

**Response:** `200 OK`

#### PATCH `/api/v1/domains/{domain_id}`

Update domain.

**Request Body:**
```json
{
  "status": "active"
}
```

#### POST `/api/v1/domains/{domain_id}/verify-ns`

Verify NS records for domain.

**Response:** `200 OK`
```json
{
  "verified": true,
  "domain_id": 1
}
```

---

### DNS Records

#### GET `/api/v1/dns/domains/{domain_id}/records`

List all DNS records for a domain.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "domain_id": 1,
    "type": "A",
    "name": "@",
    "content": "192.0.2.1",
    "ttl": 3600,
    "priority": null,
    "weight": null,
    "proxied": true,
    "comment": "Main website",
    "created_at": "2024-12-07T10:00:00Z",
    "updated_at": "2024-12-07T10:00:00Z"
  }
]
```

#### POST `/api/v1/dns/domains/{domain_id}/records`

Create a new DNS record.

**Request Body:**
```json
{
  "type": "A",
  "name": "www",
  "content": "192.0.2.1",
  "ttl": 3600,
  "proxied": true,
  "comment": "Website"
}
```

**Response:** `201 Created`

#### GET `/api/v1/dns/records/{record_id}`

Get DNS record details.

#### PATCH `/api/v1/dns/records/{record_id}`

Update DNS record.

**Request Body:**
```json
{
  "content": "192.0.2.2",
  "proxied": false
}
```

#### DELETE `/api/v1/dns/records/{record_id}`

Delete DNS record.

**Response:** `204 No Content`

---

### SSL/TLS Certificates

#### GET `/api/v1/domains/{domain_id}/certificates`

List all certificates for a domain.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "common_name": "example.com",
    "status": "issued",
    "issuer": "Let's Encrypt",
    "not_before": "2024-12-07T10:00:00Z",
    "not_after": "2025-03-07T10:00:00Z",
    "created_at": "2024-12-07T10:00:00Z"
  }
]
```

#### GET `/api/v1/domains/{domain_id}/certificates/{cert_id}`

Get certificate details.

**Response:** `200 OK`
```json
{
  "id": 1,
  "common_name": "example.com",
  "status": "issued",
  "type": "acme",
  "issuer": "Let's Encrypt Authority X3",
  "subject": "CN=example.com",
  "not_before": "2024-12-07T10:00:00Z",
  "not_after": "2025-03-07T10:00:00Z",
  "auto_renew": true,
  "renew_before_days": 30,
  "last_renewed_at": null,
  "created_at": "2024-12-07T10:00:00Z"
}
```

#### GET `/api/v1/domains/{domain_id}/certificates/available`

List all subdomains available for certificate issuance (A records without existing certificates).

**Response:** `200 OK`
```json
[
  {
    "subdomain": "@",
    "fqdn": "example.com",
    "dns_record_id": 1,
    "proxied": true,
    "records_count": 1
  },
  {
    "subdomain": "www",
    "fqdn": "www.example.com",
    "dns_record_id": 2,
    "proxied": true,
    "records_count": 1
  }
]
```

#### POST `/api/v1/domains/{domain_id}/certificates/issue`

Issue Let's Encrypt certificate for a subdomain.

**Request Body:**
```json
{
  "subdomain": "@",
  "email": "admin@example.com"
}
```

**Response:** `200 OK`
```json
{
  "status": "pending",
  "message": "Certificate issuance started for example.com",
  "certificate_id": 1,
  "fqdn": "example.com"
}
```

#### POST `/api/v1/domains/{domain_id}/certificates/{cert_id}/renew`

Renew (reissue) an existing certificate.

**Query Parameters:**
- `force` (boolean, default: true) - Force renewal regardless of expiry date

**Response:** `200 OK`
```json
{
  "status": "pending",
  "message": "Certificate renewal started for example.com",
  "old_certificate_id": 1,
  "new_certificate_id": 2,
  "common_name": "example.com"
}
```

#### GET `/api/v1/domains/{domain_id}/certificates/{cert_id}/logs`

Get certificate issuance/renewal logs.

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "level": "info",
    "message": "Certificate issuance started for example.com",
    "details": "{\"subdomain\": \"@\", \"email\": \"admin@example.com\"}",
    "created_at": "2024-12-07T10:00:00Z"
  },
  {
    "id": 2,
    "level": "info",
    "message": "ACME challenge created",
    "details": "{\"challenge_type\": \"http-01\"}",
    "created_at": "2024-12-07T10:01:00Z"
  },
  {
    "id": 3,
    "level": "success",
    "message": "Certificate issued successfully",
    "details": null,
    "created_at": "2024-12-07T10:05:00Z"
  }
]
```

#### DELETE `/api/v1/domains/{domain_id}/certificates/{cert_id}`

Delete a certificate.

**Response:** `200 OK`
```json
{
  "status": "deleted",
  "certificate_id": 1
}
```

---

### Domain Information

#### GET `/api/v1/domains/{domain_id}/info`

Get complete domain information including DNS records, certificates, and settings.

**Response:** `200 OK`
```json
{
  "domain": {
    "id": 1,
    "organization_id": 1,
    "name": "example.com",
    "status": "active",
    "ns_verified": true,
    "ns_verified_at": "2024-12-07T10:00:00Z",
    "created_at": "2024-12-07T09:00:00Z",
    "updated_at": "2024-12-07T10:00:00Z"
  },
  "dns_records": [
    {
      "id": 1,
      "type": "A",
      "name": "@",
      "content": "192.0.2.1",
      "ttl": 3600,
      "proxied": true,
      "created_at": "2024-12-07T10:00:00Z"
    }
  ],
  "certificates": [
    {
      "id": 1,
      "common_name": "example.com",
      "status": "issued",
      "issuer": "Let's Encrypt",
      "not_after": "2025-03-07T10:00:00Z"
    }
  ],
  "stats": {
    "total_dns_records": 5,
    "active_certificates": 2,
    "proxied_records": 3
  }
}
```

#### GET `/api/v1/domains/scan-dns`

Scan existing DNS records for a domain (useful for importing from another DNS provider).

**Query Parameters:**
- `domain` (required) - Domain name to scan
- `nameservers` (optional, can be multiple) - Specific nameservers to query

**Example:**
```
GET /api/v1/domains/scan-dns?domain=example.com
GET /api/v1/domains/scan-dns?domain=example.com&nameservers=ns1.old-provider.com&nameservers=ns2.old-provider.com
```

**Response:** `200 OK`
```json
[
  {
    "type": "A",
    "name": "@",
    "content": "192.0.2.1",
    "ttl": 3600,
    "proxied": true
  },
  {
    "type": "A",
    "name": "www",
    "content": "192.0.2.1",
    "ttl": 3600,
    "proxied": true
  },
  {
    "type": "MX",
    "name": "@",
    "content": "mail.example.com",
    "ttl": 3600,
    "priority": 10,
    "proxied": false
  }
]
```

#### POST `/api/v1/dns/domains/{domain_id}/records/import`

Import multiple DNS records at once.

**Request Body:**
```json
{
  "records": [
    {
      "type": "A",
      "name": "@",
      "content": "192.0.2.1",
      "ttl": 3600,
      "proxied": true
    },
    {
      "type": "A",
      "name": "www",
      "content": "192.0.2.1",
      "ttl": 3600,
      "proxied": true
    }
  ]
}
```

**Response:** `201 Created`
```json
{
  "message": "Imported 2 records",
  "count": 2
}
```

---

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "detail": "Invalid input data"
}
```

### 401 Unauthorized
```json
{
  "detail": "Could not validate credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Not enough permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

### 422 Validation Error
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

---

## Rate Limiting

API endpoints are rate limited:

- **Authentication endpoints**: 10 requests per minute per IP
- **Other endpoints**: 100 requests per minute per user

Rate limit headers are included in responses:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1670410800
```

---

## Pagination

List endpoints support pagination using query parameters:

- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20, max: 100)

Example:
```
GET /api/v1/domains?page=2&per_page=50
```

Response includes pagination metadata:
```json
{
  "items": [...],
  "total": 150,
  "page": 2,
  "per_page": 50,
  "pages": 3
}
```


