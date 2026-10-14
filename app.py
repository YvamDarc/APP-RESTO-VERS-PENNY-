import copy
import hashlib
import json
import pandas as pd
import streamlit as st
from converter import DEFAULT, load_archives, build, config_check, money

st.set_page_config(page_title='Deliveroo → Pennylane',page_icon='🧾',layout='wide')
st.title('Deliveroo → Pennylane')
st.caption('ZIP Deliveroo · schéma comptable modifiable · écritures FEC et justificatifs liés')

@st.cache_data(show_spinner=False)
def analyse(blobs):
    return load_archives(blobs)

if 'cfg' not in st.session_state: st.session_state.cfg=copy.deepcopy(DEFAULT)
with st.sidebar:
    st.header('Paramétrage')
    imported=st.file_uploader('Charger un paramétrage JSON',type=['json'],key='cfg_file')
    if imported and st.button('Appliquer ce paramétrage'):
        try:
            cfg=copy.deepcopy(DEFAULT); cfg.update(json.loads(imported.getvalue()))
            config_check(cfg)
            st.session_state.cfg=cfg
            for key in list(st.session_state):
                if key.startswith('param_'): del st.session_state[key]
            st.rerun()
        except Exception as exc: st.error(str(exc))
    cfg=copy.deepcopy(st.session_state.cfg)
    cfg['journal']=st.text_input('Journal des factures',cfg['journal'],key='param_journal')
    cfg['journal_lib']=st.text_input('Libellé du journal',cfg['journal_lib'],key='param_journal_lib')
    cfg['aux']=st.text_input('Compte auxiliaire (facultatif)',cfg['aux'],key='param_aux')
    cfg['aux_lib']=st.text_input('Nom du tiers',cfg['aux_lib'],key='param_aux_lib')
    st.caption('L’auxiliaire, s’il est renseigné, est appliqué aux lignes 401 / 411.')
    cfg['merge_statement']=st.checkbox('Joindre aussi le relevé au PDF de la facture',value=cfg['merge_statement'],key='param_merge')
    cfg['adjustments']=st.checkbox('Générer les ajustements hors facture',value=cfg['adjustments'],key='param_adjustments')
    if cfg['adjustments']:
        st.info('Remboursements et paiements supplémentaires uniquement. Les commissions déjà dans la facture sont exclues. Aucune TVA de vente n’est déduite du relevé.')
        cfg['adjust_journal']=st.text_input('Journal des ajustements',cfg['adjust_journal'],key='param_adjust_journal')
        cfg['adjust_account']=st.text_input('Compte des ajustements à qualifier',cfg['adjust_account'],key='param_adjust_account')
        cfg['clearing_account']=st.text_input('Compte de liaison Deliveroo',cfg['clearing_account'],key='param_clearing')
        st.caption('Paiement supplémentaire : débit liaison / crédit ajustement. Remboursement : sens inverse. Adapter le traitement au dossier ; 471 proposé pour qualification.')

with st.expander('Schéma des factures — comptes, bases et sens',expanded=True):
    schema=st.data_editor(pd.DataFrame(cfg['schema']),num_rows='dynamic',hide_index=True,width='stretch',key='param_schema',column_config={
        'Base':st.column_config.SelectboxColumn(options=['HT','TVA','TTC'],required=True),
        'Sens':st.column_config.SelectboxColumn(options=['Débit','Crédit'],required=True),
        'Compte':st.column_config.TextColumn(required=True),
        'Libellé':st.column_config.TextColumn(required=True)})
    cfg['schema']=schema.fillna('').to_dict('records')
    st.caption('Les comptes alphanumériques sont acceptés. Les montants négatifs inversent automatiquement débit et crédit. Chaque facture doit rester équilibrée.')
st.sidebar.download_button('Enregistrer le paramétrage',json.dumps(cfg,ensure_ascii=False,indent=2).encode('utf-8'),'parametrage_deliveroo.json','application/json')

uploads=st.file_uploader('Dépose les ZIP téléchargés sur Deliveroo',type=['zip'],accept_multiple_files=True)
if not uploads:
    st.info('Ajoute un ou plusieurs ZIP. Le modèle reconnu contient *_invoice.pdf, *_statement.pdf et *_statement.csv.')
    st.markdown('**Export :** FEC à 18 colonnes, dates AAAAMMJJ, montants à deux décimales, et PDF nommés comme les références de pièces.')
    st.stop()
blobs=tuple((f.name,f.getvalue()) for f in uploads)
fingerprint=hashlib.sha256(b''.join(hashlib.sha256(b).digest() for _,b in blobs)).hexdigest()[:16]
with st.spinner('Lecture des factures et contrôle des relevés…'):
    invoices,errors,notices=analyse(blobs)
for note in notices: st.info(note)
if errors:
    st.error('Certains fichiers n’ont pas pu être lus. Ils ne sont pas intégrés aux écritures.')
    st.dataframe(pd.DataFrame(errors),hide_index=True,width='stretch')
if not invoices: st.stop()

c1,c2,c3=st.columns(3)
c1.metric('Factures reconnues',len(invoices))
c2.metric('Total HT source',f"{sum(money(i['HT']) for i in invoices):,.2f} €")
c3.metric('Total TTC source',f"{sum(money(i['TTC']) for i in invoices):,.2f} €")
review,details,export=st.tabs(['1 · Contrôle et corrections','2 · Relevés et justificatifs','3 · Export Pennylane'])
with review:
    st.write('Tu peux exclure une facture ou corriger la date et les montants. La référence reste liée au PDF source.')
    view=pd.DataFrame([{k:i[k] for k in ['Inclure','Référence','Date','HT','TVA','TTC','Contrôle','Source']} for i in invoices])
    view['Date']=pd.to_datetime(view['Date']).dt.date
    for col in ['HT','TVA','TTC']: view[col]=view[col].astype(float)
    edited=st.data_editor(view,hide_index=True,width='stretch',key='review_'+fingerprint,disabled=['Référence','Contrôle','Source'],column_config={
        'Date':st.column_config.DateColumn(format='DD/MM/YYYY',required=True),
        **{c:st.column_config.NumberColumn(format='%.2f',required=True,step=.01) for c in ['HT','TVA','TTC']}})
    st.caption('Les contrôles portent sur les documents source. Une correction sera signalée dans CONTROLE.csv, sans modifier le justificatif.')
with details:
    chosen=st.selectbox('Facture',options=[i['Référence'] for i in invoices])
    inv=next(i for i in invoices if i['Référence']==chosen)
    st.download_button('Ouvrir / télécharger la facture source',inv['_pdf'],chosen+'.pdf','application/pdf')
    if inv['_statement']: st.download_button('Télécharger le relevé source',inv['_statement'],chosen+'-releve.pdf','application/pdf')
    if inv['_summary']:
        s=inv['_summary']; st.write({'Ventes TTC (non comptabilisées)':str(s['sales']),'Versement attendu (non comptabilisé)':str(s['payout']),'CSV contrôlé':s['csv_ok']})
        if s['adjustments']: st.dataframe(pd.DataFrame(s['adjustments']),hide_index=True,width='stretch')
    st.info('La ventilation de TVA des ventes n’est pas fournie par ces documents. Les ventes, virements et règlements fournisseurs ne sont donc pas générés automatiquement.')
with export:
    if errors and not st.checkbox('Exporter uniquement les factures reconnues malgré les fichiers rejetés',key='errors_'+fingerprint): st.stop()
    selected=edited[edited['Inclure']==True]
    if any(selected['Contrôle']!='OK'):
        st.warning('Des contrôles source sont incomplets ou en anomalie. Vérifie les PDF avant de poursuivre.')
        if not st.checkbox('J’ai vérifié les factures sélectionnées présentant une anomalie',key='anomalies_'+fingerprint): st.stop()
    try:
        rows,fec,pj,pack,controls=build(invoices,edited.to_dict('records'),cfg)
    except Exception as exc:
        st.error('À corriger avant export : '+str(exc)); st.stop()
    total=sum((money(r['Debit']) for r in rows),money(0))
    st.success(f'{len(controls)} factures · {len(rows)} lignes · Débit = Crédit = {total:.2f} € · toutes les écritures ont leur PDF')
    st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    a,b,c=st.columns(3)
    a.download_button('FEC seul',fec,'DELIVEROO_FEC.txt','text/plain')
    b.download_button('ZIP des pièces jointes',pj,'PIECES_JOINTES.zip','application/zip')
    c.download_button('Tout télécharger',pack,'DELIVEROO_PENNYLANE.zip','application/zip',type='primary')
    st.markdown('1. Dans Pennylane : **Saisie comptable → Imports → Importer un fichier → FEC**.\n2. Importe **DELIVEROO_FEC.txt** et vérifie les comptes proposés.\n3. Sur cet import, clique sur le **trombone / Joindre une archive**, puis charge **PIECES_JOINTES.zip**.')
    st.caption('Le ZIP global est un dossier de livraison à décompresser. Il contient le FEC, le ZIP des PJ et le contrôle CSV. Écritures partielles d’import, pas un FEC fiscal complet. Évite de réimporter une facture déjà comptabilisée.')
    st.markdown('[Documentation Pennylane — import et rattachement des justificatifs](https://help.pennylane.com/fr/articles/18792-importer-un-fec)')
