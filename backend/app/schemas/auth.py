from pydantic import BaseModel, Field, field_validator

MOBILE_PATTERN = r"^\+8801[3-9]\d{8}$"


class SendOtpRequest(BaseModel):
    mobile_number: str = Field(..., description="+8801XXXXXXXXX format")

    @field_validator("mobile_number")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        import re

        if not re.match(MOBILE_PATTERN, v):
            raise ValueError("Mobile number must be in +8801XXXXXXXXX format")
        return v


class SendOtpResponse(BaseModel):
    message: str
    otp_expires_in: int


class VerifyOtpRequest(BaseModel):
    mobile_number: str
    otp_code: str = Field(..., min_length=4, max_length=4)


class VerifyOtpResponse(BaseModel):
    verified: bool
    temp_token: str


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    nid_number: str = Field(..., pattern=r"^\d{17}$")
    password: str = Field(..., min_length=8)
    transaction_pin: str = Field(..., pattern=r"^\d{6}$")
    email: str | None = None


class RegisterResponse(BaseModel):
    user_id: int
    access_token: str
    refresh_token: str
    balance: float


class LoginRequest(BaseModel):
    mobile_number: str
    password: str


class UserSummary(BaseModel):
    id: int
    full_name: str
    balance: float
    role: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserSummary
