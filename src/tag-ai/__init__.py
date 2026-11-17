# __init__.py for the Tag-AI package
# Enhanced to integrate with core infrastructure

import sys
import os
import logging
import importlib.util

# Make sure the directory containing this file is in the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Configure simple logging first, in case the paths module isn't available
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Use module_loader for more robust imports
try:
    from .Module_loader import import_module
except ImportError:
    # Fallback import_module function if module_loader isn't available
    def import_module(name, package=None):
        """Fallback implementation of import_module"""
        if package:
            try:
                return importlib.import_module(f"{package}.{name}")
            except ImportError:
                pass
        try:
            return importlib.import_module(name)
        except ImportError:
            try:
                return importlib.import_module(f".{name}", package=__package__)
            except (ImportError, ValueError):
                logger.error(f"Could not import module {name}")
                raise ImportError(f"Could not import module {name}")

# Configure proper logging using paths.py if available
try:
    paths_module = import_module("paths")
    setup_logging = getattr(paths_module, "setup_logging")
    setup_logging("init", logging.INFO)
    logger.info("Using paths.py for logging configuration")
except (ImportError, AttributeError) as e:
    logger.warning(f"Could not configure logging with paths.py: {e}")

# Expose core utilities for direct import from the package
try:
    # Path utilities
    from .paths import (
        get_app_dir, get_user_data_dir, get_default_config_path, 
        get_default_db_path, get_log_dir, setup_logging
    )
    
    # Window management
    from .window_manager import get_window_manager
    
    # Component launching
    from .component_launcher import launch_module
    
    # Make key utilities available at package level for easier imports
    __all__ = [
        "get_app_dir", "get_user_data_dir", "get_default_config_path", 
        "get_default_db_path", "get_log_dir", "setup_logging",
        "get_window_manager", "launch_module"
    ]
    
    logger.info("Core utilities exposed for import from package")
except ImportError as e:
    logger.warning(f"Could not expose core utilities: {e}")
    __all__ = []

# Define Briefcase entry point
def main():
    """Entry point for the Briefcase app"""
    logger.info(f"Starting application from {__file__}")
    logger.info(f"Python path: {sys.path}")
    
    # Try to import and call main.py's main function using module_loader
    try:
        main_module = import_module("main")
        logger.info("Successfully imported main module")
        return main_module.main()
    except ImportError as e:
        logger.critical(f"Failed to import main module using module_loader: {e}")
        
        # Try relative import as second approach
        try:
            from . import main as main_module
            logger.info("Successfully imported main module via relative import")
            return main_module.main()
        except ImportError as e2:
            logger.critical(f"Relative import also failed: {e2}")
            
            # Try direct import as third approach
            try:
                import main as main_module
                logger.info("Successfully imported main module via direct import")
                return main_module.main()
            except ImportError as e3:
                logger.critical(f"Direct import also failed: {e3}")
                
                # Last resort, try to find and execute main.py directly
                try:
                    main_py = os.path.join(current_dir, "main.py")
                    if os.path.exists(main_py):
                        logger.info(f"Found main.py at {main_py}, attempting to run directly")
                        import runpy
                        globals_dict = runpy.run_path(main_py)
                        if "main" in globals_dict:
                            return globals_dict["main"]()
                        else:
                            logger.critical("main() function not found in main.py")
                    else:
                        logger.critical(f"main.py not found at {main_py}")
                except Exception as e4:
                    logger.critical(f"Last resort attempt failed: {e4}")
                
                logger.critical("All import methods failed, application cannot start")
                return 1

# Version information
__version__ = "1.0.0"