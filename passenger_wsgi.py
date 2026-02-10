"""
Passenger WSGI entry point for cPanel deployment
"""
import sys
import os

# Agregar el directorio del proyecto al path
INTERP = os.path.expanduser("~/virtualenv/fisichecker/bin/python3")
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# Directorio del proyecto
sys.path.insert(0, os.path.dirname(__file__))

# Configurar Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')

# Importar la aplicación WSGI de Django
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
