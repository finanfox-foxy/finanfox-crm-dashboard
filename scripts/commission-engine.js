/**
 * COMMISSION_ENGINE — Lógica de comisiones compartida
 * 
 * Único punto de verdad para el cálculo de comisiones de asesores.
 * Cargado por index.html y los 3 HTMLs de asesores.
 * 
 * Cambia aquí → se actualiza en todos los dashboards.
 */

var COMMISSION_TABLE = [
    { keywords: ['monefit'], product: 'Monefit', partner: 'MONEFIT', min: 100000, rate: 0.0023 },
    { keywords: ['neowintech', 'neowin'], product: 'Neowintech', partner: 'NEOWINTECH', min: 157500, rate: 0.0013 },
    // Entity-based entries: match by partner/entity name (any product from this partner)
    { entityKeywords: ['silvergold', 'silver gold', 'sg '], product: 'SilverGold', partner: 'SILVERGOLD', min: 132750, rate: 0.0057 },
    { entityKeywords: ['monefit', 'creditstar'], product: 'Monefit', partner: 'MONEFIT', min: 100000, rate: 0.0023 },
    { entityKeywords: ['neowintech', 'neowin'], product: 'Neowintech', partner: 'NEOWINTECH', min: 157500, rate: 0.0013 },
    { entityKeywords: ['reental'], product: 'Reental', partner: 'REENTAL', min: 60000, rate: 0.0042 },
    { entityKeywords: ['crowmie'], product: 'Crowmie', partner: 'CROWMIE', min: 80000, rate: 0.0024 },
    { entityKeywords: ['aegon'], product: 'Aportación anual PIAS', partner: 'AEGON', min: 4500, rate: 0.0663 },
    { entityKeywords: ['mapfre'], product: 'Aportación anual PIAS Elección', partner: 'MAPFRE', min: 40000, rate: 0.0042 },
    { entityKeywords: ['santalucia', 'santa lucí', 'santa lu'], product: 'Aportación anual PIAS', partner: 'SANTALUCÍA', min: 40000, rate: 0.0042 },
    { entityKeywords: ['the real money', 'real money', 'trm'], product: 'Cuenta Depósito bonificado', partner: 'THE REAL MONEY', min: 65000, rate: 0.009 },
    // APEX (Aportación Extraordinaria) — producto separado con su propio objetivo (500K) y comisión 0.04%
    { productKeywords: ['apex', 'aportación extraordinaria', 'aportacion extraordinaria'], product: 'APEX PIAS/UL', partner: 'AEGON', min: 500000, rate: 0.0004 },
    // Specific product-name entries (fallback when entity unknown)
    { productKeywords: ['unit-linked', 'unit linked', 'u-l ', 'ul '], product: 'Unit-Linked Prima única', partner: 'AEGON', min: 15000, rate: 0.0049 },
    { productKeywords: ['pias estrategia', 'pias selección', 'pias elección', 'pias eleccion', 'pias '], product: 'Aportación anual PIAS', partner: 'AEGON', min: 4500, rate: 0.0663 },
    { productKeywords: ['seguro de vida', 'vida', 'crecivida'], product: 'Prima neta Seguro de Vida', partner: 'AEGON', min: 4350, rate: 0.15 },
    { productKeywords: ['cuenta depósito bonificada', 'cuenta deposito bonificada', 'cuenta depósito', 'cuenta deposito'], product: 'Cuenta Depósito bonificado', partner: 'THE REAL MONEY', min: 65000, rate: 0.009 },
    { productKeywords: ['gold opportunity', 'gold opp'], product: 'Gold Opportunity', partner: 'THE REAL MONEY', min: 65000, rate: 0.009 },
];

function findCommission(productName, entityName) {
    var entLower = (entityName || '').toLowerCase();
    var prodLower = (productName || '').toLowerCase();
    // First try match by product name (more specific — e.g. APEX vs generic Aegon PIAS)
    for (var i = 0; i < COMMISSION_TABLE.length; i++) {
        var pk = COMMISSION_TABLE[i].productKeywords;
        if (pk) {
            for (var j = 0; j < pk.length; j++) {
                if (prodLower.indexOf(pk[j]) !== -1) {
                    return COMMISSION_TABLE[i];
                }
            }
        }
    }
    // Fallback: match by entity/partner name
    for (var i = 0; i < COMMISSION_TABLE.length; i++) {
        var ek = COMMISSION_TABLE[i].entityKeywords;
        if (ek) {
            for (var j = 0; j < ek.length; j++) {
                if (entLower.indexOf(ek[j]) !== -1) {
                    return COMMISSION_TABLE[i];
                }
            }
        }
    }
    return null;
}

function normalizeProduct(producto, entidad) {
    var e = (entidad || '').toLowerCase();
    var p = (producto || '').toLowerCase();
    if (p.indexOf('apex') >= 0 || e.indexOf('apex') >= 0) return 'APEX';
    if (e.indexOf('silvergold') >= 0 || e.indexOf('silver gold') >= 0) return 'SilverGold';
    if (e.indexOf('the real money') >= 0 || e.indexOf('real money') >= 0 || e.indexOf('trm') >= 0) return 'TRM';
    if (e.indexOf('monefit') >= 0) return 'Monefit';
    if (e.indexOf('aegon') >= 0) return 'PIAS';
    if (e.indexOf('neowintech') >= 0) return 'Neowintech';
    if (e.indexOf('reental') >= 0) return 'Reental';
    if (e.indexOf('crowmie') >= 0) return 'Crowmie';
    if (e.indexOf('santalucia') >= 0 || e.indexOf('santa lu') >= 0) return 'PIAS Santalucía';
    if (e.indexOf('mapfre') >= 0) return 'PIAS Mapfre';
    if (p.indexOf('monefit') >= 0) return 'Monefit';
    if (p.indexOf('compra ') >= 0 || p.indexOf('silvergold') >= 0 || p.indexOf('ccu') >= 0) return 'SilverGold';
    if (p.indexOf('pias') >= 0) return 'PIAS';
    if (p.indexOf('cuenta dep') >= 0 || p.indexOf('gold opportunity') >= 0 || p.indexOf('dep') >= 0) return 'TRM';
    if (p.indexOf('neowin') >= 0) return 'Neowintech';
    if (p.indexOf('reental') >= 0) return 'Reental';
    if (p.indexOf('crowmie') >= 0) return 'Crowmie';
    return producto;
}

var PRODUCT_ENTITY_MAP = {
    'apex': 'Aegon',
    'compra única': 'SilverGold',
    'compra unica': 'SilverGold',
    'silvergold': 'SilverGold',
    'sg': 'SilverGold',
    'trm': 'The Real Money',
    'the real money': 'The Real Money',
    'gold opportunity': 'The Real Money',
    'cuenta depósito': 'The Real Money',
    'cuenta deposito': 'The Real Money',
    'monefit': 'Monefit',
    'reental': 'Reental',
    'crowmie': 'Crowmie',
    'neowintech': 'Neowintech',
    'pias': 'Aegon',
    'unit-linked': 'Aegon',
    'unit linked': 'Aegon',
    'seguro de vida': 'Aegon',
    'vida': 'Aegon',
    'crecivida': 'Aegon',
};

function guessEntity(productName) {
    var lower = (productName || '').toLowerCase();
    for (var key in PRODUCT_ENTITY_MAP) {
        if (lower.indexOf(key) !== -1) {
            return PRODUCT_ENTITY_MAP[key];
        }
    }
    return '';
}

function inferProduct(name) {
    var n = (name || '').toLowerCase();
    if (n.indexOf('monefit') >= 0) return 'Monefit';
    if (n.indexOf('apex') >= 0) return 'APEX';
    if (n.indexOf('pias') >= 0 || n.indexOf('estrategia') >= 0) return 'PIAS';
    if (n.indexOf('trm') >= 0 || n.indexOf('gold opp') >= 0 || n.indexOf('gold oport') >= 0 || n.indexOf('cuenta gold') >= 0) return 'TRM';
    if (n.indexOf('depósito') >= 0 || n.indexOf('cuenta deposito') >= 0) return 'Cuenta Depósito';
    if (n.indexOf('compra única') >= 0 || n.indexOf('compra unica') >= 0 || n.indexOf('compra experta') >= 0 || n.indexOf(' cu ') >= 0) return 'Compra Única';
    if (n.indexOf('planificacion') >= 0 || n.indexOf('planificación') >= 0 || n.indexOf('plan financ') >= 0) return 'Planificación Financiera';
    if (n.indexOf('silvergold') >= 0 || n.indexOf(' sg ') >= 0 || n.indexOf('sg ') >= 0 || n.indexOf('sg-') >= 0 || n.indexOf('ccu') >= 0 || n.indexOf('opportunity') >= 0 || n.indexOf('oportunity') >= 0) return 'SilverGold';
    if (n.indexOf('crowdfunding') >= 0 || n.indexOf('proyecto') >= 0) return 'Crowdfunding';
    return 'Otros';
}

/**
 * Calculate commissions for a list of deals sorted chronologically.
 * @param {Array} deals - Array of { producto, entidad, total, close_date, cliente }
 * @returns {Object} { dealsWithMeta, totalCommission, cumulativePct, thresholdReachedAt }
 */
function calculateCommissions(deals) {
    if (!deals || deals.length === 0) {
        return { dealsWithMeta: [], totalCommission: 0, cumulativePct: 0, thresholdReachedAt: -1 };
    }
    var sorted = deals.slice().sort(function(a, b) { return a.close_date.localeCompare(b.close_date); });
    var cumulativePct = 0;
    var thresholdReachedAt = -1;
    var dealsWithMeta = [];
    sorted.forEach(function(d, idx) {
        var entity = d.entidad || guessEntity(d.producto);
        var commissionInfo = findCommission(d.producto, entity);
        var minAmount = commissionInfo ? commissionInfo.min : null;
        var pct = (minAmount && minAmount > 0) ? (d.total / minAmount) : 0;
        cumulativePct += pct;
        if (cumulativePct >= 1.0 && thresholdReachedAt === -1) {
            thresholdReachedAt = idx;
        }
        var normProduct = normalizeProduct(d.producto, entity);
        dealsWithMeta.push({
            cliente: d.cliente || '',
            producto: normProduct,
            entidad: entity,
            total: d.total,
            min: minAmount,
            rate: commissionInfo ? commissionInfo.rate : 0,
            pct: pct,
            close_date: d.close_date || ''
        });
    });
    var totalCommission = 0;
    dealsWithMeta.forEach(function(item, idx) {
        if (thresholdReachedAt < 0) {
            item.commission = 0;
        } else if (idx > thresholdReachedAt) {
            item.commission = item.total * item.rate;
            totalCommission += item.commission;
        } else if (idx === thresholdReachedAt) {
            var cumBefore = 0;
            for (var k = 0; k < idx; k++) { cumBefore += dealsWithMeta[k].pct; }
            var remainingPct = Math.max(0, 1.0 - cumBefore);
            var objectiveAmount = remainingPct * item.min;
            var commPortion = Math.max(0, item.total - objectiveAmount);
            item.commission = commPortion * item.rate;
            totalCommission += item.commission;
        } else {
            item.commission = 0;
        }
    });
    return { dealsWithMeta: dealsWithMeta, totalCommission: totalCommission, cumulativePct: cumulativePct, thresholdReachedAt: thresholdReachedAt };
}

/**
 * Safe fetch with timeout and error handling.
 * @param {string} url - URL to fetch
 * @param {number} timeoutMs - Timeout in ms (default 10000)
 * @returns {Promise} Parsed JSON response
 */
function safeFetch(url, timeoutMs) {
    timeoutMs = timeoutMs || 10000;
    return new Promise(function(resolve, reject) {
        var controller = new AbortController();
        var timer = setTimeout(function() { controller.abort(); }, timeoutMs);
        fetch(url, { signal: controller.signal })
            .then(function(r) {
                clearTimeout(timer);
                if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
                return r.json();
            })
            .then(resolve)
            .catch(function(err) {
                clearTimeout(timer);
                reject(err);
            });
    });
}