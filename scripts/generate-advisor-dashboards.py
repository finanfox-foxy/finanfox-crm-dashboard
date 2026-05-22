#!/usr/bin/env python3
"""
Generate 3 per-advisor CRM dashboard HTML files from the main index.html.
Uses line-by-line precise string replacement.
"""

from pathlib import Path

ADVISORS = [
    ("Alberto Prieto", "alberto-prieto"),
    ("Jaime Becerra", "jaime-becerra"),
    ("Jose Orrequia", "jose-orrequia"),
]

REPO_DIR = Path(__file__).parent.parent
INDEX_FILE = REPO_DIR / "index.html"

def generate_html(advisor_name, slug):
    html = INDEX_FILE.read_text(encoding='utf-8')

    # 1. Change title
    html = html.replace(
        '<title>CRM Dashboard - Finanfox 🦊</title>',
        f'<title>{advisor_name} - CRM Dashboard 🦊</title>'
    )
    html = html.replace(
        '<h1>🦊 <span>CRM</span> Dashboard</h1>',
        f'<h1>🦊 <span>{advisor_name}</span></h1>'
    )

    # 2. Change data source (BOTH fetches use the same path)
    html = html.replace('data/zoho-crm.json?_=', f'data/{slug}.json?_=')

    # 3. Remove the Ayer tab button (unique string)
    html = html.replace(
        '<button class="tab-btn active" data-tab="ayer" onclick="switchTab(\'ayer\')">📅 Ayer</button>',
        ''
    )

    # 4. Make "Este Mes" the default active tab (replace class on the button)
    html = html.replace(
        '<button class="tab-btn" data-tab="this_month"',
        '<button class="tab-btn active" data-tab="this_month"'
    )

    # 5. Remove the ENTIRE Ayer panel — from <!-- Ayer --> to just before <!-- Este Mes -->
    # Using the HTML comment markers
    MARKER_START = '<!-- Ayer -->'
    MARKER_END = '<!-- Este Mes -->'
    idx_start = html.find(MARKER_START)
    idx_end = html.find(MARKER_END)
    if idx_start >= 0 and idx_end >= 0:
        html = html[:idx_start] + html[idx_end:]
    else:
        print(f"  WARNING: Could not find Ayer panel markers for {advisor_name}")

    # 6. Remove the app-tab-bar (Ventas/Financiero switcher) — the whole div
    # Find it by the unique content
    app_tab_marker = 'class="app-tab-bar" id="app-tab-bar"'
    idx = html.find(app_tab_marker)
    if idx >= 0:
        # Go back to find the opening <div
        div_start = html.rfind('<div', 0, idx)
        # The app-tab-bar is: <div class="app-tab-bar" id="app-tab-bar"><button...>...Ventas...Financiero...</button></div>
        # It's followed immediately by the ventas panel. Find the </div> that closes the app-tab-bar
        # The bar has 2 buttons in it, so the structure is: <div>...</div>  (inner) + </div> (outer)
        # Actually looking at the source: <div class="app-tab-bar" id="app-tab-bar">
        #   <button class="app-tab-btn active" data-app="ventas" onclick="switchAppTab('ventas')">📊 Ventas</button>
        #   <button class="app-tab-btn" data-app="financiero" onclick="switchAppTab('financiero')">💰 Financiero</button>
        # </div>
        # So the closing </div> is one level deep
        if div_start >= 0:
            # The bar has buttons, each button is inline (no inner divs), so the first </div> closes the bar
            close_div = html.find('</div>', idx)
            if close_div >= 0:
                html = html[:div_start] + html[close_div + 6:]

    # 7. Remove the ENTIRE Financiero panel — from <!-- ===== FINANCIERO PANEL ===== --> to just before <div class="last-updated">
    FIN_START = '<!-- ===== FINANCIERO PANEL (sub-tabs) ===== -->'
    FIN_END = '<div class="last-updated">'
    idx_start = html.find(FIN_START)
    idx_end = html.find(FIN_END)
    if idx_start >= 0 and idx_end >= 0:
        html = html[:idx_start] + html[idx_end:]
    else:
        print(f"  WARNING: Could not find Financiero panel for {advisor_name}")

    # 8. Remove financial JS variable
    html = html.replace('var currentFinancialData = null;', '')
    
    # 9. Remove renderFinancialTab() call
    html = html.replace('            renderFinancialTab();', '')

    # 10. Remove the financial data fetch code — very precise
    # The financial fetch code is embedded in the DOMContentLoaded handler.
    # Find and remove the specific lines
    
    # In refreshData():
    #     var finFetch = fetch('data/financial_data.json?_=' + Date.now())
    #         .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    #         .then(function(d) { currentFinancialData = d; });
    # And in DOMContentLoaded (same block)
    # Plus the Promise.all wrapper
    
    # Remove 'var finFetch = ...' from refreshData
    html = html.replace("""    var finFetch = fetch('data/financial_data.json?_=' + Date.now())
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(d) { currentFinancialData = d; });
    Promise.all([zohoFetch, finFetch])
        .then(function(results) {
            loadData(results[0]);
            renderFinancialTab();
        })
        .catch(function(e) { showError('Error al cargar datos: ' + e.message); });""",
        """    
    zohoFetch
        .then(function(data) {
            loadData(data);
        })
        .catch(function(e) { showError('Error al cargar datos: ' + e.message); });""")

    # Remove the same pattern from DOMContentLoaded
    html = html.replace("""    var finFetch = fetch('data/financial_data.json?_=' + Date.now())
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function(d) { currentFinancialData = d; });
    Promise.all([zohoFetch, finFetch])
        .then(function(results) {
            loadData(results[0]);
            renderFinancialTab();
        })""",
        """    
    zohoFetch
        .then(function(data) {
            loadData(data);
        })""")

    # 11. Remove the renderFinancialTab and related financial functions
    # Find the section from "function renderFinancialTab()" to before "function refreshData()"
    # But keep the last-updated part
    html = html.replace("""    // Remove unused financial functions
function renderFinancialTab() {""", '// No financial tab for advisor dashboard\nfunction _unused() {')
    # Actually, let me remove the whole financial JS block
    # Find: "var currentFinancialData = null;" → already removed
    # Find: "function renderFinancialTab()" to "function refreshData()"
    
    fn_start = html.find('function renderFinancialTab()')
    fn_end = html.find('function refreshData()')
    if fn_start >= 0 and fn_end >= 0:
        # Remove everything from renderFinancialTab function declaration to before refreshData
        html = html[:fn_start] + html[fn_end:]
    else:
        print(f"  WARNING: Could not remove financial JS functions for {advisor_name}")

    # 12. Remove the ventas panel closing and last updated sections (they were duplicated)
    # Check for duplicate last-updated sections
    # Clean up extra whitespace
    html = html.replace('\n\n\n\n\n', '\n\n')

    return html

def main():
    for name, slug in ADVISORS:
        out_file = REPO_DIR / f'{slug}.html'
        html = generate_html(name, slug)
        out_file.write_text(html, encoding='utf-8')
        size = len(html)
        print(f"✅ {out_file.name} — {size:,} bytes ({name})")

if __name__ == '__main__':
    main()