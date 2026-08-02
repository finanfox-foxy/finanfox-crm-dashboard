"""
Zoho CRM Data Extractor — Tests
Run with: python3 -m pytest scripts/test_zoho_extract.py -v
"""
import sys, os, json, tempfile, importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

# Load the module despite the hyphen in filename
spec = importlib.util.spec_from_file_location("zoho_crm_extract", 
    os.path.join(os.path.dirname(__file__), "zoho-crm-extract.py"))
mod = importlib.util.module_from_spec(spec)
# Set env vars before loading
os.environ['ZOHO_CLIENT_ID'] = 'test_id'
os.environ['ZOHO_CLIENT_SECRET'] = 'test_secret'
os.environ['ZOHO_REFRESH_TOKEN'] = 'test_token'
spec.loader.exec_module(mod)
# Register for @patch decorators to find it
import sys
sys.modules['zoho_crm_extract'] = mod

# ── Timezone tests ──
def test_spain_today_returns_date():
    date = mod.spain_today()
    assert date is not None
    assert hasattr(date, 'year')

def test_spain_today_uses_zoneinfo():
    """Verify the function doesn't crash"""
    date = mod.spain_today()
    assert date is not None

# ── Date helper tests ──
def test_in_this_month():
    assert mod.in_this_month(f"{mod.THIS_MONTH}-15") == True
    year = mod.THIS_MONTH[:4]
    other_month = "01" if mod.THIS_MONTH[5:7] != "01" else "02"
    assert mod.in_this_month(f"{year}-{other_month}-15") == False

def test_in_yesterday():
    assert mod.in_yesterday(str(mod.YESTERDAY)) == True
    assert mod.in_yesterday("2020-01-01") == False

# ── Quarter helper tests ──
def test_quarter_dates():
    from datetime import date
    q, start, end = mod._quarter_dates(date(2026, 5, 15))
    assert q == "Q2"
    assert start.month == 4
    assert end.month == 6

def test_prev_quarter_dates():
    from datetime import date
    q, start, end = mod._prev_quarter_dates(date(2026, 5, 15))
    assert q == "Q1"
    assert start.month == 1
    assert end.month == 3

def test_prev_quarter_q1():
    """Q1 -> previous should be Q4 of previous year"""
    from datetime import date
    q, start, end = mod._prev_quarter_dates(date(2026, 2, 15))
    assert q == "Q4"
    assert start.year == 2025
    assert start.month == 10
    assert end.month == 12
    assert end.year == 2025

# ── API helper tests ──
@patch('zoho_crm_extract.requests.post')
def test_get_access_token(mock_post):
    mock_post.return_value.json.return_value = {'access_token': 'test_token_123'}
    token = mod.get_access_token(force=True)
    assert token == 'test_token_123'

@patch('zoho_crm_extract.requests.get')
def test_api_get_200(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {'data': [{'id': '1'}]}
    result = mod.api_get('Contacts', {'page': 1})
    assert 'data' in result
    assert len(result['data']) == 1

@patch('zoho_crm_extract.requests.get')
def test_api_get_429_retry(mock_get):
    """Should retry on 429"""
    mock_response_429 = MagicMock()
    mock_response_429.status_code = 429
    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {'data': []}
    mock_get.side_effect = [mock_response_429, mock_response_200]
    result = mod.api_get('Contacts', {'page': 1})
    assert 'data' in result
    assert mock_get.call_count == 2

@patch('zoho_crm_extract.requests.get')
def test_api_get_204(mock_get):
    mock_get.return_value.status_code = 204
    result = mod.api_get('Contacts')
    assert result == {"data": []}

# ── Fetch all tests ──
@patch('zoho_crm_extract.api_get')
def test_fetch_all_single_page(mock_api_get):
    mock_api_get.return_value = {'data': [{'id': '1'}, {'id': '2'}], 'info': {'more_records': False}}
    result = mod.fetch_all('Contacts')
    assert len(result) == 2

@patch('zoho_crm_extract.api_get')
def test_fetch_all_max_pages(mock_api_get):
    """Should stop at MAX_PAGES (500)"""
    page = {'data': [{'id': str(i)} for i in range(200)], 'info': {'more_records': True}}
    mock_api_get.return_value = page
    result = mod.fetch_all('Contacts')
    assert len(result) <= 100000

# ── Simplify tests ──
def test_simplify():
    record = {
        'id': '123', 'Full_Name': 'Test User',
        'Owner': {'name': 'Alberto Prieto', 'id': '456'},
        'Tag': [{'name': 'VIP'}, {'name': 'Nuevo'}],
        'Amount': 1000.0
    }
    result = mod.simplify(record, ['id', 'Full_Name', 'Owner', 'Tag', 'Amount'])
    assert result['id'] == '123'
    assert result['Owner'] == 'Alberto Prieto'
    assert result['Tag'] == ['VIP', 'Nuevo']
    assert result['Amount'] == 1000.0

# ── Close date tests ──
def test_close_or_create():
    d = {'Closing_Date': '2026-07-15T10:00:00+02:00', 'Created_Time': '2026-06-01T08:00:00Z'}
    assert mod._close_or_create(d) == '2026-07-15T10:00:00+02:00'

def test_close_or_create_fallback():
    d = {'Created_Time': '2026-06-01T08:00:00Z'}
    assert mod._close_or_create(d) == '2026-06-01T08:00:00Z'

# ── Compute period stats structure ──
def test_compute_period_stats_structure():
    result = mod.compute_period_stats([], [], [], "Test", lambda x: True)
    expected_keys = ['label', 'new_contacts', 'new_deals', 'won_deals', 'lost_deals',
                     'won_value', 'total_aportacion_won', 'product_breakdown',
                     'product_count', 'product_details', 'product_deals',
                     'advisor_ranking_won', 'advisor_ranking_aportacion',
                     'pipeline_stages', 'pipeline_value', 'win_rate',
                     'avg_days_to_win', 'products_closed_count',
                     'conversion_clientes', 'contacts_by_day', 'deals_by_day',
                     'lead_quality']
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"

# ── Error handling tests ──
@patch('zoho_crm_extract.requests.get')
def test_api_get_timeout(mock_get):
    import requests
    mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
    result = mod.api_get('Contacts', {'page': 1})
    assert 'error' in result

@patch('zoho_crm_extract.api_get')
def test_fetch_all_error(mock_api_get):
    mock_api_get.return_value = {'error': 'Timeout after retries'}
    result = mod.fetch_all('Contacts')
    assert result == []
