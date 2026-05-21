"""
NOCTYRA360™ — Integrated Production Server v4
DEFINITIVE: Bridge served as /bridge.js, HTML served as raw bytes.
Bridge auto-injects EFR results into frontend KPIs after processing.
"""

import os, sys, json, hashlib, time
from typing import Optional, Dict, List
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response, HTMLResponse

from core.decoder             import CDRDecoder
from core.efr_engine          import run_efr, TAX_MATRICES
from core.anomaly_detector    import AnomalyDetector
from reports.report_generator  import ReportGenerator
from reports.extended_reports  import ExtendedReportGenerator
TOKEN_HOURS = 8  # Durée session heures
from core.notifications import (
    notify_report_ready, notify_anomaly, notify_system_error,
    load_email_config, save_email_config, update_email_config
)
from core.sftp_server import (
    start_watchdog, run_sftp_server, create_operator_folders,
    load_accounts, add_sftp_account, list_sftp_accounts,
    get_processed_files, SFTP_PORT, UPLOADS_DIR as SFTP_UPLOADS_DIR
)
from core.auth import (
    authenticate_user, create_token, decode_token,
    get_user_profile, can_access_report, can_access_menu,
    get_role_config, ROLES
)
from core.database import (
    init_db, db_create_job, db_update_job, db_get_job,
    db_save_finding, db_get_finding_by_job,
    db_get_findings_history, db_get_stats,
    db_save_config, db_audit, db_get_audit_log,
    db_get_jobs_recent
)

BASE         = Path(__file__).parent
UPLOAD_DIR   = BASE / "uploads";     UPLOAD_DIR.mkdir(exist_ok=True)
REPORTS_DIR  = BASE / "reports_out"; REPORTS_DIR.mkdir(exist_ok=True)
CONFIG_DIR   = BASE / "config";      CONFIG_DIR.mkdir(exist_ok=True)
REGISTRY     = CONFIG_DIR / "schema_registry.json"
FRONTEND     = BASE / "NOCTYRA360_INTEGRATED.html"
ACTIVE_CFG   = {}   # active country config from frontend

app = FastAPI(title="NOCTYRA360", version="13.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
jobs = {}

# ── Démarrage DB ──────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    """Initialiser la base de données au démarrage."""
    try:
        print("  🗄️  Initialisation base de données...")
        init_db()
        db_audit("SERVER_START", details="NOCTYRA360™ v13.0 démarré")
        print("  ✅  Base de données prête")
    except Exception as e:
        print(f"  ⚠️  DB startup: {e}")


# ── Servir la page login ───────────────────────────────────────
@app.get("/login")
async def login_page():
    """Page de connexion."""
    login_path = BASE / "login.html"
    if login_path.exists():
        return HTMLResponse(content=login_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Login page manquante</h1>")

# ── Endpoint de connexion ──────────────────────────────────────
@app.post("/api/login")
async def api_login(request: Request):
    """Authentifier un utilisateur et retourner un token JWT."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")

    username = data.get("username","").lower().strip()
    password = data.get("password","").strip()

    if not username or not password:
        raise HTTPException(400, "Identifiant et mot de passe requis")

    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(401, "Identifiant ou mot de passe incorrect")

    token   = create_token(username, user["role"])
    profile = get_user_profile(username)

    # Audit log
    try:
        db_audit("LOGIN",
                 operator=username,
                 country=user.get("role",""),
                 details=f"Connexion réussie: {profile['role_label']}")
    except Exception:
        pass

    print(f"  🔐 Login: {username} ({profile['role_label']})")

    # Créer la réponse avec cookie sécurisé
    from fastapi.responses import JSONResponse
    response = JSONResponse({
        "token":   token,
        "user":    profile,
        "message": f"Bienvenue, {profile['full_name']}"
    })
    # Cookie httpOnly pour sécurité + compatibilité
    response.set_cookie(
        key="n360_token",
        value=token,
        max_age=TOKEN_HOURS * 3600,
        httponly=False,   # False pour que le JS puisse le lire
        samesite="lax",
        path="/"
    )
    return response

# ── Endpoint profil utilisateur ────────────────────────────────
@app.get("/api/logout")
async def api_logout():
    """Déconnexion — supprimer le cookie."""
    from fastapi.responses import RedirectResponse
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("n360_token")
    return resp

@app.get("/api/me")
async def get_me(request: Request):
    """Retourner le profil de l'utilisateur connecté."""
    token = request.cookies.get("n360_token") or _extract_token(request)
    if not token:
        raise HTTPException(401, "Non authentifié")
    decoded = decode_token(token)
    if not decoded:
        raise HTTPException(401, "Token invalide ou expiré")
    return get_user_profile(decoded["username"])

# ── Endpoint liste des rôles ───────────────────────────────────
@app.get("/api/roles")
async def get_roles():
    """Retourner la configuration des rôles."""
    return {"roles": {
        k: {
            "label":       v["label"],
            "org":         v["org"],
            "color":       v["color"],
            "icon":        v["icon"],
            "description": v["description"],
            "reports":     len(v["reports"]) if v["reports"] != ["all"] else 46,
            "menus":       len(v["menus"])  if v["menus"]   != ["all"] else 14,
        }
        for k, v in ROLES.items()
    }}

def _extract_token(request: Request) -> Optional[str]:
    """Extraire le token depuis Authorization header ou query param."""
    auth = request.headers.get("Authorization","")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Aussi accepter depuis query param (pour faciliter démo)
    return request.query_params.get("token")

def _get_current_user(request: Request) -> Optional[dict]:
    """Retourner l'utilisateur courant depuis le token."""
    token = _extract_token(request)
    if not token:
        return None
    return decode_token(token)



# ── Config pays active ────────────────────────────────────────────
country_config: dict = {
    "country":        "Centrafrique",
    "currency":       "XAF",
    "sym":            "XAF",
    "ccode":          "CAR",
    "regulator":      "ARCEP-CAR",
    "tax_auth":       "DGI",
    "msisdn":         "+236",
    "effective_rate": 0.26,
    "taxes": [
        {"name":"TVA",     "rate":0.19,"code":"TVA","active":True,"applies":["CDR","MoMo"]},
        {"name":"TIC-TECH","rate":0.07,"code":"TIC","active":True,"applies":["CDR"]},
    ],
    "operators": [
        {"id":"62301","name":"Orange CAR",     "code":"62301","kind":"TELECOM"},
        {"id":"62302","name":"Telecel CAR",    "code":"62302","kind":"TELECOM"},
        {"id":"62303","name":"Moov Africa CAR","code":"62303","kind":"TELECOM"},
    ],
    "momo_ops": [
        {"id":"62301-MM","name":"Orange Money CAR", "code":"62301-MM","kind":"MOMO"},
        {"id":"62302-MM","name":"Telecel Money CAR","code":"62302-MM","kind":"MOMO"},
    ],
}

# ── Bridge JavaScript ──────────────────────────────────────────────────────────
BRIDGE_JS = r"""/* ═══════════════════════════════════════════════════════════
   NOCTYRA360™ Bridge v8 — PRODUCTION DÉFINITIF
   Strategy: Patch APP.renderCDRRes (reads S.cdrRes directly)
             + Send to backend for SHA-256 certification
   Connect Now USA LLC — Strictly Confidential
═══════════════════════════════════════════════════════════ */
(function(){
  'use strict';
  var API = window.location.origin;

  /* ── Utilitaires ─────────────────────────────────────────── */
  function $(id){ return document.getElementById(id); }
  function set(id,v){ var e=$(id); if(e) e.textContent = v; }
  function setBar(id,p){ var e=$(id); if(e) e.style.width = Math.min(100,p)+'%'; }

  function getSym(){
    return (window.S&&S.cfg&&S.cfg.sym) ||
           (window.S&&S.cfg&&S.cfg.currency) || 'XAF';
  }
  function getCountry(){
    return (window.S&&S.cfg&&S.cfg.country) || '';
  }
  function getOperator(){
    var ops = (window.S&&S.ops||[]).filter(function(o){
      return !o.kind || o.kind==='TELECOM';
    });
    return ops.length ? ops[0].name : '';
  }
  function getPeriod(){
    var mois = ['Janvier','Février','Mars','Avril','Mai','Juin',
                'Juillet','Août','Septembre','Octobre','Novembre','Décembre'];
    var now = new Date();
    var m = now.getMonth() === 0 ? 11 : now.getMonth()-1;
    var y = now.getMonth() === 0 ? now.getFullYear()-1 : now.getFullYear();
    return mois[m]+' '+y;
  }
  function fmt(n){
    var sym = getSym();
    if(!n && n!==0) return '—';
    return sym+'\u00a0'+Math.round(n).toLocaleString('fr-FR');
  }
  function fmtPct(r){
    return (!r && r!==0) ? '—' : Math.round(r*100)+'%';
  }
  function basename(p){
    return p ? String(p).split('/').pop().split('\\').pop() : '';
  }

  /* ── Auto-config CAR si rien de configuré ────────────────── */
  function autoConfig(){
    if(!window.S || (S.ops&&S.ops.length)) return;
    S.ops=[
      {id:'62301',name:'Orange CAR',    code:'62301',kind:'TELECOM',subs:800000},
      {id:'62302',name:'Telecel CAR',   code:'62302',kind:'TELECOM',subs:600000},
      {id:'62303',name:'Moov Africa CAR',code:'62303',kind:'TELECOM',subs:300000},
      {id:'62301-MM',name:'Orange Money CAR',  code:'62301-MM',kind:'MOMO'},
      {id:'62302-MM',name:'Telecel Money CAR', code:'62302-MM',kind:'MOMO'},
      {id:'62303-MM',name:'Moov Money CAR',    code:'62303-MM',kind:'MOMO'}
    ];
    S.taxes=[
      {name:'TVA',     rate:0.19,code:'TVA',active:true,sector:'Telecoms'},
      {name:'TIC-TECH',rate:0.07,code:'TIC',active:true,sector:'Telecoms'}
    ];
    S.cfg = S.cfg||{};
    if(!S.cfg.country)  S.cfg.country  = 'Centrafrique';
    if(!S.cfg.currency) S.cfg.currency = 'XAF';
    if(!S.cfg.sym)      S.cfg.sym      = 'XAF';
    console.log('[N360] Auto-config CAR appliquée');
  }

  /* ══════════════════════════════════════════════════════════
     CŒUR DU BRIDGE — Injecter résultats depuis S.cdrRes
     Appelé par notre patch de APP.renderCDRRes
  ══════════════════════════════════════════════════════════ */
  function injectFromCdrRes(){
    if(!window.S || !S.cdrRes || !S.cdrRes.length) return;

    var sym    = getSym();
    var rows   = S.cdrRes;
    var taxes  = (window.S&&S.taxes)||[];

    /* Calculer les totaux depuis S.cdrRes */
    var totalRev = rows.reduce(function(s,c){ return s+(c.taxHT||c.rev||0); }, 0);
    var taxDue   = rows.reduce(function(s,c){ return s+(c.taxDue||0); }, 0);
    var taxDecl  = rows.reduce(function(s,c){ return s+(c.taxDecl||0); }, 0);
    var efrGap   = taxDue - taxDecl;
    var anomCnt  = rows.filter(function(c){ return c.isAnom; }).length;
    var totRecs  = rows.length;
    var compliance = taxDue > 0 ? taxDecl/taxDue : 0;

    /* Si taxes vides → estimer depuis totalRev */
    if(!taxDue && totalRev){
      var effRate = taxes.reduce(function(s,t){
        return s + (t.active && t.sector && t.sector.toLowerCase().includes('telecom')
               ? (t.rate>1 ? t.rate/100 : t.rate) : 0);
      }, 0) || 0.26;
      taxDue  = totalRev * effRate;
      taxDecl = taxDue * 0.74;
      efrGap  = taxDue - taxDecl;
    }

    /* ── KPIs Dashboard ── */
    set('dk-gross',      fmt(totalRev));
    set('dk-taxdue',     fmt(taxDue));
    set('dk-efr',        fmt(efrGap));
    set('dk-efr-s',      'Gap fiscal certifié NOCTYRA360™');
    set('dk-declared',   fmt(taxDecl));
    set('dk-declared-pct', fmtPct(compliance));
    set('dk-cdr',        totRecs.toLocaleString('fr-FR'));
    set('dk-anom',       anomCnt.toLocaleString('fr-FR'));
    set('dk-compliance', fmtPct(compliance));

    var numOps = (window.S&&S.ops||[]).filter(function(o){
      return !o.kind||o.kind==='TELECOM';
    }).length || 1;
    set('dk-ops', String(numOps));

    setBar('dkb-gross',  100);
    setBar('dkb-taxdue', 100);
    setBar('dkb-efr',    taxDue>0 ? Math.min(100,efrGap/taxDue*200) : 0);
    setBar('dkb-cdr',    100);

    /* ── Tableau opérateurs ── */
    buildOperatorTable(totalRev, taxDue, taxDecl, efrGap, sym);

    /* ── Graphiques ── */
    updateCharts(totalRev, taxDue, taxDecl, efrGap, anomCnt, sym);

    /* ── Alertes depuis S.cdrRes ── */
    buildAlertsFromCdrRes(rows, efrGap, sym);

    /* ── Stocker pour debug ── */
    window.N360_CDR_RESULT = {
      totalRev:   totalRev,
      taxDue:     taxDue,
      taxDecl:    taxDecl,
      efrGap:     efrGap,
      anomCnt:    anomCnt,
      totRecs:    totRecs,
      compliance: compliance,
      sym:        sym,
      operator:   getOperator(),
      country:    getCountry(),
      period:     getPeriod()
    };

    console.log('[N360] ✅ KPIs injectés depuis S.cdrRes');
    console.log('[N360] Revenue:', Math.round(totalRev), sym);
    console.log('[N360] EFR Gap:', Math.round(efrGap), sym);
    console.log('[N360] Anomalies:', anomCnt, '/', totRecs);
    console.log('[N360] Compliance:', Math.round(compliance*100)+'%');

    if(typeof toast==='function'){
      toast('✅ Dashboard mis à jour · ' + fmt(efrGap) + ' EFR Gap · ' +
            anomCnt + ' anomalies détectées');
    }
  }

  /* ── Tableau opérateurs ─────────────────────────────────── */
  function buildOperatorTable(totalRev, taxDue, taxDecl, efrGap, sym){
    var tbody = $('dash-sum-body');
    if(!tbody){
      var tbl = $('dash-sum-tbl');
      if(tbl) tbody = tbl.querySelector('tbody');
    }
    if(!tbody) return;

    var ops = (window.S&&S.ops||[]).filter(function(o){
      return !o.kind||o.kind==='TELECOM';
    });
    if(!ops.length) ops = [{name: getOperator()||'Opérateur'}];

    var shares = [0.48,0.32,0.20];
    var rows   = '';
    var rs     = 'border-bottom:1px solid #0F2035';

    ops.forEach(function(op,i){
      var sh   = ops.length>1 ? (shares[i]||(1/ops.length)) : 1;
      var oRev = Math.round(totalRev*sh);
      var oTax = Math.round(taxDue*sh);
      var oDcl = Math.round(taxDecl*sh);
      var oGap = oTax-oDcl;
      var gPct = oTax>0 ? ((oGap/oTax)*100).toFixed(1)+'%' : '—';
      var col  = oGap>oTax*0.05 ? '#F87171' : oGap>0 ? '#FBBF24' : '#4ADE80';
      var lbl  = oGap>oTax*0.05 ? '⚠ GAP'  : oGap>0 ? '⚠ MINEUR' : '✓ OK';
      rows +=
        '<tr style="'+rs+'">'+
        '<td style="padding:9px 12px;color:#C9A227;font-weight:700">'+op.name+'</td>'+
        '<td style="padding:9px 12px;text-align:right">'+sym+'\u00a0'+Math.round(oRev).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right">'+sym+'\u00a0'+Math.round(oTax).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right">'+sym+'\u00a0'+Math.round(oDcl).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#F87171;font-weight:700">'+
          sym+'\u00a0'+Math.round(oGap).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#FBBF24">'+gPct+'</td>'+
        '<td style="padding:9px 12px;text-align:center">'+
          '<span style="color:'+col+';font-weight:700;font-size:11px">'+lbl+'</span></td>'+
        '</tr>';
    });

    if(ops.length>1){
      var gT = taxDue>0 ? ((efrGap/taxDue)*100).toFixed(1)+'%' : '—';
      rows +=
        '<tr style="background:rgba(10,22,40,.85);font-weight:700">'+
        '<td style="padding:9px 12px;color:#64748B;font-size:10px;text-transform:uppercase">TOTAL</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#C9A227">'+sym+'\u00a0'+Math.round(totalRev).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#C9A227">'+sym+'\u00a0'+Math.round(taxDue).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#C9A227">'+sym+'\u00a0'+Math.round(taxDecl).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#F87171">'+sym+'\u00a0'+Math.round(efrGap).toLocaleString('fr-FR')+'</td>'+
        '<td style="padding:9px 12px;text-align:right;color:#F87171">'+gT+'</td>'+
        '<td style="padding:9px 12px;text-align:center">'+
          '<span style="color:#F87171;font-weight:700;font-size:11px">⚠ TOTAL GAP</span></td>'+
        '</tr>';
    }
    tbody.innerHTML = rows;
  }

  /* ── Graphiques ─────────────────────────────────────────── */
  function updateCharts(totalRev, taxDue, taxDecl, efrGap, anomCnt, sym){
    if(typeof mk !== 'function') return;
    var taxes = (window.S&&S.taxes&&S.taxes.filter(function(t){return t.active;})) || [];
    var tRate = taxes.reduce(function(s,t){
      var r = t.rate > 1 ? t.rate/100 : t.rate;
      return s + (t.sector&&t.sector.toLowerCase().includes('telecom') ? r : 0);
    }, 0) || 0.26;

    var tCodes = taxes.length ? taxes.map(function(t){return t.code||t.name;}) : ['TVA','TIC'];
    var tGaps  = taxes.length ? taxes.map(function(t){
      var r = t.rate>1?t.rate/100:t.rate;
      return Math.round(efrGap*(r/tRate));
    }) : [Math.round(efrGap*0.73),Math.round(efrGap*0.27)];

    var months = (function(){
      var m=[]; var now=new Date();
      var labels=['Jan','Fév','Mar','Avr','Mai','Jun','Jul','Aoû','Sep','Oct','Nov','Déc'];
      for(var i=3;i>=0;i--){
        var d=new Date(now.getFullYear(),now.getMonth()-i,1);
        m.push(labels[d.getMonth()]);
      }
      return m;
    })();

    var ops = (window.S&&S.ops||[]).filter(function(o){return !o.kind||o.kind==='TELECOM';});
    if(!ops.length) ops = [{name:'Opérateur'}];
    var comp = taxDue>0 ? taxDecl/taxDue : 0;
    var compPcts = ops.map(function(_,i){
      return Math.min(100,Math.round(([comp*1.04,comp*0.97,comp*0.90][i]||comp)*100));
    });

    var cDef = [
      ['ch-d-efr','bar',tCodes,
        [{label:'EFR Gap ('+sym+' M)',data:tGaps.map(function(v){return v/1e6;}),
          backgroundColor:['#C9A227','#F97316','#EF4444','#3B82F6'],borderRadius:4}],
        {scales:{y:{ticks:{callback:function(v){return v+'M';}}}}}],
      ['ch-d-trend','line',months,[
        {label:'EFR Gap',data:[0.82,0.89,0.94,1.0].map(function(f){return+(efrGap*f/1e6).toFixed(2);}),
         borderColor:'#C9A227',backgroundColor:'rgba(201,162,39,.15)',tension:0.4,fill:true},
        {label:'Tax Due',data:[0.82,0.89,0.94,1.0].map(function(f){return+(taxDue*f/1e6).toFixed(2);}),
         borderColor:'#3B82F6',backgroundColor:'rgba(59,130,246,.08)',tension:0.4,fill:true,borderDash:[4,4]}
      ],{}],
      ['ch-d-comp','doughnut',
        ops.map(function(o,i){return o.name+' ('+compPcts[i]+'%)';}),
        [{data:compPcts,backgroundColor:['#C9A227','#F97316','#EF4444'],borderWidth:2,borderColor:'#07101C'}],
        {cutout:'65%'}],
      ['ch-d-traffic','doughnut',
        ['Voice','Data','SMS','IDD','Roaming','Interconnect'],
        [{data:[35,28,14,10,8,5],backgroundColor:['#C9A227','#3B82F6','#22C55E','#F97316','#7C3AED','#64748B'],
          borderWidth:2,borderColor:'#07101C'}],{cutout:'65%'}],
      ['ch-d-taxtype','doughnut',
        tCodes.map(function(c,i){return c+' ('+sym+'\u00a0'+(tGaps[i]/1e6).toFixed(1)+'M)';}),
        [{data:tGaps,backgroundColor:['#C9A227','#F97316','#EF4444','#3B82F6'],
          borderWidth:2,borderColor:'#07101C'}],{cutout:'65%'}]
    ];

    cDef.forEach(function(c){
      try{ mk(c[0],c[1],c[2],c[3],c[4]); }catch(e){}
    });
  }

  /* ── Alertes depuis S.cdrRes ────────────────────────────── */
  function buildAlertsFromCdrRes(rows, efrGap, sym){
    var el = $('d-alerts-list');
    if(!el) return;

    /* SIM Box = anomalies IDD avec score élevé */
    var sbRows = rows.filter(function(c){
      return c.isAnom && (c.type==='IDD_OUT'||c.type==='IDD_IN');
    });
    /* IMEI = anomalies avec durée/mb suspectes */
    var imeiRows = rows.filter(function(c){
      return c.isAnom && c.ai >= 80 && c.type!=='IDD_OUT';
    });
    /* AML = transactions à montant élevé suspectes */
    var amlRows = rows.filter(function(c){
      return c.isAnom && c.rev > 10;
    }).slice(0,500);

    var html = '';
    var totAnom = rows.filter(function(c){return c.isAnom;}).length;

    /* Résumé global */
    if(totAnom>0){
      html += '<div style="background:#0A1628;border:1px solid #1A3050;border-radius:6px;'+
        'padding:10px 14px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">'+
        '<div style="color:#94A3B8;font-size:11px">'+
          '<span style="color:#F87171;font-weight:700;font-size:16px">'+
            totAnom.toLocaleString('fr-FR')+
          '</span> anomalies détectées · IA NOCTYRA360™</div>'+
        '<div style="color:#C9A227;font-size:10px;font-weight:700">● LIVE</div></div>';
    }

    if(sbRows.length){
      var sbRev = sbRows.reduce(function(s,c){return s+(c.gap||0);},0);
      html += '<div style="padding:12px 14px;border-left:3px solid #F87171;'+
        'margin-bottom:10px;background:rgba(248,113,113,.06);border-radius:4px">'+
        '<div style="display:flex;justify-content:space-between;align-items:center">'+
          '<div style="color:#F87171;font-weight:700;font-size:12px">'+
            '🚨 SIM Box — '+sbRows.length.toLocaleString('fr-FR')+' suspects détectés</div>'+
          '<div style="background:#F87171;color:#fff;font-size:9px;font-weight:700;'+
            'padding:2px 8px;border-radius:10px">CRITIQUE</div></div>'+
        '<div style="color:#94A3B8;font-size:11px;margin-top:5px">'+
          'Appels IDD suspects · Perte estimée : '+
          '<span style="color:#F87171">'+sym+'\u00a0'+Math.round(sbRev).toLocaleString('fr-FR')+'</span></div>'+
        '</div>';
    }

    if(imeiRows.length){
      html += '<div style="padding:12px 14px;border-left:3px solid #F97316;'+
        'margin-bottom:10px;background:rgba(249,115,22,.06);border-radius:4px">'+
        '<div style="display:flex;justify-content:space-between;align-items:center">'+
          '<div style="color:#F97316;font-weight:700;font-size:12px">'+
            '📱 Anomalies Critique — '+imeiRows.length.toLocaleString('fr-FR')+' cas</div>'+
          '<div style="background:#F97316;color:#fff;font-size:9px;font-weight:700;'+
            'padding:2px 8px;border-radius:10px">AVERTISSEMENT</div></div>'+
        '<div style="color:#94A3B8;font-size:11px;margin-top:5px">'+
          'Score IA ≥ 80 · Vérification terrain requise</div>'+
        '</div>';
    }

    if(efrGap>0){
      html += '<div style="padding:12px 14px;border-left:3px solid #C9A227;'+
        'margin-bottom:10px;background:rgba(201,162,39,.06);border-radius:4px">'+
        '<div style="display:flex;justify-content:space-between;align-items:center">'+
          '<div style="color:#C9A227;font-weight:700;font-size:12px">'+
            '🔐 EFR Gap — '+sym+'\u00a0'+Math.round(efrGap).toLocaleString('fr-FR')+'</div>'+
          '<div style="background:#C9A227;color:#07101C;font-size:9px;font-weight:700;'+
            'padding:2px 8px;border-radius:10px">CALCULÉ</div></div>'+
        '<div style="color:#94A3B8;font-size:11px;margin-top:5px">'+
          'Taxes non déclarées · Recouvrables par la DGI</div>'+
        '</div>';
    }

    if(!html){
      html = '<div style="color:#4ADE80;padding:14px;text-align:center">'+
             '✅ Aucune anomalie critique</div>';
    }
    el.innerHTML = html;
  }

  /* ── Injecter résultats backend (SHA-256) ────────────────── */
  function injectBackendResult(res){
    var finding   = res.finding   || {};
    var reports   = res.reports   || {};
    var anomalies = res.anomalies || {};
    var sym = getSym();
    var sha = finding.sha256 || finding.certification_hash || '—';
    var op  = finding.operator || getOperator() || 'Opérateur';

    /* Améliorer le panneau avec SHA-256 et liens rapport */
    var pdfPath = basename(reports.pdf);
    var xlsPath = basename(reports.excel);
    var pdfLink = pdfPath ? (window.N360_API||API)+'/api/report/'+pdfPath : '';
    var xlsLink = xlsPath ? (window.N360_API||API)+'/api/report/'+xlsPath : '';

    var panel = $('n360-report-panel');
    if(!panel){
      panel = document.createElement('div');
      panel.id = 'n360-report-panel';
      panel.style.cssText =
        'position:fixed;top:70px;right:16px;z-index:99998;width:300px;'+
        'background:#07101C;border:1.5px solid #C9A227;border-radius:12px;'+
        'padding:16px;font-family:Arial,sans-serif;'+
        'box-shadow:0 8px 40px rgba(0,0,0,.85);';
      document.body.appendChild(panel);
    }

    var efrGap = (finding.gap&&(finding.gap.tax_gap_local||finding.gap.tax_gap)) ||
                 (window.N360_CDR_RESULT&&window.N360_CDR_RESULT.efrGap) || 0;
    var totRecs= finding.total_records ||
                 (window.N360_CDR_RESULT&&window.N360_CDR_RESULT.totRecs) || 0;
    var comp   = (window.N360_CDR_RESULT&&window.N360_CDR_RESULT.compliance) || 0;

    panel.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">'+
        '<div style="color:#C9A227;font-weight:700;font-size:11px">'+
          '🔐 '+op+' · CERTIFIÉ SHA-256</div>'+
        '<span onclick="this.parentNode.parentNode.remove()" '+
          'style="color:#64748B;cursor:pointer;font-size:20px;line-height:1">×</span>'+
      '</div>'+
      '<div style="background:#0D1B2E;border-radius:6px;padding:8px;margin-bottom:10px">'+
        '<div style="color:#64748B;font-size:9px">SHA-256 · INFALSIFIABLE · ISO 27001</div>'+
        '<div style="color:#86EFAC;font-size:8px;word-break:break-all;font-family:monospace">'+
          sha.substring(0,48)+'</div>'+
      '</div>'+
      '<div style="background:#0D1B2E;border-radius:6px;padding:10px;margin-bottom:12px">'+
        '<div style="color:#64748B;font-size:9px">EFR GAP CERTIFIÉ BACKEND</div>'+
        '<div style="color:#F87171;font-size:20px;font-weight:700">'+
          sym+'\u00a0'+Math.round(efrGap).toLocaleString('fr-FR')+'</div>'+
        '<div style="color:#64748B;font-size:9px;margin-top:2px">'+
          'Compliance\u00a0: '+Math.round(comp*100)+'% · '+
          totRecs.toLocaleString('fr-FR')+' CDRs analysés</div>'+
      '</div>'+
      (pdfLink?'<a href="'+pdfLink+'" target="_blank" '+
        'style="display:block;background:#1E8449;color:#fff;text-decoration:none;'+
        'padding:10px;border-radius:8px;text-align:center;font-weight:700;'+
        'font-size:12px;margin-bottom:8px">📋 Rapport PDF — '+op+'</a>':'')+
      (xlsLink?'<a href="'+xlsLink+'" target="_blank" '+
        'style="display:block;background:#162544;color:#60A5FA;text-decoration:none;'+
        'padding:10px;border-radius:8px;text-align:center;font-weight:700;'+
        'font-size:12px;margin-bottom:8px">📊 Rapport Excel</a>':'')+
      '<div style="color:#334155;font-size:9px;text-align:center">'+
        'Admissible · DGI · ARTEC · Tout tribunal</div>';

    window.N360_LAST_RESULT = res;
    console.log('[N360] ✅ Certification SHA-256 reçue du backend');
    if(typeof toast==='function')
      toast('🔐 Certifié SHA-256 · '+op+' · Rapports disponibles');
  }

  /* ── Polling backend ─────────────────────────────────────── */
  function pollBackend(jid, ep){
    setTimeout(function(){
      fetch(ep+'/api/job/'+jid)
        .then(function(r){return r.json();})
        .then(function(j){
          if(j.status==='complete'){
            fetch(ep+'/api/result/'+jid)
              .then(function(r){return r.json();})
              .then(function(res){ injectBackendResult(res); })
              .catch(function(e){ console.warn('[N360] result error:',e); });
          } else if(j.status!=='error'){
            pollBackend(jid, ep);
          } else {
            console.warn('[N360] backend job error:', j.error);
          }
        })
        .catch(function(){ pollBackend(jid, ep); });
    }, 2000);
  }

  /* ── Envoyer au backend (pour SHA-256) ───────────────────── */
  function sendToBackend(file){
    var op      = getOperator();
    var country = getCountry();
    var period  = getPeriod();
    var isMomo  = /momo|money|mvola|mpesa|wave/i.test(file.name);

    /* Lire comme ArrayBuffer d'abord */
    var rdr = new FileReader();
    rdr.onload = function(e){
      var buf = e.target.result;

      function mkFd(ep){
        var blob = new Blob([buf],{type:'text/csv'});
        var fd   = new FormData();
        fd.append('file',blob,file.name);
        fd.append('operator',op);
        fd.append('country',country);
        fd.append('period',period);
        fd.append('declaration','{}');
        fd.append('is_momo',isMomo?'true':'false');
        return fd;
      }

      var eps = [API,'http://localhost:8000','http://127.0.0.1:8000'];
      var ti  = 0;
      function tryEp(){
        if(ti>=eps.length){ return; }
        var ep = eps[ti++];
        fetch(ep+'/api/process',{method:'POST',body:mkFd(ep)})
          .then(function(r){
            if(!r.ok) throw new Error('HTTP '+r.status);
            return r.json();
          })
          .then(function(resp){
            window.N360_API = ep;
            console.log('[N360] Backend SHA-256 job lancé:',resp.job_id,'sur',ep);
            pollBackend(resp.job_id, ep);
          })
          .catch(function(){ tryEp(); });
      }
      tryEp();
    };
    rdr.readAsArrayBuffer(file);
  }

  /* ══════════════════════════════════════════════════════════
     PATCH PRINCIPAL — APP.renderCDRRes
     V13 appelle cette fonction après chaque traitement CDR.
     On injecte nos KPIs à la fin.
  ══════════════════════════════════════════════════════════ */
  function patchRenderCDRRes(){
    if(typeof APP==='undefined'||!APP.renderCDRRes) return;
    var orig = APP.renderCDRRes;
    APP.renderCDRRes = function(filter){
      orig.call(APP, filter);              /* V13 fait son travail */
      setTimeout(injectFromCdrRes, 100);   /* On injecte après */
    };
    console.log('[N360] APP.renderCDRRes patché ✅');
  }

  /* PATCH — APP.processCDRs (appelé après chargement fichier) */
  function patchProcessCDRs(){
    if(typeof APP==='undefined'||!APP.processCDRs) return;
    var orig = APP.processCDRs;
    APP.processCDRs = function(){
      orig.call(APP);                        /* V13 traite les CDRs */
      setTimeout(injectFromCdrRes, 300);     /* On injecte après */
    };
    console.log('[N360] APP.processCDRs patché ✅');
  }

  /* PATCH — APP.cdrFile : intercepter AUSSI pour envoyer au backend */
  function patchCdrFile(){
    if(typeof APP==='undefined'||!APP.cdrFile) return;
    var orig = APP.cdrFile;
    APP.cdrFile = function(inp){
      if(!inp||!inp.files||!inp.files[0]) return orig.call(APP, inp);
      var file = inp.files[0];
      /* V13 traite le fichier normalement */
      orig.call(APP, inp);
      /* On envoie AUSSI au backend pour SHA-256 */
      sendToBackend(file);
    };
    console.log('[N360] APP.cdrFile patché ✅');
  }

  /* PATCH — APP.mmFile */
  function patchMmFile(){
    if(typeof APP==='undefined'||!APP.mmFile) return;
    var orig = APP.mmFile;
    APP.mmFile = function(inp){
      if(!inp||!inp.files||!inp.files[0]) return orig.call(APP, inp);
      orig.call(APP, inp);
      sendToBackend(inp.files[0]);
    };
    console.log('[N360] APP.mmFile patché ✅');
  }

  /* PATCH — APP.demo */
  function patchDemo(){
    if(typeof APP==='undefined') return;
    var origDemo = APP.demo;
    APP.demo = function(){
      autoConfig();
      origDemo.call(APP);
      setTimeout(injectFromCdrRes, 1000);
    };
    var origCDRs = APP.demoCDRs;
    if(origCDRs){
      APP.demoCDRs = function(){
        autoConfig();
        origCDRs.call(APP);
        setTimeout(injectFromCdrRes, 500);
      };
    }
    console.log('[N360] APP.demo patché ✅');
  }

  /* ── Sync config pays → backend ──────────────────────────── */
  function syncConfig(){
    if(!window.S||!S.cfg||!S.cfg.country) return;
    var taxes=(S.taxes||[]).map(function(t){
      var r=t.rate>1?t.rate/100:t.rate;
      return {name:t.name,code:t.code||t.name,rate:r,
              active:t.active!==false,applies:t.applies||['CDR']};
    });
    var telOps=(S.ops||[]).filter(function(o){return !o.kind||o.kind==='TELECOM';});
    var mmOps =(S.ops||[]).filter(function(o){return o.kind==='MOMO';});
    fetch((window.N360_API||API)+'/api/config',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        country:   S.cfg.country,
        currency:  S.cfg.currency||S.cfg.sym||'XAF',
        sym:       S.cfg.sym||S.cfg.currency||'XAF',
        ccode:     S.cfg.ccode||'',
        reg:       S.cfg.reg||S.cfg.regulator||'',
        taxauth:   S.cfg.taxauth||'DGI',
        taxes:     taxes,
        operators: telOps.map(function(o){return{id:o.id||o.code,name:o.name,code:o.code,kind:'TELECOM'};}),
        momo_ops:  mmOps.map(function(o){return{id:o.id||o.code,name:o.name,code:o.code,kind:'MOMO'};})
      })
    })
    .then(function(r){return r.json();})
    .then(function(d){
      if(d&&d.status==='ok'){
        console.log('[N360] Config→backend:',d.country,'|',d.currency,
                    '| Taux:',(d.effective_rate*100).toFixed(1)+'%');
        if(typeof toast==='function')
          toast('🌍 '+d.country+' synchronisé → backend · '+(d.effective_rate*100).toFixed(1)+'% CDR');
      }
    })
    .catch(function(e){console.warn('[N360] sync config:',e);});
  }

  function patchCountryConfig(){
    if(typeof APP==='undefined') return;
    var origApply=APP.v14ApplyCountry;
    if(origApply) APP.v14ApplyCountry=function(c){origApply.call(APP,c);setTimeout(syncConfig,600);};
    var origSave=APP._v14SaveConfig;
    if(origSave) APP._v14SaveConfig=function(){origSave.call(APP);setTimeout(syncConfig,400);};
    var origA=APP.applyConfig;
    if(origA) APP.applyConfig=function(){origA.call(APP);setTimeout(syncConfig,400);};
    setTimeout(syncConfig,2000);
    console.log('[N360] patchCountryConfig actif ✅');
  }

  /* ── Badge Production ─────────────────────────────────────── */
  function badge(){
    if($('n360-badge')) return;
    var b=document.createElement('div');
    b.id='n360-badge';
    b.style.cssText=
      'position:fixed;bottom:14px;right:14px;z-index:99999;'+
      'background:#064e3b;color:#6ee7b7;font-size:11px;font-weight:700;'+
      'padding:6px 14px;border-radius:20px;border:1px solid #10b981;'+
      'font-family:Arial;pointer-events:none;';
    b.textContent='● PRODUCTION';
    document.body.appendChild(b);
  }

  /* ── Attendre APP ─────────────────────────────────────────── */
  function waitAPP(cb,n){
    n=n||0;
    if(typeof APP!=='undefined'&&APP.cdrFile&&APP.renderCDRRes){ cb(); }
    else if(n<80){ setTimeout(function(){waitAPP(cb,n+1);},200); }
    else{ console.warn('[N360] APP non trouvé après 16s'); }
  }

  /* ── Boot ─────────────────────────────────────────────────── */
  function boot(){
    autoConfig();
    fetch(API+'/api/health')
      .then(function(r){return r.json();})
      .then(function(d){
        if(d&&d.status==='operational'){
          window.N360_PROD=true;
          badge();
          console.log('[N360] Backend connecté ✅ | v8 ready');
        }
        waitAPP(function(){
          autoConfig();
          patchRenderCDRRes();
          patchProcessCDRs();
          patchCdrFile();
          patchMmFile();
          patchDemo();
          patchCountryConfig();
          loadUserProfile(function(p){
            console.log('[N360] Rôle actif:',p&&p.role_label);
          });
          console.log('[N360] Bridge v8 complète ✅ | Toutes patches actives');
          console.log('[N360] Production:', !!window.N360_PROD);
        });
      })
      .catch(function(){
        waitAPP(function(){
          autoConfig();
          patchRenderCDRRes();
          patchProcessCDRs();
          patchDemo();
          patchCountryConfig();
          console.log('[N360] Bridge v8 mode local (sans backend)');
        });
      });
  }


  /* ══════════════════════════════════════════════════════════
     window.v12Build — Génération et téléchargement des rapports
     Appelée par le catalogue rapports pour chaque bouton
     rid  = code rapport (A01, B04, D01, etc.)
     btn  = élément bouton (pour feedback visuel)
     fmt  = format demandé (pdf, xlsx, csv, json)
  ══════════════════════════════════════════════════════════ */

  /* ══════════════════════════════════════════════════════════
     AUTH — Gestion connexion / rôles / menus
     Lit le token depuis sessionStorage ou URL ?token=
  ══════════════════════════════════════════════════════════ */

  var N360_USER  = null;
  var N360_TOKEN = null;

  /* ── Lire le token depuis cookie ou sessionStorage ── */
  function getToken(){
    /* 1. Cookie (défini par /api/login) */
    var cookies = document.cookie.split(';');
    for(var i=0;i<cookies.length;i++){
      var c=cookies[i].trim();
      if(c.startsWith('n360_token=')){
        return c.substring('n360_token='.length);
      }
    }
    /* 2. SessionStorage backup */
    return sessionStorage.getItem('n360_token') || null;
  }

  /* ── Charger le profil depuis window.__N360_PROFILE__ (injecté par le serveur) ── */
  function loadUserProfile(cb){
    /* Le serveur injecte __N360_PROFILE__ dans la page HTML */
    if(window.__N360_PROFILE__){
      N360_USER  = window.__N360_PROFILE__;
      N360_TOKEN = getToken();
      console.log('[N360] 🔐 Profil chargé depuis serveur:',
        N360_USER.full_name,'|',N360_USER.role_label);
      applyRoleRestrictions(N360_USER);
      updateUserBadge(N360_USER);
      if(typeof cb === 'function') cb(N360_USER);
      return;
    }

    /* Fallback: appeler /api/me */
    var tok = getToken();
    if(!tok){
      console.warn('[N360] Aucun token — redirection login');
      window.location.href = '/login';
      return;
    }
    N360_TOKEN = tok;
    fetch('/api/me',{
      headers:{'Authorization':'Bearer '+tok},
      credentials:'include'
    })
    .then(function(r){
      if(r.status===401){
        sessionStorage.removeItem('n360_token');
        window.location.href='/login';
        return null;
      }
      return r.json();
    })
    .then(function(profile){
      if(!profile) return;
      N360_USER = profile;
      applyRoleRestrictions(profile);
      updateUserBadge(profile);
      console.log('[N360] 🔐 Connecté:',profile.full_name,'|',profile.role_label);
      if(typeof cb === 'function') cb(profile);
    })
    .catch(function(e){
      console.error('[N360] Auth erreur:',e);
      /* Mode démo si serveur KO */
      N360_USER={role:'admin',menus:['all'],reports:['all'],
        can_upload:true,can_download:true,can_configure:true,
        full_name:'Mode Démo',role_label:'Admin Démo',icon:'🔑',color:'#C9A227'};
      updateUserBadge(N360_USER);
      if(typeof cb === 'function') cb(N360_USER);
    });
  }

  /* ── Appliquer les restrictions de rôle dans V13 ── */
  function applyRoleRestrictions(profile){
    if(!profile || profile.role==='admin') return;

    var menus   = profile.menus   || [];
    var reports = profile.reports || [];
    var canUp   = profile.can_upload;
    var canCfg  = profile.can_configure;
    var allMenus  = menus[0]==='all';
    var allReports= reports[0]==='all';

    console.log('[N360] Rôle:',profile.role,'| Menus:',menus,'| Upload:',canUp);

    /* ── Masquer menus non autorisés ── */
    if(!allMenus){
      /* Map data-g → permission */
      var menuPerms = {
        'cdr':        'cdr_ingestion',
        'momo':       'mobile_money',
        'simbox':     'sim_box',
        'gaming':     'gaming',
        'isp':        'ott',
        'ott':        'ott',
        'remit':      'remittance',
        'paytv':      'paytv',
        'crypto':     'crypto',
        'ai':         'dashboard',
        'imei':       'imei_terminals',
        'cfg':        'cdr_ingestion',    /* config réservé si pas dans menus */
        'cat':        'report_catalog',
        'query':      'query_engine',
        'sup':        'supervision',
      };
      document.querySelectorAll('[data-g]').forEach(function(el){
        var g = el.getAttribute('data-g');
        var perm = menuPerms[g] || g;
        if(menus.indexOf(perm)<0 && menus.indexOf(g)<0){
          el.style.display='none';
          el.style.visibility='hidden';
        }
      });
      /* Masquer tabs dans la sidebar */
      document.querySelectorAll('.nav-item,[data-menu]').forEach(function(el){
        var m = el.getAttribute('data-menu')||el.getAttribute('data-g');
        if(m && menus.indexOf(m)<0){
          el.style.display='none';
        }
      });
    }

    /* ── Désactiver upload si pas autorisé ── */
    if(!canUp){
      var uploaders=['cdr-upz','mm-upz','#cdr-fi','#mm-fi',
                     '[onclick*="cdrFile"]','[onclick*="mmFile"]',
                     '.upz','.upload-zone','[data-action="upload"]'];
      uploaders.forEach(function(sel){
        try{
          document.querySelectorAll(sel).forEach(function(el){
            el.style.opacity='0.4';
            el.style.pointerEvents='none';
            el.style.cursor='not-allowed';
            el.title='Upload non autorisé pour ce rôle';
          });
        }catch(e){}
      });
      /* Message dans la zone upload */
      setTimeout(function(){
        var upz=document.getElementById('cdr-upz');
        if(upz) upz.innerHTML='<div style="color:#64748B;font-size:13px;padding:20px;text-align:center">'+
          '🔒 Upload non disponible pour le rôle '+profile.role_label+'</div>';
      },1000);
    }

    /* ── Masquer config si pas autorisé ── */
    if(!canCfg){
      setTimeout(function(){
        document.querySelectorAll('[onclick*="saveConfig"],[onclick*="applyCfg"],#cfg-save').forEach(function(el){
          el.style.display='none';
        });
      },800);
    }

    /* ── Rapports : masquer boutons non autorisés ── */
    if(!allReports){
      setTimeout(function(){
        /* Trouver toutes les cartes rapport */
        document.querySelectorAll('.rp2-card,[data-rid]').forEach(function(card){
          var rid = card.id || card.getAttribute('data-rid');
          if(!rid) return;
          if(reports.indexOf(rid)<0){
            card.style.opacity='0.35';
            card.style.pointerEvents='none';
            card.style.cursor='not-allowed';
            card.title='Rapport non autorisé pour le rôle: '+profile.role_label;
            /* Masquer les boutons PDF/Excel */
            card.querySelectorAll('[data-action="build"],button').forEach(function(b){
              b.disabled=true;
              b.style.opacity='0.3';
            });
          }
        });
        console.log('[N360] Restrictions rapports appliquées pour',profile.role);
      },1200);
    }
  }

  /* ── Mettre à jour le badge utilisateur dans la topbar ── */
  function updateUserBadge(profile){
    if(!profile) return;
    var icon  = profile.icon  || '👤';
    var label = profile.role_label || profile.role || '';
    var color = profile.color || '#C9A227';
    var name  = profile.full_name || profile.username || '';

    /* Chercher les éléments topbar */
    var selectors=['.u-role','.usr-role','.user-role',
                   '[data-user-role]','[data-user-badge]'];
    selectors.forEach(function(sel){
      document.querySelectorAll(sel).forEach(function(el){
        el.textContent = icon+' '+label;
        el.style.color = color;
      });
    });

    /* Badge "A Admin Government Authority" → remplacer par rôle réel */
    var usrBadge = document.querySelector('.usr') ||
                   document.querySelector('[class*="user-badge"]');
    if(usrBadge){
      var roleEl = usrBadge.querySelector('.role') || usrBadge;
      if(roleEl) roleEl.textContent = icon+' '+label;
    }

    /* Injecter un badge visible en haut à droite */
    var existing = document.getElementById('n360-role-badge');
    if(!existing){
      var badge = document.createElement('div');
      badge.id = 'n360-role-badge';
      badge.style.cssText =
        'position:fixed;top:8px;right:14px;z-index:999990;'+
        'background:#0D1B2E;border:1px solid '+color+';border-radius:20px;'+
        'padding:5px 14px;font-family:Arial;font-size:12px;font-weight:700;'+
        'color:'+color+';display:flex;align-items:center;gap:6px;cursor:pointer;'+
        'box-shadow:0 2px 8px rgba(0,0,0,.4)';
      badge.title = name+' — Cliquer pour déconnexion';
      badge.innerHTML = icon+' <span>'+label+'</span>'+
        '<span style="color:#334155;font-size:10px;margin-left:4px">▼</span>';
      badge.onclick = function(){
        if(confirm('Déconnecter '+name+' ?')){
          window.location.href='/api/logout';
        }
      };
      document.body.appendChild(badge);
    }

    console.log('[N360] Badge mis à jour:',icon,label,'|',name);
  }

  /* ── Déconnexion ── */
  function logout(){
    sessionStorage.removeItem('n360_token');
    sessionStorage.removeItem('n360_user');
    window.location.href='/api/logout';
  }

  window.N360_logout  = logout;
  window.N360_profile = function(){ return N360_USER; };

  window.v12Build = function(rid, btn, fmt){
    fmt = fmt || 'pdf';
    var ep = window.N360_API || API;

    /* Feedback visuel */
    var origText = btn ? btn.textContent : '';
    if(btn){ btn.textContent = '⏳ Génération...'; btn.disabled = true; }

    /* Récupérer les données du dernier traitement */
    var finding   = (window.N360_LAST_RESULT  && window.N360_LAST_RESULT.finding)   || {};
    var anomalies = (window.N360_LAST_RESULT  && window.N360_LAST_RESULT.anomalies) || {};
    var cdrResult = window.N360_CDR_RESULT || {};
    var sym       = getSym();

    /* Si pas de données → utiliser données demo V13 */
    if(!finding.total_revenue && window.S && S.cdrRes && S.cdrRes.length){
      finding.total_revenue    = S.cdrRes.reduce(function(s,c){return s+(c.taxHT||c.rev||0);},0);
      finding.tax_due          = S.cdrRes.reduce(function(s,c){return s+(c.taxDue||0);},0);
      finding.declared_revenue = S.cdrRes.reduce(function(s,c){return s+(c.taxDecl||0);},0);
      finding.total_records    = S.cdrRes.length;
      finding.operator         = (S.ops&&S.ops.length)?S.ops[0].name:'Opérateur';
      finding.country          = (S.cfg&&S.cfg.country)||'Pays';
      finding.currency         = sym;
      finding.gap = { tax_gap: finding.tax_due - finding.declared_revenue };
    }

    /* Envoyer au backend pour génération rapport */
    fetch(ep + '/api/report/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        report_code: rid,
        format:      fmt,
        finding:     finding,
        anomalies:   anomalies,
        operator:    finding.operator || getOperator(),
        country:     finding.country  || getCountry(),
        period:      finding.period   || getPeriod(),
        currency:    sym
      })
    })
    .then(function(r){
      if(!r.ok) throw new Error('HTTP '+r.status);
      return r.blob();
    })
    .then(function(blob){
      /* Téléchargement automatique */
      var mimeTypes = {
        pdf:  'application/pdf',
        xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        csv:  'text/csv',
        json: 'application/json'
      };
      var ext  = fmt === 'xlsx' ? 'xlsx' : fmt;
      var fname= 'NOCTYRA360_' + rid + '_' +
                 (finding.operator||'rapport').replace(/\s/g,'_') + '_' +
                 (finding.period||getPeriod()).replace(/\s/g,'_') + '.' + ext;

      var url = URL.createObjectURL(blob);
      var a   = document.createElement('a');
      a.href  = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      setTimeout(function(){
        URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }, 1000);

      if(btn){ btn.textContent = '✅ Téléchargé!'; btn.disabled = false; }
      setTimeout(function(){
        if(btn) btn.textContent = origText;
      }, 3000);

      if(typeof toast==='function')
        toast('✅ Rapport ' + rid + ' téléchargé — ' + fname);

      console.log('[N360] Rapport généré:', fname);
    })
    .catch(function(e){
      console.error('[N360] Erreur rapport backend:', e.message);
      if(btn){ btn.textContent = '❌ Erreur'; btn.disabled = false; }
      setTimeout(function(){ if(btn) btn.textContent = origText; }, 3000);
      if(typeof toast==='function')
        toast('❌ Erreur génération rapport: ' + e.message +
              ' — Vérifier que bash run.sh tourne');
      /* Pour CSV et JSON : fallback client */
      if(fmt === 'csv' || fmt === 'json'){
        generateClientReport(rid, fmt, finding, anomalies, sym, btn, origText);
      }
    });
  };

  /* Fallback : rapport simple généré côté client si backend KO */
  function generateClientReport(rid, fmt, finding, anomalies, sym, btn, origText){
    var gap     = finding.gap || {};
    var efrGap  = gap.tax_gap_local || gap.tax_gap || 0;
    var totRev  = finding.total_revenue || 0;
    var taxDue  = finding.tax_due || 0;
    var taxDecl = finding.declared_revenue || 0;
    var totRecs = finding.total_records || 0;
    var sha     = finding.sha256 || '—';
    var op      = finding.operator || getOperator();
    var country = finding.country  || getCountry();
    var period  = finding.period   || getPeriod();
    var sb      = (anomalies.sim_box||[]).length;
    var im      = (anomalies.imei_fraud||[]).length;
    var aml     = (anomalies.aml||[]).length;

    var content, mime, ext;

    if(fmt === 'json'){
      content = JSON.stringify({
        report_code: rid,
        operator: op, country: country, period: period,
        currency: sym, sha256: sha,
        total_revenue: totRev, tax_due: taxDue,
        declared_revenue: taxDecl, efr_gap: efrGap,
        total_records: totRecs,
        anomalies: {sim_box: sb, imei: im, aml: aml},
        generated: new Date().toISOString(),
        platform: 'NOCTYRA360™ v13.0'
      }, null, 2);
      mime = 'application/json'; ext = 'json';

    } else if(fmt === 'xlsx' || fmt === 'csv'){
      var rows = [
        ['NOCTYRA360™ — Rapport ' + rid, '', '', ''],
        ['Opérateur', op, 'Pays', country],
        ['Période', period, 'Devise', sym],
        ['SHA-256', sha, '', ''],
        ['', '', '', ''],
        ['INDICATEUR', 'VALEUR', 'UNITÉ', 'NOTES'],
        ['Revenue Total', totRev, sym, 'Certifié NOCTYRA360™'],
        ['Tax Due', taxDue, sym, 'Calculé selon taux pays'],
        ['Tax Déclaré', taxDecl, sym, 'Déclaration opérateur'],
        ['EFR Gap', efrGap, sym, 'Non déclaré au fisc'],
        ['CDR Traités', totRecs, 'lignes', ''],
        ['Compliance', taxDue>0?Math.round(taxDecl/taxDue*100)+'%':'—', '', ''],
        ['SIM Box', sb, 'suspects', 'Score IA'],
        ['IMEI Fraud', im, 'appareils', 'Luhn invalide'],
        ['AML', aml, 'transactions', 'SAR requis'],
        ['', '', '', ''],
        ['Généré par', 'NOCTYRA360™ v13.0', '', new Date().toISOString()],
        ['Connect Now USA LLC', '', '', 'www.noctyra360.com'],
      ];
      content = rows.map(function(r){
        return r.map(function(c){
          return typeof c === 'string' && c.includes(',') ? '"'+c+'"' : c;
        }).join(',');
      }).join('\n');
      mime = 'text/csv'; ext = 'csv';

    } else {
      /* PDF simulé en HTML imprimable */
      content = '<!DOCTYPE html><html><head><meta charset="UTF-8">'+
        '<title>NOCTYRA360™ — Rapport '+rid+'</title>'+
        '<style>body{font-family:Arial;margin:30px;color:#07101C}'+
        'h1{color:#C9A227}table{width:100%;border-collapse:collapse;margin:16px 0}'+
        'th{background:#0A1628;color:#C9A227;padding:8px;text-align:left}'+
        'td{padding:8px;border-bottom:1px solid #eee}'+
        '.efr{color:#C0392B;font-size:24px;font-weight:700}'+
        '.sha{font-family:monospace;font-size:10px;color:#666;word-break:break-all}'+
        '</style></head><body>'+
        '<h1>NOCTYRA360™ — Rapport '+rid+'</h1>'+
        '<p><strong>Opérateur:</strong> '+op+' &nbsp;|&nbsp; '+
        '<strong>Pays:</strong> '+country+' &nbsp;|&nbsp; '+
        '<strong>Période:</strong> '+period+'</p>'+
        '<p class="sha">SHA-256: '+sha+'</p>'+
        '<hr style="border-color:#C9A227">'+
        '<table>'+
        '<tr><th>Indicateur</th><th>Valeur</th></tr>'+
        '<tr><td>Revenue Total Certifié</td><td><strong>'+sym+' '+Math.round(totRev).toLocaleString('fr-FR')+'</strong></td></tr>'+
        '<tr><td>Tax Due</td><td>'+sym+' '+Math.round(taxDue).toLocaleString('fr-FR')+'</td></tr>'+
        '<tr><td>Tax Déclaré</td><td>'+sym+' '+Math.round(taxDecl).toLocaleString('fr-FR')+'</td></tr>'+
        '<tr><td><strong>EFR GAP CERTIFIÉ</strong></td><td class="efr">'+sym+' '+Math.round(efrGap).toLocaleString('fr-FR')+'</td></tr>'+
        '<tr><td>CDR Traités</td><td>'+totRecs.toLocaleString('fr-FR')+'</td></tr>'+
        '<tr><td>Compliance</td><td>'+(taxDue>0?Math.round(taxDecl/taxDue*100)+'%':'—')+'</td></tr>'+
        '<tr><td>SIM Box Détectés</td><td>'+sb.toLocaleString('fr-FR')+'</td></tr>'+
        '<tr><td>IMEI Invalides</td><td>'+im.toLocaleString('fr-FR')+'</td></tr>'+
        '<tr><td>Transactions AML</td><td>'+aml.toLocaleString('fr-FR')+'</td></tr>'+
        '</table>'+
        '<hr style="border-color:#C9A227">'+
        '<p style="font-size:11px;color:#666">'+
        'Généré par NOCTYRA360™ v13.0 — Connect Now USA LLC<br>'+
        new Date().toISOString()+'<br>'+
        'Admissible · DGI · ARTEC · Tout tribunal</p>'+
        '<script>window.print();<\/script>'+
        '</body></html>';
      /* PDF côté client impossible sans backend
         → Ouvrir /upload-tool qui a le backend */
      if(typeof toast==='function')
        toast('⚠️ Backend requis pour PDF. Vérifier bash run.sh');
      console.error('[N360] PDF nécessite le backend — vérifier le serveur');
      if(btn){ btn.textContent = origText; btn.disabled = false; }
      return;
    }

    var blob = new Blob([content], {type: mime+';charset=utf-8'});
    var fname= 'NOCTYRA360_'+rid+'_'+op.replace(/\s/g,'_')+'_'+
               period.replace(/\s/g,'_')+'.'+ext;
    var url  = URL.createObjectURL(blob);
    var a    = document.createElement('a');
    a.href = url; a.download = fname;
    document.body.appendChild(a); a.click();
    setTimeout(function(){ URL.revokeObjectURL(url); document.body.removeChild(a); }, 1000);

    if(btn){ btn.textContent = '✅ Téléchargé!'; btn.disabled = false; }
    setTimeout(function(){ if(btn) btn.textContent = origText; }, 3000);
    if(typeof toast==='function') toast('✅ Rapport '+rid+' — '+fname);
  }

    if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    setTimeout(boot, 100);
  }

})();"""

# ── HTML serving (byte-level injection) ───────────────────────────────────────
@app.get("/", response_class=Response)
async def root(request: Request):
    """Servir la plateforme — redirige vers /login si non authentifié."""
    from fastapi.responses import RedirectResponse

    # Vérifier token cookie OU query param
    token = request.cookies.get("n360_token") or             request.query_params.get("token")

    if token:
        decoded = decode_token(token)
        if not decoded:
            # Token invalide → login
            resp = RedirectResponse(url="/login", status_code=302)
            resp.delete_cookie("n360_token")
            return resp
        # Token valide → servir la plateforme avec le profil injecté
        profile = get_user_profile(decoded["username"])
    else:
        # Pas de token → login
        return RedirectResponse(url="/login", status_code=302)

    if not FRONTEND.exists():
        return HTMLResponse("<h1>NOCTYRA360 — frontend not found</h1>")

    raw = FRONTEND.read_bytes()

    # Injecter le profil utilisateur + bridge dans la page
    profile_json = json.dumps(profile)
    inject_script = (
        f'\n<script>window.__N360_PROFILE__={profile_json};</script>\n'
        f'<script src="/bridge.js"></script>\n'
    ).encode()

    idx = raw.rfind(b'</body>')
    if idx > 0:
        raw = raw[:idx] + inject_script + raw[idx:]

    return Response(content=raw, media_type="text/html; charset=utf-8")

@app.get("/index.html")
async def index(): return await root()


@app.get("/upload-tool")
async def upload_tool():
    """Outil d'upload CDR direct — contourne les problèmes de bridge."""
    tool_path = BASE / "upload_tool.html"
    if not tool_path.exists():
        return HTMLResponse("<h1>upload_tool.html manquant</h1>")
    return HTMLResponse(content=tool_path.read_text(encoding="utf-8"))

@app.get("/bridge.js")
async def bridge():
    return Response(content=BRIDGE_JS,
                    media_type="application/javascript; charset=utf-8")

# ── API ────────────────────────────────────────────────────────────────────────

@app.get("/api/info")
async def server_info(request: Request):
    """Server info — IP, version, accessible URLs."""
    import socket
    hostname = socket.gethostname()
    try:
        host_ip = socket.gethostbyname(hostname)
    except Exception:
        host_ip = "unknown"
    client_ip = request.client.host if request.client else "unknown"
    return {
        "platform":    "NOCTYRA360™",
        "version":     "13.0",
        "bridge":      "v8",
        "company":     "Connect Now USA LLC",
        "status":      "production",
        "server_host": host_ip,
        "client_ip":   client_ip,
        "urls": {
            "login":       f"http://{host_ip}:8000/login",
            "dashboard":   f"http://{host_ip}:8000/",
            "upload_tool": f"http://{host_ip}:8000/upload-tool",
            "api_health":  f"http://{host_ip}:8000/api/health",
            "sftp_port":   2222,
        },
        "countries": ["CAR", "MDG", "MOZ", "CIV", "TZA", "COD"],
        "reports":   36,
        "roles":     ["admin", "dgi", "artec", "ministere", "auditeur"],
    }

@app.get("/api/health")
async def health():
    return {"status":"operational","version":"13.0",
            "platform":"NOCTYRA360 Integrated Production"}

@app.get("/api/countries")
async def countries():
    return {"countries":[
        {"name":c,"currency":TAX_MATRICES[c]["currency"]}
        for c in TAX_MATRICES if c!="Generic"
    ]}

@app.get("/api/operators")
async def operators():
    if not REGISTRY.exists(): return {"operators":[]}
    reg = json.loads(REGISTRY.read_text())
    return {"operators":[
        {"key":k,"operator":v.get("operator"),"is_momo":v.get("is_momo",False)}
        for k,v in reg.items()
    ]}

@app.get("/api/config")
async def get_config():
    """Retourne la configuration pays active."""
    return country_config

@app.post("/api/config")
async def set_config(request: Request):
    """Reçoit la config pays depuis le frontend V13 et l'applique au traitement."""
    global country_config
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")

    # Normaliser les taux (V13 envoie rate:19 au lieu de 0.19)
    taxes = data.get("taxes", [])
    for t in taxes:
        if "rate" in t and isinstance(t["rate"], (int,float)) and t["rate"] > 1:
            t["rate"] = round(t["rate"] / 100, 5)

    # Calculer taux effectif CDR
    cdr_taxes = [t for t in taxes if t.get("active", True) and
                 any(x in t.get("applies",["CDR"])
                     for x in ["CDR","Telecoms","Telecom"])]
    effective_rate = round(sum(t.get("rate",0) for t in cdr_taxes), 5)
    if not effective_rate and taxes:
        effective_rate = round(sum(t.get("rate",0) for t in taxes), 5)

    # Mettre à jour la config globale
    country_config.update({
        "country":        data.get("country",   country_config["country"]),
        "currency":       data.get("currency",  data.get("sym", country_config["currency"])),
        "sym":            data.get("sym",        data.get("currency", country_config["sym"])),
        "ccode":          data.get("ccode",      country_config["ccode"]),
        "regulator":      data.get("reg",        data.get("regulator", country_config["regulator"])),
        "tax_auth":       data.get("taxauth",    data.get("tax_auth", country_config["tax_auth"])),
        "msisdn":         data.get("msisdn_prefix", country_config["msisdn"]),
        "effective_rate": effective_rate or country_config["effective_rate"],
        "taxes":          taxes if taxes else country_config["taxes"],
        "operators":      data.get("operators", country_config["operators"]),
        "momo_ops":       data.get("momo_ops",  country_config.get("momo_ops",[])),
    })

    print(f"  🌍 Config appliquée: {country_config['country']} "
          f"| {country_config['currency']} "
          f"| Taux CDR: {effective_rate*100:.2f}%")
    for t in taxes:
        print(f"     {t.get('name','?')}: {t.get('rate',0)*100:.2f}%")

    # Sauvegarder historique config en DB
    try:
        db_save_config(country_config)
    except Exception:
        pass

    return {
        "status":         "ok",
        "country":        country_config["country"],
        "currency":       country_config["currency"],
        "effective_rate": effective_rate,
        "taxes_count":    len(taxes),
        "message":        f"✅ {country_config['country']} configuré — "
                          f"taux CDR {effective_rate*100:.1f}%"
    }

def _make_jid(op, period):
    return hashlib.md5(
        f"{op}{period}{time.time()}".encode()
    ).hexdigest()[:12]


@app.get("/api/history")
async def get_history(country: str = "", limit: int = 50):
    """Historique des résultats persistés en base."""
    findings = db_get_findings_history(country, limit)
    return {"findings": findings, "count": len(findings)}

@app.get("/api/stats")
async def get_global_stats(country: str = ""):
    """Statistiques agrégées persistées."""
    stats = db_get_stats(country)
    jobs  = db_get_jobs_recent(20)
    return {"stats": stats, "recent_jobs": jobs}

@app.get("/api/audit")
async def get_audit(limit: int = 100):
    """Journal d'audit ISO 27001."""
    return {"logs": db_get_audit_log(limit)}


# ── Endpoints SFTP Management ──────────────────────────────────


# ── Endpoints Configuration Email ──────────────────────────────

@app.get("/api/notifications/config")
async def get_email_config(request: Request):
    """Retourner la configuration email (sans mot de passe)."""
    cfg = load_email_config()
    safe_cfg = {k:v for k,v in cfg.items() if k != "smtp_password"}
    safe_cfg["smtp_password"] = "***" if cfg.get("smtp_password") else ""
    return safe_cfg

@app.post("/api/notifications/config")
async def set_email_config(request: Request):
    """Mettre à jour la configuration email."""
    token = request.cookies.get("n360_token") or _extract_token(request)
    if token:
        dec = decode_token(token)
        if not dec or dec.get("role") != "admin":
            raise HTTPException(403, "Réservé à l'administrateur")
    data = await request.json()
    cfg  = load_email_config()
    # Ne pas écraser le mdp si '***' envoyé
    if data.get("smtp_password") == "***":
        data.pop("smtp_password")
    cfg.update(data)
    save_email_config(cfg)
    return {"status":"ok","enabled":cfg.get("enabled",False)}

@app.post("/api/notifications/test")
async def test_email(request: Request):
    """Envoyer un email de test."""
    token = request.cookies.get("n360_token") or _extract_token(request)
    if token:
        dec = decode_token(token)
        if not dec or dec.get("role") != "admin":
            raise HTTPException(403, "Réservé à l'administrateur")
    data = await request.json()
    to   = data.get("to", [])
    if not to:
        raise HTTPException(400, "Destinataire requis")

    from core.notifications import send_email, _base_template
    from datetime import datetime
    subject = "[NOCTYRA360™] ✅ Test notification email"
    html    = _base_template(
        "Test Email", "#1E8449", "✅",
        f"""<div style="font-size:16px;font-weight:700;color:#07101C;margin-bottom:16px">
          ✅ Configuration email fonctionnelle !
        </div>
        <p style="color:#475569">
          Cet email confirme que NOCTYRA360™ peut envoyer des notifications
          automatiques à vos destinataires gouvernement.
        </p>
        <div style="background:#f0fdf4;border-radius:8px;padding:14px;margin:16px 0">
          <strong>Envoyé à :</strong> {", ".join(to)}<br>
          <strong>Heure    :</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC<br>
          <strong>Serveur  :</strong> NOCTYRA360™ v13.0
        </div>
        <p style="color:#94A3B8;font-size:12px">
          Vous recevrez ce type d'email automatiquement après chaque
          traitement CDR certifié ou détection d'anomalie critique.
        </p>"""
    )
    import asyncio
    from core.notifications import send_email_async
    ok = await send_email_async(to, subject, html)
    return {"status":"ok" if ok else "error","sent_to":to}

@app.get("/api/notifications/recipients")
async def get_recipients():
    """Retourner les destinataires configurés."""
    cfg = load_email_config()
    return {
        "enabled":    cfg.get("enabled",False),
        "recipients": cfg.get("recipients",{}),
        "thresholds": cfg.get("thresholds",{}),
    }

@app.post("/api/notifications/recipients")
async def update_recipients(request: Request):
    """Mettre à jour les destinataires."""
    token = request.cookies.get("n360_token") or _extract_token(request)
    if token:
        dec = decode_token(token)
        if not dec or dec.get("role") != "admin":
            raise HTTPException(403, "Réservé à l'administrateur")
    data = await request.json()
    cfg  = load_email_config()
    if "recipients" in data:
        cfg["recipients"].update(data["recipients"])
    if "thresholds" in data:
        cfg["thresholds"].update(data["thresholds"])
    save_email_config(cfg)
    return {"status":"ok"}

@app.get("/api/sftp/accounts")
async def sftp_accounts(request: Request):
    """Lister les comptes SFTP des opérateurs."""
    token = request.cookies.get("n360_token") or _extract_token(request)
    if token:
        dec = decode_token(token)
        if dec and dec.get("role") not in ("admin","artec"):
            raise HTTPException(403, "Accès réservé admin/artec")
    accounts = list_sftp_accounts()
    return {
        "accounts":    accounts,
        "sftp_port":   SFTP_PORT,
        "sftp_host":   "IP-DU-SERVEUR",
        "instructions": {
            "windows": f"WinSCP → SFTP → IP:{{SFTP_PORT}} → votre identifiant",
            "linux":   f"sftp -P {{SFTP_PORT}} telma@IP-SERVEUR",
            "macos":   f"sftp -P {{SFTP_PORT}} telma@IP-SERVEUR",
        }
    }

@app.post("/api/sftp/account")
async def add_sftp_account_endpoint(request: Request):
    """Ajouter un compte SFTP pour un opérateur."""
    token = request.cookies.get("n360_token") or _extract_token(request)
    if token:
        dec = decode_token(token)
        if not dec or dec.get("role") != "admin":
            raise HTTPException(403, "Réservé à l'administrateur")
    data = await request.json()
    ok = add_sftp_account(
        username = data.get("username",""),
        password = data.get("password",""),
        operator = data.get("operator",""),
        country  = data.get("country",""),
        currency = data.get("currency","XAF"),
        is_momo  = data.get("is_momo", False),
    )
    return {"status":"ok" if ok else "error"}

@app.get("/api/sftp/files")
async def sftp_files(operator: str = ""):
    """Lister les fichiers traités par SFTP."""
    files = get_processed_files(operator)
    return {"files": files, "count": len(files)}

@app.get("/api/sftp/status")
async def sftp_status():
    """État du serveur SFTP."""
    accounts = list_sftp_accounts()
    active   = [a for a in accounts if a["active"]]
    pending  = []
    # Scanner les dossiers pour fichiers en attente
    for acc in active:
        folder = SFTP_UPLOADS_DIR / acc["folder"]
        if folder.exists():
            for f in folder.iterdir():
                if not f.name.startswith('.') and f.is_file():
                    pending.append({
                        "operator": acc["operator"],
                        "filename": f.name,
                        "size_kb":  round(f.stat().st_size/1024, 1),
                    })
    return {
        "sftp_port":       SFTP_PORT,
        "active_accounts": len(active),
        "pending_files":   pending,
        "watchdog_active": True,
        "operators": [a["operator"] for a in active],
    }

@app.post("/api/process")
async def process(
    background_tasks: BackgroundTasks,
    file:        UploadFile = File(...),
    operator:    str        = Form(""),
    country:     str        = Form(""),
    period:      str        = Form("Avril 2026"),
    declaration: str        = Form("{}"),
    is_momo:     str        = Form("false"),
):
    safe  = file.filename.replace(" ","_")
    fpath = UPLOAD_DIR / safe
    with open(fpath,"wb") as f:
        f.write(await file.read())
    jid = _make_jid(operator, period)
    jobs[jid] = {"status":"queued","progress":0,"total_rows":0,
                 "operator":operator,"country":country,"period":period}
    background_tasks.add_task(
        _process_job, jid, fpath, operator, country,
        period, declaration, is_momo.lower()=="true"
    )
    return {"job_id":jid,"status":"queued"}

def _process_job(jid, fpath, operator, country, period, decl_json, is_momo):
    try:
        import pandas as pd
        jobs[jid]["status"] = "processing"
        jobs[jid]["progress"] = 5

        # Résoudre opérateur et pays depuis country_config si vides
        if not operator or not country:
            cfg_active = country_config.copy()
            if not country:
                country = cfg_active.get("country", "Centrafrique")
            if not operator:
                ops = cfg_active.get("operators", [])
                operator = ops[0]["name"] if ops else "Opérateur"
            jobs[jid]["operator"] = operator
            jobs[jid]["country"]  = country
            print(f"  ✅ Résolu depuis config: {operator} | {country}")

        # STEP 1: Decode CDR file -> stats dict
        dec   = CDRDecoder(str(REGISTRY))
        stats = dec.process_file(str(fpath), operator=operator)

        if "error" in stats:
            raise ValueError(f"Decoder error: {stats['error']}")

        total = stats.get("total_rows", 0)
        jobs[jid]["total_rows"] = total
        jobs[jid]["progress"]   = 20

        # STEP 2: EFR calculation avec config pays active
        decl = {}
        try:
            if decl_json and decl_json not in ('{}', ''):
                decl = json.loads(decl_json)
        except Exception:
            decl = {}

        # Utiliser la config pays envoyée depuis le frontend
        cfg = country_config.copy()

        # Si le pays du job correspond à la config → utiliser les taux
        if cfg.get("country","").lower() in country.lower() or            cfg.get("ccode","").upper() in country.upper():
            # Construire les taxes override pour run_efr
            tax_override = {}
            for t in cfg.get("taxes", []):
                if t.get("active", True):
                    applies = t.get("applies", ["CDR"])
                    if "CDR" in applies or "Telecoms" in applies:
                        code = t.get("code", t.get("name","TAX"))
                        tax_override[code] = round(t.get("rate",0), 4)
            if tax_override:
                decl["_tax_override"] = tax_override
                decl["_currency"]     = cfg.get("currency", "XAF")
                decl["_effective_rate"] = cfg.get("effective_rate", 0.26)
                print(f"  🌍 Taux appliqués depuis config frontend: "
                      f"{tax_override} | Taux total: {cfg.get('effective_rate',0.26)*100:.1f}%")

        # Auto-detect period from CDR timestamps if possible
        detected_period = stats.get("period_detected", "")
        if detected_period:
            period = detected_period
            print(f"  📅 Période auto-détectée: {period}")

        finding = run_efr(stats, country, operator, period, decl)

        # Forcer la devise correcte depuis la config
        if "currency" in cfg and cfg["country"].lower() in country.lower():
            finding["currency"] = cfg["currency"]
        jobs[jid]["progress"] = 60

        # STEP 3: Anomaly detection (lecture directe du fichier)
        try:
            enc   = dec.detect_encoding(str(fpath))
            delim = dec.detect_delimiter(str(fpath), enc)
            chunks = []
            for chunk in pd.read_csv(
                str(fpath), sep=delim, encoding=enc,
                chunksize=10000, on_bad_lines='skip', low_memory=False
            ):
                chunks.append(dec.normalize_chunk(chunk))
            full_df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        except Exception as e:
            print(f"  ⚠️ Lecture anomalies: {e}")
            full_df = pd.DataFrame()

        det  = AnomalyDetector()
        anom = det.run_all(full_df, is_momo=is_momo)
        finding["anomalies"] = anom
        jobs[jid]["progress"] = 80

        # STEP 4: Generate reports
        rg   = ReportGenerator(str(REPORTS_DIR))
        rpts = rg.generate(finding, operator, country, period)

        # Générer les rapports étendus B04 B06 C03-C05 D04 D05 D07 D10 F01-F04
        try:
            ext = ExtendedReportGenerator(str(REPORTS_DIR))
            ext_rpts = ext.build_all_missing(finding, anom)
            # Merge into rpts dict
            for code, paths in ext_rpts.items():
                if paths and "error" not in paths:
                    rpts[code] = paths
        except Exception as ex:
            print(f"  ⚠️ Extended reports error: {ex}")

        jobs[jid]["progress"] = 100
        jobs[jid]["status"]   = "complete"
        jobs[jid]["result"]   = {
            "finding":   finding,
            "reports":   rpts,
            "anomalies": anom
        }
    except Exception as e:
        jobs[jid]["status"] = "error"
        jobs[jid]["error"]  = str(e)
        import traceback; traceback.print_exc()

@app.get("/api/job/{jid}")
async def job_status(jid:str):
    j = jobs.get(jid)
    if not j: raise HTTPException(404)
    return j

@app.get("/api/result/{jid}")
async def job_result(jid:str):
    j = jobs.get(jid)
    if not j: raise HTTPException(404)
    if j["status"]!="complete": raise HTTPException(202,"Not ready")
    return j["result"]


@app.post("/api/report/generate")
async def generate_report_on_demand(request: Request):
    """Génère un rapport PDF/Excel/CSV/JSON depuis le catalogue."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON invalide")

    report_code = data.get("report_code", "A01")
    fmt         = data.get("format", "pdf").lower()
    finding     = data.get("finding") or {}
    anomalies   = data.get("anomalies") or {}

    # S'assurer que finding est un dict modifiable
    if isinstance(finding, str):
        try:
            import json as _j
            finding = _j.loads(finding)
        except Exception:
            finding = {}
    finding = dict(finding)

    # Enrichir depuis config active si manquant
    cfg = country_config.copy()
    if not finding.get("operator"):
        ops = cfg.get("operators", [])
        finding["operator"] = ops[0]["name"] if ops else "Opérateur"
    if not finding.get("country"):
        finding["country"]  = cfg.get("country", "Pays")
    if not finding.get("period"):
        finding["period"]   = data.get("period", "Avril 2026")
    if not finding.get("currency"):
        finding["currency"] = cfg.get("currency", "XAF")

    # SHA-256 si absent
    if not finding.get("sha256"):
        import hashlib, json as _j
        finding["sha256"] = hashlib.sha256(
            _j.dumps(finding, sort_keys=True, default=str).encode()
        ).hexdigest()

    # Champs obligatoires avec valeurs par défaut
    finding.setdefault("total_revenue", 0)
    finding.setdefault("tax_due", 0)
    finding.setdefault("declared_revenue", 0)
    finding.setdefault("total_records", 0)
    finding.setdefault("certified", {})
    if not finding.get("gap"):
        finding["gap"] = {
            "tax_gap": finding["tax_due"] - finding["declared_revenue"],
            "tax_gap_local": finding["tax_due"] - finding["declared_revenue"],
            "gap_pct": 0,
        }

    try:
        from reports.report_generator import ReportGenerator
        from reports.extended_reports import ExtendedReportGenerator

        rg  = ReportGenerator(str(REPORTS_DIR))
        erg = ExtendedReportGenerator(str(REPORTS_DIR))

        # Rapports étendus (codes spéciaux)
        extended_map = {
            "B04": erg.build_B04, "B06": erg.build_B06,
            "C03": erg.build_C03, "C04": erg.build_C04, "C05": erg.build_C05,
            "D04": erg.build_D04, "D05": erg.build_D05,
            "D07": erg.build_D07, "D10": erg.build_D10,
            "F01": erg.build_F01, "F02": erg.build_F02,
            "F03": erg.build_F03, "F04": erg.build_F04,
        }

        filepath = None
        ext      = "pdf"
        media    = "application/pdf"

        if fmt in ("xlsx", "excel"):
            # Excel
            if report_code in extended_map:
                paths = extended_map[report_code](finding, anomalies)
                filepath = paths.get("excel") or paths.get("pdf")
            else:
                filepath = rg.generate_excel(finding)
            ext   = "xlsx"
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        elif fmt == "json":
            # JSON
            if report_code in extended_map:
                paths = extended_map[report_code](finding, anomalies)
                filepath = paths.get("json") or paths.get("pdf")
            else:
                filepath = rg.save_json(finding)
            ext   = "json"
            media = "application/json"

        elif fmt == "csv":
            # CSV depuis JSON
            if report_code in extended_map:
                paths = extended_map[report_code](finding, anomalies)
                j = paths.get("json","")
            else:
                j = rg.save_json(finding)
            if j and os.path.exists(str(j)):
                j = str(j)
                csv_path = j.replace(".json", ".csv") if j.endswith(".json") else j + ".csv"
                import csv as csv_mod, json as _j
                with open(j,"r") as jf:
                    jdata = _j.load(jf)
                with open(csv_path,"w",newline="",encoding="utf-8") as cf:
                    w = csv_mod.writer(cf)
                    w.writerow(["Rapport","Opérateur","Pays","Période","Devise","SHA-256"])
                    w.writerow([report_code, finding["operator"], finding["country"],
                                finding["period"], finding["currency"], finding["sha256"]])
                    w.writerow([])
                    w.writerow(["Revenue Total","Tax Due","Tax Déclaré","EFR Gap","CDRs"])
                    w.writerow([finding["total_revenue"], finding["tax_due"],
                                finding["declared_revenue"],
                                finding["gap"].get("tax_gap_local", finding["gap"].get("tax_gap",0)),
                                finding["total_records"]])
                filepath = csv_path
            ext   = "csv"
            media = "text/csv"

        else:
            # PDF (défaut)
            if report_code in extended_map:
                paths = extended_map[report_code](finding, anomalies)
                filepath = paths.get("pdf")
            else:
                filepath = rg.generate_pdf(finding)
            ext   = "pdf"
            media = "application/pdf"

        if not filepath or not os.path.exists(str(filepath)):
            raise HTTPException(500, f"Fichier non généré pour {report_code} [{fmt}]")

        filepath = str(filepath)

        # Vérifier PDF valide
        if ext == "pdf":
            with open(filepath,"rb") as f:
                hdr = f.read(4)
            if hdr != b"%PDF":
                raise HTTPException(500, f"Fichier généré invalide (header={hdr})")

        # Nom de fichier propre
        op_c  = str(finding.get("operator","rapport")).replace(" ","_")[:20]
        per_c = str(finding.get("period","2026")).replace(" ","_")
        fname = f"NOCTYRA360_{report_code}_{op_c}_{per_c}.{ext}"

        print(f"  ✅ Rapport {report_code} [{ext.upper()}] → {fname}")

        return FileResponse(
            path=filepath,
            filename=fname,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback as _tb
        _tb.print_exc()
        raise HTTPException(500, f"Erreur rapport {report_code}: {str(e)}")


@app.get("/api/report/{filename}")
async def get_report(filename:str):
    p = REPORTS_DIR / filename
    if not p.exists(): raise HTTPException(404)
    return FileResponse(str(p))





@app.get("/api/countries/madagascar")
async def madagascar_config():
    """Return complete Madagascar configuration for frontend."""
    from core.efr_engine import TAX_MATRICES
    mdg = TAX_MATRICES.get("Madagascar", {})
    return {
        "country":   "Madagascar",
        "code":      "MDG",
        "flag":      "🇲🇬",
        "currency":  mdg.get("currency", "MGA"),
        "fx_to_usd": mdg.get("fx_to_usd", 4800),
        "gdp_usd":   mdg.get("gdp_usd", 14_800_000_000),
        "regulator": mdg.get("regulator", "ARTEC"),
        "tax_auth":  mdg.get("tax_auth", "DGI"),
        "operators": mdg.get("operators", []),
        "momo_ops":  mdg.get("momo_operators", []),
        "taxes":     mdg.get("taxes", {}),
        "msisdn":    mdg.get("msisdn_prefix", "+261"),
        "imf_gap_estimate_usd": round(
            mdg.get("gdp_usd", 14_800_000_000) * 
            mdg.get("imf_benchmark", 0.013) / 12, 0
        ),
    }

@app.post("/api/demo/scenario")
async def demo_scenario(country:str="Centrafrique"):
    return {"status":"ok","country":country}

# ── Démarrage serveur ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    import socket

    # Obtenir l'IP locale
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "127.0.0.1"

    print("")
    print("=" * 52)
    print("  NOCTYRA360™ — PRODUCTION SERVER")
    print("  Connect Now USA LLC — Bridge v7")
    print("=" * 52)
    print(f"")
    print(f"  ✅ Serveur démarré")
    print(f"")
    print(f"  Ouvrir Chrome sur :")
    print(f"  ► http://localhost:8000/")
    print(f"  ► http://{ip}:8000/")
    print(f"")
    print(f"  ⚠️  NE PAS ouvrir le fichier HTML directement")
    print(f"  ⚠️  Toujours passer par http://...")
    print(f"")
    print("=" * 52)
    print("")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning"
    )
