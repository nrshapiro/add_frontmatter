"""PyInstaller entry point.

PyInstaller needs a plain top-level script to build from, but running
``cli.py`` directly (as the old build command did) executes it as a
standalone script with no parent package — which breaks the ``from .config
import ...`` / ``from .core import ...`` relative imports inside it
(ImportError: attempted relative import with no known parent package).

This tiny wrapper is what gets handed to PyInstaller instead: it imports
``add_frontmatter.cli`` the normal way (as a package, via --paths src, see
build.yml), so the relative imports inside cli.py resolve correctly, then
just calls its main().
"""

import sys

from add_frontmatter.cli import main

if __name__ == "__main__":
    sys.exit(main())
