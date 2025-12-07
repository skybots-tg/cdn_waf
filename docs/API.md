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


