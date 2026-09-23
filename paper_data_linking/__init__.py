"""paper-data-linking: extract and ground data references from heliophysics papers."""
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("paper-data-linking")
except PackageNotFoundError:  # running from a checkout that is not installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
