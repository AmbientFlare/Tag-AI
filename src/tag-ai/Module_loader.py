"""
Advanced Module Loader for Cross-Platform Compatibility
Specifically optimized for Briefcase packaging on macOS
"""

import sys
import os
import importlib
import logging
import traceback

def configure_macos_import_paths():
    """
    Configure import paths specifically for macOS Briefcase packaging.
    Adds multiple potential paths to sys.path to ensure module discoverability.
    """
    # Potential path configurations
    macos_paths = [
        # Briefcase app bundle paths
        os.path.join(sys.prefix, 'app'),
        os.path.join(sys.prefix, 'app', 'tagai'),
        
        # Bundle resources
        os.path.join(sys.prefix, 'Resources', 'app'),
        os.path.join(sys.prefix, 'Resources', 'app', 'tagai'),
        
        # Fallback to current directory and its parent
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]
    
    for path in macos_paths:
        if path not in sys.path and os.path.exists(path):
            sys.path.insert(0, path)
            logging.debug(f"Added macOS import path: {path}")

def import_module(name, package=None):
    """
    Enhanced module import with macOS-specific path handling.
    
    Args:
        name (str): Module name to import
        package (str, optional): Package name for relative imports
    
    Returns:
        Imported module
    
    Raises:
        ImportError: If module cannot be imported
    """
    # Configure macOS paths on first import
    configure_macos_import_paths()
    
    logger = logging.getLogger("module_loader")
    logger.debug(f"Attempting to import: {name}, Package: {package}")
    
    # Import strategies
    import_strategies = [
        # 1. Direct import
        lambda: importlib.import_module(name, package),
        
        # 2. Relative import
        lambda: importlib.import_module(f"{package}.{name}") if package else None,
        
        # 3. File-based import with path exploration
        lambda: _file_based_import(name, package),
        
        # 4. Package prefix import attempts
        lambda: _try_package_prefixes(name),
    ]
    
    # Try each import strategy
    for strategy in import_strategies:
        try:
            module = strategy()
            if module is not None:
                logger.debug(f"Successfully imported {name}")
                return module
        except (ImportError, PermissionError, AttributeError) as e:
            logger.debug(f"Import strategy failed: {e}")
            continue
    
    # Comprehensive error logging if all strategies fail
    logger.error(f"Could not import module {name}")
    logger.error(f"Current sys.path: {sys.path}")
    
    raise ImportError(f"Module {name} not found. Searched multiple import strategies.")

def _file_based_import(name, package=None):
    """
    Attempt to import module by explicitly loading from file.
    
    Args:
        name (str): Module name
        package (str, optional): Package name
    
    Returns:
        Imported module or None
    """
    logger = logging.getLogger("module_loader")
    
    # Potential paths to search for the module
    search_paths = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        sys.prefix,
        *sys.path
    ]
    
    # Possible module file names
    possible_names = [
        f"{name}.py",
        f"{name}/__init__.py",
        os.path.join(name, "__init__.py")
    ]
    
    for path in search_paths:
        for module_name in possible_names:
            module_path = os.path.join(path, module_name)
            
            try:
                # Ensure the file exists and is readable
                if os.path.exists(module_path) and os.access(module_path, os.R_OK):
                    logger.debug(f"Attempting to load module from: {module_path}")
                    
                    spec = importlib.util.spec_from_file_location(name, module_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return module
            
            except (ImportError, PermissionError, FileNotFoundError) as e:
                logger.debug(f"File-based import failed for {module_path}: {e}")
                continue
    
    return None

def _try_package_prefixes(name):
    """
    Try importing with various package prefixes.
    
    Args:
        name (str): Module name
    
    Returns:
        Imported module or None
    """
    logger = logging.getLogger("module_loader")
    
    prefixes = ['tagai', 'tag_ai', 'tag-ai', '']
    for prefix in prefixes:
        try:
            full_name = f"{prefix}.{name}" if prefix else name
            module = importlib.import_module(full_name)
            logger.debug(f"Successfully imported {name} with prefix '{prefix}'")
            return module
        except ImportError:
            continue
    
    return None

# Configure basic logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Automatically configure paths on module import
configure_macos_import_paths()

# Optional diagnostic function
def diagnose_import_environment():
    """
    Diagnostic function to print out import-related environment details.
    """
    print("Module Loader Diagnostic Information")
    print("-----------------------------------")
    print(f"Current File: {__file__}")
    print(f"Current Directory: {os.path.dirname(__file__)}")
    print("\nSystem Path Entries:")
    for idx, path in enumerate(sys.path, 1):
        print(f"{idx}. {path}")
    
    print("\nOS Environment:")
    print(f"Platform: {sys.platform}")
    print(f"Python Executable: {sys.executable}")
    print(f"Prefix: {sys.prefix}")