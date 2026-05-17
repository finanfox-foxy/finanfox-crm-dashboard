#!/usr/bin/env python3
"""
Zoho CRM Data Extractor for GitHub Actions
Reads credentials from environment variables (GitHub Secrets).
Outputs structured data to data/zoho-crm.json with:
  - All-time stats
  - Yesterday stats
  - Current-month stats
  - Product breakdown for closed-won deals (with entity)
  - Advisor performance ranking
  - Lost deals per period
  - Pipeline comparison snapshot
"""

import os, sys, json, time, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Credentials ──────────────────────────────────────────
CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID')
CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET')
REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN')
ACCOUNTS_URL = os.environ.get('ZOHO_ACCOUNTS_URL', 'https://accounts.zoho.eu')
API_DOMAIN = os.environ.get('ZOHO_API_DOMAIN', 'https://www.zohoapis.eu')

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    print("ERROR: Missing Zoho credentials. Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN")
    sys.exit(1)

DATA_DIR = Path(__file__).parent.parent / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / 'zoho-crm.json'

# ── API helpers ──────────────────────────────────────────
ACCESS_TOKEN = None

def get_access_token(force=False):
    global ACCESS_TOKEN
    if ACCESS_TOKEN and not force:
        return ACCESS_TOKEN
    r = requests.post(f"{ACCOUNTS_URL}/oauth/v2/token", data={
        'refresh_token': REFRESH_TOKEN,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'refresh_token'
    })
    data = r.json()
    if 'access_token' not in data:
        print(f"ERROR refreshing token: {data}")
        sys.exit(1)
    ACCESS_TOKEN = data['access_token']
    return ACCESS_TOKEN

def api_get(module, params=None):
    token = get_access_token()
    url = f"{API_DOMAIN}/crm/v2/{module}"
    r = requests.get(url, headers={'Authorization': f'Zoho-oauthtoken {token}'}, params=params)
    if r.status_code == 204:
        return {"data": []}
    if r.status_code == 401:
        token = get_access_token(force=True)
        r = requests.get(url, headers={'Authorization': f'Zoho-oauthtoken {token}'}, params=params)
    try:
        return r.json()
    except:
        return {"error": f"HTTP {r.status_code}"}

def fetch_all(module, params_extra=None):
    all_records = []
    page = 1
    p = {'per_page': 200, 'page': page}
    if params_extra:
        p.update(params_extra)
    while True:
        p['page'] = page
        r = api_get(module, p)
        records = r.get('data', [])
        if not records:
            break
        all_records.extend(records)
        page += 1
        if page > 20:
            break
    return all_records

def simplify(record, keep_fields):
    result = {}
    for key in keep_fields:
        val = record.get(key)
        if isinstance(val, dict) and 'name' in val:
            val = val['name']
        if isinstance(val, list) and val and isinstance(val[0], dict):
            val = [v.get('name', str(v)) for v in val]
        result[key] = val
    return result

# ── Date helpers (Europe/Madrid) ─────────────────────────
def spain_today():
    """Return today's date in Spain timezone (CEST = UTC+2 in summer)."""
    now_utc = datetime.now(timezone.utc)
    # CEST (late Mar to late Oct) = UTC+2; rest CET = UTC+1
    # Approximate: May is CEST = +2h
    spain = now_utc + timedelta(hours=2)
    return spain.date()

TODAY = spain_today()
YESTERDAY = TODAY - timedelta(days=1)
PREV_YESTERDAY = YESTERDAY - timedelta(days=1)  # dia anterior a ayer
THIS_MONTH = str(TODAY)[:7]  # "2026-05"
# Mes anterior (primer dia del mes actual - 1 dia = ultimo dia del mes anterior)
PREV_MONTH_FIRST = TODAY.replace(day=1) - timedelta(days=1)
PREV_MONTH = str(PREV_MONTH_FIRST)[:7]  # e.g., "2026-04"

def in_yesterday(date_str):
    if not date_str:
        return False
    return date_str[:10] == str(YESTERDAY)

def in_this_month(date_str):
    if not date_str:
        return False
    return date_str[:7] == THIS_MONTH

def in_prev_yesterday(date_str):
    if not date_str:
        return False
    return date_str[:10] == str(PREV_YESTERDAY)

def in_prev_month(date_str):
    if not date_str:
        return False
    return date_str[:7] == PREV_MONTH

# ── Funnel stage order ───────────────────────────────────
STAGE_ORDER = [
    'Llamada Pendiente',
    'Análisis Financiero',
    'Asesoramiento',
    'Reasesoramiento',
    'Revisando Propuesta',
    'Aceptado/Falta Firma',
    'Cerrado Ganado',
    'Cerrado Perdido',
]

# ── Stats computation ────────────────────────────────────
def compute_period_stats(contacts, deals, product_records, label, filter_fn):
    """
    Compute KPIs for a given time period.
    filter_fn(date_str) -> True/False determines if record belongs to period.
    product_records: list of raw Productos_Financieros records (with Parent_Id).
    """
    period_contacts = [c for c in contacts if filter_fn(c.get('Created_Time'))]
    period_deals = [d for d in deals if filter_fn(d.get('Created_Time'))]

    # New deals created in period (by Created_Time)
    new_deals = period_deals

    # Closed-won: deals where Stage='Ganado' and Closing_Date is in period
    won_deals = [
        d for d in deals
        if 'Ganado' in (d.get('Stage') or '')
        and filter_fn(d.get('Closing_Date'))
    ]
    won_deal_ids = {d['id'] for d in won_deals if d.get('id')}

    # Lost deals: Cerrado Perdido with Closing_Date in period
    lost_deals = [
        d for d in deals
        if 'Perdido' in (d.get('Stage') or '')
        and filter_fn(d.get('Closing_Date'))
    ]

    # Product breakdown with ENTIDAD: detailed list + aggregated summary
    product_details = []
    product_breakdown = {}
    product_count = {}
    for pr in product_records:
        parent = pr.get('Parent_Id', {})
        parent_id = parent.get('id') if isinstance(parent, dict) else None
        if parent_id in won_deal_ids:
            prod = pr.get('Producto', {})
            pname = prod.get('name', 'Otro') if isinstance(prod, dict) else 'Otro'
            entidad = pr.get('Entidades', '') or ''
            amount = float(pr.get('Aportaci_n_Inicial', 0) or 0)
            product_details.append({
                'producto': pname,
                'entidad': entidad,
                'aportacion': amount
            })
            product_breakdown[pname] = product_breakdown.get(pname, 0) + amount
            product_count[pname] = product_count.get(pname, 0) + 1

    # Advisor performance: won deals by owner
    advisor_won = {}
    for d in won_deals:
        owner = d.get('Owner', 'Sin asignar')
        amount = float(d.get('Total_Aportaciones', 0) or 0)
        if owner not in advisor_won:
            advisor_won[owner] = {'won': 0, 'total_aportacion': 0.0}
        advisor_won[owner]['won'] += 1
        advisor_won[owner]['total_aportacion'] += amount

    advisor_ranking_won = sorted(
        [{'name': k, 'won': v['won'], 'total_aportacion': v['total_aportacion']}
         for k, v in advisor_won.items()],
        key=lambda x: -x['won']
    )
    advisor_ranking_aportacion = sorted(
        advisor_ranking_won,
        key=lambda x: -x['total_aportacion']
    )

    # Pipeline stages: ALL deals (not just period) — current state
    # For "yesterday" and "this-month", pipeline shows current state
    # But we also want deals CREATED in period and still open
    pipeline_stages = {}
    pipeline_value = 0.0
    for d in deals:
        stage = d.get('Stage', 'Sin etapa')
        # Include all stages (including perdido) for complete funnel
        pipeline_stages[stage] = pipeline_stages.get(stage, 0) + 1
        pipeline_value += float(d.get('Amount', 0) or 0)

    # Sort pipeline_stages by our order, unknown stages at end
    ordered_pipeline = {}
    for stage in STAGE_ORDER:
        if stage in pipeline_stages:
            ordered_pipeline[stage] = pipeline_stages[stage]
    for stage, count in pipeline_stages.items():
        if stage not in STAGE_ORDER:
            ordered_pipeline[stage] = count

    return {
        "label": label,
        "new_contacts": len(period_contacts),
        "new_deals": len(new_deals),
        "won_deals": len(won_deals),
        "lost_deals": len(lost_deals),
        "won_value": sum(float(d.get('Amount', 0) or 0) for d in won_deals),
        "total_aportacion_won": sum(float(d.get('Total_Aportaciones', 0) or 0) for d in won_deals),
        "product_breakdown": dict(sorted(product_breakdown.items(), key=lambda x: -x[1])),
        "product_count": dict(sorted(product_count.items(), key=lambda x: -x[1])),
        "product_details": sorted(product_details, key=lambda x: -x['aportacion']),
        "advisor_ranking_won": advisor_ranking_won,
        "advisor_ranking_aportacion": advisor_ranking_aportacion,
        "pipeline_stages": ordered_pipeline,
        "pipeline_value": pipeline_value,
    }

# ── Main ─────────────────────────────────────────────────
def main():
    print("Extrayendo datos de Zoho CRM...")
    print(f"   Periodo de referencia: Hoy={TODAY}, Ayer={YESTERDAY}, Mes={THIS_MONTH}")

    # Read previous JSON for pipeline snapshot comparison
    previous_pipeline = {}
    previous_pipeline_value = 0
    prev_pipeline_details = False
    if DATA_FILE.exists():
        try:
            prev_data = json.loads(DATA_FILE.read_text())
            prev_s = prev_data.get('stats', {}).get('this_month', {})
            previous_pipeline = prev_s.get('pipeline_stages', {})
            previous_pipeline_value = prev_s.get('pipeline_value', 0)
            # Check if we had pipeline_details before
            prev_pipeline_details = 'pipeline_details' in prev_data
        except:
            pass

    # ── Contacts ──
    print("  Contactos...")
    contacts_raw = fetch_all('Contacts')
    contact_fields = [
        'id', 'Full_Name', 'First_Name', 'Last_Name', 'Email', 'Phone',
        'Owner', 'Canal', 'Socio', 'Fuente', 'DNI', 'Cuenta_Corriente',
        'Estado_civil', 'Profesi_n', 'Club', 'Divisi_n',
        'Plantilla_Bienvenida_enviada', 'Visitor_Score', 'Days_Visited',
        'Average_Time_Spent_Minutes', 'Created_Time', 'Modified_Time',
        'Last_Activity_Time'
    ]
    contacts = [simplify(c, contact_fields) for c in contacts_raw]
    print(f"    -> {len(contacts)} contactos")

    # ── Deals ──
    print("  Ofertas...")
    deals_raw = fetch_all('Deals')
    deal_fields = [
        'id', 'Deal_Name', 'Amount', 'Stage', 'Probability',
        'Contact_Name', 'Owner', 'Type', 'Total_Aportaciones',
        'Total_Suscripci_n', 'Motivo_de_cierre_perdido', 'Fuente',
        'Created_Time', 'Closing_Date', 'Tag', 'Lead_Conversion_Time',
        'Overall_Sales_Duration', 'Sales_Cycle_Duration'
    ]
    deals = [simplify(d, deal_fields) for d in deals_raw]
    print(f"    -> {len(deals)} ofertas")

    # ── Products ──
    print("  Productos...")
    products_raw = fetch_all('Products')
    product_fields = ['id', 'Product_Name', 'Product_Code', 'Unit_Price', 'Description']
    products = [simplify(p, product_fields) for p in products_raw]
    print(f"    -> {len(products)} productos")

    # ── Tasks ──
    print("  Tareas...")
    tasks_raw = fetch_all('Tasks')
    task_fields = ['id', 'Subject', 'Status', 'Priority', 'Owner', 'Due_Date', 'Created_Time']
    tasks = [simplify(t, task_fields) for t in tasks_raw]
    print(f"    -> {len(tasks)} tareas")

    # ── Productos Financieros (custom subform) ──
    print("  Productos Financieros...")
    pf_records = fetch_all('Productos_Financieros')
    print(f"    -> {len(pf_records)} registros")

    # ── All-time stats ──
    print("  Calculando estadisticas...")
    contacts_by_owner = {}
    contacts_by_canal = {}
    contacts_with_email = 0
    contacts_with_phone = 0
    contacts_with_welcome = 0

    for c in contacts:
        owner = c.get('Owner', 'Sin asignar')
        contacts_by_owner[owner] = contacts_by_owner.get(owner, 0) + 1
        canal = c.get('Canal', 'Sin canal')
        contacts_by_canal[canal] = contacts_by_canal.get(canal, 0) + 1
        if c.get('Email'): contacts_with_email += 1
        if c.get('Phone'): contacts_with_phone += 1
        if c.get('Plantilla_Bienvenida_enviada'): contacts_with_welcome += 1

    deals_by_stage = {}
    deals_by_owner = {}
    deals_by_type = {}
    pipeline_value = 0
    closed_won_value = 0
    closed_won_count = 0
    total_aportaciones = 0
    closed_lost_count = 0

    for d in deals:
        stage = d.get('Stage', 'Sin etapa')
        deals_by_stage[stage] = deals_by_stage.get(stage, 0) + 1
        owner = d.get('Owner', 'Sin asignar')
        deals_by_owner[owner] = deals_by_owner.get(owner, 0) + 1
        dtype = d.get('Type', 'Sin tipo')
        deals_by_type[dtype] = deals_by_type.get(dtype, 0) + 1
        amount = d.get('Amount', 0) or 0
        pipeline_value += amount
        aport = d.get('Total_Aportaciones', 0) or 0
        total_aportaciones += aport
        if 'Ganado' in (stage or ''):
            closed_won_value += amount
            closed_won_count += 1
        if 'Perdido' in (stage or ''):
            closed_lost_count += 1

    avg_deal_size = pipeline_value / len(deals) if deals else 0
    conversion_rate = (closed_won_count / len(deals) * 100) if deals else 0

    all_time_stats = {
        "contacts": {
            "total": len(contacts),
            "with_email": contacts_with_email,
            "with_phone": contacts_with_phone,
            "welcome_sent": contacts_with_welcome,
            "by_owner": contacts_by_owner,
            "by_canal": contacts_by_canal
        },
        "deals": {
            "total": len(deals),
            "by_stage": deals_by_stage,
            "by_owner": deals_by_owner,
            "by_type": deals_by_type,
            "pipeline_value": pipeline_value,
            "total_aportaciones": total_aportaciones,
            "avg_deal_size": round(avg_deal_size, 2),
            "closed_won": closed_won_count,
            "closed_won_value": closed_won_value,
            "closed_lost": closed_lost_count,
            "conversion_rate": round(conversion_rate, 1)
        }
    }

    # ── Period stats ──
    yesterday_stats = compute_period_stats(
        contacts, deals, pf_records, "Ayer", in_yesterday
    )

    this_month_stats = compute_period_stats(
        contacts, deals, pf_records, "Este Mes", in_this_month
    )

    print(f"\nAyer ({YESTERDAY}):")
    print(f"   Nuevos contactos: {yesterday_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {yesterday_stats['new_deals']}")
    print(f"   Ofertas ganadas: {yesterday_stats['won_deals']} (E{yesterday_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {yesterday_stats['lost_deals']}")
    print(f"   Productos cerrados: {len(yesterday_stats['product_breakdown'])}")

    print(f"\nEste mes ({THIS_MONTH}):")
    print(f"   Nuevos contactos: {this_month_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {this_month_stats['new_deals']}")
    print(f"   Ofertas ganadas: {this_month_stats['won_deals']} (E{this_month_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {this_month_stats['lost_deals']}")
    print(f"   Productos cerrados: {len(this_month_stats['product_breakdown'])}")

    # ── Previous period stats (for comparison) ──
    print("\nCalculando periodos de comparacion...")
    prev_yesterday_stats = compute_period_stats(
        contacts, deals, pf_records, "Anteayer", in_prev_yesterday
    )
    prev_month_stats = compute_period_stats(
        contacts, deals, pf_records, "Mes Anterior", in_prev_month
    )

    print(f"\nAnteayer ({PREV_YESTERDAY}):")
    print(f"   Nuevos contactos: {prev_yesterday_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {prev_yesterday_stats['new_deals']}")
    print(f"   Ofertas ganadas: {prev_yesterday_stats['won_deals']} (E{prev_yesterday_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {prev_yesterday_stats['lost_deals']}")

    print(f"\nMes anterior ({PREV_MONTH}):")
    print(f"   Nuevos contactos: {prev_month_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {prev_month_stats['new_deals']}")
    print(f"   Ofertas ganadas: {prev_month_stats['won_deals']} (E{prev_month_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {prev_month_stats['lost_deals']}")

    # ── Pipeline details for funnel with conversion and comparison ──
    TERMINAL_STAGES_SET = {'Cerrado Ganado', 'Cerrado Perdido'}
    pipeline_details = []
    terminal_details = []
    total_pipeline = sum(this_month_stats['pipeline_stages'].values())
    prev_count = None
    first_stage_count = None

    for stage in STAGE_ORDER:
        curr_count = this_month_stats['pipeline_stages'].get(stage, 0)
        prev_count_in_pipeline = previous_pipeline.get(stage, None)
        is_terminal = stage in TERMINAL_STAGES_SET

        # pct_of_total: % of all pipeline deals in this stage
        pct_of_total = round(curr_count / total_pipeline * 100, 1) if total_pipeline > 0 else 0

        # Track first active stage count for conversion_from_top
        if not is_terminal and first_stage_count is None:
            first_stage_count = curr_count

        # conversion_from_top: what % of top-of-funnel makes it here
        if first_stage_count and first_stage_count > 0:
            conv_from_top = round(curr_count / first_stage_count * 100, 1)
        else:
            conv_from_top = None

        # conversion_from_prev: only meaningful for active stages with normal funnel flow
        # (current <= previous). Skip for terminal stages and when deals enter mid-funnel.
        if not is_terminal and prev_count is not None and prev_count > 0 and curr_count <= prev_count:
            conv_pct = round(curr_count / prev_count * 100, 1)
        else:
            conv_pct = None

        stage_data = {
            'stage': stage,
            'count': curr_count,
            'pct_of_total': pct_of_total,
            'conversion_from_prev': conv_pct,
            'conversion_from_top': conv_from_top,
            'cmp_count': prev_count_in_pipeline
        }

        if is_terminal:
            terminal_details.append(stage_data)
        else:
            pipeline_details.append(stage_data)
            prev_count = curr_count

    # Add extra stages not in order (unknown stages that may appear)
    extra_stages = this_month_stats['pipeline_stages'].copy()
    for stage in STAGE_ORDER:
        extra_stages.pop(stage, None)
    for stage, count in sorted(extra_stages.items()):
        prev_count_in_pipeline = previous_pipeline.get(stage, None)
        pipeline_details.append({
            'stage': stage,
            'count': count,
            'pct_of_total': 0,
            'conversion_from_prev': '',
            'conversion_from_top': '',
            'cmp_count': prev_count_in_pipeline
        })

    # ── Assemble output ──
    data = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "generated_at": str(TODAY),
        "today": str(TODAY),
        "yesterday": str(YESTERDAY),
        "this_month": THIS_MONTH,
        "contacts": contacts,
        "deals": deals,
        "products": products,
        "tasks": tasks,
        "stats": {
            "all_time": all_time_stats,
            "yesterday": yesterday_stats,
            "this_month": this_month_stats,
        },
        "comparison": {
            "yesterday": {
                "previous": str(PREV_YESTERDAY),
                "period_label": "anteayer",
                "stats": prev_yesterday_stats
            },
            "this_month": {
                "previous": PREV_MONTH,
                "period_label": "mes anterior",
                "stats": prev_month_stats
            }
        },
        "pipeline": {
            "stage_order": STAGE_ORDER,
            "details": pipeline_details,
            "terminal": terminal_details,
            "active_total": total_pipeline - sum(s.get('count', 0) for s in terminal_details),
            "won_total": this_month_stats['pipeline_stages'].get('Cerrado Ganado', 0),
            "lost_total": this_month_stats['pipeline_stages'].get('Cerrado Perdido', 0),
            "previous_pipeline": previous_pipeline,
            "previous_value": previous_pipeline_value,
            "total_pipeline": total_pipeline
        }
    }

    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nDatos guardados en {DATA_FILE}")
    print(f"   {len(contacts)} contactos | {len(deals)} ofertas | {len(products)} productos")
    print(f"   Pipeline: E{pipeline_value:,.0f} | Cerrados ganados: {closed_won_count} (E{closed_won_value:,.0f}) | Perdidos: {closed_lost_count}")

if __name__ == '__main__':
    main()
