import unittest
import os
import tempfile
import sys
import importlib.util
import configparser
from pathlib import Path

def load_photo_module():
    # Dynamically load the photo_ollama module
    root = Path(__file__).parent
    # Ensure src/tag-ai is on sys.path for 'paths' imports
    module_dir = str(root / "src" / "tag-ai")
    sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location(
        "photo_ollama", str(root / "src" / "tag-ai" / "photo_ollama.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.pop(0)
    return module

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.photo = load_photo_module()
        # Create a temporary config file with required sections
        fd, self.path = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        content = """
[watch]
folder = /tmp/photos
[image_processing]
target_max_size_mb = 2
[tagger_ollama]
ollama_endpoint = http://localhost:8080
model_name = llama
"""
        with open(self.path, 'w') as f:
            f.write(content)

    def tearDown(self):
        os.remove(self.path)

    def test_load_config(self):
        config = self.photo.load_config(self.path)
        self.assertIsInstance(config, configparser.ConfigParser)
        self.assertIn('watch', config)
        self.assertIn('image_processing', config)
        self.assertIn('tagger_ollama', config)

    def test_validate_config_success(self):
        config = self.photo.load_config(self.path)
        self.assertTrue(self.photo.validate_config(config))

    def test_validate_config_failure(self):
        parser = configparser.ConfigParser()
        parser['watch'] = {'folder': '/tmp'}
        # Missing other sections
        self.assertFalse(self.photo.validate_config(parser))

if __name__ == '__main__':
    unittest.main()
