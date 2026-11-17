import unittest
import os
import importlib.util
from pathlib import Path


def load_paths():
    # Dynamically load the paths module from the src/tag-ai folder
    root = Path(__file__).parent
    src_dir = root / "src" / "tag-ai"
    spec = importlib.util.spec_from_file_location("paths", str(src_dir / "paths.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.paths = load_paths()

    def test_get_app_dir(self):
        app_dir = self.paths.get_app_dir()
        self.assertTrue(app_dir.is_dir(), "App directory should exist")
        self.assertTrue((app_dir / "paths.py").exists(), "paths.py should be in the app directory")

    def test_get_user_data_dir(self):
        user_data = self.paths.get_user_data_dir()
        self.assertTrue(user_data.is_dir(), "User data directory should exist")
        self.assertIn(self.paths.APP_NAME, str(user_data), "User data dir should include APP_NAME")

    def test_get_config_dir(self):
        config_dir = self.paths.get_config_dir()
        self.assertTrue(config_dir.is_dir(), "Config directory should exist")
        self.assertIn(self.paths.APP_NAME, str(config_dir), "Config dir should include APP_NAME")

    def test_get_temp_dir(self):
        temp_dir = self.paths.get_temp_dir()
        self.assertTrue(temp_dir.is_dir(), "Temp directory should exist")
        self.assertIn(self.paths.APP_NAME, str(temp_dir), "Temp dir should include APP_NAME")

    def test_default_db_path(self):
        db_path = self.paths.get_default_db_path()
        self.assertTrue(db_path.parent.is_dir(), "DB path parent directory should exist")
        self.assertEqual(db_path.name, "photos.db", "DB filename should be photos.db")

    def test_default_config_path(self):
        config_path = self.paths.get_default_config_path()
        self.assertTrue(config_path.parent.is_dir(), "Config path parent directory should exist")
        self.assertEqual(config_path.name, "config.ini", "Config filename should be config.ini")


if __name__ == "__main__":
    unittest.main()
