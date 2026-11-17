import os
import sys
import platform
import tempfile
import logging
import importlib.util
from pathlib import Path

# Configure module-level logger
logger = logging.getLogger(__name__)

# Application name used for directory creation
APP_NAME = "Tag-AI"

def get_app_dir():
    """
    Get the directory where the application is installed.
    This is useful for read-only resources shipped with the app.
    
    The function tries multiple approaches to locate the app directory:
    1. Check for PyInstaller's _MEIPASS
    2. Check for Briefcase app directory pattern
    3. Fall back to the directory of this file
    """
    # First check: PyInstaller
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        app_dir = Path(sys._MEIPASS)
        logger.debug(f"Using PyInstaller _MEIPASS for app directory: {app_dir}")
        return app_dir
    
    # Get the path of the current file
    current_file = Path(__file__)
    current_dir = current_file.parent
    
    # Second check: Briefcase pattern - look for common Briefcase directory structures
    # Check if we're running from a Briefcase app bundle
    potential_dirs = [
        # Regular path
        current_dir,
        # Briefcase app inside a package
        current_dir / "app",
        # Briefcase app with additional nesting
        current_dir.parent / "app",
        # Briefcase with package name in path
        current_dir.parent / "tagai" / "app",
        # Parent directory (useful for source distributions)
        current_dir.parent,
    ]
    
    for potential_dir in potential_dirs:
        if (potential_dir / "dark_style.qss").exists():
            logger.debug(f"Found app directory with dark_style.qss: {potential_dir}")
            return potential_dir
    
    # Third check: Look for common resource files in parent and grandparent directories
    parent_dir = current_dir.parent
    if (parent_dir / "dark_style.qss").exists():
        logger.debug(f"Found app directory in parent: {parent_dir}")
        return parent_dir
    
    grandparent_dir = parent_dir.parent
    if (grandparent_dir / "dark_style.qss").exists():
        logger.debug(f"Found app directory in grandparent: {grandparent_dir}")
        return grandparent_dir
    
    # Final fallback: use the directory containing this file
    logger.debug(f"Using path of paths.py as app directory: {current_dir}")
    return current_dir

def get_user_data_dir():
    """
    Returns a platform-specific directory for user data files.
    Creates the directory if it doesn't exist.
    """
    system = platform.system()
    
    if system == "Windows":
        # Use %LOCALAPPDATA% on Windows (e.g., C:\Users\Username\AppData\Local\Tag-AI)
        data_dir = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / APP_NAME
    elif system == "Darwin":  # macOS
        # Use ~/Library/Application Support/Tag-AI on macOS
        data_dir = Path(os.path.expanduser("~")) / "Library" / "Application Support" / APP_NAME
    else:  # Linux and other platforms
        # Use ~/.local/share/Tag-AI on Linux (XDG_DATA_HOME)
        data_dir = Path(os.environ.get("XDG_DATA_HOME", 
                                      os.path.expanduser("~/.local/share"))) / APP_NAME
    
    # Create directory if it doesn't exist
    try:
        os.makedirs(data_dir, exist_ok=True)
        logger.debug(f"User data directory: {data_dir}")
    except PermissionError:
        # Fallback to a temporary directory if we can't create in the standard location
        fallback_dir = Path(tempfile.gettempdir()) / APP_NAME
        os.makedirs(fallback_dir, exist_ok=True)
        logger.warning(f"Permission denied for {data_dir}, using fallback: {fallback_dir}")
        data_dir = fallback_dir
        
    return data_dir

def get_config_dir():
    """
    Returns a platform-specific directory for configuration files.
    Creates the directory if it doesn't exist.
    """
    system = platform.system()
    
    if system == "Windows":
        # On Windows, use the same as data dir
        config_dir = get_user_data_dir()
    elif system == "Darwin":  # macOS
        # On macOS, preferences are often in the same place as data
        config_dir = get_user_data_dir()
    else:  # Linux and other platforms
        # Use ~/.config/Tag-AI on Linux (XDG_CONFIG_HOME)
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", 
                                        os.path.expanduser("~/.config"))) / APP_NAME
        try:
            os.makedirs(config_dir, exist_ok=True)
        except PermissionError:
            # Fallback to user data dir if we can't create config dir
            config_dir = get_user_data_dir()
            
    logger.debug(f"Config directory: {config_dir}")
    return config_dir

def get_log_dir():
    """
    Returns a platform-specific directory for log files.
    Creates the directory if it doesn't exist.
    """
    system = platform.system()
    
    if system == "Windows":
        # Use %LOCALAPPDATA%\Tag-AI\Logs on Windows
        log_dir = get_user_data_dir() / "Logs"
    elif system == "Darwin":  # macOS
        # Use ~/Library/Logs/Tag-AI on macOS
        log_dir = Path(os.path.expanduser("~")) / "Library" / "Logs" / APP_NAME
    else:  # Linux and other platforms
        # Use ~/.local/state/Tag-AI/logs on Linux (XDG_STATE_HOME)
        state_dir = Path(os.environ.get("XDG_STATE_HOME", 
                                      os.path.expanduser("~/.local/state"))) / APP_NAME
        log_dir = state_dir / "logs"
    
    # Create directory if it doesn't exist
    try:
        os.makedirs(log_dir, exist_ok=True)
        logger.debug(f"Log directory: {log_dir}")
    except PermissionError:
        # Fallback to temp directory if we can't create in the standard location
        fallback_dir = Path(tempfile.gettempdir()) / APP_NAME / "Logs"
        os.makedirs(fallback_dir, exist_ok=True)
        logger.warning(f"Permission denied for {log_dir}, using fallback: {fallback_dir}")
        log_dir = fallback_dir
        
    return log_dir

def get_temp_dir():
    """
    Returns a directory for temporary files specific to this application.
    Creates the directory if it doesn't exist.
    """
    temp_dir = Path(tempfile.gettempdir()) / APP_NAME
    os.makedirs(temp_dir, exist_ok=True)
    logger.debug(f"Temp directory: {temp_dir}")
    return temp_dir

def get_default_db_path():
    """
    Returns the path to the SQLite database.
    For read-write operations, this should be in the user data directory.
    """
    db_path = get_user_data_dir() / "photos.db"
    logger.debug(f"Database path: {db_path}")
    return db_path

def get_default_config_path():
    """
    Returns the path to the config.ini file.
    For read-write operations, this should be in the config directory.
    """
    config_path = get_config_dir() / "config.ini"
    logger.debug(f"Config path: {config_path}")
    return config_path

def ensure_app_resources():
    """
    Ensures that necessary resources are copied from the app directory
    to user-writable locations if they don't exist yet.
    Returns a dictionary with paths to key resources.
    """
    # Get source and destination paths
    app_dir = get_app_dir()
    user_data_dir = get_user_data_dir()
    config_dir = get_config_dir()
    
    resources = {}
    
    # Check for database
    source_db = app_dir / "photos.db"
    if not source_db.exists():
        source_db = app_dir / "template.db"
    
    # Also try variations for Briefcase
    if not source_db.exists():
        for variant in ["src/tag-ai/photos.db", "src/tag-ai/template.db"]:
            variant_path = app_dir / variant
            if variant_path.exists():
                source_db = variant_path
                break
    
    dest_db = user_data_dir / "photos.db"
    
    # Copy database if it doesn't exist in user directory
    if source_db.exists() and not dest_db.exists():
        try:
            import shutil
            shutil.copy2(source_db, dest_db)
            logger.info(f"Copied initial database to {dest_db}")
        except Exception as e:
            logger.error(f"Failed to copy database: {e}")
    
    resources['db_path'] = dest_db
    
    # Check for config.ini
    source_config = app_dir / "config.ini"
    # Also try variations for Briefcase
    if not source_config.exists():
        for variant in ["src/tag-ai/config.ini"]:
            variant_path = app_dir / variant
            if variant_path.exists():
                source_config = variant_path
                break
    
    dest_config = config_dir / "config.ini"
    
    # Copy config if it doesn't exist in user directory
    if source_config.exists() and not dest_config.exists():
        try:
            import shutil
            shutil.copy2(source_config, dest_config)
            logger.info(f"Copied initial config to {dest_config}")
        except Exception as e:
            logger.error(f"Failed to copy config: {e}")
    
    resources['config_path'] = dest_config
    
    return resources

def get_log_file_path(log_name):
    """
    Returns a path for a log file with the given name.
    """
    log_dir = get_log_dir()
    log_path = log_dir / f"{log_name}.log"
    return log_path

def setup_logging(log_name="app", level=logging.INFO):
    """
    Sets up logging to write to an appropriate log file.
    """
    log_path = get_log_file_path(log_name)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create a file handler that logs to the user's log directory
    try:
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        logger.info(f"Logging to {log_path}")
    except Exception as e:
        # If we can't log to the file, at least set up console logging
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        logger.error(f"Failed to set up file logging to {log_path}: {e}")
    
    # Always add a console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    return log_path

if __name__ == "__main__":
    # Test the module when run directly
    setup_logging("paths_test")
    
    print(f"App directory: {get_app_dir()}")
    print(f"User data directory: {get_user_data_dir()}")
    print(f"Config directory: {get_config_dir()}")
    print(f"Log directory: {get_log_dir()}")
    print(f"Temp directory: {get_temp_dir()}")
    print(f"Default database path: {get_default_db_path()}")
    print(f"Default config path: {get_default_config_path()}")
    
    resources = ensure_app_resources()
    print(f"Resource paths: {resources}")