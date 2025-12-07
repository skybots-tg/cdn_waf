## [0.1.0] - 2024-12-07

### Added

#### Core Features
- FastAPI application with async PostgreSQL and Redis support
- User authentication and authorization with JWT tokens
- Organization management with role-based access control
- Domain management with NS verification

#### DNS Management
- DNS records CRUD (A, AAAA, CNAME, MX, TXT, SRV, NS, CAA)
- Proxied vs DNS-only records (orange cloud feature)
- Import/Export DNS zones

#### CDN & Caching
- Origin server configuration with health checks
- Load balancing (round-robin, weighted, failover)
- Cache rules with patterns and TTL
- Cache purge functionality
- Dev mode for debugging

#### Security & WAF
- IP ACL (whitelist/blacklist)
- Rate limiting per IP/path
- WAF rules with custom conditions
- Basic bot protection framework

#### SSL/TLS
- Automatic certificate issuance via ACME/Let's Encrypt
- Manual certificate upload
- TLS modes: Flexible, Full, Strict
- HSTS configuration

#### Edge Nodes
- Edge node registration and management
- Configuration distribution system
- Nginx/OpenResty config generation
- Health monitoring and metrics

#### UI/UX
- Liquid glass design (light + dark theme)
- Responsive layout
- Dashboard with statistics
- Domain management interface
- DNS records management
- Real-time updates

#### API
- RESTful API with OpenAPI/Swagger docs
- API token authentication
- Versioned endpoints (/api/v1)
- Comprehensive error handling

#### Infrastructure
- Docker and Docker Compose support
- Alembic database migrations
- Celery for background tasks
- Redis pub/sub for real-time updates
- Structured logging

#### Documentation
- API documentation
- Deployment guide
- Development guide
- Edge node setup instructions
- Contributing guidelines

### Technical Stack
- Python 3.11+
- FastAPI 0.109
- SQLAlchemy 2.0 (async)
- PostgreSQL 14+
- Redis 7+
- Celery 5.3
- Alembic
- Pydantic 2.5
- HTTPX
- Jinja2

### Known Issues
- WAF rule engine needs full implementation
- Analytics and logging aggregation pending
- HTTP/3 support planned for future release
- Geo-IP filtering needs external service integration

### Security Notes
- All passwords hashed with bcrypt
- JWT tokens for authentication
- HTTPS enforced in production
- SQL injection protection via SQLAlchemy
- XSS protection in templates

