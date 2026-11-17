# component_launcher.py
"""
Helper module for launching application components through module imports
rather than subprocesses, which is more compatible with packaged applications.
"""

import sys
import os
import logging
import threading
import importlib.util
import traceback
import time
import queue
from typing import Optional, Any

# Ensure Qt imports
from PySide6.QtWidgets import QApplication, QMainWindow, QDialog, QWidget
from PySide6.QtCore import QTimer, QObject, Signal
try:
    from window_manager import get_window_manager
except ImportError:
    try:
        from .window_manager import get_window_manager
    except ImportError:
        # Define a fallback if window_manager is not available
        class DummyWindowManager:
            def register_window(self, name, window): pass
            def get_window(self, name): return None
            def remove_window(self, name): return False
        
        def get_window_manager():
            return DummyWindowManager()
        
# Configure logging with DEBUG level and file output
def setup_detailed_logging():
    logger = logging.getLogger("component_launcher")
    logger.setLevel(logging.DEBUG)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    
    # File handler for more detailed logging
    try:
        log_dir = os.path.join(os.path.expanduser("~"), "Tag-AI", "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "component_launcher_debug.log"), mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
        file_handler.setFormatter(file_format)
        
        # Clear any existing handlers
        logger.handlers.clear()
        
        # Add handlers
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Error setting up logging: {e}")
        logger.addHandler(console_handler)
    
    return logger

# Global logger setup
logger = setup_detailed_logging()

# Wrapper for capturing and logging module import details
def import_module(name, package=None):
    """
    Enhanced module import with detailed logging and error tracking.
    Preserves existing import strategies while adding more robust mechanisms.
    """
    logger.debug(f"Attempting to import module: {name}, Package: {package}")
    
    # Dynamically adjust Python path
    try:
        current_frame = sys._getframe(1)
        caller_file = current_frame.f_globals.get('__file__')
        
        if caller_file:
            caller_dir = os.path.dirname(os.path.abspath(caller_file))
            parent_dir = os.path.dirname(caller_dir)
            
            # Add directories to path if not already present
            for directory in [caller_dir, parent_dir]:
                if directory not in sys.path:
                    sys.path.insert(0, directory)
                    logger.debug(f"Added {directory} to sys.path")
    except Exception as path_error:
        logger.warning(f"Could not modify import path: {path_error}")

    try:
        # 1. Direct import attempt
        try:
            module = importlib.import_module(name, package)
            logger.debug(f"Successfully imported {name} via direct import")
            return module
        except ImportError as direct_import_error:
            logger.warning(f"Direct import failed for {name}: {direct_import_error}")
        
        # 2. Relative import attempt
        if package:
            try:
                module = importlib.import_module(f"{package}.{name}")
                logger.debug(f"Successfully imported {name} via relative import")
                return module
            except ImportError as relative_import_error:
                logger.warning(f"Relative import failed for {name}: {relative_import_error}")
        
        # 3. File-based import attempt
        try:
            # Get the calling module's file path
            frame = sys._getframe(1)
            caller_file = frame.f_globals.get('__file__')
            
            if caller_file:
                module_dir = os.path.dirname(os.path.abspath(caller_file))
                module_path = os.path.join(module_dir, f"{name}.py")
                
                if os.path.exists(module_path):
                    spec = importlib.util.spec_from_file_location(name, module_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    logger.debug(f"Successfully imported {name} via file-based import from {module_path}")
                    return module
        except Exception as file_import_error:
            logger.warning(f"File-based import failed for {name}: {file_import_error}")
        
        # 4. Last resort: try package-prefixed imports
        for prefix in ['tagai', 'tag_ai', 'tag-ai']:
            try:
                module = importlib.import_module(f"{prefix}.{name}")
                logger.debug(f"Successfully imported {name} via package prefix {prefix}")
                return module
            except ImportError:
                continue
        
        # 5. Absolute filesystem search
        try:
            potential_paths = [
                os.path.join(os.path.dirname(__file__), f"{name}.py"),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), f"{name}.py"),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "tag-ai", f"{name}.py"),
            ]

            for path in potential_paths:
                if os.path.exists(path):
                    logger.debug(f"Found module file at {path}")
                    spec = importlib.util.spec_from_file_location(name, path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return module
        except Exception as filesystem_import_error:
            logger.warning(f"Filesystem import failed: {filesystem_import_error}")
        
        # If all import methods fail
        raise ImportError(f"Could not import module {name}")
    
    except Exception as e:
        # Enhanced error logging
        logger.error(f"Critical error importing {name}: {e}")
        logger.error(f"Current sys.path: {sys.path}")
        logger.error(traceback.format_exc())
        raise

# Thread-safe result storage
class ModuleRunResult:
    def __init__(self):
        self.result = None
        self.exception = None
        self.completed = threading.Event()

def launch_module(module_name: str, function_name: str = "main", args: list = None, run_in_main_thread: bool = False) -> Optional[Any]:
    """
    Enhanced module launch with comprehensive logging and error handling.
    """
    logger.info(f"LAUNCH ATTEMPT: module={module_name}, function={function_name}, main_thread={run_in_main_thread}")
    
    # Create a result storage object
    run_result = ModuleRunResult()
    
    def execute_module_function():
        """Internal function to execute the module's function with detailed logging."""
        try:
            logger.debug(f"Executing {module_name}.{function_name}")
            
            # Import the module
            try:
                module = import_module(module_name)
            except ImportError as import_error:
                logger.error(f"Failed to import module {module_name}: {import_error}")
                run_result.exception = import_error
                run_result.completed.set()
                return
            
            # Get the target function
            if not hasattr(module, function_name):
                error_msg = f"Module '{module_name}' has no function named '{function_name}'"
                logger.error(error_msg)
                run_result.exception = AttributeError(error_msg)
                run_result.completed.set()
                return
            
            target_function = getattr(module, function_name)
            
            # Execute the function
            try:
                if args:
                    result = target_function(*args)
                else:
                    result = target_function()
                
                logger.debug(f"Function {module_name}.{function_name} executed successfully")
                logger.debug(f"Result type: {type(result)}")
                run_result.result = result
                
                # Try to set icon if result is a window
                if result and isinstance(result, (QMainWindow, QDialog, QWidget)) and hasattr(result, "setWindowIcon"):
                    try:
                        # Try to get icon from main window
                        window_manager = get_window_manager()
                        main_window = window_manager.get_window("main")
                        if main_window and hasattr(main_window, "windowIcon") and main_window.windowIcon():
                            result.setWindowIcon(main_window.windowIcon())
                            logger.debug(f"Set icon for {module_name} window from main window")
                        # Alternative: Use application-wide icon
                        elif QApplication.instance() and QApplication.instance().windowIcon():
                            result.setWindowIcon(QApplication.instance().windowIcon())
                            logger.debug(f"Set icon for {module_name} window from application")
                    except Exception as icon_error:
                        logger.debug(f"Could not set icon for launched module: {icon_error}")
            except Exception as exec_error:
                logger.error(f"Error executing {module_name}.{function_name}: {exec_error}")
                logger.error(traceback.format_exc())
                run_result.exception = exec_error
            
            run_result.completed.set()
        
        except Exception as e:
            logger.critical(f"Unexpected error in module execution: {e}")
            logger.critical(traceback.format_exc())
            run_result.exception = e
            run_result.completed.set()
    
    # Detect if this is a GUI module
    is_gui_module = any(x in module_name.lower() for x in ['window', 'gui', 'dialog'])
    if is_gui_module:
        run_in_main_thread = True
        logger.info(f"Detected GUI module {module_name}, forcing main thread execution")
    
    # Ensure QApplication exists for GUI modules
    app = QApplication.instance()
    if not app:
        logger.warning("No QApplication instance found. Creating a new one.")
        app = QApplication(sys.argv)
    
    if run_in_main_thread:
        # Execute directly in the main thread
        logger.debug("Executing module in main thread")
        execute_module_function()
        
        # Check for exceptions
        if run_result.exception:
            logger.error(f"Module execution failed: {run_result.exception}")
            raise run_result.exception
        
        return run_result.result
    else:
        # Execute in a separate thread
        logger.debug("Executing module in background thread")
        thread = threading.Thread(target=execute_module_function)
        thread.start()
        
        # Wait with timeout
        if not run_result.completed.wait(timeout=30):  # 30-second timeout
            logger.error("Module execution timed out")
            raise TimeoutError(f"Module {module_name} execution timed out")
        
        # Check for exceptions
        if run_result.exception:
            logger.error(f"Module execution failed: {run_result.exception}")
            raise run_result.exception
        
        return run_result.result

def launch_gui():
    """Launch the main GUI module in the main thread."""
    return launch_module("gui_v02", run_in_main_thread=True)

def launch_scan_window():
    """Launch the scan window module in the main thread."""
    return launch_module("scan_window", run_in_main_thread=True)

def launch_setup():
    """Launch the setup wizard dialog in the main thread."""
    return launch_module("setup", "run_setup_dialog", run_in_main_thread=True)

def launch_config_editor():
    """Launch the configuration editor in the main thread."""
    return launch_module("config_editor", run_in_main_thread=True)

def launch_purge_window():
    """Launch the purge window in the main thread."""
    return launch_module("purge_window", run_in_main_thread=True)

def wait_for_thread(thread: threading.Thread, timeout: float = None) -> bool:
    """
    Wait for a thread to complete with proper KeyboardInterrupt handling.
    
    Args:
        thread: Thread to wait for
        timeout: Maximum time to wait in seconds (None = wait forever)
        
    Returns:
        bool: True if thread completed, False if timeout or interrupted
    """
    if not thread or not thread.is_alive():
        return True
    
    try:
        start_time = time.time()
        while thread.is_alive():
            thread.join(0.5)
            if timeout is not None and time.time() - start_time > timeout:
                logger.warning(f"Timeout waiting for thread")
                return False
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt while waiting for thread")
        return False
        
    return True

if __name__ == "__main__":
    print("Component launcher utility - import and use the functions")
    print("Example: from component_launcher import launch_gui")