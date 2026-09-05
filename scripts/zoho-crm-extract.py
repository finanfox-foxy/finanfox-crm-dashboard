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
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo

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

def api_get(module, params=None, max_retries=3):
    token = get_access_token()
    url = f"{API_DOMAIN}/crm/v2/{module}"
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers={'Authorization': f'Zoho-oauthtoken {token}'}, params=params, timeout=30)
            if r.status_code == 204:
                return {"data": []}
            if r.status_code == 401:
                token = get_access_token(force=True)
                r = requests.get(url, headers={'Authorization': f'Zoho-oauthtoken {token}'}, params=params, timeout=30)
                if r.status_code == 204:
                    return {"data": []}
            if r.status_code == 429:
                wait = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                print(f"  ⏳ Rate limited (429), retrying in {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                wait = 2 ** attempt
                print(f"  ⚠️ Server error {r.status_code}, retrying in {wait}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            try:
                return r.json()
            except:
                print(f"  ❌ Invalid JSON response: HTTP {r.status_code}")
                return {"error": f"Invalid JSON from HTTP {r.status_code}"}
        except requests.exceptions.Timeout:
            print(f"  ⏰ Timeout (attempt {attempt+1}/{max_retries})")
            if attempt == max_retries - 1:
                return {"error": "Timeout after retries"}
            time.sleep(2 ** attempt)
        except requests.exceptions.ConnectionError as e:
            print(f"  🔌 Connection error: {e} (attempt {attempt+1}/{max_retries})")
            if attempt == max_retries - 1:
                return {"error": f"Connection error after retries: {e}"}
            time.sleep(2 ** attempt)
    return {"error": f"Max retries exceeded for HTTP {r.status_code if 'r' in dir() else 'unknown'}"}

def fetch_all(module, params_extra=None):
    all_records = []
    page = 1
    total = 0
    MAX_PAGES = 500  # safety limit (500 pages × 200 = 100k records)
    p = {'per_page': 200, 'page': page}
    if params_extra:
        p.update(params_extra)
    while page <= MAX_PAGES:
        p['page'] = page
        r = api_get(module, p)
        if 'error' in r:
            print(f"    ❌ Error en página {page}: {r['error']}")
            break
        records = r.get('data', [])
        info = r.get('info', {})
        more_records = info.get('more_records', False) if info else bool(records)
        if not records:
            break
        all_records.extend(records)
        total += len(records)
        page += 1
        if page % 20 == 0:
            print(f"    ...{total} registros obtenidos de {module} (página {page})")
        if not more_records:
            break
    if page > MAX_PAGES:
        print(f"    ⚠️ Límite de seguridad alcanzado ({MAX_PAGES} páginas). Posible loop infinito.")
    print(f"    -> {len(all_records)} registros de {module} en {page-1} páginas")
    return all_records


def fetch_by_ids(module, ids_list, fields_str=None):
    """Fetch records by a list of IDs (batched 200 at a time)."""
    all_records = []
    for i in range(0, len(ids_list), 200):
        batch = ids_list[i:i+200]
        params = {'ids': ','.join(batch)}
        if fields_str:
            params['fields'] = fields_str
        r = api_get(module, params)
        records = r.get('data', []) or []
        all_records.extend(records)
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
    """Return today's date in Spain timezone (CEST/CET real)."""
    now_utc = datetime.now(timezone.utc)
    spain = now_utc.astimezone(ZoneInfo('Europe/Madrid'))
    return spain.date()

TODAY = spain_today()
YESTERDAY = TODAY - timedelta(days=1)
PREV_YESTERDAY = YESTERDAY - timedelta(days=1)  # dia anterior a ayer
THIS_MONTH = str(TODAY)[:7]  # "2026-05"
# Mes anterior (primer dia del mes actual - 1 dia = ultimo dia del mes anterior)
PREV_MONTH_FIRST = TODAY.replace(day=1) - timedelta(days=1)
PREV_MONTH = str(PREV_MONTH_FIRST)[:7]  # e.g., "2026-04"

# ── Quarter helpers ──────────────────────────────────────
def _quarter_dates(today):
    
    q = (today.month - 1) // 3 + 1
    start_month = (q - 1) * 3 + 1
    start_date = today.replace(month=start_month, day=1)
    if q < 4:
        end_month = q * 3
        end_date = today.replace(month=end_month + 1, day=1) - timedelta(days=1)
    else:
        end_date = today.replace(month=12, day=31)
    return f"Q{q}", start_date, end_date

def _prev_quarter_dates(today):
    q = (today.month - 1) // 3 + 1
    if q == 1:
        prev_q = 4
        prev_year = today.year - 1
        start_date = date(prev_year, 10, 1)
        end_date = date(prev_year, 12, 31)
    else:
        prev_q = q - 1
        start_month = (prev_q - 1) * 3 + 1
        start_date = today.replace(month=start_month, day=1)
        end_month = prev_q * 3
        end_date = today.replace(month=end_month + 1, day=1) - timedelta(days=1)
    return f"Q{prev_q}", start_date, end_date

THIS_QUARTER_LABEL, THIS_QUARTER_START, THIS_QUARTER_END = _quarter_dates(TODAY)
PREV_QUARTER_LABEL, PREV_QUARTER_START, PREV_QUARTER_END = _prev_quarter_dates(TODAY)

# ── Year helpers ─────────────────────────────────────────
THIS_YEAR_START = TODAY.replace(month=1, day=1)
THIS_YEAR_END = TODAY.replace(month=12, day=31)
PREV_YEAR_START = TODAY.replace(year=TODAY.year - 1, month=1, day=1)
PREV_YEAR_END = TODAY.replace(year=TODAY.year - 1, month=12, day=31)

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

def in_this_quarter(date_str):
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        return THIS_QUARTER_START <= d <= THIS_QUARTER_END
    except:
        return False

def in_prev_quarter(date_str):
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        return PREV_QUARTER_START <= d <= PREV_QUARTER_END
    except:
        return False

def in_this_year(date_str):
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        return THIS_YEAR_START <= d <= THIS_YEAR_END
    except:
        return False

def in_prev_year(date_str):
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d').date()
        return PREV_YEAR_START <= d <= PREV_YEAR_END
    except:
        return False

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

# ── Close-date validation ──────────────────────────────
def _close_date_with_source(d):
    """
    Return (date_str, source) where source is 'Closing_Date' or 'Created_Time_fallback'.
    Also logs a warning when Closing_Date equals Created_Time's date (suspicious).
    """
    closing = d.get('Closing_Date')
    created = d.get('Created_Time')
    if closing:
        # Compare only the date part
        closing_date = closing[:10] if closing else ''
        created_date = created[:10] if created else ''
        if closing_date and created_date and closing_date == created_date:
            deal_name = d.get('Deal_Name', 'desconocido')
            deal_id = d.get('id', '?')
            print(f"  ⚠️ Closing_Date igual a Created_Time en deal '{deal_name}' (id={deal_id}): {closing_date}")
            print(f"     Puede que el campo no se haya rellenado manualmente al cerrar.")
        return closing, 'Closing_Date'
    return created, 'Created_Time_fallback'

def _close_or_create(d):
    """
    Return Closing_Date if set, else Created_Time as fallback.
    Also validates suspicious dates."""
    date_str, _ = _close_date_with_source(d)
    return date_str

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
        and filter_fn(_close_or_create(d))
    ]
    won_deal_ids = {d['id'] for d in won_deals if d.get('id')}
    # Build close-date lookup from won deals (use same _close_or_create logic as filter)
    won_deal_date_map = {d.get('id'): _close_or_create(d)[:10] for d in won_deals if d.get('id')}

    # Lost deals: Cerrado Perdido with Closing_Date in period
    lost_deals = [
        d for d in deals
        if 'Perdido' in (d.get('Stage') or '')
        and filter_fn(_close_or_create(d))
    ]

    # ── Lead Quality: No interesado / No apareció (total + ≤7d) ──
    # Compute all lost deals with relevant reasons
    lost_nina = [d for d in lost_deals if d.get('Motivo_de_cierre_perdido') in ('No interesado', 'No apareció')]
    lost_ni = [d for d in lost_deals if d.get('Motivo_de_cierre_perdido') == 'No interesado']
    lost_na = [d for d in lost_deals if d.get('Motivo_de_cierre_perdido') == 'No apareció']
    # Within 7 days
    CUTOFF_DAYS = 7
    lost_nina_7d = [d for d in lost_nina if (d.get('Sales_Cycle_Duration') or 999) <= CUTOFF_DAYS]
    lost_ni_7d = [d for d in lost_ni if (d.get('Sales_Cycle_Duration') or 999) <= CUTOFF_DAYS]
    lost_na_7d = [d for d in lost_na if (d.get('Sales_Cycle_Duration') or 999) <= CUTOFF_DAYS]

    total_new = len(new_deals)

    def _rate(count, base):
        return round(count / base * 100, 1) if base > 0 else 0.0

    lead_quality = {
        'ni_total': len(lost_ni),
        'na_total': len(lost_na),
        'ni_na_total': len(lost_nina),
        'ni_total_rate': _rate(len(lost_ni), total_new),
        'na_total_rate': _rate(len(lost_na), total_new),
        'ni_na_total_rate': _rate(len(lost_nina), total_new),
        'ni_7d': len(lost_ni_7d),
        'na_7d': len(lost_na_7d),
        'ni_na_7d': len(lost_nina_7d),
        'ni_7d_rate': _rate(len(lost_ni_7d), total_new),
        'na_7d_rate': _rate(len(lost_na_7d), total_new),
        'ni_na_7d_rate': _rate(len(lost_nina_7d), total_new),
        # Internal distribution within lead_quality bucket
        'ni_pct': _rate(len(lost_ni), len(lost_nina)),
        'na_pct': _rate(len(lost_na), len(lost_nina)),
        'ni_7d_pct': _rate(len(lost_ni_7d), len(lost_nina_7d)),
        'na_7d_pct': _rate(len(lost_na_7d), len(lost_nina_7d)),
    }

    # Product breakdown with ENTIDAD: detailed list + aggregated summary
    product_details = {}
    product_deals = []  # individual per-deal records with close dates (for chronological commission)
    product_breakdown = {}
    product_count = {}

    # Build client name lookup map from linked deals
    deal_client_map = {}
    for d_ in deals:
        cn_ = d_.get('Contact_Name', {})
        if isinstance(cn_, dict):
            deal_client_map[d_.get('id')] = cn_.get('name', '')
        elif isinstance(cn_, str):
            deal_client_map[d_.get('id')] = cn_
        else:
            deal_client_map[d_.get('id')] = ''

    if product_records:
        for pr in product_records:
            parent = pr.get('Parent_Id', {})
            parent_id = parent.get('id') if isinstance(parent, dict) else None
            if parent_id in won_deal_ids:
                prod = pr.get('Producto', {})
                pname = prod.get('name', 'Otro') if isinstance(prod, dict) else 'Otro'
                entidad = pr.get('Entidades', '') or ''
                amount = float(pr.get('Aportaci_n_Inicial', 0) or 0)
                close_date = won_deal_date_map.get(parent_id)
                close_date_source = 'deal_Closing_Date'
                if not close_date:
                    close_date = (pr.get('Created_Time', '') or '')[:10]
                    close_date_source = 'product_Created_Time_fallback'
                fecha_inicio = (pr.get('Fecha_Inicio', '') or '')[:10]
                obj_financiero = pr.get('Objetivo_Financiero', '') or ''
                plazo = pr.get('Plazos', '') or ''
                cliente = deal_client_map.get(parent_id, '')
                key = (pname, entidad)
                if key not in product_details:
                    product_details[key] = {'producto': pname, 'entidad': entidad, 'veces': 0, 'total': 0.0}
                product_details[key]['veces'] += 1
                product_details[key]['total'] += amount
                product_breakdown[pname] = product_breakdown.get(pname, 0) + amount
                product_count[pname] = product_count.get(pname, 0) + 1
                product_deals.append({
                    'producto': pname,
                    'entidad': entidad,
                    'total': amount,
                    'close_date': close_date,
                    'close_date_source': close_date_source,
                    'cliente': cliente,
                    'parent_id': parent_id,
                    'fecha_inicio': fecha_inicio,
                    'objetivo_financiero': obj_financiero,
                    'plazo': plazo
                })
        # Fallback: for won deals that have NO linked PF records (e.g. migrated from Odoo),
        # extract product info from deal name (format: "ClientName - ProductName")
        # Solo deals que YA se procesaron en el primer loop (winning PF records en won_deal_ids)
        pf_parent_ids = set()
        for pr in product_records:
            parent = pr.get('Parent_Id', {})
            parent_id = parent.get('id') if isinstance(parent, dict) else None
            if parent_id and parent_id in won_deal_ids:
                pf_parent_ids.add(parent_id)
        for d in won_deals:
            did = d.get('id')
            if did and did in pf_parent_ids:
                continue  # already handled above via PF record
            deal_name = d.get('Deal_Name', '') or ''
            amount = float(d.get('Total_Aportaciones', 0) or 0)
            close_date, close_date_source = _close_date_with_source(d)
            close_date = close_date[:10] if close_date else ''
            cn = d.get('Contact_Name', {})
            cliente = cn.get('name', '') if isinstance(cn, dict) else (cn if isinstance(cn, str) else '')
            if ' - ' in deal_name:
                parts = deal_name.split(' - ')
                pname = parts[-1].strip()
                if not cliente:
                    cliente = parts[0].strip()
            else:
                pname = 'Planificación'
            if not pname:
                pname = 'Otro'
            entidad = ''
            key = (pname, entidad)
            if key not in product_details:
                product_details[key] = {'producto': pname, 'entidad': entidad, 'veces': 0, 'total': 0.0}
            product_details[key]['veces'] += 1
            product_details[key]['total'] += amount
            product_breakdown[pname] = product_breakdown.get(pname, 0) + amount
            product_count[pname] = product_count.get(pname, 0) + 1
            product_deals.append({
                'producto': pname,
                'entidad': entidad,
                'total': amount,
                'close_date': close_date,
                'close_date_source': close_date_source,
                'cliente': cliente,
                'parent_id': did,
                'fecha_inicio': '',
                'objetivo_financiero': '',
                'plazo': ''
            })
    else:
        # Fallback (no PF records at all): extract product info from won deal names
        # (format: "ClientName - ProductName")
        for d in won_deals:
            deal_name = d.get('Deal_Name', '') or ''
            amount = float(d.get('Total_Aportaciones', 0) or 0)
            close_date, close_date_source = _close_date_with_source(d)
            close_date = close_date[:10] if close_date else ''
            cn = d.get('Contact_Name', {})
            cliente = cn.get('name', '') if isinstance(cn, dict) else (cn if isinstance(cn, str) else '')
            if ' - ' in deal_name:
                parts = deal_name.split(' - ')
                pname = parts[-1].strip()
                if not cliente:
                    cliente = parts[0].strip()
            else:
                pname = 'Planificación'
            if not pname:
                pname = 'Otro'
            entidad = ''
            key = (pname, entidad)
            if key not in product_details:
                product_details[key] = {'producto': pname, 'entidad': entidad, 'veces': 0, 'total': 0.0}
            product_details[key]['veces'] += 1
            product_details[key]['total'] += amount
            product_breakdown[pname] = product_breakdown.get(pname, 0) + amount
            product_count[pname] = product_count.get(pname, 0) + 1
            product_deals.append({
                'producto': pname,
                'entidad': entidad,
                'total': amount,
                'close_date': close_date,
                'close_date_source': close_date_source,
                'cliente': cliente,
                'parent_id': d.get('id'),
                'fecha_inicio': '',
                'objetivo_financiero': '',
                'plazo': ''
            })

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

    # Pipeline stages: filtered by period
    # Open stages: Created_Time in period
    # Terminal stages (Ganado/Perdido): Closing_Date in period
    def _in_pipeline_period(deal):
        stage = deal.get('Stage', '')
        if 'Ganado' in stage or 'Perdido' in stage:
            return filter_fn(_close_or_create(deal))
        return filter_fn(deal.get('Created_Time'))

    pipeline_stages = {}
    pipeline_value = 0.0
    for d in deals:
        if not _in_pipeline_period(d):
            continue
        stage = d.get('Stage', 'Sin etapa')
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

    # ── Win rate ──
    new_deals_count = len(new_deals)
    win_rate = round(len(won_deals) / new_deals_count * 100, 1) if new_deals_count > 0 else None

    # ── Avg days to win ──
    def _parse_date(s):
        if not s:
            return None
        try:
            return datetime.strptime(s[:10], '%Y-%m-%d')
        except:
            return None

    days_to_win = []
    for d in won_deals:
        created = _parse_date(d.get('Created_Time'))
        closed = _parse_date(d.get('Closing_Date'))
        if created and closed:
            days_to_win.append((closed - created).days)
    avg_days_to_win = round(sum(days_to_win) / len(days_to_win), 1) if days_to_win else None

    # ── Products closed count ──
    products_closed_count = sum(detail['veces'] for detail in product_details.values())

    # ── Conversion clientes ──
    # Build set of contact IDs from won deals
    contact_ids_in_deals = set()
    contact_id_to_created = {}
    for c in contacts:
        cid = c.get('id')
        if cid:
            created = _parse_date(c.get('Created_Time'))
            contact_id_to_created[cid] = created

    for d in won_deals:
        cid = d.get('_contact_id')
        if cid:
            contact_ids_in_deals.add(cid)

    # Count contacts in this period that match won deal contacts
    converted_ids = {cid for cid in contact_ids_in_deals if cid in contact_id_to_created}
    total_contacts = len(period_contacts)
    converted_contacts = len(converted_ids)
    conversion_ratio = round(converted_contacts / total_contacts * 100, 1) if total_contacts > 0 else 0.0

    # Avg days from contact creation to deal close (earliest deal per contact)
    days_to_convert = []
    contact_to_earliest_close = {}
    for d in won_deals:
        cid = d.get('_contact_id')
        if cid and cid in converted_ids:
                closed = _parse_date(d.get('Closing_Date'))
                if closed:
                    if cid not in contact_to_earliest_close or closed < contact_to_earliest_close[cid]:
                        contact_to_earliest_close[cid] = closed
    for cid, close_date in contact_to_earliest_close.items():
        created = contact_id_to_created.get(cid)
        if created and close_date:
            days_to_convert.append((close_date - created).days)
    avg_days_to_convert = round(sum(days_to_convert) / len(days_to_convert), 1) if days_to_convert else None

    # ── Contacts by day of month ──
    contacts_by_day = {}
    for c in period_contacts:
        created = c.get('Created_Time', '')
        if created and len(created) >= 10:
            day = created[8:10].lstrip('0') or '0'
            contacts_by_day[day] = contacts_by_day.get(day, 0) + 1
    contacts_by_day = dict(sorted(contacts_by_day.items(), key=lambda x: int(x[0])))

    # ── Deals (opportunities) by day of month ──
    deals_by_day = {}
    for d in new_deals:
        created = d.get('Created_Time', '')
        if created and len(created) >= 10:
            day = created[8:10].lstrip('0') or '0'
            deals_by_day[day] = deals_by_day.get(day, 0) + 1
    deals_by_day = dict(sorted(deals_by_day.items(), key=lambda x: int(x[0])))

    conversion_clientes = {
        "total_contacts": total_contacts,
        "converted_contacts": converted_contacts,
        "ratio": conversion_ratio,
        "avg_days_to_convert": avg_days_to_convert or 0,
    }

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
        "product_details": sorted(product_details.values(), key=lambda x: -x['total']),
        "product_deals": product_deals,
        "advisor_ranking_won": advisor_ranking_won,
        "advisor_ranking_aportacion": advisor_ranking_aportacion,
        "pipeline_stages": ordered_pipeline,
        "pipeline_value": pipeline_value,
        "win_rate": win_rate,
        "avg_days_to_win": avg_days_to_win,
        "products_closed_count": products_closed_count,
        "conversion_clientes": conversion_clientes,
        "contacts_by_day": contacts_by_day,
        "deals_by_day": deals_by_day,
        "lead_quality": lead_quality,
    }

def compute_pipeline_details(pipeline_stages, previous_pipeline=None):
    """Compute pipeline details with conversion rates from period-specific stages."""
    if previous_pipeline is None:
        previous_pipeline = {}

    TERMINAL_STAGES_SET = {'Cerrado Ganado', 'Cerrado Perdido'}
    pipeline_details = []
    terminal_details = []
    total_pipeline = sum(pipeline_stages.values())
    prev_count = None
    first_stage_count = None

    for stage in STAGE_ORDER:
        curr_count = pipeline_stages.get(stage, 0)
        prev_count_in_pipeline = previous_pipeline.get(stage, None)
        is_terminal = stage in TERMINAL_STAGES_SET

        pct_of_total = round(curr_count / total_pipeline * 100, 1) if total_pipeline > 0 else 0

        if not is_terminal and first_stage_count is None:
            first_stage_count = curr_count

        conv_from_top = round(curr_count / first_stage_count * 100, 1) if first_stage_count and first_stage_count > 0 else None

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

    # Add extra stages not in order
    extra_stages = pipeline_stages.copy()
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

    return {
        'stage_order': STAGE_ORDER,
        'details': pipeline_details,
        'terminal': terminal_details,
        'active_total': total_pipeline - sum(s.get('count', 0) for s in terminal_details),
        'won_total': pipeline_stages.get('Cerrado Ganado', 0),
        'lost_total': pipeline_stages.get('Cerrado Perdido', 0),
        'total_pipeline': total_pipeline
    }

# ── Advisor-specific data generation ─────────────────────────
ADVISORS = [
    "Alberto Prieto",
    "Jaime Becerra",
    "Jose Orrequia",
]

def generate_advisor_data(advisor_name, contacts_all, deals_all, pf_records_all):
    """
    Generate complete CRM stats filtered to a single advisor.
    Returns a dict with the same structure as the main data file.
    """
    # Filter deals by this advisor
    advisor_deals = [d for d in deals_all if d.get('Owner') == advisor_name]
    advisor_deal_ids = {d['id'] for d in advisor_deals if d.get('id')}
    advisor_won_ids = {d['id'] for d in advisor_deals if 'Ganado' in (d.get('Stage') or '') and d.get('id')}
    
    # Filter product records: only those linked to this advisor's won deals
    advisor_pf = [pr for pr in pf_records_all 
                  if (pr.get('Parent_Id') or {}).get('id') in advisor_won_ids]
    
    # Filter contacts by this advisor
    # Primary method: find contact IDs linked to this advisor's deals (more reliable than Owner field)
    advisor_deal_contact_ids = set()
    for d in advisor_deals:
        cid = d.get('_contact_id')
        if cid:
            advisor_deal_contact_ids.add(cid)

    advisor_contacts = [c for c in contacts_all if c.get('id') in advisor_deal_contact_ids]
    # Fallback: if no deal-linked contacts, use Owner field
    if not advisor_contacts:
        advisor_contacts = [c for c in contacts_all if c.get('Owner') == advisor_name]

    # ── All-time stats (compact) ──
    closed_won = [d for d in advisor_deals if 'Ganado' in (d.get('Stage') or '')]
    closed_lost = [d for d in advisor_deals if 'Perdido' in (d.get('Stage') or '')]
    pipeline_val = sum(float(d.get('Amount', 0) or 0) for d in advisor_deals)
    total_aport = sum(float(d.get('Total_Aportaciones', 0) or 0) for d in advisor_deals)
    
    all_time = {
        "contacts": {
            "total": len(advisor_contacts),
            "with_email": sum(1 for c in advisor_contacts if c.get('Email')),
            "with_phone": sum(1 for c in advisor_contacts if c.get('Phone')),
            "by_owner": {advisor_name: len(advisor_contacts)},
        },
        "deals": {
            "total": len(advisor_deals),
            "by_stage": {},
            "by_owner": {advisor_name: len(advisor_deals)},
            "pipeline_value": pipeline_val,
            "total_aportaciones": total_aport,
            "avg_deal_size": round(pipeline_val / len(advisor_deals), 2) if advisor_deals else 0,
            "closed_won": len(closed_won),
            "closed_won_value": sum(float(d.get('Amount', 0) or 0) for d in closed_won),
            "closed_lost": len(closed_lost),
            "conversion_rate": round(len(closed_won) / len(advisor_deals) * 100, 1) if advisor_deals else 0,
        }
    }

    # Fill by_stage for Global
    for d in advisor_deals:
        stage = d.get('Stage', 'Sin etapa')
        all_time['deals']['by_stage'][stage] = all_time['deals']['by_stage'].get(stage, 0) + 1

    # ── Period stats (reuse compute_period_stats with filtered data) ──
    yesterday_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Ayer", in_yesterday)
    this_month_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Este Mes", in_this_month)

    # ── Same guard: evitar sobreescribir this_month con ceros en transición de mes ──
    # Also inherits when prev file has product_deals (even if won_deals=0)
    # This protects against Zoho API non-determinism where Closing_Date can change
    # between API calls, causing product_deals to disappear and break commission calc
    if this_month_stats['won_deals'] == 0 and this_month_stats['won_value'] == 0.0:
        adv_file = DATA_DIR / f'{advisor_name.lower().replace(" ", "-")}.json'
        if adv_file.exists():
            try:
                prev_adv = json.loads(adv_file.read_text())
                prev_adv_month = prev_adv.get('stats', {}).get('this_month', {})
                prev_has_data = (
                    prev_adv_month.get('won_deals', 0) > 0 or
                    len(prev_adv_month.get('product_deals', [])) > 0
                )
                if prev_has_data:
                    old_ts = prev_adv.get('generated_at', '')
                    old_month = old_ts[:7] if old_ts else ''
                    # Only inherit if old data is from the SAME calendar month
                    # (prevents leaking last month's deals into the new month's commission calc)
                    if old_month == THIS_MONTH:
                        this_month_stats = prev_adv_month
            except (json.JSONDecodeError, KeyError):
                pass
    this_quarter_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Este Trimestre", in_this_quarter)
    this_year_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Este Año", in_this_year)

    prev_yesterday_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Anteayer", in_prev_yesterday)
    prev_month_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Mes Anterior", in_prev_month)
    prev_quarter_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Trimestre Anterior", in_prev_quarter)
    prev_year_stats = compute_period_stats(advisor_contacts, advisor_deals, advisor_pf, "Año Anterior", in_prev_year)

    # ── Fill contacts_by_day from deals when real contact data unavailable ──
    # Zoho contact IDs may not match deal references, so fallback to deal creation dates
    stats_list = [
        (yesterday_stats, in_yesterday),
        (this_month_stats, in_this_month),
        (this_quarter_stats, in_this_quarter),
        (this_year_stats, in_this_year),
        (prev_yesterday_stats, in_prev_yesterday),
        (prev_month_stats, in_prev_month),
    ]
    for stats_obj, filter_fn in stats_list:
        if stats_obj.get('new_contacts', 0) == 0 and stats_obj.get('contacts_by_day', {}) == {}:
            # Build contacts_by_day from deals created in this period
            deal_by_day = {}
            for d in advisor_deals:
                created = d.get('Created_Time', '')
                if created and filter_fn(created):
                    day = created[8:10].lstrip('0') or '0'
                    deal_by_day[day] = deal_by_day.get(day, 0) + 1
            stats_obj['contacts_by_day'] = dict(sorted(deal_by_day.items(), key=lambda x: int(x[0])))
            stats_obj['new_contacts'] = sum(deal_by_day.values())
            # Also fill deals_by_day from the same deal data
            deals_day = {}
            for d in advisor_deals:
                created = d.get('Created_Time', '')
                if created and filter_fn(created):
                    day = created[8:10].lstrip('0') or '0'
                    deals_day[day] = deals_day.get(day, 0) + 1
            stats_obj['deals_by_day'] = dict(sorted(deals_day.items(), key=lambda x: int(x[0])))

    # ── Pipeline details ──
    this_month_pipeline = compute_pipeline_details(this_month_stats['pipeline_stages'])
    this_quarter_pipeline = compute_pipeline_details(this_quarter_stats['pipeline_stages'],
        prev_quarter_stats['pipeline_stages'] if prev_quarter_stats else {})
    this_year_pipeline = compute_pipeline_details(this_year_stats['pipeline_stages'],
        prev_year_stats['pipeline_stages'] if prev_year_stats else {})
    
    # ── Assemble ──
    slug = advisor_name.lower().replace(' ', '-')
    return {
        "advisor_name": advisor_name,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "generated_at": str(TODAY),
        "today": str(TODAY),
        "yesterday": str(YESTERDAY),
        "this_month": THIS_MONTH,
        "this_quarter_start": str(THIS_QUARTER_START),
        "this_quarter_end": str(THIS_QUARTER_END),
        "this_quarter_label": THIS_QUARTER_LABEL,
        "stats": {
            "all_time": all_time,
            "yesterday": yesterday_stats,
            "this_month": this_month_stats,
            "this_quarter": this_quarter_stats,
            "this_year": this_year_stats,
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
            },
            "this_quarter": {
                "previous_label": PREV_QUARTER_LABEL,
                "previous_start": str(PREV_QUARTER_START),
                "previous_end": str(PREV_QUARTER_END),
                "period_label": "trimestre anterior",
                "stats": prev_quarter_stats
            },
            "this_year": {
                "previous_label": str(PREV_YEAR_START) + " a " + str(PREV_YEAR_END),
                "previous_start": str(PREV_YEAR_START),
                "previous_end": str(PREV_YEAR_END),
                "period_label": "año anterior",
                "stats": prev_year_stats
            }
        },
        "deals": advisor_deals,
        "pipeline": {
            "stage_order": STAGE_ORDER,
            "yesterday": compute_pipeline_details(yesterday_stats['pipeline_stages']),
            "this_month": this_month_pipeline,
            "this_quarter": this_quarter_pipeline,
            "this_year": this_year_pipeline,
        }
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
        'Last_Activity_Time',
        'GCLID', 'GCLID1', 'FBCLID',
        'Referrer',
        'UTM_SOURCE', 'UTM_MEDIUM', 'UTM_CAMPAIGN', 'UTM_CONTENT', 'UTM_TERM'
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
    # Preserve contact ID before simplify() strips Contact_Name dict to just name string
    deals = []
    for d in deals_raw:
        simplified = simplify(d, deal_fields)
        cn = d.get('Contact_Name', {})
        if isinstance(cn, dict):
            simplified['_contact_id'] = cn.get('id')
        deals.append(simplified)
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

    # ── Productos Financieros (Entidades y Productos subtable) ──
    print("  Productos Financieros (Entidades y Productos)...")
    pf_records = fetch_all('Productos_Financieros')
    print(f"    -> {len(pf_records)} registros de productos")

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
            "conversion_rate": round(conversion_rate, 1),
            "lead_quality": {
                'ni_total': len([d for d in deals if 'Perdido' in (d.get('Stage') or '') and d.get('Motivo_de_cierre_perdido') == 'No interesado']),
                'na_total': len([d for d in deals if 'Perdido' in (d.get('Stage') or '') and d.get('Motivo_de_cierre_perdido') == 'No apareció']),
                'ni_na_total': len([d for d in deals if 'Perdido' in (d.get('Stage') or '') and d.get('Motivo_de_cierre_perdido') in ('No interesado', 'No apareció')]),
                'ni_na_7d': len([d for d in deals if 'Perdido' in (d.get('Stage') or '') and d.get('Motivo_de_cierre_perdido') in ('No interesado', 'No apareció') and (d.get('Sales_Cycle_Duration') or 999) <= 7]),
            }
        }
    }

    # ── Period stats ──
    yesterday_stats = compute_period_stats(
        contacts, deals, pf_records, "Ayer", in_yesterday
    )

    this_month_stats = compute_period_stats(
        contacts, deals, pf_records, "Este Mes", in_this_month
    )

    # ── Guard: evitar sobreescribir this_month con ceros en transición de mes ──
    # Si el nuevo mes no tiene deals ganados aún (ej: 1 de Junio vs deals de Mayo),
    # mantener los datos del mes anterior en this_month para no romper dashboards.
    if this_month_stats['won_deals'] == 0 and this_month_stats['won_value'] == 0.0:
        if DATA_FILE.exists():
            try:
                prev_data = json.loads(DATA_FILE.read_text())
                prev_month_data = prev_data.get('stats', {}).get('this_month', {})
                if prev_month_data.get('won_deals', 0) > 0:
                    old_ts = prev_data.get('generated_at', '')
                    old_month = old_ts[:7] if old_ts else ''
                    # Solo mantener si es del mismo mes (evita filtrar datos del mes anterior en el nuevo)
                    if old_month == THIS_MONTH:
                        print(f"\n  ⚠️ Transición de mes detectada: THIS_MONTH={THIS_MONTH} pero 0 deals ganados.")
                        print(f"     Manteniendo datos de {old_ts} (won_deals={prev_month_data['won_deals']}) para evitar ceros.")
                        print(f"     Los datos se actualizarán cuando se cierre el primer deal de {THIS_MONTH}.")
                        this_month_stats = prev_month_data
            except (json.JSONDecodeError, KeyError):
                pass

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

    # ── Quarter stats ──
    this_quarter_stats = compute_period_stats(
        contacts, deals, pf_records, "Este Trimestre", in_this_quarter
    )
    prev_quarter_stats = compute_period_stats(
        contacts, deals, pf_records, "Trimestre Anterior", in_prev_quarter
    )

    print(f"\nEste trimestre ({THIS_QUARTER_LABEL}: {THIS_QUARTER_START} a {THIS_QUARTER_END}):")
    print(f"   Nuevos contactos: {this_quarter_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {this_quarter_stats['new_deals']}")
    print(f"   Ofertas ganadas: {this_quarter_stats['won_deals']} (E{this_quarter_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {this_quarter_stats['lost_deals']}")
    print(f"   Productos cerrados: {len(this_quarter_stats['product_breakdown'])}")

    print(f"\nTrimestre anterior ({PREV_QUARTER_LABEL}: {PREV_QUARTER_START} a {PREV_QUARTER_END}):")
    print(f"   Nuevos contactos: {prev_quarter_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {prev_quarter_stats['new_deals']}")
    print(f"   Ofertas ganadas: {prev_quarter_stats['won_deals']} (E{prev_quarter_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {prev_quarter_stats['lost_deals']}")
    print(f"   Productos cerrados: {len(prev_quarter_stats['product_breakdown'])}")

    # ── Year stats ──
    this_year_stats = compute_period_stats(
        contacts, deals, pf_records, "Este Año", in_this_year
    )
    prev_year_stats = compute_period_stats(
        contacts, deals, pf_records, "Año Anterior", in_prev_year
    )

    print(f"\nEste año ({THIS_YEAR_START} a {THIS_YEAR_END}):")
    print(f"   Nuevos contactos: {this_year_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {this_year_stats['new_deals']}")
    print(f"   Ofertas ganadas: {this_year_stats['won_deals']} (E{this_year_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {this_year_stats['lost_deals']}")
    print(f"   Productos cerrados: {len(this_year_stats['product_breakdown'])}")

    print(f"\nAño anterior ({PREV_YEAR_START} a {PREV_YEAR_END}):")
    print(f"   Nuevos contactos: {prev_year_stats['new_contacts']}")
    print(f"   Nuevas ofertas: {prev_year_stats['new_deals']}")
    print(f"   Ofertas ganadas: {prev_year_stats['won_deals']} (E{prev_year_stats['won_value']:,.0f})")
    print(f"   Ofertas perdidas: {prev_year_stats['lost_deals']}")
    print(f"   Productos cerrados: {len(prev_year_stats['product_breakdown'])}")

    # ── Per-period pipeline details ──
    yesterday_pipeline = compute_pipeline_details(yesterday_stats['pipeline_stages'])
    this_month_pipeline = compute_pipeline_details(this_month_stats['pipeline_stages'], previous_pipeline)
    this_quarter_pipeline = compute_pipeline_details(this_quarter_stats['pipeline_stages'],
        prev_quarter_stats['pipeline_stages'] if prev_quarter_stats else {})
    this_year_pipeline = compute_pipeline_details(this_year_stats['pipeline_stages'],
        prev_year_stats['pipeline_stages'] if prev_year_stats else {})

# ── Assemble output ──
    data = {
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "generated_at": str(TODAY),
        "today": str(TODAY),
        "yesterday": str(YESTERDAY),
        "this_month": THIS_MONTH,
        "this_quarter_start": str(THIS_QUARTER_START),
        "this_quarter_end": str(THIS_QUARTER_END),
        "this_quarter_label": THIS_QUARTER_LABEL,
        "contacts": contacts,
        "deals": deals,
        "products": products,
        "tasks": tasks,
        "stats": {
            "all_time": all_time_stats,
            "yesterday": yesterday_stats,
            "this_month": this_month_stats,
            "this_quarter": this_quarter_stats,
            "this_year": this_year_stats,
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
            },
            "this_quarter": {
                "previous_label": PREV_QUARTER_LABEL,
                "previous_start": str(PREV_QUARTER_START),
                "previous_end": str(PREV_QUARTER_END),
                "period_label": "trimestre anterior",
                "stats": prev_quarter_stats
            },
            "this_year": {
                "previous_label": str(PREV_YEAR_START) + " a " + str(PREV_YEAR_END),
                "previous_start": str(PREV_YEAR_START),
                "previous_end": str(PREV_YEAR_END),
                "period_label": "año anterior",
                "stats": prev_year_stats
            }
        },
        "pipeline": {
            "stage_order": STAGE_ORDER,
            "yesterday": yesterday_pipeline,
            "this_month": this_month_pipeline,
            "this_quarter": this_quarter_pipeline,
            "this_year": this_year_pipeline,
            "previous_pipeline": previous_pipeline,
            "previous_value": previous_pipeline_value,
        }
    }
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nDatos guardados en {DATA_FILE}")
    print(f"   {len(contacts)} contactos | {len(deals)} ofertas | {len(products)} productos")
    print(f"   Pipeline: E{pipeline_value:,.0f} | Cerrados ganados: {closed_won_count} (E{closed_won_value:,.0f}) | Perdidos: {closed_lost_count}")

    # ── Generate per-advisor JSON files ──
    print("\nGenerando datos por asesor...")
    for advisor in ADVISORS:
        slug = advisor.lower().replace(' ', '-')
        adv_file = DATA_DIR / f'{slug}.json'
        try:
            adv_data = generate_advisor_data(advisor, contacts, deals, pf_records)
            # Backup previous file before overwriting (protects against Zoho API non-determinism)
            if adv_file.exists():
                bak_file = DATA_DIR / f'{slug}.bak.json'
                bak_file.write_text(adv_file.read_text())
            adv_file.write_text(json.dumps(adv_data, indent=2, ensure_ascii=False))
            all_s = adv_data['stats']
            print(f"   {advisor}: {all_s['all_time']['deals']['total']} ofertas, {all_s['all_time']['contacts']['total']} contactos → {adv_file.name}")
        except Exception as e:
            print(f"   ERROR {advisor}: {e}")

if __name__ == '__main__':
    main()
