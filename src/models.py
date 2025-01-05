from pydantic import BaseModel
from typing import Optional

class User(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    latitude: float
    longitude: float
    location: str


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location: Optional[str] = None