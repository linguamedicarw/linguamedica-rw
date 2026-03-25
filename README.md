# LinguaMedica RW

A specialized medical translation dictionary for English ↔ Kinyarwanda, curated by expert translators working in the health sector. The "RW" badge represents Rwanda, styled in the colors of the Rwandan flag (blue, yellow, green).

## Features

- **Instant search** — Find medical terms as you type (English or Kinyarwanda)
- **Curated translations** — Every entry is validated by a domain expert
- **Example sentences** — See terms used in real medical contexts
- **Etymological explanations** — Understand *why* each translation works linguistically
- **Suggestion system** — Users can submit terms they need translated
- **Admin dashboard** — Manage the dictionary, review suggestions

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/medical-dict-en-rw.git
cd medical-dict-en-rw

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize the database with starter data
python seed_data.py

# 5. Run the development server
python app.py
```

Open http://127.0.0.1:5000 in your browser.

Admin panel: http://127.0.0.1:5000/admin/login

## Project Structure

```
medical-dict/
├── app.py              ← Main Flask application (routes, auth)
├── config.py           ← Configuration (database URL, secrets)
├── models.py           ← Database models (Term, Suggestion, Admin)
├── seed_data.py        ← Initialize database with starter terms
├── requirements.txt    ← Python dependencies
├── Procfile            ← Production server config (Railway/Render)
├── templates/          ← HTML templates (Jinja2)
│   ├── base.html       ← Shared layout
│   ├── index.html      ← Homepage with search
│   ├── suggest.html    ← Suggestion form
│   └── admin/          ← Admin templates
├── static/css/         ← Stylesheet
└── instance/           ← SQLite database (auto-created, git-ignored)
```

## Deployment

This app is deployment-ready for Railway or Render:

1. Push to GitHub
2. Connect your repo to [Railway](https://railway.app) or [Render](https://render.com)
3. Set environment variables: `SECRET_KEY`, optionally `DATABASE_URL`
4. Deploy

## Built With

- Python, Flask, SQLAlchemy, Flask-Login
- SQLite (development) → PostgreSQL (production)
- Vanilla HTML/CSS/JS — no heavy frameworks

## Author

**Khris Le Poète** — Fulbright Scholar, University of Missouri
