"""InterviewX email/password authentication for the local FastAPI demo.

Accounts are isolated in SQLite. Passwords use Argon2id. The raw session token is
kept only in an HttpOnly cookie; its SHA256 fingerprint is stored in SQLite.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DB = Path(os.getenv('INTERVIEWX_DB', str(ROOT / 'interviewx.sqlite3')))
if not DB.is_absolute(): DB = ROOT / DB
COOKIE_NAME = 'ix_session'
TTL = timedelta(days=7)
# Argon2id with memory-hard parameters; sufficient for a hackathon prototype.
hasher = PasswordHasher(time_cost=3, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)
router = APIRouter(prefix='/api/auth', tags=['authentication'])


def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_auth():
    with conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS auth_failures (
            email_ip_hash TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start REAL NOT NULL
        )""")
        db.execute('CREATE INDEX IF NOT EXISTS ix_auth_sessions_user ON auth_sessions(user_id)')


def utc_now():
    return datetime.now(timezone.utc)


def iso(ts):
    return ts.isoformat()


def _token_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def cookie_secure(request: Request):
    mode = os.getenv('INTERVIEWX_SECURE_COOKIES', 'auto').lower()
    return mode == 'true' or (mode == 'auto' and request.url.scheme == 'https')


def make_login(db, response: Response, request: Request, user_id: str):
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    now = utc_now()
    db.execute('DELETE FROM auth_sessions WHERE expires_at < ?', (iso(now),))
    db.execute('INSERT INTO auth_sessions (token_hash,user_id,csrf_token,expires_at,created_at) VALUES (?,?,?,?,?)',
               (_token_hash(raw), user_id, csrf, iso(now + TTL), iso(now)))
    response.set_cookie(COOKIE_NAME, raw, max_age=int(TTL.total_seconds()), httponly=True,
                        secure=cookie_secure(request), samesite='lax', path='/')


def optional_user(request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    if not raw: return None
    with conn() as db:
        row = db.execute("""SELECT u.id,u.email,u.name,s.csrf_token,s.expires_at
            FROM auth_sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=?""",
                         (_token_hash(raw),)).fetchone()
    if row is None or row['expires_at'] <= iso(utc_now()): return None
    return dict(row)


def current_user(request: Request):
    user = optional_user(request)
    if not user: raise HTTPException(status_code=401, detail='Sign in to continue.')
    return user


def mutation_user(request: Request, user=Depends(current_user),
                  csrf: str | None = Header(default=None, alias='X-CSRF-Token')):
    if not csrf or not secrets.compare_digest(csrf, user['csrf_token']):
        raise HTTPException(status_code=403, detail='Invalid security token. Refresh and sign in again.')
    return user


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=80)


def normalized_email(s):
    email = s.strip().lower()
    if not re.fullmatch(r'[^\s@]{1,64}@[^\s@]+\.[^\s@]{2,}', email):
        raise HTTPException(422, 'Enter a valid email address.')
    return email


def public_user(row):
    return {'id': row['id'], 'name': row['name'], 'email': row['email']}


def failed_login_key(email: str, request: Request):
    ip = request.client.host if request.client else 'unknown'
    return hashlib.sha256(f'{email}:{ip}'.encode()).hexdigest()


def enforce_limit(db, key: str):
    row = db.execute('SELECT count,window_start FROM auth_failures WHERE email_ip_hash=?',(key,)).fetchone()
    if row and time.time()-row['window_start'] < 900 and row['count']>=8:
        raise HTTPException(status_code=429, detail='Too many attempts. Try again in 15 minutes.')


def record_failure(db, key):
    row = db.execute('SELECT count,window_start FROM auth_failures WHERE email_ip_hash=?',(key,)).fetchone()
    if not row or time.time()-row['window_start'] >= 900:
        db.execute('INSERT OR REPLACE INTO auth_failures VALUES (?,?,?)',(key,1,time.time()))
    else:
        db.execute('UPDATE auth_failures SET count=count+1 WHERE email_ip_hash=?',(key,))


@router.post('/register', status_code=201)
def register(data: Registration, request: Request, response: Response):
    email = normalized_email(data.email)
    if not 10 <= len(data.password) <= 128:
        raise HTTPException(422, detail='Password must contain at least 10 characters.')
    name = ' '.join(data.name.split())
    if len(name) < 2: raise HTTPException(422, detail='Enter your name.')
    with conn() as db:
        if db.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
            raise HTTPException(409, detail='This email already has an account.')
        uid = uuid.uuid4().hex
        db.execute('INSERT INTO users VALUES (?,?,?,?,?)',
                   (uid, name, email, hasher.hash(data.password), iso(utc_now())))
        make_login(db, response, request, uid)
    return {'user': {'id':uid, 'name':name, 'email':email}}


@router.post('/login')
def login(data: Credentials, request: Request, response: Response):
    email = normalized_email(data.email)
    with conn() as db:
        key = failed_login_key(email, request)
        enforce_limit(db, key)
        row = db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        valid = False
        if row:
            try: valid = hasher.verify(row['password_hash'], data.password)
            except (VerificationError, InvalidHashError): pass
        if not valid:
            record_failure(db, key)
            db.commit()  # preserve the failure count even when returning an error
            raise HTTPException(401, detail='Incorrect email or password.')
        db.execute('DELETE FROM auth_failures WHERE email_ip_hash=?',(key,))
        make_login(db, response, request, row['id'])
    return {'user': public_user(row)}


@router.get('/me')
def me(user=Depends(current_user)):
    return {'user': public_user(user), 'csrf_token': user['csrf_token']}


@router.post('/logout')
def logout(request: Request, response: Response, user=Depends(mutation_user)):
    raw = request.cookies.get(COOKIE_NAME, '')
    with conn() as db: db.execute('DELETE FROM auth_sessions WHERE token_hash=?', (_token_hash(raw),))
    response.delete_cookie(COOKIE_NAME, path='/', samesite='lax', secure=cookie_secure(request), httponly=True)
    return {'signed_out': True}
