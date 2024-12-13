from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application configuration settings"""
    elevenlabs_api_key: str
    agent_id: str
    twilio_account_sid: str
    twilio_auth_token: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"