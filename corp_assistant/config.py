import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    app_name: str
    api_keys: frozenset[str]
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    log_level: str
    rate_limit_per_minute: int
    deepseek_api_key: str
    deepseek_model: str
    deepseek_api_base: str


def get_settings() -> Settings:
    load_dotenv()
    raw_keys = os.getenv("CORP_API_KEYS", "dev-key")
    return Settings(
        app_name=os.getenv("CORP_APP_NAME", "星澜内部助手"),
        api_keys=frozenset(item.strip() for item in raw_keys.split(",") if item.strip()),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=os.getenv("MYSQL_PASSWORD", os.getenv("MYSQL_ROOT_PASSWORD", "root123456")),
        mysql_database=os.getenv("MYSQL_DATABASE", "langchain"),
        log_level=os.getenv("CORP_LOG_LEVEL", "INFO"),
        rate_limit_per_minute=int(os.getenv("CORP_RATE_LIMIT", "60")),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        deepseek_api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    )
