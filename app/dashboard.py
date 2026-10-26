"""Interactive web client for Urja Meter Ops (light SaaS analytics design).

Served at / and /dashboard as an optional extension that provides:
  - Network Overview with KPIs, asset-status composition, and manufacturer mix
  - Interactive Leaflet geospatial map plotting meters across Jaipur with status coloring
  - Proximity search slider leveraging /api/v1/meters/nearby
  - Chart.js 30-minute interval energy consumption viewer with voltage profiling
  - Collapsible Network Hierarchy Tree (Zone -> Circle -> Feeder -> DT -> Meters)
  - Distribution Transformer browser with per-DT attached meters and status mix
  - Paginated multi-attribute meter index (Make, Phase, Status, DT, free text)
  - Client-side CSV export of filtered meter queries and of consumption readings
  - Auto-refreshing stats (60 s, pauses when the tab is hidden) plus a manual refresh
  - Keyboard shortcuts (1-6 views, / search, R refresh, ? help, Esc close)

Single-file SPA (no build step). Hash-based deep links: #/overview, #/map, ...
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Urja Meter Ops — Flock Energy</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>

  <style>
    :root {
      /* Surfaces */
      --bg: #f4f6f9;
      --surface: #ffffff;
      --surface-2: #f8fafc;
      --border: #e6e9ef;
      --border-strong: #d5dae2;

      /* Text */
      --text: #101828;
      --text-2: #475467;
      --text-3: #98a2b3;

      /* Brand + semantics */
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-soft: #eff5ff;
      --primary-border: #cfe0fc;
      --success: #067647;
      --success-dot: #12b76a;
      --success-soft: #ecfdf3;
      --success-border: #c9f2dc;
      --danger: #b42318;
      --danger-dot: #f04438;
      --danger-soft: #fef3f2;
      --danger-border: #fddcd6;
      --warning: #b54708;
      --warning-soft: #fffaeb;
      --warning-border: #fde8c4;
      --neutral-soft: #f2f4f7;
      --neutral-text: #475467;

      /* Elevation */
      --shadow-1: 0 1px 2px rgba(16, 24, 40, 0.05);
      --shadow-2: 0 4px 8px -2px rgba(16, 24, 40, 0.08), 0 2px 4px -2px rgba(16, 24, 40, 0.04);
      --shadow-3: 0 20px 24px -4px rgba(16, 24, 40, 0.10), 0 8px 12px -6px rgba(16, 24, 40, 0.08);
      --radius: 12px;
      --radius-sm: 8px;

      --sidebar-w: 252px;
      --topbar-h: 60px;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }

    button { font: inherit; cursor: pointer; }
    a { color: var(--primary); text-decoration: none; }
    a:hover { text-decoration: none; }
    :focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 4px; }
    ::selection { background: rgba(37, 99, 235, 0.15); }

    .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.92em; }
    .tnum { font-variant-numeric: tabular-nums; }

    /* ============ Icon system (Lucide-style inline SVG) ============ */
    .icon { width: 18px; height: 18px; flex: none; color: currentColor; }
    .icon-sm { width: 15px; height: 15px; }

    /* ============ App shell ============ */
    .app { display: flex; min-height: 100vh; }

    .sidebar {
      width: var(--sidebar-w);
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      position: fixed;
      inset: 0 auto 0 0;
      z-index: 100;
      transition: transform 0.24s ease;
    }

    .brand { display: flex; align-items: center; gap: 12px; padding: 20px 20px 16px; }
    .brand-mark {
      width: 38px; height: 38px; flex: none;
      border-radius: 10px;
      background: linear-gradient(135deg, #1e40af 0%, #2563eb 55%, #38bdf8 130%);
      display: grid; place-items: center;
      color: #fff;
      box-shadow: 0 4px 10px -2px rgba(37, 99, 235, 0.45);
    }
    .brand-name { font-size: 14.5px; font-weight: 700; letter-spacing: -0.01em; }
    .brand-sub { font-size: 11.5px; color: var(--text-3); margin-top: 1px; }

    .nav-section { padding: 8px 12px; }
    .nav-label {
      font-size: 10.5px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.07em; color: var(--text-3);
      padding: 10px 10px 6px;
    }
    .nav-item {
      width: 100%;
      display: flex; align-items: center; gap: 11px;
      padding: 8px 10px;
      border: none; background: none; border-radius: var(--radius-sm);
      color: var(--text-2);
      font-size: 13.5px; font-weight: 500;
      text-align: left;
      transition: background 0.15s ease, color 0.15s ease;
    }
    .nav-item:hover { background: var(--surface-2); color: var(--text); }
    .nav-item[aria-current="page"] {
      background: var(--primary-soft); color: var(--primary);
    }
    .nav-item[aria-current="page"] .icon { color: var(--primary); }

    .sidebar-footer { margin-top: auto; padding: 12px; border-top: 1px solid var(--border); }
    .gateway-card {
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      display: flex; align-items: center; gap: 10px;
    }
    .pulse-dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--success-dot); flex: none;
      position: relative;
    }
    .pulse-dot::after {
      content: ''; position: absolute; inset: -4px;
      border-radius: 50%; border: 1px solid var(--success-dot);
      opacity: 0; animation: pulseRing 2.4s ease-out infinite;
    }
    @keyframes pulseRing { 0% { transform: scale(0.5); opacity: 0.7; } 70%, 100% { transform: scale(1.4); opacity: 0; } }
    .gateway-title { font-size: 12.5px; font-weight: 600; }
    .gateway-sub { font-size: 11px; color: var(--text-3); }

    /* Main column */
    .main { flex: 1; margin-left: var(--sidebar-w); display: flex; flex-direction: column; min-width: 0; }

    .topbar {
      height: var(--topbar-h);
      background: rgba(255, 255, 255, 0.85);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 12px;
      padding: 0 24px;
      position: sticky; top: 0; z-index: 90;
    }
    .menu-btn {
      display: none;
      width: 38px; height: 38px;
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: var(--radius-sm);
      color: var(--text-2);
      place-items: center;
    }
    .view-title { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; }
    .view-sub { font-size: 12px; color: var(--text-3); }
    .topbar-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
    .env-chip {
      display: inline-flex; align-items: center; gap: 7px;
      font-size: 12px; font-weight: 500; color: var(--text-2);
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 5px 11px;
      border-radius: 999px;
      box-shadow: var(--shadow-1);
    }

    .content { padding: 24px; max-width: 1480px; width: 100%; margin: 0 auto; }

    /* ============ Generic building blocks ============ */
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-1);
    }
    .card-head {
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
    }
    .card-title { font-size: 14px; font-weight: 600; }
    .card-desc { font-size: 12.5px; color: var(--text-3); }
    .card-head-right { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 7px;
      font-size: 13px; font-weight: 600;
      padding: 0 14px; height: 36px;
      border-radius: var(--radius-sm);
      border: 1px solid transparent;
      transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
      white-space: nowrap;
    }
    .btn-primary { background: var(--primary); color: #fff; box-shadow: var(--shadow-1); }
    .btn-primary:hover { background: var(--primary-hover); }
    .btn-primary:disabled { opacity: 0.55; cursor: not-allowed; }
    .btn-secondary { background: var(--surface); color: var(--text-2); border-color: var(--border-strong); box-shadow: var(--shadow-1); }
    .btn-secondary:hover { background: var(--surface-2); color: var(--text); }
    .btn-ghost { background: transparent; color: var(--text-2); height: 34px; padding: 0 10px; }
    .btn-ghost:hover { background: var(--neutral-soft); color: var(--text); }
    .btn .spinner { display: none; }
    .btn.loading .spinner { display: block; }
    .btn.loading .icon { display: none; }
    .btn.loading .btn-label { opacity: 0.75; }

    .spinner {
      width: 15px; height: 15px; flex: none;
      border: 2px solid rgba(255, 255, 255, 0.35);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }
    .spinner-dark { border-color: rgba(37, 99, 235, 0.25); border-top-color: var(--primary); }
    @keyframes spin { to { transform: rotate(360deg); } }

    input[type="text"], input[type="date"], select {
      font: inherit; font-size: 13px;
      height: 36px;
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm);
      color: var(--text);
      padding: 0 11px;
      outline: none;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    input:hover, select:hover { border-color: var(--text-3); }
    input:focus, select:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
    }
    select { cursor: pointer; padding-right: 28px; }
    input::placeholder { color: var(--text-3); }

    .field { display: flex; flex-direction: column; gap: 5px; }
    .field > label { font-size: 12px; font-weight: 600; color: var(--text-2); }

    /* Status + meta pills */
    .pill {
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 12px; font-weight: 600;
      padding: 2.5px 9px;
      border-radius: 999px;
      border: 1px solid transparent;
      white-space: nowrap;
    }
    .pill .dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
    .pill-installed { background: var(--success-soft); color: var(--success); border-color: var(--success-border); }
    .pill-installed .dot { background: var(--success-dot); }
    .pill-faulty { background: var(--danger-soft); color: var(--danger); border-color: var(--danger-border); }
    .pill-faulty .dot { background: var(--danger-dot); }
    .pill-decommissioned { background: var(--neutral-soft); color: var(--neutral-text); border-color: var(--border); }
    .pill-decommissioned .dot { background: var(--text-3); }
    .pill-phase { background: var(--primary-soft); color: var(--primary); border-color: var(--primary-border); }
    .pill-phase-three { background: #f6f3ff; color: #6941c6; border-color: #e6dcfe; }
    .pill-plain { background: var(--neutral-soft); color: var(--neutral-text); border-color: var(--border); }

    /* Skeleton shimmer */
    .skeleton {
      border-radius: 8px;
      background: linear-gradient(90deg, #eef1f5 25%, #f6f8fa 45%, #eef1f5 65%);
      background-size: 200% 100%;
      animation: shimmer 1.3s linear infinite;
      color: transparent !important;
      user-select: none;
    }
    @keyframes shimmer { to { background-position: -200% 0; } }

    .empty-state {
      display: flex; flex-direction: column; align-items: center; gap: 8px;
      padding: 48px 24px; text-align: center; color: var(--text-3);
    }
    .empty-state .icon { width: 24px; height: 24px; color: var(--text-3); }
    .empty-title { font-weight: 600; color: var(--text-2); font-size: 13.5px; }

    /* ============ Views ============ */
    .view { display: none; animation: viewIn 0.22s ease; }
    .view.active { display: block; }
    @keyframes viewIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }

    /* --- Overview --- */
    .stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 18px; }
    .stat-card { padding: 16px 18px; display: flex; flex-direction: column; gap: 4px; position: relative; overflow: hidden; }
    .stat-card::before {
      content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2.5px;
      background: var(--accent, var(--primary)); opacity: 0.85;
    }
    .stat-label { font-size: 12px; font-weight: 600; color: var(--text-2); }
    .stat-value { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
    .stat-note { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-3); }
    .stat-note .dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
    .stat-icon {
      position: absolute; top: 14px; right: 14px;
      width: 30px; height: 30px; border-radius: 8px;
      display: grid; place-items: center;
      background: var(--accent-soft, var(--primary-soft));
      color: var(--accent, var(--primary));
    }

    .compo-grid { display: grid; grid-template-columns: 1.6fr 1.15fr 0.75fr; gap: 14px; }
    .compo-card { padding: 18px 20px; }
    .compo-title { font-size: 13.5px; font-weight: 600; margin-bottom: 2px; }
    .compo-sub { font-size: 11.5px; color: var(--text-3); margin-bottom: 14px; }

    .stack-bar {
      display: flex; height: 12px; border-radius: 999px; overflow: hidden;
      background: var(--neutral-soft);
      margin-bottom: 14px;
    }
    .stack-seg { transition: width 0.5s ease; }
    .stack-legend { display: flex; flex-direction: column; gap: 8px; }
    .legend-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
    .legend-row .legend-count { margin-left: auto; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
    .legend-row .legend-pct { color: var(--text-3); font-size: 11.5px; }
    .legend-swatch { width: 9px; height: 9px; border-radius: 3px; flex: none; }

    .bar-rows { display: flex; flex-direction: column; gap: 11px; }
    .bar-row { display: grid; grid-template-columns: 52px 1fr 58px; align-items: center; gap: 10px; font-size: 12.5px; }
    .bar-track { height: 8px; background: var(--neutral-soft); border-radius: 999px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 999px; transition: width 0.5s ease; }
    .bar-count { text-align: right; font-variant-numeric: tabular-nums; color: var(--text-2); }

    .phase-rows { display: flex; flex-direction: column; gap: 12px; }
    .phase-row {
      border: 1px solid var(--border); border-radius: 10px;
      padding: 10px 12px; display: flex; align-items: center; gap: 10px;
      background: var(--surface-2);
    }
    .phase-row b { font-size: 14px; font-variant-numeric: tabular-nums; margin-left: auto; }

    .overview-error { padding: 20px; }

    /* --- Map --- */
    .map-card { overflow: hidden; }
    .map-legend { display: flex; gap: 6px; flex-wrap: wrap; }
    .radius-wrap { display: flex; align-items: center; gap: 10px; }
    .radius-wrap label { font-size: 12.5px; font-weight: 600; color: var(--text-2); }
    input[type="range"] { width: 130px; accent-color: var(--primary); cursor: pointer; }
    .radius-badge {
      min-width: 58px; text-align: center;
      font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
      background: var(--primary-soft); color: var(--primary);
      border: 1px solid var(--primary-border);
      padding: 3px 8px; border-radius: 999px;
    }
    #map {
      height: min(62vh, 620px);
      width: 100%;
      background: #e8edf3;
    }
    #map .leaflet-tile { filter: saturate(0.82); }
    .map-status {
      position: absolute; z-index: 500; left: 50%; bottom: 14px; transform: translateX(-50%);
      pointer-events: none;
    }
    .map-count-chip {
      background: rgba(16, 24, 40, 0.82); color: #fff;
      backdrop-filter: blur(6px);
      font-size: 12px; font-weight: 500;
      padding: 6px 13px; border-radius: 999px;
      box-shadow: var(--shadow-2);
      white-space: nowrap;
    }
    .map-panel-wrap { position: relative; }

    /* Leaflet popup theming */
    .leaflet-popup-content-wrapper { border-radius: 12px; box-shadow: var(--shadow-3); }
    .leaflet-popup-content { margin: 14px 16px; font-family: 'Inter', sans-serif; font-size: 13px; color: var(--text); }
    .popup-title { font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 8px; margin-bottom: 7px; }
    .popup-rows { display: flex; flex-direction: column; gap: 3px; font-size: 12.5px; color: var(--text-2); }
    .popup-rows b { color: var(--text); font-weight: 600; }
    .popup-actions { display: flex; gap: 8px; margin-top: 11px; }
    .popup-btn {
      flex: 1; height: 30px; font-size: 12px; font-weight: 600;
      border-radius: 7px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2);
      text-align: center; line-height: 28px; cursor: pointer;
    }
    .popup-btn:hover { background: var(--surface-2); color: var(--text); }
    .popup-btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    .popup-btn-primary:hover { background: var(--primary-hover); color: #fff; }

    /* --- Consumption --- */
    .cons-controls { padding: 16px 20px; display: flex; gap: 14px; flex-wrap: wrap; align-items: flex-end; }
    .preset-group { display: flex; gap: 6px; padding-bottom: 1px; }
    .preset-btn {
      height: 36px; padding: 0 12px; font-size: 12.5px; font-weight: 600;
      border: 1px solid var(--border-strong); background: var(--surface);
      border-radius: var(--radius-sm); color: var(--text-2);
    }
    .preset-btn:hover { background: var(--surface-2); color: var(--text); }
    .cons-filters { margin-bottom: 14px; }
    .cons-summary {
      display: flex; gap: 22px; flex-wrap: wrap; align-items: center;
      font-size: 12.5px; color: var(--text-2);
    }
    .cons-summary b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
    .cons-summary .sep { width: 1px; height: 16px; background: var(--border); }
    .chart-wrap { padding: 6px 14px 16px; height: 430px; position: relative; }

    /* --- Hierarchy --- */
    .tree { padding: 10px 14px 18px; overflow: auto; max-height: calc(100vh - 220px); }
    .tree-row {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 5px 8px; margin: 1px 0;
      border: none; background: none; border-radius: 7px;
      font-size: 13px; color: var(--text); text-align: left;
      transition: background 0.12s ease;
    }
    .tree-row:hover { background: var(--surface-2); }
    .tree-chevron { color: var(--text-3); transition: transform 0.18s ease; width: 15px; height: 15px; }
    .tree-row[aria-expanded="true"] .tree-chevron { transform: rotate(90deg); }
    .tree-row[aria-expanded="false"] + .tree-children { display: none; }
    .tree-children { margin-left: 14px; padding-left: 12px; border-left: 1px solid var(--border); }
    .tree-name { font-weight: 600; }
    .tag {
      font-size: 10.5px; font-weight: 600; font-family: 'JetBrains Mono', monospace;
      padding: 1.5px 6px; border-radius: 5px;
      background: var(--neutral-soft); color: var(--neutral-text);
      border: 1px solid var(--border);
    }
    .tree-dim { font-size: 11.5px; color: var(--text-3); }
    .meter-chip {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 3px 8px; margin: 2px 4px 2px 0;
      border: 1px solid var(--border); border-radius: 999px;
      background: var(--surface);
      font-size: 11.5px; font-family: 'JetBrains Mono', monospace;
      transition: border-color 0.12s ease, background 0.12s ease;
    }
    .meter-chip:hover { border-color: var(--primary); background: var(--primary-soft); }

    /* --- Meter Index table --- */
    .table-filters { padding: 14px 20px; display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; border-bottom: 1px solid var(--border); }
    .search-box { position: relative; }
    .search-box .icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-3); pointer-events: none; width: 15px; height: 15px; }
    .search-box input { padding-left: 32px; width: 250px; }
    .table-scroll { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 720px; }
    th {
      text-align: left; font-size: 11.5px; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.05em; color: var(--text-3);
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-2);
      white-space: nowrap;
    }
    td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    tbody tr { transition: background 0.12s ease; }
    tbody tr:hover { background: #fafbfd; }
    tbody tr:last-child td { border-bottom: none; }
    .table-footer {
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
      padding: 12px 20px; font-size: 12.5px; color: var(--text-2);
      border-top: 1px solid var(--border); background: var(--surface-2);
    }
    .pager { margin-left: auto; display: flex; align-items: center; gap: 8px; }
    .pager-btn {
      width: 32px; height: 32px; display: grid; place-items: center;
      border: 1px solid var(--border-strong); border-radius: 8px;
      background: var(--surface); color: var(--text-2);
    }
    .pager-btn:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
    .pager-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .page-ind { font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; padding: 0 4px; }
    .row-actions { display: flex; gap: 6px; }
    .chip-btn {
      height: 28px; padding: 0 10px; font-size: 12px; font-weight: 600;
      border-radius: 7px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2);
      display: inline-flex; align-items: center; gap: 5px;
      transition: border-color 0.12s ease, background 0.12s ease;
    }
    .chip-btn:hover { background: var(--surface-2); color: var(--text); }
    .chip-btn-accent { background: var(--primary-soft); border-color: var(--primary-border); color: var(--primary); }
    .chip-btn-accent:hover { background: #e0ecfd; color: var(--primary-hover); }
    .chip-btn:disabled, .btn-secondary:disabled { opacity: 0.45; cursor: not-allowed; }
    .btn-secondary.loading .spinner { display: block; }

    /* --- Transformers --- */
    .dt-layout { display: grid; grid-template-columns: 330px minmax(0, 1fr); gap: 14px; align-items: start; }
    .dt-head-col { flex-direction: column; align-items: stretch; gap: 8px; }
    .dt-list { max-height: min(62vh, 640px); overflow-y: auto; padding: 8px; }
    .dt-row {
      width: 100%;
      display: flex; justify-content: space-between; align-items: center; gap: 10px;
      padding: 9px 11px; margin-bottom: 2px;
      border: none; background: none; border-radius: 8px;
      text-align: left;
      transition: background 0.12s ease;
    }
    .dt-row:hover { background: var(--surface-2); }
    .dt-row.selected { background: var(--primary-soft); box-shadow: inset 0 0 0 1px var(--primary-border); }
    .dt-row.selected .dt-code { color: var(--primary); }
    .dt-code { font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: 12.5px; }
    .dt-name { font-size: 11.5px; color: var(--text-3); }
    .dt-meta { display: flex; gap: 6px; align-items: center; flex: none; }
    .dt-detail-pad { padding: 18px 20px 22px; }
    .dt-meta-grid { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 6px; font-size: 12.5px; color: var(--text-2); }
    .dt-meta-grid b { color: var(--text); font-weight: 600; }

    /* --- Icon buttons + shortcut help popover --- */
    .icon-btn {
      width: 34px; height: 34px; flex: none;
      display: grid; place-items: center;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface);
      color: var(--text-2);
      transition: background 0.15s ease, color 0.15s ease;
    }
    .icon-btn:hover { background: var(--surface-2); color: var(--text); }
    .kbd-pop {
      position: fixed;
      top: calc(var(--topbar-h) + 10px); right: 20px;
      z-index: 300;
      width: 300px;
      padding: 16px 18px;
      box-shadow: var(--shadow-3);
      animation: viewIn 0.18s ease;
    }
    .kbd-pop[hidden] { display: none; }
    .kbd-pop-title {
      font-size: 11px; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.06em; color: var(--text-3); margin-bottom: 10px;
    }
    .kbd-row {
      display: flex; align-items: center; justify-content: space-between;
      font-size: 12.5px; padding: 5px 0; color: var(--text-2);
    }
    kbd {
      font-family: 'JetBrains Mono', monospace; font-size: 11px;
      background: var(--surface-2);
      border: 1px solid var(--border-strong); border-bottom-width: 2px;
      border-radius: 6px; padding: 1px 7px;
      color: var(--text);
    }

    /* ============ Detail slide-over ============ */
    .scrim {
      position: fixed; inset: 0; background: rgba(16, 24, 40, 0.42);
      opacity: 0; visibility: hidden; transition: opacity 0.2s ease, visibility 0.2s;
      z-index: 200;
    }
    .scrim.open { opacity: 1; visibility: visible; }

    .slideover {
      position: fixed; top: 0; right: 0; bottom: 0;
      width: min(460px, 96vw);
      background: var(--surface);
      box-shadow: var(--shadow-3);
      transform: translateX(102%);
      transition: transform 0.26s cubic-bezier(0.32, 0.72, 0.24, 1);
      z-index: 210;
      display: flex; flex-direction: column;
    }
    .slideover.open { transform: none; }
    .slideover-head {
      padding: 18px 22px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 12px;
    }
    .slideover-head h2 { font-size: 15px; font-weight: 700; letter-spacing: -0.01em; font-family: 'JetBrains Mono', monospace; }
    .slideover-close {
      margin-left: auto;
      width: 34px; height: 34px; border-radius: 8px; border: none;
      background: transparent; color: var(--text-3);
      display: grid; place-items: center;
    }
    .slideover-close:hover { background: var(--neutral-soft); color: var(--text); }
    .slideover-body { padding: 20px 22px 28px; overflow-y: auto; }
    .section-label {
      font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--text-3); margin: 20px 0 8px;
      display: flex; align-items: center; gap: 7px;
    }
    .section-label:first-child { margin-top: 0; }
    .kv-list { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
    .kv-row {
      display: grid; grid-template-columns: 42% 58%;
      padding: 8px 12px; font-size: 12.5px;
      border-bottom: 1px solid var(--border);
    }
    .kv-row:last-child { border-bottom: none; }
    .kv-row:nth-child(odd) { background: var(--surface-2); }
    .kv-key { color: var(--text-2); overflow-wrap: anywhere; }
    .kv-val { color: var(--text); font-weight: 500; overflow-wrap: anywhere; }
    .geo-box {
      border: 1px solid var(--border); border-radius: 10px;
      padding: 12px 14px; background: var(--surface-2);
      display: flex; align-items: center; gap: 10px; font-size: 12.5px;
      font-family: 'JetBrains Mono', monospace; color: var(--text-2);
    }
    .alert-line {
      border: 1px solid var(--warning-border); background: var(--warning-soft);
      color: var(--warning);
      border-radius: 10px; padding: 10px 13px;
      font-size: 12.5px;
      display: flex; gap: 9px; align-items: flex-start;
      margin-bottom: 8px;
    }
    .alert-line svg { flex: none; margin-top: 1px; }

    /* ============ Toast ============ */
    .toast-zone { position: fixed; bottom: 20px; right: 20px; z-index: 400; display: flex; flex-direction: column; gap: 8px; }
    .toast {
      display: flex; align-items: center; gap: 10px;
      background: #1d2939; color: #f2f4f7;
      font-size: 13px; font-weight: 500;
      padding: 11px 16px; border-radius: 10px;
      box-shadow: var(--shadow-3);
      animation: toastIn 0.22s ease;
      max-width: 380px;
    }
    .toast-danger { background: #7a271a; }
    .toast svg { flex: none; }
    @keyframes toastIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

    /* Backdrop for mobile sidebar */
    .mobile-scrim {
      position: fixed; inset: 0; background: rgba(16, 24, 40, 0.42);
      opacity: 0; visibility: hidden; transition: opacity 0.2s ease, visibility 0.2s;
      z-index: 99;
    }
    .mobile-scrim.open { opacity: 1; visibility: visible; }

    /* ============ Responsive ============ */
    @media (max-width: 1240px) {
      .stat-grid { grid-template-columns: repeat(3, 1fr); }
      .compo-grid { grid-template-columns: 1fr 1fr; }
      .compo-card--phase { grid-column: span 2; }
    }
    @media (max-width: 1024px) {
      .sidebar { transform: translateX(-102%); box-shadow: var(--shadow-3); }
      .sidebar.open { transform: none; }
      .main { margin-left: 0; }
      .menu-btn { display: grid; }
    }
    @media (max-width: 720px) {
      .content { padding: 16px; }
      .stat-grid { grid-template-columns: repeat(2, 1fr); }
      .compo-grid { grid-template-columns: 1fr; }
      .compo-card--phase { grid-column: auto; }
      .view-sub, .env-chip span.hide-sm { display: none; }
      .search-box input { width: 100%; }
      .search-box { width: 100%; }
      .topbar { padding: 0 16px; }
    }
    @media (max-width: 420px) {
      .stat-grid { grid-template-columns: 1fr 1fr; }
      .stat-value { font-size: 22px; }
    }
    @media (max-width: 900px) {
      .dt-layout { grid-template-columns: 1fr; }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
    }
  </style>
</head>
<body>

<!-- SVG sprite -->
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <symbol id="i-bolt" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></symbol>
    <symbol id="i-grid" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></symbol>
    <symbol id="i-map" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></symbol>
    <symbol id="i-activity" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></symbol>
    <symbol id="i-branch" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></symbol>
    <symbol id="i-list" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/></symbol>
    <symbol id="i-braces" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/></symbol>
    <symbol id="i-db" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></symbol>
    <symbol id="i-menu" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="20" y1="7" y2="7"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="17" y2="17"/></symbol>
    <symbol id="i-x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></symbol>
    <symbol id="i-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></symbol>
    <symbol id="i-refresh" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></symbol>
    <symbol id="i-chev-r" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></symbol>
    <symbol id="i-chev-l" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></symbol>
    <symbol id="i-alert" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></symbol>
    <symbol id="i-pin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></symbol>
    <symbol id="i-info" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></symbol>
    <symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></symbol>
    <symbol id="i-warn-circle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></symbol>
    <symbol id="i-tf" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M12.5 7 9.75 12h4.5L11.5 17"/></symbol>
    <symbol id="i-download" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></symbol>
    <symbol id="i-kbd" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/></symbol>
  </defs>
</svg>

<div class="app" id="app">

  <!-- ============ Sidebar ============ -->
  <aside class="sidebar" id="sidebar" aria-label="Primary navigation">
    <div class="brand">
      <div class="brand-mark"><svg class="icon" style="width:19px;height:19px"><use href="#i-bolt"/></svg></div>
      <div>
        <div class="brand-name">Urja Meter Ops</div>
        <div class="brand-sub">Flock Energy · Explorer</div>
      </div>
    </div>

    <nav class="nav-section">
      <div class="nav-label">Observability</div>
      <button class="nav-item" data-view="overview" onclick="switchView('overview')">
        <svg class="icon"><use href="#i-grid"/></svg> Overview
      </button>
      <button class="nav-item" data-view="map" onclick="switchView('map')">
        <svg class="icon"><use href="#i-map"/></svg> Live Asset Map
      </button>
      <button class="nav-item" data-view="consumption" onclick="switchView('consumption')">
        <svg class="icon"><use href="#i-activity"/></svg> Load Curve
      </button>
    </nav>

    <nav class="nav-section">
      <div class="nav-label">Network</div>
      <button class="nav-item" data-view="hierarchy" onclick="switchView('hierarchy')">
        <svg class="icon"><use href="#i-branch"/></svg> Hierarchy Tree
      </button>
      <button class="nav-item" data-view="transformers" onclick="switchView('transformers')">
        <svg class="icon"><use href="#i-tf"/></svg> Transformers
      </button>
      <button class="nav-item" data-view="meters" onclick="switchView('meters')">
        <svg class="icon"><use href="#i-list"/></svg> Meter Index
      </button>
    </nav>

    <div class="sidebar-footer">
      <nav class="nav-section" style="padding:0 0 10px">
        <div class="nav-label" style="padding-left:10px">Developer</div>
        <a class="nav-item" href="/docs" target="_blank" rel="noopener">
          <svg class="icon"><use href="#i-braces"/></svg> API Reference
        </a>
        <a class="nav-item" href="/openapi.json" target="_blank" rel="noopener">
          <svg class="icon"><use href="#i-db"/></svg> OpenAPI Schema
        </a>
      </nav>
      <div class="gateway-card">
        <span class="pulse-dot" aria-hidden="true"></span>
        <div>
          <div class="gateway-title">Gateway online</div>
          <div class="gateway-sub">urja-ops portal adapter</div>
        </div>
      </div>
    </div>
  </aside>
  <div class="mobile-scrim" id="mobile-scrim" onclick="toggleSidebar(false)"></div>

  <!-- ============ Main ============ -->
  <div class="main">
    <header class="topbar">
      <button class="menu-btn" onclick="toggleSidebar(true)" aria-label="Open navigation menu">
        <svg class="icon"><use href="#i-menu"/></svg>
      </button>
      <div>
        <div class="view-title" id="view-title">Network Overview</div>
        <div class="view-sub" id="view-sub">Live summary of the Jaipur smart-meter distribution grid</div>
      </div>
      <div class="topbar-right">
        <button class="icon-btn" onclick="refreshStatsNow()" aria-label="Refresh network stats" title="Refresh stats (R)">
          <svg class="icon icon-sm"><use href="#i-refresh"/></svg>
        </button>
        <button class="icon-btn" data-kbd-toggle onclick="toggleShortcuts()" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <svg class="icon icon-sm"><use href="#i-kbd"/></svg>
        </button>
        <div class="env-chip">
          <svg class="icon icon-sm" style="color:var(--success-dot)"><use href="#i-pin"/></svg>
          <span class="hide-sm">Jaipur distribution grid</span>
          <span>&nbsp;·&nbsp;</span>
          <span class="tnum" id="env-meter-count">— meters</span>
          <span>&nbsp;·&nbsp;</span>
          <span class="tnum" id="stats-updated" style="color:var(--text-3)" title="Stats auto-refresh every 60 seconds"></span>
        </div>
      </div>
    </header>

    <main class="content">

      <!-- ================= OVERVIEW ================= -->
      <section class="view" id="view-overview" data-view-panel="overview">
        <div class="stat-grid" id="stat-grid">
          <div class="card stat-card" style="--accent:#2563eb; --accent-soft:var(--primary-soft)">
            <div class="stat-icon"><svg class="icon icon-sm"><use href="#i-bolt"/></svg></div>
            <div class="stat-label">Metering Assets</div>
            <div class="stat-value skeleton" style="width:64px">0</div>
            <div class="stat-note">Smart meters · network wide</div>
          </div>
          <div class="card stat-card" style="--accent:#12b76a; --accent-soft:var(--success-soft)">
            <div class="stat-icon"><svg class="icon icon-sm"><use href="#i-check"/></svg></div>
            <div class="stat-label">Installed</div>
            <div class="stat-value skeleton" style="width:64px">0</div>
            <div class="stat-note"><span class="dot" style="background:var(--success-dot)"></span>Normal grid operations</div>
          </div>
          <div class="card stat-card" style="--accent:#f04438; --accent-soft:var(--danger-soft)">
            <div class="stat-icon"><svg class="icon icon-sm"><use href="#i-alert"/></svg></div>
            <div class="stat-label">Faulty Requests</div>
            <div class="stat-value skeleton" style="width:64px">0</div>
            <div class="stat-note"><span class="dot" style="background:var(--danger-dot)"></span>Requires field action</div>
          </div>
          <div class="card stat-card" style="--accent:#98a2b3; --accent-soft:#f2f4f7">
            <div class="stat-icon"><svg class="icon icon-sm"><use href="#i-info"/></svg></div>
            <div class="stat-label">Decommissioned</div>
            <div class="stat-value skeleton" style="width:64px">0</div>
            <div class="stat-note">Retired hardware</div>
          </div>
          <div class="card stat-card" style="--accent:#f79009; --accent-soft:var(--warning-soft)">
            <div class="stat-icon"><svg class="icon icon-sm"><use href="#i-branch"/></svg></div>
            <div class="stat-label">Grid Nodes</div>
            <div class="stat-value skeleton" style="width:88px">0</div>
            <div class="stat-note">Transformers · feeders</div>
          </div>
        </div>

        <div class="compo-grid">
          <div class="card compo-card">
            <div class="compo-title">Asset Status Composition</div>
            <div class="compo-sub">Share of meters per installation status</div>
            <div class="stack-bar" id="status-stack" aria-hidden="true"></div>
            <div class="stack-legend" id="status-legend"></div>
          </div>
          <div class="card compo-card">
            <div class="compo-title">Manufacturers</div>
            <div class="compo-sub">Meters by make</div>
            <div class="bar-rows" id="make-bars"></div>
          </div>
          <div class="card compo-card compo-card--phase">
            <div class="compo-title">Phase Mix</div>
            <div class="compo-sub">Single vs three phase connections</div>
            <div class="phase-rows" id="phase-rows"></div>
          </div>
        </div>
      </section>

      <!-- ================= MAP ================= -->
      <section class="view" id="view-map" data-view-panel="map">
        <div class="card map-card map-panel-wrap">
          <div class="card-head">
            <div class="map-legend" role="list" aria-label="Meter status legend">
              <span class="pill pill-installed" role="listitem"><span class="dot"></span>Installed</span>
              <span class="pill pill-faulty" role="listitem"><span class="dot"></span>Faulty</span>
              <span class="pill pill-decommissioned" role="listitem"><span class="dot"></span>Decommissioned</span>
            </div>
            <div class="card-head-right">
              <div class="radius-wrap">
                <label for="radius-slider">Radius</label>
                <input type="range" id="radius-slider" min="1" max="25" step="1" value="15"
                       aria-label="Search radius in kilometers">
                <span class="radius-badge" id="radius-label">15 km</span>
              </div>
            </div>
          </div>
          <div id="map" role="application" aria-label="Interactive map of meters in the Jaipur region"></div>
          <div class="map-status"><div class="map-count-chip" id="map-count">Locating meters&hellip;</div></div>
        </div>
      </section>

      <!-- ================= CONSUMPTION ================= -->
      <section class="view" id="view-consumption" data-view-panel="consumption">
        <div class="card cons-filters">
          <div class="cons-controls">
            <div class="field">
              <label for="cons-meter-id">Meter ID</label>
              <input type="text" id="cons-meter-id" value="J100000" placeholder="e.g. J100000" style="width:150px">
            </div>
            <div class="field">
              <label for="cons-from">From date</label>
              <input type="date" id="cons-from" value="2026-06-24">
            </div>
            <div class="field">
              <label for="cons-to">To date</label>
              <input type="date" id="cons-to" value="2026-06-25">
            </div>
            <div class="preset-group" role="group" aria-label="Quick date ranges">
              <button class="preset-btn" onclick="applyPreset(1)">1d</button>
              <button class="preset-btn" onclick="applyPreset(3)">3d</button>
              <button class="preset-btn" onclick="applyPreset(7)">7d</button>
            </div>
            <button class="btn btn-primary" id="cons-fetch-btn" onclick="loadConsumption()">
              <span class="spinner spinner-dark" aria-hidden="true"></span>
              <span class="btn-label">Fetch Load Curve</span>
            </button>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <div>
              <div class="card-title" id="chart-title">30-minute interval load profile</div>
              <div class="card-desc" id="chart-desc">Cumulative energy and R-phase voltage over the selected window</div>
            </div>
            <div class="card-head-right">
              <div class="cons-summary" id="cons-summary" aria-live="polite"></div>
              <button class="chip-btn" id="export-cons-btn" onclick="exportConsumptionCSV()" disabled
                      title="Download the current window of readings as CSV">
                <svg class="icon icon-sm"><use href="#i-download"/></svg> CSV
              </button>
            </div>
          </div>
          <div class="chart-wrap" id="chart-wrap">
            <div class="empty-state" id="chart-empty">
              <svg class="icon"><use href="#i-activity"/></svg>
              <div class="empty-title">No readings plotted yet</div>
              <div style="font-size:12.5px">Choose a meter and date window, then fetch the load curve.</div>
            </div>
            <canvas id="consumptionChart" style="display:none" aria-label="Energy consumption chart"></canvas>
          </div>
        </div>
      </section>

      <!-- ================= HIERARCHY ================= -->
      <section class="view" id="view-hierarchy" data-view-panel="hierarchy">
        <div class="card">
          <div class="card-head">
            <div>
              <div class="card-title">Zone &rarr; Circle &rarr; Feeder &rarr; DT &rarr; Meters</div>
              <div class="card-desc">Click any node to expand or contract its branch</div>
            </div>
            <div class="card-head-right">
              <button class="btn btn-secondary" onclick="setTreeState(true, this)">
                <svg class="icon icon-sm"><use href="#i-chev-r"/></svg> Expand all
              </button>
              <button class="btn btn-secondary" onclick="setTreeState(false, this)">
                <svg class="icon icon-sm" style="transform:rotate(90deg)"><use href="#i-chev-r"/></svg> Collapse all
              </button>
              <button class="btn btn-secondary" onclick="loadHierarchy(true)" aria-label="Refresh hierarchy from portal">
                <svg class="icon icon-sm"><use href="#i-refresh"/></svg> Refresh
              </button>
            </div>
          </div>
          <div class="tree" id="hierarchy-tree-container" aria-label="Network hierarchy tree">
            <div class="empty-state">
              <div class="skeleton" style="width:60%;height:16px;margin:0 auto"></div>
              <div class="skeleton" style="width:40%;height:16px;margin:0 auto"></div>
              <div class="skeleton" style="width:50%;height:16px;margin:0 auto"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- ================= TRANSFORMERS ================= -->
      <section class="view" id="view-transformers" data-view-panel="transformers">
        <div class="dt-layout">
          <div class="card">
            <div class="card-head dt-head-col">
              <div class="field">
                <label for="dt-search">Search transformers</label>
                <div class="search-box">
                  <svg class="icon"><use href="#i-search"/></svg>
                  <input type="text" id="dt-search" placeholder="Code, name or feeder&hellip;" oninput="renderDTList()">
                </div>
              </div>
              <span class="tree-dim" id="dt-count" aria-live="polite"></span>
            </div>
            <div class="dt-list" id="dt-list" role="listbox" aria-label="Distribution transformers">
              <div class="empty-state">
                <div class="skeleton" style="width:70%;height:15px;margin:0 auto"></div>
                <div class="skeleton" style="width:50%;height:15px;margin:0 auto"></div>
                <div class="skeleton" style="width:60%;height:15px;margin:0 auto"></div>
              </div>
            </div>
          </div>
          <div class="card" id="dt-detail">
            <div class="empty-state">
              <svg class="icon" style="color:var(--text-3)"><use href="#i-tf"/></svg>
              <div class="empty-title">Select a transformer</div>
              <div style="font-size:12.5px">Pick a DT from the list to see its feeder, capacity and attached meters.</div>
            </div>
          </div>
        </div>
      </section>

      <!-- ================= METER INDEX ================= -->
      <section class="view" id="view-meters" data-view-panel="meters">
        <div class="card">
          <div class="table-filters">
            <div class="field">
              <label for="filter-q">Search</label>
              <div class="search-box">
                <svg class="icon"><use href="#i-search"/></svg>
                <input type="text" id="filter-q" placeholder="Meter ID or serial number&hellip;" oninput="debounceFilter()">
              </div>
            </div>
            <div class="field">
              <label for="filter-make">Make</label>
              <select id="filter-make" onchange="applyFilters()">
                <option value="">All makes</option>
                <option value="HPL">HPL</option>
                <option value="Genus">Genus</option>
                <option value="Secure">Secure</option>
                <option value="Allied">Allied</option>
                <option value="L&T">L&amp;T</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-phase">Phase</label>
              <select id="filter-phase" onchange="applyFilters()">
                <option value="">All phases</option>
                <option value="single">Single phase</option>
                <option value="three">Three phase</option>
              </select>
            </div>
            <div class="field">
              <label for="filter-status">Status</label>
              <select id="filter-status" onchange="applyFilters()">
                <option value="">All statuses</option>
                <option value="Installed">Installed</option>
                <option value="Faulty">Faulty</option>
                <option value="Decommissioned">Decommissioned</option>
              </select>
            </div>
            <button class="btn btn-ghost" onclick="resetFilters()">
              <svg class="icon icon-sm"><use href="#i-x"/></svg> Reset
            </button>
            <div style="margin-left:auto;display:flex;align-items:flex-end">
              <button class="btn btn-secondary" id="export-meters-btn" onclick="exportMetersCSV()"
                      title="Download every meter matching the current filters as CSV">
                <span class="spinner spinner-dark" aria-hidden="true"></span>
                <svg class="icon icon-sm" style="display:block"><use href="#i-download"/></svg>
                Export CSV
              </button>
            </div>
          </div>

          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Meter ID</th>
                  <th scope="col">Serial No</th>
                  <th scope="col">Make</th>
                  <th scope="col">Phase</th>
                  <th scope="col">Status</th>
                  <th scope="col">DT Code</th>
                  <th scope="col" style="text-align:right">Actions</th>
                </tr>
              </thead>
              <tbody id="meters-table-body">
                <tr><td colspan="7" style="text-align:center;color:var(--text-3);padding:40px 0">Loading meter index&hellip;</td></tr>
              </tbody>
            </table>
          </div>

          <div class="table-footer">
            <span id="filter-count" aria-live="polite">Showing meters&hellip;</span>
            <div class="pager">
              <button class="pager-btn" id="page-prev" onclick="changePage(-1)" aria-label="Previous page">
                <svg class="icon icon-sm"><use href="#i-chev-l"/></svg>
              </button>
              <span class="page-ind" id="page-ind">Page &ndash;</span>
              <button class="pager-btn" id="page-next" onclick="changePage(1)" aria-label="Next page">
                <svg class="icon icon-sm"><use href="#i-chev-r"/></svg>
              </button>
            </div>
          </div>
        </div>
      </section>

    </main>
  </div>
</div>

<!-- ============ Detail slide-over ============ -->
<div class="scrim" id="scrim" onclick="closeDetailPanel()"></div>
<div class="slideover" id="slideover" role="dialog" aria-modal="true" aria-labelledby="slideover-title">
  <div class="slideover-head">
    <h2 id="slideover-title">Meter Details</h2>
    <span id="slideover-status"></span>
    <button class="slideover-close" onclick="closeDetailPanel()" aria-label="Close details panel">
      <svg class="icon"><use href="#i-x"/></svg>
    </button>
  </div>
  <div class="slideover-body" id="slideover-body">
    <div class="empty-state">
      <div class="skeleton" style="width:70%;height:15px;margin:0 auto"></div>
      <div class="skeleton" style="width:50%;height:15px;margin:0 auto"></div>
      <div class="skeleton" style="width:65%;height:15px;margin:0 auto"></div>
    </div>
  </div>
</div>

<!-- ============ Keyboard shortcuts popover ============ -->
<div class="card kbd-pop" id="kbd-pop" role="dialog" aria-label="Keyboard shortcuts" hidden>
  <div class="kbd-pop-title">Keyboard shortcuts</div>
  <div class="kbd-row"><span>Switch views</span><span><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> <kbd>4</kbd> <kbd>5</kbd> <kbd>6</kbd></span></div>
  <div class="kbd-row"><span>Focus meter search</span><kbd>/</kbd></div>
  <div class="kbd-row"><span>Refresh stats</span><kbd>R</kbd></div>
  <div class="kbd-row"><span>This help</span><kbd>?</kbd></div>
  <div class="kbd-row"><span>Close panels</span><kbd>Esc</kbd></div>
</div>

<div class="toast-zone" id="toast-zone" role="status" aria-live="polite"></div>

<script>
  // ================= State =================
  const state = {
    view: 'overview',
    page: 1,
    radius: 15,
    loaded: new Set(),           // views whose data has been fetched at least once
    map: null,
    markers: null,
    chart: null,
    dtList: [],                  // cached transformer list
    dtSelected: null,            // currently selected DT code
    lastReadings: null,          // last fetched load curve (meterId + data), for CSV export
  };

  const VIEW_META = {
    overview:     ['Network Overview', 'Live summary of the Jaipur smart-meter distribution grid'],
    map:          ['Live Asset Map',   'Proximity view of meters around central Jaipur'],
    consumption:  ['Load Curve',       '30-minute interval energy & voltage for a single meter'],
    hierarchy:    ['Hierarchy Tree',   'Full grid topology from zones down to individual meters'],
    transformers: ['Transformers',     'Distribution transformers with feeder, capacity and attached meters'],
    meters:       ['Meter Index',      'Multi-attribute query layer over the meter fleet'],
  };

  const KEY_VIEWS = { '1': 'overview', '2': 'map', '3': 'consumption', '4': 'hierarchy', '5': 'transformers', '6': 'meters' };

  const $ = (id) => document.getElementById(id);
  const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('en-IN') : n);

  // ================= Toasts =================
  function toast(message, kind) {
    const zone = $('toast-zone');
    const el = document.createElement('div');
    el.className = 'toast' + (kind === 'danger' ? ' toast-danger' : '');
    el.innerHTML = kind === 'danger'
      ? '<svg class="icon icon-sm"><use href="#i-warn-circle"/></svg>'
      : '<svg class="icon icon-sm"><use href="#i-info"/></svg>';
    el.appendChild(document.createTextNode(message));
    zone.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  // ================= API helper =================
  async function api(url) {
    const resp = await fetch(url);
    if (!resp.ok) {
      const detail = await resp.json().then(j => (j.detail || j.error || '')).catch(() => '');
      const err = new Error('HTTP ' + resp.status + (detail ? ' — ' + detail : ''));
      err.status = resp.status;
      throw err;
    }
    return resp.json();
  }

  // ================= View router =================
  function switchView(view, pushHash = true) {
    if (!VIEW_META[view]) return;
    state.view = view;

    document.querySelectorAll('.nav-item[data-view]').forEach(b => {
      if (b.dataset.view === view) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    document.querySelectorAll('.view').forEach(v =>
      v.classList.toggle('active', v.dataset.viewPanel === view));

    $('view-title').textContent = VIEW_META[view][0];
    $('view-sub').textContent = VIEW_META[view][1];

    if (pushHash && location.hash !== '#/' + view) {
      history.replaceState(null, '', '#/' + view);
    }

    toggleSidebar(false);
    viewChanged(view);
  }

  function viewChanged(view) {
    if (view === 'map') {
      initMapOnce();
      setTimeout(() => state.map && state.map.invalidateSize(), 180);
      if (!state.loaded.has('map')) { state.loaded.add('map'); updateRadius(state.radius); }
    } else if (view === 'overview') {
      if (!state.loaded.has('overview')) { state.loaded.add('overview'); loadStats(); }
    } else if (view === 'consumption') {
      if (!state.loaded.has('consumption')) { state.loaded.add('consumption'); loadConsumption(); }
    } else if (view === 'hierarchy') {
      if (!state.loaded.has('hierarchy')) { state.loaded.add('hierarchy'); loadHierarchy(); }
    } else if (view === 'meters') {
      if (!state.loaded.has('meters')) { state.loaded.add('meters'); applyFilters(); }
    } else if (view === 'transformers') {
      if (!state.loaded.has('transformers')) { state.loaded.add('transformers'); loadTransformers(); }
    }
  }

  function toggleSidebar(open) {
    if (open === undefined) open = !$('sidebar').classList.contains('open');
    $('sidebar').classList.toggle('open', open);
    $('mobile-scrim').classList.toggle('open', open);
  }

  // ================= Overview =================
  async function loadStats(silent = false) {
    try {
      const stats = await api('/api/v1/stats');
      const cards = $('stat-grid').querySelectorAll('.stat-value');
      cards.forEach(c => c.classList.remove('skeleton'));

      const status = stats.statusBreakdown || {};
      cards[0].textContent = fmt(stats.totalMeters);
      cards[1].textContent = fmt(status['Installed'] || 0);
      cards[2].textContent = fmt(status['Faulty'] || 0);
      cards[3].textContent = fmt(status['Decommissioned'] || 0);
      cards[4].textContent = fmt((stats.totalTransformers || 0)) + ' · ' + fmt((stats.totalFeeders || 0));
      $('env-meter-count').textContent = fmt(stats.totalMeters) + ' meters';

      const updated = $('stats-updated');
      if (updated) {
        updated.textContent = 'Updated ' +
          new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
      const errCard = $('stat-error');
      if (errCard) errCard.remove();

      renderStatusComposition(status, stats.totalMeters);
      renderMakeBars(stats.makeBreakdown || {});
      renderPhaseMix(stats.phaseBreakdown || {});
    } catch (err) {
      document.querySelectorAll('#view-overview .stat-value').forEach(c => c.classList.remove('skeleton'));
      if (!$('stat-error')) {
        $('stat-grid').insertAdjacentHTML('beforeend',
          `<div class="card overview-error" id="stat-error" style="grid-column:1/-1;display:flex;gap:10px;align-items:center;color:var(--danger);font-size:13px">
             <svg class="icon"><use href="#i-warn-circle"/></svg> Could not load network stats (${err.message}). Press R or the refresh button to retry.
           </div>`);
      }
      if (!silent) toast('Stats refresh failed: ' + err.message, 'danger');
    }
  }

  function refreshStatsNow() {
    toggleShortcuts(false);
    if (state.loaded.has('overview')) loadStats(false);
  }

  function startAutoRefresh() {
    setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      if (!state.loaded.has('overview')) return;
      loadStats(true);
    }, 60000);
  }

  const STATUS_META = {
    Installed:       { color: '#12b76a', cls: 'pill-installed' },
    Faulty:          { color: '#f04438', cls: 'pill-faulty' },
    Decommissioned:  { color: '#98a2b3', cls: 'pill-decommissioned' },
  };

  function renderStatusComposition(status, total) {
    const entries = Object.entries(STATUS_META).map(([k, m]) => [k, status[k] || 0, m]);
    const grand = total || entries.reduce((a, [, v]) => a + v, 0) || 1;

    $('status-stack').innerHTML = entries.map(([, v, m]) =>
      `<div class="stack-seg" style="width:${(v / grand * 100).toFixed(2)}%;background:${m.color}"></div>`
    ).join('');

    $('status-legend').innerHTML = entries.map(([k, v, m]) => `
      <div class="legend-row">
        <span class="legend-swatch" style="background:${m.color}"></span> ${k}
        <span class="legend-pct">${(v / grand * 100).toFixed(1)}%</span>
        <span class="legend-count">${fmt(v)}</span>
      </div>`).join('');
  }

  const BAR_COLORS = ['#2563eb', '#6941c6', '#f79009', '#12b76a', '#f04438'];

  function renderMakeBars(makes) {
    const entries = Object.entries(makes).sort((a, b) => b[1] - a[1]);
    const total = entries.reduce((a, [, v]) => a + v, 0) || 1;
    const max = entries.length ? Math.max(...entries.map(e => e[1])) : 1;

    $('make-bars').innerHTML = entries.map(([make, count], i) => `
      <div class="bar-row">
        <span style="font-weight:600">${make}</span>
        <div class="bar-track">
          <div class="bar-fill" style="width:${(count / max * 100).toFixed(1)}%;background:${BAR_COLORS[i % BAR_COLORS.length]}"></div>
        </div>
        <span class="bar-count">${fmt(count)} <span style="color:var(--text-3)">·${(count / total * 100).toFixed(0)}%</span></span>
      </div>`).join('') || '<div class="tree-dim">No manufacturer data.</div>';
  }

  function renderPhaseMix(phases) {
    const rows = [
      ['Single phase', phases['single'] || 0, '#2563eb'],
      ['Three phase',  phases['three'] || 0,  '#6941c6'],
    ];
    $('phase-rows').innerHTML = rows.map(([label, count, color]) => `
      <div class="phase-row">
        <span class="legend-swatch" style="background:${color};border-radius:50%"></span>
        <span style="font-size:12.5px;font-weight:500">${label}</span>
        <b>${fmt(count)}</b>
      </div>`).join('');
  }

  // ================= Map =================
  function initMapOnce() {
    if (state.map) return;
    state.map = L.map('map', { zoomControl: true }).setView([26.9124, 75.7873], 12);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(state.map);
    state.markers = L.layerGroup().addTo(state.map);
  }

  function statusClass(s) {
    if (s === 'Faulty') return 'pill-faulty';
    if (s === 'Decommissioned') return 'pill-decommissioned';
    return 'pill-installed';
  }
  function statusColor(s) {
    if (s === 'Faulty') return '#f04438';
    if (s === 'Decommissioned') return '#8a94a6';
    return '#12b76a';
  }

  function renderMapMarkers(meters) {
    if (!state.markers) return;
    state.markers.clearLayers();

    meters.forEach(m => {
      if (!m.latitude || !m.longitude) return;
      const color = statusColor(m.installStatus);
      const marker = L.circleMarker([m.latitude, m.longitude], {
        radius: 6.5,
        fillColor: color,
        color: '#ffffff',
        weight: 1.5,
        opacity: 0.9,
        fillOpacity: 0.9,
      });

      marker.bindPopup(`
        <div>
          <div class="popup-title">${m.meterId}
            <span class="pill ${statusClass(m.installStatus)}"><span class="dot"></span>${m.installStatus || '?'}
            </span>
          </div>
          <div class="popup-rows">
            <div>Serial&nbsp;&nbsp;<b>${m.serialNo || 'N/A'}</b></div>
            <div>Make&nbsp;&nbsp;&nbsp;&nbsp;<b>${m.make || 'N/A'}</b> · ${m.phaseType || ''}</div>
            <div>DT&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>${m.dtCode || 'N/A'}</b></div>
          </div>
          <div class="popup-actions">
            <button class="popup-btn popup-btn-primary" onclick="openLoadCurve('${m.meterId}')">Load curve</button>
            <button class="popup-btn" onclick="openDetailPanel('${m.meterId}')">Details</button>
          </div>
        </div>`);
      state.markers.addLayer(marker);
    });

    $('map-count').innerHTML = fmt(meters.length) + ' meters within <b>&nbsp;' + state.radius + ' km</b> of Jaipur center';
  }

  function openLoadCurve(meterId) {
    $('cons-meter-id').value = meterId;
    switchView('consumption');
    loadConsumption();
  }

  async function updateRadius(km) {
    state.radius = km;
    $('radius-label').textContent = km + ' km';
    try {
      const json = await api(`/api/v1/meters/nearby?lat=26.9124&lon=75.7873&radius_km=${km}&limit=500`);
      renderMapMarkers(json.data || []);
    } catch (err) {
      $('map-count').textContent = 'Failed to load nearby meters — ' + err.message;
      toast('Proximity search failed: ' + err.message, 'danger');
    }
  }

  let radiusTimeout;
  $('radius-slider').addEventListener('input', (e) => {
    clearTimeout(radiusTimeout);
    $('radius-label').textContent = e.target.value + ' km';
    radiusTimeout = setTimeout(() => updateRadius(e.target.value), 320);
  });

  // ================= Consumption =================
  function applyPreset(days) {
    const to = $('cons-to').value ? new Date($('cons-to').value) : new Date('2026-06-25');
    const from = new Date(to);
    from.setDate(from.getDate() - days + 1);
    $('cons-from').value = from.toISOString().slice(0, 10);
    loadConsumption();
  }

  async function loadConsumption() {
    const btn = $('cons-fetch-btn');
    const meterId = $('cons-meter-id').value.trim() || 'J100000';
    const fromDate = $('cons-from').value;
    const toDate = $('cons-to').value;

    let url = `/api/v1/meters/${encodeURIComponent(meterId)}/consumption`;
    const params = [];
    if (fromDate) params.push('from=' + fromDate);
    if (toDate) params.push('to=' + toDate);
    if (params.length) url += '?' + params.join('&');

    btn.disabled = true;
    btn.classList.add('loading');

    try {
      const json = await api(url);
      const data = json.data || [];
      state.lastReadings = { meterId, data };
      const exportBtn = $('export-cons-btn');
      if (exportBtn) exportBtn.disabled = data.length === 0;
      renderChart(meterId, data);

      const summary = $('cons-summary');
      if (data.length > 0) {
        const avgVolt = (data.reduce((acc, r) => acc + (r.voltR || 0), 0) / data.length).toFixed(1);
        const last = data[data.length - 1];
        summary.innerHTML =
          `<span>Intervals <b>${fmt(data.length)}</b></span><span class="sep"></span>` +
          `<span>Avg voltage <b>${avgVolt} V</b></span><span class="sep"></span>` +
          `<span>Latest kWh <b>${last.kwh ?? 'N/A'}</b></span>`;
      } else {
        summary.innerHTML = '<span style="color:var(--text-3)">No readings found for the selected window</span>';
      }
    } catch (err) {
      $('cons-summary').innerHTML =
        `<span style="color:var(--danger);display:inline-flex;gap:6px;align-items:center">
           <svg class="icon icon-sm"><use href="#i-warn-circle"/></svg>
           Fetch failed: ${err.message}
         </span>`;
      if (err.status === 404) toast(`Meter "${meterId}" was not found.`, 'danger');
    } finally {
      btn.disabled = false;
      btn.classList.remove('loading');
    }
  }

  function renderChart(meterId, readings) {
    $('chart-empty').style.display = readings.length ? 'none' : 'flex';
    const canvas = $('consumptionChart');
    canvas.style.display = readings.length ? 'block' : 'none';
    $('chart-title').textContent = 'Meter ' + meterId + ' — 30-minute interval profile';
    $('chart-desc').textContent = readings.length
      ? readings.length + ' readings · ' + readings[0].timestamp.slice(0, 10) + ' → ' + readings[readings.length - 1].timestamp.slice(0, 10)
      : 'No data returned for this window — try widening the date range.';

    if (state.chart) state.chart.destroy();
    if (!readings.length) return;

    const labels = readings.map(r => r.timestamp.replace('T', ' ').slice(5, 16));
    const kwhData = readings.map(r => r.kwh);
    const voltData = readings.map(r => r.voltR);

    state.chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Cumulative energy (kWh)',
            data: kwhData,
            borderColor: '#2563eb',
            backgroundColor: (ctx) => {
              const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height || 300);
              g.addColorStop(0, 'rgba(37, 99, 235, 0.16)');
              g.addColorStop(1, 'rgba(37, 99, 235, 0.01)');
              return g;
            },
            yAxisID: 'yKwh',
            tension: 0.35,
            fill: true,
            borderWidth: 2,
            pointRadius: readings.length > 120 ? 0 : 2,
            pointHoverRadius: 4,
          },
          {
            label: 'Voltage R-phase (V)',
            data: voltData,
            borderColor: '#f79009',
            backgroundColor: 'transparent',
            yAxisID: 'yVolt',
            tension: 0.35,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            labels: { color: '#475467', usePointStyle: true, pointStyle: 'circle', boxWidth: 7, padding: 16 },
          },
          tooltip: {
            backgroundColor: '#101828',
            titleColor: '#f2f4f7',
            bodyColor: '#d0d5dd',
            padding: 10,
            cornerRadius: 8,
            displayColors: false,
          },
        },
        scales: {
          x: {
            ticks: { color: '#98a2b3', maxTicksLimit: 10, maxRotation: 0 },
            grid: { color: 'rgba(16, 24, 40, 0.05)' },
            border: { display: false },
          },
          yKwh: {
            position: 'left',
            ticks: { color: '#2563eb', font: { family: "'JetBrains Mono', monospace", size: 10.5 } },
            grid: { color: 'rgba(16, 24, 40, 0.05)' },
            border: { display: false },
            title: { display: true, text: 'kWh', color: '#98a2b3', font: { size: 10.5 } },
          },
          yVolt: {
            position: 'right',
            ticks: { color: '#b54708', font: { family: "'JetBrains Mono', monospace", size: 10.5 } },
            grid: { drawOnChartArea: false },
            border: { display: false },
            title: { display: true, text: 'Volts', color: '#98a2b3', font: { size: 10.5 } },
          },
        },
      },
    });
  }

  // ================= Hierarchy =================
  async function loadHierarchy(force = false) {
    const container = $('hierarchy-tree-container');
    if (force) {
      container.innerHTML = '<div class="empty-state"><span class="spinner spinner-dark" style="animation:none"></span></div>' +
        '<div class="empty-state" style="padding-top:8px"><div class="empty-title">Refreshing from portal&hellip;</div></div>';
    }
    try {
      const json = await api('/api/v1/hierarchy' + (force ? '?force_refresh=true' : ''));
      container.innerHTML = renderZones(json.zones || []);
    } catch (err) {
      container.innerHTML =
        `<div class="empty-state">
           <svg class="icon"><use href="#i-warn-circle"/></svg>
           <div class="empty-title">Failed to load network hierarchy</div>
           <div style="font-size:12.5px">${err.message} — check the gateway status, then press Refresh.</div>
         </div>`;
    }
  }

  function treeToggle(name, code, tag, dim, childrenHtml) {
    return `
      <button class="tree-row" data-tree-toggle aria-expanded="true">
        <svg class="tree-chevron icon-sm"><use href="#i-chev-r"/></svg>
        <span class="tree-name">${name}</span>
        ${code ? `<span class="tag">${code}</span>` : ''}
        ${dim ? `<span class="tree-dim">${dim}</span>` : ''}
      </button>
      <div class="tree-children">${childrenHtml}</div>`;
  }

  function renderZones(zones) {
    if (!Array.isArray(zones) || !zones.length)
      return '<div class="empty-state"><div class="empty-title">No zone data returned.</div></div>';

    function renderFeeder(f) {
      const dts = (f.transformers || []).map(dt =>
        treeGroup(dt.name, dt.code, renderMeterChips(dt.meters),
          `<span class="tag" style="background:var(--warning-soft);color:var(--warning);border-color:var(--warning-border)">${dt.metersCount} meters</span>`)
      ).join('');
      return treeGroup('Feeder ' + f.name, f.code, dts, `${f.transformersCount ?? '?'} DTs`);
    }

    function renderCircle(c) {
      const feeders = (c.divisions || []).flatMap(d => (d.subdivisions || []).flatMap(sd =>
        (sd.substations || []).map(ss => ss.feeders))).flat().map(renderFeeder).join('');
      return treeGroup(c.name, c.code, feeders, '');
    }

    return zones.map(z =>
      `<div class="tree-group">${treeToggle(z.name, z.code, '', '', z.circles.map(renderCircle).join(''))}</div>`
    ).join('');
  }

  function treeGroup(name, code, childrenHtml, dim) {
    return `<div class="tree-group">${treeToggle(name, code, '', dim, childrenHtml || '')}</div>`;
  }

  function renderMeterChips(meters) {
    if (!meters || !meters.length) return '<div class="tree-dim" style="padding:4px 0">No meters attached.</div>';
    return `<div style="padding:2px 0 4px">` + meters.map(m =>
      `<button class="meter-chip" onclick="openDetailPanel('${m.meterId}')" title="Open meter details">
         <span class="dot" style="width:6px;height:6px;border-radius:50%;background:${statusColor(m.installStatus)}"></span>
         ${m.meterId}
       </button>`).join('') + `</div>`;
  }

  // Delegate toggle clicks (chevron rows)
  document.addEventListener('click', (e) => {
    const row = e.target.closest('[data-tree-toggle]');
    if (!row) return;
    const open = row.getAttribute('aria-expanded') !== 'true';
    row.setAttribute('aria-expanded', String(open));
  });

  function setTreeState(open, btn) {
    document.querySelectorAll('#hierarchy-tree-container [data-tree-toggle]')
      .forEach(r => r.setAttribute('aria-expanded', String(open)));
  }

  // ================= Transformers =================
  async function loadTransformers() {
    const listEl = $('dt-list');
    try {
      // Portal paginates 20 rows per page; collect all pages (small dataset, ~40 DTs).
      const collected = [];
      for (let page = 1; page <= 5; page++) {
        const json = await api('/api/v1/transformers?page=' + page);
        collected.push(...(json.data || []));
        const total = json.total ?? collected.length;
        if (collected.length >= total || !(json.data || []).length) break;
      }
      state.dtList = collected;
      renderDTList();
      if (collected.length) selectDT(collected[0].code);
    } catch (err) {
      listEl.innerHTML =
        `<div class="empty-state" style="color:var(--danger)">
           <svg class="icon"><use href="#i-warn-circle"/></svg>
           <div class="empty-title">Failed to load transformers</div>
           <div style="font-size:12.5px">${err.message}</div>
         </div>`;
    }
  }

  function filteredDTList() {
    const q = $('dt-search').value.trim().toLowerCase();
    return state.dtList.filter(dt => !q ||
      (dt.code || '').toLowerCase().includes(q) ||
      (dt.name || '').toLowerCase().includes(q) ||
      (dt.feederCode || '').toLowerCase().includes(q));
  }

  function renderDTList() {
    const listEl = $('dt-list');
    const items = filteredDTList();
    $('dt-count').textContent = fmt(items.length) + ' of ' + fmt(state.dtList.length) + ' transformers';

    listEl.innerHTML = items.map(dt => `
      <button class="dt-row${state.dtSelected === dt.code ? ' selected' : ''}"
              role="option" aria-selected="${state.dtSelected === dt.code}"
              onclick="selectDT('${dt.code}')">
        <div style="min-width:0">
          <div class="dt-code">${dt.code}</div>
          <div class="dt-name" style="overflow-wrap:anywhere">${dt.name || 'Distribution transformer'}</div>
        </div>
        <div class="dt-meta">
          <span class="tag">${dt.feederCode || '—'}</span>
          <span class="pill pill-plain tnum">${dt.capacityKva ? dt.capacityKva + ' kVA' : '—'}</span>
        </div>
      </button>`).join('') ||
      '<div class="empty-state"><div class="empty-title">No transformers match your search</div></div>';
  }

  async function selectDT(code) {
    state.dtSelected = code;
    renderDTList();

    const dt = state.dtList.find(x => x.code === code) || {};
    const detail = $('dt-detail');
    detail.innerHTML = `
      <div class="dt-detail-pad">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <div class="dt-code" style="font-size:15px">${code}</div>
          <h2 style="font-size:14.5px;font-weight:600">${dt.name || 'Distribution transformer'}</h2>
        </div>
        <div class="dt-meta-grid">
          <span>Feeder <b class="mono">${dt.feederCode || '—'}</b></span>
          <span>Capacity <b class="tnum">${dt.capacityKva ? dt.capacityKva + ' kVA' : '—'}</b></span>
          <span>Attached meters <b class="tnum" id="dt-meter-count">…</b></span>
        </div>
        <div class="section-label" style="margin-top:20px">Status mix</div>
        <div class="stack-bar" id="dt-stack" aria-hidden="true"></div>
        <div class="stack-legend" id="dt-legend" style="max-width:420px">
          <div class="skeleton" style="width:60%;height:14px"></div>
          <div class="skeleton" style="width:45%;height:14px"></div>
        </div>
        <div class="section-label">Attached meters</div>
        <div id="dt-meters">
          <span class="spinner spinner-dark"></span>
          <span class="tree-dim" style="margin-left:8px">Querying meter index for this DT…</span>
        </div>
      </div>`;

    try {
      const json = await api('/api/v1/meters/query?dt=' + encodeURIComponent(code) + '&page_size=100');
      const meters = json.data || [];

      if (state.dtSelected !== code) return;  // user moved on to another DT

      // tally status
      const tally = { Installed: 0, Faulty: 0, Decommissioned: 0, other: 0 };
      meters.forEach(m => {
        if (tally[m.installStatus] !== undefined) tally[m.installStatus]++;
        else tally.other++;
      });

      // hand-render the status composition inside the DT panel
      const stack = $('dt-stack'), legend = $('dt-legend');
      const entries = Object.entries(STATUS_META).map(([k, m]) => [k, tally[k] || 0, m]);
      const grand = meters.length || 1;
      stack.innerHTML = entries.map(([, v, m]) =>
        `<div class="stack-seg" style="width:${(v / grand * 100).toFixed(2)}%;background:${m.color}"></div>`).join('');
      legend.innerHTML = entries.map(([k, v, m]) => `
        <div class="legend-row">
          <span class="legend-swatch" style="background:${m.color}"></span> ${k}
          <span class="legend-pct">${(v / grand * 100).toFixed(1)}%</span>
          <span class="legend-count">${fmt(v)}</span>
        </div>`).join('');

      $('dt-meter-count').textContent = meters.length;
      $('dt-meters').innerHTML =
        meters.length
          ? renderMeterChips(meters)
          : '<div class="tree-dim">No meters are attached to this transformer.</div>';
    } catch (err) {
      if (state.dtSelected !== code) return;
      $('dt-meters').innerHTML =
        `<div class="empty-state" style="align-items:flex-start;padding:12px 0;color:var(--danger)">
           <svg class="icon"><use href="#i-warn-circle"/></svg>
           <div class="empty-title">Could not load meters for this DT — ${err.message}</div>
         </div>`;
      $('dt-legend').innerHTML = '';
    }
  }

  // ================= Meter Index =================
  function meterQueryParams() {
    const params = new URLSearchParams();
    const q = $('filter-q').value.trim();
    const make = $('filter-make').value;
    const phase = $('filter-phase').value;
    const status = $('filter-status').value;
    if (q) params.set('q', q);
    if (make) params.set('make', make);
    if (phase) params.set('phase', phase);
    if (status) params.set('status', status);
    return params;
  }

  let filterTimeout;
  function debounceFilter() {
    clearTimeout(filterTimeout);
    filterTimeout = setTimeout(() => { state.page = 1; applyFilters(); }, 280);
  }

  function changePage(delta) {
    state.page = Math.max(1, state.page + delta);
    applyFilters();
  }

  function resetFilters() {
    ['filter-q', 'filter-make', 'filter-phase', 'filter-status'].forEach(id => $(id).value = '');
    state.page = 1;
    applyFilters();
  }

  async function applyFilters() {
    const params = meterQueryParams();
    params.set('page_size', '20');
    params.set('page', String(state.page));

    const tbody = $('meters-table-body');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px 0"><span class="spinner spinner-dark"></span></td></tr>';

    try {
      const json = await api('/api/v1/meters/query?' + params.toString());
      const meters = json.data || [];
      const filteredTotal = json.filteredTotal ?? meters.length;
      const pageSize = json.pageSize || 20;
      const pageCount = Math.max(1, Math.ceil(filteredTotal / pageSize));
      state.page = json.page || state.page;

      $('filter-count').textContent =
        `Showing ${fmt(meters.length)} of ${fmt(filteredTotal)} matching meters (${fmt(json.total ?? '')} total in fleet)`;
      $('page-ind').textContent = `Page ${state.page} / ${pageCount}`;
      $('page-prev').disabled = state.page <= 1;
      $('page-next').disabled = state.page >= pageCount;

      if (meters.length === 0) {
        tbody.innerHTML =
          `<tr><td colspan="7">
             <div class="empty-state">
               <svg class="icon"><use href="#i-search"/></svg>
               <div class="empty-title">No meters match these filters</div>
               <div style="font-size:12.5px">Try clearing a filter or widening your search term.</div>
             </div>
           </td></tr>`;
        return;
      }

      tbody.innerHTML = meters.map(m => `
        <tr>
          <td class="mono" style="font-weight:600;color:var(--primary)">${m.meterId}</td>
          <td class="mono" style="color:var(--text-2)">${m.serialNo || '<span style="color:var(--text-3)">—</span>'}</td>
          <td>${m.make || '—'}</td>
          <td><span class="pill ${m.phaseType === 'three' ? 'pill-phase-three' : m.phaseType ? 'pill-phase' : 'pill-plain'}">${m.phaseType || '?'}</span></td>
          <td><span class="pill ${statusClass(m.installStatus)}"><span class="dot"></span>${m.installStatus || '?'}</span></td>
          <td class="mono" style="color:var(--text-2)">${m.dtCode || '—'}</td>
          <td style="text-align:right">
            <div class="row-actions" style="justify-content:flex-end">
              <button class="chip-btn" onclick="openDetailPanel('${m.meterId}')">
                <svg class="icon icon-sm"><use href="#i-info"/></svg> Details
              </button>
              <button class="chip-btn chip-btn-accent" onclick="openLoadCurve('${m.meterId}')">
                <svg class="icon icon-sm"><use href="#i-activity"/></svg> Curve
              </button>
            </div>
          </td>
        </tr>`).join('');
    } catch (err) {
      tbody.innerHTML =
        `<tr><td colspan="7">
           <div class="empty-state" style="color:var(--danger)">
             <svg class="icon"><use href="#i-warn-circle"/></svg>
             <div class="empty-title">Query failed — ${err.message}</div>
             <div style="font-size:12.5px">Adjust the filters or retry in a moment.</div>
           </div>
         </td></tr>`;
    }
  }

  // ================= CSV export =================
  const CSV_INJECTION = /^[=+\\-@\\t\\r]/;

  function csvCell(value) {
    if (value === null || value === undefined) return '';
    let s = String(value);
    if (CSV_INJECTION.test(s)) s = "'" + s;              // guard spreadsheet formula injection
    if (/[",\\n\\r]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function downloadCSV(filename, headers, rows) {
    const lines = [headers.map(csvCell).join(',')]
      .concat(rows.map(r => r.map(csvCell).join(',')));
    const blob = new Blob(['\uFEFF' + lines.join('\\r\\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  const todayStamp = () => new Date().toISOString().slice(0, 10);
  const EXPORT_METER_CAP = 2500;

  async function exportMetersCSV() {
    const btn = $('export-meters-btn');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    btn.classList.add('loading');

    try {
      const rows = [];
      const pageSize = 100;
      let page = 1, total = 0, truncated = false;

      while (true) {
        const params = meterQueryParams();
        params.set('page_size', String(pageSize));
        params.set('page', String(page));
        const json = await api('/api/v1/meters/query?' + params.toString());
        total = json.filteredTotal ?? json.total ?? 0;
        rows.push(...(json.data || []));

        if (!(json.data || []).length) break;
        if (rows.length >= total) break;
        if (rows.length >= EXPORT_METER_CAP) { truncated = true; break; }
        page++;
      }

      const headers = ['Meter ID', 'Serial No', 'Make', 'Phase', 'Install Status', 'DT Code'];
      const data = rows.map(m => [m.meterId, m.serialNo ?? '', m.make ?? '',
        m.phaseType ?? '', m.installStatus ?? '', m.dtCode ?? '']);
      const name = 'meter-index-' + todayStamp() + '.csv';
      downloadCSV(name, headers, data);
      toast('Exported ' + fmt(rows.length) + ' meters to ' + name +
        (truncated ? ' (first ' + EXPORT_METER_CAP + ' only)' : ''));
    } catch (err) {
      toast('CSV export failed: ' + err.message, 'danger');
    } finally {
      btn.disabled = false;
      btn.classList.remove('loading');
    }
  }

  function exportConsumptionCSV() {
    const last = state.lastReadings;
    if (!last || !last.data.length) {
      toast('Fetch a load curve first, then export it.', 'danger');
      return;
    }
    const headers = ['Timestamp', 'Active Energy (kWh)', 'Apparent Energy (kVAh)', 'Voltage R-Phase (V)'];
    const rows = last.data.map(r => [r.timestamp, r.kwh ?? '', r.kvah ?? '', r.voltR ?? '']);
    const name = 'load-curve-' + last.meterId + '-' + todayStamp() + '.csv';
    downloadCSV(name, headers, rows);
    toast('Exported ' + fmt(last.data.length) + ' readings to ' + name);
  }

  // ================= Detail slide-over =================
  async function openDetailPanel(meterId) {
    const panel = $('slideover');
    $('slideover-title').textContent = meterId;
    $('slideover-status').innerHTML = '<span class="tag">&nbsp;loading…&nbsp;</span>';
    $('slideover-body').innerHTML =
      '<div class="empty-state"><span class="spinner spinner-dark" style="animation:none"></span></div>' +
      '<div class="empty-state" style="padding-top:8px"><div class="empty-title">Fetching details from portal adapter…</div></div>';
    panel.classList.add('open');
    $('scrim').classList.add('open');

    try {
      const json = await api('/api/v1/meters/' + encodeURIComponent(meterId));
      const detail = json.nameplate?.find?.(np => /status/i.test(np.parameterName));
      const statusValue = json.installStatus || detail?.parameterValue || null;
      $('slideover-status').innerHTML = statusValue
        ? `<span class="pill ${statusClass(statusValue)}"><span class="dot"></span>${statusValue}</span>`
        : '';

      const npRows = (json.nameplate || []).map(np => `
        <div class="kv-row">
          <span class="kv-key">${np.parameterName}</span>
          <span class="kv-val mono">${np.parameterValue ?? 'null'}</span>
        </div>`).join('');

      const hRows = Object.entries(json.hierarchy || {}).map(([k, v]) => `
        <div class="kv-row">
          <span class="kv-key">${k}</span>
          <span class="kv-val mono">${v ?? 'null'}</span>
        </div>`).join('');

      const geo = json.location
        ? `${json.location.latitude}, ${json.location.longitude}`
        : 'No GPS coordinates available';

      const actions = `
        <div style="display:flex; gap:8px; margin-top:20px">
          <button class="btn btn-primary" style="flex:1" onclick="openLoadCurve('${meterId}')">
            <svg class="icon icon-sm"><use href="#i-activity"/></svg> View load curve
          </button>
          <button class="btn btn-secondary" onclick="location.href='/api/v1/meters/${encodeURIComponent(meterId)}'" target="_blank" rel="noopener">
            <svg class="icon icon-sm"><use href="#i-braces"/></svg> Raw JSON
          </button>
        </div>`;

      $('slideover-body').innerHTML = `
        ${actions}
        <div class="section-label" style="margin-top:24px"><svg class="icon icon-sm"><use href="#i-info"/></svg> Nameplate parameters</div>
        <div class="kv-list">${npRows || '<div class="kv-row"><span class="kv-key">—</span></div>'}</div>

        <div class="section-label"><svg class="icon icon-sm"><use href="#i-branch"/></svg> Network hierarchy</div>
        <div class="kv-list">${hRows || '<div class="kv-row"><span class="kv-key">—</span></div>'}</div>

        <div class="section-label"><svg class="icon icon-sm"><use href="#i-pin"/></svg> Geographic location</div>
        <div class="geo-box">
          <svg class="icon icon-sm" style="color:var(--primary)"><use href="#i-pin"/></svg> ${geo}
        </div>

        ${json.warnings && json.warnings.length ? `
          <div class="section-label" style="color:var(--danger)"><svg class="icon icon-sm"><use href="#i-alert"/></svg> Warnings · anomalies</div>
          ${json.warnings.map(w => `
            <div class="alert-line">
              <svg class="icon icon-sm"><use href="#i-alert"/></svg>
              <span>${w}</span>
            </div>`).join('')}
        ` : ''}`;
    } catch (err) {
      $('slideover-body').innerHTML =
        `<div class="empty-state" style="color:var(--danger)">
           <svg class="icon"><use href="#i-warn-circle"/></svg>
           <div class="empty-title">Could not load meter details</div>
           <div style="font-size:12.5px">${err.message}</div>
           <button class="btn btn-secondary" style="margin-top:10px" onclick="openDetailPanel('${meterId}')">Retry</button>
         </div>`;
      $('slideover-status').innerHTML = '';
    }
  }

  function closeDetailPanel() {
    $('slideover').classList.remove('open');
    $('scrim').classList.remove('open');
  }

  // ================= Keyboard shortcuts + help popover =================
  function toggleShortcuts(force) {
    const pop = $('kbd-pop');
    const open = force !== undefined ? force : pop.hidden;
    pop.hidden = !open;
  }

  document.addEventListener('click', (e) => {
    const pop = $('kbd-pop');
    if (!pop.hidden && !e.target.closest('#kbd-pop') && !e.target.closest('[data-kbd-toggle]')) {
      toggleShortcuts(false);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!$('kbd-pop').hidden) toggleShortcuts(false);
      else closeDetailPanel();
      return;
    }
    const t = e.target;
    const typing = t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' ||
      t.tagName === 'TEXTAREA' || t.isContentEditable || t.tagName === 'BUTTON');
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;

    if (KEY_VIEWS[e.key]) switchView(KEY_VIEWS[e.key]);
    else if (e.key === '/' || e.key === 's') {
      e.preventDefault();
      switchView('meters');
      $('filter-q').focus();
    } else if (e.key === 'r' || e.key === 'R') {
      refreshStatsNow();
    } else if (e.key === '?' && $('kbd-pop')) {
      toggleShortcuts();
    }
  });

  // ================= Bootstrap =================
  function init() {
    const hash = location.hash.replace('#/', '');
    switchView(VIEW_META[hash] ? hash : 'overview', false);
    viewChanged(state.view);
    startAutoRefresh();
  }

  window.addEventListener('DOMContentLoaded', init);

  // Hash navigation within the same document (pasting a new #/ link or using
  // browser back) must re-route without a full page reload.
  window.addEventListener('hashchange', () => {
    const hash = location.hash.replace('#/', '');
    if (VIEW_META[hash]) switchView(hash, false);
  });
</script>
</body>
</html>
"""
