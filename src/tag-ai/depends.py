import subprocess
import sys
import platform
import os
import tempfile
import shutil
import requests
import webbrowser
import urllib.request
import ctypes
import urllib.request

# Add paths module imports
try:
    from paths import get_temp_dir, get_user_data_dir, get_app_dir
except ImportError:
    from .paths import get_temp_dir, get_user_data_dir, get_app_dir
# ===== New GPU Support Functions =====

def detect_gpu_type(log):
    """
    Detect if the system has an NVIDIA, AMD, or other GPU.
    
    Returns:
        str: "NVIDIA", "AMD", or "Unknown"
    """
    log("Starting GPU detection...", "info")
    
    if os.name == "nt":  # Windows
        try:
            # Windows Management Instrumentation Command-line (WMIC)
            result = subprocess.run(["wmic", "path", "win32_VideoController", "get", "name"], 
                                   capture_output=True, text=True, check=True)
            output = result.stdout.lower()
            
            # Log the detected GPU information
            log(f"Detected video controllers: {output.strip()}", "info")
            
            if "nvidia" in output:
                log("✅ NVIDIA GPU detected.", "info")
                return "NVIDIA"
            elif "amd" in output or "radeon" in output:
                log("✅ AMD GPU detected.", "info")
                return "AMD"
            else:
                log("No specific GPU brand detected in Windows system.", "warning")
                return "Unknown"
                
        except Exception as e:
            log(f"Error detecting GPU on Windows: {e}", "error")
            return "Unknown"
            
    elif sys.platform.startswith("linux"):  # Linux
        try:
            # Try lspci first (most common)
            result = subprocess.run(["lspci"], capture_output=True, text=True)
            output = result.stdout.lower()
            
            # Log the detected GPU information
            log(f"Detected PCI devices: {output.strip()}", "debug")
            
            if "nvidia" in output:
                log("✅ NVIDIA GPU detected.", "info")
                return "NVIDIA"
            elif "amd" in output or "radeon" in output:
                log("✅ AMD GPU detected.", "info")
                return "AMD"
                
            # Try additional commands if lspci didn't yield results
            result = subprocess.run(["glxinfo"], capture_output=True, text=True)
            output = result.stdout.lower()
            
            if "nvidia" in output:
                log("✅ NVIDIA GPU detected via glxinfo.", "info")
                return "NVIDIA"
            elif "amd" in output or "radeon" in output:
                log("✅ AMD GPU detected via glxinfo.", "info")
                return "AMD"
                
            log("No specific GPU brand detected in Linux system.", "warning")
            return "Unknown"
                
        except Exception as e:
            log(f"Error detecting GPU on Linux: {e}", "error")
            return "Unknown"
            
    elif sys.platform == "darwin":  # macOS
        log("Running on macOS. GPU acceleration limited to Metal API.", "info")
        try:
            # Try to get GPU information on Mac
            result = subprocess.run(["system_profiler", "SPDisplaysDataType"], 
                                   capture_output=True, text=True)
            output = result.stdout.lower()
            
            if "amd" in output or "radeon" in output:
                log("Mac has AMD GPU.", "info")
                return "AMD"
            elif "nvidia" in output:
                log("Mac has NVIDIA GPU.", "info")
                return "NVIDIA"
            else:
                log("Mac with integrated or unidentified GPU.", "info")
                return "Mac"
        except Exception as e:
            log(f"Error detecting GPU on macOS: {e}", "error")
            return "Mac"
        
    else:
        log("Unsupported operating system for GPU detection.", "warning")
        return "Unknown"

def is_rocm_installed(log):
    """
    Check if ROCm is installed for AMD GPUs.
    
    Returns:
        bool: True if ROCm is installed, False otherwise
    """
    log("Checking if ROCm is installed...", "info")
    
    path_dirs = os.environ["PATH"].split(os.pathsep)
    rocm_exe = "rocminfo.exe" if os.name == "nt" else "rocminfo"
    
    # Check if rocminfo is in PATH
    rocm_found = any(os.path.exists(os.path.join(d, rocm_exe)) for d in path_dirs)
    
    if rocm_found:
        try:
            result = subprocess.run([rocm_exe], capture_output=True, text=True)
            if result.returncode == 0:
                log(f"✅ ROCm is installed and working! Sample output:\n{result.stdout[:200]}...", "info")
                return True
            else:
                log(f"⚠️ {rocm_exe} found but not working correctly.", "warning")
                log(f"Error output: {result.stderr}", "debug")
                return False
        except FileNotFoundError:
            log(f"⚠️ {rocm_exe} not found in PATH despite presence check.", "warning")
            return False
    
    # Additional checks for different ROCm installations
    if os.name == "nt":  # Windows
        # Check common installation directories
        common_paths = [
            r"C:\Program Files\AMD\ROCm",
            r"C:\Program Files\ROCm"
        ]
        for path in common_paths:
            if os.path.exists(path):
                log(f"ROCm installation directory found at {path}", "info")
                # Still return False as rocminfo is not in PATH
                log("⚠️ ROCm directory found but not properly added to PATH.", "warning")
                return False
    else:  # Linux
        # Check common Linux ROCm locations
        common_paths = [
            "/opt/rocm",
            "/usr/local/rocm"
        ]
        for path in common_paths:
            if os.path.exists(path):
                log(f"ROCm installation directory found at {path}", "info")
                # Still return False as rocminfo is not in PATH
                log("⚠️ ROCm directory found but not properly added to PATH.", "warning")
                return False
    
    log("ROCm not detected.", "info")
    return False


def download_and_install_rocm(log):
    """
    Download and install ROCm for AMD GPUs.
    
    Returns:
        bool: True if installation succeeded or instructions provided, False on error
    """
    log("Starting ROCm installation process...", "info")
    
    if os.name == "nt":  # Windows
        log("Installing ROCm on Windows...", "info")
        try:
            # For Windows, we'll provide a download link and instructions
            # as automated installation is complex
            rocm_url = "https://www.amd.com/en/graphics/drivers/rocm-developer-tools"
            
            log("ROCm installation on Windows requires manual steps:", "info")
            log(f"1. Download ROCm from: {rocm_url}", "info")
            log("2. Follow the installation instructions provided by AMD", "info")
            log("3. Ensure ROCm is added to your PATH after installation", "info")
            
            # On Windows, return True to continue with setup, as we've provided instructions
            return True
            
        except Exception as e:
            log(f"Error providing ROCm installation instructions: {e}", "error")
            return False
            
    elif sys.platform.startswith("linux"):  # Linux
        log("Installing ROCm on Linux...", "info")
        distro = ""
        
        try:
            # Try to detect Linux distribution
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    os_info = f.read().lower()
                    if "ubuntu" in os_info:
                        distro = "ubuntu"
                    elif "debian" in os_info:
                        distro = "debian"
                    elif "fedora" in os_info:
                        distro = "fedora"
                    elif "rhel" in os_info or "centos" in os_info:
                        distro = "rhel"
                        
            if not distro:
                # Try more direct commands
                try:
                    result = subprocess.run(["lsb_release", "-a"], capture_output=True, text=True)
                    if "ubuntu" in result.stdout.lower():
                        distro = "ubuntu"
                except:
                    pass
            
            log(f"Detected Linux distribution: {distro if distro else 'Unknown'}", "info")
            
            if distro == "ubuntu" or distro == "debian":
                # Ubuntu/Debian installation
                log("Installing ROCm for Ubuntu/Debian...", "info")
                
                # Add ROCm apt repository
                log("Setting up ROCm APT repository...", "info")
                commands = [
                    ["sudo", "apt", "update"],
                    ["sudo", "apt", "install", "-y", "wget", "gnupg2"],
                    ["wget", "-q", "-O", "-", "https://repo.radeon.com/rocm/rocm.gpg.key", "|", "sudo", "apt-key", "add", "-"],
                    ["echo", "deb [arch=amd64] https://repo.radeon.com/rocm/apt/debian/ ubuntu main", "|", "sudo", "tee", "/etc/apt/sources.list.d/rocm.list"],
                    ["sudo", "apt", "update"],
                    ["sudo", "apt", "install", "-y", "rocm-dev"]
                ]
                
                for cmd in commands:
                    log(f"Running: {' '.join(cmd)}", "info")
                    try:
                        subprocess.run(cmd, check=True)
                    except Exception as e:
                        log(f"Command failed: {e}", "error")
                        # Continue with next command
                
                log("ROCm installation steps completed. Please verify installation.", "info")
                return True
                
            elif distro == "fedora" or distro == "rhel":
                # Fedora/RHEL installation instructions
                log("Installing ROCm for Fedora/RHEL...", "info")
                
                commands = [
                    ["sudo", "dnf", "install", "-y", "https://repo.radeon.com/amdgpu-install/5.4.2/rhel/8.7/amdgpu-install-5.4.50402-1.el8.noarch.rpm"],
                    ["sudo", "dnf", "clean", "all"],
                    ["sudo", "amdgpu-install", "--usecase=rocm"]
                ]
                
                for cmd in commands:
                    log(f"Running: {' '.join(cmd)}", "info")
                    try:
                        subprocess.run(cmd, check=True)
                    except Exception as e:
                        log(f"Command failed: {e}", "error")
                        # Continue with next command
                
                log("ROCm installation steps completed. Please verify installation.", "info")
                return True
                
            else:
                # Generic Linux instructions
                rocm_url = "https://rocm.docs.amd.com/en/latest/deploy/linux/index.html"
                log(f"Please follow the ROCm installation guide at: {rocm_url}", "info")
                return True
                
        except Exception as e:
            log(f"Error during ROCm installation: {e}", "error")
            return False
            
    elif sys.platform == "darwin":  # macOS
        log("ROCm is not directly supported on macOS. GPU acceleration uses Metal API instead.", "info")
        return True
        
    else:
        log("Unsupported operating system for ROCm installation.", "warning")
        return False

def check_and_install_gpu_support(self):
        """Check and install GPU support based on detected GPU type."""
        gpu_type = self.detect_gpu_type()
        self.log(f"Detected GPU type: {gpu_type}")
        if os.name == "nt":
            if gpu_type == "NVIDIA":
                if self.is_cuda_installed():
                    self.log("CUDA 12.4 is already installed. Proceeding...")
                else:
                    self.log("CUDA 12.4 not found. Starting automatic installation...")
                    self.download_and_install_cuda_12_4_windows()
                    if self.is_cuda_installed():
                        self.log("CUDA 12.4 installed successfully. Proceeding...")
                    else:
                        self.log("CUDA 12.4 still not detected. Restart and re-run.")
                        sys.exit(1)
            elif gpu_type == "AMD":
                if self.is_rocm_installed():
                    self.log("ROCm is already installed. Proceeding...")
                else:
                    self.log("ROCm not found. Starting automatic installation for ROCm 6.1...")
                    self.download_and_install_rocm_6_1_windows()
                    if self.is_rocm_installed():
                        self.log("ROCm 6.1 installed successfully. Proceeding...")
                    else:
                        self.log("ROCm 6.1 still not detected. Restart and re-run.")
                        sys.exit(1)
            else:
                self.log("No supported GPU detected. Proceeding without GPU acceleration.")
        elif sys.platform == "darwin":
            self.log("You are on a Mac. CUDA/ROCm not needed or supported.")
        elif sys.platform.startswith("linux"):
            if gpu_type == "NVIDIA":
                if self.is_cuda_installed():
                    self.log("Compatible CUDA (11.8–12.5) installed. Proceeding...")
                else:
                    self.log("CUDA not found or incompatible. Install CUDA 11.8–12.5 manually.")
                    webbrowser.open("https://developer.nvidia.com/cuda-downloads?target_os=Linux")
                    self.log("After installing CUDA, press Continue to proceed...")
                    return
            elif gpu_type == "AMD":
                if self.is_rocm_installed():
                    self.log("ROCm is installed. Proceeding...")
                else:
                    self.log("ROCm not found. Install ROCm 6.1+ manually for AMD GPU support.")
                    webbrowser.open("https://rocm.docs.amd.com/en/latest/deploy/linux/quick_start.html")
                    self.log("After installing ROCm, press Continue to proceed...")
                    return
            else:
                self.log("No supported GPU detected. Proceeding without GPU acceleration.")
        else:
            self.log("Unsupported operating system.")
            sys.exit(1)

# ===== Cuda Check and Install Functions =====

def is_cuda_installed(log):
    """
    Enhanced check if CUDA is installed using multiple detection methods.
    Handles platform-specific checks properly.
    
    Returns:
        bool: True if CUDA is properly installed or not needed (macOS), False otherwise
    """
    log("Checking if CUDA is installed...", "info")
    
    # Handle macOS separately - CUDA isn't supported on Mac
    if sys.platform == "darwin":
        log("Running on macOS - CUDA is not needed (Metal API is used instead).", "info")
        return True  # Return True to indicate "no action needed" rather than failure
    
    # Method 1: Check in PATH (works on all platforms)
    path_dirs = os.environ["PATH"].split(os.pathsep)
    nvcc_exe = "nvcc.exe" if os.name == "nt" else "nvcc"
    nvcc_found = any(os.path.exists(os.path.join(d, nvcc_exe)) for d in path_dirs)
    
    if nvcc_found:
        try:
            result = subprocess.run([nvcc_exe, "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                version = result.stdout
                log(f"CUDA is installed! Version info:\n{version}", "info")
                return True
        except Exception as e:
            log(f"⚠️ Error checking NVCC in PATH: {e}", "warning")
    
    # Windows-specific checks
    if os.name == "nt":  # Windows only
        # Method 2: Check in common installation directories
        cuda_versions = ["v12.4", "v12.3", "v12.2", "v12.1", "v12.0", "v11.8"]
        for version in cuda_versions:
            cuda_path = os.path.join("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA", version, "bin", "nvcc.exe")
            if os.path.exists(cuda_path):
                log(f"✅ Found CUDA {version} at {cuda_path}", "info")
                log("CUDA is installed but may not be in PATH", "info")
                return True

        # Method 3: Check Windows Registry for CUDA installation
        try:
            # Only import winreg on Windows
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                             r"SOFTWARE\NVIDIA Corporation\GPU Computing Toolkit\CUDA") as key:
                # Just checking if the key exists
                log("✅ Found CUDA installation in Windows Registry", "info")
                return True
        except ImportError:
            log("winreg module not available - skipping Windows registry check", "warning")
        except WindowsError:
            # Key doesn't exist
            log("CUDA not found in Windows registry", "info")
    
    # Linux-specific checks
    elif sys.platform.startswith("linux"):
        # Try additional Linux-specific detection methods
        try:
            # Check if nvidia-smi is available (usually installed with CUDA)
            result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
            if result.returncode == 0:
                log("✅ nvidia-smi is available, CUDA appears to be installed", "info")
                return True
        except Exception:
            # Command not found or failed
            pass
        
        # Check common Linux CUDA installation paths
        linux_cuda_paths = [
            "/usr/local/cuda/bin/nvcc",
            "/usr/cuda/bin/nvcc",
            "/opt/cuda/bin/nvcc"
        ]
        for path in linux_cuda_paths:
            if os.path.exists(path):
                log(f"✅ Found CUDA installation at {path}", "info")
                return True
                
        # Check for CUDA in ld.so.conf or via ldconfig
        try:
            result = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True)
            if "libcuda.so" in result.stdout:
                log("✅ Found CUDA libraries in ldconfig cache", "info")
                return True
        except Exception:
            # Command not found or failed
            pass
    
    log("CUDA not detected through any detection method.", "info")
    return False


import os
import ctypes
import requests

def download_and_install_cuda_12_4_windows(log):
    """
    Download and install CUDA 12.4 for Windows using elevation via ShellExecute.
    
    Returns:
        bool: True if installation succeeded, False otherwise
    """
    log("Starting CUDA 12.4 installation process...", "info")
    
    cuda_url = "https://developer.download.nvidia.com/compute/cuda/12.4.0/local_installers/cuda_12.4.0_551.61_windows.exe"
    installer_path = os.path.join(get_temp_dir(), "cuda_12.4.0_551.61_windows.exe")
    
    # Attempt to retrieve expected file size via a HEAD request
    expected_size = 0
    try:
        head_response = requests.head(cuda_url)
        head_response.raise_for_status()
        expected_size = int(head_response.headers.get('content-length', 0))
    except Exception as e:
        log(f"Warning: Failed to retrieve expected file size from HEAD request: {e}", "warning")
    
    # If the installer exists, verify its size against the expected value (if available)
    if os.path.exists(installer_path):
        current_size = os.path.getsize(installer_path)
        if expected_size > 0 and current_size != expected_size:
            log("Existing installer file is incomplete. Removing and re-downloading...", "info")
            os.remove(installer_path)
    
    # Download the installer if it doesn't exist
    if not os.path.exists(installer_path):
        log("Downloading CUDA 12.4 installer for Windows...", "info")
        try:
            log(f"Downloading from: {cuda_url}", "info")
            response = requests.get(cuda_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            last_percent = 0
            
            with open(installer_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded * 100) // total_size
                            if percent >= last_percent + 5:
                                log(f"Download progress: {percent}%", "info")
                                last_percent = percent
            
            log("✅ Download completed successfully.", "info")
        except Exception as e:
            log(f"❌ Failed to download CUDA installer: {e}", "error")
            return False
    else:
        log(f"CUDA installer already exists at: {installer_path}", "info")
    
    # Launch the installer with elevation via ShellExecuteW (note the added None for lpDirectory)
    log("Installing CUDA 12.4...", "info")
    log("A User Account Control (UAC) prompt will appear.", "info")
    log("Please approve it to install CUDA with administrator privileges.", "info")
    
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "open", installer_path, None, None, 1)
        log("✅ CUDA installer launched successfully with elevation.", "info")
        log("Please complete the CUDA installation when prompted.", "info")
        log("This may take several minutes.", "info")
        
        # Wait for user confirmation that the installation is complete
        log("After CUDA installation completes, press Enter to continue setup...", "info")
        input("Press Enter to continue after CUDA installation completes...")
        
        # Check if CUDA is now installed
        if is_cuda_installed(log):
            log("✅ CUDA 12.4 installation verified successfully.", "success")
            return True
        else:
            log("⚠️ CUDA installation may not have completed successfully.", "warning")
            log("You may need to restart your computer for CUDA to be fully activated.", "info")
            return True  # Allow setup to continue even if not immediately detected
    except Exception as e:
        log(f"❌ Error launching CUDA installer: {e}", "error")
        return False


def check_and_install_cuda(log):
    """Check and install CUDA based on OS."""
    if os.name == "nt":
        if is_cuda_installed(log):
            log("CUDA 12.4 is already installed. Proceeding with your program...")
        else:
            log("CUDA 12.4 not found on Windows. Starting automatic installation...")
            download_and_install_cuda_12_4_windows(log)
            if is_cuda_installed(log):
                log("CUDA 12.4 installed successfully. Proceeding with your program...")
            else:
                log("Installation completed, but CUDA 12.4 still not detected. Restart and re-run.")
                sys.exit(1)
    elif sys.platform == "darwin":
        log("You are on a Mac. CUDA is not needed or supported on macOS.")
    elif sys.platform.startswith("linux"):
        if is_cuda_installed(log):
            log("Compatible CUDA version (11.8–12.5) is installed. Proceeding with your program...")
        else:
            log("CUDA not found or version is incompatible on Linux.")
            webbrowser.open("https://developer.nvidia.com/cuda-downloads?target_os=Linux")
            log("After installing CUDA, press Enter to continue...")
            input()
            if is_cuda_installed(log):
                log("Compatible CUDA version detected. Proceeding with your program...")
            else:
                log("CUDA still not detected or version is incompatible. Check installation.")
                sys.exit(1)
    else:
        log("Unsupported operating system.")
        sys.exit(1)
    
# ===== Ollama Setup Functions =====

def check_ollama_installed(log):
    """Check if the 'ollama' command is available and executable on macOS, Linux, or Windows."""
    ollama_path = shutil.which("ollama")

    # Additional checks for macOS/Linux common install locations
    if not ollama_path:
        possible_paths = [
            "/usr/local/bin/ollama",  # Homebrew (Intel macs)
            "/opt/homebrew/bin/ollama",  # Homebrew (Apple Silicon macs)
            "/usr/bin/ollama",  # Possible Linux location
            "/snap/bin/ollama",  # Possible Linux Snap install
            "/Applications/Ollama.app/Contents/MacOS/ollama",  # macOS App Store/Disk Image install
        ]
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):  # Ensure it exists and is executable
                ollama_path = path
                break

    # If found, verify it runs
    if ollama_path:
        try:
            subprocess.run([ollama_path, "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            log(f"Ollama is installed at {ollama_path}.", "info")
            return True
        except Exception as e:
            log(f"Ollama was found at {ollama_path} but could not be executed: {e}", "error")
            return False
    else:
        log("Ollama is not installed or not in a recognized location.", "info")
        return False

def get_os_info():
    """Return operating system name and architecture."""
    os_name = platform.system()
    architecture = platform.machine()
    return os_name, architecture

import os
import urllib.request

# Make sure get_temp_dir() is defined or imported from your package
# For example:
# from your_module import get_temp_dir

def download_ollama_installer(os_name, architecture, log):
    """Download the Ollama installer based on the operating system.
    
    Parameters:
      os_name (str): The name of the operating system (e.g., "Windows", "Darwin", "Linux").
      architecture (str): The CPU architecture (not currently used in this function).
      log (callable): A logging function that accepts a message and a log level.
    
    Returns:
      tuple: (os_name, installer_path) if successful; otherwise (None, None).
    """
    log(f"Downloading Ollama installer for {os_name} ({architecture})...", "info")
    download_url = None
    installer_path = None

    if os_name == "Windows":
        download_url = "https://ollama.com/download/OllamaSetup.exe"
        installer_path = os.path.join(get_temp_dir(), "OllamaSetup.exe")
    elif os_name == "Darwin":  # macOS
        download_url = "https://ollama.com/download/Ollama-darwin.zip"
        installer_path = os.path.join(get_temp_dir(), "Ollama-darwin.zip")
    elif os_name == "Linux":
        log("Linux is not supported by this installer.", "error")
        return "linux", None
    else:
        log(f"Unsupported operating system: {os_name}", "error")
        return None, None

    if download_url and installer_path:
        try:
            # Create a Request with a custom User-Agent header
            req = urllib.request.Request(download_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as response, open(installer_path, 'wb') as out_file:
                out_file.write(response.read())
            log(f"Installer downloaded to: {installer_path}", "info")
            return os_name, installer_path
        except Exception as e:
            log(f"Error downloading installer: {e}", "error")
            return None, None
    else:
        log("Download URL or installer path was not set.", "error")
        return None, None

# Example usage:
if __name__ == "__main__":
    # Example log function
    def log(message, level):
        print(f"[{level.upper()}] {message}")
    
    # Replace 'Windows' and 'x64' with your desired OS and architecture values.
    result = download_ollama_installer("Windows", "x64", log)
    print("Result:", result)




def install_ollama(os_name, installer_path, log):
    """Execute the Ollama installer."""
    if os_name == "Windows":
        log("Running Windows installer...", "info")
        try:
            # Launch the installer using ShellExecuteW
            # The parameters are:
            #   hwnd: None (0)
            #   lpOperation: "open"
            #   lpFile: installer_path
            #   lpParameters: None (no extra parameters)
            #   lpDirectory: None (default working directory)
            #   nShowCmd: 1 (SW_SHOWNORMAL)
            result = ctypes.windll.shell32.ShellExecuteW(None, "open", installer_path, None, None, 1)
            if result <= 32:
                raise Exception(f"ShellExecuteW failed with error code {result}")
            log("Ollama installation initiated.", "info")
            return True
        except Exception as e:
            log(f"Error running installer: {e}", "error")
            return False

    elif os_name == "Darwin":
        log("Running macOS installer...", "info")
        try:
            subprocess.run(["open", installer_path], check=True)
            log("macOS installer opened. Please follow the installation prompts.", "info")
            return True
        except subprocess.CalledProcessError as e:
            log(f"Error running installer: {e}", "error")
            return False

    elif os_name == "Linux":
        log("Attempting Linux Ollama installation using curl script...", "info")
        try:
            subprocess.run(["bash", "-c", "$(curl -fsSL https://ollama.ai/install.sh)"], check=True)
            log("Linux Ollama installation script executed.", "info")
            return True
        except subprocess.CalledProcessError as e:
            log(f"Error running Linux install script: {e}", "error")
            return False

    else:
        log("Installation not automated for this OS. Please install Ollama manually.", "warning")
        return False

    # Optionally, if you want to remove the installer file after the process:
    try:
        if os.path.exists(installer_path):
            os.remove(installer_path)
            log(f"Removed temporary installer: {installer_path}", "info")
    except Exception as e:
        log(f"Note: Could not remove installer file: {e}", "warning")


def install_llava_model(log):
    """Starts the Llava model using Ollama in the background."""
    log("Starting Llava model using Ollama in the background...", "info")
    try:
        ollama_process = subprocess.Popen(
            ["ollama", "run", "llava"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        log(f"Llava model process started with PID: {ollama_process.pid}", "info")
        return ollama_process
    except Exception as e:
        log(f"Error starting Llava model in background: {e}", "error")
        return None