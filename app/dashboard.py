"""Interactive modern web client for Urja Meter Ops.

Served at / and /dashboard as an optional extension that provides:
  - Real-time KPI summaries across all 403 meters, 40 transformers, and 29 feeders
  - Interactive Leaflet geospatial map plotting meters across Jaipur with status-based coloring
  - Proximity search slider leveraging /api/v1/meters/nearby
  - Chart.js 30-minute interval energy consumption viewer with voltage profiling
  - Collapsible Network Hierarchy Tree (Zone -> Circle -> Division -> Feeder -> DT -> Meters)
  - Multi-attribute query table with instant filtering (Make, Phase, Status, DT)
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Flock Energy — Urja Meter Ops Explorer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <!-- Leaflet CSS for Map -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
  <!-- Leaflet JS -->
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <!-- Chart.js for 30-minute load curve -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>

  <style>
    :root {
      --bg-dark: #0a0f1d;
      --card-bg: #121929;
      --card-border: rgba(255, 255, 255, 0.08);
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-glow: rgba(56, 189, 248, 0.15);
      --emerald: #10b981;
      --rose: #f43f5e;
      --amber: #f59e0b;
      --indigo: #6366f1;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-dark);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* Header */
    header {
      background: rgba(18, 25, 41, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 1000;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .brand-icon {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1.1rem;
      color: white;
      box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
    }
    .brand-title h1 {
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .brand-title p {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .header-links {
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    .api-badge {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.8rem;
      padding: 0.35rem 0.75rem;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
    }
    .dot {
      width: 8px;
      height: 8px;
      background: #34d399;
      border-radius: 50%;
      box-shadow: 0 0 8px #34d399;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.9); }
    }

    .btn {
      font-size: 0.8rem;
      padding: 0.4rem 0.85rem;
      border-radius: 6px;
      text-decoration: none;
      font-weight: 500;
      transition: all 0.2s ease;
      cursor: pointer;
      border: none;
    }
    .btn-outline {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--card-border);
      color: var(--text-main);
    }
    .btn-outline:hover {
      background: rgba(255, 255, 255, 0.1);
      border-color: rgba(255, 255, 255, 0.2);
    }
    .btn-primary {
      background: #0284c7;
      color: white;
    }
    .btn-primary:hover {
      background: #0369a1;
    }

    /* Container */
    .container {
      max-width: 1400px;
      width: 100%;
      margin: 0 auto;
      padding: 1.5rem 2rem;
      flex: 1;
    }

    /* KPI Grid */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .kpi-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1.25rem;
      position: relative;
      overflow: hidden;
      transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .kpi-card:hover {
      transform: translateY(-2px);
      border-color: rgba(255, 255, 255, 0.15);
    }
    .kpi-label {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.4rem;
    }
    .kpi-value {
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .kpi-sub {
      font-size: 0.75rem;
      margin-top: 0.35rem;
      display: flex;
      align-items: center;
      gap: 0.25rem;
    }

    /* Navigation Tabs */
    .nav-tabs {
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 1.5rem;
    }
    .tab-btn {
      padding: 0.65rem 1.25rem;
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      position: relative;
      transition: color 0.2s ease;
    }
    .tab-btn:hover { color: var(--text-main); }
    .tab-btn.active {
      color: var(--primary);
    }
    .tab-btn.active::after {
      content: '';
      position: absolute;
      bottom: -1px;
      left: 0;
      right: 0;
      height: 2px;
      background: var(--primary);
      box-shadow: 0 0 10px var(--primary);
    }

    /* Tab Content Panels */
    .tab-panel {
      display: none;
      animation: fadeIn 0.25s ease;
    }
    .tab-panel.active { display: block; }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Map Section */
    .map-controls {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px 8px 0 0;
      padding: 0.75rem 1rem;
      border-bottom: none;
    }
    .map-legend {
      display: flex;
      gap: 1rem;
      font-size: 0.8rem;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }
    .legend-color {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }
    #map-container {
      height: 520px;
      width: 100%;
      border-radius: 0 0 8px 8px;
      border: 1px solid var(--card-border);
      overflow: hidden;
    }

    /* Consumption Section */
    .consumption-bar {
      display: flex;
      gap: 1rem;
      align-items: center;
      flex-wrap: wrap;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 1rem;
      margin-bottom: 1rem;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
    }
    .form-group label {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    input, select {
      background: rgba(10, 15, 29, 0.8);
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 0.45rem 0.75rem;
      border-radius: 6px;
      font-size: 0.85rem;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--primary);
    }
    .chart-wrapper {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 1.5rem;
      height: 480px;
      position: relative;
    }

    /* Hierarchy Tree */
    .tree-box {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 1.5rem;
      max-height: 650px;
      overflow-y: auto;
    }
    .tree-node {
      margin-left: 1.25rem;
      padding: 0.25rem 0;
      border-left: 1px dashed rgba(255, 255, 255, 0.1);
      position: relative;
    }
    .tree-node::before {
      content: '';
      position: absolute;
      left: 0;
      top: 0.85rem;
      width: 0.75rem;
      border-bottom: 1px dashed rgba(255, 255, 255, 0.1);
    }
    .tree-header {
      padding-left: 1rem;
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      cursor: pointer;
      user-select: none;
      font-size: 0.88rem;
    }
    .tree-header:hover { color: var(--primary); }
    .badge {
      font-size: 0.7rem;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      font-family: 'JetBrains Mono', monospace;
    }
    .badge-zone { background: rgba(99, 102, 241, 0.2); color: #818cf8; }
    .badge-feeder { background: rgba(2, 132, 199, 0.2); color: #38bdf8; }
    .badge-dt { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
    .badge-installed { background: rgba(16, 185, 129, 0.2); color: #34d399; }
    .badge-faulty { background: rgba(244, 63, 94, 0.2); color: #fb7185; }
    .badge-decommissioned { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; }

    /* Meter Table */
    .table-container {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      overflow: hidden;
    }
    .table-filters {
      padding: 1rem;
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
      background: rgba(255, 255, 255, 0.02);
      border-bottom: 1px solid var(--card-border);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.85rem;
    }
    th, td {
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--card-border);
    }
    th {
      background: rgba(255, 255, 255, 0.02);
      color: var(--text-muted);
      font-weight: 500;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.05em;
    }
    tr:hover td {
      background: rgba(255, 255, 255, 0.02);
    }
    .mono { font-family: 'JetBrains Mono', monospace; }

    /* Modal */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 2000;
    }
    .modal-card {
      background: #131c2e;
      border: 1px solid var(--card-border);
      border-radius: 12px;
      width: 90%;
      max-width: 650px;
      max-height: 85vh;
      overflow-y: auto;
      padding: 1.75rem;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.25rem;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 0.75rem;
    }
    .modal-close {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
    }

    footer {
      border-top: 1px solid var(--card-border);
      padding: 1rem 2rem;
      font-size: 0.8rem;
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(18, 25, 41, 0.5);
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <div class="brand-title">
        <h1>Urja Meter Ops Explorer</h1>
        <p>Flock Energy Smart Meter Intelligence Service</p>
      </div>
    </div>
    <div class="header-links">
      <div class="api-badge" id="portal-status"><span class="dot"></span> Online Gateway</div>
      <a href="/docs" target="_blank" class="btn btn-outline" id="btn-swagger">Swagger API Docs</a>
      <a href="/openapi.json" target="_blank" class="btn btn-outline" id="btn-openapi">OpenAPI Schema</a>
    </div>
  </header>

  <div class="container">
    <!-- Top Metrics Cards -->
    <div class="kpi-grid">
      <div class="kpi-card" id="card-total-meters">
        <div class="kpi-label">Total Smart Meters</div>
        <div class="kpi-value mono" id="kpi-total-meters">403</div>
        <div class="kpi-sub" style="color: var(--primary);">Network Wide Assets</div>
      </div>
      <div class="kpi-card" id="card-installed">
        <div class="kpi-label">Active / Installed</div>
        <div class="kpi-value mono" style="color: var(--emerald);" id="kpi-installed">--</div>
        <div class="kpi-sub" style="color: var(--emerald);">Normal Grid Operations</div>
      </div>
      <div class="kpi-card" id="card-faulty">
        <div class="kpi-label">Faulty Alerts</div>
        <div class="kpi-value mono" style="color: var(--rose);" id="kpi-faulty">--</div>
        <div class="kpi-sub" style="color: var(--rose);">Requires Field Action</div>
      </div>
      <div class="kpi-card" id="card-decom">
        <div class="kpi-label">Decommissioned</div>
        <div class="kpi-value mono" style="color: var(--text-muted);" id="kpi-decommissioned">--</div>
        <div class="kpi-sub" style="color: var(--text-muted);">Retired Hardware</div>
      </div>
      <div class="kpi-card" id="card-transformers">
        <div class="kpi-label">Distribution Transformers</div>
        <div class="kpi-value mono" style="color: var(--amber);" id="kpi-transformers">40</div>
        <div class="kpi-sub" style="color: var(--amber);">Jaipur Substation Zones</div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('map')" id="tab-nav-map">🗺️ Geospatial Map</button>
      <button class="tab-btn" onclick="switchTab('consumption')" id="tab-nav-consumption">📈 30-Min Consumption Load</button>
      <button class="tab-btn" onclick="switchTab('hierarchy')" id="tab-nav-hierarchy">🌳 Network Hierarchy Tree</button>
      <button class="tab-btn" onclick="switchTab('meters')" id="tab-nav-meters">🔍 Query & Index Layer</button>
    </div>

    <!-- 1. MAP TAB -->
    <div class="tab-panel active" id="tab-map">
      <div class="map-controls">
        <div class="map-legend">
          <div class="legend-item"><span class="legend-color" style="background:#10b981;"></span> Installed</div>
          <div class="legend-item"><span class="legend-color" style="background:#f43f5e;"></span> Faulty</div>
          <div class="legend-item"><span class="legend-color" style="background:#64748b;"></span> Decommissioned</div>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem; font-size:0.8rem;">
          <label for="radius-slider">Radius Filter:</label>
          <input type="range" id="radius-slider" min="1" max="25" value="15" oninput="updateRadius(this.value)" style="cursor:pointer;">
          <span id="radius-label" class="mono">15 km</span>
        </div>
      </div>
      <div id="map-container"></div>
    </div>

    <!-- 2. CONSUMPTION TAB -->
    <div class="tab-panel" id="tab-consumption">
      <div class="consumption-bar">
        <div class="form-group">
          <label for="cons-meter-id">Meter ID</label>
          <input type="text" id="cons-meter-id" value="J100000" class="mono" style="width: 140px;" placeholder="e.g. J100000">
        </div>
        <div class="form-group">
          <label for="cons-from">From Date</label>
          <input type="date" id="cons-from" value="2026-06-24">
        </div>
        <div class="form-group">
          <label for="cons-to">To Date</label>
          <input type="date" id="cons-to" value="2026-06-25">
        </div>
        <button class="btn btn-primary" onclick="loadConsumption()" style="align-self: flex-end; height: 34px;">Fetch Load Curve</button>
        <div id="cons-summary" style="margin-left: auto; font-size: 0.82rem; color: var(--text-muted); display:flex; gap:1.25rem;"></div>
      </div>
      <div class="chart-wrapper">
        <canvas id="consumptionChart"></canvas>
      </div>
    </div>

    <!-- 3. HIERARCHY TREE TAB -->
    <div class="tab-panel" id="tab-hierarchy">
      <div class="tree-box" id="hierarchy-tree-container">
        <div style="color: var(--text-muted); text-align: center; padding: 2rem;">Loading network hierarchy tree from portal cache...</div>
      </div>
    </div>

    <!-- 4. QUERY & INDEX LAYER TAB -->
    <div class="tab-panel" id="tab-meters">
      <div class="table-container">
        <div class="table-filters">
          <input type="text" id="filter-q" placeholder="Search Meter ID or Serial..." oninput="debounceFilter()" style="width: 220px;">
          <select id="filter-make" onchange="applyFilters()">
            <option value="">All Makes</option>
            <option value="HPL">HPL</option>
            <option value="Genus">Genus</option>
            <option value="Secure">Secure</option>
            <option value="Allied">Allied</option>
            <option value="L&T">L&T</option>
          </select>
          <select id="filter-phase" onchange="applyFilters()">
            <option value="">All Phases</option>
            <option value="single">Single Phase</option>
            <option value="three">Three Phase</option>
          </select>
          <select id="filter-status" onchange="applyFilters()">
            <option value="">All Statuses</option>
            <option value="Installed">Installed</option>
            <option value="Faulty">Faulty</option>
            <option value="Decommissioned">Decommissioned</option>
          </select>
          <div style="margin-left: auto; font-size: 0.8rem; color: var(--text-muted); align-self: center;" id="filter-count">Showing meters...</div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Meter ID</th>
              <th>Serial No</th>
              <th>Make</th>
              <th>Phase</th>
              <th>Status</th>
              <th>DT Code</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="meters-table-body">
            <tr><td colspan="7" style="text-align:center; color:var(--text-muted);">Loading meter index...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Detail Modal -->
  <div class="modal-backdrop" id="detail-modal" onclick="closeModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 id="modal-title">Meter Details</h3>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>
      <div id="modal-body" style="font-size: 0.88rem;">
        Loading details...
      </div>
    </div>
  </div>

  <footer>
    <div>Clean REST API & Data Adapter Wrapper • Urja Meter Ops</div>
    <div style="color: var(--text-muted);">Flock Energy Engineering Take-Home Submission</div>
  </footer>

  <script>
    // State
    let map, markersLayer, chartInstance;
    let allMeters = [];
    let filterTimeout;

    // Tab Switching
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      
      const btn = document.getElementById('tab-nav-' + tabId);
      const panel = document.getElementById('tab-' + tabId);
      if (btn) btn.classList.add('active');
      if (panel) panel.classList.add('active');

      if (tabId === 'map' && map) {
        setTimeout(() => map.invalidateSize(), 150);
      }
    }

    // Initialize Map
    function initMap() {
      // Jaipur coordinates: 26.9124, 75.7873
      map = L.map('map-container').setView([26.9124, 75.7873], 12);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 19
      }).addTo(map);

      markersLayer = L.layerGroup().addTo(map);
    }

    function renderMapMarkers(meters) {
      if (!markersLayer) return;
      markersLayer.clearLayers();

      meters.forEach(m => {
        if (!m.latitude || !m.longitude) return;

        let color = '#10b981';
        if (m.installStatus === 'Faulty') color = '#f43f5e';
        else if (m.installStatus === 'Decommissioned') color = '#64748b';

        const circle = L.circleMarker([m.latitude, m.longitude], {
          radius: 6,
          fillColor: color,
          color: '#ffffff',
          weight: 1,
          opacity: 0.8,
          fillOpacity: 0.85
        });

        const popupContent = `
          <div style="color:#0f172a; font-family:sans-serif; min-width:180px;">
            <div style="font-weight:700; font-size:1rem; margin-bottom:4px;">${m.meterId}</div>
            <div style="font-size:0.8rem; color:#475569;">Serial: <b>${m.serialNo || 'N/A'}</b></div>
            <div style="font-size:0.8rem; color:#475569;">Make: <b>${m.make || 'N/A'}</b> (${m.phaseType || ''})</div>
            <div style="font-size:0.8rem; color:#475569;">Status: <b style="color:${color};">${m.installStatus}</b></div>
            <div style="font-size:0.8rem; color:#475569;">DT: <b>${m.dtCode || 'N/A'}</b></div>
            <button onclick="selectMeterForAnalysis('${m.meterId}')" style="margin-top:8px; padding:4px 8px; background:#0284c7; color:white; border:none; border-radius:4px; cursor:pointer; font-size:0.75rem; width:100%;">
              View Consumption Curve
            </button>
          </div>
        `;
        circle.bindPopup(popupContent);
        markersLayer.addLayer(circle);
      });
    }

    function selectMeterForAnalysis(meterId) {
      document.getElementById('cons-meter-id').value = meterId;
      switchTab('consumption');
      loadConsumption();
    }

    async function updateRadius(km) {
      document.getElementById('radius-label').textContent = km + ' km';
      try {
        const resp = await fetch(`/api/v1/meters/nearby?lat=26.9124&lon=75.7873&radius_km=${km}&limit=500`);
        const json = await resp.json();
        renderMapMarkers(json.data || []);
      } catch (err) {
        console.error('Failed to load nearby:', err);
      }
    }

    // Consumption Chart
    async function loadConsumption() {
      const meterId = document.getElementById('cons-meter-id').value.trim() || 'J100000';
      const fromDate = document.getElementById('cons-from').value;
      const toDate = document.getElementById('cons-to').value;

      let url = `/api/v1/meters/${meterId}/consumption`;
      const params = [];
      if (fromDate) params.push(`from=${fromDate}`);
      if (toDate) params.push(`to=${toDate}`);
      if (params.length) url += `?${params.join('&')}`;

      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          alert('Could not fetch consumption: HTTP ' + resp.status);
          return;
        }
        const json = await resp.json();
        const data = json.data || [];

        renderChart(meterId, data);

        const summary = document.getElementById('cons-summary');
        if (data.length > 0) {
          const avgVolt = (data.reduce((acc, r) => acc + (r.voltR || 0), 0) / data.length).toFixed(1);
          summary.innerHTML = `
            <div>Intervals: <b>${data.length}</b></div>
            <div>Avg Voltage: <b style="color:var(--emerald);">${avgVolt} V</b></div>
            <div>Latest kWh: <b>${data[data.length-1].kwh || 'N/A'}</b></div>
          `;
        } else {
          summary.innerHTML = '<div>No readings found for selected window</div>';
        }
      } catch (err) {
        console.error('Error fetching consumption:', err);
      }
    }

    function renderChart(meterId, readings) {
      const ctx = document.getElementById('consumptionChart').getContext('2d');
      if (chartInstance) chartInstance.destroy();

      const labels = readings.map(r => r.timestamp.replace('T', ' ').slice(5, 16));
      const kwhData = readings.map(r => r.kwh);
      const voltData = readings.map(r => r.voltR);

      chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            {
              label: 'Cumulative Energy (kWh)',
              data: kwhData,
              borderColor: '#38bdf8',
              backgroundColor: 'rgba(56, 189, 248, 0.1)',
              yAxisID: 'yKwh',
              tension: 0.2,
              fill: true,
              borderWidth: 2,
              pointRadius: 1.5
            },
            {
              label: 'Voltage R-Phase (V)',
              data: voltData,
              borderColor: '#fbbf24',
              backgroundColor: 'transparent',
              yAxisID: 'yVolt',
              tension: 0.2,
              borderWidth: 1.5,
              pointRadius: 0
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            title: {
              display: true,
              text: `30-Minute Interval Load Profile — Meter ${meterId}`,
              color: '#f1f5f9',
              font: { size: 14, family: 'Inter' }
            },
            legend: { labels: { color: '#94a3b8' } }
          },
          scales: {
            x: {
              ticks: { color: '#64748b', maxTicksLimit: 12 },
              grid: { color: 'rgba(255, 255, 255, 0.05)' }
            },
            yKwh: {
              type: 'linear',
              position: 'left',
              ticks: { color: '#38bdf8' },
              grid: { color: 'rgba(255, 255, 255, 0.05)' },
              title: { display: true, text: 'Active Energy (kWh)', color: '#38bdf8' }
            },
            yVolt: {
              type: 'linear',
              position: 'right',
              ticks: { color: '#fbbf24' },
              grid: { drawOnChartArea: false },
              title: { display: true, text: 'Voltage (V)', color: '#fbbf24' }
            }
          }
        }
      });
    }

    // Hierarchy Tree
    async function loadHierarchy() {
      const container = document.getElementById('hierarchy-tree-container');
      try {
        const resp = await fetch('/api/v1/hierarchy');
        const json = await resp.json();
        const zones = json.zones || [];

        let html = '';
        zones.forEach(z => {
          html += `
            <div class="tree-node">
              <div class="tree-header" onclick="toggleNode(this)">
                <span>📂</span>
                <b>${z.name}</b> <span class="badge badge-zone">${z.code}</span>
              </div>
              <div class="tree-children">
          `;

          z.circles.forEach(c => {
            html += `
              <div class="tree-node">
                <div class="tree-header" onclick="toggleNode(this)">
                  <span>📁</span> ${c.name} (${c.code})
                </div>
                <div class="tree-children">
            `;

            c.divisions.forEach(d => {
              d.subdivisions.forEach(sd => {
                sd.substations.forEach(ss => {
                  ss.feeders.forEach(f => {
                    html += `
                      <div class="tree-node">
                        <div class="tree-header" onclick="toggleNode(this)">
                          <span>⚡</span> <b>Feeder ${f.name}</b> <span class="badge badge-feeder">${f.code}</span>
                          <span style="font-size:0.75rem; color:var(--text-muted);">(${f.transformersCount} DTs)</span>
                        </div>
                        <div class="tree-children">
                    `;

                    f.transformers.forEach(dt => {
                      html += `
                        <div class="tree-node">
                          <div class="tree-header" onclick="toggleNode(this)">
                            <span>🔌</span> <b>${dt.name}</b> <span class="badge badge-dt">${dt.code}</span>
                            <span class="badge" style="background:rgba(255,255,255,0.06); color:#cbd5e1;">${dt.metersCount} meters</span>
                          </div>
                          <div class="tree-children" style="display:none;">
                            <div style="margin-left: 1.5rem; padding: 0.5rem 0; display:flex; flex-wrap:wrap; gap:0.4rem;">
                      `;

                      dt.meters.forEach(m => {
                        let statusBadge = 'badge-installed';
                        if (m.installStatus === 'Faulty') statusBadge = 'badge-faulty';
                        else if (m.installStatus === 'Decommissioned') statusBadge = 'badge-decommissioned';

                        html += `
                          <span onclick="openDetailModal('${m.meterId}')" style="cursor:pointer; padding:2px 6px; border-radius:4px; font-size:0.75rem; background:rgba(255,255,255,0.05); border:1px solid var(--card-border);" title="Click for details">
                            <span class="mono">${m.meterId}</span>
                            <span class="badge ${statusBadge}">${m.installStatus}</span>
                          </span>
                        `;
                      });

                      html += `</div></div></div>`;
                    });

                    html += `</div></div>`;
                  });
                });
              });
            });

            html += `</div></div>`;
          });

          html += `</div></div>`;
        });

        container.innerHTML = html;
      } catch (err) {
        container.innerHTML = '<div style="color:var(--rose);">Failed to load hierarchy tree.</div>';
      }
    }

    function toggleNode(elem) {
      const children = elem.nextElementSibling;
      if (children) {
        children.style.display = (children.style.display === 'none') ? 'block' : 'none';
      }
    }

    // Query & Index Layer
    function debounceFilter() {
      clearTimeout(filterTimeout);
      filterTimeout = setTimeout(applyFilters, 250);
    }

    async function applyFilters() {
      const q = document.getElementById('filter-q').value.trim();
      const make = document.getElementById('filter-make').value;
      const phase = document.getElementById('filter-phase').value;
      const status = document.getElementById('filter-status').value;

      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (make) params.set('make', make);
      if (phase) params.set('phase', phase);
      if (status) params.set('status', status);
      params.set('page_size', '50');

      try {
        const resp = await fetch(`/api/v1/meters/query?${params.toString()}`);
        const json = await resp.json();
        const meters = json.data || [];
        document.getElementById('filter-count').textContent = `Found ${json.filteredTotal} meters (showing up to 50)`;

        const tbody = document.getElementById('meters-table-body');
        if (meters.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">No meters matched criteria</td></tr>';
          return;
        }

        tbody.innerHTML = meters.map(m => {
          let statusBadge = 'badge-installed';
          if (m.installStatus === 'Faulty') statusBadge = 'badge-faulty';
          else if (m.installStatus === 'Decommissioned') statusBadge = 'badge-decommissioned';

          return `
            <tr>
              <td class="mono font-bold" style="color:var(--primary);">${m.meterId}</td>
              <td class="mono">${m.serialNo || '-'}</td>
              <td>${m.make || '-'}</td>
              <td><span class="badge" style="background:rgba(255,255,255,0.05); color:#cbd5e1;">${m.phaseType || '-'}</span></td>
              <td><span class="badge ${statusBadge}">${m.installStatus || '-'}</span></td>
              <td class="mono">${m.dtCode || '-'}</td>
              <td>
                <button class="btn btn-outline" style="padding:2px 8px; font-size:0.75rem;" onclick="openDetailModal('${m.meterId}')">Inspect</button>
                <button class="btn btn-primary" style="padding:2px 8px; font-size:0.75rem; margin-left:4px;" onclick="selectMeterForAnalysis('${m.meterId}')">Energy</button>
              </td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        console.error('Filter failed:', err);
      }
    }

    // Modal
    async function openDetailModal(meterId) {
      const modal = document.getElementById('detail-modal');
      const title = document.getElementById('modal-title');
      const body = document.getElementById('modal-body');

      title.textContent = `Meter Details — ${meterId}`;
      body.innerHTML = '<div style="color:var(--text-muted); padding:1rem;">Fetching details from portal adapter...</div>';
      modal.style.display = 'flex';

      try {
        const resp = await fetch(`/api/v1/meters/${meterId}`);
        const json = await resp.json();

        let npRows = (json.nameplate || []).map(np => `
          <tr>
            <td style="color:var(--text-muted); width:40%;">${np.parameterName}</td>
            <td class="mono font-medium">${np.parameterValue || 'null'}</td>
          </tr>
        `).join('');

        let hRows = Object.entries(json.hierarchy || {}).map(([k, v]) => `
          <tr>
            <td style="color:var(--text-muted); width:40%;">${k}</td>
            <td class="mono">${v || 'null'}</td>
          </tr>
        `).join('');

        let geoInfo = json.location ? `Latitude: ${json.location.latitude}, Longitude: ${json.location.longitude}` : 'No GPS coordinates';

        body.innerHTML = `
          <h4 style="color:var(--primary); margin-bottom:0.5rem;">Nameplate Parameters</h4>
          <table style="margin-bottom:1.25rem;"><tbody>${npRows}</tbody></table>

          <h4 style="color:var(--amber); margin-bottom:0.5rem;">Network Hierarchy</h4>
          <table style="margin-bottom:1.25rem;"><tbody>${hRows}</tbody></table>

          <h4 style="color:var(--emerald); margin-bottom:0.5rem;">Geographic Location</h4>
          <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem;" class="mono">${geoInfo}</div>

          ${json.warnings && json.warnings.length ? `
            <h4 style="color:var(--rose); margin-bottom:0.5rem;">Warnings / Anomalies</h4>
            <ul style="padding-left:1.25rem; color:var(--rose); font-size:0.8rem;">
              ${json.warnings.map(w => `<li>${w}</li>`).join('')}
            </ul>
          ` : ''}
        `;
      } catch (err) {
        body.innerHTML = '<div style="color:var(--rose);">Error loading meter details.</div>';
      }
    }

    function closeModal() {
      document.getElementById('detail-modal').style.display = 'none';
    }

    // Bootstrap
    async function init() {
      initMap();
      
      // Load stats
      try {
        const statsResp = await fetch('/api/v1/stats');
        const stats = await statsResp.json();
        if (stats.totalMeters) {
          document.getElementById('kpi-total-meters').textContent = stats.totalMeters;
          document.getElementById('kpi-installed').textContent = stats.statusBreakdown['Installed'] || 0;
          document.getElementById('kpi-faulty').textContent = stats.statusBreakdown['Faulty'] || 0;
          document.getElementById('kpi-decommissioned').textContent = stats.statusBreakdown['Decommissioned'] || 0;
          document.getElementById('kpi-transformers').textContent = stats.totalTransformers || 40;
        }
      } catch (e) {
        console.warn('Could not load stats:', e);
      }

      // Initial nearby load for map
      updateRadius(15);
      // Initial consumption load
      loadConsumption();
      // Load hierarchy
      loadHierarchy();
      // Load meter table
      applyFilters();
    }

    window.addEventListener('DOMContentLoaded', init);
  </script>
</body>
</html>
"""
