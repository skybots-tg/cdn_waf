"""Web routes for HTML pages"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
        "user": {"email": "user@example.com"}  # TODO: Get real user from session
    })


@router.get("/domains", response_class=HTMLResponse)
async def domains_page(request: Request):
    """Domains page"""
    return templates.TemplateResponse("domains.html", {
        "request": request,
        "user": {"email": "user@example.com"}
    })


@router.get("/domains/{domain_id}/dns", response_class=HTMLResponse)
async def domain_dns_page(request: Request, domain_id: int):
    """Domain DNS page"""
    return templates.TemplateResponse("domain_dns.html", {
        "request": request,
        "user": {"email": "user@example.com"},
        "domain": {"id": domain_id, "name": "example.com"}  # TODO: Get real domain
    })


@router.get("/edge-nodes", response_class=HTMLResponse)
async def edge_nodes_page(request: Request):
    """Edge nodes management page (superuser only)"""
    return templates.TemplateResponse("edge_nodes.html", {
        "request": request,
        "user": {"email": "admin@example.com", "is_superuser": True}  # TODO: Get real user
    })


@router.get("/domains/{domain_id}/settings", response_class=HTMLResponse)
async def domain_settings_page(request: Request, domain_id: int):
    """Domain settings page"""
    return templates.TemplateResponse("domain_settings.html", {
        "request": request,
        "user": {"email": "user@example.com"},
        "domain": {"id": domain_id, "name": "example.com"}  # TODO: Get real domain
    })


@router.get("/domains/{domain_id}/waf", response_class=HTMLResponse)
async def domain_waf_page(request: Request, domain_id: int):
    """Domain WAF page"""
    return templates.TemplateResponse("domain_waf.html", {
        "request": request,
        "user": {"email": "user@example.com"},
        "domain": {"id": domain_id, "name": "example.com"}  # TODO: Get real domain
    })


@router.get("/domains/{domain_id}/analytics", response_class=HTMLResponse)
async def domain_analytics_page(request: Request, domain_id: int):
    """Domain analytics page"""
    return templates.TemplateResponse("domain_analytics.html", {
        "request": request,
        "user": {"email": "user@example.com"},
        "domain": {"id": domain_id, "name": "example.com"}  # TODO: Get real domain
    })


@router.get("/analytics", response_class=HTMLResponse)
async def global_analytics_page(request: Request):
    """Global analytics page"""
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "user": {"email": "user@example.com"}  # TODO: Get real user
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """User settings page"""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": {"email": "user@example.com"}  # TODO: Get real user
    })


