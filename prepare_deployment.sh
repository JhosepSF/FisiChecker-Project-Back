#!/bin/bash
# Script de ayuda para preparar el deployment a cPanel

echo "=========================================="
echo "FisiChecker - Preparación para Deployment"
echo "=========================================="
echo ""

# Verificar si existe .env
if [ ! -f .env ]; then
    echo "⚠️  No existe archivo .env"
    echo "Creando .env desde .env.example..."
    cp .env.example .env
    echo "✅ Archivo .env creado"
    echo ""
    echo "⚠️  IMPORTANTE: Edita el archivo .env con tus credenciales reales:"
    echo "   - SECRET_KEY"
    echo "   - DATABASE_PASSWORD"
    echo "   - ALLOWED_HOSTS"
    echo "   - CORS_ALLOWED_ORIGINS"
    echo ""
else
    echo "✅ Archivo .env encontrado"
fi

# Generar SECRET_KEY si es necesario
echo ""
echo "🔑 Generando nueva SECRET_KEY..."
NEW_SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
echo ""
echo "Copia esta clave y pégala en tu archivo .env:"
echo "SECRET_KEY=$NEW_SECRET_KEY"
echo ""

# Verificar dependencias
echo "📦 Verificando dependencias..."
pip install -r requirements.txt --quiet
echo "✅ Dependencias instaladas"
echo ""

# Crear directorios necesarios
echo "📁 Creando directorios necesarios..."
mkdir -p staticfiles
mkdir -p media
mkdir -p tmp
echo "✅ Directorios creados"
echo ""

# Verificar archivos necesarios
echo "🔍 Verificando archivos de deployment..."
files=("passenger_wsgi.py" ".htaccess" ".env.example" "requirements.txt")
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
    else
        echo "  ❌ $file - FALTANTE"
    fi
done
echo ""

# Instrucciones finales
echo "=========================================="
echo "📋 PRÓXIMOS PASOS:"
echo "=========================================="
echo ""
echo "1. Edita el archivo .env con tus credenciales reales"
echo "2. Revisa DEPLOYMENT_CPANEL.md para instrucciones completas"
echo "3. Sube los archivos a cPanel (excepto .env, .venv, db.sqlite3)"
echo "4. Crea el archivo .env en el servidor con tus credenciales"
echo "5. Ejecuta las migraciones en el servidor"
echo "6. Recolecta los archivos estáticos"
echo "7. Reinicia la aplicación"
echo ""
echo "Para más detalles, lee: DEPLOYMENT_CPANEL.md"
echo ""
