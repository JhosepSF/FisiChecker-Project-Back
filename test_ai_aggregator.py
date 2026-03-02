#!/usr/bin/env python
"""
Script de prueba para verificar que el PrincipleAIAggregator recibe todos los criterios en modo AI.
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.checks.criteria.base import CriterionOutcome
from audits.ai.principle_ai import PrincipleAIAggregator

def test_aggregator_modes():
    """Prueba que en modo AI se acepten todos los verdicts, pero en AUTO solo fail/partial"""
    
    # Crear outcomes de prueba
    outcomes = [
        CriterionOutcome(
            code="1.1.1", passed=True, verdict="pass", score_0_2=2,
            details={}, level="A", title="Test Pass", principle="Perceptible", source="raw"
        ),
        CriterionOutcome(
            code="1.3.1", passed=False, verdict="fail", score_0_2=0,
            details={}, level="A", title="Test Fail", principle="Perceptible", source="raw"
        ),
        CriterionOutcome(
            code="2.4.1", passed=None, verdict="partial", score_0_2=1,
            details={}, level="A", title="Test Partial", principle="Operable", source="raw"
        ),
        CriterionOutcome(
            code="3.1.1", passed=None, verdict="na", score_0_2=1,
            details={"na": True}, level="A", title="Test NA", principle="Comprensible", source="raw"
        ),
    ]
    
    print("\n" + "="*70)
    print("PRUEBA 1: Modo AUTO (solo fail/partial)")
    print("="*70)
    
    agg_auto = PrincipleAIAggregator(mode="AUTO")
    for o in outcomes:
        agg_auto.add_outcome(o)
    
    print(f"Criterios agregados: {len(agg_auto._codes)}")
    print(f"Códigos: {sorted(agg_auto._codes)}")
    print(f"Esperado: 2 (solo fail y partial)")
    
    if len(agg_auto._codes) == 2 and "1.3.1" in agg_auto._codes and "2.4.1" in agg_auto._codes:
        print("✅ CORRECTO: Solo fail/partial fueron agregados")
    else:
        print("❌ ERROR: Debería tener solo 2 códigos (fail y partial)")
    
    print("\n" + "="*70)
    print("PRUEBA 2: Modo AI (todos los criterios)")
    print("="*70)
    
    agg_ai = PrincipleAIAggregator(mode="AI")
    for o in outcomes:
        agg_ai.add_outcome(o)
    
    print(f"Criterios agregados: {len(agg_ai._codes)}")
    print(f"Códigos: {sorted(agg_ai._codes)}")
    print(f"Esperado: 4 (todos: pass, fail, partial, na)")
    
    if len(agg_ai._codes) == 4:
        print("✅ CORRECTO: Todos los criterios fueron agregados en modo AI")
    else:
        print(f"❌ ERROR: Debería tener 4 códigos, tiene {len(agg_ai._codes)}")
    
    print("\n" + "="*70)
    print("DETALLE DE ISSUES POR PRINCIPIO (modo AI):")
    print("="*70)
    
    for principle, issues in agg_ai._issues.items():
        print(f"\n{principle}: {len(issues)} issue(s)")
        for issue in issues:
            print(f"  - {issue['code']}: {issue['verdict']} ({issue['title']})")
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    test_aggregator_modes()
