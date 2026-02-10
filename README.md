# FisiChecker - Backend

Backend del proyecto FisiChecker, API REST para análisis automático de accesibilidad web según estándares WCAG 2.1.

## 📋 Descripción del Proyecto

FisiChecker Backend es una API RESTful desarrollada con Django que proporciona servicios de auditoría de accesibilidad web. El sistema evalúa sitios web contra los criterios WCAG 2.1 (niveles A, AA, AAA) utilizando múltiples modos de análisis: HTML estático, renderizado dinámico e integración con IA.

## 🔗 Repositorios

- **Frontend**: [FisiChecker-Project-Front](https://github.com/JhosepSF/FisiChecker-Project-Front)
- **Backend**: [FisiChecker-Project-Back](https://github.com/JhosepSF/FisiChecker-Project-Back)

## 🚀 Características Principales

- **Auditorías Multi-Modo**:
  - `RAW`: Análisis de HTML estático
  - `RENDERED`: Análisis de contenido renderizado (Playwright)
  - `AI`: Análisis asistido por IA (Ollama)
  - `AUTO`: Selección automática del modo óptimo

- **Evaluación WCAG 2.1**:
  - Niveles de conformidad A, AA, AAA
  - 4 Principios: Perceptible, Operable, Comprensible, Robusto
  - Múltiples criterios de éxito evaluados

- **Estadísticas y Reportes**:
  - Puntuaciones de accesibilidad
  - Estadísticas por nivel y principio
  - Análisis comparativo de resultados

- **Persistencia de Datos**:
  - Almacenamiento de auditorías históricas
  - Resultados detallados por criterio
  - Exportación de datos

## 📦 Instalación

### Requisitos Previos

- Python 3.10 o superior
- pip
- SQLite (incluido por defecto) o MySQL
- Node.js (para Playwright)

### Pasos de Instalación

1. **Clonar el repositorio**:
```bash
git clone https://github.com/JhosepSF/FisiChecker-Project-Back.git
cd FisiChecker-Project-Back
```

2. **Crear y activar entorno virtual**:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

3. **Instalar dependencias**:
```bash
pip install -r requirements.txt
```

4. **Instalar Playwright** (para modo RENDERED):
```bash
playwright install
```

5. **Configurar base de datos**:
```bash
python manage.py migrate
```

6. **Crear superusuario** (opcional):
```bash
python manage.py createsuperuser
```

## 🏃 Ejecución

### Modo Desarrollo

```bash
python manage.py runserver
```

La API estará disponible en `http://localhost:8000`

### Modo Producción

Para producción, se recomienda usar Gunicorn o uWSGI:

```bash
pip install gunicorn
gunicorn FisiChecker.wsgi:application --bind 0.0.0.0:8000
```

## 🛠️ Tecnologías Utilizadas

- **Django 5.2.5** - Framework web
- **Django REST Framework** - API REST
- **BeautifulSoup4** - Parsing HTML
- **Playwright** - Renderizado y análisis dinámico
- **Requests** - Cliente HTTP
- **SQLite/MySQL** - Base de datos
- **CORS Headers** - Manejo de CORS
- **OpenPyXL** - Exportación Excel

## 📁 Estructura del Proyecto

```
Back/
├── FisiChecker/           # Configuración del proyecto Django
│   ├── settings.py        # Configuración principal
│   ├── urls.py            # Rutas principales
│   └── wsgi.py            # WSGI config
├── audits/                # App principal de auditorías
│   ├── models.py          # Modelos de datos
│   ├── views.py           # Vistas/endpoints API
│   ├── serializers.py     # Serializadores DRF
│   ├── audit.py           # Lógica de auditoría
│   ├── statistics.py      # Cálculo de estadísticas
│   ├── checks/            # Sistema de verificaciones
│   │   └── criteria/      # Criterios WCAG implementados
│   ├── ai/                # Integración con IA
│   │   ├── ollama_client.py
│   │   └── helper.py
│   ├── utils/             # Utilidades
│   └── wcag/              # Recursos WCAG
├── manage.py              # CLI de Django
├── requirements.txt       # Dependencias Python
└── db.sqlite3            # Base de datos SQLite
```

## 🔌 API Endpoints

### Auditorías

#### POST `/api/audit/`
Crear nueva auditoría de accesibilidad.

**Request Body**:
```json
{
  "url": "https://ejemplo.com",
  "mode": "rendered"  // "raw" | "rendered" | "ai" | "auto"
}
```

**Response**:
```json
{
  "id": 1,
  "url": "https://ejemplo.com",
  "score": 85.5,
  "status_code": 200,
  "results": { ... },
  "fetched_at": "2026-02-10T10:30:00Z"
}
```

#### GET `/api/audits/`
Listar todas las auditorías.

#### GET `/api/audits/{id}/`
Obtener detalle de una auditoría específica.

### Estadísticas

#### GET `/api/audits/{id}/statistics/`
Obtener estadísticas detalladas de una auditoría.

**Response**:
```json
{
  "overall_score": 85.5,
  "level_stats": {
    "A": { "total": 20, "pass": 18, "fail": 2 },
    "AA": { "total": 15, "pass": 12, "fail": 3 },
    "AAA": { "total": 10, "pass": 7, "fail": 3 }
  },
  "principle_stats": { ... }
}
```

## ⚙️ Configuración

### Variables de Entorno

Crea un archivo `.env` en la raíz del proyecto:

```env
DEBUG=True
SECRET_KEY=tu-clave-secreta-segura
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3

# Configuración Ollama (opcional para modo AI)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama2
```

### Base de Datos

Por defecto usa SQLite. Para usar MySQL, actualiza `settings.py`:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'fisichecker',
        'USER': 'usuario',
        'PASSWORD': 'contraseña',
        'HOST': 'localhost',
        'PORT': '3306',
    }
}
```

## 🧪 Testing

Ejecutar tests:

```bash
# Todos los tests
python manage.py test

# Tests específicos
python test_audit_strict.py
python test_statistics.py
```

## 📊 Scripts Útiles

- `check_statistics.py` - Verificar cálculos estadísticos
- `benchmark_urls.py` - Benchmark de rendimiento
- `clean_db.py` - Limpiar base de datos
- `debug_credito.py` - Debug de análisis específico
- `run_audit_auto_ai.py` - Ejecutar auditoría con IA

## 🔍 Modos de Análisis

### RAW (HTML Estático)
Análisis rápido del HTML sin ejecutar JavaScript. Ideal para verificaciones básicas.

### RENDERED (Playwright)
Renderiza la página en un navegador real y analiza el DOM final. Detecta problemas dinámicos.

### AI (Ollama)
Análisis asistido por IA para detectar problemas complejos de accesibilidad que requieren comprensión contextual.

### AUTO
Selecciona automáticamente el mejor modo según las características del sitio.

## 📈 Sistema de Puntuación

- **100**: Accesibilidad perfecta
- **80-99**: Buena accesibilidad, mejoras menores
- **60-79**: Accesibilidad aceptable, requiere mejoras
- **40-59**: Accesibilidad deficiente
- **0-39**: Accesibilidad muy pobre

## 🐛 Debugging

Ver logs de auditoría:
```bash
tail -f audit_auto_ai_log.txt
```

Modo debug en Django:
```python
# settings.py
DEBUG = True
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
}
```

## 🔐 Seguridad

- Cambia `SECRET_KEY` en producción
- Configura `ALLOWED_HOSTS` apropiadamente
- Establece `DEBUG = False` en producción
- Usa HTTPS en producción
- Configura CORS correctamente para tu frontend

## 📚 Documentación Adicional

- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [Django Documentation](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Playwright Python](https://playwright.dev/python/)

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Para contribuir:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📄 Licencia

[Especificar licencia del proyecto]

## ✉️ Contacto

Para consultas o soporte, visita el repositorio en GitHub o contacta al equipo de desarrollo.

---

**Desarrollado como parte del proyecto de tesis FisiChecker**
