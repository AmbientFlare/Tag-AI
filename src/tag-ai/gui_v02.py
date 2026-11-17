import logging
import sys
import os
import configparser
import sqlite3
import time
import rawpy
import re
import datetime
import imageio.v2 as imageio
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QScrollArea, QTextEdit, QMessageBox, QLayout, QSizePolicy, QMainWindow,
    QDialog, QTextBrowser
)
from PySide6.QtGui import QPixmap, QImage, QAction
from PySide6.QtCore import Qt, QObject, Signal, QRect, QSize, QTimer, QFile, QIODevice, QTextStream 
from PIL import Image, UnidentifiedImageError, ImageOps
import subprocess
import tempfile
import hashlib
try:
    from global_signals import global_signals
except ImportError:
    from .global_signals import global_signals
try:
    from config_editor import ConfigWindow
except ImportError:
    from .config_editor import ConfigWindow
try:
    from paths import get_app_dir, get_default_config_path, get_default_db_path, setup_logging
except ImportError:
    from .paths import get_app_dir, get_default_config_path, get_default_db_path, setup_logging
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
    # Assumes the stylesheet is saved as 'dark_style.qss' in the same directory
    stylesheet_file = QFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark_style.qss"))
    if stylesheet_file.open(QIODevice.ReadOnly | QIODevice.Text):
        stream = QTextStream(stylesheet_file)
        app.setStyleSheet(stream.readAll())
        stylesheet_file.close()

# -----------------------------
# Custom FlowLayout class
# -----------------------------
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._itemList = []
        self.setSpacing(spacing if spacing >= 0 else 6)

    def addItem(self, item):
        self._itemList.append(item)

    def count(self):
        return len(self._itemList)

    def itemAt(self, index):
        if 0 <= index < len(self._itemList):
            return self._itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._itemList):
            return self._itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._itemList:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom())
        return size

    def doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0

        for item in self._itemList:
            widget = item.widget()
            spaceX = self.spacing()
            spaceY = self.spacing()
            nextX = x + item.sizeHint().width() + spaceX

            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(x, y, item.sizeHint().width(), item.sizeHint().height()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()

# -----------------------------
# Custom stream to capture output
# -----------------------------
class EmittingStream(QObject):
    text_written = Signal(str)

    def write(self, text):
        if text.strip():
            self.text_written.emit(text)
            # Also broadcast to any other listening windows
            global_signals.log_message.emit(text)

    def flush(self):
        pass

# -----------------------------
# Configuration and image loading functions
# -----------------------------
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
THUMBNAIL_SIZE = (150, 150)
# Known RAW file extensions for rawpy fallback
RAW_EXTENSIONS = {'.arw', '.cr2', '.dng', '.nef', '.raf', '.rw2', '.srw', '.orf', '.pef', '.ptx', '.rwl'}
# Known image extensions for imageio fallback
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif', '.webp'}

def load_config(config_file, section):
    config = configparser.ConfigParser()
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file '{config_file}' not found.")
    config.read(config_file)
    if section not in config:
        raise KeyError(f"Missing '{section}' section in configuration file.")
    return config[section]

def load_image(file_path):
    """Load an image thumbnail, handling JPEG, RAW, or other formats."""
    ext = os.path.splitext(file_path)[1].lower()
    # Only attempt known image/RAW types
    if ext not in IMAGE_EXTENSIONS and ext not in RAW_EXTENSIONS:
        return None
    # First attempt: load via Pillow from in-memory buffer
    if ext in IMAGE_EXTENSIONS:
        from io import BytesIO
        # Read file into memory
        with open(file_path, 'rb') as f:
            buf = f.read()
        stream = BytesIO(buf)
        img = Image.open(stream)
        try:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img.thumbnail(THUMBNAIL_SIZE)
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimage = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            return QPixmap.fromImage(qimage)
        finally:
            img.close()
            stream.close()
    # RAW thumbnail: embedded preview and fallbacks for RAW
    if ext in RAW_EXTENSIONS:
        # 1) embedded thumbnail
        try:
            with rawpy.imread(file_path) as raw:
                thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                qimg = QImage.fromData(thumb.data, "JPEG")
            elif thumb.format == rawpy.ThumbFormat.BITMAP:
                arr = thumb.data; h, w, _ = arr.shape
                qimg = QImage(arr.tobytes(), w, h, 3*w, QImage.Format_RGB888)
            else:
                qimg = None
            if qimg and not qimg.isNull():
                return QPixmap.fromImage(qimg).scaled(
                    THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1],
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
        except Exception as e:
            logging.debug(f"RawPy extract_thumb failed: {e}")
        # 2) half-size demosaic fallback
        try:
            from io import BytesIO
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess(
                    use_auto_wb=True, no_auto_bright=False,
                    demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR,
                    half_size=True
                )
            img = Image.fromarray(rgb)
            img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
            buf = BytesIO(); img.save(buf, format="PNG"); data = buf.getvalue()
            qimg2 = QImage.fromData(data, "PNG")
            if qimg2 and not qimg2.isNull():
                return QPixmap.fromImage(qimg2).scaled(
                    THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1],
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
        except Exception as e:
            logging.debug(f"RawPy demosaic failed: {e}")
        # 3) Qt direct load fallback
        pix = QPixmap(file_path)
        if not pix.isNull():
            return pix.scaled(
                THUMBNAIL_SIZE[0], THUMBNAIL_SIZE[1],
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        return None

def load_full_image(file_path):
    """Load a full-resolution image via Qt's QImage, with fallback for unsupported formats."""
    # If RAW format, skip Qt loader and use our fallback for full quality
    ext = os.path.splitext(file_path)[1].lower()
    if ext in RAW_EXTENSIONS:
        pixmap, _ = load_full_image_fallback(file_path)
        return pixmap
    qimage = QImage(file_path)
    if not qimage.isNull():
        return QPixmap.fromImage(qimage)
    # Qt couldn't load it (e.g. RAW); try our fallback pipeline
    pixmap, _ = load_full_image_fallback(file_path)
    return pixmap

def load_full_image_fallback(file_path):
    """Fallback full-resolution image loader via Pillow, RawPy, or ImageIO."""
    ext = os.path.splitext(file_path)[1].lower()
    temp_path = None
    if ext in IMAGE_EXTENSIONS:
        from io import BytesIO
        # Pillow fallback (PNG via QImage.fromData)
        try:
            with Image.open(file_path) as img:
                img = ImageOps.exif_transpose(img)
                buf = BytesIO()
                img.save(buf, format="PNG")
                data = buf.getvalue()
            qimage = QImage.fromData(data, "PNG")
            if not qimage.isNull():
                return QPixmap.fromImage(qimage), None
        except Exception as e:
            logging.debug(f"Pillow fallback failed: {e}")
    # RawPy fallback for RAW files (PNG via QImage.fromData)
    if ext in RAW_EXTENSIONS:
        from io import BytesIO
        try:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess()
            img = Image.fromarray(rgb)
            buf = BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
            qimage = QImage.fromData(data, "PNG")
            if not qimage.isNull():
                return QPixmap.fromImage(qimage), None
        except Exception as e:
            logging.debug(f"RawPy fallback failed: {e}")
    # Final fallback: copy file directly to temp and load via QPixmap
    if ext in IMAGE_EXTENSIONS:
        try:
            import shutil
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            temp_path = temp_file.name
            temp_file.close()
            shutil.copyfile(file_path, temp_path)
            pixmap = QPixmap(temp_path)
            return pixmap, temp_path
        except Exception as e:
            logging.debug(f"ImageIO fallback failed: {e}")
    return None, None

# -----------------------------
# About Dialog class
# -----------------------------
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Tag-AI")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        try:
            from PySide6.QtGui import QIcon
            window_manager = get_window_manager()
            main_window = window_manager.get_window("main")
            if main_window and main_window.windowIcon():
                self.setWindowIcon(main_window.windowIcon())
        except Exception as e:
            logging.debug(f"Could not inherit icon from main window: {e}")

        layout = QVBoxLayout()

        # Title
        title_label = QLabel("Tag-AI")
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Description
        description_text = QTextBrowser()
        description_text.setReadOnly(True)
        description_text.setOpenExternalLinks(True)
        description_text.setHtml("""
        <p>Tag-AI is an advanced photo management tool that uses 
        artificial intelligence to automatically tag and organize your images.</p>

        <p>Key features:</p>
        <ul>
            <li>Automatic AI-powered tagging of images</li>
            <li>Fast search through your entire photo collection</li>
            <li>Support for both standard image formats and RAW files</li>
            <li>Metadata editing and management</li>
            <li>Cross-platform compatibility</li>
        </ul>

        <p>This application uses a local AI model to process your images or 
        Google's Gemini API for image analysis.</p>

        <p>Created by: <a href="https://www.ambientflare.com">Ambient Flare</a></p>
        <p>Copyright &copy; 2025. All rights reserved.</p>
        """)
        layout.addWidget(description_text)

        # OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        layout.addWidget(ok_button)

        self.setLayout(layout)

# -----------------------------
# Licenses Dialog class
# -----------------------------
class LicensesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Software Licenses")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        try:
            from PySide6.QtGui import QIcon
            window_manager = get_window_manager()
            main_window = window_manager.get_window("main")
            if main_window and main_window.windowIcon():
                self.setWindowIcon(main_window.windowIcon())
        except Exception as e:
            logging.debug(f"Could not inherit icon from main window: {e}")

        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel("Third-Party Software Licenses")
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # License information
        license_text = QTextBrowser()
        license_text.setReadOnly(True)
        license_text.setOpenExternalLinks(True)
        license_text.setHtml("""
        <h3>This application uses the following third-party software:</h3>

        <h4>PySide6 (Qt for Python)</h4>
        <p>Licensed under the LGPL v3 license</p>
        <p><a href="https://www.qt.io/qt-licensing">https://www.qt.io/qt-licensing</a></p>

        <h4>SQLite</h4>
        <p>SQLite is in the Public Domain</p>
        <p><a href="https://sqlite.org/copyright.html">https://sqlite.org/copyright.html</a></p>

        <h4>Pillow (PIL)</h4>
        <p>Licensed under the open source MIT-CMU License</p>
        <p><a href="https://github.com/python-pillow/Pillow/blob/main/LICENSE">https://github.com/python-pillow/Pillow/blob/main/LICENSE</a></p>

        <h4>RawPy</h4>
        <p>Licensed under the MIT License (Python wrapper) and LGPL (LibRaw)</p>
        <p>Python wrapper: <a href="https://github.com/letmaik/rawpy/blob/master/LICENSE">https://github.com/letmaik/rawpy/blob/master/LICENSE</a></p>
        <p>LibRaw: <a href="https://www.libraw.org/">https://www.libraw.org/</a> (LGPL)</p>

        <h4>Imageio</h4>
        <p>Licensed under the BSD-2-Clause License</p>
        <p><a href="https://github.com/imageio/imageio/blob/main/LICENSE">https://github.com/imageio/imageio/blob/main/LICENSE</a></p>

        <h4>ExifTool</h4>
        <p>Licensed under the Perl Artistic License</p>
        <p><a href="https://metacpan.org/pod/distribution/Image-ExifTool/ExifTool_licenses.pod">https://metacpan.org/pod/distribution/Image-ExifTool/ExifTool_licenses.pod</a></p>

        <h4>Gemini API (Google Generative AI)</h4>
        <p>Licensed under Google's API Terms of Service and the Gemini API Additional Terms of Service</p>
        <p><a href="https://ai.google.dev/gemini-api/terms">https://ai.google.dev/gemini-api/terms</a></p>

        <h4>Ollama</h4>
        <p>Licensed under the MIT License. Utilizes models with their own licenses, such as Llama 2 Community License.</p>
        <p><a href="https://github.com/ollama/ollama/blob/main/LICENSE">https://github.com/ollama/ollama/blob/main/LICENSE</a></p>
        <p>Llama 2 Community License: <a href="https://ai.meta.com/llama/license/">https://ai.meta.com/llama/license/</a></p>

        <h4>LLaVA</h4>
        <p>Licensed under the Apache License 2.0. Utilizes models with their own licenses, such as Llama 2 Community License.</p>
        <p><a href="https://www.apache.org/licenses/LICENSE-2.0">https://www.apache.org/licenses/LICENSE-2.0</a></p>
        <p>Llama 2 Community License: <a href="https://ai.meta.com/llama/license/">https://ai.meta.com/llama/license/</a></p>

        <h4>pynvml</h4>
        <p>Licensed under the BSD-3-Clause License</p>
        <p><a href="https://opensource.org/licenses/BSD-3-Clause">https://opensource.org/licenses/BSD-3-Clause</a></p>

        <h4>requests</h4>
        <p>Licensed under the Apache License 2.0</p>
        <p><a href="https://www.apache.org/licenses/LICENSE-2.0">https://www.apache.org/licenses/LICENSE-2.0</a></p>

        <h4>NumPy</h4>
        <p>Licensed under the BSD license</p>
        <p><a href="https://numpy.org/doc/stable/user/license.html">https://numpy.org/doc/stable/user/license.html</a></p>
        
        <p>Full license texts are available upon request.</p>
        """)
        layout.addWidget(license_text)
        
        # OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        layout.addWidget(ok_button)
        
        self.setLayout(layout)

        
# -----------------------------
# Worker class for threaded image loading
# -----------------------------
class Worker(QObject):
    image_loaded = Signal(object, object, object, object, str, object)  # file_hash can be None

    def __init__(self):
        super().__init__()

    def load_and_display_image(self, file_path, date_taken, tags, search_term, file_hash):
        pixmap = load_image(file_path)
        self.image_loaded.emit(pixmap, file_path, date_taken, tags, search_term, file_hash)

# -----------------------------
# Metadata Window class
# -----------------------------
class MetadataWindow(QDialog):
    def __init__(self, file_path, file_hash, date_taken, tags, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.file_hash = file_hash
        self.date_taken = date_taken
        self.tags = tags
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()

        file_label = QLabel(f"File Path: {self.file_path}")
        layout.addWidget(file_label)

        # Load full-resolution image using the original function
        pixmap = load_full_image(self.file_path)
        if pixmap:
            preview_pixmap = pixmap.scaled(800, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_preview = QLabel()
            image_preview.setPixmap(preview_pixmap)
            image_preview.setAlignment(Qt.AlignCenter)
            layout.addWidget(image_preview)

        self.date_input = QLineEdit(self.date_taken or "Unknown")
        layout.addWidget(QLabel("Date Taken:"))
        layout.addWidget(self.date_input)

        self.tags_input = QTextEdit(self.tags or "")
        self.tags_input.setMaximumHeight(100)
        layout.addWidget(QLabel("Tags (comma-separated):"))
        layout.addWidget(self.tags_input)

        save_button = QPushButton("Save Changes")
        save_button.clicked.connect(self.save_changes)
        layout.addWidget(save_button)

        self.setLayout(layout)
        self.resize(400, 300)

    def save_changes(self):
        new_date = self.date_input.text().strip()
        new_tags = self.tags_input.toPlainText().strip()

        try:
            cursor = self.parent().conn.cursor()
            cursor.execute("UPDATE photos SET date_taken = ? WHERE photo_id = ?", (new_date, self.file_hash))
            cursor.execute("DELETE FROM photo_tags WHERE photo_id = ?", (self.file_hash,))
            if new_tags:
                tag_list = [tag.strip() for tag in new_tags.split(",") if tag.strip()]
                for tag in tag_list:
                    cursor.execute("INSERT OR IGNORE INTO tags (tag) VALUES (?)", (tag,))
                    cursor.execute("SELECT id FROM tags WHERE tag = ?", (tag,))
                    result = cursor.fetchone()
                    if result:
                        tag_id = result[0]
                        cursor.execute("INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?, ?)",
                                       (self.file_hash, tag_id))
                    else:
                        print(f"! No tag id found for tag: {tag}")
            self.parent().conn.commit()
            print(f"?? Updated metadata for {self.file_path} (hash: {self.file_hash})")
            self.accept()
        except Exception as e:
            print(f"! Error updating metadata: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save changes:\n{e}")

    def closeEvent(self, event):
        event.accept()

# -----------------------------
# Main PhotoGallery class
# -----------------------------
class PhotoGallery(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tag-AI")
        self.setGeometry(100, 100, 800, 600)
        self.setup_ui()
        self.connect_db()

        self.worker = Worker()
        self.worker.image_loaded.connect(self.display_image)

        self.executor = ThreadPoolExecutor(max_workers=4)  # Persistent executor to avoid blocking UI during thumbnail loads

        self.current_search = ""

        self.emittingStream = EmittingStream()
        self.emittingStream.text_written.connect(self.append_output)
        sys.stdout = self.emittingStream
        sys.stderr = self.emittingStream

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)

        # Adjust these parameters to smooth out performance:
        self.batch_size = 25             # Reduced batch size
        self.batch_timer_interval = 500  # Increased timer (milliseconds)
        self.search_results = []
        self.current_batch_index = 0
    def push_tags(self):
        """Push tags from the database to the image metadata with improved error handling."""
        try:
            # First, validate that pushtags module can be imported
            try:
                from pushtags import main as pushtags_main
            except ImportError:
                try:
                    from .pushtags import main as pushtags_main
                except ImportError:
                    self.results_area.append("Error: Could not import pushtags module")
                    return

            # Inform the user about the operation starting
            self.results_area.append("Starting tag push operation...")
            self.results_area.append("This may take a while depending on the number of images...")
            
            # Disable the button to prevent multiple operations
            self.push_tags_button.setEnabled(False)
            self.push_tags_button.setText("Running...")
            
            # Run pushtags in a separate thread to avoid freezing the UI
            import threading
            
            def run_push_tags():
                try:
                    result = pushtags_main()
                    # Report completion on the main thread using a signal
                    if result == 0:
                        self.emittingStream.text_written.emit("Tag push operation completed successfully!")
                    else:
                        self.emittingStream.text_written.emit(f"Tag push operation completed with errors (code {result}).")
                except Exception as e:
                    import traceback
                    error_msg = f"Error during tag push operation: {str(e)}"
                    trace_msg = traceback.format_exc()
                    self.emittingStream.text_written.emit(error_msg)
                    self.emittingStream.text_written.emit(trace_msg)
                finally:
                    # Re-enable the button on the main thread
                    from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                    QMetaObject.invokeMethod(
                        self.push_tags_button, 
                        "setEnabled", 
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(bool, True)
                    )
                    QMetaObject.invokeMethod(
                        self.push_tags_button, 
                        "setText", 
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, "Push Tags to Image")
                    )
            
            # Start the thread
            thread = threading.Thread(target=run_push_tags)
            thread.daemon = True  # Allow the application to exit if this thread is still running
            thread.start()
        
            self.results_area.append("Tag push operation started in background...")
            self.results_area.append("You can continue using the application while tags are being processed.")
        except Exception as e:
            self.results_area.append(f"Unexpected error: {str(e)}")
            self.push_tags_button.setEnabled(True)
            self.push_tags_button.setText("Push Tags to Image")
    def setup_ui(self):
        layout = QVBoxLayout()

        self.title_label = QLabel("Welcome to Tag-AI, A smart AI Tagger")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        query_layout = QHBoxLayout()
        self.query_label = QLabel("Input query")
        self.query_input = QLineEdit()
        self.query_input.returnPressed.connect(self.perform_search)
        query_layout.addWidget(self.query_label)
        query_layout.addWidget(self.query_input)
        layout.addLayout(query_layout)

        self.results_area = QTextEdit()
        self.results_area.setReadOnly(True)
        line_height = self.results_area.fontMetrics().lineSpacing()
        self.results_area.setMaximumHeight(line_height * 8)
        layout.addWidget(self.results_area)

        buttons_layout = QHBoxLayout()
        self.search_button = QPushButton("Search")
        self.reset_button = QPushButton("Reset")
        self.scan_button = QPushButton("Scan")
        self.push_tags_button = QPushButton("Push Tags to Image")
        self.search_button.clicked.connect(self.perform_search)
        self.reset_button.clicked.connect(self.reset_gallery)
        self.scan_button.clicked.connect(self.perform_scan)
        self.push_tags_button.clicked.connect(self.push_tags)
        buttons_layout.addWidget(self.search_button)
        buttons_layout.addWidget(self.reset_button)
        buttons_layout.addWidget(self.scan_button)
        buttons_layout.addWidget(self.push_tags_button)
        layout.addLayout(buttons_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.photo_widget = QWidget()
        self.photo_layout = FlowLayout(self.photo_widget)
        self.photo_widget.setLayout(self.photo_layout)
        self.scroll_area.setWidget(self.photo_widget)
        layout.addWidget(self.scroll_area)

        self.setLayout(layout)

    def append_output(self, text):
        self.results_area.append(text.strip())
        self.results_area.ensureCursorVisible()

    def connect_db(self):
        try:
            db_path = get_default_db_path()
            logging.info(f"Connecting to database: {db_path}")
            
            # Check if file exists
            if not os.path.exists(db_path):
                error_msg = f"Database file '{db_path}' not found"
                logging.error(error_msg)
                QMessageBox.critical(self, "Database Error", error_msg)
                sys.exit(1)
                
            # Check if we have permission to read the file
            if not os.access(db_path, os.R_OK):
                error_msg = f"No read permission for database file '{db_path}'"
                logging.error(error_msg)
                QMessageBox.critical(self, "Permission Error", error_msg)
                sys.exit(1)
                
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
            
            # Test the connection
            self.cursor.execute("SELECT 1")
            self.cursor.fetchone()
            logging.info("Database connection successful")
            
        except sqlite3.Error as e:
            error_msg = f"SQLite error: {e}"
            logging.error(error_msg)
            QMessageBox.critical(self, "Database Error", error_msg)
            sys.exit(1)
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logging.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
            sys.exit(1)

    def clear_thumbnails(self):
        while self.photo_layout.count():
            item = self.photo_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def perform_search(self):
        self.clear_thumbnails()
        query_text = self.query_input.text().strip()
        if not query_text:
            QMessageBox.information(self, "Input Needed", "Please enter a search term.")
            return

        self.current_search = query_text
        print(f"?? Searching for: {query_text}")

        # Parse the query into terms, preserving quoted strings
        terms = re.findall(r'"[^"]*"|\S+', query_text)
        
        conditions = []
        params = []
        
        for term in terms:
            if term.startswith('"') and term.endswith('"'):
                # Exact match for tags
                exact_term = term[1:-1]
                conditions.append(
                    "EXISTS (SELECT 1 FROM photo_tags pt2 "
                    "JOIN tags t2 ON pt2.tag_id = t2.id "
                    "WHERE pt2.photo_id = p.photo_id AND t2.tag = ?)"
                )
                params.append(exact_term)
            else:
                # Partial match for file_path and tags
                partial_term = f"%{term}%"
                conditions.append(
                    "(p.file_path LIKE ? OR "
                    "EXISTS (SELECT 1 FROM photo_tags pt2 "
                    "JOIN tags t2 ON pt2.tag_id = t2.id "
                    "WHERE pt2.photo_id = p.photo_id AND t2.tag LIKE ?))"
                )
                params.extend([partial_term, partial_term])
        
        # Combine conditions with AND
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        sql_query = f"""
            SELECT p.photo_id, p.file_path, p.date_taken, p.file_hash,
                IFNULL(GROUP_CONCAT(t.tag, ', '), '') AS tags
            FROM photos p
            LEFT JOIN photo_tags pt ON p.photo_id = pt.photo_id
            LEFT JOIN tags t ON pt.tag_id = t.id
            WHERE {where_clause}
            GROUP BY p.photo_id, p.file_path, p.date_taken, p.file_hash
        """
        
        try:
            self.cursor.execute(sql_query, params)
            rows = self.cursor.fetchall()
        except Exception as e:
            print(f"? Database query failed: {e}")
            return
        
        if not rows:
            print("?? No images matched your query.")
            return
        
        print(f"? Found {len(rows)} matching images.")
        self.search_results = rows
        self.current_batch_index = 0
        self.load_next_batch()

    def load_next_batch(self):
        batch = self.search_results[self.current_batch_index:self.current_batch_index + self.batch_size]
        if not batch:
            return
        print(f"? Loading thumbnails {self.current_batch_index + 1} to {self.current_batch_index + len(batch)}")
        # Limit concurrency to prevent overloading the CPU
        for photo in batch:
            photo_id, file_path, date_taken, file_hash, tags = photo
            if not os.path.exists(file_path):
                print(f"?? File not found: {file_path}")
                continue
            self.executor.submit(self.worker.load_and_display_image, file_path, date_taken, tags, self.current_search, file_hash)
        self.current_batch_index += self.batch_size
        if self.current_batch_index < len(self.search_results):
            QTimer.singleShot(self.batch_timer_interval, self.load_next_batch)

    def display_image(self, pixmap, file_path, date_taken, tags, search_term, file_hash=None):
        if search_term != self.current_search:
            return
        if pixmap is None:
            print(f"! Failed to load image: {file_path}")
            return
        # Unpack tuple if fallback returned (pixmap, temp_path)
        if isinstance(pixmap, tuple):
            pixmap = pixmap[0]
        image_label = QLabel()
        image_label.setPixmap(pixmap)
        image_label.setAlignment(Qt.AlignCenter)
        tooltip_text = f"Date Taken: {date_taken}\nTags: {tags}"
        image_label.setToolTip(tooltip_text)

        def mousePressEvent(event):
            if event.button() == Qt.LeftButton:
                self.open_image(file_path)
            elif event.button() == Qt.RightButton:
                self.open_metadata(file_path, file_hash, date_taken, tags)

        image_label.mousePressEvent = mousePressEvent
        self.photo_layout.addWidget(image_label)

    def open_image(self, image_path):
        if sys.platform == "win32":
            os.startfile(image_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", image_path])
        else:
            subprocess.run(["xdg-open", image_path])

    def open_metadata(self, file_path, file_hash, date_taken, tags):
        metadata_window = MetadataWindow(file_path, file_hash, date_taken, tags, self)
        metadata_window.exec()

    def reset_gallery(self):
        self.query_input.clear()
        self.results_area.clear()
        while self.photo_layout.count():
            item = self.photo_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def delete_record(self, file_id):
        try:
            self.cursor.execute("DELETE FROM photos WHERE photo_id = ?", (file_id,))
            self.conn.commit()
            print(f"?? Deleted record {file_id}")
        except Exception as e:
            print(f"! Error deleting record {file_id}: {e}")

    def perform_scan(self):
        """Launch the scan window and keep a reference to it using WindowManager."""
        self.results_area.append("Starting scan window launch...")
        
        try:
            # Import component_launcher
            try:
                from component_launcher import launch_module
            except ImportError:
                try:
                    from .component_launcher import launch_module
                except ImportError:
                    self.results_area.append("Error: Could not import component_launcher module")
                    return
            
            # Get window manager
            window_manager = get_window_manager()
            
            # Check if window already exists in the manager
            scan_window = window_manager.get_window("scan_window")
            
            if scan_window is None:
                # Launch the scan window module
                self.results_area.append("Creating new scan window...")
                launch_result = launch_module("scan_window", "main", run_in_main_thread=False)
                
                # The launch_module function may return a thread or a window object depending on run_in_main_thread
                # We should wait for the window to be registered in the window_manager
                for _ in range(10):  # Try up to 10 times with short delays
                    scan_window = window_manager.get_window("scan_window")
                    if scan_window is not None:
                        break
                    time.sleep(0.1)  # Short delay to allow window registration
                
                if scan_window is None:
                    self.results_area.append("Warning: Scan window launched but not found in window manager")
                    return
                    
                self.results_area.append("Scan window created")
            
            # Show, raise, and activate the window
            if not scan_window.isVisible():
                scan_window.show()
                self.results_area.append("Scan window shown")
            else:
                scan_window.raise_()
                scan_window.activateWindow()
                self.results_area.append("Scan window raised to front")
            
            # Store a reference locally but don't overwrite the window manager's reference
            self.scan_window = scan_window
            
        except Exception as e:
            self.results_area.append(f"Error launching scan window: {str(e)}")
            import traceback
            self.results_area.append(traceback.format_exc())

# -----------------------------
# MainWindow class with menu integration
# -----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Set up menubar
        menubar = self.menuBar()
        actions_menu = menubar.addMenu("Actions")
        
        # Set application icon
        self.set_application_icon()
        
        # Existing menu items
        edit_config_action = QAction("Edit Config", self)
        purge_action = QAction("Purge", self)
        close_action = QAction("Close Program", self)
        
        # New menu items
        about_action = QAction("About This Program", self)
        licenses_action = QAction("Licenses", self)
        
        # Connect actions to handlers
        edit_config_action.triggered.connect(self.edit_config)
        purge_action.triggered.connect(self.purge)
        close_action.triggered.connect(self.close_program)
        about_action.triggered.connect(self.show_about)
        licenses_action.triggered.connect(self.show_licenses)
        
        # Add actions to menu
        actions_menu.addAction(edit_config_action)
        actions_menu.addAction(purge_action)
        actions_menu.addAction(about_action)
        actions_menu.addAction(licenses_action)
        actions_menu.addAction(close_action)

        self.gallery = PhotoGallery()
        self.setCentralWidget(self.gallery)
        self.setWindowTitle("Tag-AI")
        self.resize(800, 600)
        
        # Register with window manager
        try:
            window_manager = get_window_manager()
            window_manager.register_window("main", self)
        except Exception as e:
            print(f"Could not register with window manager: {e}")

    def set_application_icon(self):
        """Set the application icon for all platforms."""
        try:
            from PySide6.QtGui import QIcon
            
            # Try multiple possible locations for the icon
            icon_paths = [
                os.path.join(get_app_dir(), "resources", "tagai.ico"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "tagai.ico"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "tagai.ico"),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "tagai.ico")
            ]
            
            # Try each path until we find an existing icon
            for icon_path in icon_paths:
                if os.path.exists(icon_path):
                    app_icon = QIcon(icon_path)
                    self.setWindowIcon(app_icon)
                    # Set application-wide icon (affects all windows)
                    QApplication.setWindowIcon(app_icon)
                    logging.info(f"Set application icon from: {icon_path}")
                    
                    # Platform-specific icon handling
                    if sys.platform == "win32":
                        try:
                            import ctypes
                            # Set taskbar icon for Windows
                            app_id = "AmbientFlare.TagAI.Application.1"
                            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
                        except Exception as e:
                            logging.warning(f"Windows-specific icon setup failed: {e}")
                    
                    return
            
            logging.warning("Could not find application icon in any expected location")
        except Exception as e:
            logging.error(f"Error setting application icon: {e}")
    
    def close_program(self):
        """Gracefully shut down the application."""
        # Log the closure attempt (using a method that's safe for main thread)
        self.gallery.results_area.append("Initiating application shutdown...")
        
        # Stop any active scan window
        try:
            if hasattr(self.gallery, 'scan_window') and self.gallery.scan_window is not None:
                # Use a signal or method to request graceful shutdown
                if hasattr(self.gallery.scan_window, 'stop_scan'):
                    self.gallery.scan_window.stop_scan()
                
                # Ensure the scan window is closed
                if self.gallery.scan_window.isVisible():
                    self.gallery.scan_window.close()
        except Exception as e:
            logging.error(f"Error closing scan window: {e}")
        
        # Close the database connection if open
        try:
            if hasattr(self.gallery, 'conn') and self.gallery.conn:
                self.gallery.conn.close()
        except Exception as e:
            logging.error(f"Error closing database connection: {e}")
        
        # Attempt to close all open windows
        for window in QApplication.topLevelWidgets():
            if window is not self:  # Don't close the main window twice
                window.close()
        
        # Close the main window
        self.close()
        
        # Ensure the application exits
        QApplication.quit()

    def edit_config(self):
        config_window = ConfigWindow(get_default_config_path())
        config_window.exec()

    def purge(self):
        """Launch the purge window and keep a reference to it using WindowManager."""
        # Import here to avoid circular imports
        try:
            from purge_window import MainWindow as PurgeWindow, main as purge_main
        except ImportError:
            try:
                from .purge_window import MainWindow as PurgeWindow, main as purge_main
            except ImportError:
                self.gallery.results_area.append("Error: Could not import purge window module")
                return

        # Get window manager
        try:
            from window_manager import get_window_manager
        except ImportError:
            try:
                from .window_manager import get_window_manager
            except ImportError:
                self.gallery.results_area.append("Error: Could not import window manager module")
                return

        window_manager = get_window_manager()
        
        # Check if window already exists in the manager
        purge_window = window_manager.get_window("purge_window")
        
        if purge_window is None:
            # Create new purge window and register it
            purge_window = purge_main()  # This will handle QApplication setup
            window_manager.register_window("purge_window", purge_window)
            self.gallery.results_area.append("Purge window created")
        
        # Show, raise, and activate the window
        if not purge_window.isVisible():
            purge_window.show()
            self.gallery.results_area.append("Purge window shown")
        else:
            purge_window.raise_()
            purge_window.activateWindow()
            self.gallery.results_area.append("Purge window raised to front")
        
        # Store a reference in the main window too as a backup
        self.purge_window = purge_window
    
    def show_about(self):
        """Show the About dialog."""
        about_dialog = AboutDialog(self)
        about_dialog.exec()
    
    def show_licenses(self):
        """Show the Licenses dialog."""
        licenses_dialog = LicensesDialog(self)
        licenses_dialog.exec()
            

def main(args=None):
    """
    Main entry point for the application.
    
    Args:
        args: Optional command line arguments
        
    Returns:
        MainWindow instance or int error code
    """
    # Set up logging
    try:
        from paths import setup_logging
        setup_logging("gui", logging.INFO)
    except ImportError:
        pass
    
    logger = logging.getLogger(__name__)
    logger.info("Starting GUI application...")
    
    try:
        # Check for existing QApplication
        app = QApplication.instance()
        created_new_app = False
        if app is None:
            app = QApplication(sys.argv if args is None else args)
            logger.info("Created new QApplication instance.")
            created_new_app = True
        else:
            logger.info("Reusing existing QApplication instance.")
        
        load_stylesheet(app)
        
        # Create and show the main window
        main_window = MainWindow()
        main_window.show()
        
        if created_new_app:
            logger.info("Starting event loop.")
            return app.exec()
        else:
            # Store reference to window before logging
            window_ref = main_window
            # Either remove this log line entirely, or log earlier in the function
            # logger.info("Returning MainWindow to keep it alive.")
            return window_ref  # Return the window to keep a reference to it
        
    except Exception as e:
        logger.critical(f"Fatal error during application startup: {e}")
        import traceback
        logger.critical(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())