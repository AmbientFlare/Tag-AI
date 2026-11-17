import sys
import os
import configparser
import logging
import time
import threading
import io
import signal  # Added for signal handling
from datetime import datetime
from glob import glob
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget, QMessageBox
from PySide6.QtCore import Qt, QFile, QIODevice, QTextStream, QObject, Signal
from PySide6.QtGui import QKeySequence, QIcon

# Import core utilities with backup options
try:
    from paths import get_default_config_path, get_log_dir, get_log_file_path, setup_logging
except ImportError:
    from .paths import get_default_config_path, get_log_dir, get_log_file_path, setup_logging
try:
    from global_signals import global_signals
except ImportError:
    from .global_signals import global_signals
try:
    from Module_loader import import_module
except ImportError:
    try:
        from .Module_loader import import_module
    except ImportError:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        try:
            from Module_loader import import_module
        except ImportError:
            import importlib
            import_module = importlib.import_module

try:
    from component_launcher import launch_module
except ImportError:
    from .component_launcher import launch_module

try:
    from window_manager import get_window_manager
except ImportError:
    from .window_manager import get_window_manager

# Custom signal class for thread communication
class ScanSignals(QObject):
    output = Signal(str)
    started = Signal()
    finished = Signal()
    error = Signal(str)

def load_stylesheet(app):
    """Loads a stylesheet from 'dark_style.qss' if available."""
    stylesheet_file = QFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark_style.qss"))
    if stylesheet_file.open(QIODevice.ReadOnly | QIODevice.Text):
        stream = QTextStream(stylesheet_file)
        app.setStyleSheet(stream.readAll())
        stylesheet_file.close()
    else:
        print("Warning: Unable to load stylesheet file 'dark_style.qss'.")

def delete_old_logs(log_file_pattern='scanner_*.log', config=None):
    current_time = time.time()
    retention_hours = float(config.get('settings', 'log_retention_hours', fallback='24')) if config else 24
    log_dir = get_log_dir()
    for log_file in glob(os.path.join(log_dir, log_file_pattern)):
        if os.path.exists(log_file):
            file_time = os.path.getmtime(log_file)
            if (current_time - file_time) > (retention_hours * 3600):
                try:
                    os.remove(log_file)
                    print(f"Deleted old log file: {log_file}")
                except OSError as e:
                    print(f"Error deleting log file: {e}")

# Load config first to get retention settings
config = configparser.ConfigParser()
config.read(get_default_config_path())

# Delete old logs and set up new log file with timestamp
delete_old_logs('scanner_*.log', config)
log_name = f"scanner_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
setup_logging(log_name, logging.INFO)
logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tag-AI Scanner")
        self.resize(1000, 800)
        try:
            from PySide6.QtGui import QIcon
            window_manager = get_window_manager()
            main_window = window_manager.get_window("main")
            if main_window and main_window.windowIcon():
                self.setWindowIcon(main_window.windowIcon())
        except Exception as e:
            logging.debug(f"Could not inherit icon from main window: {e}")

        # Main UI elements with shortcuts
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.run_scan_script)
        self.scan_button.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_R))

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        self.stop_button.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_S))

        self.output_text_edit = QTextEdit()
        self.output_text_edit.setReadOnly(True)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.handle_close_button)

        # Layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.scan_button)
        main_layout.addWidget(self.stop_button)
        main_layout.addWidget(self.output_text_edit)
        main_layout.addWidget(self.close_button)
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.statusBar().showMessage("Ready")

        # Thread and stop event
        self.scan_thread = None
        self.stop_event = threading.Event()  # Renamed stop_flag to stop_event for clarity
        self.signals = ScanSignals()

        # Connect signals
        self.signals.output.connect(self.display_output)
        self.signals.started.connect(self.handle_scan_started)
        self.signals.finished.connect(self.handle_scan_finished)
        self.signals.error.connect(self.handle_scan_error)

        # Set up signal handlers in the main thread
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Connect to global signals for cross-window communication
        global_signals.log_message.connect(self.display_output)
        
        # Load config with validation
        config_path = get_default_config_path()
        self.config = configparser.ConfigParser()
        if not os.path.exists(config_path):
            self.statusBar().showMessage("Warning: config.ini not found, using default 'local'")
            logging.warning("config.ini not found, using default 'local'")
            self.config['script_to_run'] = {'llm_script': 'local'}
        else:
            self.config.read(config_path)
            if 'script_to_run' not in self.config or 'llm_script' not in self.config['script_to_run']:
                self.statusBar().showMessage("Warning: Invalid config.ini, using default 'local'")
                logging.warning("Invalid config.ini, using default 'local'")
                self.config['script_to_run'] = {'llm_script': 'local'}
            else:
                self.statusBar().showMessage("Ready - Config loaded successfully")
                logging.info(f"Config loaded with llm_script: {self.config['script_to_run']['llm_script']}")

        # Register with window manager
        try:
            window_manager = get_window_manager()
            window_manager.register_window("scan_window", self)
        except Exception as e:
            logger.error(f"Error registering with window manager: {e}")

    def signal_handler(self, signum, frame):
        """Handle signals by setting the stop_event and initiating shutdown."""
        logging.info(f"Received signal {signum}. Initiating graceful shutdown...")
        self.stop_event.set()
        self.stop_scan()

    def run_scan_script(self):
        """Run the appropriate scan script as a module in a background thread"""
        if self.scan_thread and self.scan_thread.is_alive():
            QMessageBox.warning(self, "Scan In Progress", "A scan is already running!")
            return

        self.output_text_edit.clear()
        self.statusBar().showMessage("Loading config...")
        
        # Reload configuration before each scan
        config_path = get_default_config_path()
        self.config = configparser.ConfigParser()
        if os.path.exists(config_path):
            self.config.read(config_path)
            self.statusBar().showMessage("Config reloaded successfully")
            logging.info(f"Reloaded config with llm_script: {self.config.get('script_to_run', 'llm_script', fallback='local')}")
        
        script_choice = self.config.get('script_to_run', 'llm_script', fallback='local')

        if script_choice.lower() == 'local':
            module_name = "photo_ollama"
        elif script_choice.lower() == 'gemini':
            module_name = "photo_v02_gemini"
        else:
            QMessageBox.critical(self, "Error", "Invalid config value!")
            self.statusBar().showMessage("Error: Invalid config value")
            self.scan_button.setText("Invalid config!")
            logging.error(f"Invalid config value: {script_choice}")
            return

        self.stop_event.clear()  # Clear stop_event before starting

        def run_scan_module():
            try:
                module = import_module(module_name)
                original_stdout = sys.stdout
                original_stderr = sys.stderr
                logging.debug(f"Original stdout type: {type(original_stdout).__name__}")
                logging.debug(f"Original stderr type: {type(original_stderr).__name__}")

                class SignalRedirector:
                    def __init__(self, signal):
                        self.signal = signal
                        self.buffer = ""
                        self.original_stdout = None

                    def write(self, text):
                        if text and text.strip():
                            self.signal.output.emit(text)
                            if self.original_stdout and hasattr(self.original_stdout, 'write'):
                                self.original_stdout.write(text)
                        return len(text)

                    def flush(self):
                        if self.original_stdout and hasattr(self.original_stdout, 'flush'):
                            self.original_stdout.flush()

                self.signals.started.emit()

                try:
                    stdout_redirector = SignalRedirector(self.signals)
                    stderr_redirector = SignalRedirector(self.signals)
                    stdout_redirector.original_stdout = original_stdout
                    stderr_redirector.original_stderr = original_stderr
                    sys.stdout = stdout_redirector
                    sys.stderr = stderr_redirector

                    if hasattr(module, 'main'):
                        # Pass the stop_event to the module's main function
                        module.main(self.stop_event)
                    else:
                        self.signals.error.emit(f"Module {module_name} has no main function")

                finally:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
                    logging.debug("Restored original stdout and stderr")

                self.signals.finished.emit()

            except Exception as e:
                import traceback
                error_msg = f"Error running {module_name}: {e}\n{traceback.format_exc()}"
                logging.error(error_msg)
                self.signals.error.emit(error_msg)
                self.signals.finished.emit()

        self.scan_thread = threading.Thread(target=run_scan_module)
        self.scan_thread.daemon = True
        self.scan_thread.start()
        logging.info(f"Started scan with module: {module_name}")

    def stop_scan(self):
        """Stop the running scan thread."""
        if self.scan_thread and self.scan_thread.is_alive():
            self.stop_event.set()  # Set the stop event
            self.display_output("Stopping scan... Please wait for current operations to complete.")
            logging.info("Scan stop requested by user")
            self.statusBar().showMessage("Stopping scan...")

    def display_output(self, output):
        if output.strip():
            self.output_text_edit.append(output.rstrip())
            self.output_text_edit.ensureCursorVisible()

    def handle_scan_started(self):
        self.scan_button.setText("Scanning...")
        self.stop_button.setEnabled(True)
        self.statusBar().showMessage("Scanning...")

    def handle_scan_finished(self):
        self.scan_button.setText("Scan")
        self.stop_button.setEnabled(False)
        self.statusBar().showMessage("Ready - Scan completed")

    def handle_scan_error(self, error_msg):
        QMessageBox.critical(self, "Process Error", error_msg)
        self.statusBar().showMessage("Error during scan")
        self.scan_button.setText("Scan")
        self.stop_button.setEnabled(False)
        logging.error(error_msg)

    def handle_close_button(self):
        self.hide()

    def closeEvent(self, event):
        if self.scan_thread and self.scan_thread.is_alive():
            self.hide()
            self.statusBar().showMessage("Window hidden - scan still running")
            logging.info("Window hidden; thread still running")
            event.ignore()
        else:
            event.accept()

def main():
    app = QApplication.instance()
    created_new_app = False

    if app is None:
        app = QApplication(sys.argv)
        created_new_app = True

    load_stylesheet(app)
    main_window = MainWindow()
    main_window.show()

    if created_new_app:
        return app.exec()
    else:
        return main_window

if __name__ == '__main__':
    sys.exit(main())