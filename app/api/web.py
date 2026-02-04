"""Web routes for HTML pages"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.edge_service import EdgeNodeService
from app.services.domain_service import DomainService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_mock_user(request: Request):
    """Get mock user for templates"""
    from app.core.config import settings
    if settings.DEBUG:
        # Return admin user in debug mode
        return {"email": "admin@example.com", "is_superuser": True, "id": 1, "is_active": True}
    return {"email": "user@example.com", "is_superuser": False}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    """Signup page"""
    return templates.TemplateResponse("signup.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard page"""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/domains", response_class=HTMLResponse)
async def domains_page(request: Request):
    """Domains page"""
    return templates.TemplateResponse("domains.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/domains/add", response_class=HTMLResponse)
async def add_domain_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Add domain page"""
    from app.services.dns_node_service import DNSNodeService
    
    # Get enabled DNS nodes
    nodes = await DNSNodeService.get_nodes(db, limit=100)
    dns_nodes = [node.hostname for node in nodes if node.enabled]

    return templates.TemplateResponse("domain_add.html", {
        "request": request,
        "user": get_mock_user(request),
        "dns_nodes": dns_nodes
    })


@router.get("/domains/{domain_id}")
async def domain_overview_redirect(domain_id: int):
    """Redirect to domain settings"""
    return RedirectResponse(url=f"/domains/{domain_id}/settings")


@router.get("/domains/{domain_id}/dns", response_class=HTMLResponse)
async def domain_dns_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain DNS page"""
    from app.services.dns_node_service import DNSNodeService
    
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
        
    # Get enabled DNS nodes
    nodes = await DNSNodeService.get_nodes(db, limit=100)
    dns_nodes = [node.hostname for node in nodes if node.enabled]
        
    return templates.TemplateResponse("domain_dns.html", {
        "request": request,
        "user": get_mock_user(request),
        "domain": domain,
        "dns_nodes": dns_nodes
    })


@router.get("/edge-nodes", response_class=HTMLResponse)
async def edge_nodes_page(request: Request):
    """Edge nodes management page (superuser only)"""
    return templates.TemplateResponse("edge_nodes.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/dns-nodes", response_class=HTMLResponse)
async def dns_nodes_page(request: Request):
    """DNS nodes management page (superuser only)"""
    return templates.TemplateResponse("dns_nodes.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/edge-nodes/{node_id}", response_class=HTMLResponse)
async def edge_node_manage_page(request: Request, node_id: int, db: AsyncSession = Depends(get_db)):
    """Edge node management page"""
    from app.core.config import settings
    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("node_manage.html", {
        "request": request,
        "user": get_mock_user(request),
        "node": node,
        "control_plane_url": settings.PUBLIC_URL
    })


@router.get("/dns-nodes/{node_id}", response_class=HTMLResponse)
async def dns_node_manage_page(request: Request, node_id: int, db: AsyncSession = Depends(get_db)):
    """DNS node management page"""
    from app.services.dns_node_service import DNSNodeService
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("dns_node_manage.html", {
        "request": request,
        "user": get_mock_user(request),
        "node": node
    })


@router.get("/domains/{domain_id}/settings", response_class=HTMLResponse)
async def domain_settings_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain settings page"""
    from app.services.dns_node_service import DNSNodeService
    
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
        
    # Get enabled DNS nodes
    nodes = await DNSNodeService.get_nodes(db, limit=100)
    dns_nodes = [node.hostname for node in nodes if node.enabled]

    return templates.TemplateResponse("domain_settings.html", {
        "request": request,
        "user": get_mock_user(request),
        "domain": domain,
        "dns_nodes": dns_nodes
    })


@router.get("/domains/{domain_id}/waf", response_class=HTMLResponse)
async def domain_waf_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain WAF page"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("domain_waf.html", {
        "request": request,
        "user": get_mock_user(request),
        "domain": domain
    })


@router.get("/domains/{domain_id}/analytics", response_class=HTMLResponse)
async def domain_analytics_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain analytics page"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("domain_analytics.html", {
        "request": request,
        "user": get_mock_user(request),
        "domain": domain
    })


@router.get("/analytics", response_class=HTMLResponse)
async def global_analytics_page(request: Request):
    """Global analytics page"""
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/domains/{domain_id}/logs", response_class=HTMLResponse)
async def domain_logs_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain logs viewer page"""
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("domain_logs.html", {
        "request": request,
        "user": get_mock_user(request),
        "domain": domain
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """User settings page"""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/dns", response_class=HTMLResponse)
async def dns_management_page(request: Request):
    """DNS management page - shows all domains"""
    return templates.TemplateResponse("dns_management.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/waf", response_class=HTMLResponse)
async def waf_management_page(request: Request):
    """WAF management page - shows all domains"""
    return templates.TemplateResponse("waf_management.html", {
        "request": request,
        "user": get_mock_user(request)
    })


@router.get("/cdn", response_class=HTMLResponse)
async def cdn_management_page(request: Request):
    """CDN management page - shows all domains"""
    return templates.TemplateResponse("cdn_management.html", {
        "request": request,
        "user": get_mock_user(request)
    })
