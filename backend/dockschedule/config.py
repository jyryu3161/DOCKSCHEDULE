from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///storage/development.db'
    redis_url: str = 'redis://localhost:6379/0'
    storage_root: Path = Path('storage')
    qvina_binary: Path = Path('tools/qvina2.1')
    admin_password: str = ''
    cookie_secure: bool = False
    session_hours: int = 12
    max_upload_mb: int = 100
    allowed_networks: str = '127.0.0.0/8,::1/128'


@lru_cache
def config():
    c = Config()
    c.storage_root.mkdir(parents=True, exist_ok=True)
    return c


DEFAULT_SETTINGS = dict(cpu_budget=56, max_students=8, default_cpus=4,
                        max_compounds=20000, max_conformers=10, max_exhaustiveness=64,
                        max_pending_per_user=3, compound_timeout=600, preparation_timeout=1800,
                        max_retries=1, storage_limit_gb=200, user_storage_limit_gb=10,
                        retention_days=0, paused=False)
