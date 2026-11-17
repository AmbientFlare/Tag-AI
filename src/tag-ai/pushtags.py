import os
import configparser
import hashlib
import sqlite3
import logging
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Follow the import pattern specified in your guidelines
try:
    from paths import setup_logging, get_default_config_path, get_default_db_path, get_app_dir
except ImportError:
    from .paths import setup_logging, get_default_config_path, get_default_db_path, get_app_dir

# Set up logging as per your standards
try:
    setup_logging("pushtags", logging.INFO)
except ImportError:
    setup_logging("pushtags", logging.INFO)
logger = logging.getLogger(__name__)

# More robust way to determine ExifTool path that works in both development and Briefcase
def get_exiftool_path():
    """Find a system-installed ExifTool executable on PATH."""
    return shutil.which("exiftool") or shutil.which("exiftool.exe") or "exiftool"

EXIFTOOL_PATH = get_exiftool_path()

SUPPORTED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif",
    ".heif", ".heic", ".jp2",
    ".dng", ".nef", ".cr2", ".cr3", ".arw", ".raf", ".rw2",
    ".orf", ".srw", ".pef", ".mos"
)

def calculate_sha256(file_path):
    """Calculate SHA-256 hash of a file's contents."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
    except Exception as e:
        logger.error(f"Error calculating hash for {file_path}: {e}")
        return None
    return sha256_hash.hexdigest()

def get_tags_from_db(db_path, file_hash):
    """
    Look up the file hash in the database and return associated tags.
    Uses the 'photo_tags' junction table to find related tags.
    """
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        query = """
            SELECT tags.tag 
            FROM tags
            JOIN photo_tags ON tags.id = photo_tags.tag_id
            JOIN photos ON photos.photo_id = photo_tags.photo_id
            WHERE photos.file_hash = ?;
        """
        cur.execute(query, (file_hash,))
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Database query failed for hash {file_hash}: {e}")
        return set()

    if rows:
        return {row[0] for row in rows}
    return set()

def get_existing_tags(file_path):
    """Extract existing tags from the image file using ExifTool."""
    try:
        # Create appropriate startup info to hide console window on Windows
        startupinfo = None
        if os.name == 'nt':  # Windows
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        # Use direct subprocess call to ExifTool with hidden window
        normalized_path = os.path.normpath(file_path)  # Normalize path for Windows
        cmd = [EXIFTOOL_PATH, "-j", "-XMP:Subject", normalized_path]
        result = subprocess.run(cmd, 
                               capture_output=True, 
                               text=True, 
                               check=True, 
                               startupinfo=startupinfo)
        
        # Parse JSON output
        import json
        metadata = json.loads(result.stdout)
        if metadata and "XMP:Subject" in metadata[0]:
            if isinstance(metadata[0]["XMP:Subject"], list):
                return set(metadata[0]["XMP:Subject"])
            else:
                # Handle case where it returns a string instead of a list
                return set([metadata[0]["XMP:Subject"]])
    except subprocess.CalledProcessError as e:
        logger.error(f"ExifTool command failed for {file_path}: {e}")
        logger.debug(f"ExifTool error output: {e.stderr}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ExifTool output for {file_path}: {e}")
    except Exception as e:
        logger.error(f"Failed to read tags from {file_path}: {e}")
    
    return set()

def write_tags_to_image(file_path, tags):
    """
    Use subprocess to call exiftool directly to write tags to the file.
    Only writes tags that are not already present.
    """
    existing_tags = get_existing_tags(file_path)
    updated_tags = existing_tags.union(tags)
    if updated_tags == existing_tags:
        logger.info(f"No new tags to add for {file_path}")
        return

    tag_string = ",".join(updated_tags)
    
    try:
        # Create appropriate startup info to hide console window on Windows
        startupinfo = None
        if os.name == 'nt':  # Windows
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
        
        # Direct subprocess call to exiftool with hidden window
        normalized_path = os.path.normpath(file_path)  # Normalize path for Windows
        cmd = [EXIFTOOL_PATH, "-overwrite_original", f"-XMP:Subject={tag_string}", normalized_path]
        process = subprocess.run(cmd, 
                               check=True, 
                               capture_output=True, 
                               text=True, 
                               startupinfo=startupinfo)
        logger.info(f"Updated tags for {file_path}: {updated_tags}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to write tags to {file_path}: {e}")
        logger.debug(f"ExifTool error output: {e.stderr}")
    except Exception as e:
        logger.error(f"Unexpected error writing tags to {file_path}: {e}")

def process_file(file_path, db_path):
    """Process a single file by calculating its hash, retrieving tags, and writing them."""
    try:
        logger.info(f"Processing file: {file_path}")
        file_hash = calculate_sha256(file_path)
        if not file_hash:
            logger.warning(f"Could not calculate hash for {file_path}, skipping")
            return
        
        tags_from_db = get_tags_from_db(db_path, file_hash)
        if tags_from_db:
            logger.info(f"Found {len(tags_from_db)} tags in database for {file_path}")
            write_tags_to_image(file_path, tags_from_db)
        else:
            logger.info(f"No tags found in database for {file_path}")
    except Exception as e:
        logger.error(f"Unhandled exception processing {file_path}: {e}")

def main():
    """Main entry point for the tag pushing functionality."""
    logger.info("Starting tag push operation")
    
    try:
        # Setup global signals if available to report progress to GUI
        try:
            from global_signals import global_signals
            has_signals = True
        except ImportError:
            try:
                from .global_signals import global_signals
                has_signals = True
            except ImportError:
                has_signals = False
        
        # Load configuration
        config = configparser.ConfigParser()
        config.read(get_default_config_path())
        
        # Get watch folders (support comma-separated list)
        watch_folder_str = config.get("watch", "folder")
        watch_folders = [folder.strip() for folder in watch_folder_str.split(",")]
        
        # Get database path
        db_path = get_default_db_path()
        
        # Count total files to process for progress reporting
        total_files = 0
        files_by_folder = {}
        
        for watch_folder in watch_folders:
            if not os.path.exists(watch_folder):
                logger.warning(f"Watch folder does not exist: {watch_folder}")
                continue
                
            # Get list of files with supported extensions
            folder_files = []
            for filename in os.listdir(watch_folder):
                if any(filename.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS):
                    file_path = os.path.join(watch_folder, filename)
                    if os.path.isfile(file_path):
                        folder_files.append(file_path)
            
            files_by_folder[watch_folder] = folder_files
            total_files += len(folder_files)
        
        if total_files == 0:
            logger.info("No files found to process")
            if has_signals:
                global_signals.log_message.emit("No files found to process in watch folders")
            return 0
        
        # Report total files to be processed
        logger.info(f"Found {total_files} total files to process")
        if has_signals:
            global_signals.log_message.emit(f"Found {total_files} files to process across {len(watch_folders)} folders")
        
        # Process counter for progress reporting
        processed_count = 0
        last_percent = -1
        
        # Wrap process_file to track progress
        def process_file_with_progress(file_path):
            nonlocal processed_count, last_percent
            result = process_file(file_path, db_path)
            
            # Update progress counter
            processed_count += 1
            percent = int((processed_count / total_files) * 100)
            
            # Report progress only when percentage changes to reduce GUI updates
            if percent != last_percent:
                logger.info(f"Progress: {percent}% ({processed_count}/{total_files})")
                if has_signals:
                    global_signals.log_message.emit(f"Push Tags Progress: {percent}% ({processed_count}/{total_files})")
                last_percent = percent
            
            return result
        
        # Process each folder
        for watch_folder, files_to_process in files_by_folder.items():
            if not files_to_process:
                continue
                
            logger.info(f"Processing folder: {watch_folder} ({len(files_to_process)} files)")
            if has_signals:
                global_signals.log_message.emit(f"Processing folder: {os.path.basename(watch_folder)} ({len(files_to_process)} files)")
            
            # Process files in parallel with progress tracking
            with ThreadPoolExecutor() as executor:
                executor.map(process_file_with_progress, files_to_process)
        
        # Final completion message
        logger.info(f"Tag push operation completed. Processed {processed_count} files.")
        if has_signals:
            global_signals.log_message.emit(f"✅ Tag push operation completed. Processed {processed_count} files.")
        
        return 0
    except Exception as e:
        logger.error(f"Tag push operation failed: {e}")
        if 'has_signals' in locals() and has_signals:
            global_signals.log_message.emit(f"❌ Tag push operation failed: {e}")
        return 1

if __name__ == "__main__":
    main()