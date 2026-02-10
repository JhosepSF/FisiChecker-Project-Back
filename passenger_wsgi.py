"""
Passenger WSGI entry point for cPanel deployment
Python 3.6.8 compatible
"""
import sys
import os

# Agregar el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.local', 'lib', 'python3.6', 'site-packages'))

# Configurar Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')

# Importar la aplicación WSGI de Django
try:
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
except Exception as e:
    # En caso de error, devolver una página de error informativa
    def application(environ, start_response):
        status = '500 Internal Server Error'
        output = f'Error loading Django application: {str(e)}'.encode('utf-8')
        response_headers = [('Content-type', 'text/plain'),
                          ('Content-Length', str(len(output)))]
        start_response(status, response_headers)
        return [output]
