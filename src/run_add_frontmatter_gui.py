"""PyInstaller entry point for the GUI build.

PyInstaller needs a plain top-level script to build from, but running
``gui.py`` directly would execute it as a standalone script with no parent
package — which breaks the ``from .config import ...`` / ``from .core
import ...`` relative imports inside it (same reason
``run_add_frontmatter.py`` exists for the CLI build; see that file).

This tiny wrapper is what gets handed to PyInstaller instead: it imports
``add_frontmatter.gui`` the normal way (as a package, via --paths src, see
build.yml), so the relative imports inside gui.py resolve correctly, then
just calls its main().
"""

import sys

from add_frontmatter.gui import main

if __name__ == "__main__":
    sys.exit(main())
