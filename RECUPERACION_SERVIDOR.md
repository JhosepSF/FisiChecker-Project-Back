# Guía de recuperación y despliegue del servidor FisiChecker

sudo rm -rf /var/www/front
## 1. Conexión al servidor

```
ssh ubuntu@158.69.62.72
```

## 2. Actualizar el frontend

```
cd /var/www/front
git reset --hard
git pull
npm install
npm audit fix --force
rm -rf /var/www/front/dist
npm run build
sudo systemctl restart nginx
```

## 3. Actualizar el backend

```
cd /var/www/fisichecker
git reset --hard
git pull
```

## 4. Instalar dependencias del backend

Activa el entorno virtual:
```
source /var/www/fisichecker/venv/bin/activate
```

Instala los paquetes:
```
pip install -r /var/www/fisichecker/Back/requirements.txt
```

## 5. Configurar Nginx para servir el frontend

Editar el archivo de configuración:
```
sudo nano /etc/nginx/sites-enabled/fisichecker
```

Asegúrate de tener:
```
location /app/ {
    alias /var/www/front/dist/;
    try_files $uri $uri/ /index.html;
}
location /assets/ {
    alias /var/www/front/dist/assets/;
    try_files $uri $uri/ =404;
}
```

Reinicia Nginx:
```
sudo systemctl restart nginx
```

## 6. Iniciar Gunicorn

```
source /var/www/fisichecker/venv/bin/activate
pkill gunicorn
gunicorn FisiChecker.wsgi:application --bind unix:/var/www/fisichecker/gunicorn.sock --env DJANGO_SETTINGS_MODULE=FisiChecker.settings --daemon
sudo chown www-data:www-data /var/www/fisichecker/gunicorn.sock

sudo systemctl daemon-reload
sudo systemctl restart gunicorn
sudo systemctl status gunicorn
```

## 7. Verificar funcionamiento

- Prueba el frontend en el navegador.
- Prueba el backend con curl:
```
curl -k -X POST https://158.69.62.72/api/auth/login -H "Content-Type: application/json" -d '{"username":"nik","password":"NN123456"}'
```

## 8. Revisar logs en caso de error

- Nginx:
```
sudo tail -n 50 /var/log/nginx/error.log
```
- Gunicorn/Django:
```
sudo tail -n 50 /var/www/fisichecker/audit_auto_ai_log.txt
```

---

**Con estos pasos el servidor debe funcionar correctamente.**