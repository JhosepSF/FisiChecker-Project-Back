#!/usr/bin/env python
"""
Script de verificación rápida del sistema de estadísticas.
Ejecutar: python check_statistics.py
"""

import sys
import os

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_imports():
    """Verifica que todos los módulos necesarios estén importables."""
    print("🔍 Verificando imports...")
    
    try:
        from audits.statistics import AuditStatistics
        print("  ✅ audits.statistics importado correctamente")
    except ImportError as e:
        print(f"  ❌ Error importando audits.statistics: {e}")
        return False
    
    try:
        from audits import views
        print("  ✅ audits.views importado correctamente")
    except ImportError as e:
        print(f"  ❌ Error importando audits.views: {e}")
        return False
    
    try:
        from FisiChecker import urls
        print("  ✅ FisiChecker.urls importado correctamente")
    except ImportError as e:
        print(f"  ❌ Error importando FisiChecker.urls: {e}")
        return False
    
    return True


def check_views():
    """Verifica que todas las vistas de estadísticas existan."""
    print("\n🔍 Verificando vistas de estadísticas...")
    
    from audits import views
    
    required_views = [
        'StatisticsGlobalView',
        'StatisticsVerdictDistributionView',
        'StatisticsCriteriaView',
        'StatisticsLevelView',
        'StatisticsPrincipleView',
        'StatisticsTimelineView',
        'StatisticsURLRankingView',
        'StatisticsSourceComparisonView',
        'StatisticsAuditDetailView',
        'StatisticsComprehensiveReportView',
    ]
    
    all_exist = True
    for view_name in required_views:
        if hasattr(views, view_name):
            print(f"  ✅ {view_name}")
        else:
            print(f"  ❌ {view_name} NO encontrada")
            all_exist = False
    
    return all_exist


def check_urls():
    """Verifica que las URLs estén configuradas."""
    print("\n🔍 Verificando configuración de URLs...")
    
    from FisiChecker.urls import urlpatterns
    
    statistics_urls = [
        '/api/statistics/global/',
        '/api/statistics/verdicts/',
        '/api/statistics/criteria/',
        '/api/statistics/levels/',
        '/api/statistics/principles/',
        '/api/statistics/timeline/',
        '/api/statistics/ranking/',
        '/api/statistics/sources/',
        '/api/statistics/report/',
    ]
    
    # Extraer patrones de URL
    configured_patterns = [str(pattern.pattern) for pattern in urlpatterns]
    
    all_configured = True
    for stat_url in statistics_urls:
        # Buscar si existe un patrón similar
        found = any(stat_url.replace('/', '') in pattern for pattern in configured_patterns)
        if found:
            print(f"  ✅ {stat_url}")
        else:
            print(f"  ⚠️  {stat_url} (revisar)")
    
    return all_configured


def check_statistics_methods():
    """Verifica que todos los métodos de estadísticas existan."""
    print("\n🔍 Verificando métodos de AuditStatistics...")
    
    from audits.statistics import AuditStatistics
    
    required_methods = [
        'get_global_statistics',
        'get_verdict_distribution',
        'get_criteria_statistics',
        'get_level_statistics',
        'get_principle_statistics',
        'get_timeline_statistics',
        'get_url_ranking',
        'get_source_comparison',
        'get_detailed_audit_statistics',
        'get_comprehensive_report',
    ]
    
    all_exist = True
    for method_name in required_methods:
        if hasattr(AuditStatistics, method_name):
            print(f"  ✅ {method_name}")
        else:
            print(f"  ❌ {method_name} NO encontrado")
            all_exist = False
    
    return all_exist


def check_database():
    """Verifica la conexión a la base de datos y los modelos."""
    print("\n🔍 Verificando base de datos...")
    
    try:
        from audits.models import WebsiteAudit, WebsiteAuditResult
        
        # Intentar contar registros
        audit_count = WebsiteAudit.objects.count()
        result_count = WebsiteAuditResult.objects.count()
        
        print(f"  ✅ Conexión a BD exitosa")
        print(f"  ℹ️  WebsiteAudit: {audit_count} registros")
        print(f"  ℹ️  WebsiteAuditResult: {result_count} registros")
        
        if audit_count == 0:
            print(f"  ⚠️  No hay auditorías en la base de datos")
            print(f"     Las estadísticas estarán vacías hasta que se realicen auditorías.")
        
        return True
    except Exception as e:
        print(f"  ❌ Error con la base de datos: {e}")
        print(f"     Asegúrate de ejecutar: python manage.py migrate")
        return False


def main():
    """Ejecuta todas las verificaciones."""
    print("\n" + "="*60)
    print("  VERIFICACIÓN DEL SISTEMA DE ESTADÍSTICAS")
    print("="*60 + "\n")
    
    # Django setup
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
        django.setup()
        print("✅ Django inicializado correctamente\n")
    except Exception as e:
        print(f"❌ Error inicializando Django: {e}\n")
        print("Asegúrate de ejecutar este script desde el directorio Back/\n")
        return
    
    # Ejecutar verificaciones
    checks = [
        check_imports(),
        check_statistics_methods(),
        check_views(),
        check_urls(),
        check_database(),
    ]
    
    # Resumen
    print("\n" + "="*60)
    if all(checks):
        print("✅ TODAS LAS VERIFICACIONES PASARON")
        print("\nEl sistema de estadísticas está correctamente instalado.")
        print("\nPróximos pasos:")
        print("  1. Iniciar el servidor: python manage.py runserver")
        print("  2. Probar endpoints: python test_statistics.py")
        print("  3. Ver documentación: STATISTICS_README.md")
    else:
        print("⚠️  ALGUNAS VERIFICACIONES FALLARON")
        print("\nRevisa los errores anteriores y corrige los problemas.")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
