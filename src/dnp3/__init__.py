"""Pure Python DNP3 implementation (IEEE 1815-2012)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dnp3py")
except PackageNotFoundError:
    # Package is not installed (e.g. running from source without install).
    # This sentinel is intentional: it signals a non-installed dev context.
    __version__ = "dev"
