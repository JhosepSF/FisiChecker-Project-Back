#!/usr/bin/env python
"""
Script simple para probar las estadísticas sin levantar el servidor.
Ejecutar: python test_stats_simple.py
"""
import os
import django
import json

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.statistics import AuditStatistics

print("=" * 70)
print("  PRUEBA RÁPIDA DE ESTADÍSTICAS")
print("=" * 70)

# 1. Estadísticas globales
print("\n📊 ESTADÍSTICAS GLOBALES:")
print("-" * 70)
global_stats = AuditStatistics.get_global_statistics()
print(json.dumps(global_stats, indent=2))

# 2. Distribución de veredictos
print("\n\n📋 DISTRIBUCIÓN DE VEREDICTOS:")
print("-" * 70)
verdict_stats = AuditStatistics.get_verdict_distribution()
for verdict, data in verdict_stats['distribution'].items():
    print(f"{verdict.upper():10} - {data['count']:5} checks ({data['percentage']:5.2f}%)")

# 3. Top 5 criterios con más fallos
print("\n\n❌ TOP 5 CRITERIOS CON MÁS FALLOS:")
print("-" * 70)
criteria_stats = AuditStatistics.get_criteria_statistics()
print(f"{'Código':10} {'Nivel':6} {'Fallos':8} {'% Fallo':10} {'Título'}")
print("-" * 70)
for criterion in criteria_stats[:5]:
    print(
        f"{criterion['code']:10} "
        f"{criterion['level']:6} "
        f"{criterion['fail_count']:8} "
        f"{criterion['fail_rate']:9.2f}% "
        f"{criterion['title'][:40]}"
    )

# 4. Estadísticas por nivel
print("\n\n📊 ESTADÍSTICAS POR NIVEL WCAG:")
print("-" * 70)
level_stats = AuditStatistics.get_level_statistics()
for level, stats in sorted(level_stats.items()):
    print(f"\nNivel {level}:")
    print(f"  Total checks: {stats['total_checks']}")
    print(f"  Pass rate: {stats['pass_rate']:.2f}%")
    print(f"  Fail rate: {stats['fail_rate']:.2f}%")
    print(f"  Average score: {stats['average_score']}")

print("\n" + "=" * 70)
print("✅ PRUEBA COMPLETADA EXITOSAMENTE")
print("=" * 70)
