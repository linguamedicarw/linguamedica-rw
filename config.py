"""
Configuration for the Medical Dictionary app.

WHY THIS FILE EXISTS:
- Keeps all settings in one place (not scattered across files)
- Uses environment variables so the same code works locally AND in production
- The DATABASE_URL pattern means switching from SQLite to PostgreSQL
  is literally changing one environment variable
"""

import os

# Get the absolute path to this file's directory
# This ensures the SQLite database is created in the right place
basedir = os.path.abspath(os.path.dirname(__file__))

# Ensure the instance directory exists (SQLite needs it to create the .db file)
os.makedirs(os.path.join(basedir, "instance"), exist_ok=True)


class Config:
    # Secret key for session security (Flask uses this to sign cookies)
    # In production, set this as an environment variable — never hardcode it
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

    # Database URL — this is the magic line for scalability:
    # - Locally: defaults to SQLite (a single file, zero setup)
    # - In production: set DATABASE_URL=postgresql://... and everything just works
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(basedir, 'instance', 'dictionary.db')}"
    )

    # Suppress a warning from SQLAlchemy we don't need
    SQLALCHEMY_TRACK_MODIFICATIONS = False
