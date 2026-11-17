import unittest
import sys
import os
import platform # Keep for DummyDepends
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Add src/tag-ai to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src' / 'tag-ai'))

try:
    import depends
except ImportError as e:
    print(f"Error importing depends module: {e}")
    # Provide dummy functions if import fails
    class DummyDepends:
        def detect_gpu_type(self, log): return "Unknown"
        def is_cuda_installed(self, log): return False
        def download_and_install_cuda_12_4_windows(self, log): return False
        def check_and_install_cuda(self, log): pass
        def is_rocm_installed(self, log): return False
        def download_and_install_rocm(self, log): return False
        def check_and_install_gpu_support(self, log): pass
        def check_ollama_installed(self, log): return False
        def get_os_info(self): return platform.system(), platform.machine()
        def download_ollama_installer(self, os_name, arch, log): return None, None
        def install_ollama(self, os_name, path, log): return False
        def install_llava_model(self, log): return None
    depends = DummyDepends()

# Dummy log function for tests
def dummy_log(message, level="info"):
    # print(f"[{level.upper()}] {message}") # Uncomment for debugging test logs
    pass

class TestDependsGPU(unittest.TestCase):

    # --- Test detect_gpu_type ---

    # Use context managers for patching
    def test_detect_gpu_windows_nvidia(self):
        mock_result = MagicMock()
        mock_result.stdout = "Name\nNVIDIA GeForce RTX 4090\n"
        mock_result.returncode = 0
        # Patch os.name and subprocess.run within the 'depends' module context
        with patch('depends.os.name', 'nt'), \
             patch('depends.subprocess.run', return_value=mock_result) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "NVIDIA")
            mock_run.assert_called_once_with(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, check=True
            )

    def test_detect_gpu_windows_amd(self):
        mock_result = MagicMock()
        mock_result.stdout = "Name\nAMD Radeon RX 7900 XTX\n"
        mock_result.returncode = 0
        with patch('depends.os.name', 'nt'), \
             patch('depends.subprocess.run', return_value=mock_result) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "AMD")
            mock_run.assert_called_once_with(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, check=True
            )

    def test_detect_gpu_windows_unknown(self):
        mock_result = MagicMock()
        mock_result.stdout = "Name\nIntel(R) UHD Graphics 770\n"
        mock_result.returncode = 0
        with patch('depends.os.name', 'nt'), \
             patch('depends.subprocess.run', return_value=mock_result) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Unknown")
            mock_run.assert_called_once_with(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, check=True
            )

    def test_detect_gpu_windows_error(self):
        with patch('depends.os.name', 'nt'), \
             patch('depends.subprocess.run', side_effect=Exception("WMIC Error")) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Unknown")
            mock_run.assert_called_once_with(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, check=True
            )

    def test_detect_gpu_linux_nvidia_lspci(self):
        mock_lspci_result = MagicMock()
        mock_lspci_result.stdout = "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3080]\n"
        mock_lspci_result.returncode = 0
        mock_glxinfo_result = MagicMock() # Not expected to be called
        with patch('depends.sys.platform', 'linux'), \
             patch('depends.subprocess.run', side_effect=[mock_lspci_result, mock_glxinfo_result]) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "NVIDIA")
            mock_run.assert_called_once_with(["lspci"], capture_output=True, text=True)

    def test_detect_gpu_linux_amd_lspci(self):
        mock_lspci_result = MagicMock()
        mock_lspci_result.stdout = "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 21 [Radeon RX 6800 XT]\n"
        mock_lspci_result.returncode = 0
        with patch('depends.sys.platform', 'linux'), \
             patch('depends.subprocess.run', return_value=mock_lspci_result) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "AMD")
            mock_run.assert_called_once_with(["lspci"], capture_output=True, text=True)

    def test_detect_gpu_linux_nvidia_glxinfo(self):
        mock_lspci_result = MagicMock()
        mock_lspci_result.stdout = "Some other PCI devices\n"
        mock_lspci_result.returncode = 0
        mock_glxinfo_result = MagicMock()
        mock_glxinfo_result.stdout = "OpenGL vendor string: NVIDIA Corporation\n"
        mock_glxinfo_result.returncode = 0
        with patch('depends.sys.platform', 'linux'), \
             patch('depends.subprocess.run', side_effect=[mock_lspci_result, mock_glxinfo_result]) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "NVIDIA")
            self.assertEqual(mock_run.call_count, 2)
            mock_run.assert_has_calls([
                call(["lspci"], capture_output=True, text=True),
                call(["glxinfo"], capture_output=True, text=True)
            ])

    def test_detect_gpu_linux_unknown(self):
        mock_lspci_result = MagicMock()
        mock_lspci_result.stdout = "Some other PCI devices\n"
        mock_lspci_result.returncode = 0
        mock_glxinfo_result = MagicMock()
        mock_glxinfo_result.stdout = "OpenGL vendor string: Intel\n"
        mock_glxinfo_result.returncode = 0
        with patch('depends.sys.platform', 'linux'), \
             patch('depends.subprocess.run', side_effect=[mock_lspci_result, mock_glxinfo_result]) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Unknown")
            self.assertEqual(mock_run.call_count, 2)
            mock_run.assert_has_calls([
                call(["lspci"], capture_output=True, text=True),
                call(["glxinfo"], capture_output=True, text=True)
            ])

    def test_detect_gpu_linux_error(self):
        with patch('depends.sys.platform', 'linux'), \
             patch('depends.subprocess.run', side_effect=Exception("Command Error")) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Unknown")
            mock_run.assert_any_call(["lspci"], capture_output=True, text=True)

    def test_detect_gpu_macos_amd(self):
        mock_result = MagicMock()
        mock_result.stdout = "Chipset Model: AMD Radeon Pro 5700 XT\n"
        mock_result.returncode = 0
        with patch('depends.sys.platform', 'darwin'), \
             patch('depends.subprocess.run', return_value=mock_result) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "AMD")
            mock_run.assert_called_once_with(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True
            )

    def test_detect_gpu_macos_other(self):
        mock_result = MagicMock()
        mock_result.stdout = "Chipset Model: Apple M1 Max\n"
        mock_result.returncode = 0
        with patch('depends.sys.platform', 'darwin'), \
             patch('depends.subprocess.run', return_value=mock_result) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Mac")
            mock_run.assert_called_once_with(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True
            )

    def test_detect_gpu_macos_error(self):
        with patch('depends.sys.platform', 'darwin'), \
             patch('depends.subprocess.run', side_effect=Exception("Profiler Error")) as mock_run:
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Mac")
            mock_run.assert_called_once_with(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True
            )

    def test_detect_gpu_unsupported_os(self):
        with patch('depends.sys.platform', 'sunos5'):
             # No need to patch subprocess as it shouldn't be called
            gpu_type = depends.detect_gpu_type(dummy_log)
            self.assertEqual(gpu_type, "Unknown")


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
