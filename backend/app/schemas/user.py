from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import RoleScope, UserStatus
from app.schemas.common import ORMModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PermissionOut(ORMModel):
    id: int
    code: str
    module: str
    name: str
    description: str | None


class RoleOut(ORMModel):
    id: int
    code: str
    name: str
    scope: RoleScope
    description: str | None
    is_builtin: bool


class RoleDetail(RoleOut):
    permissions: list[PermissionOut]


class RoleCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=100)
    scope: RoleScope
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class RolePermissionsSet(BaseModel):
    permission_ids: list[int]


class UserBrief(ORMModel):
    id: int
    username: str
    full_name: str
    avatar_url: str | None


class UserOut(ORMModel):
    id: int
    username: str
    email: str
    full_name: str
    phone: str | None
    avatar_url: str | None
    job_title: str | None
    customer_id: int | None
    status: UserStatus
    is_system_admin: bool
    last_login_at: datetime | None
    created_at: datetime


class UserDetail(UserOut):
    roles: list[RoleOut]


class MeOut(UserDetail):
    permissions: list[str]  # quyền cấp hệ thống


class UserCreate(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9._-]{3,50}$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    phone: str | None = None
    job_title: str | None = None
    customer_id: int | None = None
    is_system_admin: bool = False
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = None
    avatar_url: str | None = None
    job_title: str | None = None
    customer_id: int | None = None
    is_system_admin: bool | None = None


class UserRolesSet(BaseModel):
    role_ids: list[int]


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)
