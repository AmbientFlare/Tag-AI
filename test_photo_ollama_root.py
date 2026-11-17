import unittest
import tempfile
import os
import hashlib
import importlib.util
from pathlib import Path


def load_photo_module():
    root = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "photo_ollama",
        str(root / "src" / "tag-ai" / "photo_ollama.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class TestPhotoOllamaCommon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_photo_module()

    def test_calculate_file_hash(self):
        # Create a temp file with known content
        content = b"hello world"
        fd, path = tempfile.mkstemp()
        os.close(fd)
        with open(path, 'wb') as f:
            f.write(content)
        expected = hashlib.sha256(content).hexdigest()
        actual = self.module.calculate_file_hash(path)
        os.remove(path)
        self.assertEqual(actual, expected)

    def test_is_photo_and_raw(self):
        self.assertTrue(self.module.is_photo_file("image.jpg"))
        self.assertFalse(self.module.is_raw_file("image.jpg"))
        self.assertTrue(self.module.is_raw_file("image.NEF"))
        self.assertFalse(self.module.is_photo_file("image.NEF"))

    def test_constants(self):
        self.assertIsInstance(self.module.PHOTO_EXTENSIONS, set)
        self.assertIn('.jpg', {ext.lower() for ext in self.module.PHOTO_EXTENSIONS})
        self.assertIsInstance(self.module.RAW_EXTENSIONS, set)
        self.assertGreater(self.module.MAX_LLM_WORKERS, 0)

if __name__ == '__main__':
    unittest.main()
