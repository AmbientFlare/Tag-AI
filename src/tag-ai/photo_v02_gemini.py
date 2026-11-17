# photo_v02_gemini.py
import time
import os
import logging
import configparser
import rawpy
from PIL import Image
import sqlite3
import tempfile
import sys
import hashlib
import imageio
import glob
import google.generativeai as genai
import threading
import signal
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from sqlite3 import Connection
from collections import deque
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed 
try:
    from paths import get_default_config_path, get_default_db_path, setup_logging
except ImportError:
    from .paths import get_default_config_path, get_default_db_path, setup_logging

# Configure logging
setup_logging("photo_gemini", logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Configuration ---
CONFIG_FILE = get_default_config_path()

# Read configuration with robust handling
config = configparser.ConfigParser()
config.read(CONFIG_FILE)

# Set default values for configuration
DEFAULT_TARGET_MAX_SIZE_MB = 10  # Default 10 MB max size
DEFAULT_MAX_TAGS = 50
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_MAX_IMAGE_SIZE = 1024

def get_config_value(section, key, default_value):
    try:
        return config.get(section, key, fallback=default_value)
    except (configparser.NoSectionError, configparser.NoOptionError):
        logger.warning(f"Missing configuration: {section}.{key}. Using default: {default_value}")
        return default_value

TARGET_MAX_SIZE_MB = float(get_config_value("image_processing", "target_max_size_mb", DEFAULT_TARGET_MAX_SIZE_MB))
GEMINI_API_KEY = get_config_value("tagger_gemini", "gemini_api_key", "")
PAID_VERSION = get_config_value("tagger_gemini", "paid_version", "false").lower() == "true"
MAX_TAGS = int(get_config_value("tagger_gemini", "max_tags", DEFAULT_MAX_TAGS))
CONFIDENCE_THRESHOLD = float(get_config_value("tagger_gemini", "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD))
MAX_IMAGE_SIZE = int(get_config_value("tagger_gemini", "max_image_size", DEFAULT_MAX_IMAGE_SIZE))
WATCH_FOLDERS = [folder.strip() for folder in get_config_value("watch", "folder", "").split(",") if folder.strip()]

# SQLite Database Configuration
DB_PATH = get_default_db_path()

# Image Processing Configuration
TARGET_MAX_SIZE_MB = float(config["image_processing"]["target_max_size_mb"])  # Changed to float

thread_local = threading.local()

# Rate limiting queue for tagger requests
tagger_queue = deque()
TAGGER_WINDOW = 60  # Time window in seconds
tagger_queue_lock = threading.Lock()  # Global lock for rate-limiting operations

# New global queue for database write tasks
db_write_queue = queue.Queue()


    
def validate_config(config: configparser.ConfigParser) -> bool:
    """Validate configuration values."""
    required_sections = ["watch", "image_processing", "tagger_gemini"]
    required_values = {
        "watch": ["folder"],
        "image_processing": ["target_max_size_mb"],
        "tagger_gemini": ["gemini_api_key"]
    }
    # Implementation

def get_sqlite_connection() -> Connection:
    """Returns a thread-local SQLite connection."""
    if not hasattr(thread_local, "conn"):
        thread_local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        logger.info(f"Opened SQLite connection for thread {threading.current_thread().name}")
    return thread_local.conn

def enable_wal_mode():
    """Enable Write-Ahead Logging for better write performance."""
    conn = get_sqlite_connection()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
        logger.info("✅ WAL mode enabled for better performance.")
    except sqlite3.Error as e:
        logger.error(f"❌ Error enabling WAL mode: {e}")
    finally:
        cur.close()
def get_date_taken(file_path):
    """
    Extracts the date a photo was taken with a strict approach.
    
    Prioritizes:
    1. EXIF DateTimeOriginal tag
    2. File modification time (but only if it's not the current date)
    3. None if no reliable date can be found
    
    Args:
        file_path (str): Path to the image file
    
    Returns:
        str: Formatted date string or None if no reliable date found
    """
    try:
        # Try using PIL first with more comprehensive EXIF extraction
        with Image.open(file_path) as img:
            exif_data = img.getexif()
            if exif_data:
                # Prioritize DateTimeOriginal (36867) tag
                date_taken = exif_data.get(36867)
                if date_taken:
                    try:
                        # Try to parse and reformat the date to ensure it's a valid datetime
                        parsed_date = datetime.strptime(date_taken, '%Y:%m:%d %H:%M:%S')
                        return parsed_date.isoformat()
                    except ValueError:
                        logger.warning(f"Could not parse EXIF date: {date_taken}")
    except Exception as e:
        logger.warning(f"⚠️ PIL failed to extract date from {file_path}: {e}")

    try:
        # Fallback: Use rawpy for RAW files
        if rawpy and file_path.lower().endswith((".nef", ".cr2", ".arw", ".dng", ".raf", ".raw", ".3fr", ".sr2", ".kdc", ".pef")):
            with rawpy.imread(file_path) as raw:
                if hasattr(raw.metadata, 'timestamp'):
                    try:
                        # Convert timestamp to datetime and format
                        parsed_date = datetime.fromtimestamp(raw.metadata.timestamp)
                        return parsed_date.isoformat()
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to parse RAW timestamp: {e}")
    except Exception as e:
        logger.warning(f"⚠️ rawpy failed to extract date from {file_path}: {e}")

    # Final fallback: file modification time, but only if it's not from today
    try:
        # Get file modification time
        mtime = os.path.getmtime(file_path)
        mod_datetime = datetime.fromtimestamp(mtime)
        
        # Current date for comparison
        today = datetime.now().date()
        
        # If the modification date is different from today, use it
        if mod_datetime.date() != today:
            return mod_datetime.isoformat()
    except Exception as e:
        logger.error(f"❌ Failed to extract modification time for {file_path}: {e}")

    # If no reliable date is found, return None
    logger.warning(f"No reliable date found for {file_path}")
    return None
def calculate_file_hash(file_path: str) -> Optional[str]:
    """Calculates the SHA-256 hash of a file based on its content."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, 'rb') as file:
            while chunk := file.read(4096):  # Read in chunks to avoid large memory usage
                hasher.update(chunk)
        return hasher.hexdigest()  # Return the hexadecimal hash
    except Exception as e:
        logger.error(f"❌ Error calculating hash for {file_path}: {e}")
        return None

def enforce_tagger_rate_limit() -> None:
    """Ensures requests don't exceed rate limits based on API tier."""
    # Read config to determine if using paid version
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    paid_version = config.get("tagger_gemini", "paid_version", fallback="false").lower() == "true"
    
    # Determine limit based on subscription tier
    tagger_limit = 2000 if paid_version else 15
    
    with tagger_queue_lock:
        current_time = time.time()
        # Clean up old timestamps
        while tagger_queue and tagger_queue[0] < current_time - TAGGER_WINDOW:
            tagger_queue.popleft()
        
        # Check if we're at the limit
        sleep_time = 0.0
        if len(tagger_queue) >= tagger_limit:
            sleep_time = TAGGER_WINDOW - (current_time - tagger_queue[0])
            logger.info(f"Rate limit reached ({'paid' if paid_version else 'free'} tier: {tagger_limit} rpm). Sleeping for {sleep_time:.2f} seconds.")
    
    # Sleep outside the lock if needed
    if sleep_time > 0:
        time.sleep(sleep_time)
    
    # Record this API call
    with tagger_queue_lock:
        tagger_queue.append(time.time())

def get_existing_photo_path(file_hash):
    """Checks if a photo exists in the database and returns its stored path."""
    conn = get_sqlite_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT file_path FROM photos WHERE file_hash = ?", (file_hash,))
        result = cur.fetchone()
        return result[0] if result else None  # Return file path if found, else None
    except sqlite3.Error as e:
        logger.error(f"Database error in get_existing_photo_path: {e}")
        return None
    finally:
        cur.close()


def photo_exists_in_db(file_hash):
    """Checks if a photo with the same hash already exists in the database."""
    conn = get_sqlite_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM photos WHERE file_hash = ?", (file_hash,))
        result = cur.fetchone()
        logger.info(f"🔍 Checking if file exists in DB: {file_hash} - Exists? {'Yes' if result else 'No'}")
        return result is not None  # Returns True if a match is found
    except sqlite3.Error as e:
        logger.error(f"Database error in photo_exists_in_db: {e}")
        return False
    finally:
        cur.close()



def update_photo_path(file_hash, new_path):
    """Updates the file path of an existing photo in the database and logs the change."""
    conn = get_sqlite_connection()
    cur = conn.cursor()
    try:
        # Retrieve the old path before updating
        cur.execute("SELECT file_path FROM photos WHERE file_hash = ?", (file_hash,))
        old_path = cur.fetchone()
        old_path = old_path[0] if old_path else "UNKNOWN"

        # Update the file path in the database
        cur.execute("UPDATE photos SET file_path = ? WHERE file_hash = ?", (new_path, file_hash))
        conn.commit()

        # Log the update
        logger.info(f"✅ Updated file path for {file_hash}: {old_path} → {new_path}")
    except sqlite3.Error as e:
        logger.error(f"❌ Database error in update_photo_path: {e}")
    finally:
        cur.close()

def process_existing_files(directory):
    """Scans the given directory (including subdirectories) and processes all existing image files."""
    logger.info(f"📂 Scanning for existing images in {directory} and subdirectories...")

    for file_path in glob.glob(os.path.join(directory, "**", "*"), recursive=True):
        if os.path.isfile(file_path):
            try:
                # Calculate the file hash before processing
                file_hash = calculate_file_hash(file_path)

                # Check if the image already exists in the database
                existing_path = get_existing_photo_path(file_hash)
                if (existing_path):
                    # If the stored path is different from the current file_path, update it.
                    if existing_path != file_path:
                        update_photo_path(file_hash, file_path)
                    else:
                        logger.info(f"✅ Skipping {file_path}, already processed with matching path.")
                    # Skip further processing for files already in the database.
                    continue

                # Process the file if it is new (i.e. its hash isn't in the database)
                resized_path = resize_and_compress_image(file_path, TARGET_MAX_SIZE_MB)
                if not resized_path:
                    logger.error(f"❌ Failed to resize or compress {file_path}")
                    continue

                enforce_tagger_rate_limit()

                # Generate tags using the temporary resized image
                tags = generate_tags(resized_path, CONFIG_FILE)

                # Insert metadata into the database for new images
                insert_data_into_db(file_path, tags, file_hash)

            except Exception as e:
                logger.error(f"❌ Error processing file {file_path}: {e}", exc_info=True)

def process_images_in_parallel(file_paths, config_file, stop_event):
    """
    Processes images in parallel with cooperative cancellation support.
    
    Args:
        file_paths (list): List of file paths to process
        config_file (str): Path to configuration file
        stop_event (threading.Event): Event to signal stopping the processing
    """
    logger.info("🚀 Starting parallel image processing...")
    
    results = {}
    batch_counter = 0
    
    # Shuffle file paths to distribute processing more evenly
    import random
    random.shuffle(file_paths)
    
    with ThreadPoolExecutor(max_workers=16) as executor:
        # Pre-check stop event before processing
        if stop_event.is_set():
            logger.info("Stop event set before starting parallel processing. Exiting immediately.")
            return
        
        # Track futures to allow early cancellation
        futures = {}
        
        # Submit tasks respecting stop event
        for file_path in file_paths:
            # Immediate exit if stop is requested
            if stop_event.is_set():
                logger.info("Stop event set during task submission. Cancelling remaining tasks.")
                break
            
            # Submit task with stop event
            future = executor.submit(wrapped_process_single_image, file_path, config_file, stop_event)
            futures[future] = file_path
        
        # Process completed futures
        for future in as_completed(futures):
            # Immediate exit if stop is requested
            if stop_event.is_set():
                logger.info("Stop event set during processing. Cancelling remaining futures.")
                break
            
            try:
                # Process future result if not stopped
                result = future.result()
                if result:
                    results[futures[future]] = result
                    batch_counter += 1
            
            except Exception as e:
                logger.error(f"❌ Error processing {futures[future]}: {e}")
    
    logger.info(f"✅ Parallel processing complete. Processed {batch_counter} images.")
    
    # Optional: Log if processing was interrupted
    if stop_event.is_set():
        logger.info("🛑 Processing was interrupted by stop event.")

def wrapped_process_single_image(file_path, config_file, stop_event=None):
    """
    Wrapper for process_single_image with cooperative cancellation support.
    
    Args:
        file_path (str): Path to the image file
        config_file (str): Path to configuration file
        stop_event (threading.Event, optional): Event to signal stopping the processing
    
    Returns:
        Result of processing or None if cancelled
    """
    # Check stop event before starting processing
    if stop_event and stop_event.is_set():
        logger.info(f"Stop event set. Skipping processing for {file_path}")
        return None

    try:
        # 🔍 Check if image already exists in DB
        file_hash = calculate_file_hash(file_path)
        
        # Cooperative cancellation point
        if stop_event and stop_event.is_set():
            logger.info(f"Stop event set during hash calculation for {file_path}")
            return None

        if photo_exists_in_db(file_hash):
            logger.info(f"✅ Skipping {file_path}, already exists in database.")
            return None

        # Cooperative cancellation point
        if stop_event and stop_event.is_set():
            logger.info(f"Stop event set before tag generation for {file_path}")
            return None

        # 🏷 Generate tags (use the config file for processing if needed)
        tags = generate_tags(file_path, config_file)
        
        # Cooperative cancellation point
        if stop_event and stop_event.is_set():
            logger.info(f"Stop event set after tag generation for {file_path}")
            return None

        if not tags:
            logger.warning(f"⚠ No tags generated for {file_path}. Skipping database insert.")
            return None

        # 🗄 Prepare database task with cancellation support
        def db_task(conn):
            # Final cancellation check before database operation
            if stop_event and stop_event.is_set():
                logger.info(f"Stop event set before database insert for {file_path}")
                return False

            cur = conn.cursor()

            try:
                # Use get_date_taken to extract the actual date the photo was taken
                date_taken = get_date_taken(file_path)
                
                # If no date is found, use file creation time as an absolute last resort
                if date_taken is None:
                    try:
                        creation_time = os.path.getctime(file_path)
                        date_taken = datetime.fromtimestamp(creation_time).isoformat()
                        logger.info(f"Using file creation time for {file_path}")
                    except Exception as e:
                        logger.warning(f"Could not get file creation time: {e}")
                        date_taken = datetime.now().isoformat()  # Absolute final fallback

                # 🔹 Insert photo metadata
                cur.execute(
                    "INSERT INTO photos (photo_id, file_path, date_taken, file_hash) VALUES (?, ?, ?, ?) ON CONFLICT(photo_id) DO NOTHING",
                    (file_hash, file_path, date_taken, file_hash)
                )

                # Use file_hash as the photo_id directly
                for tag in tags:
                    cur.execute("INSERT INTO tags (tag) VALUES (?) ON CONFLICT(tag) DO NOTHING", (tag,))
                    cur.execute(
                        "INSERT INTO photo_tags (photo_id, tag_id) VALUES (?, (SELECT id FROM tags WHERE tag = ?))",
                        (file_hash, tag)
                    )

                conn.commit()  # 💾 Save immediately after each image
                logger.debug(f"📌 DB entry pushed for {file_path}")
                logger.info(f"✅ Successfully processed and stored {file_path} with {len(tags)} tags. Date taken: {date_taken}")
                return True
            except Exception as e:
                logger.error(f"❌ Database insertion error for {file_path}: {e}")
                conn.rollback()
                return False
            finally:
                cur.close()

        # Enqueue the database task only if not cancelled
        if not (stop_event and stop_event.is_set()):
            db_write_queue.put(db_task)
            return True

        return None

    except Exception as e:
        # Catch and log any unexpected errors
        logger.error(f"❌ Unhandled error processing {file_path}: {e}")
        return None
    
def process_single_image(image_path, config_file):
    """Process an image, generate tags, and insert directly into the database."""
    try:
        # 🔍 Check if image already exists in DB
        file_hash = calculate_file_hash(image_path)
        if photo_exists_in_db(file_hash):
            logger.info(f"✅ Skipping {image_path}, already exists in database.")
            return

        # 🏷 Generate tags (use the config file for processing if needed)
        tags = generate_tags(image_path, config_file)  # Ensure config_file is used in your tag generation function
        if not tags:
            logger.warning(f"⚠ No tags generated for {image_path}. Skipping database insert.")
            return

        # 🗄 Open a connection for this image only
        def db_task(conn):
            cur = conn.cursor()

            # 🔹 Insert photo metadata
            cur.execute(
                "INSERT INTO photos (photo_id, file_path, date_taken, file_hash) VALUES (?, ?, ?, ?) ON CONFLICT(photo_id) DO NOTHING",
                (file_hash, image_path, datetime.now().isoformat(), file_hash)
            )

            # Use file_hash as the photo_id directly
            for tag in tags:
                cur.execute("INSERT INTO tags (tag) VALUES (?) ON CONFLICT(tag) DO NOTHING", (tag,))
                cur.execute(
                    "INSERT INTO photo_tags (photo_id, tag_id) VALUES (?, (SELECT id FROM tags WHERE tag = ?))",
                    (file_hash, tag)
                )

            conn.commit()  # 💾 Save immediately after each image
            logger.debug(f"📌 DB entry pushed for {image_path}")
            logger.info(f"✅ Successfully processed and stored {image_path} with {len(tags)} tags.")
            cur.close()

        db_write_queue.put(db_task)

    except Exception as e:
        logger.error(f"❌ Error processing {image_path}: {e}")

def resize_and_compress_image(file_path, target_max_size_mb):
    """Resizes and compresses an image, converting RAW to JPEG if necessary."""
    try:
        raw_extensions = (".nef", ".cr2", ".arw", ".dng", ".raf", ".raw", ".3fr", ".sr2", ".kdc", ".pef")

        if file_path.lower().endswith(raw_extensions):
            logger.info(f"📸 Converting RAW to RGB: {file_path}")
            img = process_raw_image(file_path)  # Convert RAW to PIL Image
            if img is None:
                logger.error(f"❌ Failed to process RAW image: {file_path}")
                return None
        else:
            img = Image.open(file_path)

        # Ensure image is in RGB mode
        if img.mode not in ("RGB", "L"):
            logger.warning(f"⚠ Unexpected image mode: {img.mode}. Converting to RGB.")
            img = img.convert("RGB")

        initial_file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Only resize if the image is larger than the target size
        if initial_file_size_mb > target_max_size_mb:
            max_dimension = max(img.width, img.height)
            target_max_dimension = 800  # Adjust as needed

            if max_dimension > target_max_dimension:
                scaling_factor = target_max_dimension / max_dimension
                new_width = int(img.width * scaling_factor)
                new_height = int(img.height * scaling_factor)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # 🔹 Save resized image as JPEG instead of RAW
        temp_resized_file = os.path.join(tempfile.gettempdir(), "temp_resized_" + os.path.basename(file_path).replace(".nef", ".jpg").replace(".pef", ".jpg"))

        for quality in [75, 65, 55]:
            img.save(temp_resized_file, "JPEG", optimize=True, quality=quality)
            final_file_size_mb = os.path.getsize(temp_resized_file) / (1024 * 1024)

            if final_file_size_mb <= target_max_size_mb:
                logger.info(f"✅ Successfully resized {file_path} to {final_file_size_mb:.2f}MB as JPEG")
                return temp_resized_file

        logger.warning(f"⚠ Compression could not reduce {file_path} below {target_max_size_mb}MB")
        return temp_resized_file  # Return the best effort compression

    except Exception as e:
        logger.error(f"❌ Error resizing or compressing {file_path}: {e}", exc_info=True)
        return None

def process_raw_image(raw_path: str) -> Optional[Image.Image]:
    """Processes a RAW image file using rawpy or imageio and returns a PIL image."""
    try:
        with rawpy.imread(raw_path) as raw:
            logger.info(f"📸 Successfully opened RAW file: {raw_path}")
            rgb = raw.postprocess()
            return Image.fromarray(rgb)
    except rawpy.LibRawFileUnsupportedError:
        logger.warning(f"⚠ `rawpy` does not support this RAW file: {raw_path}. Trying imageio...")
    except Exception as e:
        logger.error(f"❌ Error processing RAW file {raw_path} with rawpy: {e}")

    # 🔹 Try `imageio` as a backup method
    try:
        img = imageio.imread(raw_path)
        return Image.fromarray(img)
    except Exception as e:
        logger.error(f"❌ Failed to process RAW file with imageio: {e}")

    return None


class ImageTagger:
    def __init__(self, config_file: str):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.gemini_api_key = self.config.get("tagger_gemini", "gemini_api_key")
        self.paid_version = self.config.get("tagger_gemini", "paid_version", fallback="false").lower() == "true"
        self.confidence_threshold = float(self.config.get("tagger_gemini", "confidence_threshold", fallback=0.7))
        self.max_tags = int(self.config.get("tagger_gemini", "max_tags", fallback=30))
        self.max_image_size = int(self.config.get("tagger_gemini", "max_image_size", fallback=1024))
        logger.info(f"Initializing ImageTagger (Using {'paid' if self.paid_version else 'free'} API tier)")
        self._init_gemini()

    def _init_gemini(self):
        if not self.gemini_api_key or self.gemini_api_key.startswith("AIzaSy") is False:
            logger.error("Invalid or missing GEMINI_API_KEY in configuration.")
            self.gemini_model = None
            return
        try:
            genai.configure(api_key=self.gemini_api_key)
            # Updated model name to 'gemini-1.5-flash'
            self.gemini_model = genai.GenerativeModel("gemini-2.0-flash")
            logger.info("Gemini model initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            self.gemini_model = None

    def _validate_image_path(self, image_path: str) -> bool:
        path = Path(image_path)
        if not path.exists():
            logger.error(f"Image path does not exist: {image_path}")
            return False
        return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".nef", ".cr2", ".arw", ".dng"}

    def _open_image(self, image_path: str) -> Optional[Image.Image]:
        """Opens an image file, ensuring RAW formats are converted properly."""
        try:
            raw_extensions = (".nef", ".cr2", ".arw", ".dng", ".raf", ".raw", ".3fr", ".sr2", ".kdc", ".pef")

            if image_path.lower().endswith(raw_extensions):
                logger.info(f"📸 Processing RAW image for tagging: {image_path}")
                img = process_raw_image(image_path)  # Convert RAW to RGB
                if img is None:
                    logger.error(f"❌ Failed to process RAW image: {image_path}")
                    return None
                return img  # Return the PIL Image
            
            elif image_path.lower().endswith(".jpg"):  # ✅ Now correctly processes converted RAW images
                return Image.open(image_path).convert("RGB")  

            else:
                logger.warning(f"⚠ Unsupported image format: {image_path}")
                return None

        except Exception as e:
            logger.error(f"❌ Error opening image {image_path}: {e}", exc_info=True)
            return None
        
    def _resize_image(self, image: Image.Image) -> Image.Image:
        """Resize the image to a maximum dimension while preserving aspect ratio"""
        if max(image.size) > self.max_image_size:
            if image.width > image.height:
                new_width = self.max_image_size
                new_height = int(image.height * (self.max_image_size / image.width))
            else:
                new_height = self.max_image_size
                new_width = int(image.width * (self.max_image_size / image.height))
            image = image.resize((new_width, new_height))
            logger.info(f"Resized image to {new_width}x{new_height}")
        return image

    def generate_content_with_timeout(self, model, contents, timeout):
        result = {}
        def task():
            try:
                response = model.generate_content(contents)
                response.resolve()
                result['response'] = response
            except Exception as e:
                result['error'] = e
        thread = threading.Thread(target=task)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            logger.warning("Gemini API request timed out")
            return None
        elif 'error' in result:
            logger.error(f"Error generating tags with Gemini: {result['error']}")
            return None
        else:
            return result['response']

    def _generate_gemini_tags(self, image: Image.Image) -> List[Tuple[str, float]]:
        if not self.gemini_model:
            logger.warning("⚠ Skipping Gemini tag generation due to missing or invalid API key.")
            return []

        try:
            logger.info("📡 Sending image to Gemini for tagging...")
            response = self.generate_content_with_timeout(
                self.gemini_model,
                ["Generate comma-separated detailed tags for this image, describing subject, context, and visual details.", image],
                timeout=30
            )

            if not response:
                logger.error("❌ Gemini API request failed or timed out")
                return []

            logger.info("✅ Received response from Gemini API")

            # Extract tags but don't log them
            tags = [tag.strip() for tag in response.text.lower().split(",") if tag.strip()]
            logger.info(f"✅ Processed Gemini tags: {len(tags)} tags generated.")  # Show count, not the tags

            return [(tag, 0.9) for tag in tags if len(tag) > 1]  # Assigning a default confidence of 0.9

        except Exception as e:
            logger.error(f"❌ Error generating tags with Gemini: {e}")
            return []



    def generate_tags(self, image_path: str) -> List[str]: 
        """Generates AI-generated tags for an image using the Gemini model."""
        image_path_obj = Path(image_path)
        if not self._validate_image_path(str(image_path_obj)):
            logger.error(f"❌ Invalid image path: {image_path}")
            return []
        try:
            img = self._open_image(str(image_path_obj))
            if img is None:
                logger.error(f"❌ Could not open or process image: {image_path}")
                return []
        
            # Resize the image if necessary before sending it to the API.
            img = self._resize_image(img)
        
            # Enforce the rate limit before calling the API.
            enforce_tagger_rate_limit()

            # Generate tags using the Gemini API.
            tags_with_confidence = self._generate_gemini_tags(img)
        
            # Filter and return unique tags above the confidence threshold.
            unique_tags = list({tag for tag, confidence in tags_with_confidence if confidence >= self.confidence_threshold})
            
            logger.info(f"✅ Generated {len(unique_tags)} tags for {image_path}.")  # Log count only

            return unique_tags[:self.max_tags]

        except Exception as e:
            logger.error(f"❌ Error processing image {image_path}: {e}", exc_info=True)
            return []



def generate_tags(image_path: str, config_file: str) -> List[str]:
    try:
        tagger = ImageTagger(config_file)
        return tagger.generate_tags(image_path)
    except Exception as e:
        logger.error(f"Fatal error during tag generation: {e}")
        # Consider re-raising the exception or returning an empty list
        return []

def insert_data_into_db(original_file_path, tags, file_hash):
    """Insert photo metadata (and associated tags) into the database efficiently."""
    if not tags:
        logger.info(f"Skipping {original_file_path} as it has no tags.")
        return

    logger.info(f"Starting database insert for {original_file_path} with {len(tags)} tags.")

    def insert_data_into_db(original_file_path, tags, file_hash):
        """Insert photo metadata (and associated tags) into the database efficiently."""
        if not tags:
            logger.info(f"Skipping {original_file_path} as it has no tags.")
            return

        logger.info(f"Starting database insert for {original_file_path} with {len(tags)} tags.")

        def db_task(conn):
            cur = conn.cursor()

            try:
                # Ensure the file exists and is readable
                if not os.access(original_file_path, os.R_OK):
                    logger.error(f"Permission denied for file: {original_file_path}")
                    return
                logger.info(f"File {original_file_path} is accessible for reading.")

                # Use get_date_taken to extract the actual date the photo was taken
                date_taken = get_date_taken(original_file_path)
                
                # If no date is found, use file creation time as an absolute last resort
                if date_taken is None:
                    try:
                        creation_time = os.path.getctime(original_file_path)
                        date_taken = datetime.fromtimestamp(creation_time).isoformat()
                        logger.info(f"Using file creation time for {original_file_path}")
                    except Exception as e:
                        logger.warning(f"Could not get file creation time: {e}")
                        date_taken = datetime.now().isoformat()  # Absolute final fallback

                logger.info(f"Extracted date for {original_file_path}: {date_taken}")

                # Check if a transaction is already in progress
                cur.execute("PRAGMA database_list;")
                result = cur.fetchall()
                if len(result) > 0:
                    logger.info("Transaction is already in progress. Skipping BEGIN TRANSACTION.")
                else:
                    # Start a new transaction if one is not already in progress
                    logger.info("Starting new transaction.")
                    cur.execute("BEGIN TRANSACTION;")

                # Insert into `photos` table with the extracted date
                logger.info(f"Inserting metadata for {original_file_path} into `photos` table.")
                cur.execute(
                    """
                    INSERT INTO photos (photo_id, file_path, file_hash, date_taken)
                    VALUES (?, ?, ?, ?)
                    """,
                    (file_hash, original_file_path, file_hash, date_taken),
                )
                new_photo_id = file_hash  # Use file_hash as photo_id

                # Insert tags into `tags` table in bulk
                logger.info(f"Inserting {len(tags)} tags into `tags` table.")
                tag_data = [(tag,) for tag in tags]
                cur.executemany("INSERT OR IGNORE INTO tags (tag) VALUES (?);", tag_data)

                # Get tag IDs efficiently
                logger.info(f"Retrieving tag IDs for {len(tags)} tags.")
                cur.execute(
                    f"SELECT id, tag FROM tags WHERE tag IN ({','.join(['?'] * len(tags))})",
                    tags
                )
                tag_id_map = {tag: tag_id for tag_id, tag in cur.fetchall()}
                
                # Log the retrieved tag IDs to help with debugging
                logger.info(f"Retrieved {len(tag_id_map)} tag IDs.")

                if not tag_id_map:
                    logger.warning(f"No valid tags found in the database for {original_file_path}. Skipping photo_tags insertion.")
                    return

                # Insert into `photo_tags` table in bulk using the auto-generated photo_id
                photo_tags_data = [(new_photo_id, tag_id_map[tag]) for tag in tags if tag in tag_id_map]
                
                # Log the number of photo_tags_data entries
                logger.info(f"Inserting {len(photo_tags_data)} tag associations into `photo_tags` table.")
                
                if not photo_tags_data:
                    logger.warning(f"No valid tag associations found for {original_file_path}. Skipping `photo_tags` insertion.")
                    return
                
                cur.executemany("INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?, ?);", photo_tags_data)

                # Commit the transaction
                conn.commit()
                logger.debug(f"📌 DB entry pushed for {original_file_path}")
                logger.info(f"✅ Successfully inserted {original_file_path} with {len(tags)} tags into the database.")

            except sqlite3.Error as e:
                conn.rollback()  # Rollback in case of an error
                logger.error(f"❌ SQLite error in insert_data_into_db: {e}")
            except Exception as ex:
                conn.rollback()
                logger.error(f"❌ Unexpected error: {ex}")
            finally:
                cur.close()
                logger.info(f"Database transaction completed for {original_file_path}.")

        db_write_queue.put(db_task)

def db_writer_thread(stop_event):
    """
    Database writer thread with stop event support.
    
    Args:
        stop_event (threading.Event): Event to signal stopping the thread
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    logger.info("✅ DB writer thread started.")
    
    try:
        while not stop_event.is_set():
            try:
                # Use a timeout to periodically check stop_event
                task = db_write_queue.get(timeout=1)
                
                # Exit if stop event is set and queue is empty
                if stop_event.is_set() and db_write_queue.empty():
                    break
                
                try:
                    task(conn)
                    conn.commit()
                except Exception as e:
                    logger.error(f"❌ Error in DB writer task: {e}")
                    conn.rollback()
                finally:
                    db_write_queue.task_done()
            
            except queue.Empty:
                # Periodically check stop event
                if stop_event.is_set():
                    break
    
    except Exception as e:
        logger.error(f"❌ Unexpected error in DB writer thread: {e}")
    
    finally:
        # Ensure any remaining tasks are processed
        while not db_write_queue.empty():
            try:
                task = db_write_queue.get_nowait()
                try:
                    task(conn)
                    conn.commit()
                except Exception as e:
                    logger.error(f"❌ Error processing final tasks: {e}")
                    conn.rollback()
                finally:
                    db_write_queue.task_done()
            except queue.Empty:
                break
        
        conn.close()
        logger.info("✅ DB writer thread stopped.")


def run_scan(stop_event=None):
    """
    Core logic to scan folders and process images.
    
    Args:
        stop_event (threading.Event, optional): Event to signal stopping the processing
    """
    # Load fresh configuration at runtime
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    watch_folders_config = config["watch"]["folder"]
    
    logger.info(f"📂 Starting folder scan on: {watch_folders_config}")
    
    # Create a stop event if not provided
    if stop_event is None:
        stop_event = threading.Event()
    
    EXCLUDED_EXTENSIONS = (".xmp", ".txt", ".csv", ".json", ".log")
    file_paths = []
    # Convert watch_folders_config into a list of folder paths (comma separated if more than one)
    watch_folders = [folder.strip() for folder in watch_folders_config.split(",")]
    
    for folder in watch_folders:
        # Break the loop if stop is requested
        if stop_event.is_set():
            logger.info("Stop event set during directory scanning. Exiting.")
            return
        
        # Gather valid file paths from each folder
        folder_paths = [
            file_path
            for file_path in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
            if os.path.isfile(file_path) and not file_path.lower().endswith(EXCLUDED_EXTENSIONS)
        ]
        file_paths.extend(folder_paths)
    
    # Exit if no files found or stop requested
    if not file_paths or stop_event.is_set():
        logger.info("No files to process or stop event set.")
        return
    
    logger.info(f"Found {len(file_paths)} valid files. Processing in parallel...")
    
    # Start dedicated DB writer thread before processing images
    stop_db_writer = threading.Event()
    writer = threading.Thread(target=db_writer_thread, kwargs={'stop_event': stop_db_writer}, daemon=True)
    writer.start()
    
    try:
        process_images_in_parallel(file_paths, CONFIG_FILE, stop_event)
    except Exception as e:
        logger.error(f"Error during parallel processing: {e}")
    finally:
        # Signal DB writer to stop
        stop_db_writer.set()
        # Wait for DB writer to finish
        writer.join(timeout=5)
    
    logger.info("✅ Done processing. Exiting script.")
    
    # Call shutdown only if available
    if hasattr(genai, "shutdown"):
        try:
            genai.shutdown()  # if such a method exists in the genai library
        except Exception as e:
            logger.warning(f"Optional shutdown failed: {e}")

def main(stop_event=None):
    """Entry point for the application to call."""
    if stop_event is None:
        stop_event = threading.Event()
    run_scan(stop_event)

if __name__ == "__main__":
    """Entry point for standalone execution."""
    import signal
    
    # Create a stop event
    stop_event = threading.Event()
    
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
        stop_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run the scan with stop event support
    run_scan(stop_event)

