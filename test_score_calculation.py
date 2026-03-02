#!/usr/bin/env python
"""
Script de prueba para verificar el cálculo correcto del score.
Simula un resultado con 34 pass, 10 fail, 5 partial, 29 NA
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FisiChecker.settings')
django.setup()

from audits.checks.criteria.base import CriterionOutcome

# Simular resultados según los datos del usuario
# Total: 78 criterios
# Pass: 34, Fail: 10, Partial: 5, NA: 29

def test_score_calculation():
    outcomes = []
    
    # Simulamos distribución por nivel (basado en WCAG 2.1)
    # A: 30 total (15 evaluados, 15 NA)
    # AA: 20 total (8 evaluados, 12 NA)  
    # AAA: 28 total (26 evaluados, 2 NA) - pero deberían excluirse si SCORE_INCLUDE_AAA=False
    
    # Nivel A (15 evaluados de 30)
    for i in range(8):  # 8 pass
        outcomes.append(CriterionOutcome(
            code=f"A_{i}", passed=True, verdict="pass", score_0_2=2, 
            details={}, level="A", title="Test", principle="P1", source="raw"
        ))
    for i in range(4):  # 4 fail
        outcomes.append(CriterionOutcome(
            code=f"A_fail_{i}", passed=False, verdict="fail", score_0_2=0,
            details={}, level="A", title="Test", principle="P1", source="raw"
        ))
    for i in range(3):  # 3 partial
        outcomes.append(CriterionOutcome(
            code=f"A_partial_{i}", passed=None, verdict="partial", score_0_2=1,
            details={}, level="A", title="Test", principle="P1", source="raw"
        ))
    for i in range(15):  # 15 NA
        outcomes.append(CriterionOutcome(
            code=f"A_na_{i}", passed=None, verdict="na", score_0_2=1,
            details={"na": True}, level="A", title="Test", principle="P1", source="raw"
        ))
    
    # Nivel AA (8 evaluados de 20)
    for i in range(5):  # 5 pass
        outcomes.append(CriterionOutcome(
            code=f"AA_{i}", passed=True, verdict="pass", score_0_2=2,
            details={}, level="AA", title="Test", principle="P2", source="raw"
        ))
    for i in range(2):  # 2 fail
        outcomes.append(CriterionOutcome(
            code=f"AA_fail_{i}", passed=False, verdict="fail", score_0_2=0,
            details={}, level="AA", title="Test", principle="P2", source="raw"
        ))
    for i in range(1):  # 1 partial
        outcomes.append(CriterionOutcome(
            code=f"AA_partial_{i}", passed=None, verdict="partial", score_0_2=1,
            details={}, level="AA", title="Test", principle="P2", source="raw"
        ))
    for i in range(12):  # 12 NA
        outcomes.append(CriterionOutcome(
            code=f"AA_na_{i}", passed=None, verdict="na", score_0_2=1,
            details={"na": True}, level="AA", title="Test", principle="P2", source="raw"
        ))
    
    # Nivel AAA (26 evaluados de 28) - pero se excluyen si SCORE_INCLUDE_AAA=False
    for i in range(21):  # 21 pass
        outcomes.append(CriterionOutcome(
            code=f"AAA_{i}", passed=True, verdict="pass", score_0_2=2,
            details={}, level="AAA", title="Test", principle="P3", source="raw"
        ))
    for i in range(4):  # 4 fail
        outcomes.append(CriterionOutcome(
            code=f"AAA_fail_{i}", passed=False, verdict="fail", score_0_2=0,
            details={}, level="AAA", title="Test", principle="P3", source="raw"
        ))
    for i in range(1):  # 1 partial
        outcomes.append(CriterionOutcome(
            code=f"AAA_partial_{i}", passed=None, verdict="partial", score_0_2=1,
            details={}, level="AAA", title="Test", principle="P3", source="raw"
        ))
    for i in range(2):  # 2 NA
        outcomes.append(CriterionOutcome(
            code=f"AAA_na_{i}", passed=None, verdict="na", score_0_2=1,
            details={"na": True}, level="AAA", title="Test", principle="P3", source="raw"
        ))
    
    # Importar función de cálculo
    from audits.audit import _compute_score, SCORE_INCLUDE_AAA, STRICT_COVERAGE_PENALTY
    
    print(f"\n{'='*70}")
    print(f"CONFIGURACIÓN:")
    print(f"  SCORE_INCLUDE_AAA = {SCORE_INCLUDE_AAA}")
    print(f"  STRICT_COVERAGE_PENALTY = {STRICT_COVERAGE_PENALTY}")
    print(f"{'='*70}\n")
    
    print(f"CRITERIOS SIMULADOS:")
    print(f"  Total: {len(outcomes)}")
    print(f"  A: 30 (15 evaluados: 8 pass, 4 fail, 3 partial + 15 NA)")
    print(f"  AA: 20 (8 evaluados: 5 pass, 2 fail, 1 partial + 12 NA)")
    print(f"  AAA: 28 (26 evaluados: 21 pass, 4 fail, 1 partial + 2 NA)")
    print()
    
    # Calcular score
    score, breakdown = _compute_score(outcomes)
    
    print(f"RESULTADOS DEL CÁLCULO:")
    print(f"  Score final: {score} ({score*100:.1f}%)" if score else "  Score final: None")
    print(f"\nBreakdown por nivel:")
    for level in ["A", "AA", "AAA"]:
        data = breakdown.get(level, {})
        if isinstance(data, dict):
            print(f"  {level}: {data.get('passed', 0)}/{data.get('total', 0)} pass")
    
    if isinstance(breakdown.get("_coverage"), (int, float)):
        print(f"\n  Cobertura: {breakdown['_coverage']:.2%}")
    if isinstance(breakdown.get("_base_score"), (int, float)):
        print(f"  Score base: {breakdown['_base_score']:.4f} ({breakdown['_base_score']*100:.1f}%)")
    
    print(f"\n{'='*70}")
    
    # Verificaciones
    if SCORE_INCLUDE_AAA == False:
        print("\n✓ CORRECTO: AAA debe excluirse del cálculo")
        # Solo A+AA = 50 criterios, 23 evaluados (15+8)
        expected_evaluated = 15 + 8  # 23
        expected_total = 30 + 20  # 50
        expected_coverage = expected_evaluated / expected_total  # 0.46
        
        # Score base: (8+5)*1.0 + (3+1)*0.5 + (4+2)*0.0 = 13 + 2 + 0 = 15 / 23 = 0.652
        # Usando score_0_2/2: (8*2+3*1+4*0)/2 + (5*2+1*1+2*0)/2 = 19/2 + 11/2 = 9.5 + 5.5 = 15 / 23
        pass_points = (8 * 1.0) + (5 * 1.0)  # 13 pass
        partial_points = (3 * 0.5) + (1 * 0.5)  # 2 partial (score_0_2=1 → 0.5)
        expected_base = (pass_points + partial_points) / expected_evaluated
        expected_final = expected_base * expected_coverage if STRICT_COVERAGE_PENALTY else expected_base
        
        print(f"  Evaluados esperados: {expected_evaluated} (A+AA solamente)")
        print(f"  Total esperado: {expected_total}")
        print(f"  Cobertura esperada: {expected_coverage:.2%}")
        print(f"  Score base esperado: {expected_base:.4f} ({expected_base*100:.1f}%)")
        print(f"  Score final esperado: {expected_final:.4f} ({expected_final*100:.1f}%)")
        
        if score and abs(score - expected_final) < 0.01:
            print(f"\n✅ SCORE CORRECTO!")
        else:
            print(f"\n❌ ERROR: Score {score} != {expected_final}")
    
    print(f"{'='*70}\n")

if __name__ == "__main__":
    test_score_calculation()
