#  global_signals.py
from PySide6.QtCore import QObject, Signal

class GlobalSignals(QObject):
    log_message = Signal(str)

# Create a global instance
global_signals = GlobalSignals()