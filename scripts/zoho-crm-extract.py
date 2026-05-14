#!/usr/bin/env python3
"""
Zoho CRM Data Extractor for GitHub Actions
Reads credentials from environment variables (GitHub Secrets).
Outputs data to data/zoho-crm.json for GitHub Pages.
"""

import os, sys, json, time, requests
from pathlib import Path

# Credentials from environment
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

def get_access_token():
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
    return data['access_token']

def api_get(module, params=None):
    token = get_access_token()
    url = f"{API_DOMAIN}/crm/v2/{module}"
    r = requests.get(url, headers={'Authorization': f'Zoho-oauthtoken {token}'}, params=params)
    if r.status_code == 204:
        return {"data": []}
    try:
        return r.json()
    except:
        return {"error": f"HTTP {r.status_code}"}

def fetch_all(module):
    all_records = []
    page = 1
    while True:
        r = api_get(module, {'per_page': 200, 'page': page})
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

def main():
    print("🔄 Extrayendo datos de Zoho CRM...")

    # Contacts
    print("  📋 Contactos...")
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
    print(f"    → {len(contacts)} contactos")

    # Deals
    print("  💰 Ofertas...")
    deals_raw = fetch_all('Deals')
    deal_fields = [
        'id', 'Deal_Name', 'Amount', 'Stage', 'Probability',
        'Contact_Name', 'Owner', 'Type', 'Total_Aportaciones',
        'Total_Suscripci_n', 'Motivo_de_cierre_perdido', 'Fuente',
        'Created_Time', 'Closing_Date', 'Tag', 'Lead_Conversion_Time',
        'Overall_Sales_Duration', 'Sales_Cycle_Duration'
    ]
    deals = [simplify(d, deal_fields) for d in deals_raw]
    print(f"    → {len(deals)} ofertas")

    # Products
    print("  📦 Productos...")
    products_raw = fetch_all('Products')
    product_fields = ['id', 'Product_Name', 'Product_Code', 'Unit_Price', 'Description']
    products = [simplify(p, product_fields) for p in products_raw]
    print(f"    → {len(products)} productos")

    # Tasks
    print("  📝 Tareas...")
    tasks_raw = fetch_all('Tasks')
    task_fields = ['id', 'Subject', 'Status', 'Priority', 'Owner', 'Due_Date', 'Created_Time']
    tasks = [simplify(t, task_fields) for t in tasks_raw]
    print(f"    → {len(tasks)} tareas")

    # Statistics
    print("  📊 Calculando estadísticas...")
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

    avg_deal_size = pipeline_value / len(deals) if deals else 0
    conversion_rate = (closed_won_count / len(deals) * 100) if deals else 0

    data = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        "contacts": contacts,
        "deals": deals,
        "products": products,
        "tasks": tasks,
        "stats": {
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
                "conversion_rate": round(conversion_rate, 1)
            }
        }
    }

    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n✅ Datos guardados en {DATA_FILE}")
    print(f"   {len(contacts)} contactos | {len(deals)} ofertas | {len(products)} productos")
    print(f"   Pipeline: €{pipeline_value:,.0f} | Cerrados ganados: {closed_won_count} (€{closed_won_value:,.0f})")

if __name__ == '__main__':
    main()