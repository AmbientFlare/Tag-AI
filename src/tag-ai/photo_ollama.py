# photo_ollama.py
##this is know working version of the script
#this script is used to tag photos using ollama and sqlite
from __future__ import annotations
import datetime
import os
import sys
import logging
import configparser
import base64
import requests
import queue
import sqlite3
import threading
import hashlib
import glob
from typing import Optional
from io import BytesIO
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None
import tempfile
import re
import time
import signal
import traceback
try:
    import rawpy
except ImportError:
    rawpy = None
try:
    import imageio
except ImportError:
    imageio = None

try:
    from paths import get_default_config_path, get_default_db_path, setup_logging
except ImportError:
    # Fallback stubs for testing or non-package import
    def get_default_config_path():
        return None
    def get_default_db_path():
        return None
    def setup_logging(*args, **kwargs):
        pass
    
try:
    from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetUtilizationRates
except ImportError:
    def nvmlInit():
        pass
    def nvmlDeviceGetHandleByIndex(index):
        return None
    class NVUtil:
        gpu = 0
        memory = 0
    def nvmlDeviceGetUtilizationRates(handle):
        return NVUtil()

# Configure logging
setup_logging("photo_ollama", logging.INFO)
logger = logging.getLogger(__name__)
stop_event = threading.Event()

# --- Global Configurations ---
CONFIG_FILE = get_default_config_path()
# SQLite Database Configuration (DB in the same folder as the script)
DB_PATH = get_default_db_path()
# Global queue for future database write tasks
db_write_queue = queue.Queue()
# Thread-local storage for SQLite connections
thread_local = threading.local()

# --- New Global Variables and Queues ---
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff"}  # allowed non-raw formats
RAW_EXTENSIONS = {".nef", ".cr2", ".arw", ".dng", ".raf", ".raw", ".3fr", ".sr2", ".kdc", ".pef"}
FILE_QUEUE = queue.Queue()
PROCESSED_QUEUE = queue.Queue()  # To hold processed image jobs with file info
# db_write_queue is already defined

# New constant for maximum number of llm workers
MAX_LLM_WORKERS = 24

# Add these global variables at the top with other globals
PROCESSING_TIMES = []
PROCESSING_LOCK = threading.Lock()

# Add new global constant below PROCESSED_QUEUE declaration
FILE_PROCESSING_AHEAD_LIMIT = 30

# Add new globals for overall processing time
SCRIPT_START_TIME = time.time()
FILES_PROCESSED = 0
def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
    stop_event.set()

# ----------------------
# Database-related Functions
# ----------------------

def get_sqlite_connection() -> sqlite3.Connection:
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

def get_existing_photo_path(file_hash: str) -> Optional[str]:
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

def photo_exists_in_db(file_hash: str) -> bool:
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

def update_photo_path(file_hash: str, new_path: str) -> None:
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

# --- New Helper Functions ---

def is_photo_file(file_path: str) -> bool:
    _, ext = os.path.splitext(file_path.lower())
    # Only treat non-raw extensions as photo files
    return ext in PHOTO_EXTENSIONS

def is_raw_file(file_path: str) -> bool:
    _, ext = os.path.splitext(file_path.lower())
    return ext in RAW_EXTENSIONS

def process_raw_image(file_path: str):
    try:
        if rawpy:
            with rawpy.imread(file_path) as raw:
                rgb = raw.postprocess()
                return Image.fromarray(rgb)
        elif imageio:
            img_arr = imageio.imread(file_path)
            return Image.fromarray(img_arr)
        else:
            logger.error("No raw image processing library available for %s", file_path)
            return None
    except Exception as e:
        logger.error("❌ Error processing raw image %s: %s", file_path, e)
        return None

def process_image_resized(file_path: str) -> Optional[str]:
    try:
        if is_raw_file(file_path):
            img = process_raw_image(file_path)
        else:
            img = Image.open(file_path)
        if not img:
            return None
        img = img.convert("RGB")
        # Resize and pad to 672x672 with black background using ImageOps.pad
        target_size = (672, 672)
        img = ImageOps.pad(img, target_size, method=Image.Resampling.LANCZOS, color=(0,0,0))
        # Save to a temporary file and return its path
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(temp_file.name, format="JPEG", quality=85)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        logger.error("❌ Error processing image %s: %s", file_path, e)
        return None

# --- Worker Functions ---



logger = logging.getLogger(__name__)

def get_date_taken(file_path):
    try:
        # Try using PIL first with more comprehensive EXIF extraction
        with Image.open(file_path) as img:
            exif_data = img.getexif()
            if exif_data:
                # Try multiple common EXIF datetime tags
                date_tags = [36867, 36868, 306]  # DateTimeOriginal, DateTimeDigitized, DateTime
                for tag in date_tags:
                    date_taken = exif_data.get(tag)
                    if date_taken:
                        return date_taken
    except Exception as e:
        logger.warning(f"⚠️ PIL failed to extract date from {file_path}: {e}")

    try:
        # Fallback: Use rawpy for RAW files
        if rawpy and is_raw_file(file_path):
            with rawpy.imread(file_path) as raw:
                if hasattr(raw.metadata, 'timestamp'):
                    return raw.metadata.timestamp
    except Exception as e:
        logger.warning(f"⚠️ rawpy failed to extract date from {file_path}: {e}")

    try:
        # Additional fallback: Use imageio if available
        if imageio:
            metadata = imageio.get_reader(file_path).get_meta_data()
            if 'datetime' in metadata:
                return metadata['datetime']
    except Exception as e:
        logger.warning(f"⚠️ imageio failed to extract date from {file_path}: {e}")

    # Final fallback: file modification time
    try:
        timestamp = os.path.getmtime(file_path)
        return datetime.datetime.fromtimestamp(timestamp).strftime('%Y:%m:%d %H:%M:%S')
    except Exception as e:
        logger.error(f"❌ Failed to extract date from {file_path}: {e}")
        return datetime.datetime.now().strftime('%Y:%m:%d %H:%M:%S')

def file_worker(stop_event):
    while not stop_event.is_set():
        try:
            file_path = FILE_QUEUE.get(timeout=5)
            # Wait if processed queue is too far ahead
            while not stop_event.is_set() and PROCESSED_QUEUE.qsize() >= FILE_PROCESSING_AHEAD_LIMIT:
                time.sleep(0.5)
            if stop_event.is_set():
                FILE_QUEUE.task_done()
                break
            start_time = time.time()  # Capture start time
            try:
                if not is_photo_file(file_path):
                    logger.debug("Skipping non-photo file: %s", file_path)
                    continue
                file_hash = calculate_file_hash(file_path)
                if not file_hash:
                    continue

                # Check if the photo exists in the database
                if photo_exists_in_db(file_hash):
                    existing_file_path = get_existing_photo_path(file_hash)
                    if existing_file_path != file_path:
                        update_photo_path(file_hash, file_path)
                        logger.info("File hash %s exists but path updated from %s to %s", file_hash, existing_file_path, file_path)
                    logger.info("File %s already processed (hash exists). Skipping processing.", file_path)
                    continue  # Skip further processing

                # Proceed with processing if the hash does not exist
                date_taken = get_date_taken(file_path)
                temp_image_path = process_image_resized(file_path)
                if not temp_image_path:
                    logger.error("❌ Failed processing %s", file_path)
                    continue
                PROCESSED_QUEUE.put({
                    "orig_file_path": file_path,
                    "date_taken": date_taken,
                    "file_hash": file_hash,
                    "temp_image_path": temp_image_path,
                    "retry": 0,
                    "start_time": start_time
                })
            except Exception as e:
                logger.error("❌ Exception in file_worker for %s: %s", file_path, e)
            finally:
                FILE_QUEUE.task_done()
        except queue.Empty:
            if stop_event.is_set():
                break
            continue
    logger.info("File worker exiting due to stop_event.")

# Modified llm_worker_proc to log average processing time after each DB entry
def llm_worker_proc(config, prompt, stop_event):
    global FILES_PROCESSED, SCRIPT_START_TIME

    while not stop_event.is_set():
        try:
            # Use a timeout to periodically check the stop_event
            try:
                item = PROCESSED_QUEUE.get(timeout=1)
            except queue.Empty:
                continue

            # Check for sentinel value or stop event
            if item is None or stop_event.is_set():
                PROCESSED_QUEUE.task_done()
                break

            # Reset retry tracking for each item
            retries = 0
            tags = None

            # Retry logic with stop event check
            while retries < 3 and not stop_event.is_set():
                tags = query_ollama_api(config, prompt, item["temp_image_path"])
                if tags and is_valid_tags(tags):
                    break
                retries += 1
                logger.info(f"Retry {retries} for file {item['orig_file_path']}")

            # Process tags if obtained successfully
            if tags and is_valid_tags(tags):
                db_write_queue.put({
                    "file_path": item["orig_file_path"],
                    "date_taken": item["date_taken"],
                    "file_hash": item["file_hash"],
                    "tags": tags
                })
                
                # Update processing metrics
                FILES_PROCESSED += 1
                avg_time = (time.time() - SCRIPT_START_TIME) / FILES_PROCESSED
                logger.info(
                    "DB entry made for %s. Average processing time: %.2f seconds over %d files",
                    os.path.basename(item["orig_file_path"]), 
                    avg_time, 
                    FILES_PROCESSED
                )
            else:
                # Log files that couldn't be processed
                unable_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unable_to_do.txt")
                with open(unable_path, "a") as f:
                    f.write(f"{item['orig_file_path']} unable to process\n")
                logger.error(f"Unable to process {item['orig_file_path']} after retries")

            # Clean up temporary image file
            try:
                os.remove(item["temp_image_path"])
            except Exception as cleanup_error:
                logger.warning(f"Failed to remove temporary image: {cleanup_error}")

            # Mark task as done
            PROCESSED_QUEUE.task_done()

        except Exception as e:
            # Catch and log any unexpected errors
            logger.error(f"Unexpected error in LLM worker: {e}")
            logger.error(traceback.format_exc())
            
            # Ensure the task is marked as done to prevent queue blocking
            if 'item' in locals():
                PROCESSED_QUEUE.task_done()

    # Final logging when worker exits
    logger.info("LLM worker exiting.")

def query_ollama_api(config: configparser.ConfigParser, prompt: str, image_path: str) -> Optional[str]:
    url = config["tagger_ollama"]["ollama_endpoint"]
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": config["tagger_ollama"]["model_name"],
        "prompt": prompt,
        "stream": False
    }
    try:
        img = preprocess_image(image_path)
        buffered = BytesIO()
        img.save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        payload["images"] = [image_base64]
    except Exception as e:
        logger.error("❌ Error processing image for llm query %s: %s", image_path, e)
        return None
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            logger.error("❌ Ollama API error %s: %s", response.status_code, response.text)
            return None
    except Exception as e:
        logger.error("❌ Exception during Ollama API query: %s", e)
        return None

def is_valid_tags(tags: str) -> bool:
    # Updated: Accept one or more comma-separated tags with optional spaces.
    return bool(re.fullmatch(r'[\w\s]+(,\s*[\w\s]+)*', tags.strip()))

def insert_data_into_db(entry: dict):
    conn = get_sqlite_connection()
    cur = conn.cursor()
    try:
        # Insert photo record
        cur.execute(
            """INSERT OR IGNORE INTO photos 
               (photo_id, file_path, date_taken, file_hash) VALUES (?, ?, ?, ?)""",
            (entry["file_hash"], entry["file_path"], entry["date_taken"], entry["file_hash"])
        )
        # Process tags
        tags = [t.strip() for t in entry["tags"].split(",")]
        for tag in tags:
            cur.execute("INSERT OR IGNORE INTO tags (tag) VALUES (?)", (tag,))
            cur.execute("SELECT id FROM tags WHERE tag = ?", (tag,))
            result = cur.fetchone()
            if result is not None:
                tag_id = result[0]
                logger.debug("Inserting into photo_tags with photo_id: %s and tag_id: %s", entry["file_hash"], tag_id)
                cur.execute("INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?, ?)", (entry["file_hash"], tag_id))
            else:
                logger.error("No tag id found for tag: %s", tag)
        conn.commit()
        logger.info("✅ Inserted data for %s", entry["file_path"])
    except sqlite3.Error as e:
        logger.error("❌ DB insertion error for %s: %s", entry["file_path"], e)
    finally:
        cur.close()

def update_photo_tags(entry: dict):
    """
    Update the many-to-many tag associations for a photo.
    This function removes any existing associations in photo_tags for the given photo,
    then ensures each tag exists in the tags table and creates a new record in photo_tags.
    
    The entry dict should include:
      - file_hash: unique photo identifier (and photo_id in photos table)
      - file_path: for logging purposes
      - tags: a comma-separated string of new tags
    """
    conn = get_sqlite_connection()
    cur = conn.cursor()
    try:
        # Clear existing tag associations for the photo
        cur.execute("DELETE FROM photo_tags WHERE photo_id = ?", (entry["file_hash"],))
        
        # Process and update new tag associations
        tags = [t.strip() for t in entry["tags"].split(",")]
        for tag in tags:
            # Add the tag to the tags table if it doesn't already exist
            cur.execute("INSERT OR IGNORE INTO tags (tag) VALUES (?)", (tag,))
            # Retrieve the tag's unique id from the tags table
            cur.execute("SELECT id FROM tags WHERE tag = ?", (tag,))
            result = cur.fetchone()
            if result is not None:
                tag_id = result[0]
                logger.debug("Updating photo_tags: photo_id='%s' with tag_id='%s'", entry["file_hash"], tag_id)
                cur.execute("INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?, ?)", (entry["file_hash"], tag_id))
            else:
                logger.error("No tag id found for tag: %s", tag)
        conn.commit()
        logger.info("✅ Updated tags for %s", entry["file_path"])
    except sqlite3.Error as e:
        logger.error("❌ DB update error for %s: %s", entry["file_path"], e)
    finally:
        cur.close()

def db_worker_proc(stop_event):
    while True:
        try:
            # Use a 1-second timeout if stop_event is set, otherwise 5 seconds
            timeout = 1 if stop_event.is_set() else 5
            entry = db_write_queue.get(timeout=timeout)
            if entry is None:  # Sentinel value to exit
                db_write_queue.task_done()
                break
            insert_data_into_db(entry)
            db_write_queue.task_done()
        except queue.Empty:
            if stop_event.is_set():
                logger.info("Stop event set and queue is empty, exiting db worker.")
                break
            continue

# ----------------------
# Application Functions
# ----------------------

def load_config(config_file: str) -> configparser.ConfigParser:
    """Load and return the configuration from the given file."""
    config = configparser.ConfigParser()
    config.read(config_file)
    return config

def validate_config(config: configparser.ConfigParser) -> bool:
    """
    Validate configuration values.
    
    Ensures that the required sections and keys exist:
      - [watch]: folder
      - [image_processing]: target_max_size_mb
      - [tagger_ollama]: ollama_endpoint, model_name
    """
    required_sections = {
        "watch": ["folder"],
        "image_processing": ["target_max_size_mb"],
        "tagger_ollama": ["ollama_endpoint", "model_name"]
    }
    valid = True
    for section, keys in required_sections.items():
        if not config.has_section(section):
            logger.error("Missing required section: [%s]", section)
            valid = False
        else:
            for key in keys:
                if key not in config[section]:
                    logger.error("Missing required key '%s' in section [%s]", key, section)
                    valid = False
    return valid

def preprocess_image(image_path: str, target_size=(672, 672)) -> Image.Image:
    """
    Opens an image, converts it to RGB, and resizes it to the target size.
    Uses ImageOps.fit to crop or pad as needed to maintain the aspect ratio.
    """
    try:
        img = Image.open(image_path).convert("RGB")
        img = ImageOps.fit(img, target_size, Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        logger.error("Error processing image '%s': %s", image_path, e)
        raise

def query_llava(config: configparser.ConfigParser, prompt: str, image_path: str = None) -> None:
    """
    Queries a locally running Ollama LLaVA instance via HTTP API with a given prompt.
    If image_path is provided, the image is preprocessed and sent as a Base64-encoded string.
    """
    url = config["tagger_ollama"]["ollama_endpoint"]
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": config["tagger_ollama"]["model_name"],
        "prompt": prompt,
        "stream": False
    }
    
    if image_path:
        try:
            img = preprocess_image(image_path)
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            payload["images"] = [image_base64]
        except FileNotFoundError:
            logger.error("File not found: %s", image_path)
            return
        except Exception as e:
            logger.error("Error processing image: %s", e)
            return

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            logger.info("LLaVA Response: %s", response.json().get("response", "No response received."))
        else:
            logger.error("Error %s: %s", response.status_code, response.text)
    except requests.RequestException as e:
        logger.error("HTTP Request failed: %s", e)

# Modified helper function to spawn new llm workers until GPU utilization is above 90%
def monitor_llm_and_scale(
    config: configparser.ConfigParser,
    prompt: str,
    llm_workers: list,
    gpu_handle,
    stop_event: threading.Event
) -> None:
    while not stop_event.is_set():
        try:
            util = nvmlDeviceGetUtilizationRates(gpu_handle).gpu
        except Exception as e:
            logger.error("❌ NVML error: %s", e)
            break
        logger.info("Current GPU utilization: %d%%", util)
        if util < 90 and not stop_event.is_set():
            if len(llm_workers) < MAX_LLM_WORKERS:
                # Modify this line to pass stop_event
                t = threading.Thread(target=llm_worker_proc, args=(config, IMPROVED_PROMPT, stop_event))
                t.start()
                llm_workers.append(t)
                logger.info("Spawned additional llm_worker. Total llm_workers: %d", len(llm_workers))
            else:
                logger.info("Maximum LLM workers reached.")
            time.sleep(5)
        else:
            logger.info("GPU utilization is above 90%. Stopping worker scaling.")
            break

# New function to calculate averages
def log_average_processing_time():
    with PROCESSING_LOCK:
        if PROCESSING_TIMES:
            avg_time = sum(PROCESSING_TIMES) / len(PROCESSING_TIMES)
            logger.info("Average processing time: %.2f seconds (%d files processed)",
                        avg_time, len(PROCESSED_QUEUE))
        else:
            logger.info("No files processed")

# --- Modified main() to launch multi-threaded pipeline ---
IMPROVED_PROMPT = """
Please analyze the provided image and follow these steps:
1. Look at the image.
2. List a minimum of 15 distinct tags that capture specific attributes of the image.
3. Return the tags in a single line separated by a comma and a space.
4. Do not include any additional text or explanations such as "Here are 15 tags that capture specific attributes of this image:"
"""

def main(stop_event):
    # Delete the unable_to_do.txt to start fresh if it exists
    unable_to_do_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unable_to_do.txt")
    if os.path.exists(unable_to_do_path):
        os.remove(unable_to_do_path)
    
    # Load and validate configuration - this will get the latest config
    config = load_config(CONFIG_FILE)
    if not validate_config(config):
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)
    
    # Initialize NVML and get GPU handle
    nvmlInit()
    gpu_handle = nvmlDeviceGetHandleByIndex(0)
    
    # Step 1: Scan directory from config watch folder and add file paths to FILE_QUEUE
    watch_dir = config["watch"]["folder"]
    logger.info("Scanning directory %s...", watch_dir)
    
    # Handle multiple watch folders separated by commas
    watch_folders = [folder.strip() for folder in watch_dir.split(",")]
    
    for folder in watch_folders:
        logger.info("Scanning folder: %s", folder)
        for root, _, files in os.walk(folder):
            for file in files:
                if stop_event.is_set():
                    break
                FILE_QUEUE.put(os.path.join(root, file))
            if stop_event.is_set():
                break
        if stop_event.is_set():
            break
    
    # Start a pool of file_worker threads (e.g., 4 workers)
    file_workers = []
    for _ in range(4):
        t = threading.Thread(target=file_worker, args=(stop_event,))
        t.start()
        file_workers.append(t)
    
    # Create worker list and control structures
    llm_workers = []
    
    # Start monitor thread first to manage LLM workers
    monitor_thread = threading.Thread(
        target=monitor_llm_and_scale,
        args=(config, IMPROVED_PROMPT, llm_workers, gpu_handle, stop_event)
    )
    monitor_thread.start()
    
    # Start DB worker thread - now passing stop_event
    db_thread = threading.Thread(target=db_worker_proc, args=(stop_event,))
    db_thread.start()
    
    # --- Pipeline Execution ---
    # Wait for file workers to finish (either due to queue completion or stop_event)
    logger.info("Waiting for file workers to complete...")
    for t in file_workers:
        t.join()
    logger.info("File workers have finished.")
    
    # Stop monitoring thread
    logger.info("Stopping worker monitoring...")
    stop_event.set()  # Ensure it's set in case it wasn't triggered externally
    monitor_thread.join()
    
    # Send termination signals to LLM workers
    logger.info("Stopping LLM workers...")
    for _ in llm_workers:
        PROCESSED_QUEUE.put(None)
    
    # Wait for LLM processing to complete
    logger.info("Joining LLM workers...")
    for t in llm_workers:
        t.join()
    
    # Signal DB worker to exit after all processing
    logger.info("Stopping database worker...")
    db_write_queue.put(None)
    db_thread.join()
    
    # Cleanup and exit
    logger.info("All tasks completed. Exiting.")


if __name__ == "__main__":
    # For standalone execution, create a stop_event and set up signal handlers
    import threading
    import signal
    
    stop_event = threading.Event()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
        stop_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main(stop_event)