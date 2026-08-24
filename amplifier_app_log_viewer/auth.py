"""Authentication for amplifier-log-viewer.

Single-user PAM/password gate, required on EVERY request from every origin --
no localhost bypass (muxplex shipped one and had to remove it as
GHSA-7c6r-fvrh-9qp4: a userspace proxy re-originates connections as
127.0.0.1, so "looks local" never proves "is local"). Frictionless local use
comes from logging in once and keeping a signed, long-lived session cookie.

``request.remote_addr``, ``X-Forwarded-For``, ``X-Forwarded-Proto`` MUST NOT
appear in any authorization decision anywhere in this module.
"""

import base64
import binascii
import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote, urlsplit

from flask import (
    Blueprint,
    Flask,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
)
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

CONFIG_DIR_NAME = "amplifier-log-viewer"
COOKIE_NAME = "amplifier_log_viewer_session"
DEFAULT_SESSION_TTL = 604800  # 7 days
ENV_PREFIX = "AMPLIFIER_LOG_VIEWER_"
_COOKIE_PAYLOAD = "amplifier-log-viewer-session"


@dataclass(frozen=True)
class AuthConfig:
    """Resolved auth config. ttl_seconds=0 -> browser-session cookie.
    password only applies in "password" mode. behind_tls_proxy is an
    operator assertion (see ``_should_mark_secure``), never header-derived.
    base_path scopes the cookie Path so a subpath deployment doesn't leak it.
    """

    mode: str
    secret: str
    ttl_seconds: int
    password: str = ""
    behind_tls_proxy: bool = False
    base_path: str = ""


def config_dir() -> Path:
    """~/.config/amplifier-log-viewer, created mode 0700.

    XDG_CONFIG_HOME is intentionally not consulted -- out of scope.
    """
    d = Path.home() / ".config" / CONFIG_DIR_NAME
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkdir(exist_ok=True) does NOT chmod a pre-existing dir, so tighten
    # unconditionally in case it was created earlier with looser perms.
    os.chmod(d, 0o700)
    return d


def secret_path() -> Path:
    return config_dir() / "secret"


def password_path() -> Path:
    return config_dir() / "password"


def _persist_once(path: Path, value_factory: Callable[[], str]) -> str:
    """Create *path* atomically at 0600 (O_CREAT|O_EXCL: never briefly
    world-readable; a losing racer re-reads the winner's value)."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    config_dir()
    value = value_factory()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    return value


def load_or_create_secret() -> str:
    """Return the persisted signing secret, creating it on first use."""
    return _persist_once(secret_path(), lambda: secrets.token_urlsafe(32))


def load_password() -> str | None:
    """Read password file, stripped. None if absent."""
    p = password_path()
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def generate_and_save_password() -> str:
    """secrets.token_urlsafe(20), persisted 0600, returned."""
    return _persist_once(password_path(), lambda: secrets.token_urlsafe(20))


def _env(name: str) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}")


def pam_available() -> bool:
    """True iff the python-pam module is importable."""
    try:
        import pam  # noqa: F401

        return True
    except ImportError:
        return False


def resolve_auth_config(
    mode: str | None = None,
    ttl_seconds: int | None = None,
    behind_tls_proxy: bool = False,
) -> AuthConfig:
    """Resolve the effective AuthConfig: argument > env var > default."""
    resolved_mode = mode or _env("AUTH")
    if resolved_mode:
        resolved_mode = resolved_mode.lower()
        if resolved_mode not in ("pam", "password"):
            raise ValueError(
                f"Invalid auth mode {resolved_mode!r}; must be 'pam' or 'password'"
            )
        if resolved_mode == "pam" and not pam_available():
            raise ValueError(
                "auth mode 'pam' was explicitly requested but the 'pam' module is not "
                "importable on this host. Install python-pam, or pass --auth password."
            )
    else:
        resolved_mode = "pam" if pam_available() else "password"

    if ttl_seconds is not None:
        resolved_ttl = ttl_seconds
    else:
        env_ttl = _env("SESSION_TTL")
        resolved_ttl = int(env_ttl) if env_ttl is not None else DEFAULT_SESSION_TTL
    if resolved_ttl < 0:
        raise ValueError(f"session TTL must be >= 0, got {resolved_ttl}")

    resolved_behind_tls_proxy = behind_tls_proxy or (
        _env("BEHIND_TLS_PROXY") or ""
    ).lower() in (
        "1",
        "true",
        "yes",
    )

    password = ""
    if resolved_mode == "password":
        password = _env("PASSWORD") or load_password()
        if password is None:
            password = generate_and_save_password()
            print(
                f"Generated password for amplifier-log-viewer: {password}\nSaved to: {password_path()}"
            )

    return AuthConfig(
        mode=resolved_mode,
        secret=load_or_create_secret(),
        ttl_seconds=resolved_ttl,
        password=password,
        behind_tls_proxy=resolved_behind_tls_proxy,
    )


def create_session_cookie(secret: str) -> str:
    return TimestampSigner(secret).sign(_COOKIE_PAYLOAD).decode()


def verify_session_cookie(secret: str, cookie: str, ttl_seconds: int) -> bool:
    """True iff signature valid and (when ttl>0) not expired.

    ttl_seconds == 0 means "browser-session cookie": no server-side expiry.
    """
    try:
        TimestampSigner(secret).unsign(
            cookie, max_age=ttl_seconds if ttl_seconds > 0 else None
        )
        return True
    except (BadSignature, SignatureExpired):
        return False


# -- PAM authentication -------------------------------------------------


def authenticate_pam(username: str, password: str) -> bool:
    """PAM auth, restricted to the process owner. The username gate runs
    BEFORE authenticate() -- policy, and the precondition that lets
    unprivileged PAM work at all (unix_chkpwd is setgid `shadow`)."""
    import pwd

    import pam as pam_mod

    running_user = pwd.getpwuid(os.getuid()).pw_name
    if username != running_user:
        return False

    authenticate = getattr(pam_mod, "authenticate", None)
    if authenticate is not None:
        return bool(authenticate(username, password, service="login"))
    return bool(pam_mod.pam().authenticate(username, password, service="login"))


def expected_username(cfg: AuthConfig) -> str:
    """Running process owner in pam mode, "" in password mode."""
    if cfg.mode != "pam":
        return ""
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


def check_credentials(cfg: AuthConfig, username: str, password: str) -> bool:
    if cfg.mode == "pam":
        return authenticate_pam(username, password)
    return hmac.compare_digest(password, cfg.password)


# -- ?next= redirect validation -------------------------------------------


def validate_next_path(next_value: str | None) -> str:
    """Validate a client ``?next=`` redirect target. Sole guard against an
    open redirect off /login -- fails CLOSED to "/". Do not loosen a clause."""
    if not next_value or not isinstance(next_value, str):
        return "/"
    if any(ord(c) < 0x20 for c in next_value):
        return "/"
    if "\\" in next_value:
        return "/"
    if not next_value.startswith("/") or next_value.startswith("//"):
        return "/"
    lowered = next_value.lower()
    if "://" in lowered:
        return "/"
    for scheme in ("javascript:", "data:", "http:", "https:", "vbscript:", "file:"):
        if scheme in lowered:
            return "/"
    parsed = urlsplit(next_value)
    if parsed.scheme or parsed.netloc:
        return "/"
    if ".." in parsed.path.split("/"):
        return "/"
    return next_value


def build_login_redirect_url(base_path: str, next_value: str | None) -> str:
    """{base_path}/login?next=<target>. Omitted only when *next_value* is
    falsy; otherwise always encoded (even bare "/") so a blocked request at
    the app's own root still round-trips with an explicit `next=%2F`."""
    login = f"{base_path}/login"
    if not next_value:
        return login
    safe = validate_next_path(next_value)
    return f"{login}?next={quote(safe, safe='')}"


# -- The gate -------------------------------------------------------------

auth_bp = Blueprint("auth", __name__)

# Both "auth.login" (GET) and "auth.login_post" (POST) must be exempt: they
# are two distinct endpoints bound to the same "/login" URL. Omitting
# "auth.login_post" would make submitting the login form itself require a
# credential -- self-defeating.
_EXEMPT_ENDPOINTS = frozenset(
    {"auth.login", "auth.login_post", "auth.logout", "auth.mode", "static"}
)


def _wants_json(base_path: str) -> bool:
    """True for machine clients that must get a 401, not a redirect.

    Path prefix is the deterministic signal (every data endpoint lives under
    {base_path}/api/) -- an Accept-only test would send our own fetch()
    poller a 302 it follows silently to the login page as if it were JSON.
    """
    return request.path.startswith(
        f"{base_path}/api/"
    ) or "application/json" in request.headers.get("Accept", "")


def install_auth(app: Flask, cfg: AuthConfig, base_path: str = "") -> None:
    """Register the auth gate and the auth blueprint on *app*."""
    cfg = replace(cfg, base_path=base_path)
    app.config["AUTH_CONFIG"] = cfg
    app.register_blueprint(auth_bp, url_prefix=base_path or None)

    @app.before_request
    def _auth_gate():
        return _check_request(cfg)

    @app.after_request
    def _security_headers(resp):
        # Anti-clickjacking: this app is never meant to be framed. Both headers
        # are set -- X-Frame-Options for older agents, CSP frame-ancestors for
        # current ones.
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return resp


def _check_request(cfg: AuthConfig):
    """Ordered gate. Returns None to proceed, or a Response to short-circuit."""

    # 1. Exempt endpoints (login page, auth endpoints, real static assets).
    #    Endpoint-matched, not path-matched -- nothing else can impersonate
    #    them (this is what closes the muxplex probe.js CVE class).
    if request.endpoint in _EXEMPT_ENDPOINTS:
        return None

    # 2. Valid signed session cookie -- the common path after one login.
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and verify_session_cookie(cfg.secret, cookie, cfg.ttl_seconds):
        return None

    # 3. HTTP Basic (curl/scripts). A presented-but-wrong credential is a
    #    terminal 401 -- must not fall through to the browser redirect, or a
    #    script would see a 302 to a 200 login page and read that as success.
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode()
        except (binascii.Error, UnicodeDecodeError):
            return jsonify({"error": "Invalid credentials"}), 401
        username, _, pw = decoded.partition(":")
        if check_credentials(cfg, username, pw):
            return None
        return jsonify({"error": "Invalid credentials"}), 401

    # 4. No credential at all.
    if _wants_json(cfg.base_path):
        return jsonify({"error": "Authentication required"}), 401
    requested = request.path
    if request.query_string:
        requested = f"{requested}?{request.query_string.decode()}"
    return redirect(build_login_redirect_url(cfg.base_path, requested), code=302)


def _should_mark_secure(cfg: AuthConfig) -> bool:
    """Cookie Secure flag: real TLS or an operator's --behind-tls-proxy
    assertion. X-Forwarded-Proto is deliberately NOT consulted -- it's
    attacker-supplied and would let a plaintext client set its own flag."""
    return request.is_secure or cfg.behind_tls_proxy


# -- Auth endpoints -------------------------------------------------------


@auth_bp.route("/login", methods=["GET"])
def login():
    """Render the login form."""
    cfg = current_app.config["AUTH_CONFIG"]
    return render_template(
        "login.html",
        mode=cfg.mode,
        expected_username=expected_username(cfg),
        next=validate_next_path(request.args.get("next")),
        error=request.args.get("error") == "1",
    )


@auth_bp.route("/login", methods=["POST"])
def login_post():
    """Validate credentials; on success set the cookie and 303 to `next`.

    303 (not 302) so the browser converts the POST into a GET on the target.
    On failure, redirect back to /login?error=1 preserving `next`.
    """
    cfg = current_app.config["AUTH_CONFIG"]
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    raw_next = request.form.get("next", "")

    if not check_credentials(cfg, username, password):
        url = f"{cfg.base_path}/login?error=1"
        safe = validate_next_path(raw_next)
        if safe != "/":
            url += f"&next={quote(safe, safe='')}"
        return redirect(url, code=303)

    safe = validate_next_path(raw_next)
    target = safe if safe != "/" else (cfg.base_path or "/")
    resp = redirect(target, code=303)
    resp.set_cookie(
        COOKIE_NAME,
        create_session_cookie(cfg.secret),
        httponly=True,
        samesite="Strict",
        secure=_should_mark_secure(cfg),
        max_age=cfg.ttl_seconds if cfg.ttl_seconds > 0 else None,
        path=cfg.base_path or "/",
    )
    return resp


@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    # POST-only: logout is state-changing, so a GET would be CSRF-triggerable
    # via <img src=".../auth/logout">. The endpoint stays in the auth-exempt
    # set (auth.logout) so an expired session can still clear itself.
    cfg = current_app.config["AUTH_CONFIG"]
    resp = redirect(f"{cfg.base_path}/login", code=303)
    resp.delete_cookie(COOKIE_NAME, path=cfg.base_path or "/")
    return resp


@auth_bp.route("/auth/mode")
def mode():
    """{"mode": "pam"|"password", "user": "<expected username>"}"""
    cfg = current_app.config["AUTH_CONFIG"]
    return jsonify({"mode": cfg.mode, "user": expected_username(cfg)})
