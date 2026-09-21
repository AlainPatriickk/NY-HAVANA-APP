import os
import json
import datetime
import unicodedata
import pandas as pd
from database import db, init_db, Client, Quittance, HistoriqueDocument
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
from database import db, init_db

init_db(app)
with app.app_context():
  db.create_all()
    
app.secret_key = "ny_havana_secret_key_pro"

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ==================== CONFIGURATION FLASK-LOGIN & USERS ====================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

USERS_FILE = 'users.json'

def load_users():
    if not os.path.exists(USERS_FILE):
        default_users = {
            "admin": {
                "password": generate_password_hash("admin123"),
                "role": "admin",
                "nom_complet": "Administrateur Principal"
            }
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_users, f, indent=4)
        return default_users
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

class User(UserMixin):
    def __init__(self, username, role, nom_complet):
        self.id = username
        self.role = role
        self.nom_complet = nom_complet

@login_manager.user_loader
def load_user(username):
    users = load_users()
    if username in users:
        u = users[username]
        return User(username, u['role'], u.get('nom_complet', username))
    return None

# Context Processor mba hisehoan'ny datetime sy current_user ao amin'ny template rehetra
@app.context_processor
def inject_globals():
    return dict(datetime=datetime.datetime)

# ==================== DONNÉES & FONCTIONS DE BASE ====================
BRANCHES = {
    10: "VIE", 14: "ARC", 16: "SANTE", 18: "AVI",
    19: "ASE", 20: "AUTO", 30: "INCENDIE", 40: "RISQUE DIVERS",
    50: "MARITIME", 60: "RISQUE DIVERS", 70: "MARITIME", 75: "TERRESTRE"
}

COUNTER_LSP_FILE = "counter_lsp.txt"
COUNTER_FACT_FILE = "counter_facture.txt"
FACTURES_HISTORY_FILE = "factures_history.json"
LSP_HISTORY_FILE = "lsp_history.json"

def strip_accents(s):
    if not isinstance(s, str):
        s = str(s)
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower().strip()

def get_next_lsp_number():
    current_year = datetime.datetime.now().strftime("%y")
    count = 1
    if os.path.exists(COUNTER_LSP_FILE):
        try:
            with open(COUNTER_LSP_FILE, "r") as f:
                data = f.read().strip()
                if data:
                    last_year, last_count = data.split("-")
                    if last_year == current_year:
                        count = int(last_count) + 1
        except Exception:
            count = 1
            
    with open(COUNTER_LSP_FILE, "w") as f:
        f.write(f"{current_year}-{count}")
        
    return f"{count:03d}-NH/{current_year}/ACF"

def get_next_facture_number():
    count = 1
    if os.path.exists(COUNTER_FACT_FILE):
        try:
            with open(COUNTER_FACT_FILE, "r") as f:
                data = f.read().strip()
                if data:
                    count = int(data) + 1
        except Exception:
            count = 1
            
    with open(COUNTER_FACT_FILE, "w") as f:
        f.write(str(count))
        
    return f"REF-{count:06d}"

def load_factures_history():
    if os.path.exists(FACTURES_HISTORY_FILE):
        try:
            with open(FACTURES_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_facture_to_history(facture_data):
    history = load_factures_history()
    history = [f for f in history if f['ref_num'] != facture_data['ref_num']]
    history.append(facture_data)
    with open(FACTURES_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4, default=str)

def load_lsp_history():
    if os.path.exists(LSP_HISTORY_FILE):
        try:
            with open(LSP_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_lsp_to_history(lsp_data):
    history = load_lsp_history()
    history = [l for l in history if l['num_lsp'] != lsp_data['num_lsp']]
    history.append(lsp_data)
    with open(LSP_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4, default=str)

def clean_code(val):
    if pd.isna(val) or val is None:
        return ""
    try:
        f_val = float(str(val).replace(',', '.').strip())
        s_val = f"{f_val:.0f}"
        return s_val
    except Exception:
        s = str(val).strip().replace(" ", "")
        if s.endswith('.0'):
            s = s[:-2]
        return s.strip()

def clean_client_name(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ['nan', 'none', 'null', '0', '', 'client non spécifié']:
        return ""
    return s

def find_column(df, possible_names):
    if df is None or df.empty:
        return None
    cols_map = {}
    for c in df.columns:
        clean_c = strip_accents(str(c)).replace(' ', '').replace('_', '').replace('°', '').replace('.', '').replace('\n', '').replace('\r', '')
        cols_map[clean_c] = c

    for name in possible_names:
        clean_n = strip_accents(name).replace(' ', '').replace('_', '').replace('°', '').replace('.', '').replace('\n', '').replace('\r', '')
        if clean_n in cols_map:
            return cols_map[clean_n]
    return None

def load_data():
    all_files = []

    if os.path.exists(UPLOAD_FOLDER):
        for f in os.listdir(UPLOAD_FOLDER):
            if f.endswith(('.xlsx', '.xls')) and not f.startswith('~$'):
                all_files.append(os.path.join(UPLOAD_FOLDER, f))

    for f in os.listdir('.'):
        if f.endswith(('.xlsx', '.xls')) and not f.startswith('~$'):
            full_p = os.path.join('.', f)
            if full_p not in all_files:
                all_files.append(full_p)

    if not all_files:
        return pd.DataFrame()

    df_list_arr = []
    df_list_enc = []

    for filepath in all_files:
        try:
            df_temp = pd.read_excel(filepath)
            df_temp.columns = [str(c).strip() for c in df_temp.columns]

            col_m_enc = find_column(df_temp, ["montantencaisse", "montantencais", "encaissement", "reglement", "paye", "versement", "montantverse"])
            fname = os.path.basename(filepath).lower()

            if 'encaissement' in fname or 'ca' in fname or 'reglement' in fname or col_m_enc is not None:
                df_list_enc.append(df_temp)
            else:
                df_list_arr.append(df_temp)
        except Exception as e:
            print(f"Erreur famakiana {filepath}: {e}")

    if not df_list_arr:
        return pd.DataFrame()

    df_arr = pd.concat(df_list_arr, ignore_index=True)

    col_q_arr = find_column(df_arr, ["nquit", "nquittance", "quittance", "numquittance", "nquitt"]) or df_arr.columns[0]
    col_pol_arr = find_column(df_arr, ["npoli", "npolice", "police", "numpolice", "npol"]) or df_arr.columns[1]
    col_cli_arr = find_column(df_arr, ["client", "assure", "nomassure", "nomclient", "sousripteur"]) or df_arr.columns[2]
    col_m_arr = find_column(df_arr, ["montantinitial", "montant", "primetotale", "arrieres", "solde", "prime"])
    col_b_arr = find_column(df_arr, ["codeb", "codebranch", "codebranche", "codebra", "bra", "branche"])
    col_eff_arr = find_column(df_arr, ["dateeffe", "dateeffet", "dateeff", "effet", "dteffet"])
    col_ech_arr = find_column(df_arr, ["dateec", "dateechean", "dateecheance", "echeance", "dtechet"])
    col_annee_arr = find_column(df_arr, ["annee", "exerc", "exerci", "exercice"])

    dict_enc_quittance = {}
    if df_list_enc:
        df_enc = pd.concat(df_list_enc, ignore_index=True)
        col_q_enc = find_column(df_enc, ["nquit", "nquittance", "quittance", "numquittance", "quit", "npiece", "nrecu", "ref"])
        col_m_enc = find_column(df_enc, ["montantencaisse", "montantencais", "encaissement", "reglement", "paye", "montant", "versement", "montantverse"])

        if col_q_enc and col_m_enc:
            df_enc['clean_q'] = df_enc[col_q_enc].apply(clean_code)
            df_enc['clean_m'] = pd.to_numeric(
                df_enc[col_m_enc].astype(str).str.replace(' ', '').str.replace(',', '.'), 
                errors='coerce'
            ).fillna(0.0)
            dict_enc_quittance = df_enc.groupby('clean_q')['clean_m'].sum().to_dict()

    df_arr['N° Quittance'] = df_arr[col_q_arr].apply(clean_code) if col_q_arr else ""
    df_arr['N° Police'] = df_arr[col_pol_arr].apply(clean_code) if col_pol_arr else "NON SPÉCIFIÉ"
    df_arr['Client'] = df_arr[col_cli_arr].apply(clean_client_name) if col_cli_arr else ""

    valid_clients = df_arr[df_arr['Client'] != ""].groupby('N° Police')['Client'].first().to_dict()
    
    def fill_client(row):
        if row['Client'] != "":
            return row['Client']
        return valid_clients.get(row['N° Police'], "CLIENT NON SPÉCIFIÉ")

    df_arr['Client'] = df_arr.apply(fill_client, axis=1)

    if col_m_arr:
        df_arr['Montant Initial'] = pd.to_numeric(
            df_arr[col_m_arr].astype(str).str.replace(' ', '').str.replace(',', '.'), 
            errors='coerce'
        ).fillna(0.0)
    else:
        df_arr['Montant Initial'] = 0.0

    df_arr['Code Branche'] = pd.to_numeric(df_arr[col_b_arr], errors='coerce').fillna(20).astype(int) if col_b_arr else 20

    if col_eff_arr:
        dates_converted = pd.to_datetime(df_arr[col_eff_arr], dayfirst=True, errors='coerce')
        df_arr['Date Effet'] = dates_converted.dt.strftime('%d/%m/%Y').fillna('')
        if col_annee_arr:
            df_arr['Annee'] = pd.to_numeric(df_arr[col_annee_arr], errors='coerce').fillna(dates_converted.dt.year).fillna(2025).astype(int)
        else:
            df_arr['Annee'] = dates_converted.dt.year.fillna(2025).astype(int)
    else:
        df_arr['Date Effet'] = ''
        df_arr['Annee'] = 2025

    if col_ech_arr:
        dates_ech = pd.to_datetime(df_arr[col_ech_arr], dayfirst=True, errors='coerce')
        df_arr['Date Echéance'] = dates_ech.dt.strftime('%d/%m/%Y').fillna('')
    else:
        df_arr['Date Echéance'] = ''

    df_arr['Montant Encaissé'] = df_arr['N° Quittance'].apply(lambda q: dict_enc_quittance.get(q, 0.0) if q != "" else 0.0)
    df_arr['Reliquat'] = df_arr['Montant Initial'] - df_arr['Montant Encaissé']
    
    df_arr = df_arr.drop_duplicates(subset=['N° Quittance', 'N° Police', 'Client', 'Montant Initial'])
    
    return df_arr

def search_in_df(df, query):
    if df.empty or not query:
        return df.head(0)
    
    clean_query = strip_accents(query)
    keywords = [k.strip() for k in clean_query.split() if k.strip()]
    
    clean_client = df['Client'].apply(strip_accents)
    clean_police = df['N° Police'].apply(strip_accents)
    clean_quittance = df['N° Quittance'].apply(strip_accents)

    mask = pd.Series(True, index=df.index)
    for kw in keywords:
        kw_mask = (
            clean_client.str.contains(kw, na=False, regex=False) |
            clean_police.str.contains(kw, na=False, regex=False) |
            clean_quittance.str.contains(kw, na=False, regex=False)
        )
        mask = mask & kw_mask
        
    return df[mask]

def get_valid_client_name(df_filtered, df_full=None, police_num=None):
    for name in df_filtered['Client']:
        clean_n = clean_client_name(name)
        if clean_n:
            return clean_n

    if df_full is not None and police_num:
        matched = df_full[df_full['N° Police'] == police_num]
        for name in matched['Client']:
            clean_n = clean_client_name(name)
            if clean_n:
                return clean_n

    return "CLIENT NON SPÉCIFIÉ"

# ==================== ROUTES AUTHENTIFICATION ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        users = load_users()

        if username in users and check_password_hash(users[username]['password'], password):
            u_data = users[username]
            user_obj = User(username, u_data['role'], u_data.get('nom_complet', username))
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        else:
            flash('Identifiant na Mot de passe tsy marina!', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/create_user', methods=['POST'])
@login_required
def create_user():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Tsy mahazo alalana hanao ity asa ity ianao.'}), 403

    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    nom_complet = data.get('nom_complet', '').strip()
    role = data.get('role', 'user')

    if not username or not password or not nom_complet:
        return jsonify({'success': False, 'message': 'Fenoy ny saha rehetra!'})

    users = load_users()
    if username in users:
        return jsonify({'success': False, 'message': 'Efa misy io Anarana mpampiasa io (Username).'})

    users[username] = {
        'password': generate_password_hash(password),
        'role': role,
        'nom_complet': nom_complet
    }
    save_users(users)
    return jsonify({'success': True, 'message': 'Tafiditra soa aman-tsara ny mpampiasa vaovao!'})

# ==================== ROUTES APLIKASYON (PROTEGÉES) ====================

@app.route('/')
@login_required
def dashboard():
    selected_annee = request.args.get('annee', '')
    df = load_data()
    annees_dispo, branches_stats = [], []
    val_arr, val_enc, val_rel, count_impayes = 0.0, 0.0, 0.0, 0

    if not df.empty:
        annees_dispo = sorted([str(int(a)) for a in df['Annee'].unique() if pd.notna(a)], reverse=True)
        if selected_annee and selected_annee != "Toutes":
            df = df[df['Annee'].astype(str) == selected_annee]

        val_arr = float(df['Montant Initial'].sum())
        val_enc = float(df['Montant Encaissé'].sum())
        val_rel = float(df['Reliquat'].sum())
        count_impayes = int(len(df[df['Reliquat'] > 0.01]))

        for code, libelle in BRANCHES.items():
            sub_df = df[df['Code Branche'] == code]
            arr = float(sub_df['Montant Initial'].sum())
            enc = float(sub_df['Montant Encaissé'].sum())
            rel = arr - enc
            taux = f"{(rel / arr * 100):.0f}%" if arr > 0 else "0%"
            if arr > 0 or enc > 0:
                branches_stats.append({
                    'code': code,
                    'libelle': libelle,
                    'arrieres': f"{arr:,.2f}".replace(",", " "),
                    'encaissements': f"{enc:,.2f}".replace(",", " "),
                    'reliquat': f"{rel:,.2f}".replace(",", " "),
                    'taux': taux
                })

    return render_template(
        'index.html', 
        active_tab='dashboard',
        total_arrieres=f"{val_arr:,.2f}".replace(",", " "),
        total_encaissements=f"{val_enc:,.2f}".replace(",", " "),
        total_reliquats=f"{val_rel:,.2f}".replace(",", " "),
        count_impayes=count_impayes,
        branches_stats=branches_stats,
        annees_dispo=annees_dispo,
        selected_annee=selected_annee
    )

@app.route('/importation', methods=['GET', 'POST'])
@login_required
def importation():
    if request.method == 'POST':
        file_type = request.form.get('file_type')
        file = request.files.get('file')
        
        if not file or file.filename == '':
            flash("Azafady, mifidiana rakitra Excel iray!", "danger")
            return redirect(url_for('importation'))
        
        try:
            df = pd.read_excel(file)
            
            if file_type == 'arriere':
                for _, row in df.iterrows():
                    nom_client = str(row.get('Client', 'NON SPECifie')).strip()
                    
                    # Jereo na ividino aloha ny Client sao dia efa misy ao amin'ny table clients
                    client_obj = Client.query.filter_by(nom_assure=nom_client).first()
                    if not client_obj:
                        client_obj = Client(nom_assure=nom_client)
                        db.session.add(client_obj)
                        db.session.commit()
                    
                    # Ampidiro ao amin'ny table Quittances (miaraka amin'ny quittance_num tsy atao unique mba handray paiement partiel)
                    quittance_num_val = str(row.get('N° Quittance', ''))
                    police_val = str(row.get('N° Police', ''))
                    branche_val = str(row.get('Code branche', ''))
                    annee_val = int(row.get('Annee', 2025) or 2025)
                    montant_val = float(row.get('Montant Initial', 0.0) or 0.0)
                    
                    nouvelle_quittance = Quittance(
                        police=police_val,
                        quittance_num=quittance_num_val,
                        branche=str(branche_val),
                        annee=annee_val,
                        prime_totale=montant_val,
                        encaisse=0.0,
                        reliquat=montant_val,
                        etat='Impayé',
                        id_client=client_obj.id
                    )
                    db.session.add(nouvelle_quittance)
                
                db.session.commit()
                flash("Fichier NOUVEAU ARRIÉRÉ voaray sy voatahiry maharitra ao amin'ny PostgreSQL!", "success")
                
            elif file_type == 'encaissement':
                # Afaka ampidirina eto koa ny lojika ho an'ny encaissement / paiement partiel
                flash("Fichier ÉTAT DES ENCAISSEMENTS voaray!", "success")
            else:
                flash("Karazana rakitra tsy fantatra!", "danger")
                return redirect(url_for('importation'))
                
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Nisy olana tamin'ny fampidirana: {e}", "danger")
            return redirect(url_for('importation'))
            
    return render_template('importation.html', active_tab='importation')
@app.route('/recherche')
@login_required
def recherche():
    query = request.args.get('q', '').strip()
    selected_police = request.args.get('police', '').strip()
    
    df = load_data()
    results = []
    polices_dispo = []
    total_reliquat = 0.0
    client_name, police_num = "", ""

    if not df.empty and query:
        df_impayes = df[df['Reliquat'] > 0.01]
        df_filtered = search_in_df(df_impayes, query)
        
        if not df_filtered.empty:
            polices_dispo = sorted(list(df_filtered['N° Police'].unique()))
            
            if selected_police:
                df_filtered = df_filtered[df_filtered['N° Police'] == selected_police]

            results = df_filtered.to_dict(orient='records')
            total_reliquat = float(df_filtered['Reliquat'].sum())
            police_num = selected_police if selected_police else df_filtered.iloc[0]['N° Police']
            client_name = get_valid_client_name(df_filtered, df_full=df, police_num=police_num)

    return render_template(
        'recherche.html', 
        active_tab='recherche', 
        query=query, 
        selected_police=selected_police,
        polices_dispo=polices_dispo,
        results=results, 
        total_reliquat=f"{total_reliquat:,.2f}".replace(",", " "),
        client_name=client_name,
        police_num=police_num
    )

@app.route('/extrait')
@login_required
def extrait():
    history = load_factures_history()
    df_data = load_data()
    
    factures_processed = []
    today = datetime.datetime.now().date()
    
    total_factures = len(history)
    count_reglees = 0
    count_encours = 0
    count_lsp_urgent = 0
    montant_total_factures = 0.0

    for fact in reversed(history):
        ref_num = fact['ref_num']
        police_num = fact['police_num']
        client_name = fact['client_name']
        date_str = fact['date_creation']
        items = fact['items']
        
        total_initial = 0.0
        total_encaisse = 0.0
        total_reliquat = 0.0
        
        for item in items:
            q_code = item['N° Quittance']
            match = df_data[df_data['N° Quittance'] == q_code] if not df_data.empty else pd.DataFrame()
            if not match.empty:
                m_init = float(match.iloc[0]['Montant Initial'])
                m_enc = float(match.iloc[0]['Montant Encaissé'])
                m_rel = float(match.iloc[0]['Reliquat'])
            else:
                m_init = float(item.get('Montant Initial', 0.0))
                m_enc = float(item.get('Montant Encaissé', 0.0))
                m_rel = float(item.get('Reliquat', m_init - m_enc))
                
            total_initial += m_init
            total_encaisse += m_enc
            total_reliquat += m_rel

        montant_total_factures += total_initial

        try:
            dt_creation = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
            days_diff = (today - dt_creation).days
        except Exception:
            days_diff = 0

        if total_reliquat <= 0.01:
            statut = "PAYÉ"
            badge_class = "bg-success"
            count_reglees += 1
        elif total_encaisse > 0:
            statut = "EN COURS DE RÈGLEMENT"
            badge_class = "bg-info text-dark"
            count_encours += 1
        else:
            if days_diff >= 15:
                statut = "LSP URGENT (> 15j)"
                badge_class = "bg-danger text-white fw-bold"
                count_lsp_urgent += 1
            else:
                statut = "NON PAYÉ"
                badge_class = "bg-warning text-dark"
                count_encours += 1

        factures_processed.append({
            'ref_num': ref_num,
            'police_num': police_num,
            'client_name': client_name,
            'date_creation': date_str,
            'created_by': fact.get('created_by', 'Agent'),
            'montant_total': f"{total_initial:,.2f}".replace(",", " "),
            'total_encaisse': f"{total_encaisse:,.2f}".replace(",", " "),
            'total_reliquat': f"{total_reliquat:,.2f}".replace(",", " "),
            'statut': statut,
            'badge_class': badge_class,
            'days_diff': days_diff
        })

    return render_template(
        'extrait.html', 
        active_tab='extrait', 
        factures=factures_processed,
        total_factures=total_factures,
        count_reglees=count_reglees,
        count_encours=count_encours,
        count_lsp_urgent=count_lsp_urgent,
        montant_total_factures=f"{montant_total_factures:,.2f}".replace(",", " ")
    )

@app.route('/lsp')
@login_required
def lsp():
    lsp_history = load_lsp_history()
    df_data = load_data()
    today = datetime.datetime.now().date()
    
    lsp_processed = []
    total_lsp = len(lsp_history)
    count_regles = 0
    count_encours = 0
    count_resiliations = 0
    montant_total_lsp = 0.0

    for lsp_item in reversed(lsp_history):
        num_lsp = lsp_item['num_lsp']
        police_num = lsp_item['police_num']
        client_name = lsp_item['client_name']
        date_str = lsp_item['date_creation']
        items = lsp_item['items']

        total_initial = 0.0
        total_encaisse = 0.0
        total_reliquat = 0.0

        for item in items:
            q_code = item['N° Quittance']
            match = df_data[df_data['N° Quittance'] == q_code] if not df_data.empty else pd.DataFrame()
            if not match.empty:
                m_init = float(match.iloc[0]['Montant Initial'])
                m_enc = float(match.iloc[0]['Montant Encaissé'])
                m_rel = float(match.iloc[0]['Reliquat'])
            else:
                m_init = float(item.get('Montant Initial', 0.0))
                m_enc = float(item.get('Montant Encaissé', 0.0))
                m_rel = float(item.get('Reliquat', m_init - m_enc))

            total_initial += m_init
            total_encaisse += m_enc
            total_reliquat += m_rel

        montant_total_lsp += total_initial

        try:
            dt_creation = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
            days_diff = (today - dt_creation).days
        except Exception:
            days_diff = 0

        if total_reliquat <= 0.01:
            statut = "RÉGLÉ"
            badge_class = "bg-success"
            count_regles += 1
        elif total_encaisse > 0:
            statut = "EN COURS DE RÈGLEMENT"
            badge_class = "bg-info text-dark"
            count_encours += 1
        else:
            if days_diff >= 40:
                statut = "RÉSILIATION À EFFECTUER"
                badge_class = "bg-danger text-white fw-bold"
                count_resiliations += 1
            else:
                statut = "EN COURS"
                badge_class = "bg-warning text-dark"
                count_encours += 1

        lsp_processed.append({
            'num_lsp': num_lsp,
            'police_num': police_num,
            'client_name': client_name,
            'date_creation': date_str,
            'created_by': lsp_item.get('created_by', 'Agent'),
            'montant_total': f"{total_initial:,.2f}".replace(",", " "),
            'total_encaisse': f"{total_encaisse:,.2f}".replace(",", " "),
            'total_reliquat': f"{total_reliquat:,.2f}".replace(",", " "),
            'statut': statut,
            'badge_class': badge_class,
            'days_diff': days_diff
        })

    return render_template(
        'lsp.html',
        active_tab='lsp',
        lsp_list=lsp_processed,
        total_lsp=total_lsp,
        count_regles=count_regles,
        count_encours=count_encours,
        count_resiliations=count_resiliations,
        montant_total_lsp=f"{montant_total_lsp:,.2f}".replace(",", " ")
    )

@app.route('/generate_lsp')
@login_required
def generate_lsp():
    query = request.args.get('q', '').strip()
    selected_police = request.args.get('police', '').strip()
    lsp_exist = request.args.get('num', '').strip()
    
    history = load_lsp_history()

    if lsp_exist:
        lsp_match = [l for l in history if l['num_lsp'] == lsp_exist]
        if lsp_match:
            l_data = lsp_match[0]
            return render_template(
                'lsp_template.html',
                num_lsp=l_data['num_lsp'],
                client_name=l_data['client_name'],
                police_num=l_data['police_num'],
                today_date=l_data['date_creation'],
                printed_by=l_data.get('created_by', current_user.nom_complet),
                items=l_data['items'],
                total_reliquat=l_data['total_reliquat']
            )

    df = load_data()
    if df.empty or not query:
        return "Tsy misy mpanjifa hita", 404
        
    df_impayes = df[df['Reliquat'] > 0.01]
    df_filtered = search_in_df(df_impayes, query)

    if selected_police:
        df_filtered = df_filtered[df_filtered['N° Police'] == selected_police]

    if df_filtered.empty:
        return "Tsy misy impayés hita amin'ity fikarohana ity", 404

    num_lsp = get_next_lsp_number()
    police_num = selected_police if selected_police else df_filtered.iloc[0]['N° Police']
    client_name = get_valid_client_name(df_filtered, df_full=df, police_num=police_num)
    
    total_reliquat = float(df_filtered['Reliquat'].sum())
    today_date = datetime.datetime.now().strftime("%d/%m/%Y")
    items_list = df_filtered.to_dict(orient='records')

    for it in items_list:
        for k, v in it.items():
            if isinstance(v, (pd.Timestamp, datetime.date, datetime.datetime)):
                it[k] = str(v)

    save_lsp_to_history({
        'num_lsp': num_lsp,
        'police_num': police_num,
        'client_name': client_name,
        'date_creation': today_date,
        'created_by': f"{current_user.nom_complet} ({current_user.id})",
        'items': items_list,
        'total_reliquat': f"{total_reliquat:,.2f}".replace(",", " ")
    })

    return render_template(
        'lsp_template.html',
        num_lsp=num_lsp,
        client_name=client_name,
        police_num=police_num,
        today_date=today_date,
        printed_by=f"{current_user.nom_complet} ({current_user.id})",
        items=items_list,
        total_reliquat=f"{total_reliquat:,.2f}".replace(",", " ")
    )

@app.route('/generate_facture')
@login_required
def generate_facture():
    query = request.args.get('q', '').strip()
    selected_police = request.args.get('police', '').strip()
    ref_exist = request.args.get('ref', '').strip()
    
    history = load_factures_history()

    if ref_exist:
        fact_match = [f for f in history if f['ref_num'] == ref_exist]
        if fact_match:
            f_data = fact_match[0]
            return render_template(
                'facture_template.html',
                ref_num=f_data['ref_num'],
                client_name=f_data['client_name'],
                police_num=f_data['police_num'],
                today_date=f_data['date_creation'],
                printed_by=f_data.get('created_by', current_user.nom_complet),
                items=f_data['items'],
                total_reliquat=f_data['total_reliquat']
            )

    df = load_data()
    if df.empty or not query:
        return "Tsy misy mpanjifa hita", 404
        
    df_impayes = df[df['Reliquat'] > 0.01]
    df_filtered = search_in_df(df_impayes, query)

    if selected_police:
        df_filtered = df_filtered[df_filtered['N° Police'] == selected_police]

    if df_filtered.empty:
        return "Tsy misy impayés hita amin'ity fikarohana ity", 404

    police_num = selected_police if selected_police else df_filtered.iloc[0]['N° Police']
    client_name = get_valid_client_name(df_filtered, df_full=df, police_num=police_num)
    
    ref_num = get_next_facture_number()
    today_date = datetime.datetime.now().strftime("%d/%m/%Y")
    total_reliquat = float(df_filtered['Reliquat'].sum())
    items_list = df_filtered.to_dict(orient='records')

    for it in items_list:
        for k, v in it.items():
            if isinstance(v, (pd.Timestamp, datetime.date, datetime.datetime)):
                it[k] = str(v)

    save_facture_to_history({
        'ref_num': ref_num,
        'police_num': police_num,
        'client_name': client_name,
        'date_creation': today_date,
        'created_by': f"{current_user.nom_complet} ({current_user.id})",
        'items': items_list,
        'total_reliquat': f"{total_reliquat:,.2f}".replace(",", " ")
    })

    return render_template(
        'facture_template.html',
        ref_num=ref_num,
        client_name=client_name,
        police_num=police_num,
        today_date=today_date,
        printed_by=f"{current_user.nom_complet} ({current_user.id})",
        items=items_list,
        total_reliquat=f"{total_reliquat:,.2f}".replace(",", " ")
    )

@app.route('/traitement')
@login_required
def traitement():
    df = load_data()
    results = []
    if not df.empty:
        results = df.to_dict(orient='records')
    return render_template('traitement.html', active_tab='traitement', results=results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
