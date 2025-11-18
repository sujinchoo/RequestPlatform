# config.py
import os

class Config:
    raw_uri = os.getenv("DATABASE_URL", "")

    # Render가 postgres:// 로 주는 경우가 많으니 psycopg용으로 변환
    if raw_uri.startswith("postgres://"):
        raw_uri = raw_uri.replace("postgres://", "postgresql+psycopg://", 1)

    SQLALCHEMY_DATABASE_URI = raw_uri
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
