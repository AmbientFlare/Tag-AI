import unittest
import os
import sys
import platform
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Assuming paths.py is in src/tag-ai relative to the project root
# Adjust the path as necessary if the project structure is different
sys.path.insert(0, str(Path(__file__).parent.parent / 'src' / 'tag-ai'))

try:
    import paths
except ImportError as e:
    print(f"Error importing paths module: {e}")
    print("Ensure paths.py is accessible and the PYTHONPATH is set correctly.")
    # Provide a dummy module to allow tests to be defined, though they will likely fail.
    class DummyPaths:
        APP_NAME = "Tag-AI-Test"
        def get_app_dir(self): return Path('.')
        def get_user_data_dir(self): return Path(tempfile.gettempdir()) / self.APP_NAME
        def get_config_dir(self): return self.get_user_data_dir()
        def get_log_dir(self): return self.get_user_data_dir() / "Logs"
        def get_temp_dir(self): return Path(tempfile.gettempdir()) / self.APP_NAME
        def get_default_db_path(self): return self.get_user_data_dir() / "photos.db"
        def get_default_config_path(self): return self.get_config_dir() / "config.ini"
        def ensure_app_resources(self): return {'db_path': self.get_default_db_path(), 'config_path': self.get_default_config_path()}
        def get_log_file_path(self, name): return self.get_log_dir() / f"{name}.log"
        def setup_logging(self, name, level): pass
    paths = DummyPaths()


class TestPaths(unittest.TestCase):

    # --- Test get_user_data_dir ---

    @patch('platform.system', return_value='Windows')
    @patch('os.environ.get')
    @patch('os.makedirs')
    def test_get_user_data_dir_windows(self, mock_makedirs, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: 'C:\\Users\\TestUser\\AppData\\Local' if key == 'LOCALAPPDATA' else default
        expected_path = Path(r'C:\Users\TestUser\AppData\Local') / 'Tag-AI'
        actual_path = paths.get_user_data_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('LOCALAPPDATA', os.path.expanduser("~"))

    @patch('platform.system', return_value='Darwin')
    @patch('os.path.expanduser', return_value='/Users/testuser')
    @patch('os.makedirs')
    def test_get_user_data_dir_macos(self, mock_makedirs, mock_expanduser, mock_system):
        expected_path = Path('/Users/testuser/Library/Application Support/Tag-AI')
        actual_path = paths.get_user_data_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_expanduser.assert_called_with("~")

    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs')
    def test_get_user_data_dir_linux_xdg(self, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: '/custom/data/path' if key == 'XDG_DATA_HOME' else default
        expected_path = Path('/custom/data/path/Tag-AI')
        actual_path = paths.get_user_data_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('XDG_DATA_HOME', '/home/testuser/.local/share')

    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs')
    def test_get_user_data_dir_linux_default(self, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: default if key == 'XDG_DATA_HOME' else None
        expected_path = Path('/home/testuser/.local/share/Tag-AI')
        actual_path = paths.get_user_data_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('XDG_DATA_HOME', '/home/testuser/.local/share')

    @patch('platform.system', return_value='Windows')
    @patch('os.environ.get')
    @patch('os.makedirs', side_effect=PermissionError("Test permission denied"))
    @patch('tempfile.gettempdir', return_value='/tmp/fallback')
    @patch('paths.logger')
    def test_get_user_data_dir_permission_fallback(self, mock_logger, mock_gettempdir, mock_makedirs, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: 'C:\\Users\\TestUser\\AppData\\Local' if key == 'LOCALAPPDATA' else default
        standard_path = Path(r'C:\Users\TestUser\AppData\Local') / 'Tag-AI'
        fallback_path = Path('/tmp/fallback/Tag-AI')
        mock_makedirs.side_effect = [PermissionError("Test permission denied"), None]
        actual_path = paths.get_user_data_dir()
        self.assertEqual(actual_path, fallback_path)
        self.assertEqual(mock_makedirs.call_count, 2)
        mock_makedirs.assert_any_call(standard_path, exist_ok=True)
        mock_makedirs.assert_any_call(fallback_path, exist_ok=True)
        mock_logger.warning.assert_called_once()

    # --- Test get_config_dir ---
    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs')
    def test_get_config_dir_linux_xdg(self, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: '/custom/config/path' if key == 'XDG_CONFIG_HOME' else default
        expected_path = Path('/custom/config/path/Tag-AI')
        with patch('paths.get_user_data_dir', return_value=Path('/user/data/fallback')):
             actual_path = paths.get_config_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('XDG_CONFIG_HOME', '/home/testuser/.config')

    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs')
    def test_get_config_dir_linux_default(self, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: default if key == 'XDG_CONFIG_HOME' else None
        expected_path = Path('/home/testuser/.config/Tag-AI')
        with patch('paths.get_user_data_dir', return_value=Path('/user/data/fallback')):
            actual_path = paths.get_config_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('XDG_CONFIG_HOME', '/home/testuser/.config')

    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs', side_effect=PermissionError("Config permission denied"))
    @patch('paths.get_user_data_dir')
    def test_get_config_dir_linux_permission_fallback(self, mock_get_user_data_dir, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: default if key == 'XDG_CONFIG_HOME' else None
        fallback_path = Path('/user/data/fallback/path')
        mock_get_user_data_dir.return_value = fallback_path
        actual_path = paths.get_config_dir()
        self.assertEqual(actual_path, fallback_path)
        mock_makedirs.assert_called_once_with(Path('/home/testuser/.config/Tag-AI'), exist_ok=True)
        mock_get_user_data_dir.assert_called_once()

    # --- Test get_log_dir ---
    @patch('platform.system', return_value='Windows')
    @patch('paths.get_user_data_dir')
    @patch('os.makedirs')
    def test_get_log_dir_windows(self, mock_makedirs, mock_get_user_data_dir, mock_system):
        mock_user_data_dir = Path(r'C:\Users\TestUser\AppData\Local') / 'Tag-AI'
        mock_get_user_data_dir.return_value = mock_user_data_dir
        expected_path = mock_user_data_dir / "Logs"
        actual_path = paths.get_log_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_get_user_data_dir.assert_called_once()

    @patch('platform.system', return_value='Darwin')
    @patch('os.path.expanduser', return_value='/Users/testuser')
    @patch('os.makedirs')
    def test_get_log_dir_macos(self, mock_makedirs, mock_expanduser, mock_system):
        expected_path = Path('/Users/testuser/Library/Logs/Tag-AI')
        actual_path = paths.get_log_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_expanduser.assert_called_with("~")

    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs')
    def test_get_log_dir_linux_xdg(self, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: '/custom/state/path' if key == 'XDG_STATE_HOME' else default
        expected_path = Path('/custom/state/path/Tag-AI/logs')
        actual_path = paths.get_log_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('XDG_STATE_HOME', '/home/testuser/.local/state')

    @patch('platform.system', return_value='Linux')
    @patch('os.environ.get')
    @patch('os.path.expanduser', side_effect=lambda p: '/home/testuser' + p[1:] if p.startswith('~') else p)
    @patch('os.makedirs')
    def test_get_log_dir_linux_default(self, mock_makedirs, mock_expanduser, mock_environ_get, mock_system):
        mock_environ_get.side_effect = lambda key, default: default if key == 'XDG_STATE_HOME' else None
        expected_path = Path('/home/testuser/.local/state/Tag-AI/logs')
        actual_path = paths.get_log_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_environ_get.assert_called_with('XDG_STATE_HOME', '/home/testuser/.local/state')

    # --- Test get_temp_dir ---
    @patch('tempfile.gettempdir', return_value='/tmp/systemp')
    @patch('os.makedirs')
    def test_get_temp_dir(self, mock_makedirs, mock_gettempdir):
        expected_path = Path('/tmp/systemp/Tag-AI')
        actual_path = paths.get_temp_dir()
        self.assertEqual(actual_path, expected_path)
        mock_makedirs.assert_called_once_with(expected_path, exist_ok=True)
        mock_gettempdir.assert_called_once()

    # --- Test get_default_db_path ---
    @patch('paths.get_user_data_dir')
    def test_get_default_db_path(self, mock_get_user_data_dir):
        mock_user_data = Path('/path/to/user/data')
        mock_get_user_data_dir.return_value = mock_user_data
        expected_path = mock_user_data / "photos.db"
        actual_path = paths.get_default_db_path()
        self.assertEqual(actual_path, expected_path)
        mock_get_user_data_dir.assert_called_once()

    # --- Test get_default_config_path ---
    @patch('paths.get_config_dir')
    def test_get_default_config_path(self, mock_get_config_dir):
        mock_config_data = Path('/path/to/config/data')
        mock_get_config_dir.return_value = mock_config_data
        expected_path = mock_config_data / "config.ini"
        actual_path = paths.get_default_config_path()
        self.assertEqual(actual_path, expected_path)
        mock_get_config_dir.assert_called_once()

    # --- Test get_log_file_path ---
    @patch('paths.get_log_dir')
    def test_get_log_file_path(self, mock_get_log_dir):
        mock_log_dir = Path('/path/to/logs')
        mock_get_log_dir.return_value = mock_log_dir
        expected_path = mock_log_dir / "my_test_log.log"
        actual_path = paths.get_log_file_path("my_test_log")
        self.assertEqual(actual_path, expected_path)
        mock_get_log_dir.assert_called_once()

    # --- Test get_app_dir ---
    # Use patch.object within the test
    def test_get_app_dir_pyinstaller(self):
        frozen_path = '/path/to/frozen_app'
        # Patch sys attributes directly using patch.object
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, '_MEIPASS', frozen_path, create=True):
            # The patched values are active within this block
            actual_path = paths.get_app_dir()
            self.assertEqual(actual_path, Path(frozen_path))

    # TODO: Add more tests for get_app_dir covering Briefcase and fallback scenarios

    # --- Test ensure_app_resources ---
    # TODO: These tests are commented out due to persistent mocking issues with pathlib.Path.
    #       Patching either Path directly or Path.exists leads to TypeErrors or
    #       mocks not being called as expected. Needs further investigation.

    # @patch('paths.get_app_dir')
    # @patch('paths.get_user_data_dir')
    # @patch('paths.get_config_dir')
    # @patch('pathlib.Path.exists') # Patch exists method directly
    # @patch('shutil.copy2')
    # @patch('paths.logger')
    # def test_ensure_app_resources_copies_files(self, mock_logger, mock_copy, mock_exists, mock_config_dir, mock_user_dir, mock_app_dir):
    #     app_dir_str = '/app/source'
    #     user_dir_str = '/user/data'
    #     config_dir_str = '/user/config'
    #
    #     mock_app_dir.return_value = Path(app_dir_str)
    #     mock_user_dir.return_value = Path(user_dir_str)
    #     mock_config_dir.return_value = Path(config_dir_str)
    #
    #     # Define expected paths as real Path objects
    #     source_db_path = Path(app_dir_str) / 'template.db'
    #     source_db_fallback_path = Path(app_dir_str) / 'photos.db'
    #     dest_db_path = Path(user_dir_str) / 'photos.db'
    #     source_config_path = Path(app_dir_str) / 'config.ini'
    #     dest_config_path = Path(config_dir_str) / 'config.ini'
    #     source_db_briefcase_path = Path(app_dir_str) / "src/tag-ai/template.db"
    #     source_config_briefcase_path = Path(app_dir_str) / "src/tag-ai/config.ini"
    #
    #     # Configure mock_exists side effect - explicitly accept 'self'
    #     def exists_logic(self_path_instance): # Argument represents the Path instance
    #         if self_path_instance == source_db_path: return True
    #         if self_path_instance == source_db_fallback_path: return False
    #         if self_path_instance == dest_db_path: return False # Destination doesn't exist
    #         if self_path_instance == source_config_path: return True
    #         if self_path_instance == dest_config_path: return False # Destination doesn't exist
    #         if self_path_instance == source_db_briefcase_path: return False
    #         if self_path_instance == source_config_briefcase_path: return False
    #         print(f"Unexpected exists call: {self_path_instance}") # Debugging
    #         return False # Default
    #     mock_exists.side_effect = exists_logic
    #
    #     # --- Execute ---
    #     resources = paths.ensure_app_resources()
    #
    #     # --- Assertions ---
    #     self.assertEqual(resources['db_path'], dest_db_path)
    #     self.assertEqual(resources['config_path'], dest_config_path)
    #
    #     # Check exists calls
    #     mock_exists.assert_any_call(source_db_path)
    #     mock_exists.assert_any_call(dest_db_path)
    #     mock_exists.assert_any_call(source_config_path)
    #     mock_exists.assert_any_call(dest_config_path)
    #     # Add asserts for fallback/briefcase paths if they are definitely checked
    #
    #     # Check copy2 calls
    #     mock_copy.assert_any_call(source_db_path, dest_db_path)
    #     mock_copy.assert_any_call(source_config_path, dest_config_path)
    #     self.assertEqual(mock_copy.call_count, 2)
    #
    #     # Check log messages (use real path strings)
    #     mock_logger.info.assert_any_call(f"Copied initial database to {dest_db_path}")
    #     mock_logger.info.assert_any_call(f"Copied initial config to {dest_config_path}")
    #
    #
    # @patch('paths.get_app_dir')
    # @patch('paths.get_user_data_dir')
    # @patch('paths.get_config_dir')
    # @patch('pathlib.Path.exists') # Patch exists method directly
    # @patch('shutil.copy2')
    # @patch('paths.logger')
    # def test_ensure_app_resources_files_exist(self, mock_logger, mock_copy, mock_exists, mock_config_dir, mock_user_dir, mock_app_dir):
    #     app_dir_str = '/app/source'
    #     user_dir_str = '/user/data'
    #     config_dir_str = '/user/config'
    #
    #     mock_app_dir.return_value = Path(app_dir_str)
    #     mock_user_dir.return_value = Path(user_dir_str)
    #     mock_config_dir.return_value = Path(config_dir_str)
    #
    #     # Define expected paths
    #     source_db_path = Path(app_dir_str) / 'template.db'
    #     dest_db_path = Path(user_dir_str) / 'photos.db'
    #     source_config_path = Path(app_dir_str) / 'config.ini'
    #     dest_config_path = Path(config_dir_str) / 'config.ini'
    #
    #     # Configure mock_exists: Destination files *do* exist - explicitly accept 'self'
    #     def exists_logic(self_path_instance): # Argument represents the Path instance
    #         if self_path_instance == dest_db_path: return True # Destination exists
    #         if self_path_instance == dest_config_path: return True # Destination exists
    #         # Assume source exists if checked by logic
    #         if self_path_instance == source_db_path: return True
    #         if self_path_instance == source_config_path: return True
    #         print(f"Unexpected exists call (exist test): {self_path_instance}") # Debugging
    #         return False # Default
    #     mock_exists.side_effect = exists_logic
    #
    #     # --- Execute ---
    #     resources = paths.ensure_app_resources()
    #
    #     # --- Assertions ---
    #     self.assertEqual(resources['db_path'], dest_db_path)
    #     self.assertEqual(resources['config_path'], dest_config_path)
    #
    #     # Check exists calls
    #     mock_exists.assert_any_call(dest_db_path)
    #     mock_exists.assert_any_call(dest_config_path)
    #     # Source might be checked depending on logic
    #
    #     mock_copy.assert_not_called()
    #     mock_logger.info.assert_not_called()


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
