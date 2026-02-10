"""
Script para importar datos de fisichecker.sql a SQLite usando Django ORM
"""
import os
import sys
import django
import re
from datetime import datetime

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.models import WebsiteAudit, WebsiteAuditResult


def parse_sql_insert(line):
    """Extrae los valores de un INSERT statement"""
    # Buscar patrón: INSERT INTO `tabla` (...) VALUES (...)
    match = re.search(r'INSERT INTO `(\w+)` \([^)]+\) VALUES\s*(.+)', line, re.IGNORECASE)
    if not match:
        return None, []
    
    table = match.group(1)
    values_str = match.group(2)
    
    # Extraer tuplas de valores - maneja múltiples rows
    rows = []
    current_row = []
    in_string = False
    escape_next = False
    paren_depth = 0
    current_val = ''
    
    for char in values_str:
        if escape_next:
            current_val += char
            escape_next = False
            continue
            
        if char == '\\':
            escape_next = True
            current_val += char
            continue
            
        if char == "'" and not escape_next:
            in_string = not in_string
            current_val += char
            continue
            
        if not in_string:
            if char == '(':
                paren_depth += 1
                if paren_depth == 1:
                    continue
            elif char == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    if current_val:
                        current_row.append(current_val)
                    if current_row:
                        rows.append(current_row)
                    current_row = []
                    current_val = ''
                    continue
            elif char == ',' and paren_depth == 1:
                current_row.append(current_val)
                current_val = ''
                continue
        
        if paren_depth > 0:
            current_val += char
    
    return table, rows


def clean_value(val):
    """Limpia un valor SQL"""
    val = val.strip()
    
    # NULL
    if val.upper() == 'NULL':
        return None
    
    # String entre comillas
    if val.startswith("'") and val.endswith("'"):
        val = val[1:-1]
        # Decodificar escapes SQL
        val = val.replace("\\'", "'")
        val = val.replace("\\\"", "\"")
        val = val.replace("\\\\", "\\")
        return val
    
    # Números
    try:
        if '.' in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def import_data():
    """Importa datos del archivo SQL"""
    print("Iniciando importación de datos...")
    
    sql_file = 'fisichecker.sql'
    
    if not os.path.exists(sql_file):
        print(f"Error: No se encontró {sql_file}")
        return
    
    # Contadores
    audits_imported = 0
    results_imported = 0
    
    # Leer archivo línea por línea
    with open(sql_file, 'r', encoding='utf-8') as f:
        current_insert = ''
        
        for line in f:
            line = line.strip()
            
            # Ignorar comentarios y líneas vacías
            if not line or line.startswith('--') or line.startswith('/*') or line.startswith('*/'):
                continue
            
            # Acumular líneas de INSERT que pueden estar en múltiples líneas
            if line.upper().startswith('INSERT INTO'):
                current_insert = line
            elif current_insert:
                current_insert += ' ' + line
            
            # Si termina con ;, procesar el INSERT
            if current_insert and current_insert.endswith(';'):
                current_insert = current_insert[:-1]  # Quitar ;
                
                table, rows = parse_sql_insert(current_insert)
                
                if table == 'audits_websiteaudit' and rows:
                    for row in rows:
                        if len(row) != 11:  # Debe tener 11 columnas
                            print(f"  ⚠️  Fila con {len(row)} columnas (esperado 11), saltando...")
                            continue
                        
                        try:
                            audit = WebsiteAudit(
                                id=clean_value(row[0]),
                                url=clean_value(row[1]),
                                fetched_at=clean_value(row[2]),
                                status_code=clean_value(row[3]),
                                elapsed_ms=clean_value(row[4]),
                                page_title=clean_value(row[5]),
                                score=clean_value(row[6]),
                                results=clean_value(row[7]) or '{}',
                                rendered=bool(clean_value(row[8])),
                                ia=bool(clean_value(row[9])),
                                raw=bool(clean_value(row[10]))
                            )
                            audit.save()
                            audits_imported += 1
                            print(f"  ✓ WebsiteAudit #{audit.id}: {audit.url[:60]}")
                        except Exception as e:
                            print(f"  ✗ Error en WebsiteAudit: {e}")
                            print(f"    Row: {row[:3]}...")
                
                elif table == 'audits_websiteauditresult' and rows:
                    for row in rows:
                        if len(row) != 11:  # Debe tener 11 columnas
                            print(f"  ⚠️  Fila de resultado con {len(row)} columnas (esperado 11), saltando...")
                            continue
                        
                        try:
                            result = WebsiteAuditResult(
                                id=clean_value(row[0]),
                                code=clean_value(row[1]),
                                title=clean_value(row[2]),
                                level=clean_value(row[3]),
                                principle=clean_value(row[4]),
                                verdict=clean_value(row[5]),
                                source=clean_value(row[6]),
                                score_hint=clean_value(row[7]),
                                details=clean_value(row[8]) or '{}',
                                audit_id=clean_value(row[9]),
                                score=clean_value(row[10])
                            )
                            result.save()
                            results_imported += 1
                            
                            if results_imported % 100 == 0:
                                print(f"  ✓ {results_imported} resultados importados...")
                        except Exception as e:
                            print(f"  ✗ Error en WebsiteAuditResult: {e}")
                            print(f"    Row ID: {row[0]}, Code: {row[1]}")
                
                current_insert = ''
    
    print(f"\n{'='*60}")
    print(f"✅ Importación completada!")
    print(f"  - WebsiteAudit: {audits_imported} registros")
    print(f"  - WebsiteAuditResult: {results_imported} registros")
    print(f"{'='*60}")


if __name__ == '__main__':
    import_data()
