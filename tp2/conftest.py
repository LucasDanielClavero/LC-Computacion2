"""
Conftest de pytest: agrega src/ al path para que los tests importen los
modulos de la aplicacion (gestor, api, tareas) como lo hace src/main.py.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))
