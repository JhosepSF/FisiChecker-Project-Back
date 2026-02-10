# Módulo de Estadísticas - FisiChecker

Este módulo proporciona endpoints para obtener estadísticas detalladas sobre las auditorías de accesibilidad realizadas.

## Endpoints Disponibles

### 1. Estadísticas Globales
**GET** `/api/statistics/global/`

Retorna estadísticas generales de todas las auditorías.

**Respuesta:**
```json
{
  "total_audits": 150,
  "average_score": 75.5,
  "total_unique_urls": 45,
  "audits_with_render": 80,
  "audits_with_ai": 30
}
```

---

### 2. Distribución de Veredictos
**GET** `/api/statistics/verdicts/`

Muestra la distribución de todos los veredictos (pass, fail, partial, na).

**Respuesta:**
```json
{
  "total_results": 5000,
  "distribution": {
    "pass": {
      "count": 2500,
      "percentage": 50.0
    },
    "fail": {
      "count": 1500,
      "percentage": 30.0
    },
    "partial": {
      "count": 500,
      "percentage": 10.0
    },
    "na": {
      "count": 500,
      "percentage": 10.0
    }
  }
}
```

---

### 3. Estadísticas por Criterio WCAG
**GET** `/api/statistics/criteria/`

Retorna estadísticas detalladas por cada criterio WCAG, ordenadas por el número de fallos.

**Respuesta:**
```json
[
  {
    "code": "1.4.3",
    "title": "Contrast (Minimum)",
    "level": "AA",
    "principle": "Perceivable",
    "total_checks": 100,
    "pass_count": 45,
    "fail_count": 40,
    "partial_count": 10,
    "na_count": 5,
    "average_score": 1.2,
    "fail_rate": 40.0,
    "pass_rate": 45.0
  },
  ...
]
```

---

### 4. Estadísticas por Nivel de Conformidad
**GET** `/api/statistics/levels/`

Agrupa estadísticas por nivel de conformidad WCAG (A, AA, AAA).

**Respuesta:**
```json
{
  "A": {
    "total_checks": 1500,
    "pass_count": 800,
    "fail_count": 500,
    "partial_count": 150,
    "na_count": 50,
    "average_score": 1.5,
    "pass_rate": 53.33,
    "fail_rate": 33.33
  },
  "AA": {
    ...
  },
  "AAA": {
    ...
  }
}
```

---

### 5. Estadísticas por Principio WCAG
**GET** `/api/statistics/principles/`

Agrupa estadísticas por principio WCAG (Perceivable, Operable, Understandable, Robust).

**Respuesta:**
```json
{
  "Perceivable": {
    "total_checks": 2000,
    "pass_count": 1000,
    "fail_count": 700,
    "partial_count": 200,
    "na_count": 100,
    "average_score": 1.4,
    "pass_rate": 50.0,
    "fail_rate": 35.0
  },
  ...
}
```

---

### 6. Timeline de Auditorías
**GET** `/api/statistics/timeline/?days=30`

Muestra la evolución de auditorías en el tiempo.

**Parámetros:**
- `days` (opcional): Número de días a incluir (default: 30)

**Respuesta:**
```json
[
  {
    "date": "2026-01-01",
    "audits_count": 15,
    "average_score": 78.5
  },
  {
    "date": "2026-01-02",
    "audits_count": 20,
    "average_score": 75.2
  },
  ...
]
```

---

### 7. Ranking de URLs
**GET** `/api/statistics/ranking/?limit=10`

Retorna las URLs mejor y peor puntuadas.

**Parámetros:**
- `limit` (opcional): Número de URLs a retornar (default: 10)

**Respuesta:**
```json
{
  "best_urls": [
    {
      "url": "https://example.com",
      "score": 95.5,
      "page_title": "Example Page",
      "audited_at": "2026-01-03T10:30:00Z"
    },
    ...
  ],
  "worst_urls": [
    {
      "url": "https://bad-example.com",
      "score": 25.0,
      "page_title": "Bad Example",
      "audited_at": "2026-01-02T15:20:00Z"
    },
    ...
  ]
}
```

---

### 8. Comparación por Fuente
**GET** `/api/statistics/sources/`

Compara resultados entre diferentes fuentes (raw, rendered, mixed).

**Respuesta:**
```json
{
  "raw": {
    "total_checks": 3000,
    "pass_count": 1500,
    "fail_count": 1000,
    "average_score": 1.5,
    "pass_rate": 50.0
  },
  "rendered": {
    "total_checks": 2000,
    "pass_count": 1200,
    "fail_count": 600,
    "average_score": 1.6,
    "pass_rate": 60.0
  },
  "mixed": {
    ...
  }
}
```

---

### 9. Estadísticas de una Auditoría Específica
**GET** `/api/statistics/audit/<audit_id>/`

Retorna estadísticas detalladas para una auditoría en particular.

**Respuesta:**
```json
{
  "audit_id": 123,
  "url": "https://example.com",
  "score": 85.5,
  "fetched_at": "2026-01-03T10:30:00Z",
  "total_criteria_checked": 50,
  "verdict_distribution": {
    "pass": {
      "count": 30,
      "percentage": 60.0
    },
    "fail": {
      "count": 15,
      "percentage": 30.0
    },
    ...
  },
  "level_distribution": {
    "A": 20,
    "AA": 25,
    "AAA": 5
  },
  "principle_distribution": {
    "Perceivable": 15,
    "Operable": 12,
    ...
  }
}
```

---

### 10. Reporte Completo
**GET** `/api/statistics/report/`

Genera un reporte completo con todas las estadísticas principales en un solo endpoint.

**Respuesta:**
```json
{
  "global_statistics": { ... },
  "verdict_distribution": { ... },
  "level_statistics": { ... },
  "principle_statistics": { ... },
  "source_comparison": { ... },
  "top_failing_criteria": [ ... ],
  "url_ranking": { ... }
}
```

---

## Uso desde el Frontend

Ejemplo de cómo consumir estos endpoints desde JavaScript:

```javascript
// Obtener estadísticas globales
async function getGlobalStats() {
  const response = await fetch('http://localhost:8000/api/statistics/global/');
  const data = await response.json();
  console.log(data);
}

// Obtener criterios que más fallan
async function getFailingCriteria() {
  const response = await fetch('http://localhost:8000/api/statistics/criteria/');
  const data = await response.json();
  // Los datos ya vienen ordenados por fail_count descendente
  const top10 = data.slice(0, 10);
  console.log('Top 10 criterios que más fallan:', top10);
}

// Obtener reporte completo
async function getFullReport() {
  const response = await fetch('http://localhost:8000/api/statistics/report/');
  const data = await response.json();
  return data;
}
```

---

## Casos de Uso

1. **Dashboard de administración**: Usa `/api/statistics/report/` para obtener todos los datos de un vistazo.

2. **Análisis de tendencias**: Usa `/api/statistics/timeline/` para ver cómo evoluciona la calidad en el tiempo.

3. **Identificar problemas comunes**: Usa `/api/statistics/criteria/` para ver qué criterios WCAG fallan más frecuentemente.

4. **Comparar URLs**: Usa `/api/statistics/ranking/` para identificar las mejores y peores páginas auditadas.

5. **Análisis por nivel de conformidad**: Usa `/api/statistics/levels/` para ver el rendimiento por nivel A, AA, AAA.

6. **Reporte detallado de una auditoría**: Usa `/api/statistics/audit/<id>/` para analizar una auditoría específica.

---

## Notas

- Todos los endpoints están disponibles sin autenticación (configurados con `AllowAny`).
- Los porcentajes se redondean a 2 decimales.
- Los scores promedio también se redondean a 2 decimales.
- Los criterios en `/api/statistics/criteria/` están ordenados por número de fallos (descendente).
