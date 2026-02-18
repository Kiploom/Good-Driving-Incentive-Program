# Good Driver Incentive Program – Driver Rewards Platform

A full-stack driver rewards platform that enables sponsor companies to incentivize their drivers through a points-based reward system. Drivers earn points from sponsors and redeem them for products from integrated catalogs (eBay). Includes a Flask web app and an Android mobile app.

![Home Screen](flask/app/static/img/landing/hero.jpg)

---

## Features

### User Roles

| Role | Capabilities |
|------|--------------|
| **Drivers** | Earn points, browse catalog, place orders, track achievements, leaderboards, challenges |
| **Sponsors** | Manage drivers, award points, curate catalog, run challenges, review applications |
| **Admins** | User management, support tickets, analytics, audit logs, system configuration |

### Core Features

- **Points System** – Multi-environment points per driver–sponsor relationship; award, deduct, refund, and dispute tracking
- **Product Catalog** – eBay Browse API integration; search, filter, browse, add to cart
- **Orders & Checkout** – Cart management, checkout flow, order history, refund handling
- **Leaderboards & Challenges** – Gamification with leaderboards and sponsor-defined challenges
- **Mobile App** – Native Android (Kotlin) with catalog, cart, orders, and notifications
- **Support System** – Ticket creation, admin responses, driver/sponsor messaging
- **Security** – MFA (TOTP), bcrypt, CSRF protection, session management, encrypted sensitive fields

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Backend** | Flask, SQLAlchemy, MySQL, Flask-Login, Flask-WTF |
| **Frontend** | Jinja2, Bootstrap, CSS |
| **Mobile** | Android (Kotlin), Material Design |
| **Cloud** | AWS S3 (avatars), eBay API (catalog) |
| **Email** | Ethereal Mail, MailTrap |

---

## Prerequisites

- **Python** 3.9+
- **MySQL** 5.7+ or 8.x
- **Node.js** (optional, for tooling)
- **Android Studio** (for mobile app)

---

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/YOUR_ORG/Good-Driving-Incentive-Program.git
cd Good-Driving-Incentive-Program
```

### 2. Backend (Flask)

```bash
cd flask
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r ../requirements.txt
```

### 3. Environment Variables

Create `flask/.env` with:

```env
# Database
DB_HOST=localhost
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=gooddriver
DB_PORT=3306

# Required
SECRET_KEY=your-secret-key
ENCRYPTION_KEY=your-fernet-key   # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Optional: AWS S3 (profile pictures)
AWS_REGION=us-east-1
AWS_S3_BUCKET_NAME=your-bucket
AWS_S3_BUCKET_PREFIX_AVATARS=avatars

# Optional: eBay catalog
EBAY_CLIENT_ID=...
EBAY_CLIENT_SECRET=...
EBAY_ENV=SANDBOX

# Optional: Email (MailTrap, Ethereal)
MAIL_SERVER=sandbox.smtp.mailtrap.io
MAIL_PORT=2525
MAIL_USERNAME=...
MAIL_PASSWORD=...
```

### 4. Database Migrations

```bash
cd flask
flask --app run:app db upgrade
```

### 5. Run the Web App

```bash
cd flask
python run.py
```

App runs at **http://localhost:5000**

### 6. Create Admin (optional)

```bash
flask --app run:app create-admin
```

---

## Mobile App

```bash
cd mobileApplication
./gradlew assembleDebug   # Linux/macOS
gradlew.bat assembleDebug # Windows
```

APK output: `mobileApplication/app/build/outputs/apk/debug/`

Configure the API base URL in the app to point to your Flask backend.

---

## Deployment

### Web (Flask)

- **WSGI server:** Use Gunicorn or uWSGI in production (not the built-in dev server).
- **Database:** MySQL on AWS RDS or equivalent.
- **Environment:** Set `BEHIND_PROXY=true` if behind a reverse proxy (nginx, CloudFront).
- **HTTPS:** Use a reverse proxy for TLS; set `remember_cookie_secure=True` in production.

### Environment Variables (Production)

| Variable | Description |
|----------|-------------|
| `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | MySQL connection |
| `SECRET_KEY` | Flask session secret |
| `ENCRYPTION_KEY` | Fernet key for sensitive data |
| `AWS_*` | S3 for profile pictures |
| `EBAY_*` | eBay API for catalog |
| `BEHIND_PROXY` | Set to `true` behind nginx/load balancer |
| `ALLOW_IFRAME_ORIGINS` | Optional; space-separated origins for iframe embedding |

---

## Project Structure

```
Good-Driving-Incentive-Program/
├── flask/                 # Flask web app
│   ├── app/               # Application code
│   │   ├── routes/       # Blueprints (auth, admin, driver, sponsor, etc.)
│   │   ├── models/       # SQLAlchemy models
│   │   ├── static/       # CSS, JS, images
│   │   └── templates/    # Jinja2 templates
│   ├── run.py            # Entry point
│   └── config.py         # Config (uses .env)
├── mobileApplication/     # Android app (Kotlin)
├── migrations/            # Flask-Migrate / Alembic
├── docs/                  # Documentation
│   ├── ASSETS_NEEDED.md  # Landing page assets
│   └── PROJECT_SUMMARY.md
└── requirements.txt
```

---

## Contributors

- **Team 10** – Good Driver Incentive Program (CPSC 4910)

---

## Sources & Acknowledgments

| Resource | Use |
|----------|-----|
| [eBay Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html) | Product catalog integration |
| [AWS S3](https://aws.amazon.com/s3/) | Profile picture storage |
| [Flask](https://flask.palletsprojects.com/) | Web framework |
| [SQLAlchemy](https://www.sqlalchemy.org/) | ORM |
| [Bootstrap](https://getbootstrap.com/) | UI components |
| [Font Awesome](https://fontawesome.com/) | Icons |

---

## License

See [LICENSE](LICENSE) for details (if applicable).
