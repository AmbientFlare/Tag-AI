import unittest
import sys
import tempfile
import os
import configparser
import importlib.util
from pathlib import Path


def load_gui_module():
    root = Path(__file__).parent
    module_dir = root / "src" / "tag-ai"
    sys.path.insert(0, str(module_dir))
    # Ensure a QApplication exists for Qt image handling
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            QApplication([])
    except ImportError:
        pass
    spec = importlib.util.spec_from_file_location(
        "gui_v02", str(module_dir / "gui_v02.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.pop(0)
    return module


class TestGUIV02(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = load_gui_module()

    def test_load_config_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.gui.load_config("nonexistent.ini", "section")

    def test_load_config_missing_section(self):
        fd, path = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        with open(path, "w") as f:
            f.write("[other]\nkey=value\n")
        with self.assertRaises(KeyError):
            self.gui.load_config(path, "mysection")
        os.remove(path)

    def test_load_config_success(self):
        fd, path = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        with open(path, "w") as f:
            f.write("[test]\nfoo=bar\n")
        section = self.gui.load_config(path, "test")
        self.assertIsInstance(section, configparser.SectionProxy)
        self.assertEqual(section.get("foo"), "bar")
        os.remove(path)

    def test_load_image_jpeg(self):
        from PIL import Image
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        img.save(path)
        original = self.gui.QPixmap.fromImage
        self.gui.QPixmap.fromImage = lambda img: "pixmap"
        pixmap = self.gui.load_image(path)
        self.assertEqual(pixmap, "pixmap")
        self.gui.QPixmap.fromImage = original
        os.remove(path)

    def test_load_image_invalid(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        with open(path, "wb") as f:
            f.write(b"notanimage")
        result = self.gui.load_image(path)
        self.assertIsNone(result)
        os.remove(path)

    def test_load_full_image_jpeg(self):
        from PIL import Image
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img = Image.new("RGB", (100, 100), color=(0, 255, 0))
        img.save(path)
        original = self.gui.QPixmap.fromImage
        self.gui.QPixmap.fromImage = lambda img: "fullpix"
        pixmap = self.gui.load_full_image(path)
        self.assertEqual(pixmap, "fullpix")
        self.gui.QPixmap.fromImage = original
        os.remove(path)

    def test_load_full_image_invalid(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        result = self.gui.load_full_image(path)
        self.assertIsNone(result)
        os.remove(path)

    def test_load_full_image_fallback_success(self):
        from PIL import Image
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img = Image.new("RGB", (50, 50), color=(128, 128, 0))
        img.save(path)
        original = self.gui.QPixmap.fromImage
        self.gui.QPixmap.fromImage = lambda img: "fallbackpix"
        pixmap, temp = self.gui.load_full_image_fallback(path)
        self.assertEqual(pixmap, "fallbackpix")
        self.assertIsNone(temp)
        self.gui.QPixmap.fromImage = original
        os.remove(path)

    def test_load_full_image_fallback_invalid(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        pixmap, temp = self.gui.load_full_image_fallback(path)
        self.assertIsNone(pixmap)
        self.assertIsNone(temp)
        os.remove(path)

    def test_load_full_image_fallback_imageio(self):
        from PIL import Image
        # Create a valid image file
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.new("RGB", (20, 20), color=(10, 20, 30)).save(path)
        # Force Pillow to fail
        orig_img_open = self.gui.Image.open
        self.gui.Image.open = lambda *args, **kwargs: (_ for _ in ()).throw(Exception("force pillow fail"))
        # Force rawpy to fail
        orig_rawpy = self.gui.rawpy
        class DummyRawpy:
            @staticmethod
            def imread(fp):
                raise Exception("force rawpy fail")
        self.gui.rawpy = DummyRawpy
        # Run fallback
        pixmap, temp = self.gui.load_full_image_fallback(path)
        # Verify imageio fallback used
        self.assertIsNotNone(pixmap)
        self.assertTrue(os.path.exists(temp))
        # Cleanup and restore
        self.gui.Image.open = orig_img_open
        self.gui.rawpy = orig_rawpy
        os.remove(path)
        os.remove(temp)

    def test_load_full_image_fallback_rawpy(self):
        # Simulate rawpy fallback
        from PIL import Image as PILImage
        # Create dummy file (extension .cr2 triggers rawpy path)
        fd, path = tempfile.mkstemp(suffix=".cr2")
        os.close(fd)
        # Create valid PNG content on disk
        tmp_png = path + ".png"
        PILImage.new("RGB", (30, 30), color=(50, 100, 150)).save(tmp_png)
        # Force Pillow to fail
        orig_img_open = self.gui.Image.open
        self.gui.Image.open = lambda *args, **kwargs: (_ for _ in ()).throw(Exception("force pillow fail"))
        # Stub rawpy.imread to return context manager with postprocess
        orig_rawpy_imread = self.gui.rawpy.imread
        class DummyRawContext:
            def postprocess(self):
                import numpy as np
                return np.zeros((10, 10, 3), dtype=np.uint8)
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False
        self.gui.rawpy.imread = staticmethod(lambda fp: DummyRawContext())
        # Stub QPixmap.fromImage
        original_fromImage = self.gui.QPixmap.fromImage
        self.gui.QPixmap.fromImage = lambda qimg: "rawpix"
        # Run fallback
        pixmap, temp = self.gui.load_full_image_fallback(path)
        self.assertEqual(pixmap, "rawpix")
        self.assertIsNone(temp)
        # Cleanup
        self.gui.Image.open = orig_img_open
        self.gui.rawpy.imread = orig_rawpy_imread
        self.gui.QPixmap.fromImage = original_fromImage
        os.remove(path)
        os.remove(tmp_png)

    def test_get_window_manager_fallback(self):
        """Ensure get_window_manager returns fallback DummyWindowManager with expected API."""
        gm = self.gui.get_window_manager()
        # Methods should exist
        self.assertTrue(hasattr(gm, 'register_window'))
        self.assertTrue(hasattr(gm, 'get_window'))
        self.assertTrue(hasattr(gm, 'remove_window'))
        # Behavior of fallback methods
        self.assertIsNone(gm.get_window('any'))
        self.assertFalse(gm.remove_window('any'))
        # register_window should not raise
        try:
            gm.register_window('test', object())
        except Exception as e:
            self.fail(f"register_window raised exception: {e}")

    def test_load_image_unsupported_extension(self):
        # Files with unsupported extensions should return None immediately
        fd, path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        with open(path, 'w') as f:
            f.write('not an image')
        result = self.gui.load_image(path)
        self.assertIsNone(result)
        os.remove(path)


if __name__ == '__main__':
    unittest.main()
