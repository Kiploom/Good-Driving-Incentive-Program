from flask import Flask, session, render_template, redirect, url_for, flash, request, jsonify, current_app, g
from flask_login import login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy.exc import OperationalError, StatementError
from sqlalchemy.orm import joinedload
import os
from datetime import datetime, timedelta

# Config / extensions
from config import db_config, secret_key, fernet
from .extensions import db, migrate, login_manager, bcrypt
from .sponsor_catalog.routes import bp as sponsor_catalog_bp
from .driver_points_catalog.routes import bp as driver_points_bp
from .cart.routes import bp as cart_bp
from .cart.checkout_routes import bp as checkout_bp
from app.models import Account, Driver, Sponsor
from app.ebay_oauth import init_ebay_oauth

# Blueprints
from .routes.auth import bp as auth_bp
from .routes.users import bp as users_bp
from .routes.about import bp as about_bp
from .routes.session_routes import bp as sessions_bp
from .routes.home import bp as home_bp
from .routes.auth_reset import bp_reset as bp_reset
from .routes.themes import bp as themes_bp
from app.routes import sponsor_routes
from app.routes import driver_routes
from app.routes import admin_routes
from app.routes import driver_env
from app.routes import leaderboard
from app.routes import challenge_routes
from .routes.apply import bp as apply_bp
from app.routes.sponsor_applications import bp as sponsor_apps_bp
from app.routes import product_reports
from app.routes import catalog_detail
from app.routes import orders
from app.routes.support_routes import bp as support_bp
from app.routes.support_ui_routes import bp as support_ui_bp
from app.routes.mobile_api import mobile_bp
from app.routes.account_deactivation import bp as account_deactivation_bp
from app.routes.account_password import bp as account_password_bp

# Optional: Flask-Mail support
from flask_mail import Mail
mail = Mail()

# Performance optimizations
try:
    from flask_compress import Compress
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False

try:
    import orjson
    ORJSON_AVAILABLE = True
except ImportError:
    ORJSON_AVAILABLE = False

from werkzeug.middleware.proxy_fix import ProxyFix


def create_app(config_object="config.Config"):
    app = Flask(__name__)

    # --- Core configuration ---
    app.config['SECRET_KEY'] = secret_key
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+pymysql://{db_config['user']}:{db_config['password']}@"
        f"{db_config['host']}/{db_config['database']}"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Performance optimizations
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
    app.config['JSON_SORT_KEYS'] = False

    # Flask-Compress settings (gzip compression for JSON)
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html',
        'text/css',
        'text/javascript',
        'application/json',
        'application/javascript',
        'text/xml',
        'application/xml',
    ]
    app.config['COMPRESS_LEVEL'] = 6
    app.config['COMPRESS_MIN_SIZE'] = 500

    # Engine / pool tuning
    app.config.update(
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_timeout": 30,
            "connect_args": {"connect_timeout": 10},
        },
    )

    # Mail config - Ethereal Mail for notifications
    app.config['MAIL_SERVER'] = os.getenv('ETHEREAL_MAIL_SERVER')
    app.config['MAIL_PORT'] = int(os.getenv('ETHEREAL_MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('ETHEREAL_MAIL_USE_TLS', 'True') == 'True'
    app.config['MAIL_USERNAME'] = os.getenv('ETHEREAL_MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('ETHEREAL_MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('ETHEREAL_MAIL_DEFAULT_SENDER')
    
    # Keep original MailTrap config for other emails (password resets, etc.)
    app.config['MAILTRAP_SERVER'] = os.getenv('MAIL_SERVER')
    app.config['MAILTRAP_PORT'] = int(os.getenv('MAIL_PORT', 2525))
    app.config['MAILTRAP_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    app.config['MAILTRAP_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAILTRAP_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAILTRAP_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@example.com')

    # --- CSRF configuration (keep existing behavior; make AJAX easy) ---
    # Set CSRF token to expire after 31 days (2678400 seconds) to prevent logout issues
    # when users stay logged in for extended periods
    app.config['WTF_CSRF_TIME_LIMIT'] = 2678400
    app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken', 'X-CSRF-Token']
    app.config['WTF_CSRF_METHODS'] = ['POST', 'PUT', 'PATCH', 'DELETE']
    
    # --- Session configuration ---
    # Set permanent session lifetime to match CSRF token and remember cookie (31 days)
    # This ensures sessions persist for the full 31 days, preventing CSRF token expiration issues
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)

    # --- Init extensions ---
    db.init_app(app)
    # Migrations live at project root (outside flask/) for visibility
    _migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "migrations"))
    migrate.init_app(app, db, directory=_migrations_dir)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)

    # Initialize CSRF protection
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect()
    csrf.init_app(app)

    def _get_csrf_token():
        token = getattr(g, "_csrf_token", None)
        if token is None:
            token = generate_csrf()
            g._csrf_token = token
        return token

    # Exempt mobile API routes from CSRF protection
    csrf.exempt(mobile_bp)

    # Add security headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Configure iframe embedding via environment variable
        # Set ALLOW_IFRAME_ORIGINS to allow specific origins, or '*' to allow all
        # Examples:
        #   ALLOW_IFRAME_ORIGINS=https://gbensoon.com https://www.gbensoon.com
        #   ALLOW_IFRAME_ORIGINS=*
        #   Leave unset to deny all iframe embedding (default)
        allow_iframe_origins = os.getenv('ALLOW_IFRAME_ORIGINS', '').strip()
        
        if allow_iframe_origins:
            # Remove X-Frame-Options when using CSP frame-ancestors (CSP takes precedence)
            # X-Frame-Options is deprecated in favor of CSP frame-ancestors
            response.headers.pop('X-Frame-Options', None)
        else:
            # Default: deny iframe embedding if not configured
            response.headers['X-Frame-Options'] = 'DENY'
        
        # Get S3 bucket domain from config for CSP
        from config import s3_config
        s3_domains = []
        if s3_config.get('bucket_name'):
            bucket_name = s3_config['bucket_name']
            region = s3_config.get('region', 'us-east-1')
            # Add both regional and global S3 endpoints
            s3_domains.extend([
                f"https://{bucket_name}.s3.{region}.amazonaws.com",
                f"https://{bucket_name}.s3.amazonaws.com",
                f"https://*.s3.{region}.amazonaws.com",
                f"https://*.s3.amazonaws.com"
            ])
        
        # Build CSP with S3 domain support
        # Note: img-src already has 'https:' which should allow S3, but we add explicitly for clarity
        # connect-src is needed for fetch/XHR requests
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
            f"img-src 'self' data: https: {' '.join(s3_domains)}",
            f"connect-src 'self' https: {' '.join(s3_domains)}",
            "font-src 'self' https://cdnjs.cloudflare.com"
        ]
        
        # Add frame-ancestors directive if iframe embedding is allowed
        if allow_iframe_origins:
            if allow_iframe_origins == '*':
                csp_directives.append("frame-ancestors *")
            else:
                # Allow specific origins (space-separated list)
                origins = ' '.join(origin.strip() for origin in allow_iframe_origins.split() if origin.strip())
                if origins:
                    csp_directives.append(f"frame-ancestors {origins}")
        
        response.headers['Content-Security-Policy'] = "; ".join(csp_directives) + ";"
        return response

    # Ensure a readable CSRF cookie exists for AJAX/JSON requests (double-submit pattern).
    @app.after_request
    def ensure_csrf_cookie(response):
        try:
            token = _get_csrf_token()
            response.set_cookie(
                "csrf_token",
                token,
                httponly=False,
                samesite="Lax",
                secure=False if app.debug or app.testing else True
            )
        except Exception:
            pass
        return response

    # Expose Fernet
    app.extensions['fernet'] = fernet

    # Make CSRF token function available in templates
    @app.context_processor
    def inject_csrf_token():
        return {'csrf_token': _get_csrf_token}
    
    # Also make the function available directly
    @app.template_global()
    def csrf_token():
        return _get_csrf_token()
    
    # Make avatar helper available in templates
    @app.template_global()
    def get_avatar_display_url(profile_image_url):
        from app.utils.avatar_helper import get_avatar_display_url as helper_func
        return helper_func(profile_image_url)
    
    # Add CSRF error handler for better debugging
    @app.errorhandler(400)
    def handle_csrf_error(e):
        if 'CSRF' in str(e):
            flash('CSRF token is missing or invalid. Please try again.', 'error')
            return redirect(url_for('auth.login_page'))
        return e

    # Flask-Compress
    if COMPRESS_AVAILABLE:
        compress = Compress()
        compress.init_app(app)
        app.logger.info("Flask-Compress enabled for JSON/HTML routes")

    # ProxyFix if behind proxy/CDN
    if os.getenv('BEHIND_PROXY', 'false').lower() == 'true':
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
            x_prefix=1
        )
        app.logger.info("ProxyFix middleware enabled (BEHIND_PROXY=true)")

    # orjson JSON provider
    if ORJSON_AVAILABLE:
        from flask.json.provider import DefaultJSONProvider
        import orjson

        class ORJSONProvider(DefaultJSONProvider):
            def dumps(self, obj, **kwargs):
                return orjson.dumps(obj).decode('utf-8')

        app.json = ORJSONProvider(app)
        app.logger.info("orjson enabled for faster JSON serialization")
    else:
        app.logger.info("orjson not available - using standard json (install with: pip install orjson)")

    # --- Flask-Login user loader ---
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return Account.query.get(user_id)
        except (OperationalError, StatementError):
            db.session.rollback()
            try:
                db.engine.dispose()
            except Exception:
                pass
            return Account.query.get(user_id)

    login_manager.login_view = "auth.login_page"
    
    # Set remember cookie duration to match CSRF token lifetime (31 days)
    login_manager.remember_cookie_duration = timedelta(days=31)
    login_manager.remember_cookie_httponly = True
    login_manager.remember_cookie_secure = False  # Set to True in production with HTTPS

    # --- Example routes ---
    @app.get("/catalog")
    def catalog_home():
        if current_user.is_authenticated and session.get("sponsor_id"):
            return redirect(url_for("sponsor_catalog.index"))
        if current_user.is_authenticated:
            return redirect(url_for("driver_points_catalog.index"))
        return redirect(url_for("home.home_page"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        # ---- CHANGE: ensure DRIVER takes precedence so the driver card is always visible ----
        if session.get("admin_id"):
            role = "admin"
            catalog_url = url_for("admin.admin_account")
        elif session.get("driver_id"):
            role = "driver"
            catalog_url = url_for("driver_points_catalog.index")
        elif session.get("sponsor_id"):
            role = "sponsor"
            catalog_url = url_for("sponsor_catalog.index")
        else:
            role = "unknown"
            catalog_url = None

        # For drivers, fetch their environments
        driver_envs = []
        current_driver_sponsor_id = None
        if role == "driver":
            from app.models import DriverSponsor, Driver
            driver_id = session.get("driver_id")
            if driver_id:
                driver_envs = (
                    DriverSponsor.query
                    .filter_by(DriverID=driver_id)
                    .options(joinedload(DriverSponsor.sponsor))
                    .all()
                )
                current_driver_sponsor_id = session.get("driver_sponsor_id")
        
        return render_template(
            "dashboard.html",
            catalog_url=catalog_url,
            role=role,
            driver_envs=driver_envs,
            current_driver_sponsor_id=current_driver_sponsor_id
        )

    @app.context_processor
    def inject_nav_state():
        # ---- CHANGE: same precedence in the navbar for consistent UI ----
        role = None
        if current_user.is_authenticated:
            if session.get("admin_id"):
                role = "admin"
            elif session.get("driver_id"):
                role = "driver"
            elif session.get("sponsor_id"):
                role = "sponsor"
        return {"nav_role": role}

    @app.context_processor
    def inject_driver_env_state():
        pending = bool(session.get("driver_env_selection_pending"))
        return {"driver_env_pending": pending}

    # Add custom Jinja2 filters
    @app.template_filter('escapejs')
    def escapejs_filter(value):
        if value is None:
            return ''
        return (str(value)
                .replace('\\', '\\\\')
                .replace("'", "\\'")
                .replace('"', '\\"')
                .replace('\n', '\\n')
                .replace('\r', '\\r')
                .replace('\t', '\\t')
                .replace('</', '<\\/'))

    # 🔹 Driver points available to all templates (for navbar badge)
    @app.context_processor
    def inject_driver_points_balance():
        try:
            if current_user.is_authenticated and session.get('driver_id'):
                driver_sponsor_id = session.get('driver_sponsor_id')
                if driver_sponsor_id:
                    from app.models import DriverSponsor
                    env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
                    if env:
                        return {"driver_points_balance": env.PointsBalance}
        except Exception:
            pass
        return {"driver_points_balance": None}

    @app.context_processor
    def inject_sponsor_company_label():
        """
        Ensure sponsor accounts expose their company name in templates and emit
        debug data to help diagnose missing session state.
        """
        if not getattr(current_user, "is_authenticated", False):
            return {}

        # Skip if this is a driver context; the driver injector handles it.
        if session.get("driver_id"):
            return {}

        sponsor_id = session.get("sponsor_id")
        sponsor_company_name = session.get("sponsor_company")
        debug_payload = {
            "sponsor_id": sponsor_id,
            "session_company": sponsor_company_name,
            "resolved_company": sponsor_company_name,
        }

        if sponsor_id and not sponsor_company_name:
            try:
                sponsor = (
                    Sponsor.query.options(joinedload(Sponsor.sponsor_company))
                    .filter(Sponsor.SponsorID == sponsor_id)
                    .first()
                )
            except Exception as exc:
                current_app.logger.exception(
                    "Navbar sponsor lookup failed for sponsor_id=%s", sponsor_id
                )
                debug_payload["lookup_error"] = str(exc)
            else:
                if sponsor and sponsor.sponsor_company:
                    sponsor_company_name = sponsor.sponsor_company.CompanyName
                    session["sponsor_company"] = sponsor_company_name
                    debug_payload["resolved_company"] = sponsor_company_name
                else:
                    debug_payload["resolved_company"] = None

        return {
            "current_sponsor_name": sponsor_company_name,
            "nav_sponsor_debug": debug_payload,
        }

    @app.context_processor
    def inject_driver_env_options():
        """
        Provide driver environment options to all templates so the navbar sponsor switcher mirrors
        the dashboard logic and defaults to the most recent environment the driver has used.
        """
        if not getattr(current_user, "is_authenticated", False):
            return {}

        # Ensure this only runs for driver accounts
        driver_id = session.get("driver_id")
        if not driver_id:
            return {}

        try:
            from app.models import DriverSponsor  # Local import to avoid circular dependency
        except Exception:
            return {}

        try:
            env_query = (
                DriverSponsor.query
                .options(joinedload(DriverSponsor.sponsor))
                .filter(DriverSponsor.DriverID == driver_id)
                .all()
            )
        except Exception:
            return {}

        active_envs = [
            env for env in env_query
            if (env.Status or "").strip().upper() == "ACTIVE"
        ]

        if not active_envs:
            session.pop("driver_sponsor_id", None)
            session.pop("sponsor_id", None)
            session.pop("sponsor_company", None)
            return {
                "driver_env_options": [],
                "driver_env_selected_id": None,
                "current_sponsor_name": session.get("sponsor_company"),
            }

        # Sort environments: active first, then by most recently updated/created
        def _status_score(env):
            return 1 if (env.Status or "").strip().upper() == "ACTIVE" else 0

        def _timestamp(env):
            return env.UpdatedAt or env.CreatedAt or datetime.min

        envs_sorted = sorted(
            active_envs,
            key=lambda env: (_status_score(env), _timestamp(env)),
            reverse=True,
        )

        selected_id = session.get("driver_sponsor_id")
        if selected_id:
            selected_id = str(selected_id)

        # Check ALL environments (not just sorted/active ones) to find the selected one
        # This ensures we find the selected environment even if it's not in the sorted list
        all_envs = env_query  # Use the original query result
        selected_env = None
        
        if selected_id:
            # Try to find the selected environment in all environments
            selected_env = next(
                (env for env in all_envs if str(env.DriverSponsorID) == selected_id),
                None,
            )
            
            if selected_env:
                # Found the selected environment - ensure session values are in sync
                # But only update if they're different to avoid unnecessary session modifications
                if str(selected_env.DriverSponsorID) != session.get("driver_sponsor_id"):
                    session["driver_sponsor_id"] = str(selected_env.DriverSponsorID)
                if str(selected_env.SponsorID) != session.get("sponsor_id"):
                    session["sponsor_id"] = str(selected_env.SponsorID)
                if selected_env.sponsor and selected_env.sponsor.Company != session.get("sponsor_company"):
                    session["sponsor_company"] = selected_env.sponsor.Company
            # If selected_env is None but selected_id exists, don't overwrite - 
            # the session value might be valid but the environment query might have missed it
            # (e.g., due to timing or database issues)
        else:
            # No selection in session - default to the most recent ACTIVE environment
            selected_env = envs_sorted[0] if envs_sorted else None
            if selected_env:
                selected_id = str(selected_env.DriverSponsorID)
                session["driver_sponsor_id"] = selected_id
                session.setdefault("driver_id", str(selected_env.DriverID))
                session["sponsor_id"] = str(selected_env.SponsorID)
                session["sponsor_company"] = (
                    selected_env.sponsor.Company
                    if getattr(selected_env, "sponsor", None) and selected_env.sponsor.Company
                    else None
                )

        options = []
        current_label = None
        for env in envs_sorted:
            status = (env.Status or "").strip().upper()
            label = (
                env.sponsor.Company
                if getattr(env, "sponsor", None) and env.sponsor.Company
                else f"Sponsor #{env.SponsorID}"
            )
            option_id = str(env.DriverSponsorID)
            is_selected = selected_id is not None and option_id == selected_id
            if is_selected:
                current_label = label
            options.append(
                {
                    "id": option_id,
                    "label": label,
                    "status": status,
                    "is_selected": is_selected,
                }
            )

        if not current_label:
            current_label = session.get("sponsor_company")

        return {
            "driver_env_options": options,
            "driver_env_selected_id": selected_id,
            "current_sponsor_name": current_label,
        }

    # --- DB setup ---
    with app.app_context():
        db.create_all()
        try:
            from sqlalchemy import text
            db_name = db.engine.url.database
            # Add ProfileImageURL to Account if missing
            exists_profile = db.session.execute(text(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=:db AND TABLE_NAME='Account' "
                "AND COLUMN_NAME='ProfileImageURL'"
            ), {"db": db_name}).scalar()
            if not exists_profile:
                db.session.execute(text(
                    "ALTER TABLE Account ADD COLUMN ProfileImageURL VARCHAR(255) NULL"
                ))
                db.session.commit()
            exists = db.session.execute(text(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=:db AND TABLE_NAME='Admin' "
                "AND COLUMN_NAME='AlertLoginActivity'"
            ), {"db": db_name}).scalar()
            if not exists:
                db.session.execute(text(
                    "ALTER TABLE Admin ADD COLUMN AlertLoginActivity TINYINT(1) NOT NULL DEFAULT 0"
                ))
                db.session.commit()
        except Exception:
            db.session.rollback()

    # --- Register blueprints ---
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(bp_reset)
    app.register_blueprint(themes_bp)
    app.register_blueprint(sponsor_catalog_bp, url_prefix="/sponsor-catalog")
    app.register_blueprint(driver_points_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(sponsor_routes.bp)
    app.register_blueprint(driver_routes.bp)
    app.register_blueprint(admin_routes.bp)
    app.register_blueprint(driver_env.bp)
    app.register_blueprint(leaderboard.bp)
    app.register_blueprint(apply_bp)
    app.register_blueprint(sponsor_apps_bp)
    app.register_blueprint(product_reports.bp)
    app.register_blueprint(catalog_detail.bp)  # Detail view optimization
    app.register_blueprint(orders.bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(support_ui_bp)
    app.register_blueprint(mobile_bp)
    app.register_blueprint(challenge_routes.bp)
    app.register_blueprint(account_deactivation_bp)
    app.register_blueprint(account_password_bp)

    # --- CLI commands ---
    from app.cli_commands import create_admin_cmd
    app.cli.add_command(create_admin_cmd)

    # --- Update session last-activity globally on authenticated requests ---
    from flask import session as flask_session, request
    from app.services.session_management_service import SessionManagementService
    from app.tasks.session_cleanup import _notify_refund_expirations

    def _recreate_session_for_authenticated_user(flask_session, current_user, request):
        """Restore role session data (admin_id, driver_id, sponsor_id, driver_sponsor_id) when recreating a session."""
        from app.routes.auth import _set_role_session
        _set_role_session(current_user)
        # Restore driver environment if driver has single active env
        from app.models import Driver, DriverSponsor
        driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
        if driver and not flask_session.get('driver_sponsor_id'):
            envs = DriverSponsor.query.filter_by(DriverID=driver.DriverID, Status="ACTIVE").all()
            if len(envs) == 1:
                flask_session['driver_sponsor_id'] = str(envs[0].DriverSponsorID)
                flask_session['sponsor_id'] = str(envs[0].SponsorID)
                flask_session['driver_env_selection_pending'] = False
                if envs[0].sponsor:
                    flask_session['sponsor_company'] = envs[0].sponsor.Company
            elif len(envs) > 1:
                flask_session.pop('driver_sponsor_id', None)
                flask_session['driver_env_selection_pending'] = True
            else:
                flask_session.pop('driver_sponsor_id', None)
                flask_session['driver_env_selection_pending'] = False

    @app.before_request
    def _enforce_active_session_and_touch():
        ep = (getattr(request, 'endpoint', None) or '')
        path = request.path or ''
        
        # Skip static files and auth routes
        if ep.startswith('static') or ep.startswith('auth.'):
            return None
        
        # Check if this is a mobile API endpoint
        is_mobile_api = path.startswith('/api/mobile/')
        
        # Log session state for mobile API requests to debug sponsor switching
        if is_mobile_api:
            current_app.logger.info(f"before_request: Mobile API request to {path}")
            current_app.logger.info(f"before_request: Session driver_sponsor_id: {flask_session.get('driver_sponsor_id')}")
            current_app.logger.info(f"before_request: Session sponsor_id: {flask_session.get('sponsor_id')}")
            current_app.logger.info(f"before_request: Session keys: {list(flask_session.keys())}")
            current_app.logger.info(f"before_request: Session modified: {flask_session.modified}")

        if getattr(current_user, 'is_authenticated', False):
            # Set session as permanent for authenticated users to match CSRF token lifetime
            # This ensures the session persists for 31 days, preventing CSRF token expiration
            flask_session.permanent = True
            
            token = flask_session.get('session_token')
            if not token:
                # Session token missing (e.g. Flask session expired but Flask-Login remember cookie still valid).
                # Recreate session for both web and mobile - user is still authenticated.
                try:
                    _recreate_session_for_authenticated_user(flask_session, current_user, request)
                    SessionManagementService.create_session(current_user.AccountID, request)
                except Exception:
                    if is_mobile_api:
                        pass  # Let endpoint handle auth
                    else:
                        return redirect(url_for('auth.logout_api'))
            else:
                # Validate existing session token
                is_valid, _ = SessionManagementService.validate_session(token)
                if not is_valid:
                    SessionManagementService.revoke_session(token)
                    # Session expired/inactive (24h expiry or 30min inactivity) but user still authenticated.
                    # Recreate session for both web and mobile instead of forcing logout.
                    try:
                        _recreate_session_for_authenticated_user(flask_session, current_user, request)
                        SessionManagementService.create_session(current_user.AccountID, request)
                    except Exception:
                        if is_mobile_api:
                            return jsonify({"success": False, "message": "Session expired"}), 401
                        else:
                            return redirect(url_for('auth.logout_api'))

            # Enforce account status on every authenticated request
            try:
                status_code = (getattr(current_user, 'Status', '') or '').upper()
                if status_code == 'I':
                    if is_mobile_api:
                        return jsonify({"success": False, "message": "Account deactivated"}), 403
                    return redirect(url_for('auth.account_deactivated'))
                if status_code == 'H':
                    if is_mobile_api:
                        return jsonify({"success": False, "message": "Account archived"}), 403
                    return redirect(url_for('auth.account_archived'))
            except Exception:
                pass

            # Update session activity (get token again in case it was just created)
            token = flask_session.get('session_token')
            if token:
                SessionManagementService.update_session_activity(token)

        # Light-weight periodic task trigger (best-effort) – run every ~5 minutes
        try:
            last_run = session.get('_refund_notify_last_run')
        except Exception:
            last_run = None
        try:
            from datetime import datetime, timedelta
            now_ts = datetime.utcnow()
            should_run = False
            if not last_run:
                should_run = True
            else:
                # Parse stored ISO string
                from datetime import datetime as _dt
                try:
                    lr = _dt.fromisoformat(last_run)
                except Exception:
                    lr = None
                if not lr or (now_ts - lr) >= timedelta(minutes=5):
                    should_run = True
            if should_run:
                session['_refund_notify_last_run'] = now_ts.isoformat()
                _notify_refund_expirations(app)
        except Exception:
            pass

    # Initialize eBay OAuth auto-refresh
    init_ebay_oauth(app)

    return app
