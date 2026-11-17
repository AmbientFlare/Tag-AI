import sys
import logging
import os
import configparser
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QFormLayout, 
                               QLineEdit, QPushButton, QComboBox, QHBoxLayout, 
                               QFileDialog, QDialog, QScrollArea, QLabel, QMessageBox,
                               QCheckBox, QStyle)
from PySide6.QtCore import Qt, QFile, QIODevice, QTextStream
from PySide6.QtGui import QDoubleValidator, QIntValidator
from configparser import ConfigParser
try:
    from paths import get_app_dir, get_default_config_path
except ImportError:
    from .paths import get_app_dir, get_default_config_path
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
        
def load_stylesheet(app):
    stylesheet_file = QFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark_style.qss"))
    if stylesheet_file.open(QIODevice.ReadOnly | QIODevice.Text):
        stream = QTextStream(stylesheet_file)
        app.setStyleSheet(stream.readAll())
        stylesheet_file.close()

class ToggleSwitch(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setMinimumWidth(66)
        self.setMinimumHeight(22)
        
        # Custom styling for the toggle switch
        self.setStyleSheet("""
            QPushButton {
                background-color: #888;
                border-radius: 11px;
                color: white;
                font-weight: bold;
                padding: 0 10px;
            }
            QPushButton:checked {
                background-color: #2A82DA;
            }
        """)
        
        # Set initial state
        self.update_text()
        
        # Connect the toggled signal to update text
        self.toggled.connect(self.update_text)
    
    def update_text(self):
        """Update button text based on checked state."""
        self.setText("Yes" if self.isChecked() else "No")

    def set_value(self, value: bool):
        """Set the switch state programmatically."""
        self.setChecked(value)
    
    def get_value(self) -> bool:
        """Get the current switch state."""
        return self.isChecked()

class ConfigWindow(QDialog):
    def __init__(self, config_file):
        super().__init__()
        self.config_file = config_file
        self.config = ConfigParser()
        self.config.read(config_file)
        self.setWindowTitle('Config Editor')
        self.setMinimumWidth(600)
        try:
            from PySide6.QtGui import QIcon
            window_manager = get_window_manager()
            main_window = window_manager.get_window("main")
            if main_window and main_window.windowIcon():
                self.setWindowIcon(main_window.windowIcon())
        except Exception as e:
            logging.debug(f"Could not inherit icon from main window: {e}")
        # Layouts
        self.main_layout = QVBoxLayout()
        self.form_layout = QFormLayout()
        self.buttons_layout = QHBoxLayout()

        # Dictionary to store dynamically created widgets
        self.widgets = {}

        # Watch Section (dynamic with folder management)
        if self.config.has_section('watch'):
            self.widgets['watch'] = {}
            self.folder_layout = QVBoxLayout()
            folder_str = self.config.get('watch', 'folder', fallback='')
            self.folder_widgets = []
            if folder_str:
                for folder in [f.strip() for f in folder_str.split(",") if f.strip()]:
                    self.add_folder_field(folder)
            else:
                self.add_folder_field()

            folder_container = QWidget()
            folder_container.setLayout(self.folder_layout)
            self.form_layout.addRow("Folders:", folder_container)

            self.add_folder_button = QPushButton('+')
            self.add_folder_button.clicked.connect(lambda: self.add_folder_field())
            self.add_folder_button.setToolTip("Add a new folder entry.")
            self.form_layout.addRow("", self.add_folder_button)

            self.widgets['watch']['folder'] = self.folder_widgets
            self.form_layout.addRow(QLabel(" "))

        # Image Processing Section
        if self.config.has_section('image_processing'):
            self.widgets['image_processing'] = {}
            for option in self.config.options('image_processing'):
                line_edit = QLineEdit(self.config.get('image_processing', option))
                if option == 'target_max_size_mb':
                    line_edit.setValidator(QDoubleValidator(0.01, 10000.0, 2, self))
                    line_edit.setToolTip("The maximum size in megabytes for processed images.")
                self.form_layout.addRow(f"{option.replace('_', ' ').title()}:", line_edit)
                self.widgets['image_processing'][option] = line_edit
            self.form_layout.addRow(QLabel(" "))

        # Tagger Gemini Section
        if self.config.has_section('tagger_gemini'):
            self.widgets['tagger_gemini'] = {}
            
            # Paid Version Toggle Switch
            paid_version_toggle = ToggleSwitch()
            paid_version_value = self.config.get('tagger_gemini', 'paid_version', fallback='false').lower() == 'true'
            paid_version_toggle.set_value(paid_version_value)
            self.form_layout.addRow("Paid Version:", paid_version_toggle)
            self.widgets['tagger_gemini']['paid_version'] = paid_version_toggle

            for option in self.config.options('tagger_gemini'):
                if option == 'paid_version':
                    continue  # Already handled
                
                line_edit = QLineEdit(self.config.get('tagger_gemini', option))
                
                # Add specific validators
                if option == 'max_tags':
                    line_edit.setValidator(QIntValidator(1, 1000, self))
                elif option == 'confidence_threshold':
                    line_edit.setValidator(QDoubleValidator(0.0, 1.0, 2, self))
                elif option == 'max_image_size':
                    line_edit.setValidator(QIntValidator(1, 10000, self))
                
                self.form_layout.addRow(f"{option.replace('_', ' ').title()}:", line_edit)
                self.widgets['tagger_gemini'][option] = line_edit
            
            self.form_layout.addRow(QLabel(" "))

        # Tagger Ollama Section
        if self.config.has_section('tagger_ollama'):
            self.widgets['tagger_ollama'] = {}
            for option in self.config.options('tagger_ollama'):
                line_edit = QLineEdit(self.config.get('tagger_ollama', option))
                self.form_layout.addRow(f"{option.replace('_', ' ').title()}:", line_edit)
                self.widgets['tagger_ollama'][option] = line_edit
            self.form_layout.addRow(QLabel(" "))

        # Script to Run Section
        if self.config.has_section('script_to_run'):
            self.widgets['script_to_run'] = {}
            for option in self.config.options('script_to_run'):
                if option == 'llm_script':
                    self.llm_dropdown = QComboBox()
                    self.llm_dropdown.addItems(['local', 'gemini'])
                    current_script = self.config.get('script_to_run', 'llm_script', fallback='local')
                    self.llm_dropdown.setCurrentText(current_script)
                    self.llm_dropdown.setToolTip("Select which LLM script to run (local = Ollama)")
                    self.llm_dropdown.setStyleSheet("""
                        QComboBox {
                            color: white;
                            background-color: #404040;
                            border: 1px solid gray;
                            padding: 2px;
                        }
                        QComboBox::drop-down {
                            border: none;
                        }
                        QComboBox QAbstractItemView {
                            color: white;
                            background-color: #404040;
                            selection-background-color: #555555;
                        }
                    """)
                    self.form_layout.addRow('LLM Script:', self.llm_dropdown)
                    self.widgets['script_to_run']['llm_script'] = self.llm_dropdown

        # License Section
        if self.config.has_section('license'):
            self.widgets['license'] = {}
            for option in self.config.options('license'):
                line_edit = QLineEdit(self.config.get('license', option))
                self.form_layout.addRow(f"{option.replace('_', ' ').title()}:", line_edit)
                self.widgets['license'][option] = line_edit

        # Setup Section
        if self.config.has_section('setup'):
            self.widgets['setup'] = {}
            for option in self.config.options('setup'):
                line_edit = QLineEdit(self.config.get('setup', option))
                if option == 'setup_complete':
                    # Create a toggle switch for boolean setup_complete
                    setup_complete_toggle = ToggleSwitch()
                    setup_complete_value = self.config.get('setup', option, fallback='false').lower() == 'true'
                    setup_complete_toggle.set_value(setup_complete_value)
                    self.form_layout.addRow(f"{option.replace('_', ' ').title()}:", setup_complete_toggle)
                    self.widgets['setup'][option] = setup_complete_toggle
                else:
                    self.form_layout.addRow(f"{option.replace('_', ' ').title()}:", line_edit)
                    self.widgets['setup'][option] = line_edit

        # Buttons
        self.reset_button = QPushButton('Reset to Defaults')
        self.reset_button.clicked.connect(self.reset_to_defaults)
        self.reset_button.setToolTip("Reset all fields to default values.")

        self.save_button = QPushButton('Save')
        self.save_button.clicked.connect(self.save_config)
        self.save_button.setToolTip("Save changes and close.")

        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setToolTip("Discard changes and close.")

        self.buttons_layout.addWidget(self.reset_button)
        self.buttons_layout.addWidget(self.save_button)
        self.buttons_layout.addWidget(self.cancel_button)

        # Scroll Area
        self.main_layout.addWidget(self.scroll_area_setup())
        self.main_layout.addLayout(self.buttons_layout)
        self.setLayout(self.main_layout)

    def add_folder_field(self, text=''):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        folder_field = QLineEdit(text)
        folder_field.setToolTip("Path to the folder to watch.")
        find_button = QPushButton('Find...')
        find_button.setToolTip("Browse for a folder.")
        find_button.clicked.connect(lambda: self.open_file_dialog(folder_field))
        remove_button = QPushButton('Remove')
        remove_button.setToolTip("Remove this folder entry.")
        remove_button.clicked.connect(lambda: self.remove_folder_field(row_widget, folder_field))
        row_layout.addWidget(folder_field)
        row_layout.addWidget(find_button)
        row_layout.addWidget(remove_button)
        self.folder_layout.addWidget(row_widget)
        self.folder_widgets.append(folder_field)

    def open_file_dialog(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            line_edit.setText(folder)

    def remove_folder_field(self, row_widget, folder_field):
        self.folder_layout.removeWidget(row_widget)
        row_widget.setParent(None)
        row_widget.deleteLater()
        if folder_field in self.folder_widgets:
            self.folder_widgets.remove(folder_field)
    def scroll_area_setup(self):
        """Create and return a scroll area with the form layout."""
        scroll_content = QWidget()
        scroll_content.setLayout(self.form_layout)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_content)
        return scroll_area
    def save_config(self):
        # Watch Section: Combine multiple folder paths
        if 'watch' in self.widgets and 'folder' in self.widgets['watch']:
            folder_list = [folder_widget.text().strip() for folder_widget in self.folder_widgets if folder_widget.text().strip()]
            if not self.config.has_section('watch'):
                self.config.add_section('watch')
            self.config.set('watch', 'folder', ", ".join(folder_list))

        # Process all other sections
        for section_name, section_widgets in self.widgets.items():
            # Skip watch section as it's already handled
            if section_name == 'watch':
                continue

            # Ensure section exists
            if not self.config.has_section(section_name):
                self.config.add_section(section_name)

            for option, widget in section_widgets.items():
                # Handle toggle switches
                if isinstance(widget, ToggleSwitch):
                    value = 'true' if widget.get_value() else 'false'
                # Handle dropdown combos
                elif isinstance(widget, QComboBox):
                    value = widget.currentText()
                # Default to text input
                else:
                    value = widget.text()
                
                self.config.set(section_name, option, value)

        try:
            with open(self.config_file, 'w') as configfile:
                self.config.write(configfile)
            self.accept()
        except IOError as e:
            QMessageBox.critical(self, "Error", f"Could not save config file: {e}")

    def reset_to_defaults(self):
        # Watch Section
        if 'watch' in self.widgets and 'folder' in self.widgets['watch']:
            for folder_field in self.folder_widgets[:]:
                row_widget = folder_field.parentWidget()
                self.remove_folder_field(row_widget, folder_field)
            self.add_folder_field(os.path.expanduser("~/Pictures"))

        # Image Processing Section
        if 'image_processing' in self.widgets:
            if 'target_max_size_mb' in self.widgets['image_processing']:
                self.widgets['image_processing']['target_max_size_mb'].setText('10')

        # Tagger Gemini Section
        if 'tagger_gemini' in self.widgets:
            # Paid Version Toggle
            if 'paid_version' in self.widgets['tagger_gemini']:
                self.widgets['tagger_gemini']['paid_version'].set_value(False)
            
            # Other Gemini Fields
            defaults = {
                'gemini_api_key': '',
                'max_tags': '50',
                'confidence_threshold': '0.7',
                'max_image_size': '1024',
                'llm': 'Gemini'
            }
            for option, default_value in defaults.items():
                if option in self.widgets['tagger_gemini']:
                    self.widgets['tagger_gemini'][option].setText(default_value)

        # Tagger Ollama Section
        if 'tagger_ollama' in self.widgets:
            defaults = {
                'ollama_endpoint': 'http://localhost:11434/api/generate',
                'model_name': 'llava'
            }
            for option, default_value in defaults.items():
                if option in self.widgets['tagger_ollama']:
                    self.widgets['tagger_ollama'][option].setText(default_value)

        # Script to Run Section
        if 'script_to_run' in self.widgets:
            if 'llm_script' in self.widgets['script_to_run']:
                self.widgets['script_to_run']['llm_script'].setCurrentText('local')

        # License Section
        if 'license' in self.widgets:
            if 'license_key' in self.widgets['license']:
                self.widgets['license']['license_key'].setText('')

        # Setup Section
        if 'setup' in self.widgets:
            if 'setup_complete' in self.widgets['setup']:
                self.widgets['setup']['setup_complete'].set_value(False)