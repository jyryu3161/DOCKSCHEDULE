from pydantic import BaseModel, Field, field_validator, model_validator


class Register(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    name: str = Field(min_length=1, max_length=100)
    student_number: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class Login(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=128)


class LibraryOptions(BaseModel):
    delimiter: str = ','
    encoding: str = 'utf-8-sig'
    header: bool = True
    cid_column: str = ''
    smiles_column: str = ''


class Prepare(BaseModel):
    upload_id: str
    name: str = Field(min_length=1, max_length=200)
    model: int = 1
    chains: list[str]
    keep_heterogens: list[str] = []
    ph: float = Field(default=7.4, ge=0, le=14, allow_inf_nan=False)


class Docking(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    receptor_id: str
    library_id: str
    library: LibraryOptions
    center: list[float] = Field(min_length=3, max_length=3)
    size: list[float] = Field(default=[20, 20, 20], min_length=3, max_length=3)
    selected_residues: list[str] = []
    conformers: int = Field(default=1, ge=1, le=100)
    exhaustiveness: int = Field(default=8, ge=1, le=1024)
    seed: int = Field(default=42, ge=1, le=2147483646)
    strip_salts: bool = True

    @field_validator('center', 'size')
    @classmethod
    def finite_coordinates(cls, values, info):
        import math
        if not all(math.isfinite(x) and abs(x) < 100000 for x in values):
            raise ValueError('유효한 좌표를 입력하세요.')
        if info.field_name == 'size' and not all(1 <= x <= 100 for x in values):
            raise ValueError('박스 크기는 각 축 1~100 Å이어야 합니다.')
        return values


class ResourceSettings(BaseModel):
    cpu_budget: int = Field(ge=1, le=4096)
    max_students: int = Field(ge=1, le=128)
    default_cpus: int = Field(ge=1, le=4096)
    max_compounds: int = Field(ge=1, le=100000)
    max_conformers: int = Field(ge=1, le=100)
    max_exhaustiveness: int = Field(ge=1, le=1024)
    max_pending_per_user: int = Field(ge=1, le=100)
    compound_timeout: int = Field(ge=10, le=86400)
    preparation_timeout: int = Field(ge=60, le=86400)
    max_retries: int = Field(ge=0, le=5)
    storage_limit_gb: int = Field(ge=1, le=100000)
    user_storage_limit_gb: int = Field(ge=1, le=100000)
    retention_days: int = Field(ge=0, le=3650)
    gnina_top_n: int = Field(default=1000, ge=0, le=100000)
    paused: bool

    @model_validator(mode='after')
    def gnina_within_library_limit(self):
        if self.gnina_top_n > self.max_compounds:
            raise ValueError('GNINA 재채점 개수는 library 최대 화합물 수 이하여야 합니다.')
        return self


class UserUpdate(BaseModel):
    status: str | None = Field(default=None, pattern='^(approved|rejected|suspended|pending)$')
    cpu_override: int | None = Field(default=None, ge=1, le=4096)

    @field_validator('status')
    @classmethod
    def status_not_null(cls, value):
        if value is None:
            raise ValueError('계정 상태는 비워 둘 수 없습니다.')
        return value


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
