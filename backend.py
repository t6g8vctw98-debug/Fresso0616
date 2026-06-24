#!/usr/bin/env python3
"""
BunnyKitchen AI - COMPLETE Unified Backend
Maintains ALL original functionality while fixing schema for unified app compatibility
"""

# Defer evaluation of all type annotations so modern union syntax like
# ``dict | None`` works on Python 3.9 (it is otherwise only valid at runtime
# on Python 3.10+). This makes every annotation a lazy string; nothing in this
# module evaluates annotations at runtime, so it is fully safe.
from __future__ import annotations

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import requests
from bs4 import BeautifulSoup
import json
import re
import os
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urljoin, urlunparse
import traceback
from typing import Dict, List, Optional, Union, Any
from fractions import Fraction

# =============================================================================
# SSRF PROTECTION - URL Validation for Extraction Endpoints
# =============================================================================
import ipaddress
import socket


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if an IP address string is in a blocked/private range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Unparseable → block
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_extraction_url(url: str) -> tuple:
    """
    Validate that a URL is safe to fetch for recipe extraction.

    Returns (is_valid: bool, error_message: str | None).

    Rules:
      - Must be http or https scheme only.
      - Host must not resolve to loopback, private, link-local, multicast,
        reserved, or unspecified IP ranges (SSRF protection).
      - Basic parse must succeed.
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL could not be parsed"

    if parsed.scheme not in ('http', 'https'):
        return False, "Only http and https URLs are permitted"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname"

    # Resolve hostname to IPs and check each one
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except Exception as e:
        return False, f"DNS lookup error: {e}"

    for _fam, _type, _proto, _canon, sockaddr in results:
        ip = sockaddr[0]
        if _is_blocked_ip(ip):
            return False, f"Requests to private/reserved addresses are not permitted"

    return True, None


def _resolve_safe_ip(hostname: str) -> tuple:
    """Resolve `hostname` and return (ip, error). The returned IP is guaranteed
    to NOT be in a blocked/private range. Returns (None, error_message) on
    failure. This is the single resolution we then pin the connection to, so
    the IP we *validated* is the IP we *connect to* (closes the TOCTOU / DNS
    rebinding window).
    """
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except Exception as e:
        return None, f"DNS resolution failed: {e}"
    for _fam, _type, _proto, _canon, sockaddr in results:
        ip = sockaddr[0]
        if not _is_blocked_ip(ip):
            return ip, None
    return None, "Host resolves only to private/reserved addresses"


import threading as _threading
from contextlib import contextmanager as _contextmanager

# NOTE: _pin_lock is process-wide and serializes ALL pinned HTTP fetches
# (DNS-rebinding protection temporarily patches socket.getaddrinfo globally,
# so only one pinned request can be in flight at a time). This is fine for
# single-user / low-traffic use, but becomes a bottleneck under concurrent
# recipe extractions. If you add workers/threads, switch to a per-request
# resolver (e.g. a custom requests transport adapter) to remove this serialization.
_pin_lock = _threading.Lock()
_orig_getaddrinfo = socket.getaddrinfo


@_contextmanager
def _pin_host_to_ip(hostname: str, ip: str):
    """Temporarily force socket.getaddrinfo to return `ip` for `hostname`.

    This guarantees that the IP we *validated* is the IP the socket actually
    *connects to*, closing the DNS-rebinding / TOCTOU window — while leaving the
    original hostname intact for TLS SNI, certificate verification, and the HTTP
    Host header (so HTTPS keeps working). All other hosts resolve normally.

    socket.getaddrinfo is process-global, so we serialize pinned requests with a
    lock to avoid cross-talk between concurrent extractions.
    """
    target = hostname.lower()
    fam = socket.AF_INET6 if ':' in ip else socket.AF_INET

    def _patched(host, port, *args, **kwargs):
        if host and str(host).lower() == target:
            return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (ip, port))]
        return _orig_getaddrinfo(host, port, *args, **kwargs)

    with _pin_lock:
        socket.getaddrinfo = _patched
        try:
            yield
        finally:
            socket.getaddrinfo = _orig_getaddrinfo


def safe_requests_get(url: str, *, headers=None, timeout=15, max_redirects=5):
    """SSRF-hardened HTTP GET.

    Defends against DNS-rebinding / TOCTOU: each hop's hostname is resolved and
    validated once, then the connection is pinned to that exact IP for the
    duration of the request (HTTPS cert/SNI still validate against the real
    hostname).

    Redirects are followed manually so every hop is re-validated; auto-redirects
    are disabled to prevent a public URL from bouncing us to an internal one.

    Returns a requests.Response. Raises ValueError if any hop is disallowed.
    """
    current_url = url
    headers = dict(headers or {})
    for _hop in range(max_redirects + 1):
        parsed = urlparse(current_url)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL has no hostname")
        if parsed.scheme not in ('http', 'https'):
            raise ValueError("Only http and https URLs are permitted")

        ip, ip_err = _resolve_safe_ip(hostname)
        if ip is None:
            raise ValueError(ip_err)

        with _pin_host_to_ip(hostname, ip):
            resp = requests.get(
                current_url, headers=headers, timeout=timeout,
                allow_redirects=False,
            )

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('Location')
            if not location:
                return resp
            current_url = urljoin(current_url, location)
            continue
        return resp
    raise ValueError("Too many redirects")


from flask import make_response

# Load environment variables.
# Load the .env that sits next to this file using an ABSOLUTE path, so the
# SECRET_KEY (and other vars) load correctly no matter which directory the
# server is started from. A plain load_dotenv() only searches the current
# working dir and its parents — if you launch from elsewhere, .env is missed
# and SECRET_KEY silently falls back to a generated key, which breaks JWT
# validation. override=True ensures .env wins over any stale shell exports.
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(_ENV_PATH, override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try NEW API first (openai >= 1.0.0)
try:
        from openai import OpenAI
        logger.info("OpenAI new API library detected")
        OPENAI_NEW_API = True
except ImportError:
        OpenAI = None
        OPENAI_NEW_API = False
        logger.warning("OpenAI library not installed")

# NOTE: OpenAI client is initialized exactly once, later in this file (after the
# Flask app config block), via init_openai_client(). We intentionally do NOT
# initialize it here to avoid the previous double-initialization bug where this
# block created a client and a second block silently overwrote it with None.
openai_client = None
openai_api_key = None



# Add these imports at the top with your other imports

# =============================================================================
# FRACTION AND RANGE PARSING UTILITIES - Day 2 Enhancement
# =============================================================================

def parse_quantity(quantity_str):
    """Parse ingredient quantity supporting fractions, ranges, unicode"""
    if not quantity_str or not isinstance(quantity_str, str):
        return None, quantity_str

    # Unicode fraction replacements
    unicode_fractions = {
        '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4',
        '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5', '⅙': '1/6',
        '⅚': '5/6', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8'
    }

    text = quantity_str.strip()
    for unicode_frac, ascii_frac in unicode_fractions.items():
        text = text.replace(unicode_frac, ascii_frac)

    # Handle ranges (take average for scaling)
    range_patterns = [
        r'(\d+(?:\s+\d+/\d+|\.\d+|/\d+)?)\s*[-–—to]\s*(\d+(?:\s+\d+/\d+|\.\d+|/\d+)?)',
        r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)'
    ]

    for pattern in range_patterns:
        range_match = re.search(pattern, text)
        if range_match:
            try:
                min_val = float(Fraction(range_match.group(1).replace(' ', '+')))
                max_val = float(Fraction(range_match.group(2).replace(' ', '+')))
                return (min_val + max_val) / 2, quantity_str
            except (ValueError, ZeroDivisionError):
                logger.debug("parse_quantity: failed to parse range %r", quantity_str)
                continue

    # Handle mixed numbers (1 1/2)
    mixed_match = re.search(r'(\d+)\s+(\d+/\d+)', text)
    if mixed_match:
        try:
            whole = int(mixed_match.group(1))
            frac = float(Fraction(mixed_match.group(2)))
            return whole + frac, quantity_str
        except (ValueError, ZeroDivisionError):
            logger.debug("parse_quantity: failed to parse mixed number %r", quantity_str)

    # Handle simple fractions and decimals
    simple_patterns = [
        r'(\d+/\d+)',  # 1/2, 3/4
        r'(\d+\.\d+)',  # 2.5
        r'(\d+)'  # 3
    ]

    for pattern in simple_patterns:
        simple_match = re.search(pattern, text)
        if simple_match:
            try:
                return float(Fraction(simple_match.group(1))), quantity_str
            except (ValueError, ZeroDivisionError):
                logger.debug("parse_quantity: failed to parse simple value %r", quantity_str)
                continue

    return None, quantity_str


def format_quantity(value, original_text=""):
    """Format numeric value back to readable culinary fraction"""
    if not isinstance(value, (int, float)):
        return original_text or str(value)

    # Handle zero and negative
    if value <= 0:
        return original_text or "0"

    # Common culinary fractions with tolerance
    common_fractions = {
        0.125: '⅛', 0.25: '¼', 0.333: '⅓', 0.375: '⅜',
        0.5: '½', 0.625: '⅝', 0.667: '⅔', 0.75: '¾', 0.875: '⅞'
    }

    # Check if it's close to a whole number
    if abs(value - round(value)) < 0.01:
        return str(int(round(value)))

    # Check for exact common fractions
    for decimal, fraction in common_fractions.items():
        if abs(value - decimal) < 0.01:
            return fraction

    # Check for mixed numbers
    whole_part = int(value)
    decimal_part = value - whole_part

    if whole_part > 0 and decimal_part > 0.05:  # Avoid tiny decimals
        for decimal, fraction in common_fractions.items():
            if abs(decimal_part - decimal) < 0.01:
                return f"{whole_part} {fraction}"

    # Try to convert to simple fraction
    try:
        frac = Fraction(value).limit_denominator(16)  # Limit to reasonable denominators
        if frac.denominator <= 16 and frac.numerator <= 50:
            if frac.numerator > frac.denominator:
                # Mixed number
                whole = frac.numerator // frac.denominator
                remainder = frac.numerator % frac.denominator
                if remainder > 0:
                    return f"{whole} {remainder}/{frac.denominator}"
                else:
                    return str(whole)
            else:
                # Simple fraction
                return f"{frac.numerator}/{frac.denominator}"
    except (ValueError, ZeroDivisionError, AttributeError):
        logger.debug("format_quantity: falling back to decimal")

    # Fallback to decimal with reasonable precision
    if value < 1:
        return f"{value:.2f}".rstrip('0').rstrip('.')
    else:
        return f"{value:.1f}".rstrip('0').rstrip('.')


def extract_ingredient_parts(ingredient_text):
    """Extract quantity, unit, and ingredient name from ingredient text"""
    if not ingredient_text:
        return None, None, ingredient_text

    text = ingredient_text.strip()

    # Pattern to match quantity and unit at start of ingredient.
    # Order matters: try richest patterns first (mixed numbers), then ranges,
    # then plain fractions, then unicode fractions, then decimals/integers.
    patterns = [
        # Mixed number: "2 1/2 cups flour"
        r'^(\d+\s+\d+/\d+)\s+([a-zA-Z\.]+)(?:\s+(.+))?$',
        # Range: "2-3 tbsp oil" or "2 to 3 tbsp oil"
        r'^(\d+(?:\.\d+)?\s*(?:[-–—]|to)\s*\d+(?:\.\d+)?)\s+([a-zA-Z\.]+)(?:\s+(.+))?$',
        # Plain fraction: "1/2 cup sugar"
        r'^(\d+/\d+)\s+([a-zA-Z\.]+)(?:\s+(.+))?$',
        # Decimal: "2.5 cups flour"
        r'^(\d+\.\d+)\s+([a-zA-Z\.]+)(?:\s+(.+))?$',
        # Integer: "2 cups flour"
        r'^(\d+)\s+([a-zA-Z\.]+)(?:\s+(.+))?$',
        # Unicode fractions: "½ cup flour" or "1½ cup flour"
        r'^(\d*\s*[½¼¾⅓⅔⅛⅜⅝⅞])\s+([a-zA-Z\.]+)(?:\s+(.+))?$'
    ]

    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            quantity_str = match.group(1)
            unit = match.group(2).rstrip('.')
            ingredient_name = match.group(3) or ""

            # Parse quantity using our parser
            quantity_value, _ = parse_quantity(quantity_str)

            return quantity_value, unit, ingredient_name.strip()

    # If no pattern matches, check for just quantity at start
    qty_match = re.match(r'^(\d+(?:\s+\d+/\d+|\s*\d+/\d+|\.\d+|[½¼¾⅓⅔⅛⅜⅝⅞])?)', text)
    if qty_match:
        quantity_str = qty_match.group(1)
        quantity_value, _ = parse_quantity(quantity_str)
        remainder = text[len(quantity_str):].strip()
        return quantity_value, None, remainder

    return None, None, ingredient_text


def scale_ingredient_quantity(ingredient_text, scale_factor):
    """Scale ingredient quantities with proper fraction handling"""
    if not ingredient_text or scale_factor <= 0:
        return ingredient_text

    # Parse the ingredient into parts
    quantity_value, unit, ingredient_name = extract_ingredient_parts(ingredient_text)

    if quantity_value is None:
        return ingredient_text  # No quantity found, return as-is

    # Scale the quantity
    scaled_value = quantity_value * scale_factor

    # Format back to fraction
    formatted_quantity = format_quantity(scaled_value, ingredient_text)

    # Reconstruct the ingredient string
    if formatted_quantity and unit:
        return f"{formatted_quantity} {unit} {ingredient_name}".strip()
    elif formatted_quantity:
        return f"{formatted_quantity} {ingredient_name}".strip()
    else:
        return ingredient_name.strip() if ingredient_name else ingredient_text


def scale_recipe(recipe_data, new_servings):
    original_servings = int(recipe_data.get("servings", 4)) if recipe_data.get("servings") else 4
    logger.info(
        f"DEBUG: original_servings={original_servings} (type: {type(original_servings)}), new_servings={new_servings} (type: {type(new_servings)})")
    if original_servings == new_servings:
        return recipe_data
    scaling_factor = new_servings / original_servings
    scaled_ingredients = []
    ingredients = recipe_data.get("ingredients", [])
    if isinstance(ingredients, str):
        try:
            ingredients = json.loads(ingredients)
        except Exception:
            ingredients = [ingredients]
    for ingredient in ingredients:
        if isinstance(ingredient, dict):
            ingredient_text = ingredient.get("ingredient", ingredient.get("text", ""))
        else:
            ingredient_text = ingredient
        scaled_text = scale_ingredient_quantity(ingredient_text, scaling_factor)
        if isinstance(ingredient, dict):
            scaled_ingredient = ingredient.copy()
            scaled_ingredient["ingredient"] = scaled_text
            scaled_ingredient["text"] = scaled_text
        else:
            scaled_ingredient = scaled_text
        scaled_ingredients.append(scaled_ingredient)
    scaled_recipe = recipe_data.copy()
    scaled_recipe["ingredients"] = scaled_ingredients
    scaled_recipe["servings"] = new_servings
    scaled_recipe["originalServings"] = original_servings
    scaled_recipe["scalingFactor"] = round(scaling_factor, 2)
    return scaled_recipe



# =============================================================================
# END FRACTION AND RANGE PARSING UTILITIES
# =============================================================================

# (.env and logging are configured once near the top of the file; the
# previously duplicated load_dotenv()/logging.basicConfig() calls here were
# redundant and have been removed.)
# AI Extraction Configuration
USE_AI_EXTRACTION = os.getenv('USE_AI_EXTRACTION', 'true').lower() == 'true'
AI_MODEL = os.getenv('AI_MODEL', 'gpt-4o-mini')
AI_MAX_TOKENS = int(os.getenv('AI_MAX_TOKENS', '2000'))
AI_TEMPERATURE = float(os.getenv('AI_TEMPERATURE', '0.1'))
AI_COST_TRACKING = os.getenv('AI_COST_TRACKING', 'true').lower() == 'true'

# Cost tracking variables
ai_extraction_count = 0
ai_total_cost = 0.0
ai_total_tokens = 0


# Initialize Flask app
app = Flask(__name__)

# ── SECRET_KEY ──────────────────────────────────────────────────────────────
# Production: set SECRET_KEY env var to a strong random value.
# Development/test: if not set and FLASK_ENV != production, generate a
# per-process ephemeral key and log a warning so developers notice.
# In production without a key we abort startup to prevent silent insecurity.
_raw_secret = os.environ.get('SECRET_KEY', '').strip()
_flask_env  = os.environ.get('FLASK_ENV', 'development').lower()

if _raw_secret:
    app.config['SECRET_KEY'] = _raw_secret
elif _flask_env == 'production':
    raise RuntimeError(
        "SECRET_KEY environment variable must be set in production. "
        "Refusing to start with an insecure default."
    )
else:
    # Dev/test: persist a generated key to instance/.secret_key so the same
    # key survives restarts. This avoids invalidating sessions on every
    # `python backend.py` run while still being safe (file is gitignored
    # and only created when SECRET_KEY is unset).
    import secrets as _secrets_mod
    _secret_path = os.path.join(app.instance_path, '.secret_key')
    os.makedirs(app.instance_path, exist_ok=True)
    if os.path.exists(_secret_path):
        try:
            with open(_secret_path, 'r', encoding='utf-8') as _f:
                _dev_key = _f.read().strip()
            if not _dev_key:
                raise ValueError('empty key file')
            logger.info("Loaded persistent dev SECRET_KEY from instance/.secret_key")
        except Exception as _key_err:
            logger.warning(f"Could not read .secret_key, regenerating: {_key_err}")
            _dev_key = _secrets_mod.token_hex(32)
            with open(_secret_path, 'w', encoding='utf-8') as _f:
                _f.write(_dev_key)
            os.chmod(_secret_path, 0o600)
    else:
        _dev_key = _secrets_mod.token_hex(32)
        with open(_secret_path, 'w', encoding='utf-8') as _f:
            _f.write(_dev_key)
        os.chmod(_secret_path, 0o600)
        logger.warning(
            "⚠️  SECRET_KEY is not set. Generated a persistent dev key at "
            "instance/.secret_key. Set SECRET_KEY env var in production."
        )
    app.config['SECRET_KEY'] = _dev_key
    del _secrets_mod, _dev_key, _secret_path

del _raw_secret, _flask_env

# [auth-debug] Print a non-secret fingerprint of SECRET_KEY at startup so we can
# confirm it is stable across restarts/processes (a changing fingerprint means
# tokens minted before a restart will fail to validate). Never logs the key.
try:
    import hashlib as _hl
    _fp = _hl.sha256(app.config['SECRET_KEY'].encode()).hexdigest()[:12]
    logger.info(f"[auth-debug] SECRET_KEY fingerprint: {_fp} | source: "
                f"{'env/.env' if os.environ.get('SECRET_KEY','').strip() else 'instance/.secret_key (generated)'}")
    logger.info("[auth-debug] BUILD MARKER: timezone-fix v2 (tokens minted with datetime.now(timezone.utc))")
    del _hl, _fp
except Exception:
    logger.debug("auth-debug fingerprint logging skipped", exc_info=True)

# ── Database ─────────────────────────────────────────────────────────────────
# Use absolute path inside Flask's instance folder. Flask uses 3-slash URIs as
# relative to its instance_path, which made the original 'sqlite:///instance/...'
# resolve to instance/instance/... and fail to open. We now use a 4-slash
# absolute URI tied to app.instance_path and ensure the folder exists.
os.makedirs(app.instance_path, exist_ok=True)
_default_db_path = os.path.join(app.instance_path, 'bunnykitchen-complete.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', f'sqlite:///{_default_db_path}'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ── Debug mode ───────────────────────────────────────────────────────────────
# Controlled by FLASK_DEBUG env var; defaults to False (safe for production).
_debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')
app.config['DEBUG'] = _debug_mode

# ── CORS origins ─────────────────────────────────────────────────────────────
# Set CORS_ORIGINS env var to a comma-separated list of allowed origins.
# Defaults to common localhost dev ports (5000/5200/5173/3000/5001) so local dev
# works without wildcard exposure. The Fresso web frontend runs on :5000 or
# :5200 (5200 is used when macOS AirPlay Receiver occupies :5000).
_cors_env = os.environ.get('CORS_ORIGINS', '').strip()
if _cors_env == '*':
    _cors_origins = '*'
    logger.warning(
        "⚠️  CORS_ORIGINS is set to '*' (wildcard). This allows requests from ANY "
        "origin. Do NOT combine a wildcard with credentialed requests "
        "(supports_credentials=True). Use an explicit comma-separated allowlist "
        "in production."
    )
elif _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(',') if o.strip()]
else:
    # Safe default: allow localhost dev origins (Vite/React) so the Fresso
    # frontend can call the API during local development.
    _cors_origins = ['http://localhost:5001', 'http://127.0.0.1:5001',
                     'http://localhost:5173', 'http://127.0.0.1:5173',
                     'http://localhost:3000', 'http://127.0.0.1:3000',
                     'http://localhost:5000', 'http://127.0.0.1:5000',
                     'http://localhost:5200', 'http://127.0.0.1:5200']

# Initialize extensions
db = SQLAlchemy(app)
CORS(app, resources={r"/api/*": {"origins": _cors_origins}}, supports_credentials=False, max_age=int(timedelta(hours=1).total_seconds()))
# Keep _cors_origins available for the after_request CORS echo handler below.
_CORS_ORIGINS = _cors_origins
del _cors_env, _cors_origins


# ── API versioning (v1) ─────────────────────────────────────────────────────
# All endpoints are defined once under `/api/...` and exposed *also* under
# `/api/v1/...` via a WSGI middleware that rewrites the path *before* Flask
# routes the request. This gives us:
#   • Stable contract for web/iOS clients: they hit `/api/v1/...`
#   • Backwards compatibility: legacy `/api/...` paths keep working during
#     the transition (eventually we can deprecate and remove them).
#   • Zero per-route boilerplate: no Blueprint refactor needed.
# Using a `before_request` hook does NOT work because Flask resolves the URL
# rule *before* dispatching `before_request`, so editing PATH_INFO there is
# too late. WSGI middleware runs first.
API_CURRENT_VERSION = 'v1'
API_SUPPORTED_VERSIONS = {'v1'}


class _ApiVersionRewriteMiddleware:
    """Strip /api/<vN>/ prefix → /api/, tagging the env with the version.

    Unknown versions short-circuit with a JSON 404 — they never hit Flask.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path.startswith('/api/'):
            segments = path.split('/', 3)  # ['', 'api', '<ver>', '<rest>']
            if len(segments) >= 3:
                candidate = segments[2]
                looks_versioned = (len(candidate) >= 2
                                    and candidate[0] == 'v'
                                    and candidate[1:].isdigit())
                if looks_versioned:
                    if candidate not in API_SUPPORTED_VERSIONS:
                        # This response bypasses Flask's error handlers, so log
                        # it here explicitly for observability.
                        logger.warning(
                            "Rejected unsupported API version '%s' for path '%s'",
                            candidate, path,
                        )
                        body = json.dumps({
                            'error': 'unsupported_api_version',
                            'message': f"API version '{candidate}' is not supported.",
                            'supported_versions': sorted(API_SUPPORTED_VERSIONS),
                            'current_version': API_CURRENT_VERSION,
                        }).encode('utf-8')
                        start_response('404 Not Found', [
                            ('Content-Type', 'application/json; charset=utf-8'),
                            ('Content-Length', str(len(body))),
                            ('X-API-Version', candidate),
                        ])
                        return [body]
                    rest = '/' + segments[3] if len(segments) == 4 else '/'
                    environ['PATH_INFO']            = '/api' + rest
                    environ['fresso.api_version']   = candidate
        return self.wsgi_app(environ, start_response)


app.wsgi_app = _ApiVersionRewriteMiddleware(app.wsgi_app)


# ── Pagination helpers ───────────────────────────────────────────────────
def _parse_pagination(default_per_page: int = 20, max_per_page: int = 100) -> tuple[int, int]:
    """Read `page` and `per_page` query params, with safe bounds.

    Mobile clients on slow networks need small page sizes; max_per_page caps
    naive `?per_page=10000` requests that would otherwise OOM the server.
    """
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page


def _pagination_dict(paginated) -> dict:
    """Standard Flask-SQLAlchemy paginate → client-friendly metadata."""
    return {
        'page':       paginated.page,
        'per_page':   paginated.per_page,
        'total':      paginated.total,
        'pages':      paginated.pages,
        'has_next':   paginated.has_next,
        'has_prev':   paginated.has_prev,
        'next_page':  paginated.next_num if paginated.has_next else None,
        'prev_page':  paginated.prev_num if paginated.has_prev else None,
    }


@app.after_request
def _add_api_version_header(response):
    """Echo the served API version in a response header for client telemetry."""
    from flask import request as _req
    version = _req.environ.get('fresso.api_version')
    if version:
        response.headers['X-API-Version'] = version
    elif _req.path.startswith('/api/'):
        response.headers['X-API-Version'] = 'legacy'
    return response

@app.after_request
def add_cors_headers(resp):
    # flask-cors handles most cases, but the /api/v1 -> /api WSGI prefix rewrite
    # means the rewritten request can miss flask-cors' Allow-Origin handling.
    # To be robust (and to avoid the localhost vs 127.0.0.1 mismatch), we echo
    # the request Origin back ourselves when it is an allowed/local dev origin.
    from flask import request as _req
    origin = _req.headers.get('Origin')
    if origin and 'Access-Control-Allow-Origin' not in resp.headers:
        allow = False
        if _CORS_ORIGINS == '*':
            allow = True
        elif isinstance(_CORS_ORIGINS, (list, tuple)) and origin in _CORS_ORIGINS:
            allow = True
        else:
            # Always permit local development origins regardless of port
            # (covers http://localhost:<port> and http://127.0.0.1:<port>).
            try:
                from urllib.parse import urlparse
                host = urlparse(origin).hostname
                if host in ('localhost', '127.0.0.1', '::1'):
                    allow = True
            except (ValueError, AttributeError):
                logger.debug("CORS: failed to parse origin %r", origin)
        if allow:
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers.setdefault('Vary', 'Origin')
    resp.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization")
    resp.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    return resp

# Initialize OpenAI (single source of truth).
def init_openai_client():
    """Initialize the OpenAI client exactly once and return (client, api_key).

    Reads OPENAI_API_KEY from the environment (already populated by load_dotenv
    at the top of the file). Sets the module-level `openai_client` and
    `openai_api_key` globals so the rest of the app can reference them safely
    even if initialization fails (they stay None / falsy rather than unbound).
    """
    global openai_client, openai_api_key
    openai_api_key = os.environ.get('OPENAI_API_KEY')
    openai_client = None

    if openai_api_key:
        if OPENAI_NEW_API and OpenAI is not None:
            try:
                openai_client = OpenAI(api_key=openai_api_key)
                logger.info("✅ OpenAI client initialized successfully (New API)")
            except Exception as e:
                logger.warning(f"❌ OpenAI new API initialization failed: {e}")
        else:
            try:
                openai.api_key = openai_api_key
                logger.info("✅ OpenAI client initialized successfully (Legacy API)")
            except Exception as e:
                logger.warning(f"❌ OpenAI legacy API initialization failed: {e}")
    else:
        logger.info("⚠️ OpenAI API key not found. AI features will be limited.")
    return openai_client, openai_api_key


init_openai_client()

# API Ninjas key for nutrition data
api_ninjas_key = os.environ.get('API_NINJAS_KEY')

# ============================================================================
# USER MODEL - Multi-user authentication support
# ============================================================================
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import hashlib


def utcnow() -> datetime:
    """Single source of truth for "now" in DB datetime columns.

    Returns a timezone-aware UTC datetime. Using this everywhere (column
    defaults, expiry assignments, and comparisons) eliminates the previous bug
    where naive `datetime.utcnow()` values were compared against aware ones,
    which raises TypeError. JWT epoch timestamps use their own aware-UTC path.

    NOTE: SQLite stores datetimes without tzinfo, so values read back from the
    DB are naive. Comparisons happen via the helpers below which normalise
    both sides, so mixing is safe.
    """
    return datetime.now(timezone.utc)


def _as_aware_utc(dt):
    """Normalise a (possibly naive, SQLite-loaded) datetime to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hash_token(raw_token: str) -> str:
    """sha256 hex digest used for session tokens at rest.

    Session tokens are 256 bits of entropy from secrets.token_urlsafe(32),
    so a fast hash like sha256 is appropriate (no need for bcrypt/argon2).
    The hash lets us avoid storing plaintext tokens in the DB; if the DB is
    leaked, attackers cannot resume sessions.
    """
    if not raw_token:
        return ''
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


class User(db.Model):
    """User model for authentication and recipe ownership"""
    __tablename__ = 'users'

    # Basic info
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100))

    # Session management.
    # `session_token` is kept for backward compatibility with sessions issued
    # before the hash migration. New sessions populate `session_token_hash`
    # (sha256 of the raw token); the raw token is only ever returned to the
    # client on login/signup and never stored in plaintext after that.
    session_token = db.Column(db.String(100), unique=True, index=True)
    session_token_hash = db.Column(db.String(64), unique=True, index=True)
    session_expires = db.Column(db.DateTime)

    # User preferences
    default_servings = db.Column(db.Integer, default=4)
    preferred_units = db.Column(db.String(20), default='metric')
    # Preferred UI language (i18n). One of: ru, en, it, es, fr, de.
    language = db.Column(db.String(5), nullable=False, default='ru', server_default='ru')

    # Timestamps
    created_at = db.Column(db.DateTime, default=utcnow)
    last_login = db.Column(db.DateTime)

    # Relationships
    recipes = db.relationship('Recipe', backref='owner', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        """Hash and store password securely"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify password against stored hash"""
        return check_password_hash(self.password_hash, password)

    def generate_session_token(self):
        """Create new session token with 30-day expiry.

        Returns the raw token (caller must send it to the client). Only the
        sha256 hash is persisted in the DB. The legacy `session_token` column
        is cleared so old plaintext rows are eventually phased out.
        """
        raw_token = secrets.token_urlsafe(32)
        self.session_token_hash = _hash_token(raw_token)
        self.session_token = None  # never store plaintext in DB anymore
        self.session_expires = utcnow() + timedelta(days=30)
        return raw_token

    def is_session_valid(self):
        """Check if current session token is still valid."""
        has_token = bool(self.session_token_hash or self.session_token)
        exp = _as_aware_utc(self.session_expires)
        return has_token and exp is not None and exp > utcnow()

    def __repr__(self):
        return f'<User {self.username}>'


# ── JWT access tokens + refresh tokens ─────────────────────────────────────
import jwt as _jwt

# Lifetimes (constants — keep in sync with frontend/mobile clients).
ACCESS_TOKEN_TTL  = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
JWT_ALGORITHM     = 'HS256'


def _jwt_secret() -> str:
    """JWT signing key. Reuses Flask SECRET_KEY — same trust boundary."""
    return app.config['SECRET_KEY']


def issue_access_token(user_id: int) -> tuple[str, int]:
    """Mint a short-lived JWT access token. Returns (token, expires_in_seconds).

    Includes a random `jti` so back-to-back refreshes always produce distinct
    tokens even within the same second — useful for client-side dedup and logs.

    IMPORTANT: use timezone-aware UTC. A naive datetime.utcnow().timestamp()
    is interpreted in LOCAL time by Python, so in any non-UTC timezone the
    `iat`/`exp` epoch values are shifted by the UTC offset — which made tokens
    look already-expired (e.g. on a UTC+3 / Moscow machine). Using an aware UTC
    datetime makes .timestamp() correct in every timezone.
    """
    now = datetime.now(timezone.utc)
    exp = now + ACCESS_TOKEN_TTL
    payload = {
        'sub':  str(user_id),
        'iat':  int(now.timestamp()),
        'exp':  int(exp.timestamp()),
        'jti':  secrets.token_hex(8),
        'type': 'access',
    }
    token = _jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, int(ACCESS_TOKEN_TTL.total_seconds())


def decode_access_token(token: str) -> Optional[dict]:
    """Validate JWT and return payload, or None if invalid/expired."""
    try:
        # leeway absorbs minor clock differences between issuer and validator.
        payload = _jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM],
                              leeway=30)
        if payload.get('type') != 'access':
            logger.warning(f"[auth-debug] token decoded but type != access: type={payload.get('type')!r}")
            return None
        return payload
    except _jwt.ExpiredSignatureError:
        logger.warning("[auth-debug] JWT access token EXPIRED (clock/TTL issue?)")
        return None
    except _jwt.InvalidTokenError as exc:
        logger.warning(f"[auth-debug] JWT decode FAILED: {type(exc).__name__}: {exc}")
        return None
    except Exception as exc:
        logger.warning(f"[auth-debug] JWT decode unexpected error: {type(exc).__name__}: {exc}")
        return None


class RefreshToken(db.Model):
    """Opaque, rotatable refresh token. Only sha256 hash stored in DB.

    Lifecycle:
      * Login/signup mints (access JWT, refresh).
      * /auth/refresh accepts refresh → returns new access + rotates refresh
        (old refresh marked revoked). This limits the blast radius of theft.
      * /auth/logout revokes the presented refresh token.
    """
    __tablename__ = 'refresh_tokens'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                             nullable=False, index=True)
    token_hash   = db.Column(db.String(64), unique=True, nullable=False, index=True)
    expires_at   = db.Column(db.DateTime, nullable=False)
    created_at   = db.Column(db.DateTime, default=utcnow, nullable=False)
    revoked_at   = db.Column(db.DateTime)
    # Audit trail for security investigations.
    user_agent   = db.Column(db.String(255))
    ip_address   = db.Column(db.String(64))

    user = db.relationship('User', backref=db.backref('refresh_tokens', lazy='dynamic',
                                                       cascade='all, delete-orphan'))

    @property
    def is_active(self) -> bool:
        exp = _as_aware_utc(self.expires_at)
        return self.revoked_at is None and exp is not None and exp > utcnow()

    def revoke(self):
        self.revoked_at = utcnow()


def issue_refresh_token(user_id: int, *, user_agent: Optional[str] = None,
                        ip_address: Optional[str] = None) -> str:
    """Mint a new refresh token row. Returns the raw token — hash is stored."""
    raw = secrets.token_urlsafe(48)
    rt = RefreshToken(
        user_id    = user_id,
        token_hash = _hash_token(raw),
        expires_at = utcnow() + REFRESH_TOKEN_TTL,
        user_agent = (user_agent or '')[:255] or None,
        ip_address = (ip_address or '')[:64] or None,
    )
    db.session.add(rt)
    db.session.commit()
    return raw


def find_active_refresh_token(raw_token: str) -> Optional['RefreshToken']:
    rt = RefreshToken.query.filter_by(token_hash=_hash_token(raw_token)).first()
    return rt if (rt and rt.is_active) else None


# COMPLETE Database Models (maintaining original complexity + unified app compatibility)
class Recipe(db.Model):
    __tablename__ = 'recipes'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    imageurl = db.Column(db.String(500))
    sourceurl = db.Column(db.String(500))
    preptime = db.Column(db.Integer, default=0)
    cooktime = db.Column(db.Integer, default=0)
    totaltime = db.Column(db.Integer, default=0)
    servings = db.Column(db.Integer, default=4)
    originalservings = db.Column(db.Integer, default=4)  # Track original servings
    difficulty = db.Column(db.String(20), default='Medium')
    aicomment = db.Column(db.Text)
    nutritiondata = db.Column(db.Text)  # JSON string
    nutritionperserving = db.Column(db.Text)  # JSON string
    hashtags = db.Column(db.Text)  # JSON string
    cuisinetype = db.Column(db.String(50))
    cookingmethod = db.Column(db.String(50))
    dietarytags = db.Column(db.Text)  # JSON string
    language = db.Column(db.String(5))  # Language the recipe text is stored in (ru/en/it/es/fr/de)

    # ── Adaptation lineage ────────────────────────────────────────────────
    # When a recipe is created by adapting another recipe (servings change,
    # lactose-free, vegetarian, etc.) we keep a back-reference to the source
    # recipe id and the list of presets that were applied. Both NULL for
    # ordinary imported recipes.
    adaptedfrom = db.Column(db.Integer, db.ForeignKey('recipes.id'), nullable=True, index=True)
    adaptationpresets = db.Column(db.Text)  # JSON string: list of preset keys applied

    # Literary quote fields
    literaryquote = db.Column(db.Text)
    quoteauthor = db.Column(db.String(200))
    quotesource = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=utcnow)
    is_saved = db.Column(db.Boolean, default=False)  # False = preview, True = saved to collection
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # User ownership - links recipes to specific users
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    is_public = db.Column(db.Boolean, default=False)  # Future: allow recipe sharing

    # Relationships
    ingredients = db.relationship('Ingredient', backref='recipe', lazy=True, cascade='all, delete-orphan')
    instructions = db.relationship('Instruction', backref='recipe', lazy=True, cascade='all, delete-orphan')
    categories = db.relationship('RecipeCategory', backref='recipe', lazy=True, cascade='all, delete-orphan')

    # Unified app compatibility properties
    @property
    def ingredients_json(self):
        """Return ingredients as JSON string for unified app"""
        ingredient_list = []
        for ingredient in sorted(self.ingredients, key=lambda x: x.order_index):
            if ingredient.quantity and ingredient.unit:
                text = f"{ingredient.quantity} {ingredient.unit} {ingredient.ingredient}"
            elif ingredient.quantity:
                text = f"{ingredient.quantity} {ingredient.ingredient}"
            else:
                text = ingredient.ingredient

            if ingredient.preparation:
                text += f", {ingredient.preparation}"
            ingredient_list.append(text)

        return json.dumps(ingredient_list)

    @property  
    def instructions_json(self):
        """Return instructions as JSON string for unified app"""
        instruction_list = []
        for instruction in sorted(self.instructions, key=lambda x: x.step_number):
            text = instruction.instruction
            if instruction.time_estimate:
                text += f" (about {instruction.time_estimate} minutes)"
            if instruction.temperature:
                text += f" at {instruction.temperature}"
            instruction_list.append(text)

        return json.dumps(instruction_list)

    def to_dict(self, include_relationships=True):
        """Convert recipe to dictionary for JSON response"""
        result = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'imageurl': self.imageurl,
            'sourceurl': self.sourceurl,
            'preptime': self.preptime,
            'cooktime': self.cooktime,
            'totaltime': self.totaltime,
            'servings': self.servings,
            'originalservings': self.originalservings or self.servings,
            'difficulty': self.difficulty,
            'aicomment': self.aicomment,
            'hashtags': json.loads(self.hashtags) if self.hashtags else [],
            'cuisinetype': self.cuisinetype,
            'cookingmethod': self.cookingmethod,
            'dietarytags': json.loads(self.dietarytags) if self.dietarytags else [],
            'literaryquote': self.literaryquote,
            'quoteauthor': self.quoteauthor,
            'quotesource': self.quotesource,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_saved': self.is_saved,
            'language': self.language,
            'adaptedfrom': self.adaptedfrom,
            'adaptationpresets': json.loads(self.adaptationpresets) if self.adaptationpresets else [],
        }

        if include_relationships:
            # For unified app compatibility - return as simple arrays
            result['ingredients'] = []
            for ingredient in sorted(self.ingredients, key=lambda x: x.order_index):
                if ingredient.quantity and ingredient.unit:
                    text = f"{ingredient.quantity} {ingredient.unit} {ingredient.ingredient}"
                elif ingredient.quantity:
                    text = f"{ingredient.quantity} {ingredient.ingredient}"
                else:
                    text = ingredient.ingredient

                if ingredient.preparation:
                    text += f", {ingredient.preparation}"
                result['ingredients'].append(text)

            result['instructions'] = []
            for instruction in sorted(self.instructions, key=lambda x: x.step_number):
                result['instructions'].append(instruction.instruction)

            result['categories'] = []
            for recipe_category in self.categories:
                if recipe_category.category:
                    result['categories'].append(recipe_category.category.name)

        return result

class Ingredient(db.Model):
    __tablename__ = 'ingredients'

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id'), nullable=False)
    ingredient = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.String(50))
    unit = db.Column(db.String(50))
    preparation = db.Column(db.String(100))
    originalquantity = db.Column(db.String(50))  # Store original for scaling
    originalunit = db.Column(db.String(50))  # Store original for scaling
    order_index = db.Column(db.Integer, default=0)

class Instruction(db.Model):
    __tablename__ = 'instructions'

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id'), nullable=False)
    step_number = db.Column(db.Integer, nullable=False)
    instruction = db.Column(db.Text, nullable=False)
    time_estimate = db.Column(db.Integer)
    temperature = db.Column(db.String(20))

class Category(db.Model):
    __tablename__ = 'categories'
    __table_args__ = (
        # Composite uniqueness: (name, user_id).
        # NULL user_id = global/default category; SQLite treats each NULL as
        # distinct so multiple users can share a category name with their own
        # user_id without violating this constraint.
        db.UniqueConstraint('name', 'user_id', name='uq_category_name_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    icon = db.Column(db.String(10))
    # NULL = global/default category (visible to all, not editable by users)
    # Non-NULL = owned by that user (only they can edit/delete it)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

class RecipeCategory(db.Model):
    __tablename__ = 'recipe_categories'

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)

    # Relationship
    category = db.relationship('Category', backref='recipe_categories')

# Database migration function

# ============================================================================
# AUTHENTICATION DECORATOR - Protects routes requiring user login
# ============================================================================
from functools import wraps
import time as _time
from collections import defaultdict as _defaultdict, deque as _deque

# ── Lightweight in-memory rate limiter ──────────────────────────────────────
# Protects sensitive endpoints (login/signup/refresh) from brute-force and
# credential-stuffing without adding an external dependency (works on the
# user's Python 3.9 venv). For multi-process / multi-server deployments,
# replace this with Flask-Limiter backed by Redis.
_rate_lock = _threading.Lock()
_rate_hits: dict = _defaultdict(_deque)  # key -> deque[timestamps]


def _client_ip() -> str:
    """Best-effort client IP, honouring a single proxy hop if present."""
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def rate_limit(max_requests: int = 10, window_seconds: int = 60, scope: str = ''):
    """Decorator: allow at most `max_requests` per `window_seconds` per client IP.

    Returns HTTP 429 with a Retry-After header when the limit is exceeded.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f"{scope or f.__name__}:{_client_ip()}"
            now = _time.monotonic()
            with _rate_lock:
                hits = _rate_hits[key]
                # Drop timestamps outside the window.
                while hits and (now - hits[0]) > window_seconds:
                    hits.popleft()
                if len(hits) >= max_requests:
                    retry_after = int(window_seconds - (now - hits[0])) + 1
                    logger.warning(f"Rate limit hit for {key} ({len(hits)} reqs)")
                    resp = jsonify({
                        'error': 'rate_limited',
                        'message': 'Too many requests. Please slow down and try again later.',
                    })
                    resp.status_code = 429
                    resp.headers['Retry-After'] = str(max(retry_after, 1))
                    return resp
                hits.append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def require_auth(f):
    """
    Decorator to protect routes - requires valid session token in Authorization header.

    Usage:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            user = request.current_user  # Access authenticated user
            return jsonify({'message': f'Hello {user.username}'})
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')

        if not auth_header or not auth_header.startswith('Bearer '):
            logger.warning("Authentication failed: Missing or invalid Authorization header")
            return jsonify({'error': 'Authentication required'}), 401

        # Extract token (format: "Bearer <token>")
        try:
            token = auth_header.split('Bearer ')[1]
        except IndexError:
            logger.warning("Authentication failed: Malformed Authorization header")
            return jsonify({'error': 'Invalid authentication format'}), 401

        # Resolve authenticated user. We accept three credential shapes, in
        # priority order, so existing clients keep working while new clients
        # adopt JWT access tokens:
        #   1. JWT access token (`type=access`, signed with SECRET_KEY)
        #   2. New session token stored as sha256 hash (post-migration)
        #   3. Legacy plaintext session token (transparently upgraded to hash)
        user = None

        # 1. JWT access token — detect by the three-segment dot structure.
        if token.count('.') == 2:
            payload = decode_access_token(token)
            if payload:
                try:
                    user = User.query.get(int(payload.get('sub')))
                except (TypeError, ValueError):
                    user = None
                if user:
                    request.current_user = user
                    request.auth_method = 'jwt'
                    logger.debug(f"Authenticated user (JWT): {user.username} (ID: {user.id})")
                    return f(*args, **kwargs)
                # Token signature ok but user gone → fall through to 401.
                logger.warning("JWT token valid but user not found")
                return jsonify({'error': 'Invalid session token'}), 401
            # JWT-shaped but invalid/expired — do not fall through to opaque
            # session-token lookup; the client must call /auth/refresh.
            return jsonify({'error': 'Access token expired or invalid',
                            'code':  'token_expired'}), 401

        # 2 + 3. Opaque session token (legacy). Try hashed lookup first.
        token_hash = _hash_token(token)
        user = User.query.filter_by(session_token_hash=token_hash).first()
        if not user:
            user = User.query.filter_by(session_token=token).first()
            if user:
                # Transparently upgrade legacy plaintext sessions to hashed
                # storage on first use, then clear the plaintext column.
                user.session_token_hash = token_hash
                user.session_token = None
                db.session.commit()

        if not user:
            logger.warning("Authentication failed: Invalid token")
            return jsonify({'error': 'Invalid session token'}), 401

        if not user.is_session_valid():
            logger.warning(f"Authentication failed: Expired token for user {user.username}")
            return jsonify({'error': 'Session expired. Please log in again.'}), 401
        request.auth_method = 'session'

        # Attach authenticated user to request context
        request.current_user = user
        logger.debug(f"Authenticated user: {user.username} (ID: {user.id})")

        return f(*args, **kwargs)

    return decorated_function

def migrate_database():
    """Add missing columns to existing database.

    NOTE: SQLAlchemy 2.0 removed ``Engine.execute()``. All DDL/DML below runs
    through an explicit connection obtained from ``db.engine.begin()``, which
    opens a transaction and commits automatically on success. This keeps the
    migration compatible with the SQLAlchemy 2.0.x pulled in by
    Flask-SQLAlchemy 3.1.x.
    """
    try:
        with app.app_context():
            inspector = db.inspect(db.engine)

            # Single transactional connection for the whole migration.
            with db.engine.begin() as conn:
                # ── Session token hash column ─────────────────────────────
                # Added when sessions migrated from plaintext to sha256 storage.
                user_columns = [col['name'] for col in inspector.get_columns('users')]
                if 'session_token_hash' not in user_columns:
                    logger.info("Adding users.session_token_hash column...")
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN session_token_hash VARCHAR(64)"
                    ))
                    try:
                        conn.execute(text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_session_token_hash "
                            "ON users(session_token_hash)"
                        ))
                    except Exception as _idx_e:
                        logger.warning(f"Could not create session_token_hash index: {_idx_e}")
                    logger.info("✅ Added users.session_token_hash column")

                # ── i18n language column ─────────────────────────────────
                # Preferred UI language for the user. Defaults to 'ru' for all
                # existing rows so behaviour is unchanged after migration.
                if 'language' not in user_columns:
                    logger.info("Adding users.language column...")
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'ru'"
                    ))
                    logger.info("✅ Added users.language column (default 'ru')")

                # Check if originalservings column exists
                columns = [col['name'] for col in inspector.get_columns('recipes')]
                if 'originalservings' not in columns:
                    logger.info("Adding missing originalservings column...")
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN originalservings INTEGER DEFAULT 4"))
                    conn.execute(text("UPDATE recipes SET originalservings = servings WHERE originalservings IS NULL"))
                    logger.info("Added originalservings column")

                # ── Recipe language column ────────────────────────────────
                # Tracks which language the recipe text is currently stored in,
                # so the UI can show a translate prompt when it differs.
                if 'language' not in columns:
                    logger.info("Adding recipes.language column...")
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN language VARCHAR(5)"))
                    logger.info("✅ Added recipes.language column")

                # ── Recipe adaptation lineage columns ─────────────────────
                # Back-reference + applied presets for adapted recipes.
                if 'adaptedfrom' not in columns:
                    logger.info("Adding recipes.adaptedfrom column...")
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN adaptedfrom INTEGER"))
                    logger.info("✅ Added recipes.adaptedfrom column")
                if 'adaptationpresets' not in columns:
                    logger.info("Adding recipes.adaptationpresets column...")
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN adaptationpresets TEXT"))
                    logger.info("✅ Added recipes.adaptationpresets column")

                # Check ingredient table for original columns
                ingredient_columns = [col['name'] for col in inspector.get_columns('ingredients')]
                if 'originalquantity' not in ingredient_columns:
                    logger.info("Adding missing ingredient original columns...")
                    conn.execute(text("ALTER TABLE ingredients ADD COLUMN originalquantity VARCHAR(50)"))
                    conn.execute(text("ALTER TABLE ingredients ADD COLUMN originalunit VARCHAR(50)"))
                    conn.execute(text("UPDATE ingredients SET originalquantity = quantity WHERE originalquantity IS NULL"))
                    conn.execute(text("UPDATE ingredients SET originalunit = unit WHERE originalunit IS NULL"))
                    logger.info("Added ingredient original columns")

                # ── Literary quote columns ────────────────────────────────
                # These live on the `recipes` table, so the check must use the
                # recipes `columns` list and run INDEPENDENTLY of the ingredient
                # migration above. (Previously this was nested inside the
                # `originalquantity` branch, so a DB that already had the
                # ingredient columns would never get the quote columns.)
                if 'literaryquote' not in columns:
                    logger.info("Adding literary quote columns...")
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN literaryquote TEXT"))
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN quoteauthor VARCHAR(200)"))
                    conn.execute(text("ALTER TABLE recipes ADD COLUMN quotesource VARCHAR(200)"))
                    logger.info("✅ Added literary quote columns")

                # ── Category ownership migration ──────────────────────────
                # Add user_id column to categories (NULL = global/default).
                # Safe: existing rows keep NULL, meaning they stay global.
                try:
                    cat_columns = [col['name'] for col in inspector.get_columns('categories')]
                    if 'user_id' not in cat_columns:
                        logger.info("Adding user_id column to categories table...")
                        conn.execute(text(
                            "ALTER TABLE categories ADD COLUMN user_id INTEGER REFERENCES users(id)"
                        ))
                        logger.info("✅ Added categories.user_id column (existing rows stay NULL = global)")

                        # Replace the old unique index on 'name' alone with a
                        # composite unique index (name, user_id). Done with
                        # try/except so a missing index doesn't abort startup.
                        try:
                            conn.execute(text("DROP INDEX IF EXISTS ix_categories_name"))
                            logger.info("Dropped old ix_categories_name unique index")
                        except Exception as _idx_e:
                            logger.warning(f"Could not drop old category name index: {_idx_e}")
                        try:
                            conn.execute(text(
                                "CREATE UNIQUE INDEX IF NOT EXISTS uq_category_name_user "
                                "ON categories (name, user_id)"
                            ))
                            logger.info("✅ Created composite unique index uq_category_name_user")
                        except Exception as _idx_e:
                            logger.warning(f"Could not create composite category index: {_idx_e}")
                except Exception as _cat_e:
                    logger.warning(f"Category user_id migration step failed: {_cat_e}")

    except Exception as e:
        # Surface the full traceback so a genuine failure (disk full, permission
        # error, locked DB) is visible rather than silently swallowed. Some
        # benign "duplicate column" errors can still occur on re-runs; we log
        # those at WARNING and continue, but anything else is logged at ERROR.
        msg = str(e).lower()
        benign = 'duplicate column' in msg or 'already exists' in msg
        if benign:
            logger.warning(f"Migration step skipped (already applied): {e}")
        else:
            logger.error(f"Migration error: {e}")
            logger.error(traceback.format_exc())

def create_default_categories():
    """Create default recipe categories"""
    try:
        default_categories = [
            {'name': 'Breakfast & Brunch', 'description': 'Morning meals and brunch dishes', 'icon': '🍳'},
            {'name': 'Appetizers & Starters', 'description': 'Small dishes and appetizers', 'icon': '🥟'},
            {'name': 'Main Courses', 'description': 'Main dishes and entrees', 'icon': '🍽️'},
            {'name': 'Side Dishes', 'description': 'Accompaniments and side dishes', 'icon': '🥗'},
            {'name': 'Desserts & Sweets', 'description': 'Sweet treats and desserts', 'icon': '🍰'},
            {'name': 'Beverages', 'description': 'Drinks and smoothies', 'icon': '🥤'},
            {'name': 'Snacks', 'description': 'Quick bites and snacks', 'icon': '🥨'},
        ]

        for cat_data in default_categories:
            existing = Category.query.filter_by(name=cat_data['name']).first()
            if not existing:
                category = Category(**cat_data)
                db.session.add(category)

        db.session.commit()
        logger.info("Default categories created")
    except Exception as e:
        logger.error(f"Failed to create default categories: {e}")
        db.session.rollback()

# ALL ORIGINAL HELPER FUNCTIONS
def sanitize_string(value):
    """Convert any value to a safe string for database storage"""
    if value is None:
        return ""
    if isinstance(value, list):
        if value and len(value) > 0:
            return str(value[0]).strip() if value[0] else ""
        return ""
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value).strip()
def normalize_title(title):
    """Normalize recipe title for duplicate detection"""
    if not title:
        return ""
    normalized = title.lower().strip()
    normalized = ' '.join(normalized.split())
    normalized = re.sub(r'[!?.,:;\'"]', '', normalized)
    return normalized

def normalize_url(url):
    """Normalize URL for duplicate detection"""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        scheme = 'https' if parsed.scheme in ['http', 'https'] else parsed.scheme
        netloc = parsed.netloc.lower().replace('www.', '')
        path = parsed.path.rstrip('/')
        normalized = urlunparse((scheme, netloc, path, '', '', ''))
        return normalized
    except (ValueError, AttributeError):
        logger.debug("normalize_url: failed to normalize %r", url)
        return url.strip().lower()
def sanitize_image_url(value):
    """Safely extract image URL from various formats"""
    if not value:
        return ""
    if isinstance(value, list):
        for url in value:
            if url and isinstance(url, str) and url.strip():
                clean_url = url.strip()
                if '?' in clean_url:
                    clean_url = clean_url.split('?')[0]
                return clean_url
        return ""
    if isinstance(value, dict):
        if 'url' in value:
            return sanitize_image_url(value['url'])
        if 'id' in value:
            return sanitize_image_url(value['id'])
        return ""
    if isinstance(value, str):
        clean_url = value.strip()
        if '?' in clean_url:
            clean_url = clean_url.split('?')[0]
        return clean_url
    return ""

def sanitize_integer(value, default=0):
    """Safely convert value to integer"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def sanitize_json_field(value):
    """Safely convert value to JSON string for database storage"""
    if value is None:
        return "[]"
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except (ValueError, TypeError):
            return json.dumps([value])
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return json.dumps([str(value)])

def safe_get_attribute(obj, attr, default=None):
    """Safely get attribute from object with fallback"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

def parse_time_string(time_str):
    """Parse time string to minutes"""
    if not time_str:
        return 0

    try:
        if time_str.startswith('PT'):
            match = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?', time_str)
            if match:
                hours = int(match.group(1) or 0)
                minutes = int(match.group(2) or 0)
                return hours * 60 + minutes

        time_str = time_str.lower().replace('-', ' ')
        total_minutes = 0

        hours_match = re.search(r'(\d+)\s*(?:hours?|hrs?|h)\b', time_str)
        if hours_match:
            total_minutes += int(hours_match.group(1)) * 60

        minutes_match = re.search(r'(\d+)\s*(?:minutes?|mins?|m)\b', time_str)
        if minutes_match:
            total_minutes += int(minutes_match.group(1))

        if total_minutes == 0:
            numbers = re.findall(r'(\d+)', time_str)
            if numbers:
                total_minutes = int(numbers[0])

        return total_minutes
    except Exception as e:
        logger.error(f"Time parsing error for '{time_str}': {e}")
        return 0

def extract_servings(text):
    """Extract serving count from text"""
    if not text:
        return 4
    try:
        matches = re.findall(r'(\d+)', str(text).lower())
        if matches:
            return int(matches[0])
        return 4
    except (ValueError, TypeError):
        logger.debug("extract_servings: failed to parse %r", text)
        return 4

# Known cooking units. Only these are treated as units; anything else after the
# quantity is part of the ingredient name. This prevents "2 avocados" from
# being parsed as quantity=2, unit="avocado", ingredient="s".
_KNOWN_UNITS = {
    # Volume
    'tsp', 'teaspoon', 'teaspoons',
    'tbsp', 'tablespoon', 'tablespoons',
    'cup', 'cups',
    'pint', 'pints', 'pt',
    'quart', 'quarts', 'qt',
    'gallon', 'gallons', 'gal',
    'ml', 'milliliter', 'milliliters',
    'l', 'liter', 'liters', 'litre', 'litres',
    'fl', 'oz',  # 'fl oz' handled below
    'dl', 'cl',
    # Weight
    'g', 'gr', 'gram', 'grams',
    'kg', 'kilogram', 'kilograms',
    'mg',
    'lb', 'lbs', 'pound', 'pounds',
    'ounce', 'ounces',
    # Misc
    'pinch', 'pinches', 'dash', 'dashes', 'drop', 'drops',
    'slice', 'slices', 'clove', 'cloves',
    'can', 'cans', 'jar', 'jars', 'pack', 'packs', 'package', 'packages',
    'stick', 'sticks',
    'piece', 'pieces',
    'inch', 'inches', 'cm', 'mm',
}


# Unicode vulgar fractions → ascii equivalents (module-level so other helpers
# can reuse it).
_UNICODE_FRACTIONS = {
    '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4',
    '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5', '⅙': '1/6',
    '⅚': '5/6', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
    '⅐': '1/7', '⅑': '1/9', '⅒': '1/10',
}


def _pre_normalise_raw_ingredient(text: str) -> str:
    """Clean up messy raw ingredient strings BEFORE quantity/unit parsing.

    Source sites (e.g. BBC Good Food) often emit strings like:
        "/1¾oz fine sea salt", "/¾oz root ginger", "/3½oz carrot"
    The leading slash and the unicode fraction glued to the unit broke the
    quantity regex and produced ingredient names like "/1¾oz fine sea salt",
    which then failed USDA lookups (HTTP 400). This normaliser:

      1. Strips leading punctuation/whitespace junk ('/', '-', '·', '•', etc).
      2. Converts unicode fractions to ascii ('¾' -> '3/4'), inserting a space
         so a digit glued to a fraction ('1¾' -> '1 3/4') parses as a mixed
         number.
      3. Inserts a space between a number and a following letter when the
         letters look like a unit glued to the quantity ('1¾oz' -> '1 3/4 oz',
         '200g' -> '200 g', '2tbsp' -> '2 tbsp').
    """
    if not text:
        return ''
    s = str(text).strip()

    # 0. Multiplier packs: "2 x 400 g Tins Cherry Tomatoes" -> "800 g Cherry
    #    Tomatoes". Source sites express tinned/canned goods as count x size.
    #    Without this the parser took only the count (2) and mis-weighed the
    #    main ingredient. We fold the multiplier into a single total quantity
    #    and drop the container word (tin/tins/can/cans/jar/jars/pack(s)).
    mult = re.match(
        r'^\s*(\d+(?:\.\d+)?)\s*[x\u00d7\u0445\u0425*]\s*'   # count + x/× (lat/cyr)
        r'(\d+(?:\.\d+)?)\s*'                                  # pack size number
        r'(g|gr|gram|grams|kg|mg|oz|ounce|ounces|lb|lbs|ml|milliliter|'
        r'milliliters|l|liter|liters|litre|litres|cl|dl)\b'      # pack size unit
        r'\s*(.*)$',
        s, flags=re.IGNORECASE,
    )
    if mult:
        count = float(mult.group(1))
        size = float(mult.group(2))
        unit = mult.group(3)
        rest = mult.group(4)
        # Strip a leading container word so the name is clean for USDA lookup.
        rest = re.sub(
            r'^(?:of\s+)?(?:tins?|cans?|jars?|packs?|packets?|packages?|'
            r'bottles?|tubs?|boxes?|box)\s+', '', rest, flags=re.IGNORECASE,
        ).strip()
        total = count * size
        total_str = str(int(total)) if total == int(total) else str(total)
        s = f"{total_str} {unit} {rest}".strip()

    # 1. Strip leading junk punctuation (slashes, bullets, dashes, dots).
    s = re.sub(r'^[\s/\\\-–—·•*°.,;:]+', '', s)

    # 2. Put a space before unicode fractions when preceded by a digit
    #    ("1¾" -> "1 ¾") so the mixed-number case is recognised, then convert.
    s = re.sub(r'(?<=\d)(?=[½¼¾⅓⅔⅛⅜⅝⅞⅕⅖⅗⅘⅙⅚⅐⅑⅒])', ' ', s)
    for u, a in _UNICODE_FRACTIONS.items():
        s = s.replace(u, a)

    # 3. Insert a space between a number (or fraction) and glued letters, so a
    #    unit stuck to the quantity ("200g", "3/4oz") is separated.
    s = re.sub(r'(?<=[\d/])(?=[a-zA-Z])', ' ', s)

    # Collapse whitespace.
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def clean_ingredient_text(text):
    """Parse ingredient text into quantity, unit and ingredient name.

    Only recognises a fixed set of cooking units (see _KNOWN_UNITS) — words like
    "avocados" or "limes" stay in the ingredient name instead of being
    mis-classified as units.
    """
    if not text:
        return {"ingredient": "", "quantity": "", "unit": ""}

    # Normalise messy raw strings (leading '/', glued unicode fractions/units)
    # before parsing so quantity/unit/name come out clean.
    text = _pre_normalise_raw_ingredient(text)
    if not text:
        return {"ingredient": "", "quantity": "", "unit": ""}

    # Quantity regex covers: integers, decimals, simple fractions, mixed
    # numbers, ranges, and unicode fractions like ½.
    qty_re = (
        r'\d+\s+\d+/\d+'        # mixed: 1 1/2
        r'|\d+/\d+'              # plain fraction: 1/2
        r'|\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?'  # range: 2-3
        r'|\d+\.\d+'             # decimal: 2.5
        r'|\d+'                  # integer: 2
        r'|[½¼¾⅓⅔⅛⅜⅝⅞]'  # unicode fraction
    )
    match = re.match(rf'^({qty_re})\s*(.*)$', text)
    if not match:
        return {"quantity": "", "unit": "", "ingredient": text}

    quantity = match.group(1).strip()
    remainder = match.group(2).strip()

    # Try to recognise the next token as a known unit. Handle two-word unit
    # "fl oz" as a special case.
    unit = ""
    if remainder.lower().startswith('fl oz'):
        unit = 'fl oz'
        ingredient = remainder[5:].strip()
    else:
        first_token_match = re.match(r'^([a-zA-Z]+)\.?\s*(.*)$', remainder)
        if first_token_match:
            candidate = first_token_match.group(1).lower().rstrip('.')
            if candidate in _KNOWN_UNITS:
                unit = candidate
                ingredient = first_token_match.group(2).strip()
            else:
                ingredient = remainder
        else:
            ingredient = remainder

    return {"quantity": quantity, "unit": unit, "ingredient": ingredient}

# Helper to check if @type includes 'Recipe'
def is_recipe_type(type_value):
    """Check if @type includes 'Recipe' (handles both string and array)"""
    if not type_value:
        return False
    if isinstance(type_value, str):
        return type_value == 'Recipe'
    if isinstance(type_value, list):
        return 'Recipe' in type_value
    return False

# Enhanced image extraction
def extract_recipe_images(soup, base_url):
    """
    Extract MAIN recipe image only (not logos, icons, or auxiliary images)

    Strategy:
    1. First try JSON-LD Recipe schema image (most reliable for main image)
    2. Fall back to og:image if it's high quality
    3. Filter out common non-recipe images (logos, icons, avatars)
    4. Return only 1-2 best images, not all images
    """
    images = []

    try:
        # Method 1: JSON-LD Recipe schema (PRIMARY - most reliable)
        json_scripts = soup.find_all('script', type='application/ld+json')
        logger.debug(f"Found {len(json_scripts)} JSON-LD scripts")

        for idx, script in enumerate(json_scripts):
            try:
                data = json.loads(script.string)

                # Handle different JSON-LD structures
                items_to_check = []

                # Check for @graph (common in WordPress/Yoast SEO)
                if isinstance(data, dict) and '@graph' in data:
                    items_to_check = data['@graph']
                    logger.debug(f"Script {idx}: Found @graph with {len(items_to_check)} items")
                elif isinstance(data, list):
                    items_to_check = data
                elif isinstance(data, dict):
                    items_to_check = [data]

                # Find Recipe type and extract images
                for item in items_to_check:
                    if not isinstance(item, dict):
                        continue

                    # Check if this is a Recipe
                    item_type = item.get('@type', '')
                    if is_recipe_type(item_type):
                        logger.debug(f"Found Recipe schema in script {idx}")

                        # Extract image from Recipe schema
                        image_data = item.get('image')
                        if image_data:
                            extracted = _extract_image_urls_from_schema(image_data)
                            if extracted:
                                # Recipe schema images are highest priority
                                images = extracted + images  # Prepend to prioritize
                                logger.debug(f"Extracted {len(extracted)} images from Recipe schema")
                        break  # Found Recipe, no need to check other items in this script

            except json.JSONDecodeError as e:
                logger.debug(f"Script {idx}: JSON parse error")
                continue
            except Exception as e:
                logger.debug(f"Script {idx}: Error - {str(e)[:100]}")
                continue

        # Method 2: Open Graph image (SECONDARY fallback)
        # Only use if no Recipe schema images found
        if not images:
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                og_url = urljoin(base_url, og_image['content'])
                # Always use og:image as fallback (bypass filter)
                images.append(og_url)
                logger.info(f"Using og:image as fallback: {og_url[:80]}")

        # Method 3: Twitter image (TERTIARY fallback)
        if not images:
            twitter_image = soup.find('meta', attrs={'name': 'twitter:image'}) or \
                            soup.find('meta', property='twitter:image')
            if twitter_image and twitter_image.get('content'):
                twitter_url = urljoin(base_url, twitter_image['content'])
                # Always use twitter:image as fallback (bypass filter)
                images.append(twitter_url)
                logger.info(f"Using twitter:image as fallback: {twitter_url[:80]}")

        # Clean and filter
        clean_images = []
        seen = set()

        for img_url in images:
            if not img_url or img_url in seen:
                continue

            # Make absolute URL
            full_url = urljoin(base_url, img_url)

            # Filter out unwanted images
            # FILTER DISABLED: Accept all images from JSON-LD
            # if _is_logo_or_icon(full_url):
            #     logger.debug(f"Rejected (logo/icon): {full_url[:80]}")
            #     continue
            # Verify it looks like an image URL
            # if not _is_valid_image_url(full_url):
            #     logger.debug(f"Rejected (invalid format): {full_url[:80]}")
            #     continue

            clean_images.append(full_url)
            seen.add(img_url)
            logger.info(f"✅ ACCEPTED IMAGE: {full_url[:80]}")

            # IMPORTANT: Only return 1-2 images (main recipe images)
            if len(clean_images) >= 2:
                break

        logger.info(f"Image extraction: {len(clean_images)} main recipe image(s) found")
        return clean_images

    except Exception as e:
        logger.error(f"Image extraction error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return []


def _extract_image_urls_from_schema(image_data):
    """
    Extract URLs from various JSON-LD image formats
    Handles: strings, lists, dicts, ImageObject schemas
    """
    urls = []

    if isinstance(image_data, str):
        # Simple string URL
        urls.append(image_data)

    elif isinstance(image_data, list):
        # Array of images
        for img in image_data:
            if isinstance(img, dict):
                # ImageObject with properties
                url = (img.get('url') or
                       img.get('@id') or
                       img.get('contentUrl') or
                       img.get('thumbnailUrl'))
                if url:
                    urls.append(url)
            elif isinstance(img, str):
                urls.append(img)

    elif isinstance(image_data, dict):
        # Single ImageObject
        url = (image_data.get('url') or
               image_data.get('@id') or
               image_data.get('contentUrl') or
               image_data.get('thumbnailUrl'))
        if url:
            urls.append(url)

    return urls


def _is_valid_image_url(url):
    """
    Check if URL appears to be a valid image
    Accepts: file extensions, CDN URLs, image keywords
    """
    url_lower = url.lower()

    # Remove query string for extension check
    url_path = url.split('?')[0].lower()

    # Check 1: Has image file extension
    if url_path.endswith(('.jpg', '.jpeg', '.png', '.webp', '.avif', '.gif')):
        return True

    # Check 2: Has image-related keywords in full URL
    image_keywords = ['image', 'img', 'photo', 'picture', 'recipe', 'food']
    if any(keyword in url_lower for keyword in image_keywords):
        return True

    # Check 3: Is from known CDN (often don't use extensions)
    cdn_domains = ['cloudinary', 'imgix', 'cloudfront', 'akamai', 'fastly',
                   'cdn', 'imagekit', 'bunnycdn', 'digitalocean']
    if any(cdn in url_lower for cdn in cdn_domains):
        return True

    # Check 4: Has format parameter in query string
    if 'format=' in url_lower or 'type=image' in url_lower:
        return True

    return False


def _is_logo_or_icon(url):
    """
    Filter out logos, icons, avatars, and other non-recipe images
    (UPDATED: Less aggressive filtering)
    """
    url_lower = url.lower()

    # REDUCED LIST - removed problematic patterns
    unwanted_patterns = [
        'logo', 'icon', 'favicon', 'avatar', 'profile',
        'badge', 'button', 'banner',
        '/icons/', '/logos/', '/assets/brand/',
        '150x150', '200x200', '100x100', '50x50', '80x80',
        'default-image', 'fallback', 'og-default'
    ]

    for pattern in unwanted_patterns:
        if pattern in url_lower:
            return True

    # REDUCED minimum: 250x250 instead of 400x400
    import re
    dimension_match = re.search(r'(\d+)x(\d+)', url_lower)
    if dimension_match:
        width = int(dimension_match.group(1))
        height = int(dimension_match.group(2))
        if width < 250 or height < 250:
            return True

    return False


# AI text enhancement
def enhance_text_with_ai(text_data, text_type="general"):
    """Use AI to clean up recipe text"""
    if not (openai_client or openai_api_key):
        return text_data

    try:
        if text_type == "ingredients" and isinstance(text_data, list) and len(text_data) > 0:
            ingredients_text = "\n".join([str(ing) for ing in text_data[:10]])
            prompt = f"""Fix capitalization and formatting for these ingredients (return as clean list, one per line):
{ingredients_text}"""
        elif text_type == "instructions" and isinstance(text_data, list) and len(text_data) > 0:
            instructions_text = "\n".join([str(inst)[:200] for inst in text_data[:8]])
            prompt = f"""Fix grammar and formatting for these cooking instructions (return as clean steps, one per line):
{instructions_text}"""
        else:
            return text_data

        # Make API call
        if OPENAI_NEW_API and openai_client:
            response = openai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            cleaned_text = response.choices[0].message.content.strip()
        elif openai_api_key:
            response = openai.ChatCompletion.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            cleaned_text = response.choices[0].message.content.strip()
        else:
            return text_data

        # Return cleaned lines as list
        if cleaned_text:
            lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
            return lines if lines else text_data

        return text_data

    except Exception as e:
        logger.error(f"AI enhancement error: {e}")
        return text_data


def enhance_with_ai(recipe_data, url):
    """Use OpenAI to enhance recipe data with compatibility for both API versions"""
    if not openai_client and not openai_api_key:
        return recipe_data

    try:
        prompt = f"""Enhance this recipe data with additional useful information. Provide your response as a JSON object.

Recipe:
- Title: {recipe_data.get('title', 'Unknown')}
- Description: {recipe_data.get('description', 'No description')}
- Ingredients: {len(recipe_data.get('ingredients', []))} items
- Instructions: {len(recipe_data.get('instructions', []))} steps

Please provide:
1. A helpful cooking tip or comment (max 100 words)
2. Difficulty level (Easy/Medium/Hard)
3. 3-5 relevant hashtags
4. Cuisine type if identifiable
5. Primary cooking method

Return ONLY valid JSON in this exact format: {{"aicomment": "helpful cooking tip", "difficulty": "Easy/Medium/Hard", "hashtags": ["tag1", "tag2", "tag3"], "cuisinetype": "cuisine name", "cookingmethod": "method name"}}"""

        ai_response = None
        if openai_client:
            try:
                response = openai_client.chat.completions.create(
                    model=AI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    response_format={"type": "json_object"}  # This forces clean JSON output
                )
                ai_response = response.choices[0].message.content
            except Exception as e:
                logger.error(f"New OpenAI API failed: {e}")

        if not ai_response and not OPENAI_NEW_API and openai_api_key:
            try:
                response = openai.ChatCompletion.create(
                    model=AI_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    response_format={"type": "json_object"}  # This forces clean JSON output
                )
                ai_response = response.choices[0].message.content
            except Exception as e:
                logger.error(f"Legacy OpenAI API failed: {e}")

        if ai_response:
            try:
                # Parse the JSON response
                ai_data = json.loads(ai_response.strip())
                recipe_data["aicomment"] = ai_data.get("aicomment", "")
                recipe_data["difficulty"] = ai_data.get("difficulty", "Medium")
                recipe_data["hashtags"] = ai_data.get("hashtags", [])
                recipe_data["cuisinetype"] = ai_data.get("cuisinetype", "")
                recipe_data["cookingmethod"] = ai_data.get("cookingmethod", "")

                logger.info("✅ AI enhancement successful")

            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse AI response as JSON: {e}")
                logger.error(f"Raw response: {ai_response[:200]}")

    except Exception as e:
        logger.error(f"AI enhancement error: {e}")


    # Generate literary quote

    try:

        quote_data = generate_literary_quote(recipe_data)

        if quote_data:
            recipe_data['literaryquote'] = quote_data['quote']

            recipe_data['quoteauthor'] = quote_data['author']

            recipe_data['quotesource'] = quote_data.get('source')

            logger.info(f"✨ Added literary quote")

    except Exception as e:

        logger.error(f"Quote failed: {e}")

    return recipe_data


# Human-readable language names for translation prompts.
LANG_NAMES = {
    'ru': 'Russian',
    'en': 'English',
    'it': 'Italian',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
}


def translate_recipe_fields(recipe: dict, target_lang: str) -> dict:
    """Translate a recipe's human-readable text into `target_lang` using the LLM.

    Translates title, description, ingredients[] and instructions[] in a single
    call (cheaper + keeps terminology consistent). Numbers, quantities and units
    are preserved. Returns a NEW dict (does not mutate the input). If the LLM is
    unavailable or anything fails, the original recipe is returned unchanged so
    the import/translate flow never breaks.
    """
    target_lang = (target_lang or '').strip().lower()
    if target_lang not in LANG_NAMES:
        return recipe
    if not (openai_client or openai_api_key):
        logger.info("translate_recipe_fields: no OpenAI client; skipping translation")
        return recipe

    lang_name = LANG_NAMES[target_lang]
    payload = {
        'title': recipe.get('title', ''),
        'description': recipe.get('description', ''),
        'ingredients': [str(x) for x in (recipe.get('ingredients') or []) if str(x).strip()],
        'instructions': [str(x) for x in (recipe.get('instructions') or []) if str(x).strip()],
    }
    # Nothing to translate.
    if not any([payload['title'], payload['description'], payload['ingredients'], payload['instructions']]):
        return recipe

    prompt = (
        f"Translate the following recipe into {lang_name}. "
        f"Translate the cooking text naturally and idiomatically. "
        f"KEEP all numbers, quantities, and measurement units exactly as-is "
        f"(do not convert units). Preserve the SAME number of array items and "
        f"their order. If a field is already in {lang_name}, return it unchanged. "
        f"Return ONLY valid JSON with exactly these keys: "
        f'"title" (string), "description" (string), "ingredients" (array of strings), '
        f'"instructions" (array of strings).\n\n'
        f"Recipe JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        if OPENAI_NEW_API and openai_client:
            resp = openai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
        elif openai_api_key:
            resp = openai.ChatCompletion.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
        else:
            return recipe

        translated = json.loads(content)
    except Exception as e:
        logger.error(f"Recipe translation failed ({target_lang}): {e}")
        return recipe

    out = dict(recipe)
    if isinstance(translated.get('title'), str) and translated['title'].strip():
        out['title'] = translated['title'].strip()
    if isinstance(translated.get('description'), str):
        out['description'] = translated['description'].strip()
    # Only accept arrays if the item count matches, to avoid losing/scrambling steps.
    ti = translated.get('ingredients')
    if isinstance(ti, list) and len(ti) == len(payload['ingredients']) and ti:
        out['ingredients'] = [str(x).strip() for x in ti]
    tn = translated.get('instructions')
    if isinstance(tn, list) and len(tn) == len(payload['instructions']) and tn:
        out['instructions'] = [str(x).strip() for x in tn]
    out['language'] = target_lang
    logger.info(f"✅ Recipe translated to {lang_name}")
    return out


def generate_literary_quote(recipe_data):
    """Generate a literary quote about food/cooking related to this recipe"""
    if not openai_client and not openai_api_key:
        return None

    try:
        title = recipe_data.get('title', 'Unknown')
        cuisine = recipe_data.get('cuisinetype', 'General')
        method = recipe_data.get('cookingmethod', 'Various')

        # Get first 3 ingredients for context
        ingredients = recipe_data.get('ingredients', [])
        key_ingredients = []
        for ing in ingredients[:3]:
            if isinstance(ing, dict):
                key_ingredients.append(ing.get('ingredient', str(ing)))
            else:
                key_ingredients.append(str(ing))

        ingredients_text = ', '.join(key_ingredients) if key_ingredients else 'various ingredients'

        prompt = f"""You are a literary food writer creating inspiring quotes about cooking and food.

Recipe: {title}
Cuisine: {cuisine}
Method: {method}
Ingredients: {ingredients_text}

Generate ONE quote about food or cooking (under 25 words) in this format:
"Quote text" - Author Name"""

        # Make API call (supports both old and new OpenAI API)
        if openai_client:
            try:
                response = openai_client.chat.completions.create(
                    model=AI_MODEL,  # ✅ Use configured model
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=150,  # ✅ Changed from max_completion_tokens (works for both gpt-4o-mini and gpt-5)
                    temperature=0.7
                )
                quote_text = response.choices[0].message.content.strip()
                logger.info(f"🧐 DEBUG - Raw quote from OpenAI: {quote_text!r}")
                logger.info(f"🧐 DEBUG - Length: {len(quote_text)} characters")
                logger.info(f"🧐 DEBUG - Contains ' - ': {' - ' in quote_text}")

            except Exception as e:
                logger.error(f"OpenAI quote error: {e}")
                return None
        elif openai_api_key:
            try:
                response = openai.ChatCompletion.create(
                    model=AI_MODEL,  # ✅ Use configured model
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=150,  # ✅ Changed from max_completion_tokens
                    temperature=0.7
                )
                quote_text = response.choices[0].message.content.strip()
                logger.info(f"🧐 DEBUG - Raw quote from OpenAI: {quote_text!r}")
                logger.info(f"🧐 DEBUG - Length: {len(quote_text)} characters")
                logger.info(f"🧐 DEBUG - Contains ' - ': {' - ' in quote_text}")

            except Exception as e:
                logger.error(f"OpenAI legacy quote error: {e}")
                return None
        else:
            return None

        # Parse quote and author
        if ' - ' in quote_text:
            parts = quote_text.rsplit(' - ', 1)
            quote = parts[0].strip().strip('"').strip('"').strip('"')
            author = parts[1].strip()
            logger.info(f"✨ Generated quote for '{title}'")
            return {'quote': quote, 'author': author, 'source': None}
        else:
            return {'quote': quote_text.strip().strip('"'), 'author': 'Culinary Wisdom', 'source': None}

    except Exception as e:
        logger.error(f"Quote generation error: {e}")
        return None

        # JSON-LD extraction with multiple @type support


# Site-specific extraction rules
SITE_RULES = {
    'lacucinaitaliana.it': {
        'selectors': {
            'ingredients': [
                'div.recipe-ingredients li',
                'ul.ingredients li',
                'div[data-ingredient]',
                '.ingredient-list li',
                'div.ingredients-container li'
            ],
            'instructions': [
                'div.recipe-preparation ol li',
                'div.recipe-method ol li',
                'ol.preparation-steps li',
                'div.instructions ol li',
                'div.steps li'
            ],
            'title': ['h1.recipe-title', 'h1.article-title', 'h1'],
            'servings': ['span.servings', 'div.yield', '.recipe-yield']
        },
        'language': 'it'
    },
    'recipetineats.com': {
        'selectors': {
            'ingredients': [
                'ul.wprm-recipe-ingredients li',
                'div.wprm-recipe-ingredient',
                'li.wprm-recipe-ingredient'
            ],
            'instructions': [
                'ul.wprm-recipe-instructions li',
                'div.wprm-recipe-instruction-text',
                'li.wprm-recipe-instruction'
            ],
            'title': ['h2.wprm-recipe-name', 'h1'],
            'servings': ['span.wprm-recipe-servings', 'div.wprm-recipe-servings']
        },
        'language': 'en'
    },
    'allrecipes.com': {
        'selectors': {
            'ingredients': [
                'ul.mntl-structured-ingredients__list li',
                'span.mntl-structured-ingredients__item'
            ],
            'instructions': [
                'ol.mntl-sc-block-group--OL li',
                'div.mntl-sc-block-html p'
            ]
        },
        'language': 'en'
    }
}


def extract_with_site_rules(soup, url):
    """Try site-specific extraction rules based on domain"""
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        # Check if we have rules for this domain
        if domain not in SITE_RULES:
            logger.debug(f"No site-specific rules for {domain}")
            return None

        rules = SITE_RULES[domain]
        logger.info(f"🎯 Using site-specific rules for {domain}")

        recipe = {}

        # Extract title
        if 'title' in rules.get('selectors', {}):
            for selector in rules['selectors']['title']:
                title_elem = soup.select_one(selector)
                if title_elem:
                    recipe['name'] = title_elem.get_text(strip=True)
                    logger.debug(f"  ✓ Title: {recipe['name'][:50]}")
                    break

        # Extract ingredients
        if 'ingredients' in rules.get('selectors', {}):
            for selector in rules['selectors']['ingredients']:
                elements = soup.select(selector)
                if elements and len(elements) > 2:  # At least 3 ingredients
                    recipe['recipeIngredient'] = [
                        el.get_text(strip=True) for el in elements
                        if el.get_text(strip=True)
                    ]
                    logger.info(f"  ✓ Found {len(recipe['recipeIngredient'])} ingredients with: {selector}")
                    break

        # Extract instructions
        if 'instructions' in rules.get('selectors', {}):
            for selector in rules['selectors']['instructions']:
                elements = soup.select(selector)
                if elements and len(elements) > 1:  # At least 2 steps
                    recipe['recipeInstructions'] = [
                        el.get_text(strip=True) for el in elements
                        if el.get_text(strip=True) and len(el.get_text(strip=True)) > 10
                    ]
                    logger.info(f"  ✓ Found {len(recipe['recipeInstructions'])} instructions with: {selector}")
                    break

        # Extract servings
        if 'servings' in rules.get('selectors', {}):
            for selector in rules['selectors']['servings']:
                serving_elem = soup.select_one(selector)
                if serving_elem:
                    recipe['recipeYield'] = serving_elem.get_text(strip=True)
                    break

        # Validate we got enough data
        has_ingredients = recipe.get('recipeIngredient') and len(recipe['recipeIngredient']) >= 2
        has_instructions = recipe.get('recipeInstructions') and len(recipe['recipeInstructions']) >= 1

        if has_ingredients and has_instructions:
            logger.info(f"✅ Site-specific extraction successful for {domain}")
            return recipe
        else:
            logger.warning(
                f"⚠️ Site-specific extraction incomplete: {len(recipe.get('recipeIngredient', []))} ingredients, {len(recipe.get('recipeInstructions', []))} instructions")
            return None

    except Exception as e:
        logger.error(f"Site-specific extraction error: {e}")
        return None


# ============================================================================
# AI-POWERED EXTRACTION (Strategy 3)
# ============================================================================

def extract_recipe_with_ai(soup, url):
    """
    Use OpenAI GPT-4 to intelligently extract recipe from HTML
    This is a universal fallback when structured data and site rules fail

    Args:
        soup: BeautifulSoup object of the page
        url: URL of the recipe page

    Returns:
        dict: Recipe data in standard format, or None if extraction fails
    """
    global ai_extraction_count, ai_total_cost, ai_total_tokens
    recipe_data = None
    try:
        # Check if AI extraction is enabled
        if not USE_AI_EXTRACTION:
            logger.debug("AI extraction disabled via config")
            return None

        # Check if OpenAI is available
        if not OPENAI_NEW_API or not openai_client:
            logger.warning("OpenAI not configured, skipping AI extraction")
            return None

        logger.info("→ Strategy 3: AI-powered extraction (GPT-4)")

        # Extract clean text from the page
        # Remove scripts, styles, navigation, and other non-content elements
        soup_copy = BeautifulSoup(str(soup), 'html.parser')
        for element in soup_copy(['script', 'style', 'nav', 'header', 'footer',
                                  'aside', 'iframe', 'noscript', 'svg']):
            element.decompose()

        # Get visible text
        page_text = soup_copy.get_text(separator='\n', strip=True)

        # Smart truncation that preserves recipe content
        max_chars = 15000  # ~4000 tokens (better for large pages)
        if len(page_text) > max_chars:
            # Split into lines
            lines = page_text.split('\n')

            # Identify important lines (likely to contain recipe data)
            recipe_keywords = [
                'ingredient', 'ingredients', 'cups', 'cup', 'tablespoon', 'teaspoon',
                'oz', 'ounce', 'gram', 'kg', 'ml', 'liter',
                'method', 'instruction', 'step', 'directions',
                'serves', 'servings', 'yield', 'prep', 'cook', 'total time'
            ]

            # Score each line by importance
            scored_lines = []
            for line in lines:
                line_lower = line.lower()
                score = sum(1 for keyword in recipe_keywords if keyword in line_lower)
                # Boost score for lines that look like list items
                if line.strip().startswith(('-', '•', '1.', '2.', '3.')):
                    score += 2
                scored_lines.append((score, line))

            # Sort by score (highest first), keeping original order for same scores
            scored_lines.sort(key=lambda x: (-x[0], lines.index(x[1])))

            # Take the most important lines up to max_chars
            important_lines = []
            char_count = 0
            for score, line in scored_lines:
                if char_count + len(line) > max_chars:
                    break
                if score > 0:  # Only include lines with recipe keywords
                    important_lines.append(line)
                    char_count += len(line) + 1  # +1 for newline

            # Re-sort to maintain original document order
            important_lines.sort(key=lambda x: lines.index(x))
            page_text = '\n'.join(important_lines)

            logger.info(f"Smart truncation: kept {len(important_lines)} important lines ({char_count} chars)")

        # Get page title for context
        title = soup.find('h1')
        page_title = title.get_text(strip=True) if title else "Unknown Recipe"

        prompt = f"""You are a professional recipe extraction expert. Extract the complete recipe information from this webpage text with high accuracy.

        Recipe Page URL: {url}
        Page Title: {page_title}

        Webpage Content:
        {page_text}

        Extract and return a JSON object with this EXACT structure:
        {{
            "name": "Full recipe title (string, required)",
            "description": "Brief description of the dish (string, optional)",
            "recipeIngredient": [
                "IMPORTANT: Include EVERY ingredient with exact quantities",
                "Example: 2 cups all-purpose flour",
                "Example: 1/4 teaspoon salt",
                "Example: Fresh basil leaves, to taste"
            ],
            "recipeInstructions": [
                "Step 1: Detailed first instruction",
                "Step 2: Detailed second instruction",
                "Include ALL steps in order"
            ],
            "recipeYield": "Number of servings (e.g., '4 servings', '6-8 servings')",
            "prepTime": "ISO 8601 format (e.g., 'PT15M' for 15 minutes, 'PT1H30M' for 1.5 hours)",
            "cookTime": "ISO 8601 format (e.g., 'PT30M' for 30 minutes)",
            "totalTime": "ISO 8601 format (e.g., 'PT45M' for 45 minutes)"
        }}

        CRITICAL INSTRUCTIONS:
        1. Extract ALL ingredients - do not skip any
        2. Include exact quantities and units (cups, tbsp, tsp, oz, grams, etc.)
        3. Preserve measurement fractions (1/2, 1/4, 3/4)
        4. Each instruction should be a complete step
        5. Maintain the original order of ingredients and steps
        6. If ingredients have no quantity (like "salt to taste"), include them as-is
        7. For times: PT15M = 15 minutes, PT1H = 1 hour, PT1H30M = 1.5 hours
        8. If ANY field except description is not available, omit it completely (do not guess)
        9. Name must be the actual recipe title, not "Unknown Recipe"
        10. If description is missing generate it based on recipe contents.
        11. Return ONLY valid JSON with no markdown, explanations, or extra text

        VALIDATION:
        - recipeIngredient must have at least 2 items
        - recipeInstructions must have at least 1 item
        - name must not be "Unknown Recipe" or empty

                Recipe JSON:"""

        # ✅ FIX: Call OpenAI API BEFORE validation
        try:
            start_time = datetime.now()

            response = openai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a recipe extraction expert. Extract structured recipe data and return valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=AI_MAX_TOKENS,
                response_format={"type": "json_object"}
            )

            result = response.choices[0].message.content
            logger.info(f"✅ OpenAI responded with {len(result)} characters")

            # Parse the JSON response
            recipe_data = json.loads(result)
            logger.info(f"✅ Successfully parsed JSON")
            logger.info(f"DEBUG - Parsed keys: {list(recipe_data.keys())}")

            # Calculate cost
            tokens_used = response.usage.total_tokens
            total_cost = (response.usage.prompt_tokens / 1_000_000) * 0.150 + \
                        (response.usage.completion_tokens / 1_000_000) * 0.600

            elapsed = (datetime.now() - start_time).total_seconds()

            if AI_COST_TRACKING:
                ai_extraction_count += 1
                ai_total_tokens += tokens_used
                ai_total_cost += total_cost

        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse OpenAI response: {e}")
            logger.error(f"Response: {result[:500] if 'result' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"❌ OpenAI API call failed: {e}")
            return None

        # NOW validate we got meaningful data
        ingredients = recipe_data.get('recipeIngredient', [])
        instructions = recipe_data.get('recipeInstructions', [])
        logger.info(f"   - Time: {elapsed:.2f}s")

        if AI_COST_TRACKING:
            logger.info(f"   - Session total: {ai_extraction_count} extractions, ${ai_total_cost:.6f}")

        return recipe_data

    except json.JSONDecodeError as e:
        logger.error(f"AI extraction JSON parse error: {e}")
        logger.error(f"Response content: {result[:200] if 'result' in locals() else 'N/A'}")
        return None
    except Exception as e:
        logger.error(f"AI extraction error: {e}")
        logger.error(traceback.format_exc())
        return None


# ============================================================================
# END AI-POWERED EXTRACTION
# ============================================================================


def extract_json_ld(soup):
    """Extract recipe from JSON-LD with improved parsing and @graph support"""
    try:
        json_scripts = soup.find_all('script', type='application/ld+json')

        for script in json_scripts:
            try:
                # Handle None or empty script content
                if not script.string:
                    logger.debug("Skipping empty JSON-LD script")
                    continue

                # Clean and parse JSON
                script_content = script.string.strip()
                if not script_content:
                    continue

                data = json.loads(script_content)

                # Strategy 1: Handle @graph structure (WordPress sites)
                if isinstance(data, dict) and '@graph' in data:
                    logger.debug("Found @graph structure, searching for Recipe")
                    for item in data['@graph']:
                        if is_recipe_type(item.get('@type')):
                            logger.info("✓ Found Recipe in @graph")
                            return item

                # Strategy 2: Handle list of items
                if isinstance(data, list):
                    logger.debug(f"Found list with {len(data)} items")
                    for item in data:
                        if isinstance(item, dict) and is_recipe_type(item.get('@type')):
                            logger.info("✓ Found Recipe in list")
                            return item

                # Strategy 3: Handle single recipe object
                elif isinstance(data, dict) and is_recipe_type(data.get('@type')):
                    logger.info("✓ Found Recipe as single object")
                    return data

                # Strategy 4: Search nested structures
                elif isinstance(data, dict):
                    # Check for Recipe nested in other types (like Article)
                    if 'recipeInstructions' in data or 'recipeIngredient' in data:
                        logger.info("✓ Found Recipe-like properties in object")
                        return data

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error in script: {str(e)[:100]}")
                continue
            except AttributeError as e:
                logger.warning(f"Attribute error in JSON-LD: {str(e)}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected error parsing JSON-LD: {str(e)}")
                continue

        logger.debug("No Recipe found in any JSON-LD scripts")
        return None

    except Exception as e:
        logger.error(f"JSON-LD extraction error: {e}")
        return None

def extract_microdata(soup):
    """Extract recipe from microdata"""
    try:
        recipe_elem = soup.find(attrs={"itemtype": "https://schema.org/Recipe"}) or \
                     soup.find(attrs={"itemtype": "http://schema.org/Recipe"})

        if not recipe_elem:
            return None

        recipe = {}

        title_elem = recipe_elem.find(attrs={"itemprop": "name"})
        if title_elem:
            recipe['name'] = title_elem.get_text(strip=True)

        desc_elem = recipe_elem.find(attrs={"itemprop": "description"})
        if desc_elem:
            recipe['description'] = desc_elem.get_text(strip=True)

        prep_elem = recipe_elem.find(attrs={"itemprop": "prepTime"})
        if prep_elem:
            recipe['prepTime'] = prep_elem.get('datetime') or prep_elem.get_text(strip=True)

        cook_elem = recipe_elem.find(attrs={"itemprop": "cookTime"})
        if cook_elem:
            recipe['cookTime'] = cook_elem.get('datetime') or cook_elem.get_text(strip=True)

        yield_elem = recipe_elem.find(attrs={"itemprop": "recipeYield"})
        if yield_elem:
            recipe['recipeYield'] = yield_elem.get_text(strip=True)

        ingredient_elems = recipe_elem.find_all(attrs={"itemprop": "recipeIngredient"})
        if ingredient_elems:
            recipe['recipeIngredient'] = [elem.get_text(strip=True) for elem in ingredient_elems]

        instruction_elems = recipe_elem.find_all(attrs={"itemprop": "recipeInstructions"})
        if instruction_elems:
            instructions = []
            for elem in instruction_elems:
                text = elem.get_text(strip=True)
                if text:
                    instructions.append(text)
            recipe['recipeInstructions'] = instructions

        return recipe if recipe else None
    except Exception as e:
        logger.error(f"Microdata extraction error: {e}")
        return None

# Unit conversion factors. Each entry maps a source unit (lower-case, dot-stripped)
# to (target_unit, factor). value_in_target = value_in_source * factor.
_UNIT_CONVERSIONS = {
    'metric_to_imperial': {
        # Weight
        'g':   ('oz', 0.035274),
        'gr':  ('oz', 0.035274),
        'gram': ('oz', 0.035274),
        'grams': ('oz', 0.035274),
        'kg':  ('lb', 2.20462),
        'kilogram': ('lb', 2.20462),
        # Volume
        'ml':  ('fl oz', 0.033814),
        'milliliter': ('fl oz', 0.033814),
        'l':   ('cup', 4.22675),
        'liter': ('cup', 4.22675),
        'litre': ('cup', 4.22675),
        # Length
        'cm':  ('inch', 0.393701),
        'mm':  ('inch', 0.0393701),
    },
    'imperial_to_metric': {
        # Weight
        'oz':  ('g', 28.3495),
        'ounce': ('g', 28.3495),
        'ounces': ('g', 28.3495),
        'lb':  ('g', 453.592),
        'lbs': ('g', 453.592),
        'pound': ('g', 453.592),
        'pounds': ('g', 453.592),
        # Volume
        'tsp': ('ml', 4.92892),
        'teaspoon': ('ml', 4.92892),
        'teaspoons': ('ml', 4.92892),
        'tbsp': ('ml', 14.7868),
        'tablespoon': ('ml', 14.7868),
        'tablespoons': ('ml', 14.7868),
        'fl oz': ('ml', 29.5735),
        'cup': ('ml', 236.588),
        'cups': ('ml', 236.588),
        'pint': ('ml', 473.176),
        'pints': ('ml', 473.176),
        'quart': ('l', 0.946353),
        'quarts': ('l', 0.946353),
        'qt':  ('l', 0.946353),
        'gallon': ('l', 3.78541),
        'gallons': ('l', 3.78541),
        # Length
        'inch': ('cm', 2.54),
        'inches': ('cm', 2.54),
        'in':  ('cm', 2.54),
    }
}


def _convert_single_ingredient(ing, table):
    """Return a new ingredient dict/string with quantity & unit converted."""
    if isinstance(ing, dict):
        text_source = ing.get('original_text') or ing.get('ingredient') or ing.get('text') or ''
    else:
        text_source = str(ing)

    if not text_source:
        return ing

    qty_value, unit, name = extract_ingredient_parts(text_source)
    if qty_value is None or not unit:
        return ing

    unit_key = unit.lower().rstrip('.').strip()
    if unit_key not in table:
        return ing

    new_unit, factor = table[unit_key]
    new_value = qty_value * factor
    new_qty_str = format_quantity(new_value, text_source)
    new_text = f"{new_qty_str} {new_unit} {name}".strip()

    if isinstance(ing, dict):
        result = dict(ing)
        result['original_text'] = new_text
        # Update amount/unit fields if present
        if 'amount' in result:
            result['amount'] = new_qty_str
        if 'unit' in result:
            result['unit'] = new_unit
        # Keep 'ingredient'/'text' aliases consistent for downstream consumers
        if 'ingredient' in result:
            result['ingredient'] = new_text
        if 'text' in result:
            result['text'] = new_text
        return result
    return new_text


def convert_units(ingredients, from_system='metric', to_system='imperial'):
    """Convert ingredient units between metric and imperial systems."""
    conversion_key = f"{from_system}_to_{to_system}"
    table = _UNIT_CONVERSIONS.get(conversion_key)
    if not table:
        return ingredients

    if not isinstance(ingredients, list):
        return ingredients

    return [_convert_single_ingredient(ing, table) for ing in ingredients]


# ============================================================================
# AUTHENTICATION API ENDPOINTS
# ============================================================================

@app.route('/api/auth/signup', methods=['POST'])
@rate_limit(max_requests=5, window_seconds=300, scope='auth_signup')
def signup():
    """Create new user account"""
    try:
        data = request.get_json()

        # Validate required fields
        if not data.get('email') or not data.get('password') or not data.get('username'):
            return jsonify({'error': 'Email, username, and password are required'}), 400

        # Validate email format. Disable deliverability (DNS) check so signup
        # doesn't fail on test domains, blocked DNS, or transient lookups.
        from email_validator import validate_email, EmailNotValidError
        try:
            validate_email(data['email'], check_deliverability=False)
        except EmailNotValidError as e:
            return jsonify({'error': f'Invalid email address: {e}'}), 400

        # Validate password length
        if len(data['password']) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        # Check if email already exists
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already registered'}), 400

        # Check if username already exists
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already taken'}), 400

        # Create new user
        user = User(
            email=data['email'],
            username=data['username'],
            display_name=data.get('display_name', data['username'])
        )
        user.set_password(data['password'])
        legacy_token = user.generate_session_token()  # kept for backward compat

        db.session.add(user)
        db.session.commit()

        # Issue JWT access + refresh token pair (new clients).
        access_token, access_ttl = issue_access_token(user.id)
        refresh_token = issue_refresh_token(
            user.id,
            user_agent = request.headers.get('User-Agent'),
            ip_address = request.remote_addr,
        )

        logger.info(f"✅ New user created: {user.username}")

        return jsonify({
            'success': True,
            # Legacy field — still accepted by require_auth.
            'token': legacy_token,
            # New auth pair (v1 clients should use these).
            'access_token':  access_token,
            'refresh_token': refresh_token,
            'token_type':    'Bearer',
            'expires_in':    access_ttl,
            'user': {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'language': user.language or 'ru'
            }
        }), 201

    except Exception as e:
        logger.error(f"❌ Signup error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Signup failed'}), 500


@app.route('/api/auth/login', methods=['POST'])
@rate_limit(max_requests=10, window_seconds=300, scope='auth_login')
def login():
    """Authenticate user and return session token"""
    try:
        data = request.get_json()

        if not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email and password required'}), 400

        # Find user by email
        user = User.query.filter_by(email=data['email']).first()

        if not user or not user.check_password(data['password']):
            logger.warning(f"⚠️ Failed login attempt for: {data.get('email')}")
            return jsonify({'error': 'Invalid email or password'}), 401

        # Generate legacy opaque session token (kept for old clients).
        legacy_token = user.generate_session_token()
        user.last_login = utcnow()
        db.session.commit()

        # Issue JWT access + refresh token pair (new clients).
        access_token, access_ttl = issue_access_token(user.id)
        refresh_token = issue_refresh_token(
            user.id,
            user_agent = request.headers.get('User-Agent'),
            ip_address = request.remote_addr,
        )

        logger.info(f"✅ User logged in: {user.username}")

        return jsonify({
            'success': True,
            # Legacy.
            'token': legacy_token,
            # v1 auth pair.
            'access_token':  access_token,
            'refresh_token': refresh_token,
            'token_type':    'Bearer',
            'expires_in':    access_ttl,
            'user': {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'default_servings': user.default_servings,
                'preferred_units': user.preferred_units,
                'language': user.language or 'ru'
            }
        })

    except Exception as e:
        logger.error(f"❌ Login error: {str(e)}")
        return jsonify({'error': 'Login failed'}), 500


@app.route('/api/auth/logout', methods=['POST'])
@require_auth
def logout():
    """Invalidate session(s).

    Body may contain `refresh_token` — if present, only that refresh token is
    revoked (single-device logout). Otherwise we revoke ALL active refresh
    tokens for the user *and* clear the legacy opaque session column
    (everywhere-logout).
    """
    try:
        user = request.current_user
        body = request.get_json(silent=True) or {}
        single_refresh = (body.get('refresh_token') or '').strip()

        if single_refresh:
            rt = find_active_refresh_token(single_refresh)
            if rt and rt.user_id == user.id:
                rt.revoke()
                db.session.commit()
                logger.info(f"✅ Single-device logout for {user.username}")
            else:
                logger.info(f"Logout: refresh token not found/active for {user.username}")
            return jsonify({'success': True, 'scope': 'single'})

        # Global logout: nuke all refresh tokens + legacy session.
        active = RefreshToken.query.filter_by(user_id=user.id, revoked_at=None).all()
        for rt in active:
            rt.revoke()
        user.session_token = None
        user.session_token_hash = None
        user.session_expires = None
        db.session.commit()

        logger.info(f"✅ Global logout for {user.username} (revoked {len(active)} refresh tokens)")
        return jsonify({'success': True, 'scope': 'all', 'revoked_refresh_tokens': len(active)})

    except Exception as e:
        logger.error(f"❌ Logout error: {str(e)}")
        return jsonify({'error': 'Logout failed'}), 500


@app.route('/api/auth/refresh', methods=['POST'])
@rate_limit(max_requests=30, window_seconds=300, scope='auth_refresh')
def refresh_access_token():
    """Exchange a valid refresh token for a new access token (and rotated refresh).

    Refresh token rotation: each successful refresh revokes the presented
    refresh and issues a brand-new one. Stolen tokens become single-use this way.
    """
    try:
        body = request.get_json(silent=True) or {}
        raw_refresh = (body.get('refresh_token') or '').strip()
        if not raw_refresh:
            return jsonify({'error': 'refresh_token required'}), 400

        rt = find_active_refresh_token(raw_refresh)
        if not rt:
            logger.warning("Refresh attempt with invalid or revoked token")
            return jsonify({'error': 'invalid_refresh_token'}), 401

        user = User.query.get(rt.user_id)
        if not user:
            return jsonify({'error': 'user_not_found'}), 401

        # Rotate: revoke old, issue new.
        rt.revoke()
        db.session.commit()

        access_token, access_ttl = issue_access_token(user.id)
        new_refresh = issue_refresh_token(
            user.id,
            user_agent = request.headers.get('User-Agent'),
            ip_address = request.remote_addr,
        )

        return jsonify({
            'success':       True,
            'access_token':  access_token,
            'refresh_token': new_refresh,
            'token_type':    'Bearer',
            'expires_in':    access_ttl,
        })

    except Exception as e:
        logger.error(f"❌ Refresh error: {e}")
        return jsonify({'error': 'Refresh failed'}), 500


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def get_current_user():
    """Get current authenticated user information"""
    user = request.current_user
    return jsonify({
        'id': user.id,
        'email': user.email,
        'username': user.username,
        'display_name': user.display_name,
        'default_servings': user.default_servings,
        'preferred_units': user.preferred_units,
        'language': user.language or 'ru',
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'last_login': user.last_login.isoformat() if user.last_login else None
    })


@app.route('/api/auth/me', methods=['PATCH'])
@require_auth
def update_current_user():
    """Update mutable fields of the current user (language, display name)."""
    try:
        data = request.get_json(silent=True) or {}
        user = request.current_user

        SUPPORTED = {'ru', 'en', 'it', 'es', 'fr', 'de'}
        if 'language' in data:
            lang = data['language']
            if lang not in SUPPORTED:
                return jsonify({
                    'error': 'Unsupported language',
                    'supported': sorted(SUPPORTED)
                }), 400
            user.language = lang

        # Accept both 'name' and 'display_name' for flexibility.
        new_name = data.get('display_name', data.get('name'))
        if new_name:
            user.display_name = str(new_name).strip()[:100]

        db.session.commit()
        return jsonify({
            'user': {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'display_name': user.display_name,
                'default_servings': user.default_servings,
                'preferred_units': user.preferred_units,
                'language': user.language or 'ru'
            }
        })
    except Exception as e:
        logger.error(f"❌ Update me error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Update failed'}), 500

@app.route('/api/health', methods=['GET', 'OPTIONS'])
def health_check():
    if request.method == 'OPTIONS':
        resp = make_response('', 204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return resp
    return jsonify({
        'status': 'ok',
        'message': 'BunnyKitchen API is healthy',
        'timestamp': utcnow().isoformat(),
        'openai_configured': bool(openai_client)
    })
# Unit conversion functions
@app.route('/')
def index():
    """Serve the frontend HTML if present, otherwise return a JSON health summary."""
    frontend_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend.html'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bunnykitchen-updated-behr-palette-2.html'),
    ]
    for candidate in frontend_candidates:
        if os.path.exists(candidate):
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as exc:
                logger.error(f"Failed to read frontend file {candidate}: {exc}")
                break
    return jsonify({
        'status': 'healthy',
        'service': 'BunnyKitchen AI Complete Backend',
        'version': '3.1.0',
        'features': [
            'recipe_extraction', 'image_extraction', 'ai_text_cleanup',
            'recipe_scaling', 'unit_conversion', 'categories', 'nutrition_data',
            'unified_app_compatibility', 'complex_database_schema'
        ],
        'openai_configured': bool(openai_client or openai_api_key),
        'openai_api_version': 'new' if openai_client else 'legacy' if openai_api_key else 'none',
        'endpoints': [
            '/', '/api/recipes/extract', '/api/recipes', '/api/recipes/<id>',
            '/api/recipes/<id>/scale', '/api/recipes/<id>/checklist',
            '/api/convert-units','/api/scale-data', '/api/categories'
        ]
    })

# API ROUTES - COMPLETE SET FROM ORIGINAL
def extract_recipe_from_text(soup):
    """Extract recipe from plain text when no structured data exists - ULTIMATE VERSION"""
    try:
        recipe = {}

        # Extract title from h1 or title tag
        title_elem = soup.find('h1') or soup.find('title')
        if title_elem:
            recipe['name'] = title_elem.get_text(strip=True)

        # Look for description in meta tags
        desc_meta = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', property='og:description')
        if desc_meta:
            recipe['description'] = desc_meta.get('content', '')

        # ULTIMATE INGREDIENT DETECTION - 7 SEARCH STRATEGIES
        ingredients = []

        # Method 1: Look for ingredient lists near "ingredients" headings
        ingredient_headings = soup.find_all(['h2', 'h3', 'h4', 'h5'], string=re.compile(r'ingredients?', re.IGNORECASE))

        for heading in ingredient_headings:
            containers = [
                heading.find_next_sibling(['ul', 'ol']),
                heading.find_next(['ul', 'ol']),
                heading.parent.find_next(['ul', 'ol']),
                heading.find_next_sibling('div'),
                heading.find_next('div', class_=re.compile(r'ingredient', re.IGNORECASE))
            ]

            for container in containers:
                if container:
                    items = container.find_all('li')
                    for item in items:
                        text = item.get_text(strip=True)
                        if text and (re.match(r'^\s*[\d½¼¾⅓⅔⅛⅜⅝⅞]', text) or
                                     re.match(r'^\s*\d+\s*[-–]\s*\d+', text)):
                            ingredients.append(text)
                            if len(ingredients) >= 30:
                                break
                    if ingredients:
                        break
            if ingredients:
                break

        # Method 2: Search by CSS classes commonly used for ingredients
        if not ingredients:
            ingredient_classes = [
                'recipe-ingredient', 'ingredients', 'ingredient-list', 'recipe-ingredients',
                'ingredient-item', 'ingredient', 'recipe-list', 'ingredients-list'
            ]

            for class_name in ingredient_classes:
                elements = soup.find_all(['div', 'ul', 'ol', 'section'], class_=re.compile(class_name, re.IGNORECASE))
                for element in elements:
                    items = element.find_all(['li', 'p', 'div'])
                    for item in items:
                        text = item.get_text(strip=True)
                        if text and re.match(r'^\s*[\d½¼¾⅓⅔]', text):
                            ingredients.append(text)
                            if len(ingredients) >= 30:
                                break
                    if ingredients:
                        break
                if ingredients:
                    break

        # Method 3: Search by data attributes (modern recipe sites)
        if not ingredients:
            data_attrs = ['data-ingredient', 'data-recipe-ingredient', 'data-name']
            for attr in data_attrs:
                elements = soup.find_all(attrs={attr: True})
                for element in elements:
                    text = element.get_text(strip=True) or element.get(attr)
                    if text and len(text) > 3:
                        ingredients.append(text)
                        if len(ingredients) >= 30:
                            break
                if ingredients:
                    break

        # Method 4: Look for any text containing "ingredients" and search nearby
        if not ingredients:
            ingredient_sections = soup.find_all(string=re.compile(r'ingredients?', re.IGNORECASE))
            for section in ingredient_sections:
                if section.parent:
                    parent = section.parent
                    search_areas = [
                        parent, parent.parent, parent.find_next_sibling(),
                        parent.find_next(), parent.find_previous_sibling()
                    ]

                    for area in search_areas:
                        if area:
                            lists = area.find_all(['ul', 'ol'])
                            for ul in lists:
                                items = ul.find_all('li')
                                for item in items:
                                    text = item.get_text(strip=True)
                                    if text and re.match(r'^\s*[\d½¼¾⅓⅔]', text):
                                        ingredients.append(text)
                                        if len(ingredients) >= 30:
                                            break
                                if ingredients:
                                    break
                            if ingredients:
                                break
                    if ingredients:
                        break

        # Method 5: Search paragraphs that start with quantities (blog-style recipes)
        if not ingredients:
            paragraphs = soup.find_all('p')
            potential_ingredients = []

            for p in paragraphs:
                text = p.get_text(strip=True)
                # Look for paragraphs that start with quantities
                if text and re.match(
                        r'^\s*[\d½¼¾⅓⅔]\s*[\d/]*\s*(cup|tsp|tbsp|pound|oz|gram|ml|liter|large|medium|small)', text,
                        re.IGNORECASE):
                    # Split by sentences or line breaks to get individual ingredients
                    lines = re.split(r'[.;]\s*|\n', text)
                    for line in lines:
                        line = line.strip()
                        if line and re.match(r'^\s*[\d½¼¾⅓⅔]', line):
                            potential_ingredients.append(line)

            # If we found a good chunk of ingredients this way, use them
            if len(potential_ingredients) >= 3:
                ingredients.extend(potential_ingredients[:30])

        # Method 6: Look for divs/sections with specific recipe-related IDs
        if not ingredients:
            recipe_ids = ['ingredients', 'recipe-ingredients', 'ingredient-list', 'ingredients-section']
            for recipe_id in recipe_ids:
                element = soup.find(['div', 'section', 'ul'], id=re.compile(recipe_id, re.IGNORECASE))
                if element:
                    items = element.find_all(['li', 'p', 'div'])
                    for item in items:
                        text = item.get_text(strip=True)
                        if text and re.match(r'^\s*[\d½¼¾⅓⅔]', text):
                            ingredients.append(text)
                            if len(ingredients) >= 30:
                                break
                    if ingredients:
                        break

        # Method 7: ULTIMATE FALLBACK - Broad search with smart filtering
        if not ingredients:
            all_items = soup.find_all(['li', 'p', 'div', 'span'])
            for item in all_items:
                text = item.get_text(strip=True)

                # Enhanced patterns for all possible ingredient formats
                patterns = [
                    r'^\s*[\d½¼¾⅓⅔]\s*[\d/]*\s*(cup|cups|c\.|tsp|teaspoon|teaspoons|t\.|tbsp|tablespoon|tablespoons|T\.|pound|pounds|lb|lbs|oz|ounce|ounces|gram|grams|g\.|kg|kilogram|ml|milliliter|liter|liters|l\.)',
                    r'^\s*\d+\s*(large|medium|small|whole|fresh|dried|frozen|canned)',
                    r'^\s*[\d½¼¾⅓⅔]\s*[\d/]*\s*(clove|cloves|piece|pieces|slice|slices|bunch|bunches|sprig|sprigs|head|heads)',
                    r'^\s*\d+\s*[-–]\s*\d+\s*(tablespoon|tbsp|teaspoon|tsp|cups?|ounces?|oz)',
                    r'^\s*a\s+(pinch|dash|handful|few)\s+of',  # "a pinch of salt"
                    r'^\s*(salt|pepper|sugar|flour|butter|oil|milk|water|egg|eggs)\s*(to taste|as needed|\(.*\))?$',
                    # Common ingredients
                ]

                if text and any(re.match(pattern, text, re.IGNORECASE) for pattern in patterns):
                    # Advanced filtering to exclude non-ingredients
                    skip_patterns = [
                        r'step\s+\d+', r'minute|hour|degree', r'preheat|bake|cook|mix|stir|add',
                        r'serving|portion|yield|makes?', r'preparation|prep\s+time',
                        r'difficulty|rating|review', r'comment|note|tip'
                    ]

                    if not any(re.search(pattern, text, re.IGNORECASE) for pattern in skip_patterns):
                        # Additional length and content checks
                        if 5 <= len(text) <= 150 and not text.startswith(('http', 'www')):
                            ingredients.append(text)
                            if len(ingredients) >= 30:
                                break

        # Method 8: SPECIAL CASE - Recipe card formats (WordPress recipe plugins)
        if not ingredients:
            recipe_cards = soup.find_all(['div', 'section'],
                                         class_=re.compile(r'recipe-card|wp-block-recipe|recipe-plugin', re.IGNORECASE))
            for card in recipe_cards:
                ingredient_sections = card.find_all(['ul', 'ol', 'div'],
                                                    class_=re.compile(r'ingredients?', re.IGNORECASE))
                for section in ingredient_sections:
                    items = section.find_all(['li', 'p'])
                    for item in items:
                        text = item.get_text(strip=True)
                        if text and re.match(r'^\s*[\d½¼¾⅓⅔]', text):
                            ingredients.append(text)
                            if len(ingredients) >= 30:
                                break
                    if ingredients:
                        break
                if ingredients:
                    break

        # Remove duplicates while preserving order
        if ingredients:
            seen = set()
            unique_ingredients = []
            for ingredient in ingredients:
                # Normalize for comparison but keep original
                normalized = re.sub(r'\s+', ' ', ingredient.lower().strip())
                if normalized not in seen and len(normalized) > 3:
                    seen.add(normalized)
                    unique_ingredients.append(ingredient)
            recipe['recipeIngredient'] = unique_ingredients[:25]  # Limit to 25 best ingredients

            # ENHANCED INSTRUCTION DETECTION - 4 SEARCH STRATEGIES
            instructions = []

            # Method 1: Look for instruction headings and nearby lists
            instruction_headings = soup.find_all(['h2', 'h3', 'h4', 'h5'],
                                                 string=re.compile(
                                                     r'instructions?|directions?|method|steps|preparation|how\s+to',
                                                     re.IGNORECASE))

            for heading in instruction_headings:
                containers = [
                    heading.find_next_sibling(['ol', 'ul']),
                    heading.find_next(['ol', 'ul']),
                    heading.parent.find_next(['ol', 'ul']),
                    heading.find_next_sibling('div'),
                    heading.find_next('div', class_=re.compile(r'instruction|direction|method|step', re.IGNORECASE))
                ]

                for container in containers:
                    if container:
                        items = container.find_all('li')
                        step_num = 1
                        for item in items:
                            text = item.get_text(strip=True)
                            if text and len(text) > 15:
                                instructions.append({'text': text, 'name': f'Step {step_num}'})
                                step_num += 1
                                if len(instructions) >= 25:
                                    break
                        if instructions:
                            break
                if instructions:
                    break

            # Method 2: Search by CSS classes commonly used for instructions
            if not instructions:
                instruction_classes = [
                    'recipe-instruction', 'instructions', 'instruction-list', 'recipe-instructions',
                    'instruction-item', 'instruction', 'directions', 'method', 'steps', 'recipe-method',
                    'cooking-instructions', 'recipe-directions', 'how-to'
                ]

                for class_name in instruction_classes:
                    elements = soup.find_all(['div', 'ul', 'ol', 'section'],
                                             class_=re.compile(class_name, re.IGNORECASE))
                    for element in elements:
                        items = element.find_all('li') or element.find_all(['p', 'div'])
                        step_num = 1
                        for item in items:
                            text = item.get_text(strip=True)
                            if text and len(text) > 20:
                                instructions.append({'text': text, 'name': f'Step {step_num}'})
                                step_num += 1
                                if len(instructions) >= 25:
                                    break
                        if instructions:
                            break
                    if instructions:
                        break

            # Method 3: Look for numbered paragraphs or divs (Food.com style)
            if not instructions:
                all_elements = soup.find_all(['p', 'div', 'li'])
                step_num = 1
                for element in all_elements:
                    text = element.get_text(strip=True)
                    # Match patterns like "1.", "Step 1:", etc.
                    if text and re.match(r'^\s*(?:step\s*)?\d+[.):\s]', text, re.IGNORECASE):
                        clean_text = re.sub(r'^\s*(?:step\s*)?\d+[.):\s]+', '', text, flags=re.IGNORECASE).strip()
                        if clean_text and len(clean_text) > 15:
                            instructions.append({'text': clean_text, 'name': f'Step {step_num}'})
                            step_num += 1
                            if len(instructions) >= 25:
                                break

            # Method 4: ULTIMATE FALLBACK - Look for cooking instructions
            if not instructions:
                all_elements = soup.find_all(['p', 'div', 'li'])
                step_num = 1
                for element in all_elements:
                    text = element.get_text(strip=True)

                    cooking_keywords = [
                        'heat', 'cook', 'bake', 'fry', 'boil', 'simmer', 'sauté', 'roast', 'grill',
                        'mix', 'stir', 'whisk', 'combine', 'add', 'pour', 'season', 'serve',
                        'preheat', 'oven', 'pan', 'skillet', 'pot', 'bowl', 'temperature',
                        'minutes', 'hours', 'until', 'degrees'
                    ]

                    if (text and 30 <= len(text) <= 500 and
                            any(keyword in text.lower() for keyword in cooking_keywords) and
                            not re.match(r'^\s*[\d½¼¾⅓⅔]', text)):  # Not an ingredient

                        skip_patterns = [
                            r'subscribe|newsletter|email|comment|review|rating|print|save',
                            r'nutrition|calories|serving|yield|prep\s+time|cook\s+time',
                            r'recipe\s+by|author|chef|copyright|©'
                        ]

                        if not any(re.search(pattern, text, re.IGNORECASE) for pattern in skip_patterns):
                            instructions.append({'text': text, 'name': f'Step {step_num}'})
                            step_num += 1
                            if len(instructions) >= 25:
                                break

            # Remove duplicates and set instructions
            if instructions:
                seen = set()
                unique_instructions = []
                for instruction in instructions:
                    text = instruction['text']
                    normalized = re.sub(r'\s+', ' ', text.lower().strip())
                    if normalized not in seen and len(normalized) > 15:
                        seen.add(normalized)
                        unique_instructions.append(instruction)
                recipe['recipeInstructions'] = unique_instructions[:20]

            # Enhanced servings/yield detection
            text_content = soup.get_text()
            serving_patterns = [
                r'(?:serves?|servings?)\s*:?\s*(\d+)',
                r'(?:makes?|yields?)\s*:?\s*(\d+)',
                r'(\d+)\s*servings?',
                r'(\d+)\s*portions?',
                r'(\d+)-muffin pan',
                r'(\d+)-cup muffin pan'
            ]

            for pattern in serving_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    recipe['recipeYield'] = match.group(1)
                    break

            if 'recipeYield' not in recipe:
                if 'muffin' in text_content.lower():
                    recipe['recipeYield'] = '12'
                elif any(word in text_content.lower() for word in ['cake', 'pie', 'loaf']):
                    recipe['recipeYield'] = '8'
                else:
                    recipe['recipeYield'] = '4'

        # Enhanced validation
        has_ingredients = recipe.get('recipeIngredient') and len(recipe['recipeIngredient']) >= 3

        if has_ingredients:
            return recipe
        else:
            return None

    except Exception as e:
        logger.error(f"Text extraction error: {e}")
        return None

@app.route('/api/recipes/extract', methods=['POST'])
@require_auth
def extract_recipe():
    """Enhanced recipe extraction endpoint"""
    try:
        data = request.json
        url = data.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        # SSRF protection: validate URL before fetching
        _url_valid, _url_err = validate_extraction_url(url)
        if not _url_valid:
            logger.warning(f"Blocked extraction URL: {url!r} — {_url_err}")
            return jsonify({'success': False, 'error': f'Invalid or disallowed URL: {_url_err}'}), 400

        logger.info(f"Extracting recipe from: {url}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,it;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }

        try:
            # SSRF-hardened fetch: validates + pins the IP on every redirect hop.
            response = safe_requests_get(url, headers=headers, timeout=15)
        except ValueError as _ssrf_err:
            logger.warning(f"Blocked extraction URL during fetch: {url!r} — {_ssrf_err}")
            return jsonify({'success': False, 'error': f'Invalid or disallowed URL: {_ssrf_err}'}), 400
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        recipe_data = None
        extraction_method = None

        recipe_data = None
        extraction_method = None

        # Log extraction attempt
        logger.info(f"{'=' * 60}")
        logger.info(f"EXTRACTION ATTEMPT: {url}")
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        logger.info(f"Content Length: {len(response.content)} bytes")
        logger.info(f"{'=' * 60}")

        # Strategy 1: Try JSON-LD (best for structured sites)
        try:
            logger.info("→ Strategy 1: JSON-LD extraction")
            recipe_data = extract_json_ld(soup)
            if recipe_data:
                extraction_method = 'JSON-LD'
                logger.info(f"✅ SUCCESS: JSON-LD found recipe")
            else:
                logger.info("⚠️ JSON-LD: No recipe found")
        except Exception as e:
            logger.warning(f"❌ JSON-LD extraction failed: {e}")

        # Strategy 2: Try site-specific rules
        if not recipe_data:
            try:
                logger.info("→ Strategy 2: Site-specific rules")
                recipe_data = extract_with_site_rules(soup, url)
                if recipe_data:
                    extraction_method = 'Site-Specific Rules'
                    logger.info(f"✅ SUCCESS: Site-specific extraction")
                else:
                    logger.info("⚠️ Site rules: No match or incomplete data")
            except Exception as e:
                logger.warning(f"❌ Site-specific extraction failed: {e}")

        # Strategy 3: Try AI-powered extraction (NEW!) ✨
        if not recipe_data:
            try:
                logger.info("→ Strategy 3: AI-powered extraction")
                recipe_data = extract_recipe_with_ai(soup, url)
                if recipe_data:
                    extraction_method = 'AI-Powered Extraction'
                    logger.info(f"✅ SUCCESS: AI extraction")
                else:
                    logger.info("⚠️ AI: Extraction incomplete or disabled")
            except Exception as e:
                logger.warning(f"❌ AI extraction failed: {e}")

        # Strategy 4: Try Microdata
        if not recipe_data:
            try:
                logger.info("→ Strategy 4: Microdata extraction")
                recipe_data = extract_microdata(soup)
                if recipe_data:
                    extraction_method = 'Microdata'
                    logger.info(f"✅ SUCCESS: Microdata found recipe")
                else:
                    logger.info("⚠️ Microdata: No recipe found")
            except Exception as e:
                logger.warning(f"❌ Microdata extraction failed: {e}")

        # Strategy 5: Try text parsing (fallback)
        if not recipe_data:
            try:
                logger.info("→ Strategy 5: Text parsing (fallback)")
                recipe_data = extract_recipe_from_text(soup)
                if recipe_data:
                    extraction_method = 'Text Parsing'
                    ingredients_count = len(recipe_data.get('recipeIngredient', []))
                    instructions_count = len(recipe_data.get('recipeInstructions', []))
                    logger.info(
                        f"✅ SUCCESS: Text parsing extracted {ingredients_count} ingredients, {instructions_count} instructions")
                else:
                    logger.info("⚠️ Text parsing: No recipe data found")
            except Exception as e:
                logger.warning(f"❌ Text extraction failed: {e}")

        # Final validation
        if not recipe_data:
            logger.error(f"{'=' * 60}")
            logger.error(f"❌❌❌ COMPLETE FAILURE: Could not extract recipe")
            logger.error(f"URL: {url}")
            logger.error(f"{'=' * 60}")

            # Return helpful debug info
            return jsonify({
                'success': False,
                'error': 'Could not extract recipe data from this URL',
                'debug': {
                    'url': url,
                    'status': response.status_code,
                    'has_json_ld_scripts': len(soup.find_all('script', type='application/ld+json')),
                    'title': soup.find('h1').get_text(strip=True) if soup.find('h1') else None,
                    'suggestion': 'Try adding site-specific rules for this domain'
                }
            }), 400

        logger.info(f"✅ Extraction successful via: {extraction_method}")

        # Extract images
        recipe_images = extract_recipe_images(soup, url)
        logger.info(f"🖼️  Image extraction: Found {len(recipe_images)} images")
        if recipe_images:
            logger.info(f"🖼️  Primary image: {recipe_images[:80]}...")
        else:
            logger.warning(f"⚠️  No images found for {url}")

        # Process ingredients and instructions
        raw_ingredients = safe_get_attribute(recipe_data, 'recipeIngredient', [])
        raw_instructions = safe_get_attribute(recipe_data, 'recipeInstructions', [])

        # Apply AI text cleanup if available
        if openai_client or openai_api_key:
            try:
                clean_ingredients = enhance_text_with_ai(raw_ingredients, "ingredients")
                clean_instructions = enhance_text_with_ai(raw_instructions, "instructions")
            except Exception:
                logger.warning("AI text cleanup failed; using raw ingredients/instructions", exc_info=True)
                clean_ingredients = raw_ingredients
                clean_instructions = raw_instructions
        else:
            clean_ingredients = raw_ingredients
            clean_instructions = raw_instructions

        # Process ingredients
        ingredients = []
        for ingredient_text in (clean_ingredients if isinstance(clean_ingredients, list) else raw_ingredients):
            if isinstance(ingredient_text, str) and ingredient_text.strip():
                ingredients.append(ingredient_text.strip())

        # Process instructions  
        instructions = []
        for instruction in (clean_instructions if isinstance(clean_instructions, list) else raw_instructions):
            if isinstance(instruction, dict):
                text = instruction.get('text') or str(instruction)
            else:
                text = str(instruction)

            if text and text.strip():
                instructions.append(text.strip())

        # Create normalized recipe data
        normalized_recipe = {
            'title': sanitize_string(safe_get_attribute(recipe_data, 'name') or safe_get_attribute(recipe_data, 'title') or 'Extracted Recipe'),
            'description': sanitize_string(safe_get_attribute(recipe_data, 'description', '')),
            'sourceurl': sanitize_string(url),
            'imageurl': recipe_images[0] if recipe_images else '',
            'all_images': recipe_images,
            'preptime': sanitize_integer(parse_time_string(safe_get_attribute(recipe_data, 'prepTime', ''))),
            'cooktime': sanitize_integer(parse_time_string(safe_get_attribute(recipe_data, 'cookTime', ''))),
            'servings': sanitize_integer(extract_servings(safe_get_attribute(recipe_data, 'recipeYield') or safe_get_attribute(recipe_data, 'servings')), 4),
            'difficulty': 'Medium',
            'ingredients': ingredients,
            'instructions': instructions
        }

        # Calculate total time
        normalized_recipe['totaltime'] = normalized_recipe['preptime'] + normalized_recipe['cooktime']

        # Enhance with AI if available
        normalized_recipe = enhance_with_ai(normalized_recipe, url)

        # Translate the recipe into the requested language (falls back to the
        # user's stored preference). The frontend sends `lang` = current UI
        # language so imported recipes appear in the user's chosen language.
        target_lang = (data.get('lang') or getattr(request.current_user, 'language', None) or 'ru')
        normalized_recipe = translate_recipe_fields(normalized_recipe, target_lang)

        logger.info(f"Recipe extracted using {extraction_method}: {normalized_recipe.get('title', 'Unknown')}")

        # CHECK FOR DUPLICATES BEFORE RETURNING
        normalized_title = normalize_title(normalized_recipe['title'])
        normalized_url = normalize_url(url)

        duplicate_info = None
        user_recipes = Recipe.query.filter(
            Recipe.user_id == request.current_user.id
        ).all()

        for recipe in user_recipes:
            if normalize_title(recipe.title) == normalized_title:
                duplicate_info = {
                    'is_duplicate': True,
                    'match_type': 'title',
                    'existing_recipe': {
                        'id': recipe.id,
                        'title': recipe.title,
                        'created_at': recipe.created_at.isoformat() if recipe.created_at else None
                    }
                }
                logger.info(f"Duplicate detected by title: {recipe.title}")
                break
            if recipe.sourceurl and normalize_url(recipe.sourceurl) == normalized_url:
                duplicate_info = {
                    'is_duplicate': True,
                    'match_type': 'url',
                    'existing_recipe': {
                        'id': recipe.id,
                        'title': recipe.title,
                        'created_at': recipe.created_at.isoformat() if recipe.created_at else None
                    }
                }
                logger.info(f"Duplicate detected by URL: {recipe.title}")
                break

        # ---------------------------------------------------------------
        # Persist the extracted recipe as a PREVIEW (is_saved=False) so the
        # frontend has a real `id` to navigate to (/recipes/:id). Without a
        # persisted row there is no id, which is why the client showed
        # "Recipe imported, but we couldn't figure out its ID."
        #
        # If this URL/title already exists for the user, reuse that existing
        # recipe's id instead of creating a duplicate row.
        # ---------------------------------------------------------------
        if duplicate_info and duplicate_info.get('existing_recipe', {}).get('id'):
            existing_id = duplicate_info['existing_recipe']['id']
            normalized_recipe['id'] = existing_id
            logger.info(f"Returning existing recipe id={existing_id} for extracted duplicate")
            return jsonify({
                'success': True,
                'recipe': normalized_recipe,
                'recipe_id': existing_id,
                'extractionmethod': extraction_method,
                'ai_enhanced': bool(openai_client or openai_api_key),
                'images_found': len(recipe_images),
                'duplicate_info': duplicate_info,
            })

        try:
            preview = Recipe(
                user_id=request.current_user.id,
                title=sanitize_string(normalized_recipe['title']),
                description=sanitize_string(normalized_recipe.get('description', '')),
                imageurl=sanitize_image_url(normalized_recipe.get('imageurl', '')),
                sourceurl=sanitize_string(normalized_recipe.get('sourceurl', '')),
                preptime=sanitize_integer(normalized_recipe.get('preptime'), 0),
                cooktime=sanitize_integer(normalized_recipe.get('cooktime'), 0),
                totaltime=sanitize_integer(normalized_recipe.get('totaltime'), 0),
                servings=sanitize_integer(normalized_recipe.get('servings', 4), 4),
                originalservings=sanitize_integer(normalized_recipe.get('servings', 4), 4),
                difficulty=sanitize_string(normalized_recipe.get('difficulty', 'Medium')),
                aicomment=sanitize_string(normalized_recipe.get('aicomment', '')),
                hashtags=sanitize_json_field(normalized_recipe.get('hashtags', [])),
                cuisinetype=sanitize_string(normalized_recipe.get('cuisinetype', '')),
                cookingmethod=sanitize_string(normalized_recipe.get('cookingmethod', '')),
                dietarytags=sanitize_json_field(normalized_recipe.get('dietarytags', [])),
                language=normalized_recipe.get('language') or target_lang,
                is_saved=False,  # preview only — user explicitly saves to cookbook later
            )
            db.session.add(preview)
            db.session.flush()  # assign preview.id

            for i, ing_text in enumerate(normalized_recipe.get('ingredients', [])):
                if isinstance(ing_text, str) and ing_text.strip():
                    parsed = clean_ingredient_text(ing_text)
                    db.session.add(Ingredient(
                        recipe_id=preview.id,
                        ingredient=parsed['ingredient'],
                        quantity=parsed['quantity'],
                        unit=parsed['unit'],
                        originalquantity=parsed['quantity'],
                        originalunit=parsed['unit'],
                        order_index=i,
                    ))

            for step_no, instr_text in enumerate(normalized_recipe.get('instructions', []), start=1):
                if isinstance(instr_text, str) and instr_text.strip():
                    db.session.add(Instruction(
                        recipe_id=preview.id,
                        step_number=step_no,
                        instruction=sanitize_string(instr_text),
                    ))

            db.session.commit()
            db.session.refresh(preview)
            normalized_recipe['id'] = preview.id
            normalized_recipe['language'] = preview.language
            logger.info(f"✅ Extracted recipe persisted as preview: {preview.title} (ID: {preview.id})")
        except Exception as persist_err:
            db.session.rollback()
            logger.error(f"Failed to persist extracted recipe preview: {persist_err}")
            logger.error(traceback.format_exc())
            # Fall through and still return the parsed recipe (without id) so
            # the user at least sees the extraction result.

        return jsonify({
            'success': True,
            'recipe': normalized_recipe,
            'recipe_id': normalized_recipe.get('id'),
            'extractionmethod': extraction_method,
            'ai_enhanced': bool(openai_client or openai_api_key),
            'images_found': len(recipe_images),
            'duplicate_info': duplicate_info  # ADD THIS LINE
        })


    except Exception as e:
        error_msg = str(e)
        logger.error(f"Recipe extraction failed: {error_msg}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False, 
            'error': f'Failed to extract recipe: {error_msg}'
        }), 500


# ============================================================================
# DEBUG ENDPOINT - Recipe Extraction Analysis (Fix #6)
# ============================================================================

@app.route('/api/recipes/debug-extract', methods=['POST'])
@require_auth
def debug_extract():
    """Debug endpoint to analyze recipe extraction without saving

    Returns detailed information about:
    - HTTP response details
    - JSON-LD structure analysis
    - HTML structure candidates
    - Results from each extraction method

    Usage:
        POST /api/recipes/debug-extract
        Body: {"url": "https://example.com/recipe"}
    """
    # Gate: require BOTH the explicit opt-in env flag AND Flask debug mode.
    # This double-gate makes it much harder to accidentally expose raw HTML /
    # internal extraction structure in a production deployment.
    _debug_enabled = (
        os.environ.get('ENABLE_DEBUG_ENDPOINTS', '').lower() in ('1', 'true', 'yes')
        and _debug_mode
    )
    if not _debug_enabled:
        return jsonify({'error': 'Debug endpoints are disabled'}), 403
    try:
        data = request.json
        url = data.get('url')

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        # SSRF protection: validate URL before fetching
        _url_valid, _url_err = validate_extraction_url(url)
        if not _url_valid:
            logger.warning(f"Blocked debug extraction URL: {url!r} — {_url_err}")
            return jsonify({'error': f'Invalid or disallowed URL: {_url_err}'}), 400

        logger.info(f"🔍 Debug extraction for: {url}")

        # Use improved headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,it;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Fetch the page (SSRF-hardened: validates + pins IP on each hop)
        try:
            response = safe_requests_get(url, headers=headers, timeout=15)
        except ValueError as _ssrf_err:
            logger.warning(f"Blocked debug-extract URL during fetch: {url!r} — {_ssrf_err}")
            return jsonify({'success': False, 'error': f'Invalid or disallowed URL: {_ssrf_err}'}), 400
        soup = BeautifulSoup(response.content, 'html.parser')

        # Initialize debug info structure
        debug_info = {
            'url': url,
            'timestamp': datetime.now().isoformat(),

            'http_response': {
                'status_code': response.status_code,
                'content_type': response.headers.get('Content-Type', 'unknown'),
                'content_length': len(response.content),
                'encoding': response.encoding
            },

            'page_info': {
                'title': soup.find('title').get_text(strip=True) if soup.find('title') else None,
                'h1_title': soup.find('h1').get_text(strip=True) if soup.find('h1') else None,
                'meta_description': None
            },

            'json_ld_analysis': {
                'script_count': 0,
                'types_found': [],
                'has_recipe': False,
                'scripts_analyzed': []
            },

            'html_structure': {
                'ingredient_candidates': [],
                'instruction_candidates': [],
                'potential_selectors': []
            },

            'extraction_results': {}
        }

        # Extract meta description
        desc_meta = soup.find('meta', attrs={'name': 'description'}) or \
                    soup.find('meta', property='og:description')
        if desc_meta:
            debug_info['page_info']['meta_description'] = desc_meta.get('content', '')[:200]

        # Analyze JSON-LD scripts
        json_scripts = soup.find_all('script', type='application/ld+json')
        debug_info['json_ld_analysis']['script_count'] = len(json_scripts)

        for idx, script in enumerate(json_scripts[:5]):  # Analyze first 5 scripts
            script_info = {
                'index': idx,
                'has_content': bool(script.string),
                'content_length': len(script.string) if script.string else 0,
                'types': [],
                'is_recipe': False
            }

            try:
                if script.string:
                    data_obj = json.loads(script.string)

                    # Handle different structures
                    if isinstance(data_obj, dict):
                        type_val = data_obj.get('@type')
                        script_info['types'].append(type_val)
                        debug_info['json_ld_analysis']['types_found'].append(type_val)

                        # Check for Recipe
                        if is_recipe_type(type_val):
                            script_info['is_recipe'] = True
                            debug_info['json_ld_analysis']['has_recipe'] = True
                            script_info['ingredient_count'] = len(data_obj.get('recipeIngredient', []))
                            script_info['instruction_count'] = len(data_obj.get('recipeInstructions', []))

                        # Check for @graph
                        if '@graph' in data_obj:
                            script_info['has_graph'] = True
                            script_info['graph_items'] = len(data_obj['@graph'])
                            for item in data_obj['@graph']:
                                if isinstance(item, dict):
                                    item_type = item.get('@type')
                                    script_info['types'].append(f"@graph:{item_type}")
                                    if is_recipe_type(item_type):
                                        script_info['is_recipe'] = True
                                        debug_info['json_ld_analysis']['has_recipe'] = True

                    elif isinstance(data_obj, list):
                        script_info['is_list'] = True
                        script_info['list_length'] = len(data_obj)
                        for item in data_obj:
                            if isinstance(item, dict):
                                item_type = item.get('@type')
                                script_info['types'].append(item_type)
                                debug_info['json_ld_analysis']['types_found'].append(item_type)
                                if is_recipe_type(item_type):
                                    script_info['is_recipe'] = True
                                    debug_info['json_ld_analysis']['has_recipe'] = True

            except json.JSONDecodeError as e:
                script_info['error'] = f"JSON parse error: {str(e)[:100]}"
            except Exception as e:
                script_info['error'] = f"Error: {str(e)[:100]}"

            debug_info['json_ld_analysis']['scripts_analyzed'].append(script_info)

        # Find potential ingredient containers
        ing_patterns = [
            'ingredient', 'recipe-ingredient', 'wprm-recipe-ingredient',
            'ingredients', 'ingredient-list', 'ingredients-list'
        ]

        for pattern in ing_patterns:
            elements = soup.find_all(class_=re.compile(pattern, re.IGNORECASE))
            if elements:
                candidate = {
                    'pattern': pattern,
                    'match_type': 'class',
                    'count': len(elements),
                    'sample_text': elements.get_text(strip=True)[:100] if elements else None,
                    # Only expose raw HTML when debug mode is on (the endpoint
                    # is already gated, but keep raw internals strictly opt-in).
                    'sample_html': (str(elements)[:300] if (elements and _debug_mode) else None),
                    'tag_name': elements.name if elements else None
                }
                debug_info['html_structure']['ingredient_candidates'].append(candidate)

        # Check for data attributes
        data_ing_elements = soup.find_all(attrs={'data-ingredient': True})
        if data_ing_elements:
            debug_info['html_structure']['ingredient_candidates'].append({
                'pattern': 'data-ingredient',
                'match_type': 'data-attribute',
                'count': len(data_ing_elements),
                'sample_text': data_ing_elements.get_text(strip=True)[:100]
            })

        # Find potential instruction containers
        inst_patterns = [
            'instruction', 'recipe-instruction', 'wprm-recipe-instruction',
            'step', 'direction', 'recipe-step', 'preparation'
        ]

        for pattern in inst_patterns:
            elements = soup.find_all(class_=re.compile(pattern, re.IGNORECASE))
            if elements:
                candidate = {
                    'pattern': pattern,
                    'match_type': 'class',
                    'count': len(elements),
                    'sample_text': elements.get_text(strip=True)[:100] if elements else None,
                    'tag_name': elements.name if elements else None
                }
                debug_info['html_structure']['instruction_candidates'].append(candidate)

        # Generate potential CSS selectors
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        if debug_info['html_structure']['ingredient_candidates']:
            top_ing = debug_info['html_structure']['ingredient_candidates']
            if top_ing['match_type'] == 'class':
                debug_info['html_structure']['potential_selectors'].append({
                    'type': 'ingredients',
                    'selector': f".{top_ing['pattern']}",
                    'confidence': 'high' if top_ing['count'] > 3 else 'medium'
                })

        if debug_info['html_structure']['instruction_candidates']:
            top_inst = debug_info['html_structure']['instruction_candidates']
            if top_inst['match_type'] == 'class':
                debug_info['html_structure']['potential_selectors'].append({
                    'type': 'instructions',
                    'selector': f".{top_inst['pattern']}",
                    'confidence': 'high' if top_inst['count'] > 2 else 'medium'
                })

        # Test each extraction method
        logger.info("Testing extraction methods...")

        # Method 1: JSON-LD
        try:
            json_ld_result = extract_json_ld(soup)
            debug_info['extraction_results']['json_ld'] = {
                'success': bool(json_ld_result),
                'method': 'JSON-LD Schema',
                'data': {}
            }
            if json_ld_result:
                debug_info['extraction_results']['json_ld']['data'] = {
                    'name': json_ld_result.get('name', 'N/A'),
                    'ingredient_count': len(json_ld_result.get('recipeIngredient', [])),
                    'instruction_count': len(json_ld_result.get('recipeInstructions', [])),
                    'has_image': bool(json_ld_result.get('image')),
                    'has_cookTime': bool(json_ld_result.get('cookTime'))
                }
        except Exception as e:
            debug_info['extraction_results']['json_ld'] = {
                'success': False,
                'error': str(e)[:200]
            }

        # Method 2: Site-specific rules
        try:
            site_rules_result = extract_with_site_rules(soup, url)
            debug_info['extraction_results']['site_rules'] = {
                'success': bool(site_rules_result),
                'method': 'Site-Specific Rules',
                'has_rules_for_domain': domain in SITE_RULES,
                'data': {}
            }
            if site_rules_result:
                debug_info['extraction_results']['site_rules']['data'] = {
                    'name': site_rules_result.get('name', 'N/A'),
                    'ingredient_count': len(site_rules_result.get('recipeIngredient', [])),
                    'instruction_count': len(site_rules_result.get('recipeInstructions', []))
                }
        except Exception as e:
            debug_info['extraction_results']['site_rules'] = {
                'success': False,
                'error': str(e)[:200]
            }

        # Method 3: Microdata
        try:
            microdata_result = extract_microdata(soup)
            debug_info['extraction_results']['microdata'] = {
                'success': bool(microdata_result),
                'method': 'Microdata',
                'data': {}
            }
            if microdata_result:
                debug_info['extraction_results']['microdata']['data'] = {
                    'name': microdata_result.get('name', 'N/A'),
                    'ingredient_count': len(microdata_result.get('recipeIngredient', [])),
                    'instruction_count': len(microdata_result.get('recipeInstructions', []))
                }
        except Exception as e:
            debug_info['extraction_results']['microdata'] = {
                'success': False,
                'error': str(e)[:200]
            }

        # Method 4: Text parsing
        try:
            text_result = extract_recipe_from_text(soup)
            debug_info['extraction_results']['text_parsing'] = {
                'success': bool(text_result),
                'method': 'Text Parsing (Fallback)',
                'data': {}
            }
            if text_result:
                debug_info['extraction_results']['text_parsing']['data'] = {
                    'name': text_result.get('name', 'N/A'),
                    'ingredient_count': len(text_result.get('recipeIngredient', [])),
                    'instruction_count': len(text_result.get('recipeInstructions', []))
                }
        except Exception as e:
            debug_info['extraction_results']['text_parsing'] = {
                'success': False,
                'error': str(e)[:200]
            }

        # Determine best method
        successful_methods = [
            method for method, result in debug_info['extraction_results'].items()
            if result.get('success', False)
        ]

        debug_info['recommendation'] = {
            'successful_methods': successful_methods,
            'best_method': successful_methods[0] if successful_methods else None,
            'needs_site_rules': len(successful_methods) == 0 and domain not in SITE_RULES,
            'suggestion': ''
        }

        if not successful_methods:
            if domain not in SITE_RULES:
                debug_info['recommendation']['suggestion'] = f"Add site-specific rules for {domain}"
            else:
                debug_info['recommendation'][
                    'suggestion'] = "Site may require JavaScript rendering or has strong anti-scraping"
        else:
            debug_info['recommendation']['suggestion'] = f"Use {successful_methods} method"

        logger.info(f"✅ Debug analysis complete. Successful methods: {successful_methods}")

        return jsonify(debug_info)

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error in debug endpoint: {e}")
        return jsonify({
            'error': f'Failed to fetch URL: {str(e)}',
            'error_type': 'request_error'
        }), 500

    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'error': str(e),
            'error_type': 'server_error'
        }), 500


# ============================================================================
# END DEBUG ENDPOINT
# ============================================================================
@app.route('/api/recipes/ai-stats', methods=['GET'])
@require_auth
def get_ai_stats():
    """Get AI extraction usage statistics and costs"""
    try:
        stats = {
            'ai_extraction_enabled': USE_AI_EXTRACTION,
            'model': AI_MODEL,
            'session_stats': {
                'total_extractions': ai_extraction_count,
                'total_cost_usd': round(ai_total_cost, 6),
                'total_tokens': ai_total_tokens,
                'avg_cost_per_extraction': round(ai_total_cost / ai_extraction_count,
                                                 6) if ai_extraction_count > 0 else 0,
                'avg_tokens_per_extraction': round(ai_total_tokens / ai_extraction_count,
                                                   2) if ai_extraction_count > 0 else 0
            },
            'cost_estimates': {
                'per_100_recipes': round(ai_total_cost / ai_extraction_count * 100,
                                         2) if ai_extraction_count > 0 else 0.05,
                'per_1000_recipes': round(ai_total_cost / ai_extraction_count * 1000,
                                          2) if ai_extraction_count > 0 else 0.50,
                'per_10000_recipes': round(ai_total_cost / ai_extraction_count * 10000,
                                           2) if ai_extraction_count > 0 else 5.00
            },
            'configuration': {
                'max_tokens': AI_MAX_TOKENS,
                'temperature': AI_TEMPERATURE,
                'cost_tracking': AI_COST_TRACKING
            }
        }

        return jsonify(stats)

    except Exception as e:
        logger.error(f"AI stats endpoint error: {e}")
        return jsonify({'error': 'Failed to retrieve AI statistics'}), 500


@app.route('/api/recipes', methods=['GET', 'POST'])
@require_auth
def recipes():
    """Get all recipes or save a new recipe"""
    if request.method == 'GET':
        try:
            page, per_page = _parse_pagination(default_per_page=20, max_per_page=100)
            category = (request.args.get('category') or '').strip() or None
            search   = (request.args.get('q') or '').strip() or None
            saved_only = request.args.get('saved', '').lower() in ('1', 'true', 'yes')

            # Filter by current user only.
            query = Recipe.query.filter_by(user_id=request.current_user.id)
            if category:
                query = query.join(RecipeCategory).join(Category).filter(Category.name == category)
            if search:
                # Case-insensitive title/description match.
                like = f"%{search}%"
                query = query.filter(db.or_(Recipe.title.ilike(like),
                                            Recipe.description.ilike(like)))
            if saved_only:
                query = query.filter(Recipe.is_saved.is_(True))
            recipes = query.order_by(Recipe.created_at.desc()).paginate(
                page=page, per_page=per_page, error_out=False
            )

            recipe_list = [r.to_dict(include_relationships=True) for r in recipes.items]

            return jsonify({
                'success': True,
                'recipes': recipe_list,
                'pagination': _pagination_dict(recipes),
            })

        except Exception as e:
            logger.error(f"Get recipes failed: {e}")
            return jsonify({'success': False, 'error': 'Failed to retrieve recipes'}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            if not data or not data.get('title'):
                return jsonify({'success': False, 'error': 'Recipe title is required'}), 400

            logger.info(f"Saving recipe: {data.get('title')}")
            # DUPLICATE DETECTION - Check if recipe already exists in SAVED recipes only
            recipe_title = sanitize_string(data.get('title', ''))
            source_url = sanitize_string(data.get('sourceurl', ''))

            # Normalize for comparison
            normalized_title = normalize_title(recipe_title)
            normalized_url = normalize_url(source_url) if source_url else None

            # Single scan of the user's recipes, matching by normalized title
            # OR normalized source URL. (Normalization is a Python function, so
            # it can't be pushed into SQL; but we only load the rows ONCE here
            # instead of the previous two identical full-table scans.)
            existing_by_title = None
            existing_by_url = None
            if normalized_title or normalized_url:
                user_recipes = Recipe.query.filter(
                    Recipe.user_id == request.current_user.id
                ).all()

                for recipe in user_recipes:
                    if (existing_by_title is None and normalized_title
                            and normalize_title(recipe.title) == normalized_title):
                        existing_by_title = recipe
                    if (existing_by_url is None and normalized_url
                            and recipe.sourceurl
                            and normalize_url(recipe.sourceurl) == normalized_url):
                        existing_by_url = recipe
                    if existing_by_title and existing_by_url:
                        break

            # If we found a duplicate in saved recipes
            if existing_by_title or existing_by_url:
                duplicate_recipe = existing_by_title or existing_by_url
                logger.info(
                    f"Duplicate recipe detected in saved collection: {duplicate_recipe.title} (ID: {duplicate_recipe.id})")

                return jsonify({
                    'success': False,
                    'error': 'duplicate',
                    'message': 'You already have this recipe in your cookbook',
                    'existing_recipe': {
                        'id': duplicate_recipe.id,
                        'title': duplicate_recipe.title,
                        'created_at': duplicate_recipe.created_at.isoformat() if duplicate_recipe.created_at else None
                    }
                }), 409

            # Create recipe with proper data sanitization
            recipe = Recipe(
                user_id=request.current_user.id,  # ADD THIS LINE
                title=sanitize_string(data.get('title')),
                description=sanitize_string(data.get('description', '')),
                imageurl=sanitize_image_url(data.get('imageurl', '')),
                sourceurl=sanitize_string(data.get('sourceurl', '')),
                preptime=sanitize_integer(data.get('preptime'), 0),
                cooktime=sanitize_integer(data.get('cooktime'), 0),
                totaltime=sanitize_integer(data.get('totaltime'), 0),
                servings=sanitize_integer(data.get('servings', 4), 4),
                originalservings=sanitize_integer(data.get('originalservings', data.get('servings', 4)), 4),
                difficulty=sanitize_string(data.get('difficulty', 'Medium')),
                aicomment=sanitize_string(data.get('aicomment', '')),
                nutritiondata=sanitize_json_field(data.get('nutritiondata', [])),
                nutritionperserving=sanitize_json_field(data.get('nutritionperserving', [])),
                hashtags=sanitize_json_field(data.get('hashtags', [])),
                cuisinetype=sanitize_string(data.get('cuisinetype', '')),
                cookingmethod=sanitize_string(data.get('cookingmethod', '')),
                dietarytags=sanitize_json_field(data.get('dietarytags', [])),
                literaryquote=sanitize_string(data.get('literaryquote', '')),
                quoteauthor=sanitize_string(data.get('quoteauthor', '')),
                quotesource=sanitize_string(data.get('quotesource', '')),
                is_saved=data.get('is_saved', True),
            )

            db.session.add(recipe)
            db.session.flush()  # Get the recipe ID

            # Add ingredients
            for i, ingredient_data in enumerate(data.get('ingredients', [])):
                if isinstance(ingredient_data, str):
                    parsed = clean_ingredient_text(ingredient_data)
                    ingredient_text = parsed['ingredient']
                    quantity = parsed['quantity']
                    unit = parsed['unit']
                else:
                    ingredient_text = sanitize_string(ingredient_data.get('ingredient', ''))
                    quantity = sanitize_string(ingredient_data.get('quantity', ''))
                    unit = sanitize_string(ingredient_data.get('unit', ''))

                if ingredient_text:
                    ingredient = Ingredient(
                        recipe_id=recipe.id,
                        ingredient=ingredient_text,
                        quantity=quantity,
                        unit=unit,
                        preparation=sanitize_string(ingredient_data.get('preparation', '') if isinstance(ingredient_data, dict) else ''),
                        originalquantity=quantity,
                        originalunit=unit,
                        order_index=i
                    )
                    db.session.add(ingredient)

            # Add instructions
            for instruction_data in data.get('instructions', []):
                if isinstance(instruction_data, str):
                    instruction_text = instruction_data
                    step_number = len(recipe.instructions) + 1
                else:
                    instruction_text = sanitize_string(instruction_data.get('instruction', ''))
                    step_number = sanitize_integer(instruction_data.get('step_number', len(recipe.instructions) + 1), 1)

                if instruction_text:
                    instruction = Instruction(
                        recipe_id=recipe.id,
                        step_number=step_number,
                        instruction=instruction_text,
                        time_estimate=sanitize_integer(instruction_data.get('time_estimate') if isinstance(instruction_data, dict) else None),
                        temperature=sanitize_string(instruction_data.get('temperature') if isinstance(instruction_data, dict) else None)
                    )
                    db.session.add(instruction)


            # Handle categories - MOVED OUTSIDE THE LOOPS
            category_ids = data.get('category_ids', [])
            if category_ids:
                logger.info(f"📁 Assigning {len(category_ids)} categories to recipe")
                for category_id in category_ids:
                    category = Category.query.get(category_id)
                    if category:
                        recipe_category = RecipeCategory(
                            recipe_id=recipe.id,
                            category_id=category_id
                        )
                        db.session.add(recipe_category)
                        logger.info(f"   ✓ Assigned category: {category.name}")
            else:
                logger.info(f"📁 No categories provided for recipe")

            db.session.commit()

            # Refresh the recipe to reload relationships after commit
            db.session.refresh(recipe)

            logger.info(f"Recipe saved successfully: {recipe.title} (ID: {recipe.id})")

            return jsonify({
                'success': True,
                'recipe_id': recipe.id,
                'recipe': recipe.to_dict(),
                'message': f"Recipe '{recipe.title}' saved successfully"
            })

        except Exception as e:
            db.session.rollback()
            logger.error(f"Save recipe failed: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': 'Failed to save recipe'}), 500

@app.route('/api/recipes/<int:recipe_id>', methods=['GET', 'PUT', 'DELETE'])
@require_auth
def recipe_detail(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)

    # Check ownership
    if recipe.user_id != request.current_user.id:
        return jsonify({'error': 'Access denied'}), 403

    if request.method == 'GET':
        payload = recipe.to_dict()
        payload['pantry_match'] = compute_pantry_match(recipe)
        return jsonify({
            'success': True,
            'recipe': payload
        })

    elif request.method == 'PUT':  # ADD THIS ENTIRE BLOCK
        try:
            data = request.json

            # Update is_saved status and other fields if provided
            if 'is_saved' in data:
                recipe.is_saved = data.get('is_saved')

            # Update other fields if provided
            if 'title' in data:
                recipe.title = sanitize_string(data.get('title'))
            if 'description' in data:
                recipe.description = sanitize_string(data.get('description', ''))
            if 'servings' in data:
                recipe.servings = sanitize_integer(data.get('servings'), recipe.servings)

            # Add more fields as needed for your use case

            recipe.updated_at = utcnow()

            # Handle categories if provided
            category_ids = data.get('category_ids', [])
            if category_ids:
                # Clear existing categories to avoid duplicates
                RecipeCategory.query.filter_by(recipe_id=recipe.id).delete()
                logger.info(f"📁 Assigning {len(category_ids)} categories to recipe")
                for category_id in category_ids:
                    category = Category.query.get(category_id)
                    if category:
                        recipe_category = RecipeCategory(
                            recipe_id=recipe.id,
                            category_id=category_id
                        )
                        db.session.add(recipe_category)
                        logger.info(f"   ✓ Assigned category: {category.name}")
            db.session.commit()

            logger.info(f"Recipe updated: {recipe.title} (ID: {recipe.id})")
            return jsonify({
                'success': True,
                'recipe': recipe.to_dict(),
                'message': f"Recipe '{recipe.title}' updated successfully"
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update recipe {recipe_id}: {str(e)}")
            return jsonify({'success': False, 'error': 'Failed to update recipe'}), 500

    elif request.method == 'DELETE':
        try:
            db.session.delete(recipe)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Recipe deleted successfully'
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete recipe {recipe_id}: {str(e)}")
            return jsonify({'success': False, 'error': 'Failed to delete recipe'}), 500


@app.route('/api/recipes/<int:recipe_id>/scale', methods=['POST'])
@require_auth
def scale_recipe_endpoint(recipe_id):

    try:
        data = request.get_json() or {}
        new_servings = int(data.get('servings', 4))
        recipe = Recipe.query.get_or_404(recipe_id)
        # Check ownership
        if recipe.user_id != request.current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        recipe_dict = recipe.to_dict()
        scaled = scale_recipe(recipe_dict, new_servings)
        return jsonify({'success': True, 'recipe': scaled})
    except Exception as e:
        logger.error(f"Recipe scaling error: {e}")
        return jsonify({'success': False, 'error': 'Failed to scale recipe'}), 500


@app.route('/api/recipes/<int:recipe_id>/translate', methods=['POST'])
@require_auth
def translate_recipe_endpoint(recipe_id):
    """Translate a saved recipe's text into the requested language and persist it.

    Body: { "lang": "en" }  (one of ru/en/it/es/fr/de)
    Re-writes title/description and rebuilds the ingredient/instruction rows
    from the translated strings. Quantities/units are preserved by the LLM and
    re-parsed with clean_ingredient_text. Falls back gracefully (returns the
    recipe unchanged) when no OpenAI key is configured.
    """
    data = request.get_json() or {}
    target_lang = (data.get('lang') or '').strip().lower()
    if target_lang not in LANG_NAMES:
        return jsonify({'success': False, 'error': 'Unsupported language'}), 400

    recipe = Recipe.query.get(recipe_id)
    if recipe is None:
        return jsonify({'success': False, 'error': 'Recipe not found'}), 404
    if recipe.user_id != request.current_user.id:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    # Short-circuit: recipe is already stored in the target language. Avoid a
    # wasted LLM call (and tokens) when there is nothing to translate.
    if (recipe.language or '').strip().lower() == target_lang:
        logger.info(f"Recipe {recipe.id} already in {target_lang}; skipping translation")
        return jsonify({
            'success': True,
            'translated': False,
            'already_in_language': True,
            'recipe': recipe.to_dict(),
        })

    try:

        # Build a plain dict (string arrays for ingredients/instructions).
        recipe_dict = recipe.to_dict(include_relationships=True)
        translated = translate_recipe_fields(recipe_dict, target_lang)

        # If nothing changed (no key / failure / already in language), report it
        # but don't error out — the client just re-renders the same recipe.
        if translated.get('language') != target_lang:
            return jsonify({
                'success': True,
                'translated': False,
                'recipe': recipe.to_dict(),
            })

        # Persist the translated text.
        if isinstance(translated.get('title'), str) and translated['title'].strip():
            recipe.title = sanitize_string(translated['title'])
        if isinstance(translated.get('description'), str):
            recipe.description = sanitize_string(translated['description'])
        recipe.language = target_lang

        # Rebuild ingredients.
        new_ingredients = translated.get('ingredients')
        if isinstance(new_ingredients, list) and new_ingredients:
            Ingredient.query.filter_by(recipe_id=recipe.id).delete()
            for i, ing_text in enumerate(new_ingredients):
                if isinstance(ing_text, str) and ing_text.strip():
                    parsed = clean_ingredient_text(ing_text)
                    db.session.add(Ingredient(
                        recipe_id=recipe.id,
                        ingredient=parsed['ingredient'],
                        quantity=parsed['quantity'],
                        unit=parsed['unit'],
                        originalquantity=parsed['quantity'],
                        originalunit=parsed['unit'],
                        order_index=i,
                    ))

        # Rebuild instructions.
        new_instructions = translated.get('instructions')
        if isinstance(new_instructions, list) and new_instructions:
            Instruction.query.filter_by(recipe_id=recipe.id).delete()
            for step_no, instr_text in enumerate(new_instructions, start=1):
                if isinstance(instr_text, str) and instr_text.strip():
                    db.session.add(Instruction(
                        recipe_id=recipe.id,
                        step_number=step_no,
                        instruction=sanitize_string(instr_text),
                    ))

        db.session.commit()
        db.session.refresh(recipe)
        logger.info(f"✅ Recipe {recipe.id} translated to {target_lang}")
        return jsonify({
            'success': True,
            'translated': True,
            'recipe': recipe.to_dict(),
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Recipe translation endpoint error: {e}")
        return jsonify({'success': False, 'error': 'Failed to translate recipe'}), 500


@app.route('/api/convert-units', methods=['POST'])
@require_auth
def convert_units_api():
    """Convert ingredient units between metric and imperial"""
    try:
        data = request.json
        ingredients = data.get('ingredients', [])
        from_system = data.get('from_system', 'metric')
        to_system = data.get('to_system', 'imperial')

        if from_system == to_system:
            return jsonify({'success': True, 'converted_ingredients': ingredients})

        converted_ingredients = convert_units(ingredients, from_system, to_system)

        return jsonify({
            'success': True,
            'converted_ingredients': converted_ingredients
        })

    except Exception as e:
        logger.error(f"Unit conversion failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to convert units'}), 500


@app.route('/api/scale-data', methods=['POST'])
@require_auth
def scale_recipe_data():
    """Scale recipe data without saving to database - Client-side scaling"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        recipe_data = data.get('recipe')
        new_servings = int(data.get('servings', 4)) if data.get('servings') else 4

        if not recipe_data:
            return jsonify({'success': False, 'error': 'Recipe data required'}), 400

        logger.info(f"Scaling recipe data to {new_servings} servings")

        # Use the existing scale_recipe function (which has your fraction parsing)
        scaled_recipe = scale_recipe(recipe_data, new_servings)

        return jsonify({
            'success': True,
            'recipe': scaled_recipe
        })

    except Exception as e:
        logger.error(f"Recipe data scaling error: {e}")
        return jsonify({'success': False, 'error': 'Failed to scale recipe data'}), 500


@app.route('/api/categories', methods=['GET'])
@require_auth
def get_categories():
    """Get global categories plus the current user's categories, with user-scoped counts"""
    try:
        user_id = request.current_user.id

        # Visible categories: global (user_id IS NULL) + current user's own
        visible_filter = db.or_(Category.user_id == None, Category.user_id == user_id)

        # Fetch visible categories with recipe counts scoped to this user's saved recipes
        categories = db.session.query(
            Category.id,
            Category.name,
            Category.description,
            Category.icon,
            Category.user_id,
            db.func.count(RecipeCategory.recipe_id).label('count')
        ).filter(visible_filter).outerjoin(
            RecipeCategory,
            db.and_(
                RecipeCategory.category_id == Category.id,
                RecipeCategory.recipe_id.in_(
                    db.session.query(Recipe.id).filter_by(user_id=user_id, is_saved=True)
                )
            )
        ).group_by(Category.id).all()

        category_list = []

        # "All Recipes" count is scoped to this user
        total_recipes = db.session.query(Recipe).filter_by(user_id=user_id, is_saved=True).count()
        category_list.append({
            'id': 0,
            'name': 'All Recipes',
            'description': 'All recipes in your collection',
            'icon': '\U0001f4da',
            'count': total_recipes,
            'is_global': True
        })

        for category in categories:
            category_list.append({
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'icon': category.icon,
                'count': category.count,
                'is_global': category.user_id is None   # clients can use this for UI hints
            })

        return jsonify({
            'success': True,
            'categories': category_list
        })

    except Exception as e:
        logger.error(f"Get categories failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve categories'}), 500


@app.route('/api/categories', methods=['POST'])
@require_auth
def create_category():
    """Create a new category owned by the current user"""
    try:
        data = request.json
        name = data.get('name', '').strip()
        user_id = request.current_user.id

        if not name:
            return jsonify({'success': False, 'error': 'Category name is required'}), 400

        # Duplicate check scoped to (name, user_id): the same name is allowed
        # for different users, but a user cannot have two categories with the
        # same name. Also block creating a name that clashes with a global
        # category (user_id IS NULL) so the shared namespace stays unambiguous.
        existing = Category.query.filter(
            Category.name == name,
            db.or_(Category.user_id == user_id, Category.user_id == None)
        ).first()
        if existing:
            return jsonify({'success': False, 'error': 'A category with that name already exists'}), 409

        category = Category(
            name=name,
            description=data.get('description', '').strip(),
            icon=data.get('icon', '📁'),
            user_id=user_id   # owned by the creating user
        )

        db.session.add(category)
        db.session.commit()

        logger.info(f"User {user_id} created category: {name}")
        return jsonify({
            'success': True,
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'icon': category.icon,
                'is_global': False
            }
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Create category failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to create category'}), 500


@app.route('/api/categories/<int:category_id>', methods=['PUT'])
@require_auth
def update_category(category_id):
    """Update a user-owned category. Global (default) categories are not editable."""
    try:
        category = Category.query.get_or_404(category_id)
        user_id = request.current_user.id

        # Global categories (user_id IS NULL) are system defaults — not editable
        if category.user_id is None:
            return jsonify({'success': False, 'error': 'Built-in categories cannot be modified'}), 403

        # Only the owner may edit their own category
        if category.user_id != user_id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        data = request.json

        if 'name' in data:
            name = data['name'].strip()
            if name:
                # Duplicate check: no clash within (name, user_id) space or global space
                existing = Category.query.filter(
                    Category.name == name,
                    Category.id != category_id,
                    db.or_(Category.user_id == user_id, Category.user_id == None)
                ).first()
                if existing:
                    return jsonify({'success': False, 'error': 'A category with that name already exists'}), 409
                category.name = name

        if 'description' in data:
            category.description = data['description'].strip()

        if 'icon' in data:
            category.icon = data['icon']

        db.session.commit()

        logger.info(f"User {user_id} updated category: {category.name}")
        return jsonify({
            'success': True,
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'icon': category.icon,
                'is_global': False
            }
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Update category failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to update category'}), 500


@app.route('/api/categories/<int:category_id>', methods=['DELETE'])
@require_auth
def delete_category(category_id):
    """Delete a user-owned category. Global (default) categories are protected."""
    try:
        category = Category.query.get_or_404(category_id)
        user_id = request.current_user.id

        # Global categories (user_id IS NULL) are system defaults — not deletable
        if category.user_id is None:
            return jsonify({'success': False, 'error': 'Built-in categories cannot be deleted'}), 403

        # Only the owner may delete their own category
        if category.user_id != user_id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403

        # Check if category is in use by this user's recipes
        recipes_count = db.session.query(RecipeCategory).join(Recipe).filter(
            RecipeCategory.category_id == category_id,
            Recipe.user_id == user_id
        ).count()

        if recipes_count > 0:
            return jsonify({
                'success': False,
                'error': f'Cannot delete category: {recipes_count} of your recipe(s) use it.'
            }), 400

        db.session.delete(category)
        db.session.commit()

        logger.info(f"User {user_id} deleted category: {category.name}")
        return jsonify({'success': True, 'message': 'Category deleted successfully'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Delete category failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to delete category'}), 500


@app.route('/api/recipes/<int:recipe_id>/categories', methods=['POST', 'PUT'])
@require_auth
def update_recipe_categories(recipe_id):
    """Update categories for a recipe"""
    try:
        # Get recipe and check ownership
        recipe = Recipe.query.get_or_404(recipe_id)

        # Check ownership
        if recipe.user_id != request.current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        data = request.json
        category_ids = data.get('category_ids', [])

        # Remove existing categories
        RecipeCategory.query.filter_by(recipe_id=recipe_id).delete()

        # Add new categories — only allow global categories or ones owned by this user
        current_user_id = request.current_user.id
        for category_id in category_ids:
            category = Category.query.get(category_id)
            # Skip categories that don't exist or belong to another user
            if not category:
                continue
            if category.user_id is not None and category.user_id != current_user_id:
                logger.warning(
                    f"User {current_user_id} attempted to assign category {category_id} "
                    f"owned by user {category.user_id} — skipped"
                )
                continue
            recipe_category = RecipeCategory(
                recipe_id=recipe_id,
                category_id=category_id
            )
            db.session.add(recipe_category)

        db.session.commit()

        logger.info(f"Updated categories for recipe: {recipe.title}")
        return jsonify({
            'success': True,
            'message': 'Recipe categories updated',
            'categories': [cat.category.name for cat in recipe.categories]
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Update recipe categories failed: {e}")
        return jsonify({'success': False, 'error': 'Failed to update recipe categories'}), 500


# ============================================================================
# NUTRITION (USDA FoodData Central + AI fallback)
# ============================================================================

USDA_API_KEY = os.environ.get('USDA_API_KEY', 'DEMO_KEY')  # DEMO_KEY = 30 req/hr; obtain a real key at https://fdc.nal.usda.gov/api-key-signup.html
USDA_SEARCH_URL = 'https://api.nal.usda.gov/fdc/v1/foods/search'
USDA_FOOD_URL = 'https://api.nal.usda.gov/fdc/v1/food/{fdc_id}'

# Map USDA nutrient IDs to our normalised keys.
# All values are reported per 100 g of the food (or per 100 ml for liquids).
_USDA_NUTRIENT_MAP = {
    1008: ('calories', 'kcal'),
    1003: ('protein',  'g'),
    1004: ('fat',      'g'),
    1005: ('carbs',    'g'),
    1079: ('fiber',    'g'),
    2000: ('sugar',    'g'),
    1093: ('sodium',   'mg'),
}

# Approximate gram mass for one piece of common whole foods (used when the
# ingredient has no weight unit, e.g. "2 avocados").
_PIECE_WEIGHTS_G = {
    'avocado': 200, 'avocados': 200,
    'apple': 180, 'apples': 180,
    'banana': 120, 'bananas': 120,
    'lime': 67, 'limes': 67,
    'lemon': 84, 'lemons': 84,
    'egg': 50, 'eggs': 50,
    'onion': 150, 'onions': 150,
    'red onion': 150, 'red onions': 150,
    'white onion': 150, 'spring onion': 15, 'spring onions': 15,
    'shallot': 40, 'shallots': 40,
    'tomato': 123, 'tomatoes': 123,
    'cherry tomato': 17, 'cherry tomatoes': 17,
    'potato': 213, 'potatoes': 213,
    'sweet potato': 130, 'sweet potatoes': 130,
    'carrot': 61, 'carrots': 61,
    'garlic clove': 3, 'garlic cloves': 3, 'clove': 3, 'cloves': 3,
    'garlic': 5,
    'orange': 131, 'oranges': 131,
    # Peppers & other common veg (previously missing -> ingredients were dropped)
    'pepper': 120, 'peppers': 120,
    'red pepper': 120, 'red peppers': 120,
    'green pepper': 120, 'green peppers': 120,
    'yellow pepper': 120, 'yellow peppers': 120,
    'bell pepper': 120, 'bell peppers': 120,
    'chilli': 15, 'chillies': 15, 'chili': 15, 'chilies': 15,
    'chilli pepper': 15, 'chili pepper': 15,
    'courgette': 196, 'courgettes': 196, 'zucchini': 196,
    'aubergine': 250, 'aubergines': 250, 'eggplant': 250,
    'cucumber': 300, 'cucumbers': 300,
    'mushroom': 18, 'mushrooms': 18,
    'leek': 90, 'leeks': 90,
    'celery stalk': 40, 'celery stalks': 40, 'celery stick': 40, 'celery sticks': 40,
}

# Volume conversions to ml (for ingredients given by volume).
_VOLUME_TO_ML = {
    'tsp': 4.93, 'teaspoon': 4.93, 'teaspoons': 4.93,
    'tbsp': 14.79, 'tablespoon': 14.79, 'tablespoons': 14.79,
    'cup': 236.59, 'cups': 236.59,
    'pint': 473.18, 'pints': 473.18,
    'quart': 946.35, 'quarts': 946.35,
    'gallon': 3785.41, 'gallons': 3785.41,
    'fl oz': 29.57,
    'ml': 1, 'milliliter': 1, 'milliliters': 1,
    'l': 1000, 'liter': 1000, 'liters': 1000,
    'dl': 100, 'cl': 10,
}

# Approximate density (g per ml) for common ingredients. Anything missing
# defaults to water density (1.0 g/ml), good enough for liquid-ish foods.
_INGREDIENT_DENSITY = {
    'flour': 0.53,
    'sugar': 0.85, 'brown sugar': 0.93,
    'salt': 1.20,
    'butter': 0.96,
    'olive oil': 0.92, 'oil': 0.92, 'vegetable oil': 0.92,
    'milk': 1.03,
    'water': 1.00,
    'rice': 0.78, 'oats': 0.41,
}

_WEIGHT_TO_G = {
    'g': 1, 'gram': 1, 'grams': 1, 'gr': 1,
    'kg': 1000, 'kilogram': 1000, 'kilograms': 1000,
    'mg': 0.001,
    'oz': 28.35, 'ounce': 28.35, 'ounces': 28.35,
    'lb': 453.59, 'lbs': 453.59, 'pound': 453.59, 'pounds': 453.59,
}

# ── Shopping-list unit reconciliation ─────────────────────────────────────────
# These tables let the SHOPPING LIST merge two lines of the same ingredient that
# were written in different units (e.g. "2 cup flour" + "100 g flour"). They are
# used ONLY for the aggregated shopping list. They never mutate a recipe's stored
# Ingredient rows, so cooking/scaling still use the original recipe quantities.
#
# Each unit belongs to a "dimension": 'mass', 'volume', or 'count'. We only ever
# merge units that share a dimension. Cross-dimension merges (e.g. grams of flour
# vs cups of flour) are attempted ONLY when we have a trusted density for that
# specific ingredient; otherwise the two lines are kept separate (safe fallback).

# Canonical display unit + step ladder per dimension, largest-first. When the
# merged total in the base unit (g or ml) is large enough, we promote it to a
# friendlier unit for display (e.g. 1500 g -> "1.5 kg").
_MASS_DISPLAY_LADDER = [('kg', 1000.0), ('g', 1.0)]
_VOLUME_DISPLAY_LADDER = [('l', 1000.0), ('ml', 1.0)]


def _unit_dimension(unit: str) -> Optional[str]:
    """Classify a raw unit string into 'mass', 'volume', 'count', or None.

    None means "unitless / unknown" (e.g. 'to taste', 'pinch', '') — such lines
    are never auto-converted; they merge only on an exact unit-string match.
    """
    u = (unit or '').lower().strip().rstrip('.')
    if not u:
        return None
    if u in _WEIGHT_TO_G:
        return 'mass'
    if u in _VOLUME_TO_ML:
        return 'volume'
    if u in {'piece', 'pieces', 'pcs', 'pc', 'whole', 'unit', 'units'}:
        return 'count'
    return None


def _to_base_amount(qty: float, unit: str) -> Optional[tuple]:
    """Convert (qty, unit) to a (base_amount, dimension) pair.

    Mass   -> grams,      dimension 'mass'
    Volume -> millilitres, dimension 'volume'
    Count  -> pieces,     dimension 'count'
    Returns None if the unit isn't convertible.
    """
    u = (unit or '').lower().strip().rstrip('.')
    if u in _WEIGHT_TO_G:
        return (qty * _WEIGHT_TO_G[u], 'mass')
    if u in _VOLUME_TO_ML:
        return (qty * _VOLUME_TO_ML[u], 'volume')
    if u in {'piece', 'pieces', 'pcs', 'pc', 'whole', 'unit', 'units'}:
        return (qty, 'count')
    return None


def _ingredient_density(name_norm: str) -> Optional[float]:
    """Return a trusted g/ml density for an ingredient, or None if unknown.

    Unlike _ingredient_grams (which falls back to water=1.0 for nutrition
    estimates), here we return None when we are NOT confident, because a wrong
    density would silently corrupt a shopping quantity. Only known ingredients
    get a cross-unit (mass<->volume) merge.
    """
    if name_norm in _INGREDIENT_DENSITY:
        return _INGREDIENT_DENSITY[name_norm]
    for key, dens in _INGREDIENT_DENSITY.items():
        if name_norm.endswith(key):
            return dens
    return None


def _format_base_amount(base_amount: float, dimension: str) -> tuple:
    """Turn a base amount (g / ml / pieces) into a friendly (qty_str, unit)."""
    def _fmt(v: float) -> str:
        return (str(int(round(v))) if abs(v - round(v)) < 1e-6
                else f'{v:.2f}'.rstrip('0').rstrip('.'))

    if dimension == 'mass':
        for unit, factor in _MASS_DISPLAY_LADDER:
            if base_amount >= factor:
                return (_fmt(base_amount / factor), unit)
        return (_fmt(base_amount), 'g')
    if dimension == 'volume':
        for unit, factor in _VOLUME_DISPLAY_LADDER:
            if base_amount >= factor:
                return (_fmt(base_amount / factor), unit)
        return (_fmt(base_amount), 'ml')
    # count
    return (_fmt(base_amount), 'pcs')


class NutritionCache(db.Model):
    """Cache USDA lookups so we don't hit the API for every recipe view.

    Keyed on a normalised ingredient name. Values are per 100 g.
    """
    __tablename__ = 'nutrition_cache'
    id = db.Column(db.Integer, primary_key=True)
    name_key = db.Column(db.String(120), unique=True, index=True, nullable=False)
    source = db.Column(db.String(20), default='usda')  # 'usda' | 'ai' | 'manual'
    calories = db.Column(db.Float)
    protein = db.Column(db.Float)
    fat = db.Column(db.Float)
    carbs = db.Column(db.Float)
    fiber = db.Column(db.Float)
    sugar = db.Column(db.Float)
    sodium = db.Column(db.Float)
    matched_description = db.Column(db.String(200))
    fetched_at = db.Column(db.DateTime, default=utcnow)

    def to_per_100g(self):
        return {
            'calories': self.calories or 0,
            'protein':  self.protein or 0,
            'fat':      self.fat or 0,
            'carbs':    self.carbs or 0,
            'fiber':    self.fiber or 0,
            'sugar':    self.sugar or 0,
            'sodium':   self.sodium or 0,
            'source':   self.source,
            'matched':  self.matched_description,
        }


def _normalise_ingredient_name(name: str) -> str:
    """Strip parens, prep words and excess whitespace; lowercase.

    Examples:
      "chicken breast, boneless and skinless" -> "chicken breast"
      "red onion (finely chopped)" -> "red onion"
      "all-purpose flour" -> "all purpose flour"
    """
    if not name:
        return ''
    s = name.lower().strip()
    # Defensive: strip any leading punctuation junk (e.g. a stray '/' that
    # survived upstream parsing) and any leading quantity+unit fragment so the
    # USDA query is a clean ingredient name, not "/1 3/4 oz fine sea salt".
    s = re.sub(r'^[\s/\\\-–—·•*°.,;:]+', '', s)
    s = re.sub(
        r'^\d+(?:\s+\d+/\d+|\.\d+|/\d+)?\s*'      # leading quantity
        r'(?:g|kg|mg|oz|lb|lbs|ml|l|cup|cups|tsp|tbsp|tablespoon|tablespoons|'
        r'teaspoon|teaspoons|gram|grams|kilogram|kilograms|fl\s*oz|pinch|'
        r'clove|cloves|slice|slices)?\s+',
        '', s
    )
    # Remove parenthetical notes
    s = re.sub(r'\([^)]*\)', '', s)
    # Remove text after common separators
    s = re.split(r'[,;]', s, maxsplit=1)[0]
    # Drop common preparation words
    s = re.sub(
        r'\b(chopped|sliced|diced|minced|grated|crushed|peeled|cooked|raw|'
        r'fresh|frozen|dried|whole|ground|melted|softened|optional|to taste|'
        r'finely|roughly|coarsely|large|small|medium|big|extra|tinned|canned|'
        r'ripe|skinless|boneless|organic)\b',
        ' ', s
    )
    s = s.replace('-', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _ingredient_grams(qty_str: str, unit: str, name: str) -> Optional[float]:
    """Best-effort conversion from a parsed ingredient to grams.

    Returns None if we genuinely cannot estimate (e.g. "to taste").
    """
    qty = _parse_quantity_to_float(qty_str)
    if qty is None:
        return None

    unit_l = (unit or '').lower().strip().rstrip('.')
    name_norm = _normalise_ingredient_name(name)

    if unit_l in _WEIGHT_TO_G:
        return qty * _WEIGHT_TO_G[unit_l]

    if unit_l in _VOLUME_TO_ML:
        ml = qty * _VOLUME_TO_ML[unit_l]
        density = _INGREDIENT_DENSITY.get(name_norm, 1.0)
        # Try suffix match (e.g. "all purpose flour" -> uses flour density)
        if name_norm not in _INGREDIENT_DENSITY:
            for key, dens in _INGREDIENT_DENSITY.items():
                if name_norm.endswith(key):
                    density = dens
                    break
        return ml * density

    # No unit ("2 avocados"): use piece-weight table
    if not unit_l:
        for key, weight in _PIECE_WEIGHTS_G.items():
            if name_norm == key or name_norm.endswith(' ' + key):
                return qty * weight
    return None


def _parse_quantity_to_float(qty_str) -> Optional[float]:
    """Convert a quantity string ('2', '1/2', '1 1/2', '2-3', '½') to float."""
    if qty_str is None:
        return None
    if isinstance(qty_str, (int, float)):
        return float(qty_str)
    s = str(qty_str).strip()
    if not s:
        return None
    # Unicode fractions
    unicode_frac = {'½':0.5,'¼':0.25,'¾':0.75,'⅓':1/3,'⅔':2/3,'⅛':0.125,'⅜':0.375,'⅝':0.625,'⅞':0.875}
    if s in unicode_frac:
        return unicode_frac[s]
    # Range "2-3" -> average
    range_match = re.match(r'^(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)$', s)
    if range_match:
        return (float(range_match.group(1)) + float(range_match.group(2))) / 2
    # Mixed number "1 1/2"
    mixed = re.match(r'^(\d+)\s+(\d+)/(\d+)$', s)
    if mixed:
        return int(mixed.group(1)) + int(mixed.group(2)) / int(mixed.group(3))
    # Plain fraction
    frac = re.match(r'^(\d+)/(\d+)$', s)
    if frac:
        return int(frac.group(1)) / int(frac.group(2))
    try:
        return float(s)
    except ValueError:
        return None


def _usda_extract_macros_from_search(food: dict) -> dict:
    """Extract macros from a /foods/search response item (flat shape)."""
    result = {}
    for n in food.get('foodNutrients', []) or []:
        nid = n.get('nutrientId')
        if nid in _USDA_NUTRIENT_MAP:
            key, _ = _USDA_NUTRIENT_MAP[nid]
            result[key] = float(n.get('value') or 0)
    return result


def _usda_extract_macros_from_detail(food: dict) -> dict:
    """Extract macros from a /food/{id} response item (nested shape)."""
    result = {}
    for n in food.get('foodNutrients', []) or []:
        nut = n.get('nutrient') or {}
        nid = nut.get('id')
        if nid in _USDA_NUTRIENT_MAP:
            key, _ = _USDA_NUTRIENT_MAP[nid]
            result[key] = float(n.get('amount') or 0)
    return result


# Map common cooking ingredient names to more specific USDA query terms
# that yield the canonical "plain" product rather than exotic variants.
_USDA_QUERY_SYNONYMS = {
    'flour': 'wheat flour, white, all-purpose',
    'sugar': 'sugars, granulated',
    'salt': 'salt, table',
    'butter': 'butter, salted',
    'milk': 'milk, whole',
    'egg': 'egg, whole, raw',
    'eggs': 'egg, whole, raw',
    'rice': 'rice, white, long-grain, raw',
    'pasta': 'pasta, dry, unenriched',
    'olive oil': 'oil, olive',
    'vegetable oil': 'oil, vegetable',
    'onion': 'onions, raw',
    'garlic': 'garlic, raw',
    'tomato': 'tomatoes, red, ripe, raw',
    'potato': 'potatoes, raw, skin',
    'carrot': 'carrots, raw',
    'chicken': 'chicken, broiler, breast, meat only, raw',
    'chicken breast': 'chicken, broiler, breast, meat only, raw',
    'beef': 'beef, ground, raw',
    'pork': 'pork, fresh, loin, raw',
    'cheese': 'cheese, cheddar',
    'water': 'water, tap',
    'pepper': 'spices, pepper, black',
    'black pepper': 'spices, pepper, black',
    'lemon': 'lemons, raw',
    'apple': 'apples, raw, with skin',
    'banana': 'bananas, raw',
}


# Cache of {original_lower: english_term} so we don't re-translate the same
# non-English ingredient name on every nutrition lookup.
_INGREDIENT_EN_CACHE: dict = {}

# Small built-in dictionary for the most common Russian/Italian cooking terms,
# used as an instant fallback before hitting the LLM (and when no key is set).
_INGREDIENT_EN_DICT = {
    # Russian
    'мука': 'flour', 'сахар': 'sugar', 'соль': 'salt', 'масло': 'butter',
    'сливочное масло': 'butter', 'растительное масло': 'vegetable oil',
    'оливковое масло': 'olive oil', 'молоко': 'milk', 'яйцо': 'egg',
    'яйца': 'eggs', 'рис': 'rice', 'макароны': 'pasta', 'паста': 'pasta',
    'лук': 'onion', 'чеснок': 'garlic', 'помидор': 'tomato', 'томат': 'tomato',
    'помидоры': 'tomatoes', 'картофель': 'potato', 'картошка': 'potato',
    'морковь': 'carrot', 'курица': 'chicken', 'куриная грудка': 'chicken breast',
    'говядина': 'beef', 'свинина': 'pork', 'рыба': 'fish', 'сыр': 'cheese',
    'сметана': 'sour cream', 'сливки': 'cream', 'творог': 'cottage cheese',
    'вода': 'water', 'перец': 'pepper', 'чёрный перец': 'black pepper',
    'сахарная пудра': 'powdered sugar', 'дрожжи': 'yeast', 'мёд': 'honey',
    'мед': 'honey', 'грибы': 'mushrooms', 'капуста': 'cabbage',
    'огурец': 'cucumber', 'свёкла': 'beet', 'свекла': 'beet',
    'фасоль': 'beans', 'горох': 'peas', 'кукуруза': 'corn', 'хлеб': 'bread',
    'мясо': 'meat', 'уксус': 'vinegar', 'сода': 'baking soda',
    'разрыхлитель': 'baking powder', 'ваниль': 'vanilla', 'какао': 'cocoa',
    'шоколад': 'chocolate', 'орехи': 'nuts', 'изюм': 'raisins',
    'лимон': 'lemon', 'яблоко': 'apple', 'банан': 'banana',
    # Italian
    'farina': 'flour', 'zucchero': 'sugar', 'sale': 'salt', 'burro': 'butter',
    'olio': 'oil', "olio d'oliva": 'olive oil', 'latte': 'milk', 'uovo': 'egg',
    'uova': 'eggs', 'riso': 'rice', 'cipolla': 'onion', 'aglio': 'garlic',
    'pomodoro': 'tomato', 'pomodori': 'tomatoes', 'patata': 'potato',
    'carota': 'carrot', 'pollo': 'chicken', 'manzo': 'beef', 'maiale': 'pork',
    'pesce': 'fish', 'formaggio': 'cheese', 'panna': 'cream', 'acqua': 'water',
    'pepe': 'pepper', 'lievito': 'yeast', 'miele': 'honey',
}


def _to_english_ingredient(name: str) -> str:
    """Translate a non-English ingredient name to a canonical English term.

    USDA FoodData Central is English-only, so Russian/Italian/etc. names never
    match. We detect non-ASCII names, try a built-in dictionary first, then ask
    the LLM. English (ASCII) names are returned unchanged. Results are cached.
    """
    if not name:
        return name

    key = name.lower().strip()
    if key in _INGREDIENT_EN_CACHE:
        return _INGREDIENT_EN_CACHE[key]

    # 1) Dictionary fast-path (exact, then word-level). Checked even for ASCII
    #    names because Italian/Spanish/French terms (e.g. "farina") are ASCII
    #    but still need translating for USDA.
    if key in _INGREDIENT_EN_DICT:
        _INGREDIENT_EN_CACHE[key] = _INGREDIENT_EN_DICT[key]
        return _INGREDIENT_EN_DICT[key]
    for word in key.split():
        if word in _INGREDIENT_EN_DICT:
            _INGREDIENT_EN_CACHE[key] = _INGREDIENT_EN_DICT[word]
            return _INGREDIENT_EN_DICT[word]

    # Pure-ASCII names not in the dictionary are assumed already English
    # (translating every English ingredient via the LLM would be wasteful).
    try:
        if name.isascii():
            return name
    except (AttributeError, TypeError):
        logger.debug("ingredient EN translate: isascii check failed for %r", name)

    # 2) LLM translation to a single canonical English ingredient name
    #    (handles non-ASCII names like Cyrillic that aren't in the dictionary).
    if OPENAI_NEW_API and openai_client:
        try:
            resp = openai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{
                    'role': 'user',
                    'content': (
                        'Translate this food ingredient name to its common '
                        'English name as found in a nutrition database. '
                        'Reply with ONLY the English ingredient name, no extra '
                        f'words, no punctuation:\n"{name}"'
                    ),
                }],
                temperature=0,
                max_tokens=20,
            )
            english = (resp.choices[0].message.content or '').strip().strip('".')
            if english and english.isascii():
                _INGREDIENT_EN_CACHE[key] = english
                return english
        except Exception as e:
            logger.warning(f"Ingredient translation failed for {name!r}: {e}")

    # 3) Give up — return original (AI nutrition fallback may still handle it).
    return name


def _usda_lookup(ingredient_name: str) -> Optional[dict]:
    """Query USDA FoodData Central for the best match.

    The /foods/search endpoint returns an abbreviated nutrient list, so a
    product may match by description but be missing the macro fields we need
    (Energy/Protein/Fat/Carbs). In that case we follow up with /food/<fdcId>
    which returns the full nutrient profile.

    Returns a dict of per-100g macros, or None on failure.
    """
    if not ingredient_name:
        return None
    # Re-route common ingredient terms to canonical USDA descriptions to
    # avoid quirks like "flour" → "Arrowroot flour".
    q_key = ingredient_name.lower().strip()
    query_term = _USDA_QUERY_SYNONYMS.get(q_key, ingredient_name)
    try:
        # USDA's `dataType` filter is finicky: passing parenthesised values
        # like "Survey (FNDDS)" alongside others can yield 400. We try the
        # cleanest filter first, then fall back to Branded-included.
        params = {
            'query':    query_term,
            'pageSize': 10,
            'dataType': 'Foundation,SR Legacy',
            'api_key':  USDA_API_KEY,
        }
        r = requests.get(USDA_SEARCH_URL, params=params, timeout=8)
        if r.status_code == 429:
            logger.warning("USDA rate-limited (429). Falling back to AI nutrition.")
            return None
        if r.status_code != 200:
            logger.warning(f"USDA search failed [{r.status_code}] for {ingredient_name!r}: {r.text[:120]}")
            return None
        foods = r.json().get('foods') or []
        if not foods:
            # Retry without dataType filter (Branded fallback).
            params.pop('dataType', None)
            r = requests.get(USDA_SEARCH_URL, params=params, timeout=8)
            if r.status_code != 200:
                return None
            foods = r.json().get('foods') or []
        if not foods:
            return None

        # Score candidates by how closely the description matches the query.
        # USDA's relevance ranking sometimes surfaces "Avocado dressing" for
        # "avocado", so we re-rank: exact match > starts-with > word-match.
        q_lower = ingredient_name.lower().strip()
        q_words = set(q_lower.split())
        def _match_score(food):
            desc = (food.get('description') or '').lower()
            desc_words = set(desc.replace(',', ' ').split())
            if desc == q_lower:
                return 0
            if desc.startswith(q_lower + ',') or desc.startswith(q_lower + ' '):
                return 1
            if desc.startswith(q_lower):
                return 2
            # All query words present as whole words
            if q_words.issubset(desc_words):
                return 3
            if f' {q_lower}' in f' {desc}':
                return 4
            return 5
        foods = sorted(foods, key=_match_score)

        # Try each candidate until one has Energy. The first hit often skips
        # Energy entirely (especially Foundation entries), so we may need to
        # request /food/<id> for the full profile.
        for food in foods:
            macros = _usda_extract_macros_from_search(food)
            if 'calories' not in macros:
                fdc_id = food.get('fdcId')
                if fdc_id:
                    try:
                        rd = requests.get(
                            USDA_FOOD_URL.format(fdc_id=fdc_id),
                            params={'api_key': USDA_API_KEY},
                            timeout=8,
                        )
                        if rd.status_code == 200:
                            macros = _usda_extract_macros_from_detail(rd.json())
                    except Exception as e:
                        logger.debug(f"USDA detail fetch failed for fdcId={fdc_id}: {e}")
            if macros.get('calories'):
                macros['source'] = 'usda'
                macros['matched'] = food.get('description')
                return macros

        # Nothing had calories — still return the first match with whatever
        # we have, so the caller can show partial data.
        food = foods[0]
        macros = _usda_extract_macros_from_search(food)
        macros['source'] = 'usda'
        macros['matched'] = food.get('description')
        return macros
    except Exception as e:
        logger.warning(f"USDA lookup error for {ingredient_name!r}: {e}")
        return None


def _ai_nutrition_fallback(ingredient_name: str) -> Optional[dict]:
    """Ask the LLM to estimate per-100g macros when USDA has no match."""
    if not (openai_client or openai_api_key):
        return None
    prompt = (
        f'Estimate the nutrition per 100 g of "{ingredient_name}". '
        'Respond ONLY with compact JSON keys: calories (kcal), protein (g), '
        'fat (g), carbs (g), fiber (g), sugar (g), sodium (mg). '
        'Use realistic average values. Numbers only, no text.'
    )
    try:
        if openai_client:
            resp = openai_client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
                max_tokens=120,
                response_format={'type': 'json_object'},
            )
            text_response = resp.choices[0].message.content
        else:
            return None
        parsed = json.loads(text_response)
        parsed['source'] = 'ai'
        parsed['matched'] = f'AI estimate for {ingredient_name}'
        return parsed
    except Exception as e:
        logger.warning(f"AI nutrition fallback failed for {ingredient_name!r}: {e}")
        return None


def get_ingredient_nutrition(name: str, force_refresh: bool = False) -> dict:
    """Return per-100g macros for an ingredient, with caching.

    Lookup order: cache → USDA → AI fallback. Returns zero-filled dict if no
    source produced data (the caller can decide how to surface that).
    """
    name_key = _normalise_ingredient_name(name)
    if not name_key:
        return {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0,
                'fiber': 0, 'sugar': 0, 'sodium': 0, 'source': 'unknown',
                'matched': None}

    if not force_refresh:
        cached = NutritionCache.query.filter_by(name_key=name_key).first()
        if cached:
            return cached.to_per_100g()

    # USDA is English-only: translate non-English ingredient names first so the
    # lookup can match. English names pass through unchanged.
    lookup_name = _to_english_ingredient(name_key)
    info = _usda_lookup(lookup_name) or _ai_nutrition_fallback(lookup_name) \
        or (_ai_nutrition_fallback(name_key) if lookup_name != name_key else None)
    if not info:
        return {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0,
                'fiber': 0, 'sugar': 0, 'sodium': 0, 'source': 'unknown',
                'matched': None}

    # Upsert cache
    try:
        cached = NutritionCache.query.filter_by(name_key=name_key).first()
        if not cached:
            cached = NutritionCache(name_key=name_key)
            db.session.add(cached)
        cached.source = info.get('source', 'usda')
        cached.calories = info.get('calories', 0) or 0
        cached.protein  = info.get('protein', 0) or 0
        cached.fat      = info.get('fat', 0) or 0
        cached.carbs    = info.get('carbs', 0) or 0
        cached.fiber    = info.get('fiber', 0) or 0
        cached.sugar    = info.get('sugar', 0) or 0
        cached.sodium   = info.get('sodium', 0) or 0
        cached.matched_description = info.get('matched')
        cached.fetched_at = utcnow()
        db.session.commit()
    except Exception as e:
        logger.warning(f"Failed to cache nutrition for {name_key!r}: {e}")
        db.session.rollback()

    return {
        'calories': info.get('calories', 0) or 0,
        'protein':  info.get('protein', 0) or 0,
        'fat':      info.get('fat', 0) or 0,
        'carbs':    info.get('carbs', 0) or 0,
        'fiber':    info.get('fiber', 0) or 0,
        'sugar':    info.get('sugar', 0) or 0,
        'sodium':   info.get('sodium', 0) or 0,
        'source':   info.get('source', 'usda'),
        'matched':  info.get('matched'),
    }


def calculate_recipe_nutrition(ingredients_list, servings: int = 1) -> dict:
    """Aggregate nutrition for a list of ingredient strings/dicts.

    Returns total + per-serving macros, plus per-ingredient breakdown.
    """
    totals = {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0,
              'fiber': 0, 'sugar': 0, 'sodium': 0}
    breakdown = []

    for raw_ing in ingredients_list or []:
        if isinstance(raw_ing, dict):
            text = raw_ing.get('original_text') or raw_ing.get('ingredient') or raw_ing.get('text') or ''
            qty_str = raw_ing.get('quantity') or raw_ing.get('amount') or ''
            unit = raw_ing.get('unit') or ''
            name = raw_ing.get('ingredient') or raw_ing.get('name') or text
            if not qty_str and not unit and text:
                parsed = clean_ingredient_text(text)
                qty_str, unit, name = parsed['quantity'], parsed['unit'], parsed['ingredient']
        else:
            text = str(raw_ing)
            parsed = clean_ingredient_text(text)
            qty_str, unit, name = parsed['quantity'], parsed['unit'], parsed['ingredient']

        if not name:
            continue

        grams = _ingredient_grams(qty_str, unit, name)
        per100 = get_ingredient_nutrition(name)

        ing_breakdown = {
            'ingredient': name,
            'quantity':   qty_str,
            'unit':       unit,
            'grams_estimate': round(grams, 1) if grams else None,
            'per_100g':   per100,
            'estimated':  None,
        }

        if grams and per100.get('source') != 'unknown':
            scale = grams / 100.0
            est = {k: round(per100[k] * scale, 2) for k in totals}
            ing_breakdown['estimated'] = est
            for k in totals:
                totals[k] += est[k]

        breakdown.append(ing_breakdown)

    totals = {k: round(v, 1) for k, v in totals.items()}
    servings = max(1, int(servings or 1))
    per_serving = {k: round(v / servings, 1) for k, v in totals.items()}

    return {
        'total': totals,
        'per_serving': per_serving,
        'servings': servings,
        'ingredients': breakdown,
    }


@app.route('/api/nutrition/ingredient', methods=['GET'])
@require_auth
@rate_limit(max_requests=60, window_seconds=60, scope='nutrition_ingredient')
def api_nutrition_ingredient():
    """Return per-100g macros for a single ingredient name.

    Requires authentication and is rate-limited because it triggers external
    USDA / OpenAI calls that cost money and quota.
    Query string: ?name=chicken+breast
    """
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name query parameter is required'}), 400
    info = get_ingredient_nutrition(name)
    return jsonify({'ingredient': name, 'per_100g': info})


@app.route('/api/nutrition/recipe', methods=['POST'])
@require_auth
@rate_limit(max_requests=30, window_seconds=60, scope='nutrition_recipe')
def api_nutrition_recipe():
    """Compute aggregate nutrition from a list of ingredients.

    Body:
      { "ingredients": ["2 cups flour", "1 tsp salt", ...],
        "servings": 4 }
    """
    data = request.get_json(silent=True) or {}
    ingredients = data.get('ingredients') or []
    servings = int(data.get('servings') or 1)
    if not isinstance(ingredients, list) or not ingredients:
        return jsonify({'error': 'ingredients array is required'}), 400
    result = calculate_recipe_nutrition(ingredients, servings=servings)
    return jsonify({'success': True, 'nutrition': result})


@app.route('/api/recipes/<int:recipe_id>/nutrition', methods=['GET'])
@require_auth
def api_recipe_nutrition(recipe_id):
    """Compute nutrition for a saved recipe owned by the authenticated user."""
    user = request.current_user
    recipe = Recipe.query.filter_by(id=recipe_id, user_id=user.id).first()
    if not recipe:
        return jsonify({'error': 'Recipe not found'}), 404

    ingredients = []
    for ing in recipe.ingredients:
        ingredients.append({
            'ingredient': ing.ingredient,
            'quantity':   ing.quantity,
            'unit':       ing.unit,
        })
    result = calculate_recipe_nutrition(ingredients, servings=recipe.servings or 1)
    return jsonify({'success': True, 'recipe_id': recipe_id, 'nutrition': result})


# ============================================================================
# SHOPPING LISTS
# ============================================================================

class ShoppingList(db.Model):
    __tablename__ = 'shopping_lists'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default='Shopping list')
    target_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    items = db.relationship('ShoppingListItem', backref='shopping_list',
                            lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'target_date': self.target_date.isoformat() if self.target_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'items': [it.to_dict() for it in self.items.order_by(ShoppingListItem.id.asc())],
        }


class ShoppingListItem(db.Model):
    __tablename__ = 'shopping_list_items'
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('shopping_lists.id'),
                        nullable=False, index=True)
    ingredient = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.String(50))
    unit = db.Column(db.String(50))
    checked = db.Column(db.Boolean, default=False)
    # JSON-encoded list of recipe IDs that contributed to this item.
    source_recipes = db.Column(db.Text, default='[]')

    def to_dict(self):
        try:
            sources = json.loads(self.source_recipes or '[]')
        except Exception:
            sources = []
        return {
            'id': self.id,
            'ingredient': self.ingredient,
            'quantity':   self.quantity,
            'unit':       self.unit,
            'checked':    bool(self.checked),
            'source_recipes': sources,
            'category':    categorize_ingredient(self.ingredient),
        }


# ── Grocery category classification (offline RU+EN keyword dictionary) ────────
# Maps a normalised ingredient name to one of the smart-list aisles. Unknown
# items fall back to 'other'. Keys are substrings matched against the
# normalised name; first matching category wins (checked in CATEGORY_ORDER).
GROCERY_CATEGORIES = ('vegetables', 'fruits', 'dairy', 'meat', 'pantry', 'other')

GROCERY_KEYWORDS = {
    'vegetables': [
        # EN
        'tomato', 'onion', 'garlic', 'potato', 'carrot', 'pepper', 'cucumber',
        'lettuce', 'spinach', 'broccoli', 'cabbage', 'zucchini', 'mushroom',
        'celery', 'corn', 'pea', 'bean sprout', 'eggplant', 'aubergine',
        'pumpkin', 'beet', 'radish', 'leek', 'scallion', 'kale', 'cauliflower',
        'green bean', 'asparagus', 'chili', 'chilli', 'ginger', 'herb',
        'parsley', 'cilantro', 'basil', 'dill', 'mint',
        # RU
        'помидор', 'томат', 'лук', 'чеснок', 'картоф', 'морков', 'перец',
        'огурец', 'огурц', 'салат', 'шпинат', 'брокколи', 'капуст', 'кабач',
        'гриб', 'шампиньон', 'сельдерей', 'кукуруз', 'горош', 'баклажан',
        'тыкв', 'свекл', 'редис', 'порей', 'зелен', 'петрушк', 'кинз',
        'базилик', 'укроп', 'мят', 'имбир', 'цветная капуста', 'спарж',
    ],
    'fruits': [
        'apple', 'banana', 'orange', 'lemon', 'lime', 'berry', 'strawberry',
        'blueberry', 'raspberry', 'grape', 'pear', 'peach', 'mango', 'pineapple',
        'avocado', 'cherry', 'melon', 'kiwi', 'apricot', 'plum', 'pomegranate',
        'яблок', 'банан', 'апельсин', 'лимон', 'лайм', 'ягод', 'клубник',
        'черник', 'малин', 'виноград', 'груш', 'персик', 'манго', 'ананас',
        'авокадо', 'вишн', 'черешн', 'дын', 'арбуз', 'киви', 'абрикос', 'слив',
        'гранат', 'смородин',
    ],
    'dairy': [
        'milk', 'cream', 'butter', 'cheese', 'yogurt', 'yoghurt', 'curd',
        'sour cream', 'mozzarella', 'parmesan', 'cheddar', 'feta', 'ricotta',
        'egg', 'kefir', 'mascarpone',
        'молок', 'молоч', 'сливк', 'масл', 'сыр', 'йогурт', 'творог',
        'сметан', 'моцарелл', 'пармезан', 'чеддер', 'фет', 'рикотт', 'яйц',
        'яйца', 'кефир', 'маскарпоне',
    ],
    'meat': [
        'chicken', 'beef', 'pork', 'lamb', 'turkey', 'bacon', 'sausage', 'ham',
        'mince', 'steak', 'fish', 'salmon', 'tuna', 'shrimp', 'prawn', 'cod',
        'meat', 'fillet', 'duck', 'veal', 'seafood', 'anchov',
        'куриц', 'куриное', 'курин', 'говядин', 'свинин', 'баранин', 'индейк',
        'бекон', 'колбас', 'сосиск', 'ветчин', 'фарш', 'стейк', 'рыб', 'лосос',
        'тунец', 'креветк', 'треск', 'мяс', 'филе', 'утк', 'телятин',
        'морепродукт', 'анчоус',
    ],
    'pantry': [
        'flour', 'sugar', 'salt', 'pepper', 'oil', 'vinegar', 'rice', 'pasta',
        'noodle', 'bread', 'oat', 'cereal', 'honey', 'syrup', 'sauce', 'paste',
        'stock', 'broth', 'spice', 'baking', 'yeast', 'soda', 'cocoa',
        'chocolate', 'vanilla', 'cinnamon', 'nut', 'almond', 'walnut', 'seed',
        'lentil', 'chickpea', 'bean', 'canned', 'tinned', 'soy', 'mustard',
        'ketchup', 'mayo', 'water', 'wine', 'coffee', 'tea',
        'мук', 'сахар', 'сол', 'масло растит', 'уксус', 'рис', 'макарон',
        'паст', 'лапш', 'хлеб', 'овсян', 'хлоп', 'мёд', 'мед', 'сироп',
        'соус', 'бульон', 'специ', 'припр', 'дрожж', 'сод', 'какао',
        'шоколад', 'ванил', 'корица', 'орех', 'миндал', 'грецк', 'семеч',
        'чечевиц', 'нут', 'фасол', 'консерв', 'соев', 'горчиц', 'кетчуп',
        'майонез', 'вод', 'вино', 'кофе', 'чай', 'крупа', 'греч',
    ],
}


# High-priority phrase overrides, checked BEFORE the broad keyword scan. These
# fix common substring false-positives where a compound word contains a keyword
# for a different aisle (e.g. "vegetable oil" contains the dairy keyword "oil"
# via RU "масл", "black pepper" contains the veg keyword "pepper",
# "chicken stock" contains the meat keyword "chicken" but is really a pantry
# staple, "coconut milk" contains the dairy keyword "milk"). First match wins.
GROCERY_OVERRIDES = [
    # Cooking oils -> pantry (must beat dairy 'oil'/RU 'масл').
    ('vegetable oil', 'pantry'), ('olive oil', 'pantry'), ('sunflower oil', 'pantry'),
    ('coconut oil', 'pantry'), ('sesame oil', 'pantry'), ('canola oil', 'pantry'),
    ('растительное масло', 'pantry'), ('масло растит', 'pantry'),
    ('оливковое масло', 'pantry'), ('подсолнечное масло', 'pantry'),
    ('подсолнечн', 'pantry'), ('кокосовое масло', 'pantry'),
    ('кунжутное масло', 'pantry'), ('растительн', 'pantry'),
    # Plant 'milks' & creams -> pantry (must beat dairy 'milk'/RU 'молок').
    ('coconut milk', 'pantry'), ('almond milk', 'pantry'), ('soy milk', 'pantry'),
    ('oat milk', 'pantry'), ('rice milk', 'pantry'), ('coconut cream', 'pantry'),
    ('кокосовое молоко', 'pantry'), ('миндальное молоко', 'pantry'),
    ('соевое молоко', 'pantry'), ('овсяное молоко', 'pantry'),
    # Spices/condiments with veg/meat keyword substrings -> pantry.
    ('black pepper', 'pantry'), ('white pepper', 'pantry'), ('peppercorn', 'pantry'),
    ('cayenne pepper', 'pantry'), ('red pepper flake', 'pantry'),
    ('черный перец', 'pantry'), ('чёрный перец', 'pantry'), ('перец черный', 'pantry'),
    ('перец чёрный', 'pantry'), ('перец горошком', 'pantry'), ('душистый перец', 'pantry'),
    ('паприка', 'pantry'),
    # Stocks / broths / fish sauce -> pantry (beat meat 'chicken'/'beef'/'fish').
    ('chicken stock', 'pantry'), ('beef stock', 'pantry'), ('vegetable stock', 'pantry'),
    ('fish stock', 'pantry'), ('chicken broth', 'pantry'), ('beef broth', 'pantry'),
    ('vegetable broth', 'pantry'), ('fish sauce', 'pantry'), ('oyster sauce', 'pantry'),
    ('bouillon', 'pantry'), ('stock cube', 'pantry'),
    ('куриный бульон', 'pantry'), ('говяжий бульон', 'pantry'),
    ('овощной бульон', 'pantry'), ('бульонный кубик', 'pantry'),
    ('рыбный соус', 'pantry'), ('устричный соус', 'pantry'), ('бульон', 'pantry'),
    # 'butter' compounds that aren't dairy.
    ('peanut butter', 'pantry'), ('almond butter', 'pantry'), ('nut butter', 'pantry'),
    ('cocoa butter', 'pantry'), ('butter bean', 'pantry'), ('butternut', 'vegetables'),
    ('арахисовое масло', 'pantry'), ('ореховая паста', 'pantry'),
    # 'corn' compounds that are pantry staples (beat veg 'corn').
    ('cornstarch', 'pantry'), ('corn starch', 'pantry'), ('corn flour', 'pantry'),
    ('cornmeal', 'pantry'), ('popcorn', 'pantry'), ('corn syrup', 'pantry'),
    ('кукурузный крахмал', 'pantry'), ('кукурузная мука', 'pantry'),
    ('кукурузный сироп', 'pantry'), ('попкорн', 'pantry'),
    # 'bean' compounds that are pantry (beat veg; 'green bean' stays veg below).
    ('vanilla bean', 'pantry'), ('coffee bean', 'pantry'), ('cocoa bean', 'pantry'),
    ('ванильный стручок', 'pantry'), ('кофейные зёрна', 'pantry'),
    ('кофейные зерна', 'pantry'),
    # 'egg' compounds that aren't dairy.
    ('egg noodle', 'pantry'), ('eggplant', 'vegetables'), ('баклажан', 'vegetables'),
    # Keep these as veg even though they contain other keywords.
    ('green bean', 'vegetables'), ('bell pepper', 'vegetables'),
    ('болгарский перец', 'vegetables'), ('сладкий перец', 'vegetables'),
    ('стручковая фасоль', 'vegetables'), ('зеленая фасоль', 'vegetables'),
    ('зелёная фасоль', 'vegetables'),
]


def categorize_ingredient(name: str) -> str:
    """Classify an ingredient name into a grocery aisle using the keyword dict.

    First, high-priority phrase overrides are checked (GROCERY_OVERRIDES) to
    resolve common substring false-positives (e.g. "vegetable oil" is pantry,
    not dairy). Then matching falls back to the broad keyword dict: the first
    category in the order meat, dairy, vegetables, fruits, pantry with a
    matching keyword wins so that e.g. protein words beat the 'stock'/'sauce'
    pantry keywords. Unknown -> 'other'.
    """
    norm = _normalise_ingredient_name(name or '')
    if not norm:
        return 'other'
    raw = (name or '').lower()
    # 1) Phrase overrides (first match wins).
    for phrase, cat in GROCERY_OVERRIDES:
        if phrase in norm or phrase in raw:
            return cat
    # 2) Broad keyword scan. Order matters: protein words should win over the
    # 'stock'/'sauce' pantry keywords, and dairy 'egg' should win generically.
    for cat in ('meat', 'dairy', 'vegetables', 'fruits', 'pantry'):
        for kw in GROCERY_KEYWORDS[cat]:
            if kw in norm or kw in raw:
                return cat
    return 'other'


class PantryItem(db.Model):
    """A product the user currently has at home (manual pantry inventory).

    Matching against recipe ingredients is done by normalised name only
    (no quantity comparison). Categories are auto-assigned via
    categorize_ingredient on create/update.
    """
    __tablename__ = 'pantry_items'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'),
                        nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.String(50))
    unit = db.Column(db.String(50))
    category = db.Column(db.String(50), default='other')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'quantity': self.quantity or '',
            'unit': self.unit or '',
            'category': self.category or 'other',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


def _aggregate_ingredients_for_list(recipe_ids: list, owner_id: int) -> list:
    """Pull ingredients from each recipe and merge them for a shopping list.

    Unit-aware merge algorithm (shopping list ONLY — never touches recipes):
      1. For each recipe owned by owner_id, iterate its Ingredient rows.
      2. Normalise name (lower, trim, drop prep words).
      3. Convert the (qty, unit) pair to a base amount + dimension:
           mass -> grams, volume -> ml, count -> pieces.
      4. Bucket convertible lines by (name, dimension) and SUM in the base
         unit, so "2 cup flour" + "100 g flour" land in the same mass bucket
         once a trusted density bridges volume->mass.
      5. Non-convertible lines (no/unknown unit, 'to taste', 'pinch') fall back
         to the legacy (name, exact-unit) bucketing — never auto-converted.
      6. Lines whose quantity isn't numeric keep their textual quantity.
      7. Re-format each merged total to a friendly unit (1500 g -> "1.5 kg").

    Safety: recipe Ingredient rows are read-only here. The conversion output is
    used purely to build the shopping list; cooking and serving-scaling continue
    to use the original recipe quantities.
    """
    # Two bucket spaces:
    #   dim_buckets: keyed (name, dimension) -> accumulates base_amount
    #   raw_buckets: keyed (name, exact_unit) -> legacy text/exact-unit merge
    dim_buckets: dict[tuple, dict] = {}
    raw_buckets: dict[tuple, dict] = {}

    for rid in recipe_ids:
        recipe = Recipe.query.filter_by(id=rid, user_id=owner_id).first()
        if not recipe:
            continue
        for ing in recipe.ingredients:
            name_key = _normalise_ingredient_name(ing.ingredient)
            if not name_key:
                continue
            qty_value = _parse_quantity_to_float(ing.quantity)
            unit_raw = ing.unit or ''
            base = _to_base_amount(qty_value, unit_raw) if qty_value is not None else None

            # ---- Path A: convertible numeric line (mass/volume/count) --------
            if base is not None:
                base_amount, dimension = base
                # Volume lines are folded into the MASS dimension only when we
                # have a trusted density for this ingredient; otherwise they
                # stay in their own volume dimension (safe — no guessed density).
                if dimension == 'volume':
                    dens = _ingredient_density(name_key)
                    if dens is not None:
                        base_amount, dimension = base_amount * dens, 'mass'
                key = (name_key, dimension)
                if key not in dim_buckets:
                    dim_buckets[key] = {
                        'ingredient': ing.ingredient.strip(),
                        'base_amount': base_amount,
                        'dimension': dimension,
                        'sources': [recipe.id],
                    }
                else:
                    b = dim_buckets[key]
                    b['base_amount'] += base_amount
                    if recipe.id not in b['sources']:
                        b['sources'].append(recipe.id)
                continue

            # ---- Path B: non-convertible / textual line (legacy merge) ------
            unit_key = unit_raw.lower().strip()
            key = (name_key, unit_key)
            if key not in raw_buckets:
                raw_buckets[key] = {
                    'ingredient': ing.ingredient.strip(),
                    'quantity_numeric': qty_value,
                    'quantity_text': ing.quantity if qty_value is None else None,
                    'unit': unit_raw,
                    'sources': [recipe.id],
                }
            else:
                b = raw_buckets[key]
                if qty_value is not None and b['quantity_numeric'] is not None:
                    b['quantity_numeric'] += qty_value
                elif qty_value is not None and b['quantity_numeric'] is None:
                    b['quantity_numeric'] = qty_value
                if recipe.id not in b['sources']:
                    b['sources'].append(recipe.id)

    items = []
    for b in dim_buckets.values():
        qty_str, unit = _format_base_amount(b['base_amount'], b['dimension'])
        items.append({
            'ingredient': b['ingredient'],
            'quantity':   qty_str,
            'unit':       unit,
            'sources':    b['sources'],
            'category':   categorize_ingredient(b['ingredient']),
        })
    for b in raw_buckets.values():
        if b['quantity_numeric'] is not None:
            qv = b['quantity_numeric']
            qty_str = (str(int(qv)) if abs(qv - round(qv)) < 1e-6 else f'{qv:.2f}'.rstrip('0').rstrip('.'))
        else:
            qty_str = b['quantity_text'] or ''
        items.append({
            'ingredient': b['ingredient'],
            'quantity':   qty_str,
            'unit':       b['unit'],
            'sources':    b['sources'],
            'category':   categorize_ingredient(b['ingredient']),
        })
    items.sort(key=lambda it: it['ingredient'].lower())
    return items


@app.route('/api/shopping-lists', methods=['GET', 'POST'])
@require_auth
def api_shopping_lists():
    user = request.current_user

    if request.method == 'GET':
        page, per_page = _parse_pagination(default_per_page=20, max_per_page=100)
        paginated = (
            ShoppingList.query
            .filter_by(user_id=user.id)
            .order_by(ShoppingList.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return jsonify({
            'success': True,
            'shopping_lists': [sl.to_dict() for sl in paginated.items],
            'pagination': _pagination_dict(paginated),
        })

    # POST
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or 'Shopping list').strip()
    target_date_str = data.get('target_date')
    target_date = None
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'target_date must be YYYY-MM-DD'}), 400

    sl = ShoppingList(user_id=user.id, name=name, target_date=target_date)
    db.session.add(sl)
    db.session.flush()  # get sl.id

    # Optional: build items from recipe IDs
    recipe_ids = data.get('recipe_ids') or []
    if recipe_ids:
        aggregated = _aggregate_ingredients_for_list(recipe_ids, user.id)
        for item in aggregated:
            sl.items.append(ShoppingListItem(
                ingredient=item['ingredient'],
                quantity=item['quantity'],
                unit=item['unit'],
                checked=False,
                source_recipes=json.dumps(item['sources']),
            ))

    # Optional: free-form items
    for raw in data.get('items') or []:
        if isinstance(raw, dict):
            sl.items.append(ShoppingListItem(
                ingredient=raw.get('ingredient', ''),
                quantity=str(raw.get('quantity', '')),
                unit=raw.get('unit', ''),
                checked=bool(raw.get('checked', False)),
            ))
        elif isinstance(raw, str) and raw.strip():
            parsed = clean_ingredient_text(raw)
            sl.items.append(ShoppingListItem(
                ingredient=parsed['ingredient'] or raw,
                quantity=parsed['quantity'],
                unit=parsed['unit'],
            ))

    db.session.commit()
    return jsonify({'success': True, 'shopping_list': sl.to_dict()}), 201


@app.route('/api/shopping-lists/<int:list_id>',
           methods=['GET', 'PUT', 'DELETE'])
@require_auth
def api_shopping_list_detail(list_id):
    user = request.current_user
    sl = ShoppingList.query.filter_by(id=list_id, user_id=user.id).first()
    if not sl:
        return jsonify({'error': 'Shopping list not found'}), 404

    if request.method == 'GET':
        return jsonify({'success': True, 'shopping_list': sl.to_dict()})

    if request.method == 'DELETE':
        db.session.delete(sl)
        db.session.commit()
        return jsonify({'success': True, 'deleted_id': list_id})

    # PUT — update metadata or replace items
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        sl.name = (data.get('name') or '').strip() or sl.name
    if 'target_date' in data:
        td = data.get('target_date')
        if td:
            try:
                sl.target_date = datetime.strptime(td, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'error': 'target_date must be YYYY-MM-DD'}), 400
        else:
            sl.target_date = None
    if 'items' in data and isinstance(data['items'], list):
        # Replace items wholesale
        sl.items.delete()
        for raw in data['items']:
            if isinstance(raw, dict):
                sl.items.append(ShoppingListItem(
                    ingredient=raw.get('ingredient', ''),
                    quantity=str(raw.get('quantity', '')),
                    unit=raw.get('unit', ''),
                    checked=bool(raw.get('checked', False)),
                ))
    db.session.commit()
    return jsonify({'success': True, 'shopping_list': sl.to_dict()})


@app.route('/api/shopping-lists/<int:list_id>/items/<int:item_id>',
           methods=['PATCH', 'DELETE'])
@require_auth
def api_shopping_list_item_detail(list_id, item_id):
    user = request.current_user
    sl = ShoppingList.query.filter_by(id=list_id, user_id=user.id).first()
    if not sl:
        return jsonify({'error': 'Shopping list not found'}), 404
    item = ShoppingListItem.query.filter_by(id=item_id, list_id=list_id).first()
    if not item:
        return jsonify({'error': 'Item not found'}), 404

    if request.method == 'DELETE':
        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True, 'deleted_id': item_id})

    data = request.get_json(silent=True) or {}
    if 'checked' in data:
        item.checked = bool(data['checked'])
    if 'ingredient' in data:
        item.ingredient = (data['ingredient'] or '').strip() or item.ingredient
    if 'quantity' in data:
        item.quantity = str(data['quantity'])
    if 'unit' in data:
        item.unit = data['unit']
    db.session.commit()
    return jsonify({'success': True, 'item': item.to_dict()})


@app.route('/api/shopping-lists/from-recipes', methods=['POST'])
@require_auth
def api_shopping_list_from_recipes():
    """Create a saved shopping list by merging ingredients from recipes.

    Body:
      {
        "recipe_ids": [1, 2, 3],          # required
        "name": "Weekend groceries",       # optional, defaults to a generated name
        "date": "2026-06-07",             # optional target date (YYYY-MM-DD)
        "servings_overrides": {"1": 6},   # optional, see note below
        "preview": false                   # optional, see below
      }

    Default behaviour (documented contract): aggregates/merges the ingredients
    across the given recipes, persists a new ShoppingList for the current user,
    and returns the saved list (HTTP 201).

    Preview mode: pass "preview": true to aggregate ingredients WITHOUT saving.
    Returns { success, items } so the frontend can show a draft before saving.

    NOTE on servings_overrides: per-recipe serving scaling is not yet applied
    during aggregation. The field is accepted (and echoed back) so the client
    contract is stable, but quantities currently reflect each recipe's stored
    servings. Scaling support is tracked as a follow-up.
    """
    data = request.get_json(silent=True) or {}
    user = request.current_user

    recipe_ids = data.get('recipe_ids') or []
    if not isinstance(recipe_ids, list) or not recipe_ids:
        return jsonify({'error': 'recipe_ids array is required'}), 400

    servings_overrides = data.get('servings_overrides') or {}
    if servings_overrides and not isinstance(servings_overrides, dict):
        return jsonify({'error': 'servings_overrides must be an object'}), 400

    aggregated = _aggregate_ingredients_for_list(recipe_ids, user.id)

    # Preview mode: return the merged items without persisting anything.
    if bool(data.get('preview')):
        return jsonify({
            'success': True,
            'preview': True,
            'items': aggregated,
            'servings_overrides': servings_overrides,
        })

    # ── Default: create and persist a saved list ──────────────────────────────
    name = (data.get('name') or '').strip()
    if not name:
        name = f"Shopping list ({len(recipe_ids)} recipe{'s' if len(recipe_ids) != 1 else ''})"

    target_date = None
    target_date_str = data.get('date') or data.get('target_date')
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'date must be YYYY-MM-DD'}), 400

    sl = ShoppingList(user_id=user.id, name=name, target_date=target_date)
    db.session.add(sl)
    db.session.flush()  # assign sl.id

    for item in aggregated:
        sl.items.append(ShoppingListItem(
            ingredient=item['ingredient'],
            quantity=item['quantity'],
            unit=item['unit'],
            checked=False,
            source_recipes=json.dumps(item['sources']),
        ))

    db.session.commit()
    return jsonify({'success': True, 'shopping_list': sl.to_dict()}), 201


# ── Weekly Meal Planner ───────────────────────────────────────────────────────
# A meal plan is a flat collection of entries. One entry = (user, date, slot,
# recipe). Multiple recipes per slot are allowed (e.g. side + main), so the
# unique key includes recipe_id. The frontend groups entries into a 7-day x
# 3-slot grid. Weeks start on Monday.

MEAL_SLOTS = ('breakfast', 'lunch', 'dinner')


class MealPlanEntry(db.Model):
    __tablename__ = 'meal_plan_entries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    slot = db.Column(db.String(20), nullable=False)  # breakfast | lunch | dinner
    position = db.Column(db.Integer, default=0)       # order within a slot
    created_at = db.Column(db.DateTime, default=utcnow)

    recipe = db.relationship('Recipe', lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', 'slot', 'recipe_id',
                            name='uq_meal_plan_entry'),
    )

    def to_dict(self):
        r = self.recipe
        recipe_card = None
        if r is not None:
            recipe_card = {
                'id': r.id,
                'title': r.title,
                'imageurl': r.imageurl,
                'totaltime': r.totaltime or ((r.preptime or 0) + (r.cooktime or 0)),
                'servings': r.servings,
            }
        return {
            'id': self.id,
            'recipe_id': self.recipe_id,
            'date': self.date.isoformat() if self.date else None,
            'slot': self.slot,
            'position': self.position,
            'recipe': recipe_card,
        }


def _parse_date(value, field='date'):
    """Parse a YYYY-MM-DD string into a date, or return (None, error_response)."""
    if not value:
        return None, (jsonify({'error': f'{field} is required (YYYY-MM-DD)'}), 400)
    try:
        return datetime.strptime(value, '%Y-%m-%d').date(), None
    except (ValueError, TypeError):
        return None, (jsonify({'error': f'{field} must be YYYY-MM-DD'}), 400)


def _monday_of(d):
    """Return the Monday (week start) for the week containing date d."""
    return d - timedelta(days=d.weekday())


@app.route('/api/meal-plans', methods=['GET', 'POST'])
@require_auth
def api_meal_plans():
    user = request.current_user

    if request.method == 'GET':
        # ?week_start=YYYY-MM-DD (defaults to current week's Monday).
        ws_str = request.args.get('week_start')
        if ws_str:
            week_start, err = _parse_date(ws_str, 'week_start')
            if err:
                return err
            week_start = _monday_of(week_start)
        else:
            week_start = _monday_of(datetime.now(timezone.utc).date())
        week_end = week_start + timedelta(days=6)

        entries = (
            MealPlanEntry.query
            .filter(
                MealPlanEntry.user_id == user.id,
                MealPlanEntry.date >= week_start,
                MealPlanEntry.date <= week_end,
            )
            .order_by(MealPlanEntry.date.asc(), MealPlanEntry.position.asc())
            .all()
        )
        return jsonify({
            'success': True,
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'entries': [e.to_dict() for e in entries],
        })

    # POST: add a recipe to a (date, slot).
    data = request.get_json(silent=True) or {}
    date_val, err = _parse_date(data.get('date'))
    if err:
        return err
    slot = (data.get('slot') or '').strip().lower()
    if slot not in MEAL_SLOTS:
        return jsonify({'error': f'slot must be one of {list(MEAL_SLOTS)}'}), 400
    recipe_id = data.get('recipe_id')
    if not recipe_id:
        return jsonify({'error': 'recipe_id is required'}), 400

    recipe = Recipe.query.filter_by(id=recipe_id, user_id=user.id).first()
    if recipe is None:
        return jsonify({'error': 'recipe not found'}), 404

    # Idempotent: if this recipe is already in the slot, return it.
    existing = MealPlanEntry.query.filter_by(
        user_id=user.id, date=date_val, slot=slot, recipe_id=recipe_id
    ).first()
    if existing is not None:
        return jsonify({'success': True, 'entry': existing.to_dict()}), 200

    count = MealPlanEntry.query.filter_by(
        user_id=user.id, date=date_val, slot=slot
    ).count()
    entry = MealPlanEntry(
        user_id=user.id, recipe_id=recipe_id, date=date_val,
        slot=slot, position=count,
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({'success': True, 'entry': entry.to_dict()}), 201


@app.route('/api/meal-plans/<int:entry_id>', methods=['DELETE'])
@require_auth
def api_meal_plan_delete(entry_id):
    user = request.current_user
    entry = MealPlanEntry.query.filter_by(id=entry_id, user_id=user.id).first()
    if entry is None:
        return jsonify({'error': 'entry not found'}), 404
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'success': True}), 200


def _copy_entries(user_id, src_entries, date_mapper):
    """Copy a set of entries onto new dates, skipping duplicates.

    date_mapper: callable(old_date) -> new_date.
    Returns the number of entries created.
    """
    created = 0
    for e in src_entries:
        new_date = date_mapper(e.date)
        exists = MealPlanEntry.query.filter_by(
            user_id=user_id, date=new_date, slot=e.slot, recipe_id=e.recipe_id
        ).first()
        if exists is not None:
            continue
        count = MealPlanEntry.query.filter_by(
            user_id=user_id, date=new_date, slot=e.slot
        ).count()
        db.session.add(MealPlanEntry(
            user_id=user_id, recipe_id=e.recipe_id, date=new_date,
            slot=e.slot, position=count,
        ))
        created += 1
    return created


@app.route('/api/meal-plans/copy-day', methods=['POST'])
@require_auth
def api_meal_plan_copy_day():
    user = request.current_user
    data = request.get_json(silent=True) or {}
    from_date, err = _parse_date(data.get('from_date'), 'from_date')
    if err:
        return err
    to_date, err = _parse_date(data.get('to_date'), 'to_date')
    if err:
        return err

    src = MealPlanEntry.query.filter_by(user_id=user.id, date=from_date).all()
    created = _copy_entries(user.id, src, lambda _d: to_date)
    db.session.commit()
    return jsonify({'success': True, 'copied': created}), 200


@app.route('/api/meal-plans/copy-week', methods=['POST'])
@require_auth
def api_meal_plan_copy_week():
    user = request.current_user
    data = request.get_json(silent=True) or {}
    from_ws, err = _parse_date(data.get('from_week_start'), 'from_week_start')
    if err:
        return err
    to_ws, err = _parse_date(data.get('to_week_start'), 'to_week_start')
    if err:
        return err
    from_ws = _monday_of(from_ws)
    to_ws = _monday_of(to_ws)
    offset = (to_ws - from_ws).days

    src = MealPlanEntry.query.filter(
        MealPlanEntry.user_id == user.id,
        MealPlanEntry.date >= from_ws,
        MealPlanEntry.date <= from_ws + timedelta(days=6),
    ).all()
    created = _copy_entries(user.id, src, lambda d: d + timedelta(days=offset))
    db.session.commit()
    return jsonify({'success': True, 'copied': created,
                    'to_week_start': to_ws.isoformat()}), 200


@app.route('/api/meal-plans/shopping-list', methods=['POST'])
@require_auth
def api_meal_plan_shopping_list():
    """Build a shopping list from all recipes planned in a given week."""
    user = request.current_user
    data = request.get_json(silent=True) or {}
    week_start, err = _parse_date(data.get('week_start'), 'week_start')
    if err:
        return err
    week_start = _monday_of(week_start)
    week_end = week_start + timedelta(days=6)

    entries = MealPlanEntry.query.filter(
        MealPlanEntry.user_id == user.id,
        MealPlanEntry.date >= week_start,
        MealPlanEntry.date <= week_end,
    ).all()
    recipe_ids = list({e.recipe_id for e in entries})
    if not recipe_ids:
        return jsonify({'error': 'no recipes planned for this week'}), 400

    aggregated = _aggregate_ingredients_for_list(recipe_ids, user.id)
    name = (data.get('name') or f'Week of {week_start.isoformat()}').strip()
    sl = ShoppingList(user_id=user.id, name=name, target_date=week_start)
    db.session.add(sl)
    db.session.flush()
    for item in aggregated:
        sl.items.append(ShoppingListItem(
            ingredient=item['ingredient'],
            quantity=item['quantity'],
            unit=item['unit'],
            checked=False,
            source_recipes=json.dumps(item['sources']),
        ))
    db.session.commit()
    return jsonify({'success': True, 'shopping_list': sl.to_dict()}), 201


# =============================================================================
# RECIPE ADAPTATION
# -----------------------------------------------------------------------------
# Turns an existing recipe into a variant tailored to a household task:
#   • serving size (2 / 4 / 6)  → scaled ALGORITHMICALLY (free, instant, exact)
#   • dietary / goal presets    → rewritten via OpenAI, then nutrients recomputed
# The endpoint returns a PREVIEW (never persists). A separate /save endpoint
# stores an accepted preview as a NEW recipe linked to the original.
# Presets are multi-select and can be combined in a single request.
# =============================================================================

# Allowed serving targets for the algorithmic scaler.
ADAPT_SERVING_TARGETS = (2, 4, 6)

# LLM-driven presets. `key` is the stable id stored on the recipe and sent by
# the client; `instruction` is the natural-language directive injected into the
# prompt. Order here defines the order they are described to the model.
ADAPT_PRESETS = {
    'lactose_free': {
        'instruction': (
            "Make the recipe LACTOSE-FREE. Replace milk, cream, butter, cheese, "
            "yogurt and other dairy with lactose-free or plant-based equivalents "
            "(e.g. lactose-free milk, plant milk, vegan butter, lactose-free cheese). "
            "Keep flavor and texture as close to the original as possible."
        ),
    },
    'vegetarian': {
        'instruction': (
            "Make the recipe VEGETARIAN. Remove all meat, poultry and fish and "
            "replace them with vegetarian protein sources (legumes, tofu, mushrooms, "
            "eggs, dairy) that fit the dish. Eggs and dairy are allowed."
        ),
    },
    'high_protein': {
        'instruction': (
            "Make the recipe HIGHER IN PROTEIN. Increase protein-rich ingredients "
            "and/or add suitable protein sources without changing the character of "
            "the dish. Adjust other ingredients to keep the recipe balanced."
        ),
    },
    'lower_calorie': {
        'instruction': (
            "Make the recipe LOWER IN CALORIES. Reduce or substitute high-calorie "
            "ingredients (oils, fats, sugar, cream) with lighter alternatives and "
            "lighter cooking methods, while keeping the dish satisfying."
        ),
    },
    'faster': {
        'instruction': (
            "Make the recipe FASTER to cook. Simplify steps, use quicker techniques "
            "or shortcut ingredients, and reduce total time. Keep the result tasty. "
            "Update preptime/cooktime/totaltime to realistic smaller values."
        ),
    },
    'cheaper': {
        'instruction': (
            "Make the recipe CHEAPER. Replace expensive ingredients with affordable, "
            "widely available substitutes that keep the dish recognizable and tasty."
        ),
    },
    'gluten_free': {
        'instruction': (
            "Make the recipe GLUTEN-FREE. Replace wheat flour, breadcrumbs, pasta, "
            "soy sauce and other gluten sources with certified gluten-free "
            "alternatives. Keep texture and taste close to the original."
        ),
    },
    'pantry': {
        # Special preset: requires the `pantry` free-text field from the client.
        # Its instruction is built dynamically in adapt_recipe_fields().
        'instruction': None,
    },
}

# Presets that change the recipe text and therefore require an OpenAI call.
LLM_ADAPT_PRESETS = tuple(ADAPT_PRESETS.keys())


def adapt_recipe_fields(recipe: dict, presets: list, pantry: str = '', target_lang: str = 'ru') -> dict:
    """Rewrite a recipe's text to satisfy one or more dietary/goal presets.

    Sends title/description/ingredients/instructions to the LLM together with the
    combined preset directives and asks for a rewritten recipe in the SAME
    language. Returns a NEW dict (does not mutate input). On any failure or when
    no OpenAI client is configured, returns the original recipe unchanged with
    `adapted=False` so the caller can surface a friendly message.
    """
    presets = [p for p in (presets or []) if p in ADAPT_PRESETS]
    if not presets:
        out = dict(recipe)
        out['adapted'] = False
        return out

    if not (openai_client or openai_api_key):
        logger.info("adapt_recipe_fields: no OpenAI client; skipping adaptation")
        out = dict(recipe)
        out['adapted'] = False
        out['adapt_error'] = 'no_openai_key'
        return out

    lang = (target_lang or recipe.get('language') or 'ru').strip().lower()
    lang_name = LANG_NAMES.get(lang, 'Russian')

    payload = {
        'title': recipe.get('title', ''),
        'description': recipe.get('description', ''),
        'ingredients': [str(x) for x in (recipe.get('ingredients') or []) if str(x).strip()],
        'instructions': [str(x) for x in (recipe.get('instructions') or []) if str(x).strip()],
        'preptime': recipe.get('preptime', 0),
        'cooktime': recipe.get('cooktime', 0),
        'totaltime': recipe.get('totaltime', 0),
        'servings': recipe.get('servings', 4),
    }

    # Build the combined directive list.
    directives = []
    for key in presets:
        if key == 'pantry':
            pantry_clean = (pantry or '').strip()
            if not pantry_clean:
                continue
            directives.append(
                "Adapt the recipe to use mainly what the cook already has at home. "
                "Available ingredients: " + pantry_clean + ". "
                "Prefer these ingredients, minimize what must be bought, and you may "
                "omit or substitute non-essential ingredients accordingly."
            )
        else:
            instr = ADAPT_PRESETS[key]['instruction']
            if instr:
                directives.append(instr)

    if not directives:
        out = dict(recipe)
        out['adapted'] = False
        return out

    directive_text = '\n'.join(f"- {d}" for d in directives)

    prompt = (
        "You are a culinary assistant. Adapt the following recipe according to ALL "
        "of these requirements at once:\n"
        f"{directive_text}\n\n"
        f"Write the adapted recipe in {lang_name}. Keep it realistic and cookable. "
        "Adjust ingredient quantities and instructions consistently with the changes. "
        "Keep the SAME servings count unless a requirement implies otherwise. "
        "Return ONLY valid JSON with exactly these keys: "
        '"title" (string), "description" (string), '
        '"ingredients" (array of strings, each like \"2 cups flour\"), '
        '"instructions" (array of strings), '
        '"preptime" (integer minutes), "cooktime" (integer minutes), '
        '"totaltime" (integer minutes), "servings" (integer), '
        '"summary" (string: one short sentence in ' + lang_name + ' describing what changed).\n\n'
        f"Original recipe JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        if OPENAI_NEW_API and openai_client:
            resp = openai_client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
        elif openai_api_key:
            resp = openai.ChatCompletion.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
        else:
            out = dict(recipe)
            out['adapted'] = False
            out['adapt_error'] = 'no_openai_key'
            return out

        adapted = json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
        logger.error(f"Recipe adaptation parse failed ({presets}): {e}")
        out = dict(recipe)
        out['adapted'] = False
        out['adapt_error'] = 'llm_failed'
        return out
    except Exception as e:
        logger.error(f"Recipe adaptation failed ({presets}): {e}")
        out = dict(recipe)
        out['adapted'] = False
        out['adapt_error'] = 'llm_failed'
        return out

    out = dict(recipe)
    if isinstance(adapted.get('title'), str) and adapted['title'].strip():
        out['title'] = adapted['title'].strip()
    if isinstance(adapted.get('description'), str):
        out['description'] = adapted['description'].strip()
    ai = adapted.get('ingredients')
    if isinstance(ai, list) and ai:
        out['ingredients'] = [str(x).strip() for x in ai if str(x).strip()]
    an = adapted.get('instructions')
    if isinstance(an, list) and an:
        out['instructions'] = [str(x).strip() for x in an if str(x).strip()]
    for k in ('preptime', 'cooktime', 'totaltime', 'servings'):
        try:
            if adapted.get(k) is not None:
                out[k] = int(adapted[k])
        except (TypeError, ValueError):
            pass
    out['language'] = lang
    out['adapted'] = True
    out['adapt_summary'] = adapted.get('summary', '') if isinstance(adapted.get('summary'), str) else ''
    return out


def _recipe_to_plain_dict(recipe) -> dict:
    """Build a plain dict (string arrays) suitable for adaptation/scaling."""
    d = recipe.to_dict(include_relationships=True)
    # to_dict already returns ingredients/instructions as string arrays.
    return d


@app.route('/api/recipes/<int:recipe_id>/adapt', methods=['POST'])
@require_auth
def api_adapt_recipe(recipe_id):
    """Produce an adaptation PREVIEW of a recipe. Does NOT persist anything.

    Body:
      {
        "servings": 2|4|6,            # optional; algorithmic scaling
        "presets": ["vegetarian",...],# optional; LLM dietary/goal presets
        "pantry": "rice, eggs, ...",  # required only when "pantry" preset used
        "lang": "ru"                  # optional; output language for LLM presets
      }
    Returns: { success, adapted, recipe, original, presets, servings,
               summary, recompute_nutrition }
    """
    recipe = Recipe.query.get(recipe_id)
    if recipe is None:
        return jsonify({'success': False, 'error': 'Recipe not found'}), 404
    if recipe.user_id != request.current_user.id:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    data = request.get_json(silent=True) or {}
    presets = data.get('presets') or []
    if not isinstance(presets, list):
        return jsonify({'success': False, 'error': 'presets must be a list'}), 400
    bad = [p for p in presets if p not in ADAPT_PRESETS]
    if bad:
        return jsonify({'success': False, 'error': f'unknown presets: {bad}'}), 400

    servings = data.get('servings')
    if servings is not None:
        try:
            servings = int(servings)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'servings must be an integer'}), 400
        if servings not in ADAPT_SERVING_TARGETS:
            return jsonify({'success': False, 'error': f'servings must be one of {ADAPT_SERVING_TARGETS}'}), 400

    pantry = (data.get('pantry') or '').strip()
    if 'pantry' in presets and not pantry:
        return jsonify({'success': False, 'error': 'pantry text required for pantry preset'}), 400

    if not presets and servings is None:
        return jsonify({'success': False, 'error': 'nothing to adapt: provide presets and/or servings'}), 400

    lang = (data.get('lang') or recipe.language or 'ru').strip().lower()

    base = _recipe_to_plain_dict(recipe)
    work = dict(base)
    adapted_flag = False
    adapt_error = None
    summary = ''

    # 1) LLM dietary/goal presets first (rewrites text).
    llm_presets = [p for p in presets]
    if llm_presets:
        work = adapt_recipe_fields(work, llm_presets, pantry=pantry, target_lang=lang)
        adapted_flag = bool(work.get('adapted'))
        adapt_error = work.get('adapt_error')
        summary = work.get('adapt_summary', '')
        if not adapted_flag and adapt_error:
            # LLM failed / no key: surface error, don't fake a result.
            status = 503 if adapt_error == 'no_openai_key' else 502
            return jsonify({
                'success': False,
                'error': adapt_error,
                'message': ('OpenAI key is not configured on the server'
                            if adapt_error == 'no_openai_key'
                            else 'Adaptation service failed, please try again'),
            }), status

    # 2) Algorithmic serving scaling (exact, free).
    if servings is not None:
        work = scale_recipe(work, servings)
        work['servings'] = servings
        adapted_flag = True

    # 3) Recompute nutrition for the adapted ingredient list.
    recompute = None
    try:
        target_servings = int(work.get('servings') or base.get('servings') or 4)
        recompute = calculate_recipe_nutrition(work.get('ingredients', []), servings=target_servings)
    except Exception as e:
        logger.warning(f"adapt: nutrition recompute failed: {e}")
        recompute = None

    # Assemble preview payload (mirrors to_dict-ish shape the client renders).
    preview = {
        'title': work.get('title', base.get('title')),
        'description': work.get('description', base.get('description')),
        'imageurl': base.get('imageurl'),
        'sourceurl': base.get('sourceurl'),
        'preptime': work.get('preptime', base.get('preptime')),
        'cooktime': work.get('cooktime', base.get('cooktime')),
        'totaltime': work.get('totaltime', base.get('totaltime')),
        'servings': work.get('servings', base.get('servings')),
        'originalservings': base.get('servings'),
        'difficulty': base.get('difficulty'),
        'cuisinetype': base.get('cuisinetype'),
        'cookingmethod': base.get('cookingmethod'),
        'ingredients': work.get('ingredients', base.get('ingredients')),
        'instructions': work.get('instructions', base.get('instructions')),
        'categories': base.get('categories', []),
        'language': work.get('language', base.get('language')),
    }

    return jsonify({
        'success': True,
        'adapted': adapted_flag,
        'recipe': preview,
        'original': {
            'id': recipe.id,
            'title': base.get('title'),
            'servings': base.get('servings'),
            'ingredients': base.get('ingredients'),
            'instructions': base.get('instructions'),
        },
        'presets': presets,
        'servings': servings,
        'summary': summary,
        'recompute_nutrition': recompute,
    })


@app.route('/api/recipes/adapt/save', methods=['POST'])
@require_auth
def api_adapt_recipe_save():
    """Persist an accepted adaptation preview as a NEW recipe.

    Body:
      {
        "adapted_from": <recipe_id>,        # required; source recipe
        "presets": ["vegetarian", ...],     # optional; for lineage badge
        "servings": 2|4|6,                  # optional; for lineage
        "recipe": { ... preview payload ... } # required; from /adapt response
      }
    The source recipe must belong to the current user. Returns the new recipe.
    """
    user = request.current_user
    data = request.get_json(silent=True) or {}

    adapted_from = data.get('adapted_from')
    preview = data.get('recipe') or {}
    presets = data.get('presets') or []
    servings = data.get('servings')

    if not isinstance(preview, dict) or not preview.get('title'):
        return jsonify({'success': False, 'error': 'recipe preview is required'}), 400

    source = None
    if adapted_from is not None:
        source = Recipe.query.get(adapted_from)
        if source is None:
            return jsonify({'success': False, 'error': 'source recipe not found'}), 404
        if source.user_id != user.id:
            return jsonify({'success': False, 'error': 'Access denied'}), 403

    # Build nutrition for the new recipe so cards/labels are populated.
    nutrition_json = '[]'
    per_serving_json = '[]'
    try:
        srv = int(preview.get('servings') or 4)
        nutri = calculate_recipe_nutrition(preview.get('ingredients', []), servings=srv)
        nutrition_json = json.dumps(nutri.get('total', {}))
        per_serving_json = json.dumps(nutri.get('per_serving', {}))
    except Exception as e:
        logger.warning(f"adapt/save: nutrition compute failed: {e}")

    new_recipe = Recipe(
        user_id=user.id,
        title=sanitize_string(preview.get('title')),
        description=sanitize_string(preview.get('description', '')),
        imageurl=sanitize_image_url(preview.get('imageurl', '')),
        sourceurl=sanitize_string(preview.get('sourceurl', '')),
        preptime=sanitize_integer(preview.get('preptime'), 0),
        cooktime=sanitize_integer(preview.get('cooktime'), 0),
        totaltime=sanitize_integer(preview.get('totaltime'), 0),
        servings=sanitize_integer(preview.get('servings', 4), 4),
        originalservings=sanitize_integer(preview.get('originalservings', preview.get('servings', 4)), 4),
        difficulty=sanitize_string(preview.get('difficulty', 'Medium')),
        nutritiondata=nutrition_json,
        nutritionperserving=per_serving_json,
        cuisinetype=sanitize_string(preview.get('cuisinetype', '')),
        cookingmethod=sanitize_string(preview.get('cookingmethod', '')),
        language=sanitize_string(preview.get('language', source.language if source else 'ru')),
        adaptedfrom=source.id if source else None,
        adaptationpresets=json.dumps([p for p in presets if isinstance(p, str)]),
        is_saved=True,
    )
    db.session.add(new_recipe)
    db.session.flush()

    for i, ing_text in enumerate(preview.get('ingredients', [])):
        if isinstance(ing_text, str) and ing_text.strip():
            parsed = clean_ingredient_text(ing_text)
            db.session.add(Ingredient(
                recipe_id=new_recipe.id,
                ingredient=parsed['ingredient'],
                quantity=parsed['quantity'],
                unit=parsed['unit'],
                originalquantity=parsed['quantity'],
                originalunit=parsed['unit'],
                order_index=i,
            ))

    for step_no, instr_text in enumerate(preview.get('instructions', []), start=1):
        if isinstance(instr_text, str) and instr_text.strip():
            db.session.add(Instruction(
                recipe_id=new_recipe.id,
                step_number=step_no,
                instruction=sanitize_string(instr_text),
            ))

    # Carry over categories from the source recipe, if any.
    if source:
        for rc in source.categories:
            if rc.category_id:
                db.session.add(RecipeCategory(recipe_id=new_recipe.id, category_id=rc.category_id))

    db.session.commit()
    db.session.refresh(new_recipe)
    logger.info(f"✅ Saved adapted recipe {new_recipe.id} (from {adapted_from}, presets={presets})")
    return jsonify({'success': True, 'recipe': new_recipe.to_dict()}), 201


# ── Pantry (home inventory) ──────────────────────────────────────────────────
def _pantry_normalised_names(user_id: int) -> dict:
    """Return {normalised_name: PantryItem} for a user's pantry."""
    result = {}
    for it in PantryItem.query.filter_by(user_id=user_id).all():
        key = _normalise_ingredient_name(it.name)
        if key:
            result[key] = it
    return result


def compute_pantry_match(recipe, pantry_names: Optional[dict] = None) -> dict:
    """How many of a recipe's ingredients the user already has at home.

    Matching is by normalised name only. Returns
    {have, total, have_names: [...]}.
    """
    if pantry_names is None:
        pantry_names = _pantry_normalised_names(recipe.user_id) if recipe.user_id else {}
    total = 0
    have = 0
    have_names = []
    seen = set()
    for ing in recipe.ingredients:
        key = _normalise_ingredient_name(ing.ingredient)
        if not key or key in seen:
            continue
        seen.add(key)
        total += 1
        if key in pantry_names:
            have += 1
            have_names.append(ing.ingredient.strip())
    return {'have': have, 'total': total, 'have_names': have_names}


@app.route('/api/pantry', methods=['GET', 'POST'])
@require_auth
def api_pantry():
    user = request.current_user

    if request.method == 'GET':
        items = (PantryItem.query
                 .filter_by(user_id=user.id)
                 .order_by(PantryItem.category.asc(), PantryItem.name.asc())
                 .all())
        return jsonify({
            'success': True,
            'pantry_items': [it.to_dict() for it in items],
        })

    # POST — add a single item
    data = request.get_json(silent=True) or {}
    name = sanitize_string(data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    quantity = sanitize_string(str(data.get('quantity') or '')).strip() or None
    unit = sanitize_string(str(data.get('unit') or '')).strip() or None
    # Dedupe by normalised name (consistent with bulk-add and cook-deduction,
    # which match by normalised name). Adding an item that already exists
    # updates the existing row's quantity/unit instead of creating a duplicate,
    # so the pantry never holds two rows for the same ingredient.
    key = _normalise_ingredient_name(name)
    existing = None
    if key:
        existing = next(
            (it for it in PantryItem.query.filter_by(user_id=user.id).all()
             if _normalise_ingredient_name(it.name) == key),
            None,
        )
    if existing is not None:
        if quantity is not None:
            existing.quantity = quantity
        if unit is not None:
            existing.unit = unit
        db.session.commit()
        return jsonify({'success': True, 'pantry_item': existing.to_dict()}), 200
    item = PantryItem(
        user_id=user.id,
        name=name,
        quantity=quantity,
        unit=unit,
        category=categorize_ingredient(name),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'pantry_item': item.to_dict()}), 201


@app.route('/api/pantry/bulk', methods=['POST'])
@require_auth
def api_pantry_bulk():
    """Bulk-add pantry items. Body: {items: [str | {name,quantity,unit}]}.
    Each item is auto-categorised. Existing items (same normalised name) are
    skipped so the call is idempotent.
    """
    user = request.current_user
    data = request.get_json(silent=True) or {}
    raw_items = data.get('items') or []
    existing = set(_pantry_normalised_names(user.id).keys())
    created = []
    for raw in raw_items:
        if isinstance(raw, str):
            name, quantity, unit = raw.strip(), '', ''
        elif isinstance(raw, dict):
            name = sanitize_string(str(raw.get('name') or '')).strip()
            quantity = sanitize_string(str(raw.get('quantity') or '')).strip()
            unit = sanitize_string(str(raw.get('unit') or '')).strip()
        else:
            continue
        if not name:
            continue
        key = _normalise_ingredient_name(name)
        if not key or key in existing:
            continue
        existing.add(key)
        item = PantryItem(
            user_id=user.id,
            name=name,
            quantity=quantity or None,
            unit=unit or None,
            category=categorize_ingredient(name),
        )
        db.session.add(item)
        created.append(item)
    db.session.commit()
    return jsonify({
        'success': True,
        'created': [it.to_dict() for it in created],
        'created_count': len(created),
    }), 201


@app.route('/api/pantry/<int:item_id>', methods=['PATCH', 'DELETE'])
@require_auth
def api_pantry_item(item_id):
    user = request.current_user
    item = PantryItem.query.filter_by(id=item_id, user_id=user.id).first()
    if not item:
        return jsonify({'error': 'Pantry item not found'}), 404

    if request.method == 'DELETE':
        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True})

    # PATCH
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        new_name = sanitize_string(str(data.get('name') or '')).strip()
        if not new_name:
            return jsonify({'error': 'name cannot be empty'}), 400
        item.name = new_name
        item.category = categorize_ingredient(new_name)
    if 'quantity' in data:
        item.quantity = sanitize_string(str(data.get('quantity') or '')).strip() or None
    if 'unit' in data:
        item.unit = sanitize_string(str(data.get('unit') or '')).strip() or None
    db.session.commit()
    return jsonify({'success': True, 'pantry_item': item.to_dict()})


@app.route('/api/recipes/<int:recipe_id>/cook', methods=['POST'])
@require_auth
def api_recipe_cook(recipe_id):
    """Mark a recipe as cooked and deduct the selected ingredients from pantry.

    Body: {ingredient_names: [str, ...]}. Matching is by normalised name.
    Matched pantry items are removed (we don't track decremental quantities).
    Returns the list of removed pantry item names.
    """
    user = request.current_user
    recipe = Recipe.query.filter_by(id=recipe_id, user_id=user.id).first()
    if not recipe:
        return jsonify({'error': 'Recipe not found'}), 404

    data = request.get_json(silent=True) or {}
    names = data.get('ingredient_names')
    # If no explicit selection, default to all recipe ingredients.
    if not names:
        names = [ing.ingredient for ing in recipe.ingredients]

    wanted = set()
    for n in names:
        key = _normalise_ingredient_name(n)
        if key:
            wanted.add(key)

    removed = []
    for it in PantryItem.query.filter_by(user_id=user.id).all():
        key = _normalise_ingredient_name(it.name)
        if key in wanted:
            removed.append(it.name)
            db.session.delete(it)
    db.session.commit()
    return jsonify({
        'success': True,
        'removed': removed,
        'removed_count': len(removed),
    })


@app.route('/api/recipes/suggest-from-pantry', methods=['GET'])
@require_auth
def api_recipes_suggest_from_pantry():
    """Suggest recipes the user can make from what's in their pantry.

    Returns ALL of the user's recipes, each annotated with a pantry_match
    ({have, total, have_names}) and a match_ratio, sorted by match_ratio
    descending (then by have count, then newest first). Matching is by
    normalised ingredient name only — no quantity comparison (consistent
    with pantry-match v1).

    Optional query params:
      ?limit=<int>   cap the number of recipes returned (default: all)
    """
    user = request.current_user
    pantry_names = _pantry_normalised_names(user.id)

    recipes = (Recipe.query
               .filter_by(user_id=user.id)
               .order_by(Recipe.created_at.desc())
               .all())

    suggestions = []
    for recipe in recipes:
        match = compute_pantry_match(recipe, pantry_names=pantry_names)
        total = match['total']
        ratio = (match['have'] / total) if total else 0.0
        payload = recipe.to_dict(include_relationships=True)
        payload['pantry_match'] = match
        payload['match_ratio'] = round(ratio, 4)
        # Use recipe id as a stable, comparable newest-first tiebreaker
        # (avoids naive/aware datetime comparison issues).
        suggestions.append((ratio, match['have'], recipe.id, payload))

    # Sort: ratio desc, then absolute have count desc, then newest (higher id) first.
    suggestions.sort(
        key=lambda t: (t[0], t[1], t[2]),
        reverse=True,
    )

    ordered = [p for _, _, _, p in suggestions]

    limit = request.args.get('limit', type=int)
    if limit is not None and limit > 0:
        ordered = ordered[:limit]

    return jsonify({
        'success': True,
        'recipes': ordered,
        'pantry_count': len(pantry_names),
    })


# Create database tables and run migrations
# ── OpenAPI / Swagger UI ──────────────────────────────────────────────────────
from openapi_spec import build_openapi_spec as _build_openapi_spec

_OPENAPI_CACHE: Optional[dict] = None


@app.route('/api/openapi.json', methods=['GET'])
def openapi_json():
    """Machine-readable OpenAPI 3.0 spec for the Fresso API.

    Consumers: Swagger UI, codegen for TypeScript/Swift clients, Postman.
    """
    global _OPENAPI_CACHE
    if _OPENAPI_CACHE is None:
        _OPENAPI_CACHE = _build_openapi_spec()
    return jsonify(_OPENAPI_CACHE)


@app.route('/api/docs', methods=['GET'])
def swagger_ui():
    """Interactive API documentation (Swagger UI loaded from CDN)."""
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Fresso API — v1</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui.css">
    <style>
      body { margin: 0; }
      .topbar { display: none; }
      .swagger-ui .info .title { color: #2d6a4f; }
    </style>
  </head>
  <body>
    <div id="swagger"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: '/api/openapi.json',
        dom_id: '#swagger',
        deepLinking: true,
        persistAuthorization: true,
        tryItOutEnabled: true,
        defaultModelsExpandDepth: 1,
        defaultModelExpandDepth: 2,
      });
    </script>
  </body>
</html>""", 200, {'Content-Type': 'text/html; charset=utf-8'}


with app.app_context():
    try:
        db.create_all()
        migrate_database()
        create_default_categories()
        logger.info("Database tables created and migrated successfully")
    except Exception as e:
        logger.error(f"Database creation/migration error: {e}")

if __name__ == '__main__':
    print("🐰 BunnyKitchen AI - COMPLETE Backend starting...")
    print(f"✅ OpenAI API: {'Configured' if openai_api_key else 'Not configured'}")
    print(f"📊 OpenAI API version: {'new' if openai_client else 'legacy' if openai_api_key else 'none'}")
    print("🗄️ Database: Complete schema with all original functionality")
    print("🔗 Unified app compatibility: Enabled")
    print("🚀 Starting server on http://localhost:5001")
    print()
    print("📋 Available endpoints:")
    print("• POST /api/recipes/extract - Extract recipe from URL")
    print("• GET /api/recipes - Get all recipes")
    print("• POST /api/recipes - Save new recipe")
    print("• POST /api/recipes/<id>/scale - Scale recipe servings")
    print("• POST /api/scale-data - Scale recipe data (client-side)")
    print("• POST /api/convert-units - Convert ingredient units")
    print("• GET /api/categories - Get recipe categories")
    print("-" * 50)

    app.run(host='0.0.0.0', port=5001, debug=_debug_mode)
