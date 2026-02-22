# audits/statistics.py
from django.db.models import Count, Avg, Q, F, FloatField, Case, When
from django.db.models.functions import TruncDate
from .models import WebsiteAudit, WebsiteAuditResult
from typing import Dict, List, Any
from collections import defaultdict


class AuditStatistics:
    """
    Clase para calcular estadísticas sobre las auditorías realizadas.
    """

    @staticmethod
    def get_global_statistics() -> Dict[str, Any]:
        """
        Obtiene estadísticas globales de todas las auditorías.
        """
        total_audits = WebsiteAudit.objects.count()
        
        if total_audits == 0:
            return {
                "total_audits": 0,
                "average_score": 0,
                "total_unique_urls": 0,
                "audits_with_render": 0,
                "audits_with_ai": 0,
            }

        stats = WebsiteAudit.objects.aggregate(
            avg_score=Avg('score'),
            total_unique_urls=Count('url', distinct=True),
            audits_with_render=Count('id', filter=Q(rendered=True)),
            audits_with_ai=Count('id', filter=Q(ia=True)),
        )

        return {
            "total_audits": total_audits,
            "average_score": round(stats['avg_score'] or 0, 2),
            "total_unique_urls": stats['total_unique_urls'],
            "audits_with_render": stats['audits_with_render'],
            "audits_with_ai": stats['audits_with_ai'],
        }

    @staticmethod
    def get_verdict_distribution() -> Dict[str, Any]:
        """
        Obtiene la distribución de veredictos (pass, fail, partial, na) 
        en todas las auditorías.
        """
        distribution = WebsiteAuditResult.objects.values('verdict').annotate(
            count=Count('id')
        ).order_by('-count')

        total_results = WebsiteAuditResult.objects.count()
        
        verdict_data = {}
        for item in distribution:
            verdict = item['verdict']
            count = item['count']
            percentage = (count / total_results * 100) if total_results > 0 else 0
            verdict_data[verdict] = {
                "count": count,
                "percentage": round(percentage, 2)
            }

        return {
            "total_results": total_results,
            "distribution": verdict_data
        }

    @staticmethod
    def get_criteria_statistics() -> List[Dict[str, Any]]:
        """
        Obtiene estadísticas por criterio WCAG (código).
        Muestra qué criterios fallan más frecuentemente.
        """
        criteria_stats = WebsiteAuditResult.objects.values(
            'code', 'title', 'level', 'principle'
        ).annotate(
            total_checks=Count('id'),
            pass_count=Count('id', filter=Q(verdict='pass')),
            fail_count=Count('id', filter=Q(verdict='fail')),
            partial_count=Count('id', filter=Q(verdict='partial')),
            na_count=Count('id', filter=Q(verdict='na')),
            avg_score=Avg('score')
        ).order_by('-fail_count')

        results = []
        for stat in criteria_stats:
            total = stat['total_checks']
            results.append({
                "code": stat['code'],
                "title": stat['title'],
                "level": stat['level'],
                "principle": stat['principle'],
                "total_checks": total,
                "pass_count": stat['pass_count'],
                "fail_count": stat['fail_count'],
                "partial_count": stat['partial_count'],
                "na_count": stat['na_count'],
                "average_score": round(stat['avg_score'] or 0, 2),
                "fail_rate": round((stat['fail_count'] / total * 100) if total > 0 else 0, 2),
                "pass_rate": round((stat['pass_count'] / total * 100) if total > 0 else 0, 2),
            })

        return results

    @staticmethod
    def get_level_statistics() -> Dict[str, Any]:
        """
        Obtiene estadísticas agrupadas por nivel de conformidad (A, AA, AAA).
        """
        level_stats = WebsiteAuditResult.objects.values('level').annotate(
            total_checks=Count('id'),
            pass_count=Count('id', filter=Q(verdict='pass')),
            fail_count=Count('id', filter=Q(verdict='fail')),
            partial_count=Count('id', filter=Q(verdict='partial')),
            na_count=Count('id', filter=Q(verdict='na')),
            avg_score=Avg('score')
        )

        results = {}
        for stat in level_stats:
            level = stat['level'] or 'unknown'
            total = stat['total_checks']
            results[level] = {
                "total_checks": total,
                "pass_count": stat['pass_count'],
                "fail_count": stat['fail_count'],
                "partial_count": stat['partial_count'],
                "na_count": stat['na_count'],
                "average_score": round(stat['avg_score'] or 0, 2),
                "pass_rate": round((stat['pass_count'] / total * 100) if total > 0 else 0, 2),
                "fail_rate": round((stat['fail_count'] / total * 100) if total > 0 else 0, 2),
            }

        return results

    @staticmethod
    def get_principle_statistics() -> Dict[str, Any]:
        """
        Obtiene estadísticas agrupadas por principio WCAG.
        """
        principle_stats = WebsiteAuditResult.objects.values('principle').annotate(
            total_checks=Count('id'),
            pass_count=Count('id', filter=Q(verdict='pass')),
            fail_count=Count('id', filter=Q(verdict='fail')),
            partial_count=Count('id', filter=Q(verdict='partial')),
            na_count=Count('id', filter=Q(verdict='na')),
            avg_score=Avg('score')
        )

        results = {}
        for stat in principle_stats:
            principle = stat['principle'] or 'unknown'
            total = stat['total_checks']
            results[principle] = {
                "total_checks": total,
                "pass_count": stat['pass_count'],
                "fail_count": stat['fail_count'],
                "partial_count": stat['partial_count'],
                "na_count": stat['na_count'],
                "average_score": round(stat['avg_score'] or 0, 2),
                "pass_rate": round((stat['pass_count'] / total * 100) if total > 0 else 0, 2),
                "fail_rate": round((stat['fail_count'] / total * 100) if total > 0 else 0, 2),
            }

        return results

    @staticmethod
    def get_timeline_statistics(days: int = 30) -> List[Dict[str, Any]]:
        """
        Obtiene estadísticas de auditorías a lo largo del tiempo.
        """
        audits_by_date = WebsiteAudit.objects.annotate(
            date=TruncDate('fetched_at')
        ).values('date').annotate(
            count=Count('id'),
            avg_score=Avg('score')
        ).order_by('date')[:days]

        results = []
        for item in audits_by_date:
            results.append({
                "date": item['date'].isoformat() if item['date'] else None,
                "audits_count": item['count'],
                "average_score": round(item['avg_score'] or 0, 2)
            })

        return results

    @staticmethod
    def get_url_ranking(limit: int = 10) -> Dict[str, List[Dict[str, Any]]]:
        """
        Obtiene el ranking de URLs mejor y peor puntuadas.
        Retorna un dict con: best_urls y worst_urls.
        """
        base_qs = WebsiteAudit.objects.filter(score__isnull=False).values(
            "url", "score", "page_title", "fetched_at"
        )

        best_urls = base_qs.order_by("-score")[:limit]
        worst_urls = base_qs.order_by("score")[:limit]

        def serialize(item: Dict[str, Any]) -> Dict[str, Any]:
            score = item.get("score")
            fetched_at = item.get("fetched_at")
            return {
                "url": item.get("url"),
                "score": round(float(score), 2) if score is not None else None,
                "page_title": item.get("page_title"),
                "audited_at": fetched_at.isoformat() if fetched_at else None,
            }

        return {
            "best_urls": [serialize(item) for item in best_urls],
            "worst_urls": [serialize(item) for item in worst_urls],
        }

    @staticmethod
    def get_source_comparison() -> Dict[str, Any]:
        """
        Compara resultados entre diferentes fuentes (raw, rendered, mixed).
        """
        source_stats = WebsiteAuditResult.objects.values('source').annotate(
            total_checks=Count('id'),
            pass_count=Count('id', filter=Q(verdict='pass')),
            fail_count=Count('id', filter=Q(verdict='fail')),
            avg_score=Avg('score')
        )

        results = {}
        for stat in source_stats:
            source = stat['source']
            total = stat['total_checks']
            results[source] = {
                "total_checks": total,
                "pass_count": stat['pass_count'],
                "fail_count": stat['fail_count'],
                "average_score": round(stat['avg_score'] or 0, 2),
                "pass_rate": round((stat['pass_count'] / total * 100) if total > 0 else 0, 2),
            }

        return results

    @staticmethod
    def get_detailed_audit_statistics(audit_id: int) -> Dict[str, Any]:
        """
        Obtiene estadísticas detalladas para una auditoría específica.
        """
        try:
            audit = WebsiteAudit.objects.get(id=audit_id)
        except WebsiteAudit.DoesNotExist:
            return {"error": "Audit not found"}

        results = WebsiteAuditResult.objects.filter(audit=audit)
        
        verdict_dist = results.values('verdict').annotate(count=Count('id'))
        level_dist = results.values('level').annotate(count=Count('id'))
        principle_dist = results.values('principle').annotate(count=Count('id'))

        total_results = results.count()

        return {
            "audit_id": audit.id,
            "url": audit.url,
            "score": audit.score,
            "fetched_at": audit.fetched_at.isoformat() if audit.fetched_at else None,
            "total_criteria_checked": total_results,
            "verdict_distribution": {
                item['verdict']: {
                    "count": item['count'],
                    "percentage": round((item['count'] / total_results * 100) if total_results > 0 else 0, 2)
                }
                for item in verdict_dist
            },
            "level_distribution": {
                item['level']: item['count'] 
                for item in level_dist
            },
            "principle_distribution": {
                item['principle']: item['count'] 
                for item in principle_dist
            }
        }

    @staticmethod
    def get_accessibility_levels_hilera() -> Dict[str, Any]:
        """
        Calcula niveles de accesibilidad según metodología de Hilera et al. (2013).
        
        Fórmula: Porcentaje = (100% × Cumple + 50% × Parciales) / Total de puntos parciales
        Donde: Total de puntos parciales = Cumple + No cumple + Parciales
        
        Niveles:
        - Alto: 70-100%
        - Moderado: 50-70%
        - Deficiente: 25-50%
        - Muy deficiente: <25%
        """
        audits = WebsiteAudit.objects.all()
        
        level_counts = {
            'alto': 0,
            'moderado': 0,
            'deficiente': 0,
            'muy_deficiente': 0
        }
        
        audit_details = []
        total_percentage = 0
        valid_audits = 0
        
        for audit in audits:
            results = WebsiteAuditResult.objects.filter(audit=audit)
            
            # Contar veredictos (excluir NA)
            cumple = results.filter(verdict='pass').count()
            parciales = results.filter(verdict='partial').count()
            no_cumple = results.filter(verdict='fail').count()
            
            # Total de puntos parciales (sin contar NA)
            total_puntos_parciales = cumple + no_cumple + parciales
            na = results.filter(verdict='na').count()
            
            if total_puntos_parciales == 0:
                continue
            
            # Fórmula de Hilera et al. (2013)
            porcentaje_base = ((100 * cumple) + (50 * parciales)) / total_puntos_parciales
            # Penalización por cobertura (NA) para hacerla más estricta
            coverage = total_puntos_parciales / (total_puntos_parciales + na) if (total_puntos_parciales + na) > 0 else 1.0
            porcentaje = porcentaje_base * coverage
            
            # Clasificar en nivel
            if porcentaje >= 70:
                nivel = 'alto'
            elif porcentaje >= 50:
                nivel = 'moderado'
            elif porcentaje >= 25:
                nivel = 'deficiente'
            else:
                nivel = 'muy_deficiente'
            
            level_counts[nivel] += 1
            total_percentage += porcentaje
            valid_audits += 1
            
            audit_details.append({
                'audit_id': audit.id,
                'url': audit.url,
                'cumple': cumple,
                'parciales': parciales,
                'no_cumple': no_cumple,
                'na': na,
                'coverage': round(coverage, 4),
                'porcentaje_base': round(porcentaje_base, 2),
                'total_evaluados': total_puntos_parciales,
                'porcentaje': round(porcentaje, 2),
                'nivel': nivel
            })
        
        # Calcular porcentajes de distribución
        total_audits = valid_audits
        distribution = {}
        for nivel, count in level_counts.items():
            percentage = (count / total_audits * 100) if total_audits > 0 else 0
            distribution[nivel] = {
                'count': count,
                'percentage': round(percentage, 2)
            }
        
        # Promedio general
        average_percentage = (total_percentage / valid_audits) if valid_audits > 0 else 0
        
        return {
            'total_audits_evaluated': valid_audits,
            'average_accessibility_percentage': round(average_percentage, 2),
            'distribution': distribution,
            'summary': {
                'alto': level_counts['alto'],
                'moderado': level_counts['moderado'],
                'deficiente': level_counts['deficiente'],
                'muy_deficiente': level_counts['muy_deficiente']
            },
            'details': sorted(audit_details, key=lambda x: x['porcentaje'], reverse=True)
        }

    @staticmethod
    def get_accessibility_levels_by_wcag_level() -> Dict[str, Any]:
        """
        Calcula niveles de accesibilidad por nivel WCAG (A, AA, AAA) 
        según metodología de Hilera et al. (2013).
        """
        audits = WebsiteAudit.objects.all()
        
        wcag_levels = ['A', 'AA', 'AAA']
        results_by_wcag = {}
        
        for wcag_level in wcag_levels:
            level_counts = {
                'alto': 0,
                'moderado': 0,
                'deficiente': 0,
                'muy_deficiente': 0
            }
            
            total_percentage = 0
            valid_audits = 0
            
            for audit in audits:
                # Filtrar solo criterios del nivel WCAG específico
                results = WebsiteAuditResult.objects.filter(
                    audit=audit,
                    level=wcag_level
                )
                
                cumple = results.filter(verdict='pass').count()
                parciales = results.filter(verdict='partial').count()
                no_cumple = results.filter(verdict='fail').count()
                
                total_puntos_parciales = cumple + no_cumple + parciales
                na = results.filter(verdict='na').count()
                
                if total_puntos_parciales == 0:
                    continue
                
                # Fórmula de Hilera
                porcentaje_base = ((100 * cumple) + (50 * parciales)) / total_puntos_parciales
                coverage = total_puntos_parciales / (total_puntos_parciales + na) if (total_puntos_parciales + na) > 0 else 1.0
                porcentaje = porcentaje_base * coverage
                
                # Clasificar
                if porcentaje >= 70:
                    nivel = 'alto'
                elif porcentaje >= 50:
                    nivel = 'moderado'
                elif porcentaje >= 25:
                    nivel = 'deficiente'
                else:
                    nivel = 'muy_deficiente'
                
                level_counts[nivel] += 1
                total_percentage += porcentaje
                valid_audits += 1
            
            # Calcular distribución
            distribution = {}
            for nivel, count in level_counts.items():
                percentage = (count / valid_audits * 100) if valid_audits > 0 else 0
                distribution[nivel] = {
                    'count': count,
                    'percentage': round(percentage, 2)
                }
            
            average = (total_percentage / valid_audits) if valid_audits > 0 else 0
            
            results_by_wcag[wcag_level] = {
                'total_audits_evaluated': valid_audits,
                'average_accessibility_percentage': round(average, 2),
                'distribution': distribution,
                'summary': level_counts
            }
        
        # Promedio de los 3 niveles
        avg_of_averages = sum(
            results_by_wcag[level]['average_accessibility_percentage'] 
            for level in wcag_levels
        ) / len(wcag_levels)
        
        return {
            'average_across_levels': round(avg_of_averages, 2),
            'by_wcag_level': results_by_wcag
        }

    @staticmethod
    def get_comprehensive_report() -> Dict[str, Any]:
        """
        Genera un reporte completo con todas las estadísticas principales.
        """
        return {
            "global_statistics": AuditStatistics.get_global_statistics(),
            "verdict_distribution": AuditStatistics.get_verdict_distribution(),
            "level_statistics": AuditStatistics.get_level_statistics(),
            "principle_statistics": AuditStatistics.get_principle_statistics(),
            "source_comparison": AuditStatistics.get_source_comparison(),
            "top_failing_criteria": AuditStatistics.get_criteria_statistics()[:10],
            "url_ranking": AuditStatistics.get_url_ranking(10),
        }
