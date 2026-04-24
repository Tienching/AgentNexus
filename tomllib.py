"""Compatibility shim for stdlib ``tomllib``.

On Python 3.11+ we load the real stdlib implementation explicitly from the
standard-library path so this local shim does not shadow it. On older Python
versions we fall back to the ``tomli`` backport.
"""

from __future__ import annotations

import importlib.util
import sys
import sysconfig
from pathlib import Path


def _load_stdlib_tomllib():
    stdlib_root = Path(sysconfig.get_path("stdlib"))
    module_path = stdlib_root / "tomllib.py"
    package_dir = stdlib_root / "tomllib"
    if module_path.exists():
        spec = importlib.util.spec_from_file_location("_stdlib_tomllib", module_path)
    elif (package_dir / "__init__.py").exists():
        spec = importlib.util.spec_from_file_location(
            "_stdlib_tomllib",
            package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
    else:
        raise ImportError(f"Unable to locate stdlib tomllib under {stdlib_root}")
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load stdlib tomllib from {stdlib_root}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if sys.version_info >= (3, 11):
    _tomllib = _load_stdlib_tomllib()
    __all__ = list(getattr(_tomllib, "__all__", []))
    if not __all__:
        __all__ = [name for name in ("load", "loads", "TOMLDecodeError") if hasattr(_tomllib, name)]
    for _name in __all__:
        globals()[_name] = getattr(_tomllib, _name)
else:
    from tomli import *  # type: ignore  # noqa: F401,F403
    from tomli import __all__  # type: ignore  # noqa: F401
