# Guía de Deployment - FisiChecker Backend en cPanel

Esta guía te ayudará a desplegar el backend de FisiChecker en tu servidor cPanel.

## 📋 Información del Servidor

- **URL cPanel**: https://taw.solucionesahora.com:2083
- **Usuario**: taw
- **Dominio**: taw.solucionesahora.com

## 🚀 Pasos de Deployment

### 1. Preparar el Proyecto Localmente

#### 1.1 Instalar python-dotenv
```bash
pip install python-dotenv
```

#### 1.2 Crear archivo .env (NO subir a Git)
Copia `.env.example` a `.env` y completa con tus valores reales:

```bash
cp .env.example .env
```

Edita `.env` con la información del servidor:

```env
DEBUG=False
SECRET_KEY=TU_CLAVE_SECRETA_GENERADA_AQUI
ALLOWED_HOSTS=taw.solucionesahora.com,www.taw.solucionesahora.com

# Database MySQL en cPanel
DATABASE_ENGINE=mysql
DATABASE_NAME=taw_fisichecker
DATABASE_USER=taw_fisichecker_user
DATABASE_PASSWORD=
DATABASE_HOST=localhost
DATABASE_PORT=3306

# CORS
CORS_ALLOWED_ORIGINS=https://taw.solucionesahora.com,https://jhosepsf.github.io
CORS_ALLOW_CREDENTIALS=True

# Static Files
STATIC_URL=/static/
STATIC_ROOT=/home/taw/public_html/static
MEDIA_URL=/media/
MEDIA_ROOT=/home/taw/public_html/media
```

#### 1.3 Generar SECRET_KEY segura
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copia la salida y úsala en `.env` como `SECRET_KEY`.

#### 1.4 Crear archivo .gitignore
Asegúrate de tener:
```
.env
db.sqlite3
*.pyc
__pycache__/
staticfiles/
media/
.venv/
venv/
*.log
```

### 2. Acceder a cPanel

1. Abre tu navegador y ve a: https://taw.solucionesahora.com:2083
2. Inicia sesión con:
   - Usuario: `taw`
   - Contraseña: `nomevoyolvidar`

### 3. Configurar Base de Datos MySQL

#### 3.1 Crear Base de Datos
1. En cPanel, busca **"MySQL® Databases"**
2. En "Create New Database", ingresa: `fisichecker`
3. Click en **"Create Database"**

#### 3.2 Crear Usuario de Base de Datos
1. En la misma página, bajo "MySQL Users"
2. Username: `fisichecker_user`
3. Password: Genera una segura (guárdala en tu .env)
4. Click en **"Create User"**

#### 3.3 Asignar Usuario a la Base de Datos
1. Bajo "Add User To Database"
2. Selecciona el usuario: `taw_fisichecker_user`
3. Selecciona la base de datos: `taw_fisichecker`
4. Click en **"Add"**
5. Marca **"ALL PRIVILEGES"**
6. Click en **"Make Changes"**

### 4. Configurar Python en cPanel

#### Opción A: Si tu cPanel tiene "Setup Python App"

1. En cPanel, busca **"Setup Python App"** (o "Python Applications")
2. Click en **"Create Application"**
3. Configuración:
   - **Python version**: 3.9 o superior (la más reciente disponible)
   - **Application root**: `/home/taw/fisichecker`
   - **Application URL**: `/` o `/api` (según prefieras)
   - **Application startup file**: `passenger_wsgi.py`
   - **Application Entry point**: `application`

4. Click en **"Create"**

5. Agrega **Environment Variables** en la misma página:
```
DEBUG=False
SECRET_KEY=tu-clave-secreta-generada
ALLOWED_HOSTS=taw.solucionesahora.com
DATABASE_ENGINE=mysql
DATABASE_NAME=taw_fisichecker
DATABASE_USER=taw_fisichecker_user
DATABASE_PASSWORD=tu_password_mysql
DATABASE_HOST=localhost
DATABASE_PORT=3306
CORS_ALLOWED_ORIGINS=https://jhosepsf.github.io
```

#### Opción B: Método Manual con .htaccess (Si no existe "Setup Python App")

**Nota:** Si cPanel no tiene la opción de "Setup Python App", usa este método que funciona directamente con archivos:

1. Sube los archivos normalmente al servidor (ver sección 5)
2. El archivo `.htaccess` que ya incluimos dirigirá el tráfico a Passenger
3. Crea un archivo `.htaccess` adicional en `/home/taw/public_html`:

```apache
<IfModule mod_passenger.c>
  PassengerAppRoot "/home/taw/fisichecker"
  PassengerBaseURI "/"
  PassengerPython "/home/taw/virtualenv/fisichecker/bin/python3"
  PassengerEnabled On
</IfModule>
```

4. Las variables de entorno se configuran en el archivo `.env` que crearás en el servidor

### 5. Subir Archivos al Servidor

#### Método Recomendado #1: Usando ZIP (Más Fácil)

**En tu computadora local:**

1. Comprime el proyecto COMPLETO en un archivo ZIP:
   - Nombre sugerido: `fisichecker.zip`
   - **NO incluyas:** `.venv/`, `venv/`, `db.sqlite3`, `__pycache__/`, `.env`

2. En cPanel **File Manager**:
   - Navega a `/home/taw/`
   - Click en **"Upload"**
   - Sube `fisichecker.zip`
   - Una vez subido, haz click derecho sobre el archivo
   - Selecciona **"Extract"** (Extraer)
   - Se creará automáticamente la carpeta `fisichecker/` con todo dentro

#### Método Recomendado #2: Usando Git (Si ya tienes el repo en GitHub)

1. Accede a cPanel **Terminal** (o SSH)
2. Ejecuta:

```bash
cd /home/taw
git clone https://github.com/JhosepSF/FisiChecker-Project-Back.git fisichecker
cd fisichecker
```

✅ **Ventaja:** Todo se descarga automáticamente desde GitHub

#### Método #3: FTP/SFTP con Cliente (FileZilla, WinSCP)

**Configurar cliente FTP:**
- **Host:** `taw.solucionesahora.com`
- **Puerto:** 21 (FTP) o 22 (SFTP - más seguro)
- **Usuario:** `taw`
- **Contraseña:** `nomevoyolvidar`
- **Directorio remoto:** `/home/taw/fisichecker`

**Pasos:**
1. Conecta con el cliente
2. Arrastra toda la carpeta del proyecto
3. El cliente sincroniza automáticamente

#### Método #4: Manual con File Manager (Más lento, NO recomendado)

1. En cPanel, abre **"File Manager"**
2. Navega a `/home/taw/`
3. Crea la carpeta `fisichecker` si no existe
4. Sube todos los archivos del proyecto EXCEPTO:
   - `.env` (lo crearás manualmente después)
   - `db.sqlite3`
   - `.venv/`, `venv/` (el entorno virtual)
   - `__pycache__/`
   - `*.pyc`
   - `*.log`

#### Archivos IMPORTANTES que SI debes subir (con cualquier método):
- ✅ `passenger_wsgi.py` - Entry point para Passenger
- ✅ `.htaccess` - Configuración de Apache
- ✅ `requirements.txt` - Dependencias Python
- ✅ `manage.py` - Comando Django
- ✅ `FisiChecker/` - Configuración del proyecto
- ✅ `audits/` - App principal
- ✅ Todos los demás archivos `.py` y directorios

#### Archivos que NO debes subir:
- ❌ `.env` (lo crearás en el servidor con credenciales reales)
- ❌ `db.sqlite3` (base de datos local)
- ❌ `.venv/`, `venv/` (entorno virtual)
- ❌ `__pycache__/`, `*.pyc` (archivos compilados)
- ❌ `*.log` (logs locales)
- ❌ `.git/` (opcional, solo si no usas git clone)

#### 5.2 Usando FTP/SFTP (Alternativa)
Configurar cliente FTP:
- Host: `taw.solucionesahora.com`
- Puerto: 21 (FTP) o 22 (SFTP)
- Usuario: `taw`
- Contraseña: `nomevoyolvidar`
- Directorio remoto: `/home/taw/fisichecker`

### 6. Instalar Dependencias

#### 6.1 Acceder a Terminal SSH
1. En cPanel, busca **"Terminal"** o usa SSH:
```bash
ssh taw@taw.solucionesahora.com
```

#### 6.2 Activar el Entorno Virtual
```bash
cd ~/fisichecker
source /home/taw/virtualenv/fisichecker/bin/activate
```

#### 6.3 Instalar Requirements
```bash
pip install -r requirements.txt
```

#### 6.4 Instalar Playwright (Opcional)
```bash
playwright install
# Si da error de permisos, instala solo chromium:
playwright install chromium
```

### 7. Crear archivo .env en el Servidor

Usando el File Manager o terminal, crea `/home/taw/fisichecker/.env`:

```bash
nano .env
```

Pega el contenido de tu `.env` local (con las credenciales correctas del servidor).

### 8. Ejecutar Migraciones de Django

```bash
cd ~/fisichecker
source /home/taw/virtualenv/fisichecker/bin/activate
python manage.py migrate
```

### 9. Crear Superusuario (Administrador)

```bash
python manage.py createsuperuser
```

Sigue las instrucciones para crear el usuario admin.

### 10. Recolectar Archivos Estáticos

```bash
python manage.py collectstatic --noinput
```

### 11. Configurar Permisos

```bash
chmod 755 /home/taw/fisichecker
chmod 755 /home/taw/fisichecker/passenger_wsgi.py
chmod 644 /home/taw/fisichecker/.htaccess
chmod 600 /home/taw/fisichecker/.env
```

### 12. Reiniciar la Aplicación

En cPanel, en **"Setup Python App"**:
1. Click en el icono de **"Restart"** junto a tu aplicación
2. O desde terminal:
```bash
touch /home/taw/fisichecker/tmp/restart.txt
```

## 🧪 Verificar el Deployment

### Probar la API
1. Abre tu navegador y ve a:
   - `https://taw.solucionesahora.com/api/audits/`
   
2. Deberías ver una respuesta JSON (lista vacía inicialmente)

### Acceder al Admin
1. Ve a: `https://taw.solucionesahora.com/admin/`
2. Inicia sesión con el superusuario creado

### Probar una Auditoría
```bash
curl -X POST https://taw.solucionesahora.com/api/audit/ \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.google.com", "mode": "raw"}'
```

## 🔧 Troubleshooting

### Error 500 - Internal Server Error
1. Revisa el log de errores:
```bash
tail -f ~/logs/error_log
```

2. Verifica que DEBUG=False en .env
3. Revisa que ALLOWED_HOSTS incluya tu dominio

### Error de Base de Datos
1. Verifica las credenciales en .env
2. Prueba la conexión:
```bash
python manage.py dbshell
```

### Playwright no funciona
- En cPanel compartido, Playwright puede no funcionar por limitaciones de recursos
- Usa principalmente el modo `"raw"` para auditorías
- Considera usar un VPS si necesitas modo `"rendered"` intensivo

### Los archivos estáticos no se cargan
1. Verifica STATIC_ROOT en .env
2. Re-ejecuta collectstatic:
```bash
python manage.py collectstatic --clear --noinput
```

## 📝 Mantenimiento

### Actualizar el Código
```bash
cd ~/fisichecker
source /home/taw/virtualenv/fisichecker/bin/activate
git pull  # Si usas Git
python manage.py migrate
python manage.py collectstatic --noinput
touch tmp/restart.txt
```

### Backup de Base de Datos
Desde cPanel > phpMyAdmin:
1. Selecciona la base de datos `taw_fisichecker`
2. Click en "Export"
3. Descarga el archivo SQL

O desde terminal:
```bash
mysqldump -u taw_fisichecker_user -p taw_fisichecker > backup_$(date +%Y%m%d).sql
```

### Ver Logs
```bash
# Error logs de Apache
tail -f ~/logs/error_log

# Logs de la aplicación (si configuraste logging)
tail -f ~/fisichecker/audit_auto_ai_log.txt
```

## 🔐 Seguridad Post-Deployment

### Checklist de Seguridad
- [ ] DEBUG=False en producción
- [ ] SECRET_KEY única y segura
- [ ] .env con permisos 600
- [ ] HTTPS habilitado (SSL)
- [ ] ALLOWED_HOSTS configurado correctamente
- [ ] CORS_ALLOWED_ORIGINS solo con dominios confiables
- [ ] Contraseñas de DB seguras
- [ ] Firewall configurado en cPanel
- [ ] Backups automáticos configurados

### Habilitar SSL
1. En cPanel, busca **"SSL/TLS Status"**
2. Activa "AutoSSL" para tu dominio
3. O instala certificado Let's Encrypt

## 📞 Soporte

Si encuentras problemas:
1. Revisa los logs de error
2. Verifica la configuración de .env
3. Consulta la documentación de Django y cPanel
4. Contacta al soporte de tu hosting si es necesario

---

**¡Deployment completado!** 🎉

El backend de FisiChecker ahora está corriendo en:
- **API**: https://taw.solucionesahora.com/api/
- **Admin**: https://taw.solucionesahora.com/admin/
