#!/usr/bin/env python
"""
Prueba rápida de auditoría con los cambios aplicados
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.audit import scrape_and_audit

# URL de prueba (página con problemas de accesibilidad conocidos)
test_url = "https://www.w3.org/"

print("=" * 80)
print("  PRUEBA DE AUDITORIA CON NUEVA LOGICA ESTRICTA")
print("=" * 80)
print(f"\nURL: {test_url}")
print("\nEjecutando auditoria completa...")
print("-" * 80)

try:
    result = scrape_and_audit(test_url)
    
    # Debug: ver estructura
    print(f"\nKeys en resultado: {list(result.keys())}")
    
    # Obtener outcomes
    outcomes = result.get('criterion_results', [])
    
    # Contar veredictos
    cumple = 0
    parcial = 0
    no_cumple = 0
    na = 0
    
    for criterion in outcomes:
        verdict = criterion.get('verdict', '').lower()
        if verdict == 'pass':
            cumple += 1
        elif verdict == 'partial':
            parcial += 1
        elif verdict == 'fail':
            no_cumple += 1
        elif verdict == 'na':
            na += 1
    
    total_evaluated = cumple + parcial + no_cumple
    
    # Calcular score Hilera
    if total_evaluated > 0:
        hilera_score = ((100 * cumple) + (50 * parcial)) / total_evaluated
    else:
        hilera_score = 0
    
    print("\nRESULTADOS:")
    print("-" * 80)
    print(f"{'CUMPLE (PASS):':<25} {cumple:>5}")
    print(f"{'PARCIAL:':<25} {parcial:>5}")
    print(f"{'NO CUMPLE (FAIL):':<25} {no_cumple:>5}")
    print(f"{'NO APLICABLE (NA):':<25} {na:>5}")
    print("-" * 80)
    print(f"{'Total evaluados:':<25} {total_evaluated:>5}")
    print(f"{'Total criterios:':<25} {cumple + parcial + no_cumple + na:>5}")
    print("-" * 80)
    print(f"{'SCORE HILERA:':<25} {hilera_score:>5.2f}%")
    print("=" * 80)
    
    # Mostrar algunos criterios críticos
    print("\nCRITERIOS CRITICOS MODIFICADOS (15 total):")
    print("-" * 80)
    critical_codes = ['1.1.1', '1.2.2', '1.3.1', '2.1.1', '2.4.4', '2.4.7', '2.5.3', '2.5.5',
                      '3.3.1', '3.3.2', '3.3.3', '3.3.4', '3.3.5', '3.3.6', '4.1.2', '4.1.3']
    
    for criterion in outcomes:
        code = criterion.get('code', '')
        if code in critical_codes:
            verdict = criterion.get('verdict', '').upper()
            details = criterion.get('details', {})
            ratio = details.get('ratio', 'N/A')
            if isinstance(ratio, float):
                ratio = f"{ratio:.2%}"
            
            print(f"\n{code} - {criterion.get('title', 'Sin título')}")
            print(f"  Veredicto: {verdict}")
            print(f"  Ratio: {ratio}")
            if 'applicable' in details:
                print(f"  Aplicables: {details.get('applicable', 0)}")
            if 'violations' in details:
                print(f"  Violaciones: {details.get('violations', 0)}")
            if 'missing_alt' in details:
                print(f"  Missing alt: {details.get('missing_alt', 0)}")
            if 'missing_label' in details:
                print(f"  Missing label: {details.get('missing_label', 0)}")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
