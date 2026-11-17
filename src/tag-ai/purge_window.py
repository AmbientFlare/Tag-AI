#purge_window.py
import os
import sys
import time
import logging
import sqlite3
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QApplication, 
    QMessageBox, QWidget, QListWidget, QFrame, QStatusBar
)
from PySide6.QtCore import Qt, QFile, QIODevice, QTextStream
from PySide6.QtGui import QIcon

# Use try/except pattern for imports
try:
    from paths import get_default_db_path, get_app_dir, get_default_config_path, setup_logging
except ImportError:
    try:
        from .paths import get_default_db_path, get_app_dir, get_default_config_path, setup_logging
    except ImportError:
        # Final fallback
        print("Critical error: Could not import paths module")
        sys.exit(1)

# Register with window manager if available
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

# Thread-local storage for SQLite connections
import threading
thread_local = threading.local()

# Set up logging
setup_logging("purge_window", logging.INFO)
logger = logging.getLogger(__name__)

def load_stylesheet(app):
    """Load the application's stylesheet from a QSS file."""
    try:
        stylesheet_file = QFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark_style.qss"))
        if stylesheet_file.open(QIODevice.ReadOnly | QIODevice.Text):
            stream = QTextStream(stylesheet_file)
            app.setStyleSheet(stream.readAll())
            stylesheet_file.close()
            logger.debug("Stylesheet loaded successfully")
        else:
            logger.warning("Could not open stylesheet file")
    except Exception as e:
        logger.error(f"Error loading stylesheet: {e}")

def get_sqlite_connection() -> sqlite3.Connection:
    """Returns a thread-local SQLite connection."""
    if not hasattr(thread_local, "conn"):
        db_path = get_default_db_path()
        logger.debug(f"Creating new SQLite connection to {db_path} for thread {threading.current_thread().name}")
        thread_local.conn = sqlite3.connect(db_path, check_same_thread=False)
        thread_local.conn.row_factory = sqlite3.Row
    return thread_local.conn

# ============================================================
# Utility: Read configuration settings from config.ini
# ============================================================
def get_config():
    """Load and return configuration from config.ini."""
    try:
        import configparser
        config = configparser.ConfigParser()
        config_path = get_default_config_path()
        if os.path.exists(config_path):
            config.read(config_path)
            logger.debug(f"Configuration loaded from {config_path}")
        else:
            logger.warning(f"Configuration file not found at {config_path}")
        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        return None

# ============================================================
# Worker function: Check if a file exists.
# ============================================================
def check_file(record):
    """
    Check if a file exists in the filesystem.
    
    Args:
        record: tuple (photo_id, file_path)
        
    Returns:
        tuple: (record, exists)
    """
    photo_id, file_path = record
    exists = os.path.exists(file_path)
    logger.debug(f"Checked file for photo_id {photo_id}: exists={exists}")
    return (record, exists)

# ============================================================
# Delete a record from the database.
# ============================================================
def delete_record(photo_id):
    """
    Delete a record from the database by photo_id.
    
    Args:
        photo_id: The ID of the photo to delete
    """
    try:
        conn = get_sqlite_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM photos WHERE photo_id = ?", (photo_id,))
        conn.commit()
        logger.info(f"Record {photo_id} removed from database.")
    except sqlite3.Error as e:
        logger.error(f"Error deleting record {photo_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error deleting record {photo_id}: {e}")

class MainWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tag-AI Purge Missing Files")
        # Set the window size.
        self.resize(800, 600)
        try:
            from PySide6.QtGui import QIcon
            window_manager = get_window_manager()
            main_window = window_manager.get_window("main")
            if main_window and main_window.windowIcon():
                self.setWindowIcon(main_window.windowIcon())
        except Exception as e:
            logging.debug(f"Could not inherit icon from main window: {e}")
            
        # Create the main layout
        layout = QVBoxLayout(self)

        # Top section: Information on all missing files.
        self.info_label = QLabel("All missing files will be listed below.")
        layout.addWidget(self.info_label)
        
        self.info_list = QListWidget()
        self.info_list.setMinimumHeight(150)
        # Apply dark mode styling to the info_list widget.
        self.info_list.setStyleSheet("background-color: #2e2e2e; color: #f0f0f0; border: 1px solid #555555;")
        layout.addWidget(self.info_list)

        # Bottom section: Process one missing file at a time.
        self.current_frame = QFrame()
        self.current_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.current_frame.setStyleSheet("background-color: #333333; border-radius: 5px; padding: 10px;")
        
        current_layout = QVBoxLayout(self.current_frame)
        self.current_label = QLabel("Current file to process will appear here.")
        current_layout.addWidget(self.current_label)
        
        # Buttons for handling missing files
        btn_layout = QHBoxLayout()
        self.btn_remove = QPushButton("Remove")
        self.btn_skip = QPushButton("Skip")
        self.btn_remove_all = QPushButton("Remove All")
        self.btn_skip_all = QPushButton("Skip All")
        
        # Connect buttons to handlers
        self.btn_remove.clicked.connect(lambda: self.handle_missing_action("remove"))
        self.btn_skip.clicked.connect(lambda: self.handle_missing_action("skip"))
        self.btn_remove_all.clicked.connect(lambda: self.handle_missing_action("remove_all"))
        self.btn_skip_all.clicked.connect(lambda: self.handle_missing_action("skip_all"))
        
        # Add buttons to layout
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_skip)
        btn_layout.addWidget(self.btn_remove_all)
        btn_layout.addWidget(self.btn_skip_all)
        current_layout.addLayout(btn_layout)
        
        layout.addWidget(self.current_frame)

        # Status bar for feedback
        self.status_bar = QStatusBar()
        layout.addWidget(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Scan and Close buttons.
        scan_close_layout = QHBoxLayout()
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.scan_files)
        scan_close_layout.addWidget(self.scan_button)
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        scan_close_layout.addWidget(self.close_button)
        
        layout.addLayout(scan_close_layout)

        self.setLayout(layout)
        
        # Attributes for processing.
        self.missing_files = []
        self.current_missing_index = 0
        self.conn = None
        
        # Register with window manager
        try:
            window_manager = get_window_manager()
            window_manager.register_window("purge_window", self)
            logger.debug("Registered with window manager")
        except Exception as e:
            logger.error(f"Failed to register with window manager: {e}")

    def scan_files(self):
        """Scan the database for files that don't exist on disk."""
        # Clear fields and reset state for a new scan.
        self.info_list.clear()
        self.current_label.setText("")
        self.missing_files = []
        self.current_missing_index = 0
        
        # If a previous connection is open, close it.
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn = None
                logger.debug("Closed previous database connection")
            except Exception as e:
                logger.warning(f"Error closing previous connection: {e}")

        self.scan_button.setEnabled(False)
        self.status_bar.showMessage("Scanning for missing files...")
        self.info_label.setText("Scanning files...")
        
        # Get a fresh connection
        self.conn = get_sqlite_connection()
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT photo_id, file_path FROM photos")
            records = cursor.fetchall()
            logger.info(f"Found {len(records)} total records in database")
            self.status_bar.showMessage(f"Checking {len(records)} files...")
        except sqlite3.Error as e:
            error_msg = f"Error executing query: {e}"
            logger.error(error_msg)
            self.info_label.setText(error_msg)
            self.status_bar.showMessage("Error during scan")
            self.scan_button.setEnabled(True)
            return
        
        missing_files = []
        workers = min(os.cpu_count() or 4, 8)  # Use either CPU count or max 8 workers
        
        # Process in parallel for faster scanning
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(check_file, record): record for record in records}
            
            # Process results as they complete
            completed = 0
            total = len(futures)
            
            for future in as_completed(futures):
                completed += 1
                if completed % 50 == 0 or completed == total:
                    progress_pct = (completed * 100) // total
                    self.status_bar.showMessage(f"Checking files: {progress_pct}% ({completed}/{total})")
                    QApplication.processEvents()  # Allow UI updates
                
                try:
                    record, exists = future.result()
                    if not exists:
                        missing_files.append(record)
                except Exception as e:
                    logger.error(f"Error checking file: {e}")
        
        # Update UI with results
        self.info_label.setText(f"Scan complete. {len(missing_files)} missing files found.")
        self.status_bar.showMessage(f"Found {len(missing_files)} missing files")
        
        self.info_list.clear()
        if missing_files:
            self.missing_files = missing_files
            
            # Populate the top box with full list
            for photo_id, file_path in self.missing_files:
                self.info_list.addItem(f"Missing file: {file_path} (ID: {photo_id})")
            
            self.current_missing_index = 0
            self.show_next_missing_file()
        else:
            self.info_list.addItem("No missing files found.")
            self.current_label.setText("No missing files to process.")
            self.status_bar.showMessage("No missing files found")
        
        self.scan_button.setEnabled(True)

    def show_next_missing_file(self):
        """Display the next missing file for processing."""
        if self.current_missing_index < len(self.missing_files):
            photo_id, file_path = self.missing_files[self.current_missing_index]
            self.current_label.setText(f"Current file: {file_path} (ID: {photo_id})")
            self.status_bar.showMessage(f"Processing file {self.current_missing_index + 1} of {len(self.missing_files)}")
        else:
            self.current_label.setText("Missing file processing complete.")
            self.status_bar.showMessage("Processing complete")

    def handle_missing_action(self, action):
        """
        Handle user action for a missing file.
        
        Args:
            action: One of "remove", "skip", "remove_all", "skip_all"
        """
        if self.current_missing_index >= len(self.missing_files):
            logger.debug("No more missing files to process")
            return
        
        photo_id, file_path = self.missing_files[self.current_missing_index]
        
        if action == "remove":
            logger.info(f"Removing file {file_path} (ID: {photo_id})")
            delete_record(photo_id)
            # Remove from top list as well
            self.info_list.takeItem(self.current_missing_index)
            self.missing_files.pop(self.current_missing_index)
            self.status_bar.showMessage(f"Removed file with ID: {photo_id}")
        
        elif action == "skip":
            logger.info(f"Skipping file {file_path} (ID: {photo_id})")
            # Remove only the current item from bottom processing
            self.missing_files.pop(self.current_missing_index)
            self.info_list.takeItem(self.current_missing_index)
            self.status_bar.showMessage(f"Skipped file with ID: {photo_id}")
        
        elif action == "remove_all":
            count = len(self.missing_files)
            logger.info(f"Removing all {count} missing files")
            
            for missing in self.missing_files:
                pid, _ = missing
                delete_record(pid)
            
            self.info_list.clear()
            self.missing_files = []
            self.current_missing_index = 0
            self.status_bar.showMessage(f"Removed all {count} missing files")
        
        elif action == "skip_all":
            count = len(self.missing_files)
            logger.info(f"Skipping all {count} missing files")
            self.info_list.clear()
            self.missing_files = []
            self.current_missing_index = 0
            self.status_bar.showMessage(f"Skipped all {count} missing files")
        
        self.show_next_missing_file()

    def closeEvent(self, event):
        """Handle window close event."""
        logger.debug("Close event received")
        
        # Make sure to clean up resources
        if hasattr(self, 'conn') and self.conn:
            try:
                logger.debug("Closing database connection")
                self.conn = None
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")
        
        # Unregister from window manager
        try:
            window_manager = get_window_manager()
            window_manager.remove_window("purge_window")
            logger.debug("Unregistered from window manager")
        except Exception as e:
            logger.error(f"Error unregistering from window manager: {e}")
        
        event.accept()

# ============================================================
# Main function integrating scanning and GUI dialog prompts.
# ============================================================
def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    parser.add_argument("--delete", help="delete record with specified photo_id")
    args = parser.parse_args()
    
    # Configure logging based on debug flag
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging("purge_window", log_level)
    
    logger.info("Starting purge window application")
    
    # Handle direct delete command if specified
    if args.delete:
        logger.info(f"Direct delete mode for photo_id: {args.delete}")
        delete_record(args.delete)
        return 0
    
    # Start the GUI application
    app = QApplication.instance()
    created_new_app = False
    
    if app is None:
        logger.debug("Creating new QApplication instance")
        app = QApplication(sys.argv)
        created_new_app = True
    else:
        logger.debug("Using existing QApplication instance")
    
    # Apply the stylesheet
    load_stylesheet(app)
    
    # Create and show the main window
    main_window = MainWindow()
    main_window.show()
    
    # Return appropriate value based on whether we created a new app
    if created_new_app:
        logger.debug("Starting application event loop")
        return app.exec()
    else:
        logger.debug("Returning window reference")
        return main_window

if __name__ == '__main__':
    sys.exit(main())