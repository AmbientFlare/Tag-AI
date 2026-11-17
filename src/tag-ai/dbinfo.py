import sqlite3
from typing import List, Dict
import sys
import os

def get_database_schema(db_path: str) -> Dict[str, List[Dict]]:
    """
    Extract complete schema information from a SQLite database.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        Dictionary containing tables and their column information
    """
    schema = {}
    
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """)
        tables = cursor.fetchall()
        
        # For each table, get detailed column information
        for table in tables:
            table_name = table[0]
            
            # Get column info
            cursor.execute(f"PRAGMA table_info('{table_name}')")
            columns = cursor.fetchall()
            
            # Store column details
            schema[table_name] = [
                {
                    'name': col[1],
                    'type': col[2],
                    'nullable': not col[3],
                    'default': col[4],
                    'primary_key': bool(col[5])
                }
                for col in columns
            ]
            
            # Get index information
            cursor.execute(f"PRAGMA index_list('{table_name}')")
            indexes = cursor.fetchall()
            
            # Add index information to schema
            if indexes:
                schema[table_name].append({
                    'indexes': [
                        {
                            'name': idx[1],
                            'unique': bool(idx[2])
                        }
                        for idx in indexes
                    ]
                })
            
            # Get foreign key information
            cursor.execute(f"PRAGMA foreign_key_list('{table_name}')")
            foreign_keys = cursor.fetchall()
            
            # Add foreign key information to schema
            if foreign_keys:
                schema[table_name].append({
                    'foreign_keys': [
                        {
                            'table': fk[2],
                            'from': fk[3],
                            'to': fk[4],
                            'on_update': fk[5],
                            'on_delete': fk[6]
                        }
                        for fk in foreign_keys
                    ]
                })
    
    except sqlite3.Error as e:
        print(f"Error accessing database: {e}")
        return {}
    
    finally:
        if 'conn' in locals():
            conn.close()
    
    return schema

def print_schema(schema: Dict[str, List[Dict]]) -> None:
    """
    Print the schema information in a readable format.
    """
    for table_name, table_info in schema.items():
        print(f"\nTable: {table_name}")
        print("-" * (len(table_name) + 7))
        
        # Print column information
        print("\nColumns:")
        for col in table_info:
            if all(key in col for key in ['name', 'type', 'nullable']):
                nullable = "NULL" if col['nullable'] else "NOT NULL"
                pk = "PRIMARY KEY" if col['primary_key'] else ""
                default = f"DEFAULT {col['default']}" if col['default'] is not None else ""
                print(f"  {col['name']} {col['type']} {nullable} {pk} {default}".strip())
        
        # Print index information
        for item in table_info:
            if 'indexes' in item:
                print("\nIndexes:")
                for idx in item['indexes']:
                    unique = "UNIQUE" if idx['unique'] else ""
                    print(f"  {idx['name']} {unique}".strip())
        
        # Print foreign key information
        for item in table_info:
            if 'foreign_keys' in item:
                print("\nForeign Keys:")
                for fk in item['foreign_keys']:
                    print(f"  {fk['from']} -> {fk['table']}({fk['to']})")
                    print(f"    ON UPDATE: {fk['on_update']}")
                    print(f"    ON DELETE: {fk['on_delete']}")

def main():
    # Check if database path is provided
    if len(sys.argv) != 2:
        print("Usage: python dbinfo.py <path_to_database>")
        sys.exit(1)
    
    # Get database path from command line argument
    db_path = sys.argv[1]
    
    # Check if file exists
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found")
        sys.exit(1)
    
    # Get and print schema
    schema = get_database_schema(db_path)
    if schema:
        print_schema(schema)
    else:
        print("No schema information found or error occurred")

if __name__ == "__main__":
    main()