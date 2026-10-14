import hashlib
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .config import config
from .db import get_db, transaction
from .models import LoginSession, User, now

hasher = PasswordHasher()


def password_hash(password):
    if not 8 <= len(password) <= 128:
        raise ValueError('비밀번호는 8~128자로 입력하세요.')
    return hasher.hash(password)


def verify(password, hashed):
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, ValueError):
        return False


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user):
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(token_hash=digest(token), user_id=user.id,
                        expires_at=now() + timedelta(hours=config().session_hours)))
    return token


def current_user(request: Request, db=Depends(get_db)):
    session = db.get(LoginSession, digest(request.cookies.get('ds_session', '')))
    if session is None or session.expires_at < now():
        raise HTTPException(401, '로그인이 필요합니다.')
    user = db.get(User, session.user_id)
    if user is None or user.status in ('rejected', 'suspended'):
        raise HTTPException(403, '사용할 수 없는 계정입니다.')
    return user


def approved(user=Depends(current_user)):
    if user.status != 'approved':
        raise HTTPException(403, '관리자 승인 후 사용할 수 있습니다.')
    return user


def admin(user=Depends(approved)):
    if user.role != 'admin':
        raise HTTPException(403, '관리자 전용 기능입니다.')
    return user


def owned(obj, user):
    if obj is None or (obj.owner_id != user.id and user.role != 'admin'):
        raise HTTPException(404, '자료를 찾을 수 없습니다.')
    return obj


def bootstrap():
    from .config import DEFAULT_SETTINGS
    from .models import Settings
    with transaction() as db:
        if db.get(Settings, 1) is None:
            db.add(Settings(id=1, values=DEFAULT_SETTINGS.copy()))
        if db.scalar(select(User).where(User.username == 'admin')) is None:
            if not config().admin_password:
                raise RuntimeError('첫 실행 시 ADMIN_PASSWORD를 설정하세요.')
            db.add(User(username='admin', name='관리자', password_hash=password_hash(config().admin_password),
                        role='admin', status='approved'))
