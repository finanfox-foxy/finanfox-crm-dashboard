# CRM Dashboard Finanfox 🦊

Dashboard CRM con métricas de ventas, finanzas y prospección para asesores Finanfox.

## Stack

- **Frontend**: HTML/CSS/JS vanilla con Chart.js
- **Backend**: Python (extractor Zoho CRM) + Node.js (Fox Squad)
- **Datos**: Zoho CRM API → JSON estáticos → GitHub Pages
- **CI/CD**: GitHub Actions (extracción diaria + deploy automático)

## Estructura

```
finanfox-crm-dashboard/
├── index.html              # Dashboard global (CRM + Finanzas)
├── alberto-prieto.html     # Dashboard Alberto Prieto
├── jaime-becerra.html      # Dashboard Jaime Becerra
├── jose-orrequia.html      # Dashboard Jose Orrequia
├── scripts/
│   ├── zoho-crm-extract.py # Extractor Zoho CRM (Python)
│   ├── commission-engine.js # Lógica de comisiones compartida
│   └── test_zoho_extract.py# Tests del extractor
├── data/                   # JSON generados (gitignored)
└── .github/workflows/      # CI/CD pipeline
```

## Comisiones

La lógica de comisiones está en `scripts/commission-engine.js` y es compartida por los 4 dashboards.  
**No duplicar.** Cualquier cambio se hace aquí y se propaga automáticamente.

### Tabla de comisiones actual

| Producto | Objetivo mínimo | Tasa comisión |
|----------|----------------|---------------|
| Monefit | 100.000€ | 0.23% |
| SilverGold | 132.750€ | 0.57% |
| PIAS Aegon | 4.500€ | 6.63% |
| APEX Aegon | 500.000€ | 0.04% |
| Unit-Linked Aegon | 15.000€ | 0.49% |
| ... | ver commission-engine.js | ... |

## Desarrollo local

```bash
# Servir localmente
cd finanfox-crm-dashboard
python3 -m http.server 8000

# Tests
cd scripts
python3 -m pytest test_zoho_extract.py -v
```

## CI/CD

- **Schedule**: 5:00 UTC diario (7:00 AM España)
- **Trigger**: También en cada push
- **Proceso**: Extrae Zoho → genera JSON → commit + push → GitHub Pages
- **Si falla**: no hay alerta automática (pendiente)

## Secretos

| Variable | Dónde está |
|----------|-----------|
| ZOHO_CLIENT_ID | GitHub Secrets |
| ZOHO_CLIENT_SECRET | GitHub Secrets |
| ZOHO_REFRESH_TOKEN | GitHub Secrets |
| PROSP_API_KEY | .env en fox-squad/ (gitignored) |

## Fox Squad

El pipeline de prospección (Fox Squad) corre en el VPS Hostinger con PM2.

```bash
ssh root@76.13.57.41
pm2 status
pm2 logs fox-squad
```

## Runbook

### Rollback de datos

```bash
# Si los datos de Zoho están corruptos, restaurar backup
cp data/asesor.bak.json data/asesor.json
git commit -m "rollback: restore previous data"
git push
```

### El extractor falla

1. Check GitHub Actions logs
2. Verificar tokens Zoho en Secrets
3. Re-run workflow manualmente
4. Si persiste, check Zoho API status

### Migración de base de datos

```bash
# Nuevo producto → añadir a commission-engine.js
# Después regenerar datos con el extractor
```