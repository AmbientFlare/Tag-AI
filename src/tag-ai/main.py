# main.py
import sys
import os
import logging
import configparser
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QFile, QIODevice, QTextStream

# Import the module loader first
try:
    from Module_loader import import_module
except ImportError:
    # If module_loader isn't available, define a fallback import_module function
    def import_module(name, package=None):
        if package:
            try:
                return __import__(f"{package}.{name}", fromlist=[None])
            except ImportError:
                pass
        try:
            return __import__(name)
        except ImportError:
            try:
                return __import__(f".{name}", fromlist=[None])
            except ImportError:
                raise ImportError(f"Could not import {name}")

# Now use import_module for all internal imports
paths_module = import_module('paths')
setup_logging = getattr(paths_module, 'setup_logging')
get_default_config_path = getattr(paths_module, 'get_default_config_path')

# Import component_launcher
component_launcher = import_module('component_launcher')
launch_setup = getattr(component_launcher, 'launch_setup')

# Set up logging
setup_logging("main", logging.INFO)
logger = logging.getLogger(__name__)

# Global reference to main window
_main_window = None

def load_stylesheet(app):
    """Load the application's stylesheet."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    stylesheet_file = QFile(os.path.join(current_dir, "dark_style.qss"))
    if stylesheet_file.open(QIODevice.ReadOnly | QIODevice.Text):
        stream = QTextStream(stylesheet_file)
        app.setStyleSheet(stream.readAll())
        stylesheet_file.close()
    else:
        logger.warning("Failed to load stylesheet: dark_style.qss")

def is_setup_complete():
    """Check if initial setup has been completed successfully."""
    config = configparser.ConfigParser()
    config_path = get_default_config_path()
    
    if not os.path.exists(config_path):
        logger.error(f"Config file not found at {config_path}")
        return False
        
    config.read(config_path)
    if "setup" not in config:
        logger.error("No setup section in config.ini")
        return False
    
    if "setup_complete" not in config["setup"]:
        logger.error("No setup_complete key in config.ini")
        return False
    
    value = config["setup"].get("setup_complete", "").lower().strip()
    setup_complete = value in ("true", "1", "yes", "y", "t")
    logger.info(f"Setup complete status: {setup_complete} (value='{value}')")
    
    return setup_complete

def main():
    """Main entry point for the application."""
    global _main_window
    
    # Set up logging
    setup_logging("main", logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Create QApplication instance
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)

    # Check if setup is complete
    if not is_setup_complete():
        logger.info("Setup not complete, launching setup wizard...")
        
        def launch_setup():
            """Launch the setup wizard dialog in the main thread."""
            try:
                from . import setup
            except ImportError:
                try:
                    import setup
                except ImportError:
                    import importlib.util
                    import os

                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    setup_path = os.path.join(current_dir, 'setup.py')
                    
                    spec = importlib.util.spec_from_file_location("setup", setup_path)
                    setup = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(setup)
            
            return setup.run_setup_dialog()

        setup_result = launch_setup()
        
        if not setup_result:
            logger.error("Setup was not completed successfully")
            QMessageBox.critical(None, "Setup Error", "Setup was not completed successfully")
            return 1
        
        # Recheck setup status after the wizard
        if not is_setup_complete():
            logger.error("Setup wizard did not mark setup as complete")
            QMessageBox.critical(None, "Setup Error", "Setup was not marked as complete")
            return 1

    # Import gui_v02 module using our import_module function
    try:
        gui_v02 = import_module('gui_v02')
        gui_main = getattr(gui_v02, 'main')
        
        _main_window = gui_main()
        
        if isinstance(_main_window, int):  # If gui_main returned an exit code
            return _main_window
            
        # If we got here, _main_window should be a window instance and we can start the event loop
        return app.exec()
    except Exception as e:
        logger.critical(f"Error launching GUI: {e}", exc_info=True)
        QMessageBox.critical(None, "Error", f"Failed to launch GUI: {e}")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        QMessageBox.critical(None, "Fatal Error", f"An unexpected error occurred: {e}")
        sys.exit(1)
