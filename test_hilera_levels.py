#!/usr/bin/env python
"""
Script para probar el cálculo de niveles de accesibilidad según Hilera et al. (2013)
Ejecutar: python test_hilera_levels.py
"""
import os
import django
import matplotlib.pyplot as plt
import json

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.statistics import AuditStatistics

print("=" * 80)
print("  ANÁLISIS DE NIVELES DE ACCESIBILIDAD - METODOLOGÍA HILERA ET AL. (2013)")
print("=" * 80)

# 1. Obtener niveles generales
print("\n📊 NIVELES DE ACCESIBILIDAD GENERALES:")
print("-" * 80)
data = AuditStatistics.get_accessibility_levels_hilera()

print(f"\nTotal de sitios evaluados: {data['total_audits_evaluated']}")
print(f"Porcentaje promedio de accesibilidad: {data['average_accessibility_percentage']}%")

print("\n📊 Distribución por Nivel:")
distribution = data['distribution']
for nivel, stats in distribution.items():
    nivel_nombre = nivel.replace('_', ' ').title()
    print(f"  {nivel_nombre:20} - {stats['count']:3} sitios ({stats['percentage']:5.2f}%)")

# 2. Análisis por nivel WCAG
print("\n\n📊 ANÁLISIS POR NIVEL WCAG (A, AA, AAA):")
print("-" * 80)
data_wcag = AuditStatistics.get_accessibility_levels_by_wcag_level()

print(f"\n⭐ Promedio de cumplimiento de los 3 niveles WCAG: {data_wcag['average_across_levels']}%")

for wcag_level, stats in data_wcag['by_wcag_level'].items():
    print(f"\n🔹 Nivel {wcag_level}:")
    print(f"   Sitios evaluados: {stats['total_audits_evaluated']}")
    print(f"   Porcentaje promedio: {stats['average_accessibility_percentage']}%")
    print(f"   Distribución:")
    for nivel, data_nivel in stats['distribution'].items():
        nivel_nombre = nivel.replace('_', ' ').title()
        print(f"      - {nivel_nombre:15}: {data_nivel['count']:3} ({data_nivel['percentage']:5.2f}%)")

# 3. Top 5 sitios mejor puntuados
print("\n\n🏆 TOP 5 SITIOS CON MEJOR ACCESIBILIDAD:")
print("-" * 80)
top_5 = data['details'][:5]
for i, site in enumerate(top_5, 1):
    nivel_nombre = site['nivel'].replace('_', ' ').title()
    print(f"{i}. {site['url'][:60]}")
    print(f"   Porcentaje: {site['porcentaje']}% - Nivel: {nivel_nombre}")
    print(f"   Cumple: {site['cumple']} | Parciales: {site['parciales']} | No cumple: {site['no_cumple']}")

# 4. Top 5 sitios peor puntuados
print("\n\n⚠️  TOP 5 SITIOS CON PEOR ACCESIBILIDAD:")
print("-" * 80)
bottom_5 = data['details'][-5:]
for i, site in enumerate(bottom_5, 1):
    nivel_nombre = site['nivel'].replace('_', ' ').title()
    print(f"{i}. {site['url'][:60]}")
    print(f"   Porcentaje: {site['porcentaje']}% - Nivel: {nivel_nombre}")
    print(f"   Cumple: {site['cumple']} | Parciales: {site['parciales']} | No cumple: {site['no_cumple']}")

# 5. Crear gráfico circular
print("\n\n📊 Generando gráfico circular...")

try:
    labels = ['Alta', 'Moderada', 'Deficiente', 'Muy deficiente']
    sizes = [
        distribution['alto']['percentage'],
        distribution['moderado']['percentage'],
        distribution['deficiente']['percentage'],
        distribution['muy_deficiente']['percentage']
    ]
    
    # Colores similares a la imagen
    colors = ['#93C5FD', '#FDB099', '#D1D5DB', '#FDE68A']
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    wedges, texts, autotexts = ax.pie(
        sizes, 
        labels=labels, 
        colors=colors,
        autopct='%1.0f%%',
        startangle=90,
        textprops={'fontsize': 14, 'weight': 'bold'},
        wedgeprops={'edgecolor': 'white', 'linewidth': 2}
    )
    
    for autotext in autotexts:
        autotext.set_color('black')
        autotext.set_fontsize(13)
    
    plt.title('Niveles de Accesibilidad', fontsize=18, weight='bold', pad=20)
    plt.legend(labels, loc="upper right", bbox_to_anchor=(1.2, 1), fontsize=11)
    ax.axis('equal')
    
    # Guardar gráfico
    plt.tight_layout()
    plt.savefig('niveles_accesibilidad.png', dpi=300, bbox_inches='tight')
    print("✅ Gráfico guardado en 'niveles_accesibilidad.png'")
    
    # Mostrar gráfico
    plt.show()
    
except Exception as e:
    print(f"⚠️ No se pudo generar el gráfico: {e}")
    print("   (Esto es normal si no tienes interfaz gráfica disponible)")

# 6. Guardar datos en JSON
print("\n💾 Guardando datos en JSON...")
output_data = {
    'niveles_generales': data,
    'niveles_por_wcag': data_wcag
}

with open('niveles_accesibilidad.json', 'w', encoding='utf-8') as f:
    json.dump(output_data, f, indent=2, ensure_ascii=False)

print("✅ Datos guardados en 'niveles_accesibilidad.json'")

# 7. Resumen final
print("\n" + "=" * 80)
print("📋 RESUMEN EJECUTIVO")
print("=" * 80)
print(f"\n✅ {data['total_audits_evaluated']} sitios web evaluados")
print(f"📊 Porcentaje promedio general: {data['average_accessibility_percentage']}%")
print(f"📈 Promedio de los 3 niveles WCAG: {data_wcag['average_across_levels']}%")

print("\n💡 Interpretación:")
avg = data['average_accessibility_percentage']
if avg >= 70:
    print("   ✅ NIVEL ALTO - La mayoría de sitios cumplen con los requisitos de accesibilidad")
elif avg >= 50:
    print("   ⚠️  NIVEL MODERADO - Los sitios necesitan mejoras en accesibilidad")
elif avg >= 25:
    print("   ⚠️  NIVEL DEFICIENTE - Se requieren correcciones significativas")
else:
    print("   ❌ NIVEL MUY DEFICIENTE - Se necesitan mejoras urgentes en accesibilidad")

print("\n🔬 Metodología aplicada: Hilera et al. (2013)")
print("📐 Fórmula: (100% × Cumple + 50% × Parciales) / Total de puntos parciales")
print("=" * 80)
