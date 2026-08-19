from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    password: str = Field(min_length=12, max_length=256)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        return value.strip()


class SignUpRequest(Credentials):
    pass


class LoginRequest(Credentials):
    pass


class PasswordResetRequest(Credentials):
    recovery_code: str = Field(min_length=1, max_length=256)


class UsernameRecoveryRequest(BaseModel):
    recovery_code: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UsernameChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        return value.strip()


class PasswordConfirmation(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: str
    username: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    recovery_code: str | None = None


class UsernameRecoveryResponse(BaseModel):
    username: str


class RecoveryCodeResponse(BaseModel):
    recovery_code: str
