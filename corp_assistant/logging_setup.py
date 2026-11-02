import logging

from corp_assistant.config import get_settings


def setup_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root.setLevel(level)
