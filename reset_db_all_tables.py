#!/usr/bin/env python
"""
Limpia todas las tablas de la BD y reinicia AUTO_INCREMENT.
Requiere pymysql instalado.
"""
import pymysql

DB_NAME = "fisichecker"

conn = pymysql.connect(
    host="127.0.0.1",
    user="root",
    password="",
    database=DB_NAME,
    charset="utf8mb4",
    autocommit=True,
)

try:
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS=0;")
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (DB_NAME,),
        )
        tables = [row[0] for row in cur.fetchall()]
        for t in tables:
            cur.execute(f"TRUNCATE TABLE `{t}`;")
        cur.execute("SET FOREIGN_KEY_CHECKS=1;")
        print(f"✅ Tablas limpiadas: {len(tables)}")
finally:
    conn.close()
