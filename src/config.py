from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DotEnvConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    sticker_db_name: str
    sticker_db_user: str
    sticker_db_password: SecretStr
    sticker_db_host: str
    sticker_db_port: int = 5432
    sticker_db_type: str = "postgresql"
    # Browser origins allowed to call the API directly, as a JSON list. Stays
    # empty when the frontend reaches the API through a same-origin proxy.
    sticker_cors_origins: list[str] = []
    # Path prefix the proxy strips before forwarding, used for the /docs links.
    sticker_root_path: str = ""
    # Per client IP, in `limits` notation. The write endpoint has no login.
    sticker_create_rate_limit: str = "30/minute"

    @property
    def db_url(self) -> URL:
        return URL.create(
            self.sticker_db_type,
            username=self.sticker_db_user,
            password=self.sticker_db_password.get_secret_value(),
            host=self.sticker_db_host,
            port=self.sticker_db_port,
            database=self.sticker_db_name,
        )


config = DotEnvConfig()  # type: ignore
