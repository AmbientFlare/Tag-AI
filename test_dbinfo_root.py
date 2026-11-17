import unittest
import sqlite3
import tempfile
import os
import importlib.util
from pathlib import Path


def load_dbinfo():
    # Dynamically load the dbinfo module
    root = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "dbinfo", str(root / "src" / "tag-ai" / "dbinfo.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class TestDbInfo(unittest.TestCase):
    def setUp(self):
        self.dbinfo = load_dbinfo()
        # create temp DB file
        self.tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmpfile.name
        self.tmpfile.close()
        # load schema from root schema.sql
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        schema_file = Path(__file__).parent / "schema.sql"
        with open(schema_file, "r") as f:
            cur.executescript(f.read())
        conn.commit()
        conn.close()

    def tearDown(self):
        os.remove(self.db_path)

    def test_get_database_schema(self):
        schema = self.dbinfo.get_database_schema(self.db_path)
        # Expect core tables
        for tbl in ["photos", "tags", "photo_tags"]:
            self.assertIn(tbl, schema)
        # Test columns exist
        cols = [col["name"] for col in schema["photos"] if "name" in col]
        self.assertIn("photo_id", cols)
        self.assertIn("file_path", cols)

    def test_print_schema_output(self):
        schema = self.dbinfo.get_database_schema(self.db_path)
        from io import StringIO
        import sys
        buf = StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            self.dbinfo.print_schema(schema)
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertIn("Table: photos", out)
        self.assertIn("Columns:", out)

if __name__ == '__main__':
    unittest.main()
