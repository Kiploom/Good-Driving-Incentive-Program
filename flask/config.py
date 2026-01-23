import os
from dotenv import load_dotenv, find_dotenv
from cryptography.fernet import Fernet

# Load .env file in development
env_path = find_dotenv()
load_dotenv(env_path)

# -----------------------------
# Database config
# -----------------------------
db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", "3306")),
}

# -----------------------------
# eBay config (legacy dict style)
# -----------------------------
ebay_config = {
    "client_id": os.getenv("EBAY_CLIENT_ID"),
    "client_secret": os.getenv("EBAY_CLIENT_SECRET"),
    "oauth_token": os.getenv("EBAY_OAUTH_TOKEN"),
    "env": os.getenv("EBAY_ENV"),
    "provider": os.getenv("EBAY_PROVIDER"),
    "marketplace_id": os.getenv("EBAY_MARKETPLACE_ID"),
}

# -----------------------------
# Secret key for sessions
# -----------------------------
secret_key = os.getenv("SECRET_KEY")

# -----------------------------
# Encryption key / Fernet
# -----------------------------
FERNET_KEY = os.getenv("ENCRYPTION_KEY")
if not FERNET_KEY:
    raise RuntimeError(
        "ENCRYPTION_KEY is not set in your environment or .env file."
    )
fernet = Fernet(FERNET_KEY)

# -----------------------------
# Email config
# -----------------------------
email_config = {
    "server": os.getenv("ETHEREAL_MAIL_SERVER", "smtp.ethereal.email"),
    "port": int(os.getenv("ETHEREAL_MAIL_PORT", "587")),
    "use_tls": os.getenv("ETHEREAL_MAIL_USE_TLS", "True") == "True",
    "username": os.getenv("ETHEREAL_MAIL_USERNAME"),
    "password": os.getenv("ETHEREAL_MAIL_PASSWORD"),
    "default_sender": os.getenv("ETHEREAL_MAIL_DEFAULT_SENDER"),
}

# -----------------------------
# AWS S3 config for profile pictures
# -----------------------------
s3_config = {
    "region": os.getenv("AWS_REGION", "us-east-1"),
    "bucket_name": os.getenv("AWS_S3_BUCKET_NAME"),
    "bucket_prefix_avatars": os.getenv("AWS_S3_BUCKET_PREFIX_AVATARS", "avatars"),
    "presigned_url_expiration": int(os.getenv("AWS_S3_PRESIGNED_URL_EXPIRATION", "3600")),
}

# -----------------------------
# App-level Config class
# -----------------------------
class Config:
    """
    App-wide configuration (used by create_app).
    Keeps extra runtime settings and safety flags.
    """
    # Catalog defaults
    SPONSOR_CATALOG_CACHE_TTL_SECONDS = 600
    SPONSOR_CATALOG_PAGE_SIZE_DEFAULT = 48
    DRIVER_POINTS_PAGE_SIZE_DEFAULT = 48

    # eBay creds (sponsor side connects to eBay)
    EBAY_APP_ID = os.getenv("EBAY_CLIENT_ID")  # Client ID
    EBAY_OAUTH_TOKEN = os.getenv("EBAY_OAUTH_TOKEN")  # Application access token (Bearer)
    EBAY_ENV = os.getenv("EBAY_ENV")  # or "SANDBOX"

    # Safety flags
    SPONSOR_SAFE_SEARCH = True
    DRIVER_SAFE_SEARCH = True

    # Driver UX
    DRIVER_ALLOW_EXTERNAL_URL = os.getenv("DRIVER_ALLOW_EXTERNAL_URL")

    LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", 10))
