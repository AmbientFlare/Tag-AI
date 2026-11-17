import logging
import sys
try:
    from paths import get_log_file_path, setup_logging
except ImportError:
    from .paths import get_log_file_path, setup_logging

LOG_FILE = get_log_file_path("app")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)