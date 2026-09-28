"""Shared settings. Environment-specific values come from .env (see .env.example)."""
from pathlib import Path

import environ
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Public base URL, used for canonical/OG/sitemaps (no trailing slash).
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")

INSTALLED_APPS = [
    "unfold",  # admin theme; must come before django.contrib.admin
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "mptt",
    "tinymce",
    "apps.core",
    "apps.seo",
    "apps.pages",
    "apps.blog",
    "apps.news",
    "apps.courses",
    "apps.navigation",
    "apps.catalog",
    "apps.mmc",
    "apps.cart",
    "apps.orders",
    "apps.checkout",
    "apps.contact",
    "apps.exampapers",
    "apps.search",
    "apps.emails",
    "apps.wpimport",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.minify.HtmlMinifyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.core.middleware.RedirectMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.cart.middleware.WooCommerceCompatMiddleware",
    "apps.core.middleware.NotFoundLogMiddleware",
]

ROOT_URLCONF = "sst.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
                "apps.cart.context_processors.cart",
            ],
            "builtins": ["apps.core.templatetags.wp"],
        },
    },
]

WSGI_APPLICATION = "sst.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="mysql://root:@127.0.0.1:3306/sst_django"),
}
if env("DATABASE_ENGINE", default=""):
    DATABASES["default"]["ENGINE"] = env("DATABASE_ENGINE")
DATABASES["default"].setdefault("OPTIONS", {}).update(
    {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"}
)
# Source WordPress database, only used by the wp_import_* commands.
WP_DATABASE_URL = env("WP_DATABASE_URL", default="mysql://root:@127.0.0.1:3306/sst")
if WP_DATABASE_URL:
    DATABASES["wordpress"] = env.db_url_config(WP_DATABASE_URL)
    DATABASES["wordpress"].setdefault("OPTIONS", {})["charset"] = "utf8mb4"
    if env("DATABASE_ENGINE", default=""):
        DATABASES["wordpress"]["ENGINE"] = env("DATABASE_ENGINE")
    # Tests must never create/drop a database on the WordPress server.
    DATABASES["wordpress"]["TEST"] = {"MIRROR": "default"}
WP_TABLE_PREFIX = env("WP_TABLE_PREFIX", default="wp_")
WP_ROOT = env("WP_ROOT", default=str(BASE_DIR.parent))
WP_PHP_BIN = env("WP_PHP_BIN", default="C:/xampp/php/php.exe")
# URLs the WP content was published under; rewritten to site-relative on import.
WP_OLD_URLS = env.list(
    "WP_OLD_URLS",
    default=["http://localhost/sst", "https://sstcourses.co.uk", "https://www.sstcourses.co.uk", "http://sstcourses.co.uk"],
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True
APPEND_SLASH = True

STATIC_URL = "/static/"
STATIC_ROOT = env("STATIC_ROOT", default=str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]

# Imported uploads keep their WordPress URLs.
MEDIA_URL = "/wp-content/uploads/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 48

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": env("CACHE_DIR", default=str(BASE_DIR / ".cache")),
    }
}

# Email: console locally, Brevo HTTP API in production (SMTP ports are blocked on the host).
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
BREVO_API_KEY = env("BREVO_API_KEY", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Site Safety Training <noreply@sstcourses.co.uk>")
ORDER_ADMIN_EMAILS = env.list("ORDER_ADMIN_EMAILS", default=[])
# Contact Form 7 reCAPTCHA v3 secret; empty skips verification (the site key is in the form markup).
RECAPTCHA_SECRET_KEY = env("RECAPTCHA_SECRET_KEY", default="")

# MMC (ManageMyCourses). Secrets only ever come from the environment.
MMC_API_BASE = env("MMC_API_BASE", default="https://targetzero.managemycourses.co.uk/api/v1")
MMC_CLIENT_ID = env("MMC_CLIENT_ID", default="")
MMC_CLIENT_SECRET = env("MMC_CLIENT_SECRET", default="")
MMC_WEBHOOK_SECRET = env("MMC_WEBHOOK_SECRET", default="")

STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

GA4_MEASUREMENT_ID = env("GA4_MEASUREMENT_ID", default="")
GOOGLE_SITE_VERIFICATION = env("GOOGLE_SITE_VERIFICATION", default="F8GtZx6rzWAjI4FL-9zstMgZSmvkinQJmV8tCbv0tZg")

TINYMCE_DEFAULT_CONFIG = {
    "height": 500,
    "menubar": "edit view insert format table",
    "plugins": "link image lists table code autolink media",
    "toolbar": "undo redo | blocks | bold italic | alignleft aligncenter alignright | bullist numlist | link image | code",
    "relative_urls": False,
    "remove_script_host": True,
    "convert_urls": True,
    "promotion": False,
    "branding": False,
}



# The admin is the only login; Unfold's login form doesn't post a "next" field.
LOGIN_REDIRECT_URL = "/admin/"


def _nav(title, icon, model):
    """Sidebar link to a model's changelist, shown only to users who can view it."""
    app, name = model.split(".")
    return {"title": title, "icon": icon, "link": reverse_lazy(f"admin:{app}_{name}_changelist"),
            "permission": lambda request: request.user.has_perm(f"{app}.view_{name}")}


# Admin theme (django-unfold). Icons are Material Symbols names.
UNFOLD = {
    "SITE_TITLE": "SST admin",
    "SITE_HEADER": "Site Safety Training",
    "SITE_SUBHEADER": "Website administration",
    "SITE_SYMBOL": "health_and_safety",
    "SITE_URL": "/",
    "ENVIRONMENT": "apps.core.admin_utils.environment_callback",
    "DASHBOARD_CALLBACK": "apps.core.admin_dashboard.dashboard_callback",
    "COLORS": {
        # Tailwind "sky", close to the site's #50b5fe accent.
        "primary": {
            "50": "oklch(97.7% .013 236.62)",
            "100": "oklch(95.1% .026 236.824)",
            "200": "oklch(90.1% .058 230.902)",
            "300": "oklch(82.8% .111 230.318)",
            "400": "oklch(74.6% .16 232.661)",
            "500": "oklch(68.5% .169 237.323)",
            "600": "oklch(58.8% .158 241.966)",
            "700": "oklch(50% .134 242.749)",
            "800": "oklch(44.3% .11 240.79)",
            "900": "oklch(39.1% .09 240.876)",
            "950": "oklch(29.3% .066 243.157)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "command_search": True,
        "show_all_applications": True,
        "navigation": [
            {"items": [{"title": "Dashboard", "icon": "dashboard", "link": reverse_lazy("admin:index")}]},
            {"title": "Orders", "items": [
                _nav("Orders", "receipt_long", "orders.order"),
                _nav("Delegates", "groups", "orders.delegate"),
                _nav("MMC bookings", "event_available", "orders.mmcbooking"),
                _nav("Coupons", "confirmation_number", "cart.coupon"),
            ]},
            {"title": "Shop", "items": [
                _nav("Products", "inventory_2", "catalog.product"),
                _nav("Product categories", "category", "catalog.productcategory"),
                _nav("Product tags", "sell", "catalog.producttag"),
                _nav("Venues", "location_on", "catalog.venue"),
                _nav("Deleted products", "delete_history", "catalog.deletedproduct"),
            ]},
            {"title": "Content", "items": [
                _nav("Pages", "description", "pages.page"),
                _nav("Blog posts", "article", "blog.post"),
                _nav("News", "newspaper", "news.news"),
                _nav("Media", "perm_media", "core.media"),
                _nav("Exam papers", "quiz", "exampapers.exampaper"),
            ]},
            {"title": "Courses", "collapsible": True, "items": [
                _nav("NEBOSH courses", "school", "courses.neboshcourse"),
                _nav("Safety courses", "health_and_safety", "courses.safetycourse"),
                _nav("NEBOSH categories", "folder", "courses.neboshcourseterm"),
                _nav("Safety categories", "folder", "courses.safetycourseterm"),
            ]},
            {"title": "Taxonomies", "collapsible": True, "items": [
                _nav("Blog categories", "folder", "blog.category"),
                _nav("Blog tags", "sell", "blog.tag"),
                _nav("News categories", "folder", "news.newscategory"),
                _nav("Authors", "badge", "blog.authorprofile"),
                _nav("Exam paper options", "tune", "exampapers.dropdownoption"),
            ]},
            {"title": "Forms", "items": [
                _nav("Submissions", "inbox", "contact.submission"),
                _nav("Contact forms", "contact_mail", "contact.contactform"),
            ]},
            {"title": "MMC integration", "collapsible": True, "items": [
                _nav("MMC settings", "settings_ethernet", "mmc.mmcsettings"),
                _nav("Sync runs", "sync", "mmc.syncrun"),
                _nav("Logs", "terminal", "mmc.mmclog"),
                _nav("Webhook events", "webhook", "mmc.webhookevent"),
            ]},
            {"title": "Site", "collapsible": True, "items": [
                _nav("Site options", "settings", "core.siteoptions"),
                _nav("Menus", "menu", "navigation.menu"),
                _nav("Menu items", "list", "navigation.menuitem"),
                _nav("Redirects", "alt_route", "core.redirect"),
                _nav("404 log", "error", "core.notfoundlog"),
            ]},
            {"title": "Users", "collapsible": True, "items": [
                _nav("Users", "person", "auth.user"),
                _nav("Groups", "group", "auth.group"),
            ]},
        ],
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"apps": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")}},
}
DATABASE_ROUTERS = ["sst.db_router.WordPressRouter"]
