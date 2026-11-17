# window_manager.py
"""
A singleton manager for application windows to prevent garbage collection
and maintain references across the application.
"""

import logging
from typing import Dict, Any, Optional

try:
    from global_signals import global_signals
except ImportError:
    from .global_signals import global_signals
# First try to import our custom module_loader
try:
    from Module_loader import import_module
except ImportError:
    # Fallback implementation if module_loader is not available
    def import_module(name, package=None):
        import importlib
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
                # Try some common package prefixes
                for prefix in ['tagai', 'tag_ai', 'tag-ai']:
                    try:
                        return importlib.import_module(f"{prefix}.{name}")
                    except ImportError:
                        continue
                raise ImportError(f"Could not import module {name}")

# Import paths module using our import_module function
paths_module = import_module('paths')
setup_logging = getattr(paths_module, 'setup_logging')

# Set up logging
setup_logging("window_manager", logging.INFO)
logger = logging.getLogger(__name__)

class WindowManager:
    """
    Singleton class to maintain references to windows and dialogs.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            logger.debug("Creating new WindowManager instance")
            cls._instance = super(WindowManager, cls).__new__(cls)
            cls._instance._windows = {}
        return cls._instance
    
    def register_window(self, name: str, window: Any) -> None:
        """
        Register a window with the manager.
        
        Args:
            name: A unique name for the window
            window: The window object to register
        """
        if name in self._windows:
            logger.warning(f"Window with name '{name}' already registered, replacing")
        else:
            logger.debug(f"Registering window '{name}'")
        self._windows[name] = window
    
    def get_window(self, name: str) -> Optional[Any]:
        """
        Get a window by name.
        
        Args:
            name: The name of the window to retrieve
            
        Returns:
            The window object or None if not found
        """
        window = self._windows.get(name)
        if window is None:
            logger.debug(f"Window '{name}' not found")
        return window
    
    def remove_window(self, name: str) -> bool:
        """
        Remove a window from the manager.
        
        Args:
            name: The name of the window to remove
            
        Returns:
            True if the window was removed, False otherwise
        """
        if name in self._windows:
            logger.debug(f"Removing window '{name}'")
            del self._windows[name]
            return True
        logger.debug(f"Cannot remove window '{name}', not found")
        return False
    
    def list_windows(self) -> Dict[str, Any]:
        """
        Get a dictionary of all registered windows.
        
        Returns:
            A dictionary mapping window names to window objects
        """
        return self._windows.copy()

# Create a global instance
window_manager = WindowManager()

def get_window_manager() -> WindowManager:
    """
    Get the global WindowManager instance.
    
    Returns:
        The global WindowManager instance
    """
    return window_manager

# Example usage:
# from window_manager import get_window_manager
# 
# # Register a window
# window_manager = get_window_manager()
# window_manager.register_window("main", main_window)
# 
# # Get a window
# main_window = window_manager.get_window("main")