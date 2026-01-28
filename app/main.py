"""Main FastAPI application"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.redis import redis_client
from app.core.init import init_system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await redis_client.connect()
    # Initialize system (create tables, seed data)
    await init_system()
    yield
    # Shutdown
    await redis_client.disconnect()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="""
# FlareCloud CDN Control Panel API

Мощный API для управления CDN, DNS, SSL сертификатами и WAF правилами.

## Возможности

* 🌐 **Управление доменами** - добавление, верификация, настройка доменов
* 📝 **DNS записи** - полное управление DNS records (A, AAAA, CNAME, MX, TXT, NS)
* 🔒 **SSL/TLS сертификаты** - автоматический выпуск Let's Encrypt сертификатов
* 🛡️ **WAF** - настройка правил безопасности и rate limiting
* 📊 **Аналитика** - статистика трафика и производительности
* 🔑 **API ключи** - управление токенами доступа

## Аутентификация

Большинство эндпоинтов требуют аутентификации. Используйте Bearer токен:

```
Authorization: Bearer YOUR_ACCESS_TOKEN
```

Получить токен: `POST /api/v1/auth/login`
    """,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "auth", "description": "Аутентификация и управление пользователями"},
        {"name": "domains", "description": "Управление доменами"},
        {"name": "dns", "description": "Управление DNS записями"},
        {"name": "certificates", "description": "SSL/TLS сертификаты"},
        {"name": "edge-nodes", "description": "Управление edge нодами (CDN серверы)"},
        {"name": "dns-nodes", "description": "Управление DNS серверами"},
        {"name": "cdn", "description": "CDN настройки"},
        {"name": "security", "description": "WAF и безопасность"},
        {"name": "analytics", "description": "Аналитика и статистика"},
        {"name": "organization", "description": "Управление организацией и командой"},
    ]
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Import and include routers
from app.api.v1 import auth, domains, dns, edge_nodes, dns_nodes, cdn, security, analytics, organization, certificates
from app.api import web, internal

# API routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(domains.router, prefix="/api/v1/domains", tags=["domains"])
app.include_router(certificates.router, prefix="/api/v1/domains", tags=["certificates"])
app.include_router(dns.router, prefix="/api/v1/dns", tags=["dns"])
app.include_router(edge_nodes.router, prefix="/api/v1/edge-nodes", tags=["edge-nodes"])
app.include_router(dns_nodes.router, prefix="/api/v1/dns-nodes", tags=["dns-nodes"])
app.include_router(cdn.router, prefix="/api/v1/domains", tags=["cdn"])
app.include_router(security.router, prefix="/api/v1/domains", tags=["security"])
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
app.include_router(organization.router, prefix="/api/v1/organization", tags=["organization"])

# Internal API for edge nodes
app.include_router(internal.router, prefix="/internal/edge", tags=["internal"])

# Web routes
app.include_router(web.router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "FlareCloud Control Panel API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


@app.get("/.well-known/acme-challenge/{token}")
async def acme_challenge(token: str, request: Request):
    """Public ACME challenge endpoint for Let's Encrypt validation"""
    from fastapi.responses import PlainTextResponse
    from fastapi import HTTPException
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Log request details for debugging
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", "unknown"))
    client_ip = request.headers.get("x-real-ip", request.client.host if request.client else "unknown")
    logger.info(f"ACME challenge request for token: {token[:30]}... from {client_ip} for host: {forwarded_host}")
    
    validation = None
    if redis_client:
        key = f"acme:challenge:{token}"
        validation = await redis_client.get(key)
        logger.info(f"Redis lookup for key: {key}, found: {validation is not None}")
        
        if validation:
            logger.info(f"Returning validation response (length: {len(validation)})")
    
    if not validation:
        logger.warning(f"Challenge token '{token}' not found in Redis")
        raise HTTPException(
            status_code=404,
            detail=f"Challenge token not found"
        )
    
    # Return plain text (required by ACME spec)
    return PlainTextResponse(content=validation)

