import sqlite3
import logging
import sys

# Use try/except pattern for imports
try:
    from paths import get_default_db_path, setup_logging
except ImportError:
    try:
        from .paths import get_default_db_path, setup_logging
    except ImportError:
        # Fallback logging setup
        import logging
        logging.basicConfig(
            level=logging.INFO, 
            format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
        )
        
        def get_default_db_path():
            """Fallback implementation if paths module is unavailable"""
            import os
            return os.path.join(os.path.expanduser("~"), "photos.db")
        
        def setup_logging(name, level=logging.INFO):
            """Fallback logging setup"""
            logging.getLogger(name).setLevel(level)

# Set up module-specific logging
setup_logging("cleardb", logging.INFO)
logger = logging.getLogger(__name__)

def clear_db(database_path=None):
    """
    Clear the contents of the SQLite database.
    
    Args:
        database_path (str, optional): Path to the database file. 
                                       If None, uses the default path.
    
    Returns:
        bool: True if clearing was successful, False otherwise.
    """
    if database_path is None:
        database_path = get_default_db_path()
    
    logger.info(f"Starting database clearing process for: {database_path}")
    
    # Validate database path
    import os
    if not os.path.exists(database_path):
        logger.error(f"Database file not found: {database_path}")
        return False
    
    # Check write permissions
    if not os.access(database_path, os.W_OK):
        logger.error(f"No write permission for database file: {database_path}")
        return False
    
    try:
        # Open connection with foreign key and journal mode settings
        conn = sqlite3.connect(database_path)
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("PRAGMA journal_mode = DELETE;")
        cursor = conn.cursor()
        
        # Retrieve all tables in the database
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if not row[0].startswith('sqlite_')]
        
        logger.info(f"Found {len(tables)} tables to clear")
        
        # Close any existing connections and take an exclusive lock
        conn.execute("BEGIN EXCLUSIVE TRANSACTION;")
        
        for table in tables:
            try:
                # Safely delete rows from each table
                cursor.execute(f"DELETE FROM {table};")
                logger.info(f"Cleared all rows from table: {table}")
            except sqlite3.Error as table_error:
                logger.warning(f"Error clearing table {table}: {table_error}")
        
        # Commit the clearing transaction
        conn.commit()
        
        # Try to vacuum the database to reclaim storage and reset file
        try:
            conn.execute("VACUUM;")
            logger.info("Database vacuumed to reclaim storage")
        except sqlite3.Error as vacuum_error:
            logger.warning(f"Could not VACUUM database: {vacuum_error}")
        
        # Re-enable foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")
        
        logger.info("Database cleared successfully.")
        return True
    
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error during clearing: {e}")
        return False
    
    except sqlite3.Error as e:
        logger.error(f"SQLite error during database clearing: {e}")
        return False
    
    except Exception as e:
        logger.error(f"Unexpected error during database clearing: {e}")
        return False
    
    finally:
        # Always close the connection if it was opened
        if 'conn' in locals():
            try:
                conn.close()
                logger.debug("Database connection closed")
            except Exception as close_error:
                logger.warning(f"Error closing database connection: {close_error}")

def main():
    """
    Command-line entry point for database clearing.
    
    Provides a simple CLI interface to clear the database.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Clear contents of the Tag-AI SQLite database.")
    parser.add_argument(
        "-p", "--path", 
        help="Optional path to the database file. Uses default if not specified."
    )
    parser.add_argument(
        "-y", "--yes", 
        action="store_true", 
        help="Skip confirmation and clear database immediately"
    )
    
    args = parser.parse_args()
    
    # If no confirmation flag is set, ask user
    if not args.yes:
        confirm = input(
            "WARNING: This will delete ALL data in the database. "
            "Are you sure? (y/N): "
        ).lower().strip()
        
        if confirm != 'y':
            logger.info("Database clearing cancelled.")
            return 1
    
    # Perform database clearing
    success = clear_db(args.path)
    
    return 0 if success else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)