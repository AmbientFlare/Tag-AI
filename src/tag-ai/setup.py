# setup.py
# Import changes to add at the top of setup.py
import ctypes
import os
import sys
import logging
import configparser
import subprocess
import traceback
import time
import re
import threading
import tempfile  # Added for get_temp_dir
import requests  # Added for HTTP downloads
from PySide6.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel, 
                             QPushButton, QHBoxLayout, QWidget, QTextEdit, 
                             QMessageBox, QProgressBar, QFrame, QScrollArea)
from PySide6.QtCore import Qt, QFile, QIODevice, QTextStream, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QTextCursor, QFont

# Import path utilities - use the try/except pattern
try:
    from paths import get_default_config_path, get_default_db_path, setup_logging, get_temp_dir
    from paths import get_app_dir, get_user_data_dir
except ImportError:
    from .paths import get_default_config_path, get_default_db_path, setup_logging, get_temp_dir
    from .paths import get_app_dir, get_user_data_dir

# Import dependency checking functions - use the try/except pattern
try:
    from depends import (
        check_and_install_gpu_support,
        is_cuda_installed,
        download_and_install_cuda_12_4_windows,
        check_and_install_cuda,
        check_ollama_installed,
        get_os_info,
        download_ollama_installer,
        install_ollama,
        install_llava_model,
        detect_gpu_type,
        is_rocm_installed,
        download_and_install_rocm
    )
except ImportError:
    from .depends import (
        check_and_install_gpu_support,
        is_cuda_installed,
        download_and_install_cuda_12_4_windows,
        check_and_install_cuda,
        check_ollama_installed,
        get_os_info,
        download_ollama_installer,
        install_ollama,
        install_llava_model,
        detect_gpu_type,
        is_rocm_installed,
        download_and_install_rocm
    )

# Setup logging - use setup_logging from paths.py
setup_logging("setup", logging.INFO)
logger = logging.getLogger(__name__)

def load_stylesheet(app):
    """Load the application's stylesheet."""
    stylesheet_file = QFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark_style.qss"))
    if stylesheet_file.open(QIODevice.ReadOnly | QIODevice.Text):
        stream = QTextStream(stylesheet_file)
        app.setStyleSheet(stream.readAll())
        stylesheet_file.close()
        logger.debug("Successfully loaded stylesheet from dark_style.qss")
    else:
        logger.warning("Failed to load stylesheet: dark_style.qss")

class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    started = Signal(str)
    progress = Signal(str)
    finished = Signal(bool, str)
    log = Signal(str, str)  # message, level (info, warning, error, success)
    needs_confirmation = Signal(str)  # confirmation_type

class SetupWorker(QObject):
    """Worker thread for performing setup tasks."""
    def __init__(self, task_func, description):
        super().__init__()
        self.signals = WorkerSignals()
        self.task_func = task_func
        self.description = description
        self.is_running = False
        logger.debug(f"Created SetupWorker for task: {description}")

    def handle_step_needs_confirmation(self, confirmation_type):
        """Handle when a step requires user confirmation."""
        if confirmation_type == "cuda_install":
            # Display a dialog box
            result = QMessageBox.information(
                None,  # Changed from self since this runs in worker thread
                "CUDA Installation",
                "A CUDA installation window has been launched.\n\n"
                "After installation completes, click 'Continue' below.",
                QMessageBox.Ok
            )
            
            # Then recheck if CUDA is installed
            step_widget = self.steps[self.current_step]
            step_widget.log("Verifying CUDA installation...", "info")
            
            if is_cuda_installed(step_widget.log):
                step_widget.log("✅ CUDA installation verified successfully.", "success")
                return True, "CUDA installation verified."
            else:
                step_widget.log("⚠️ CUDA installation could not be verified.", "warning")
                step_widget.log("You may need to restart your computer for CUDA to be fully activated.", "warning")
                # Still return True to continue setup
                return True, "Continuing setup, but CUDA may require restart."
        # Add return for unhandled cases
        return False, f"Unhandled confirmation type: {confirmation_type}"
   
    def run(self):
        """Execute the task function and emit signals."""
        self.is_running = True
        logger.info(f"Starting task: {self.description}")
        self.signals.started.emit(self.description)
        
        success = False
        result_message = ""
        
        try:
            # Run the task function with our log callback
            success, result_message = self.task_func(self.log)
            
            # Check if this requires confirmation from the user
            if isinstance(result_message, str) and result_message.startswith("requires_confirmation:"):
                # Extract the confirmation type
                confirmation_type = result_message.split(":", 1)[1]
                logger.info(f"Task requires user confirmation: {confirmation_type}")
                
                # Signal that we need confirmation
                self.signals.progress.emit(f"Waiting for user confirmation: {confirmation_type}")
                self.signals.needs_confirmation.emit(confirmation_type)
                
                # Since we're in a worker thread, we need to wait for the result
                # The main thread will set an event or variable that we can check
                # This implementation depends on how you want to handle this synchronization
                
                # Example using a simple polling approach:
                # (You'll need to define self.confirmation_result in __init__)
                wait_start = time.time()
                confirmation_timeout = 1800  # 30 minutes max wait time
                
                while self.is_running and not hasattr(self, 'confirmation_completed'):
                    # Sleep briefly to avoid burning CPU
                    time.sleep(0.5)
                    
                    # Check if we've timed out
                    if time.time() - wait_start > confirmation_timeout:
                        logger.warning(f"Confirmation timed out after {confirmation_timeout} seconds")
                        self.signals.log.emit("Confirmation timed out - proceeding with setup", "warning")
                        break
                
                # Get confirmation result if available
                if hasattr(self, 'confirmation_completed') and hasattr(self, 'confirmation_result'):
                    success = self.confirmation_result.get('success', False)
                    result_message = self.confirmation_result.get('message', 'Confirmation completed')
                    logger.info(f"Received confirmation result: {success}, {result_message}")
                else:
                    # Assume we should continue even without explicit confirmation
                    logger.warning("No confirmation result received, continuing with best effort")
                    success = True
                    result_message = "Continuing setup without explicit confirmation"
            
            logger.info(f"Task completed: {self.description} - Success: {success}")
            
        except Exception as e:
            error_msg = f"Error in task {self.description}: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            self.signals.log.emit(f"Error: {str(e)}", "error")
            self.signals.log.emit(traceback.format_exc(), "error")
            result_message = f"Failed: {str(e)}"
            success = False
        
        self.is_running = False
        self.signals.finished.emit(success, result_message)
        logger.debug(f"Worker finished for task: {self.description}")
    
    def log(self, message, level="info"):
        """Log a message with the specified level."""
        # Log to application logger with the correct level
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "success":
            logger.info(f"SUCCESS: {message}")
        else:  # Default to info
            logger.info(message)
            
        # Also emit signal for UI updates
        self.signals.log.emit(message, level)
        self.signals.progress.emit(message)

class StepWidget(QFrame):
    def __init__(self, title, description, parent=None, allow_skip=False):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setObjectName("setupStep")
        self.setStyleSheet("""
            QFrame#setupStep {
                border: 1px solid #3D3D3D;
                border-radius: 5px;
                background-color: #1E1E1E;
                padding: 10px;
                margin: 5px;
            }
        """)
        
        self.layout = QVBoxLayout(self)
        
        # Title and status
        header_layout = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self.title_label)
        
        self.status_label = QLabel("Pending")
        self.status_label.setStyleSheet("color: #A0A0A0;")
        header_layout.addWidget(self.status_label, 0, Qt.AlignRight)
        
        self.layout.addLayout(header_layout)
        
        # Description
        self.description_label = QLabel(description)
        self.description_label.setWordWrap(True)
        self.layout.addWidget(self.description_label)
        
        # Skip button (conditionally added)
        self.skip_button = None
        if allow_skip:
            skip_layout = QHBoxLayout()
            self.skip_button = QPushButton("Skip GPU Setup and Continue")
            self.skip_button.setStyleSheet("background-color: #664400; color: white;")
            self.skip_button.setToolTip("Skip GPU setup and proceed with CPU-only processing (slower)")
            skip_layout.addStretch()
            skip_layout.addWidget(self.skip_button)
            self.layout.addLayout(skip_layout)
            
            # Warning label about CPU-only mode
            self.warning_label = QLabel("⚠️ WARNING: Running without GPU acceleration will be significantly slower.\n"
                                        "The AI will still function, but image processing will take much longer.")
            self.warning_label.setStyleSheet("color: #FFA500; font-weight: bold;")
            self.warning_label.setWordWrap(True)
            self.layout.addWidget(self.warning_label)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)
        
        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        self.log_output.setVisible(False)
        self.layout.addWidget(self.log_output)
        
        self.setFixedHeight(160 if allow_skip else 120)  # Adjust initial height
    
    def set_status(self, status, color="#A0A0A0"):
        """Set the status text and color."""
        logger.debug(f"Step '{self.title_label.text()}' status changed to: {status}")
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {color};")
    
    def start(self):
        """Mark the step as started."""
        logger.info(f"Starting step: {self.title_label.text()}")
        self.set_status("Running", "#2A82DA")
        self.progress_bar.setVisible(True)
        self.log_output.setVisible(True)
        self.setFixedHeight(220)  # Expand to show logs
    
    def complete(self, success, message=""):
        """Mark the step as completed."""
        status = "Complete" if success else "Failed"
        logger.info(f"Completing step: {self.title_label.text()} - {status}")
        
        if success:
            self.set_status("Complete", "#4CAF50")
        else:
            self.set_status("Failed", "#F44336")
        
        self.progress_bar.setVisible(False)
        if message:
            self.log(message, "success" if success else "error")
    
    def log(self, message, level="info"):
        """Add a log message to the output."""
        # Map log levels to colors
        color = {
            "info": "#E0E0E0",    # Light gray
            "warning": "#FFC107",  # Amber
            "error": "#F44336",    # Red
            "success": "#4CAF50"   # Green
        }.get(level, "#E0E0E0")
        
        # Log to application logger with the correct level
        if level == "error":
            logger.error(f"Step '{self.title_label.text()}': {message}")
        elif level == "warning":
            logger.warning(f"Step '{self.title_label.text()}': {message}")
        elif level == "success":
            logger.info(f"Step '{self.title_label.text()}' SUCCESS: {message}")
        else:  # Default to info
            logger.info(f"Step '{self.title_label.text()}': {message}")
        
        # Update the UI
        cursor = self.log_output.textCursor()
        text_format = self.log_output.currentCharFormat()
        text_format.setForeground(QColor(color))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"{message}\n", text_format)
        self.log_output.setTextCursor(cursor)
        self.log_output.ensureCursorVisible()

class SetupWizard(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tag-AI Setup Wizard")
        self.resize(800, 700)
        logger.info("Initializing Tag-AI Setup Wizard")
        
        # Main layout
        self.layout = QVBoxLayout(self)
        
        # Heading and description
        self.heading = QLabel("Tag-AI Setup")
        self.heading.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.heading.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.heading)
        
        self.description = QLabel("This wizard will help you set up the Tag-AI application.")
        self.description.setStyleSheet("font-size: 14px;")
        self.description.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.description)
        
        # Progress indicator
        self.progress_label = QLabel("Setup Progress:")
        self.layout.addWidget(self.progress_label)
        
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.layout.addWidget(self.overall_progress)
        
        # Setup steps container
        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setSpacing(10)
        
        # Create step widgets
        logger.debug("Creating setup step widgets")
        self.steps = [
            StepWidget("1. Check GPU Software Installation", 
                    "Verifying GPU and installing necessary software.", 
                    allow_skip=True),  # Allow skipping for GPU step
            StepWidget("2. Check Ollama Installation", 
                    "Checking and installing Ollama for local LLM processing."),
            StepWidget("3. Install LLaVA Model", 
                    "Setting up the LLaVA vision-language model."),
            StepWidget("4. Setup Database", 
                    "Preparing the database for storing photo metadata and tags."),
            StepWidget("5. Configure Settings", 
                    "Setting up application configuration and finalizing the setup.")
        ]

        # Connect skip button for GPU step - correct connection
        if self.steps[0].skip_button:
            self.steps[0].skip_button.clicked.connect(self.skip_current_step)
    
        for step in self.steps:
            self.steps_layout.addWidget(step)
        
        # Make the steps container scrollable
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.steps_container)
        self.layout.addWidget(scroll_area)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.proceed_button = QPushButton("Start Setup")
        self.proceed_button.clicked.connect(self.proceed)
        button_layout.addWidget(self.proceed_button)
        
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        button_layout.addWidget(self.exit_button)
        
        self.layout.addLayout(button_layout)
        
        # Setup variables
        self.current_step = -1
        self.ollama_process = None
        self.current_worker = None
        
        # Define step functions correctly
        self.step_functions = [
            self._run_check_gpu_software,
            self._run_check_ollama,
            self._run_install_llava_model,
            self._run_setup_database,
            self._run_mark_setup_complete
        ]
        
        logger.info("Setup Wizard initialized and ready")
    
    # Wrapper methods to correctly call the module-level functions
    def _run_check_gpu_software(self, log_func):
        return check_gpu_software(log_func)
    def skip_current_step(self):
        """Skip the current step and immediately start the next one."""
        # First time user clicks skip button before starting setup
        if self.current_step == -1:
            # Move to first step and mark it as skipped
            self.current_step = 0
            step_widget = self.steps[self.current_step]
            
            # Update the UI for the skipped step
            step_widget.set_status("Skipped", "#FFA500")  # Orange color for skipped
            step_widget.log("⚠️ GPU setup skipped. Using CPU-only mode.", "warning")
            step_widget.log("⚠️ WARNING: Processing will be significantly slower without GPU acceleration.", "warning")
            
            # Update overall progress
            progress_value = ((self.current_step + 1) * 100) // len(self.step_functions)
            self.overall_progress.setValue(progress_value)
            
            # Automatically move to next step
            self.current_step += 1
            self.run_step(self.current_step)
        else:
            # User clicks skip during GPU setup
            step_widget = self.steps[self.current_step]
            
            # Log skipping in the current step
            step_widget.log("⚠️ GPU setup skipped. Using CPU-only mode.", "warning")
            step_widget.log("⚠️ WARNING: Processing will be significantly slower without GPU acceleration.", "warning")
            
            # Update UI for the skipped step
            step_widget.set_status("Skipped", "#FFA500")
            step_widget.progress_bar.setVisible(False)
            
            # Stop current worker if it's running
            if hasattr(self, 'current_worker') and self.current_worker and hasattr(self.current_worker, 'is_running') and self.current_worker.is_running:
                if hasattr(self.current_worker, 'stop_event') and self.current_worker.stop_event:
                    self.current_worker.stop_event.set()
            
            # Move to next step
            self.current_step += 1
            
            # Make sure we haven't gone past the end
            if self.current_step < len(self.step_functions):
                # Start the next step
                self.run_step(self.current_step)
            else:
                # If we're at the end, update the button
                self.proceed_button.setText("Finish")
                self.proceed_button.setEnabled(True)

    def handle_confirmation_request(self, confirmation_type):
        """Handle a confirmation request from a worker thread.

        Args:
            confirmation_type (str): The type of confirmation request (e.g., 'cuda_install', 'rocm_install').
        """
        logger.info(f"Handling confirmation request: {confirmation_type}")

        if not hasattr(self, 'current_worker') or self.current_worker is None:
            logger.error("No current worker available to handle confirmation")
            return

        if confirmation_type == "cuda_install":
            result = QMessageBox.information(
                self,
                "CUDA Installation",
                "A CUDA installation has been launched.\n\n"
                "After the installation completes, click 'Continue'.",
                QMessageBox.Ok
            )

            if result != QMessageBox.Ok:
                self.current_worker.confirmation_completed = True
                self.current_worker.confirmation_result = {
                    'success': False,
                    'message': "User canceled the confirmation"
                }
                return

            try:
                cuda_installed = is_cuda_installed(lambda msg, level: self.steps[self.current_step].log(msg, level))
                self.current_worker.confirmation_completed = True
                self.current_worker.confirmation_result = {
                    'success': cuda_installed,
                    'message': "CUDA installation verified" if cuda_installed else "CUDA installation not verified"
                }
                if not cuda_installed:
                    self.steps[self.current_step].log(
                        "⚠️ CUDA installation couldn't be verified. You may need to restart your computer.",
                        "warning"
                    )
            except Exception as e:
                logger.error(f"Error verifying CUDA installation: {e}")
                self.current_worker.confirmation_completed = True
                self.current_worker.confirmation_result = {
                    'success': False,
                    'message': f"Error verifying CUDA: {e}"
                }

        elif confirmation_type == "rocm_install":
            # Handle ROCm confirmation similarly
            logger.info("ROCm installation confirmation not yet implemented")
            self.current_worker.confirmation_completed = True
            self.current_worker.confirmation_result = {
                'success': False,
                'message': "ROCm confirmation not implemented"
            }

        else:
            logger.warning(f"Unknown confirmation type: {confirmation_type}")

    def _run_check_ollama(self, log_func):
            return check_ollama(log_func)
    
    def _run_install_llava_model(self, log_func):
        # Create a list to store the process by reference
        ollama_process_ref = [None]
        result = install_llava_model(log_func, ollama_process_ref)
        # Store the process in the instance if one was created
        if ollama_process_ref[0]:
            self.ollama_process = ollama_process_ref[0]
        return result
    
    def _run_setup_database(self, log_func):
        return setup_database(log_func)
    
    def _run_mark_setup_complete(self, log_func):
        return mark_setup_complete(log_func)
        
    def proceed(self):
        """Handle the proceed button click."""
        if self.current_step == -1:
            logger.info("Starting the setup process from the beginning")
            self.current_step = 0
            self.run_step(self.current_step)
        elif self.current_step < len(self.step_functions) - 1:
            logger.info(f"Moving to setup step {self.current_step + 1}")
            self.current_step += 1
            self.run_step(self.current_step)
        else:
            logger.info("Setup completed successfully, accepting dialog")
            self.accept()
    
    def run_step(self, step_index):
        """Run the specified setup step."""
        logger.info(f"Running setup step {step_index + 1}: {self.steps[step_index].title_label.text()}")
        self.proceed_button.setEnabled(False)
        step_widget = self.steps[step_index]
        step_widget.start()
        
        # Update progress
        progress_value = (step_index * 100) // len(self.step_functions)
        logger.debug(f"Setting overall progress to {progress_value}%")
        self.overall_progress.setValue(progress_value)
        
        # Run the step function in a worker thread
        self.current_worker = SetupWorker(
            self.step_functions[step_index],
            f"Step {step_index + 1}: {step_widget.title_label.text()}"
        )
        
        # Connect signals
        self.current_worker.signals.log.connect(
            lambda msg, level: step_widget.log(msg, level)
        )
        self.current_worker.signals.finished.connect(
            lambda success, msg: self.handle_step_completed(success, msg)
        )
        
        # ADD THIS NEW CONNECTION HERE:
        self.current_worker.signals.needs_confirmation.connect(
            self.handle_confirmation_request
        )
        
        # Start the worker thread
        worker_thread = threading.Thread(target=self.current_worker.run)
        worker_thread.daemon = True
        worker_thread.start()
        logger.debug(f"Started worker thread for step {step_index + 1}")
    
    def handle_step_completed(self, success, message):
        """Handle completion of a setup step."""
        step_widget = self.steps[self.current_step]
        step_name = step_widget.title_label.text()
        
        if success:
            logger.info(f"Step {self.current_step + 1} ({step_name}) completed successfully")
        else:
            logger.error(f"Step {self.current_step + 1} ({step_name}) failed: {message}")
            
        step_widget.complete(success, message)
        
        if success:
            if self.current_step < len(self.step_functions) - 1:
                self.proceed_button.setText("Next Step")
                logger.debug("Updated button text to 'Next Step'")
            else:
                self.proceed_button.setText("Finish")
                logger.debug("Updated button text to 'Finish'")
            self.proceed_button.setEnabled(True)
        else:
            self.proceed_button.setEnabled(False)
            logger.warning(f"Step {step_name} failed, showing retry dialog")
            result = QMessageBox.question(
                self, "Step Failed",
                f"The step '{step_name}' has failed.\n\n{message}\n\nDo you want to retry?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if result == QMessageBox.Yes:
                logger.info(f"User chose to retry step {step_name}")
                self.run_step(self.current_step)
            else:
                logger.info("User chose not to retry, exiting setup")
                self.reject()
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        logger.info("Setup wizard closing, cleaning up resources...")
        if self.ollama_process:
            try:
                logger.info(f"Stopping LLaVA model process (PID: {self.ollama_process.pid})...")
                self.ollama_process.terminate()
                success = self.ollama_process.wait(timeout=5)
                logger.info(f"LLaVA process terminated with exit code: {success}")
            except subprocess.TimeoutExpired:
                logger.warning("Timeout waiting for LLaVA process to terminate, killing process...")
                self.ollama_process.kill()
            except Exception as e:
                logger.warning(f"Error stopping LLaVA model process: {e}")
        logger.info("Setup wizard closed")
        event.accept()
        
    def proceed(self):
        """Handle the proceed button click."""
        if self.current_step == -1:
            logger.info("Starting the setup process from the beginning")
            self.current_step = 0
            self.run_step(self.current_step)
        elif self.current_step < len(self.step_functions) - 1:
            logger.info(f"Moving to setup step {self.current_step + 1}")
            self.current_step += 1
            self.run_step(self.current_step)
        else:
            logger.info("Setup completed successfully, accepting dialog")
            self.accept()
    
    def run_step(self, step_index):
        """Run the specified setup step."""
        logger.info(f"Running setup step {step_index + 1}: {self.steps[step_index].title_label.text()}")
        self.proceed_button.setEnabled(False)
        step_widget = self.steps[step_index]
        step_widget.start()
        
        # Update progress
        progress_value = (step_index * 100) // len(self.step_functions)
        logger.debug(f"Setting overall progress to {progress_value}%")
        self.overall_progress.setValue(progress_value)
        
        # Run the step function in a worker thread
        self.current_worker = SetupWorker(
            self.step_functions[step_index],
            f"Step {step_index + 1}: {step_widget.title_label.text()}"
        )
        
        # Connect signals
        self.current_worker.signals.log.connect(
            lambda msg, level: step_widget.log(msg, level)
        )
        self.current_worker.signals.finished.connect(
            lambda success, msg: self.handle_step_completed(success, msg)
        )
        
        # Start the worker thread
        worker_thread = threading.Thread(target=self.current_worker.run)
        worker_thread.daemon = True
        worker_thread.start()
        logger.debug(f"Started worker thread for step {step_index + 1}")
    
    def handle_step_completed(self, success, message):
        """Handle completion of a setup step."""
        step_widget = self.steps[self.current_step]
        step_name = step_widget.title_label.text()
        
        if success:
            logger.info(f"Step {self.current_step + 1} ({step_name}) completed successfully")
        else:
            logger.error(f"Step {self.current_step + 1} ({step_name}) failed: {message}")
            
        step_widget.complete(success, message)
        
        if success:
            if self.current_step < len(self.step_functions) - 1:
                self.proceed_button.setText("Next Step")
                logger.debug("Updated button text to 'Next Step'")
            else:
                self.proceed_button.setText("Finish")
                logger.debug("Updated button text to 'Finish'")
            self.proceed_button.setEnabled(True)
        else:
            self.proceed_button.setEnabled(False)
            logger.warning(f"Step {step_name} failed, showing retry dialog")
            result = QMessageBox.question(
                self, "Step Failed",
                f"The step '{step_name}' has failed.\n\n{message}\n\nDo you want to retry?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if result == QMessageBox.Yes:
                logger.info(f"User chose to retry step {step_name}")
                self.run_step(self.current_step)
            else:
                logger.info("User chose not to retry, exiting setup")
                self.reject()
    
def check_gpu_software(log_func):
    """
    Check GPU type and install appropriate drivers/libraries.
    
    Args:
        log_func: Function to log messages
        
    Returns:
        tuple: (success, message)
    """
    log_func("Starting GPU detection and software setup...", "info")
    
    try:
        # Handle macOS as a special case first
        if sys.platform == "darwin":
            log_func("Running on macOS - using Metal API for GPU acceleration.", "info")
            log_func("No additional GPU software installation required on Mac.", "info")
            return True, "Mac system detected. Using Metal API for acceleration."
        
        # For other platforms, detect GPU type
        gpu_type = detect_gpu_type(log_func)
        log_func(f"Detected GPU type: {gpu_type}", "info")
        
        # Handle each GPU type
        if gpu_type == "NVIDIA":
            log_func("Processing NVIDIA GPU path...", "info")
            
            # Check if CUDA is already installed
            if is_cuda_installed(log_func):
                log_func("✅ CUDA is already installed and ready for use.", "success")
                return True, "CUDA is properly installed for NVIDIA GPU."
            else:
                log_func("CUDA not found. Need to install CUDA for NVIDIA GPU.", "info")
                
                # Platform-specific CUDA installation
                if os.name == "nt":  # Windows
                    try:
                        log_func("Installing CUDA for NVIDIA GPU on Windows...", "info")
                        log_func("A separate installer window will appear with UAC prompt.", "info")
                        log_func("Please complete the CUDA installation when prompted.", "info")
                        
                        # Launch the installer using ShellExecute (non-blocking)
                        cuda_url = "https://developer.download.nvidia.com/compute/cuda/12.4.0/local_installers/cuda_12.4.0_551.61_windows.exe"
                        installer_path = os.path.join(get_temp_dir(), "cuda_12.4.0_551.61_windows.exe")
                        
                        # Download if needed
                        if not os.path.exists(installer_path):
                            log_func("Downloading CUDA installer...", "info")
                            response = requests.get(cuda_url, stream=True)
                            response.raise_for_status()
                            
                            # Show download progress
                            total_size = int(response.headers.get('content-length', 0))
                            downloaded = 0
                            last_percent = 0
                            
                            with open(installer_path, "wb") as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        
                                        # Update progress every 5%
                                        if total_size > 0:
                                            percent = (downloaded * 100) // total_size
                                            if percent >= last_percent + 5:
                                                log_func(f"Download progress: {percent}%", "info")
                                                last_percent = percent
                            
                            log_func("✅ Download completed successfully.", "info")
                        
                        # Launch installer with ShellExecute
                        log_func("Launching CUDA installer with elevation...", "info")
                        ctypes.windll.shell32.ShellExecuteW(None, "open", installer_path, "/s", None, 1)
                        
                        # Signal that we need user confirmation after installation
                        return True, "requires_confirmation:cuda_install"
                        
                    except Exception as e:
                        log_func(f"❌ Error during CUDA installation process: {e}", "error")
                        log_func("You can skip GPU setup and continue with CPU-only mode, but processing will be slower.", "warning")
                        return False, f"Error installing CUDA: {e}"
                
                elif sys.platform.startswith("linux"):  # Linux
                    log_func("For Linux, CUDA installation requires manual steps:", "info")
                    log_func("1. Visit https://developer.nvidia.com/cuda-downloads", "info")
                    log_func("2. Select your Linux distribution and follow installation instructions", "info")
                    log_func("3. After installation, restart your computer", "info")
                    return False, "Manual CUDA installation required for Linux."
        
        elif gpu_type == "AMD":
            log_func("Processing AMD GPU path...", "info")
            
            # Check if ROCm is already installed
            if is_rocm_installed(log_func):
                log_func("✅ ROCm is already installed for AMD GPU.", "success")
                return True, "ROCm is properly installed for AMD GPU."
            else:
                log_func("ROCm not found. Need to install it for AMD GPU.", "info")
                
                # Platform-specific ROCm installation
                if os.name == "nt":  # Windows
                    try:
                        log_func("Installing ROCm for AMD GPU on Windows...", "info")
                        success = download_and_install_rocm(log_func)
                        
                        if success:
                            log_func("✅ ROCm instructions provided successfully.", "success")
                            return True, "requires_confirmation:rocm_install"
                        else:
                            log_func("❌ ROCm installation instructions failed.", "warning")
                            log_func("You can skip GPU setup and continue with CPU-only mode, but processing will be slower.", "warning")
                            return False, "Failed to provide ROCm installation instructions."
                    except Exception as e:
                        log_func(f"❌ Error during ROCm installation process: {e}", "error")
                        log_func("You can skip GPU setup and continue with CPU-only mode, but processing will be slower.", "warning")
                        return False, f"Error installing ROCm: {e}"
                
                elif sys.platform.startswith("linux"):  # Linux
                    log_func("For Linux, ROCm installation requires manual steps:", "info")
                    log_func("1. Visit https://rocm.docs.amd.com/en/latest/deploy/linux/index.html", "info")
                    log_func("2. Select your Linux distribution and follow installation instructions", "info")
                    log_func("3. After installation, restart your computer", "info")
                    return False, "Manual ROCm installation required for Linux."
        
        else:  # Unknown or unsupported GPU type
            log_func("No supported GPU detected or GPU type unknown.", "warning")
            log_func("⚠️ CPU-only mode will be significantly slower for AI image processing.", "warning")
            log_func("⚠️ If you have a compatible GPU, it's strongly recommended to set it up for better performance.", "warning")
            log_func("You may continue without GPU acceleration, but image tagging will take much longer.", "info")
            return False, "No supported GPU detected. CPU-only mode will be significantly slower for AI processing."
            
    except Exception as e:
        log_func(f"❌ Error during GPU detection or setup: {e}", "error")
        import traceback
        log_func(traceback.format_exc(), "error")
        log_func("You can continue in CPU-only mode, but performance will be significantly reduced.", "warning")
        return False, f"GPU setup error: {e}. Consider skipping and using CPU-only mode."

def check_ollama(log_func):
    """Check and install Ollama if necessary."""
    log_func("Checking Ollama installation...", "info")
    
    try:
        # First check if Ollama is already installed
        log_func("Verifying if Ollama is already installed...", "info")
        if check_ollama_installed(log_func):
            log_func("✅ Ollama is already installed and in PATH.", "success")
            return True, "Ollama is properly installed."
        else:
            log_func("⚠️ Ollama not found in PATH. Starting installation process...", "warning")
            
            # Get OS information for platform-specific installation
            os_name, architecture = get_os_info()
            log_func(f"Detected OS: {os_name}, Architecture: {architecture}", "info")
            
            # Handle different installation paths based on OS
            installer_path = None
            if os_name == "linux":
                log_func("Linux detected, will use installation script instead of installer package", "info")
                success = install_ollama(os_name, None, log_func)
            else:
                log_func("Downloading Ollama installer for your platform...", "info")
                os_type, installer_path = download_ollama_installer(os_name, architecture, log_func)
                
                if not os_type or not installer_path and os_name != "linux":
                    log_func("❌ Failed to determine download URL or download installer for Ollama", "error")
                    return False, "Failed to download Ollama installer"
                
                log_func(f"Running Ollama installer for {os_type or os_name}...", "info")
                success = install_ollama(os_type or os_name, installer_path, log_func)
            
            # Verify installation was successful
            log_func("Verifying Ollama installation...", "info")
            time.sleep(5)  # Give some time for installation to complete and PATH to update
            
            if success and check_ollama_installed(log_func):
                log_func("✅ Ollama installed successfully and verified in PATH.", "success")
                return True, "Ollama was installed successfully."
            elif success:
                log_func("⚠️ Ollama installer completed but 'ollama' command not found in PATH.", "warning")
                log_func("You may need to restart your system or manually add Ollama to your PATH.", "info")
                # Still return True because installation completed
                return True, "Ollama installed but not in PATH. You may need to restart your system."
            else:
                log_func("❌ Ollama installation failed.", "error")
                return False, "Ollama installation failed."
    except Exception as e:
        log_func(f"❌ Error checking/installing Ollama: {e}", "error")
        log_func(traceback.format_exc(), "error")
        return False, f"Ollama installation error: {e}"

def install_llava_model(log_func, ollama_process_ref=None):
    """Install the LLaVA model for image analysis with improved progress tracking."""
    log_func("Starting LLaVA model installation...", "info")
    
    try:
        # No need to check if model exists first - just run 'ollama pull llava'
        # This command is idempotent - it will install if needed or verify if already present
        log_func("Running 'ollama pull llava' to download or verify the model...", "info")
        log_func("This may take several minutes depending on your internet connection and hardware.", "info")
        
        import subprocess
        import threading
        import queue
        import time
        
        # Queue for capturing output
        output_queue = queue.Queue()
        
        # Flag for signaling completion
        is_completed = threading.Event()
        exit_code = [None]  # Use a list to store mutable state
        
        def run_ollama_pull():
            try:
                # Start the process
                process = subprocess.Popen(
                    ["ollama", "pull", "llava"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    encoding='utf-8',
                    errors='ignore'  # Ignore decoding errors
                )
                
                # Store the process reference if provided
                if ollama_process_ref is not None:
                    ollama_process_ref[0] = process
                
                # Read output lines and put them in the queue
                for line in iter(process.stdout.readline, ''):
                    if line.strip():
                        output_queue.put(line.strip())
                
                # Wait for process to complete and store the exit code
                exit_code[0] = process.wait()
                
            except Exception as e:
                output_queue.put(f"Error in Ollama pull thread: {e}")
                exit_code[0] = 1
            finally:
                is_completed.set()
        
        # Start Ollama pull in a separate thread
        thread = threading.Thread(target=run_ollama_pull)
        thread.daemon = True
        thread.start()
        
        # Process and display output from the queue
        last_percentage = 0
        last_update_time = time.time()
        
        # Monitor until completed or timeout (30 minutes max)
        timeout = 30 * 60  # 30 minutes in seconds
        start_time = time.time()
        
        while not is_completed.is_set() or not output_queue.empty():
            # Check for timeout
            if time.time() - start_time > timeout:
                log_func("⚠️ Installation timed out after 30 minutes.", "warning")
                break
            
            try:
                # Get output with timeout to prevent blocking forever
                line = output_queue.get(timeout=1.0)
                
                # Check for command not found error
                if "command not found" in line.lower():
                    log_func("❌ Ollama command not found. Please make sure Ollama is installed.", "error")
                    return False, "Ollama not found. Install it before continuing."
                
                # Check for pulling/progress information
                if "pulling" in line and "..." in line and "%" in line:
                    try:
                        # Extract progress information
                        parts = line.split("...")
                        if len(parts) >= 2:
                            # Extract percentage if present
                            percentage_parts = parts[1].split("%")
                            if len(percentage_parts) >= 1:
                                percentage_text = percentage_parts[0].strip()
                                # Remove non-digit characters and convert to int
                                percentage = int(''.join(filter(str.isdigit, percentage_text)))
                                
                                # Only log significant progress changes
                                if percentage > last_percentage + 9 or time.time() - last_update_time > 5:
                                    log_func(f"Download progress: {percentage}% - {parts[0].strip()}", "info")
                                    last_percentage = percentage
                                    last_update_time = time.time()
                    except (IndexError, ValueError):
                        # If we can't parse percentage, just log the line occasionally
                        if time.time() - last_update_time > 10:
                            log_func(f"Progress: {line}", "info")
                            last_update_time = time.time()
                
                # Log other important status messages
                elif any(keyword in line.lower() for keyword in ["verifying", "writing manifest"]):
                    log_func(line, "info")
                elif "success" in line.lower():
                    log_func("✅ Model installation successful!", "success")
                elif any(keyword in line.lower() for keyword in ["error", "warning", "fail"]):
                    log_func(f"Ollama output: {line}", "warning")
            
            except queue.Empty:
                # No new output, continue waiting
                continue
        
        # Check the exit code to determine success
        if exit_code[0] == 0:
            log_func("✅ LLaVA model installed successfully.", "success")
            return True, "LLaVA model was installed successfully."
        else:
            log_func(f"❌ LLaVA model installation failed with exit code {exit_code[0]}", "error")
            return False, f"LLaVA model installation failed with exit code {exit_code[0]}"
            
    except Exception as e:
        log_func(f"❌ Error during LLaVA model installation: {e}", "error")
        import traceback
        log_func(traceback.format_exc(), "error")
        return False, f"Error during LLaVA model installation: {e}"


def setup_database(log_func):
    """Set up the database."""
    log_func("Starting database setup...", "info")
    
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        user_db_path = get_default_db_path()
        log_func(f"User database path: {user_db_path}", "info")

        # Verify database has the correct schema by checking for required tables
        log_func("Verifying database schema...", "info")
        import sqlite3
        try:
            conn = sqlite3.connect(user_db_path)
            cursor = conn.cursor()
            
            # Check for SQLite version
            cursor.execute("SELECT sqlite_version()")
            version = cursor.fetchone()[0]
            log_func(f"SQLite version: {version}", "info")
            
            # Check which tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            log_func(f"Found tables: {', '.join(tables)}", "info")
            
            # Define required tables
            required_tables = ['photos', 'tags', 'photo_tags']
            missing_tables = [table for table in required_tables if table not in tables]
            
            if missing_tables:
                log_func(f"⚠️ Database is missing required tables: {', '.join(missing_tables)}", "warning")
                
                # Look for schema.sql to create the missing tables
                schema_candidates = [
                    os.path.join(current_dir, "..", "schema.sql"),
                    os.path.join(current_dir, "schema.sql"),
                    os.path.join(current_dir, "..", "..", "schema.sql"),
                ]
                schema_file = next((path for path in schema_candidates if os.path.exists(path)), None)
                
                if schema_file:
                    log_func(f"Found schema file at {schema_file}", "info")
                    log_func("Creating database schema from schema.sql...", "info")
                    with open(schema_file, 'r') as f:
                        schema_sql = f.read()
                    
                    # Execute the schema SQL
                    cursor.executescript(schema_sql)
                    conn.commit()
                    
                    # Verify tables were created
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    new_tables = [row[0] for row in cursor.fetchall()]
                    log_func(f"Tables after schema creation: {', '.join(new_tables)}", "info")
                    
                    missing_tables = [table for table in required_tables if table not in new_tables]
                    if missing_tables:
                        log_func(f"❌ Still missing tables after schema creation: {', '.join(missing_tables)}", "error")
                        return False, f"Failed to create all required tables: {', '.join(missing_tables)}"
                    else:
                        log_func("✅ Database schema created successfully.", "success")
                else:
                    log_func("❌ Schema file not found.", "error")
                    
                    # Try to create tables manually as a last resort
                    log_func("Attempting to create tables manually...", "info")
                    try:
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS photos (
                                photo_id TEXT PRIMARY KEY,
                                file_path TEXT,
                                date_taken TEXT,
                                file_hash TEXT UNIQUE
                            )
                        """)
                        
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS tags (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                tag TEXT UNIQUE
                            )
                        """)
                        
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS photo_tags (
                                photo_id TEXT,
                                tag_id INTEGER,
                                PRIMARY KEY (photo_id, tag_id),
                                FOREIGN KEY (photo_id) REFERENCES photos(photo_id) ON DELETE CASCADE,
                                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                            )
                        """)
                        
                        conn.commit()
                        log_func("✅ Tables created manually.", "success")
                    except Exception as e:
                        log_func(f"❌ Failed to create tables manually: {e}", "error")
                        return False, f"Database schema creation failed: {e}"
            else:
                log_func("✅ All required tables present in database.", "success")
            
            # Check if FTS5 extension is available
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='photos_fts'")
            if not cursor.fetchone():
                log_func("FTS virtual table not found, checking if FTS5 is available...", "info")
                try:
                    cursor.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')")
                    fts5_available = cursor.fetchone()[0]
                    if fts5_available:
                        log_func("FTS5 is available, creating photos_fts virtual table...", "info")
                        try:
                            cursor.execute("""
                                CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts 
                                USING fts5(photo_id, file_path, date_taken, tags, content='photos', content_rowid='photo_id')
                            """)
                            conn.commit()
                            log_func("✅ Created FTS5 virtual table.", "success")
                        except Exception as e:
                            log_func(f"⚠️ Could not create FTS5 virtual table: {e}", "warning")
                    else:
                        log_func("⚠️ FTS5 is not available in this SQLite build.", "warning")
                except Exception as e:
                    log_func(f"⚠️ Could not check for FTS5 availability: {e}", "warning")
            
            conn.close()
            log_func("✅ Database setup and verification completed successfully.", "success")
            return True, "Database is properly set up."
            
        except sqlite3.Error as e:
            log_func(f"❌ SQLite error during database setup: {e}", "error")
            return False, f"Database error: {e}"
            
    except Exception as e:
        log_func(f"❌ Error setting up database: {e}", "error")
        log_func(traceback.format_exc(), "error")
        return False, f"Database setup error: {e}"

def mark_setup_complete(log_func):
    """Mark setup as complete in the configuration file."""
    log_func("Finalizing setup and updating configuration...", "info")
    
    try:
        # Get configuration file path
        config = configparser.ConfigParser()
        config_path = get_default_config_path()
        log_func(f"Configuration file path: {config_path}", "info")
        
        # Ensure config directory exists
        config_dir = os.path.dirname(config_path)
        if not os.path.exists(config_dir):
            log_func(f"Creating config directory: {config_dir}", "info")
            os.makedirs(config_dir, exist_ok=True)
        
        # Check if config file already exists
        if os.path.exists(config_path):
            log_func("Reading existing configuration file...", "info")
            config.read(config_path)
            log_func(f"Found {len(config.sections())} sections in existing config", "info")
        else:
            log_func("Configuration file does not exist, will create a new one", "info")
        
        # Add or update setup section
        if "setup" not in config:
            log_func("Creating [setup] section in configuration...", "info")
            config["setup"] = {}
        
        # Mark setup as complete
        config["setup"]["setup_complete"] = "true"
        log_func("Setting setup_complete=true", "info")
        
        # Record GPU setup status
        try:
            # Get a reference to the SetupWizard instance to check if GPU was skipped
            # This assumes this function is called as a method or has access to 'self'
            wizard_instance = None
            current_frame = sys._getframe(1)
            if 'self' in current_frame.f_locals:
                wizard_instance = current_frame.f_locals['self']
            
            # Check if GPU setup was skipped
            gpu_setup_skipped = False
            if wizard_instance and hasattr(wizard_instance, 'steps') and len(wizard_instance.steps) > 0:
                first_step = wizard_instance.steps[0]
                if first_step.status_label.text() == "Skipped":
                    gpu_setup_skipped = True
                    log_func("Detected that GPU setup was skipped", "info")
            
            # Record GPU information
            config["setup"]["gpu_setup_skipped"] = str(gpu_setup_skipped).lower()
            
            # Detect GPU even if setup was skipped (for information purposes)
            gpu_type = detect_gpu_type(log_func)
            config["setup"]["gpu_type"] = gpu_type
            config["setup"]["gpu_acceleration"] = str(gpu_type in ["NVIDIA", "AMD", "Mac"]).lower()
            log_func(f"Recorded GPU type: {gpu_type}", "info")
            
            if gpu_setup_skipped:
                log_func("Note: GPU acceleration may not be fully functional since setup was skipped", "warning")
        except Exception as e:
            log_func(f"Warning: Could not record GPU information: {e}", "warning")
            config["setup"]["gpu_acceleration"] = "false"
            config["setup"]["gpu_setup_skipped"] = "unknown"
        
        # Add initial configuration sections if they don't exist
        sections_to_add = {
            "watch": {
                "folder": os.path.expanduser("~/Pictures")
            },
            "image_processing": {
                "target_max_size_mb": "10"
            },
            "tagger_ollama": {
                "ollama_endpoint": "http://localhost:11434/api/generate",
                "model_name": "llava"
            },
            "script_to_run": {
                "llm_script": "local"
            },
            "tagger_gemini": {
                "gemini_api_key": "",
                "paid_version": "false",
                "max_tags": "50",
                "confidence_threshold": "0.7",
                "max_image_size": "1024"
            }
        }
        
        for section, options in sections_to_add.items():
            if section not in config:
                log_func(f"Adding default [{section}] section...", "info")
                config[section] = {}
                for key, value in options.items():
                    config[section][key] = value
                    log_func(f"  Setting {section}.{key} = {value}", "info")
            else:
                log_func(f"Section [{section}] already exists, checking for missing keys...", "info")
                for key, value in options.items():
                    if key not in config[section]:
                        log_func(f"  Adding missing {section}.{key} = {value}", "info")
                        config[section][key] = value
        
        # Write the updated configuration
        log_func(f"Writing updated configuration to {config_path}...", "info")
        with open(config_path, "w") as configfile:
            config.write(configfile)
        
        log_func(f"✅ Configuration saved successfully with {len(config.sections())} sections", "success")
        log_func("Setup process completed successfully!", "success")
        return True, "Setup has been finalized successfully."
    except Exception as e:
        log_func(f"❌ Error updating configuration: {e}", "error")
        import traceback
        log_func(traceback.format_exc(), "error")
        return False, f"Error updating configuration: {e}"

def closeEvent(self, event):
    """Handle dialog close event."""
    logger.info("Setup wizard closing, cleaning up resources...")
    if self.ollama_process:
        try:
            logger.info(f"Stopping LLaVA model process (PID: {self.ollama_process.pid})...")
            self.ollama_process.terminate()
            success = self.ollama_process.wait(timeout=5)
            logger.info(f"LLaVA process terminated with exit code: {success}")
        except subprocess.TimeoutExpired:
            logger.warning("Timeout waiting for LLaVA process to terminate, killing process...")
            self.ollama_process.kill()
        except Exception as e:
            logger.warning(f"Error stopping LLaVA model process: {e}")
    logger.info("Setup wizard closed")
    event.accept()

def run_setup_dialog():
    """Run the setup wizard as a modal dialog and return whether it was accepted."""
    logger.info("Starting Tag-AI setup wizard...")
    app = QApplication.instance()
    if app is None:
        logger.debug("Creating new QApplication instance")
        app = QApplication(sys.argv)
    else:
        logger.debug("Using existing QApplication instance")
    
    logger.debug("Loading application stylesheet")
    load_stylesheet(app)
    
    logger.info("Creating and showing setup wizard dialog")
    wizard = SetupWizard()
    result = wizard.exec()
    
    success = result == QDialog.Accepted
    logger.info(f"Setup wizard {'completed successfully' if success else 'was cancelled or failed'}")
    return success
def main():
    """Main entry point when running setup independently."""
    success = run_setup_dialog()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()