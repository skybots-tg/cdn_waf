"""Web routes for HTML pages"""
import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError, jwt

from app.core.database import get_db
from app.core.config import settings
from app.services.edge_service import EdgeNodeService
from app.services.domain_service import DomainService

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def get_current_web_user(request: Request, db: AsyncSession = Depends(get_db)):
    """Extract user from the ``access_token`` cookie, falling back to DEBUG admin."""
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            if payload.get("type") == "access":
                user_id = int(payload.get("sub"))
                from app.services.user_service import UserService
                user_service = UserService(db)
                user = await user_service.get_by_id(user_id)
                if user and user.is_active:
                    return {
                        "id": user.id,
                        "email": user.email,
                        "is_superuser": user.is_superuser,
                        "is_active": user.is_active,
                    }
        except (JWTError, ValueError, TypeError):
            pass
    if settings.DEBUG:
        return {"email": "admin@example.com", "is_superuser": True, "id": 1, "is_active": True}
    return None


def _require_user_or_redirect(user):
    """Return ``RedirectResponse`` to /login when user is ``None``."""
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    """Landing page — redirect logged-in users to dashboard."""
    user = await get_current_web_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
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
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Dashboard page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})


@router.get("/domains", response_class=HTMLResponse)
async def domains_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Domains page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("domains.html", {"request": request, "user": user})


@router.get("/domains/add", response_class=HTMLResponse)
async def add_domain_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Add domain page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    from app.services.dns_node_service import DNSNodeService
    nodes = await DNSNodeService.get_nodes(db, limit=100)
    dns_nodes = [node.hostname for node in nodes if node.enabled]

    return templates.TemplateResponse("domain_add.html", {
        "request": request, "user": user, "dns_nodes": dns_nodes
    })


@router.get("/domains/{domain_id}")
async def domain_overview_redirect(domain_id: int):
    """Redirect to domain settings"""
    return RedirectResponse(url=f"/domains/{domain_id}/settings")


@router.get("/domains/{domain_id}/dns", response_class=HTMLResponse)
async def domain_dns_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain DNS page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    from app.services.dns_node_service import DNSNodeService
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    nodes = await DNSNodeService.get_nodes(db, limit=100)
    dns_nodes = [node.hostname for node in nodes if node.enabled]

    return templates.TemplateResponse("domain_dns.html", {
        "request": request, "user": user, "domain": domain, "dns_nodes": dns_nodes
    })


@router.get("/edge-nodes", response_class=HTMLResponse)
async def edge_nodes_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Edge nodes management page (superuser only)"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("edge_nodes.html", {"request": request, "user": user})


@router.get("/dns-nodes", response_class=HTMLResponse)
async def dns_nodes_page(request: Request, db: AsyncSession = Depends(get_db)):
    """DNS nodes management page (superuser only)"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("dns_nodes.html", {"request": request, "user": user})


@router.get("/edge-nodes/{node_id}", response_class=HTMLResponse)
async def edge_node_manage_page(request: Request, node_id: int, db: AsyncSession = Depends(get_db)):
    """Edge node management page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    node = await EdgeNodeService.get_node(db, node_id)
    if not node:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("node_manage.html", {
        "request": request, "user": user, "node": node,
        "control_plane_url": settings.PUBLIC_URL,
    })


@router.get("/dns-nodes/{node_id}", response_class=HTMLResponse)
async def dns_node_manage_page(request: Request, node_id: int, db: AsyncSession = Depends(get_db)):
    """DNS node management page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    from app.services.dns_node_service import DNSNodeService
    node = await DNSNodeService.get_node(db, node_id)
    if not node:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("dns_node_manage.html", {
        "request": request, "user": user, "node": node
    })


@router.get("/domains/{domain_id}/settings", response_class=HTMLResponse)
async def domain_settings_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain settings page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    from app.services.dns_node_service import DNSNodeService
    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    nodes = await DNSNodeService.get_nodes(db, limit=100)
    dns_nodes = [node.hostname for node in nodes if node.enabled]

    return templates.TemplateResponse("domain_settings.html", {
        "request": request, "user": user, "domain": domain, "dns_nodes": dns_nodes
    })


@router.get("/domains/{domain_id}/waf", response_class=HTMLResponse)
async def domain_waf_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain WAF page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("domain_waf.html", {
        "request": request, "user": user, "domain": domain
    })


@router.get("/domains/{domain_id}/analytics", response_class=HTMLResponse)
async def domain_analytics_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain analytics page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("domain_analytics.html", {
        "request": request, "user": user, "domain": domain
    })


@router.get("/analytics", response_class=HTMLResponse)
async def global_analytics_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Global analytics page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("analytics.html", {"request": request, "user": user})


@router.get("/domains/{domain_id}/logs", response_class=HTMLResponse)
async def domain_logs_page(request: Request, domain_id: int, db: AsyncSession = Depends(get_db)):
    """Domain logs viewer page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect

    domain_service = DomainService(db)
    domain = await domain_service.get_by_id(domain_id)
    if not domain:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    return templates.TemplateResponse("domain_logs.html", {
        "request": request, "user": user, "domain": domain
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    """User settings page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("settings.html", {"request": request, "user": user})


@router.get("/dns", response_class=HTMLResponse)
async def dns_management_page(request: Request, db: AsyncSession = Depends(get_db)):
    """DNS management page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("dns_management.html", {"request": request, "user": user})


@router.get("/waf", response_class=HTMLResponse)
async def waf_management_page(request: Request, db: AsyncSession = Depends(get_db)):
    """WAF management page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("waf_management.html", {"request": request, "user": user})


@router.get("/cdn", response_class=HTMLResponse)
async def cdn_management_page(request: Request, db: AsyncSession = Depends(get_db)):
    """CDN management page"""
    user = await get_current_web_user(request, db)
    redirect = _require_user_or_redirect(user)
    if redirect:
        return redirect
    return templates.TemplateResponse("cdn_management.html", {"request": request, "user": user})
