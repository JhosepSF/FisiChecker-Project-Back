#!/usr/bin/env python
"""
Script de ejemplo para probar los endpoints de estadísticas.
Ejecutar desde el directorio Back/:
    python test_statistics.py
"""

import requests
import json
from typing import Dict, Any

API_BASE_URL = "http://localhost:8000/api"


def print_section(title: str):
    """Imprime un separador visual para las secciones."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_json(data: Dict[str, Any], indent: int = 2):
    """Imprime datos JSON de forma legible."""
    print(json.dumps(data, indent=indent, ensure_ascii=False))


def test_global_statistics():
    """Prueba el endpoint de estadísticas globales."""
    print_section("ESTADÍSTICAS GLOBALES")
    
    response = requests.get(f"{API_BASE_URL}/statistics/global/")
    if response.status_code == 200:
        data = response.json()
        print_json(data)
        
        print("\n📊 Resumen:")
        print(f"  • Total de auditorías: {data['total_audits']}")
        print(f"  • Score promedio: {data['average_score']}")
        print(f"  • URLs únicas auditadas: {data['total_unique_urls']}")
        print(f"  • Auditorías con renderizado: {data['audits_with_render']}")
        print(f"  • Auditorías con IA: {data['audits_with_ai']}")
    else:
        print(f"❌ Error: {response.status_code}")


def test_verdict_distribution():
    """Prueba el endpoint de distribución de veredictos."""
    print_section("DISTRIBUCIÓN DE VEREDICTOS")
    
    response = requests.get(f"{API_BASE_URL}/statistics/verdicts/")
    if response.status_code == 200:
        data = response.json()
        print(f"Total de resultados: {data['total_results']}\n")
        
        for verdict, stats in data['distribution'].items():
            print(f"{verdict.upper():10} - {stats['count']:5} ({stats['percentage']:5.2f}%)")
    else:
        print(f"❌ Error: {response.status_code}")


def test_criteria_statistics():
    """Prueba el endpoint de estadísticas por criterio."""
    print_section("TOP 10 CRITERIOS CON MÁS FALLOS")
    
    response = requests.get(f"{API_BASE_URL}/statistics/criteria/")
    if response.status_code == 200:
        data = response.json()
        top_10 = data[:10]
        
        print(f"{'Código':10} {'Nivel':6} {'Fallos':8} {'% Fallo':10} {'Título'}")
        print("-" * 80)
        
        for criterion in top_10:
            print(
                f"{criterion['code']:10} "
                f"{criterion['level']:6} "
                f"{criterion['fail_count']:8} "
                f"{criterion['fail_rate']:9.2f}% "
                f"{criterion['title'][:40]}"
            )
    else:
        print(f"❌ Error: {response.status_code}")


def test_level_statistics():
    """Prueba el endpoint de estadísticas por nivel."""
    print_section("ESTADÍSTICAS POR NIVEL DE CONFORMIDAD")
    
    response = requests.get(f"{API_BASE_URL}/statistics/levels/")
    if response.status_code == 200:
        data = response.json()
        
        for level, stats in sorted(data.items()):
            print(f"\nNivel {level}:")
            print(f"  Total checks: {stats['total_checks']}")
            print(f"  Pass rate: {stats['pass_rate']:.2f}%")
            print(f"  Fail rate: {stats['fail_rate']:.2f}%")
            print(f"  Average score: {stats['average_score']}")
    else:
        print(f"❌ Error: {response.status_code}")


def test_principle_statistics():
    """Prueba el endpoint de estadísticas por principio."""
    print_section("ESTADÍSTICAS POR PRINCIPIO WCAG")
    
    response = requests.get(f"{API_BASE_URL}/statistics/principles/")
    if response.status_code == 200:
        data = response.json()
        
        for principle, stats in data.items():
            print(f"\n{principle}:")
            print(f"  Total checks: {stats['total_checks']}")
            print(f"  Pass: {stats['pass_count']} ({stats['pass_rate']:.2f}%)")
            print(f"  Fail: {stats['fail_count']} ({stats['fail_rate']:.2f}%)")
            print(f"  Average score: {stats['average_score']}")
    else:
        print(f"❌ Error: {response.status_code}")


def test_url_ranking():
    """Prueba el endpoint de ranking de URLs."""
    print_section("RANKING DE URLs")
    
    response = requests.get(f"{API_BASE_URL}/statistics/ranking/?limit=5")
    if response.status_code == 200:
        data = response.json()
        
        print("🏆 MEJORES URLs:")
        for i, url_data in enumerate(data['best_urls'], 1):
            print(f"\n{i}. {url_data['url']}")
            print(f"   Score: {url_data['score']}")
            print(f"   Título: {url_data['page_title']}")
        
        print("\n\n⚠️  PEORES URLs:")
        for i, url_data in enumerate(data['worst_urls'], 1):
            print(f"\n{i}. {url_data['url']}")
            print(f"   Score: {url_data['score']}")
            print(f"   Título: {url_data['page_title']}")
    else:
        print(f"❌ Error: {response.status_code}")


def test_source_comparison():
    """Prueba el endpoint de comparación por fuente."""
    print_section("COMPARACIÓN POR FUENTE (raw, rendered, mixed)")
    
    response = requests.get(f"{API_BASE_URL}/statistics/sources/")
    if response.status_code == 200:
        data = response.json()
        
        print(f"{'Fuente':15} {'Total':8} {'Pass':8} {'Fail':8} {'% Pass':10} {'Avg Score':10}")
        print("-" * 80)
        
        for source, stats in data.items():
            print(
                f"{source:15} "
                f"{stats['total_checks']:8} "
                f"{stats['pass_count']:8} "
                f"{stats['fail_count']:8} "
                f"{stats['pass_rate']:9.2f}% "
                f"{stats['average_score']:10.2f}"
            )
    else:
        print(f"❌ Error: {response.status_code}")


def test_timeline():
    """Prueba el endpoint de timeline."""
    print_section("TIMELINE DE AUDITORÍAS (últimos 7 días)")
    
    response = requests.get(f"{API_BASE_URL}/statistics/timeline/?days=7")
    if response.status_code == 200:
        data = response.json()
        
        print(f"{'Fecha':12} {'Auditorías':12} {'Score Promedio':15}")
        print("-" * 50)
        
        for item in data:
            print(
                f"{item['date']:12} "
                f"{item['audits_count']:12} "
                f"{item['average_score']:15.2f}"
            )
    else:
        print(f"❌ Error: {response.status_code}")


def test_audit_detail(audit_id: int = 1):
    """Prueba el endpoint de detalle de auditoría."""
    print_section(f"DETALLE DE AUDITORÍA #{audit_id}")
    
    response = requests.get(f"{API_BASE_URL}/statistics/audit/{audit_id}/")
    if response.status_code == 200:
        data = response.json()
        
        if "error" not in data:
            print(f"URL: {data['url']}")
            print(f"Score: {data['score']}")
            print(f"Fecha: {data['fetched_at']}")
            print(f"\nTotal de criterios evaluados: {data['total_criteria_checked']}")
            
            print("\n📊 Distribución de veredictos:")
            for verdict, stats in data['verdict_distribution'].items():
                print(f"  {verdict}: {stats['count']} ({stats['percentage']}%)")
            
            print("\n📋 Distribución por nivel:")
            for level, count in data['level_distribution'].items():
                print(f"  Nivel {level}: {count}")
        else:
            print(data['error'])
    else:
        print(f"❌ Error: {response.status_code}")


def test_comprehensive_report():
    """Prueba el endpoint de reporte completo."""
    print_section("REPORTE COMPLETO")
    
    response = requests.get(f"{API_BASE_URL}/statistics/report/")
    if response.status_code == 200:
        data = response.json()
        
        print("✅ Reporte generado exitosamente")
        print(f"\nSecciones disponibles:")
        for key in data.keys():
            print(f"  • {key}")
        
        print(f"\n📊 Resumen rápido:")
        print(f"  Total auditorías: {data['global_statistics']['total_audits']}")
        print(f"  Score promedio: {data['global_statistics']['average_score']}")
        print(f"  Criterios con más fallos: {len(data['top_failing_criteria'])}")
    else:
        print(f"❌ Error: {response.status_code}")


def main():
    """Ejecuta todas las pruebas."""
    print("\n" + "🔬 PROBANDO ENDPOINTS DE ESTADÍSTICAS ".center(80, "="))
    
    try:
        # Prueba cada endpoint
        test_global_statistics()
        test_verdict_distribution()
        test_criteria_statistics()
        test_level_statistics()
        test_principle_statistics()
        test_url_ranking()
        test_source_comparison()
        test_timeline()
        
        # Prueba detalle de auditoría (si existe una con ID=1)
        test_audit_detail(1)
        
        # Reporte completo
        test_comprehensive_report()
        
        print("\n" + "✅ TODAS LAS PRUEBAS COMPLETADAS ".center(80, "=") + "\n")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: No se pudo conectar al servidor.")
        print("Asegúrate de que el servidor Django esté corriendo en http://localhost:8000")
    except Exception as e:
        print(f"\n❌ ERROR inesperado: {e}")


if __name__ == "__main__":
    main()
