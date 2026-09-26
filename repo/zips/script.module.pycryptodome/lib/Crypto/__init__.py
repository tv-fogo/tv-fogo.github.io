"""Compatibility namespace for packages that import `Crypto`.

Kodi Matrix/Nexus/Omega run Python 3, while this addon historically exposed the
`Crypto` namespace. We ship upstream `Cryptodome` (Python 3) and map this
package path so imports like `from Crypto.Cipher import AES` keep working.
"""

from __future__ import absolute_import

import os

from Cryptodome import version_info as _version_info

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
_CRYPTODOME_DIR = os.path.join(_BASE_DIR, "Cryptodome")

# Redirect all submodule imports (Crypto.Cipher, Crypto.Hash, ...) to the
# bundled Python 3 implementation under `Cryptodome`.
__path__ = [_CRYPTODOME_DIR]

__all__ = ["Cipher", "Hash", "Protocol", "PublicKey", "Util", "Signature",
           "IO", "Math", "Random"]
version_info = _version_info
__version__ = ".".join([str(x) for x in version_info])
