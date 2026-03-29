# LinguaMedica RW

A curated medical translation dictionary for English ↔ Kinyarwanda, built to standardize medical terminology for healthcare professionals, translators, and researchers working in Rwanda's health sector.

**Live at [linguamedica.rw](https://linguamedica.rw)**

## Features

- **Instant search** — Find medical terms as you type (English or Kinyarwanda)
- **Curated translations** — Every entry is validated by a domain expert
- **Example sentences** — See terms used in real medical contexts (both languages)
- **Etymological explanations** — Understand *why* each translation works linguistically
- **Suggestion system** — Users can submit terms they need translated
- **Admin dashboard** — Manage the dictionary, review suggestions
- **JSON API** — Ready for mobile apps and integrations

## Quick Start

```bash
# Clone the repository
git clone https://github.com/linguamedicarw/linguamedica-rw.git
cd linguamedica-rw

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables (see .env.example)
export SECRET_KEY="your-secret-key"
export ADMIN_USERNAME="your-username"
export ADMIN_PASSWORD="your-strong-password"

# Initialize the database with starter data
python seed_data.py

# Run the development server
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key |
| `ADMIN_USERNAME` | Yes | Admin login username |
| `ADMIN_PASSWORD` | Yes | Admin login password |
| `DATABASE_URL` | No | Database URL (defaults to SQLite) |
| `PORT` | No | Server port (Railway sets automatically) |

See `.env.example` for a template.

## Project Structure

```
linguamedica-rw/
├── app.py              ← Main Flask application (routes, auth, security)
├── config.py           ← Configuration (database URL, secrets)
├── models.py           ← Database models (Term, Suggestion, Admin)
├── seed_data.py        ← 53 curated medical terms + admin setup
├── requirements.txt    ← Python dependencies
├── Procfile            ← Production server config (Railway)
├── .env.example        ← Environment variable template
├── LICENSE             ← MIT License
├── templates/          ← HTML templates (Jinja2)
│   ├── base.html       ← Shared layout
│   ├── index.html      ← Homepage with search
│   ├── suggest.html    ← Suggestion form
│   └── admin/          ← Admin templates
├── static/css/         ← Stylesheet
└── instance/           ← SQLite database (auto-created, git-ignored)
```

## Security

- Passwords hashed with Werkzeug (never stored in plaintext)
- All credentials loaded from environment variables
- CSRF protection on all forms (Flask-WTF)
- Rate limiting on login route — 5 attempts per minute (Flask-Limiter)
- Content-Security-Policy and X-Frame-Options headers
- SQLAlchemy ORM prevents SQL injection
- XSS protection via HTML escaping on all user content

## Deployment

This app is deployment-ready for Railway or Render:

1. Push to GitHub
2. Connect your repo to [Railway](https://railway.app)
3. Set environment variables: `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`
4. Deploy

## Tech Stack

- Python, Flask, SQLAlchemy, Flask-Login
- Flask-WTF (CSRF), Flask-Limiter (rate limiting)
- SQLite (development) → PostgreSQL (production)
- Vanilla HTML/CSS/JS — no heavy frameworks

## Research Context

LinguaMedica RW is part of ongoing research on terminology-constrained medical translation for low-resource languages, specifically English-Kinyarwanda. The curated dictionary serves as both a practical tool and a parallel corpus for NLP research.

## Author

**Christophe Mumaragishyika** — Fulbright Scholar, University of Missouri

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
