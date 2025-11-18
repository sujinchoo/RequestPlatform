# config.py
import os

class Config:
    # Render PostgreSQL에서 제공하는 URL 사용
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
