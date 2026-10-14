"""Deliveroo FR -> écritures d'import FEC + justificatifs Pennylane."""
import csv
import hashlib
import io
import re
import zipfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import PurePosixPath
import pdfplumber
from pypdf import PdfReader, PdfWriter

FIELDS = 'JournalCode JournalLib EcritureNum EcritureDate CompteNum CompteLib CompAuxNum CompAuxLib PieceRef PieceDate EcritureLib Debit Credit EcritureLet DateLet ValidDate Montantdevise Idevise'.split()
DEFAULT = {
 'journal':'AC', 'journal_lib':'Achats Deliveroo', 'aux':'', 'aux_lib':'Deliveroo',
 'schema':[
  {'Base':'HT','Sens':'Débit','Compte':'622200','Libellé':'Commissions Deliveroo'},
  {'Base':'TVA','Sens':'Débit','Compte':'445660','Libellé':'TVA déductible 20 %'},
  {'Base':'TTC','Sens':'Crédit','Compte':'401DELIVEROO','Libellé':'Deliveroo'}],
 'adjustments':False, 'adjust_account':'471000', 'clearing_account':'467DELIVEROO',
 'adjust_journal':'OD', 'merge_statement':True,
}
MONEY = r'-?\d[\d\s\u00a0\u202f]*[,.]\d{2}'
MONTHS = {'janv':1,'janvier':1,'févr':2,'février':2,'mars':3,'avr':4,'avril':4,'mai':5,'juin':6,'juil':7,'juillet':7,'août':8,'sept':9,'septembre':9,'oct':10,'octobre':10,'nov':11,'novembre':11,'déc':12,'décembre':12}

def money(v):
 s = re.sub(r'[\s€\u200b]', '', str(v)).replace(',', '.')
 if not s or s in ('—','-'): return Decimal('0.00')
 d=Decimal(s)
 if not d.is_finite(): raise ValueError('Montant non numérique')
 return d.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)

def pdf_text(data):
 with pdfplumber.open(io.BytesIO(data)) as p:
  return '\n'.join(page.extract_text() or '' for page in p.pages).replace('\u200b','')

def ref_date(text):
 r=re.search(r'(?:Facture n°|Facture correspondante)\s*:\s*([A-Za-z0-9_-]+)',text)
 d=re.search(r"Date d'émission\s*:\s*\w+,?\s*(\d{1,2})\s+([\w]+)\.?\s+(\d{4})",text)
 if not r or not d: raise ValueError('Référence ou date non reconnue dans le PDF')
 return r[1], date(int(d[3]),MONTHS[d[2].lower()],int(d[1])).isoformat()

def parse_invoice(data):
 t=pdf_text(data)
 if 'Facture de TVA' not in t: raise ValueError('PDF non reconnu comme facture Deliveroo FR')
 ref,day=ref_date(t)
 m=re.search(r'Montant TTC\s+€\s*('+MONEY+r')\s+€\s*('+MONEY+r')\s+€\s*('+MONEY+r')',t)
 if not m: raise ValueError('Total HT / TVA / TTC non reconnu (PDF scanné ou autre modèle)')
 ht,tva,ttc=map(money,m.groups())
 if ht+tva!=ttc: raise ValueError('Total PDF incohérent : HT + TVA ≠ TTC')
 return {'Référence':ref,'Date':day,'HT':str(ht),'TVA':str(tva),'TTC':str(ttc)}

def csv_rows(data):
 text=data.decode('utf-8-sig')
 rows=[]
 for row in csv.reader(io.StringIO(text)):
  if not row or len(row)<11 or row[0]=='Nom du restaurant': continue
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2}.*',row[2]):
   raise ValueError('Ligne CSV non reconnue : '+str(row[:4]))
  rows.append(row)
 if not rows: raise ValueError('CSV sans lignes de commandes reconnues')
 return rows

def parse_statement(data, csv_data=None):
 t=pdf_text(data); ref,day=ref_date(t)
 def euro_line(label):
  line=next((x for x in t.splitlines() if x.startswith(label)),None)
  if line is None: raise ValueError('Relevé : rubrique absente '+label)
  vals=re.findall(r'€\s*('+MONEY+r')',line)
  if not vals: raise ValueError('Relevé : montant illisible '+label)
  return money(vals[-1])
 sales=euro_line('Montant total de la commande TTC')
 payout=euro_line('Montant total à payer à ')
 net=euro_line('Montant net facturable par Deliveroo')
 if sales+net!=payout: raise ValueError('Relevé : versement incohérent')
 result={'ref':ref,'date':day,'sales':sales,'payout':payout,'net':net,'csv_ok':False,'adjustments':[]}
 if csv_data is not None:
  rows=csv_rows(csv_data)
  if sum((money(x[10]) for x in rows),Decimal(0))!=payout:
   raise ValueError('Somme du CSV différente du versement du relevé')
  commission=Decimal(0); tax=Decimal(0); adj=[]
  for row in rows:
   kind=row[3]; commission-=money(row[7]); tax-=money(row[9])
   if kind in ('Livraison','À emporter'):
    if money(row[5])!=0: raise ValueError('Ajustement sur une commande : contrôler manuellement')
   elif kind.startswith('Commission Deliveroo'):
    commission-=money(row[5])
   else:
    if money(row[9])!=0: raise ValueError('Ajustement avec TVA non pris en charge : '+kind)
    adj.append({'Libellé':kind,'Montant':str(money(row[10])),'Commande':row[1]})
  result.update(csv_ok=True, invoice_ht=commission,invoice_tax=tax,adjustments=adj)
 return result

def load_archives(uploads):
 """All processing in memory; no archive path is extracted to disk."""
 invoices=[]; errors=[]; notices=[]; seen={}; expanded=0
 for zip_name,blob in uploads:
  try:
   with zipfile.ZipFile(io.BytesIO(blob)) as z:
    if len(z.infolist())>5000: raise ValueError('Archive trop volumineuse (> 5 000 entrées)')
    members={}
    for info in z.infolist():
     if info.is_dir(): continue
     p=PurePosixPath(info.filename)
     if '..' in p.parts or p.is_absolute(): raise ValueError('Chemin ZIP non autorisé')
     if info.filename in members: raise ValueError('Nom de fichier répété dans le ZIP')
     expanded+=info.file_size
     if expanded>250*1024**2 or info.file_size>30*1024**2: raise ValueError('Limite de lecture dépassée (30 Mo/fichier, 250 Mo au total)')
     members[info.filename]=info
    candidates=[n for n in members if n.lower().endswith('_invoice.pdf')]
    if not candidates: errors.append({'Source':zip_name,'Erreur':'Aucun fichier *_invoice.pdf reconnu'})
    for name in candidates:
     try:
      raw=z.read(name); inv=parse_invoice(raw); ref=inv['Référence']
      digest=hashlib.sha256(raw).hexdigest()
      if ref in seen:
       if seen[ref]==digest: notices.append('Doublon ignoré : '+ref); continue
       raise ValueError('Même référence avec un PDF différent : '+ref)
      stem=name[:-len('_invoice.pdf')]
      sp=stem+'_statement.pdf'; sc=stem+'_statement.csv'
      statement=z.read(sp) if sp in members else None
      csv_data=z.read(sc) if sc in members else None
      checks=[]; summary=None
      if statement:
       try:
        summary=parse_statement(statement,csv_data)
        if summary['ref']!=ref or summary['date']!=inv['Date']: raise ValueError('Relevé associé à une autre facture/date')
        if summary['csv_ok']:
         if summary['invoice_ht']!=money(inv['HT']) or summary['invoice_tax']!=money(inv['TVA']): raise ValueError('Commissions CSV différentes du total facturé')
         adjustments=sum((money(a['Montant']) for a in summary['adjustments']),Decimal(0))
         if summary['sales']-money(inv['TTC'])+adjustments!=summary['payout']: raise ValueError('Ventes - facture + ajustements ≠ versement')
        else: checks.append('CSV absent : contrôle détaillé indisponible')
       except Exception as exc:
        checks.append(str(exc)); summary=None
      else: checks.append('Relevé PDF absent')
      inv.update({'Inclure':True,'Source':zip_name+' / '+name,'Contrôle':'OK' if not checks else ' ; '.join(checks),
                  '_pdf':raw,'_statement':statement,'_summary':summary,'_hash':digest})
      seen[ref]=digest; invoices.append(inv)
     except Exception as exc: errors.append({'Source':zip_name+' / '+name,'Erreur':str(exc)})
  except Exception as exc: errors.append({'Source':zip_name,'Erreur':str(exc)})
 return sorted(invoices,key=lambda x:(x['Date'],x['Référence'])), errors, notices

def clean(value):
 return re.sub(r'[\t\r\n;]+',' ',str(value)).strip()

def config_check(cfg):
 for name in ['journal','adjust_journal']:
  if not re.fullmatch(r'[A-Za-z0-9]+',str(cfg.get(name,''))): raise ValueError('Code journal alphanumérique requis : '+name)
 if not cfg.get('schema'): raise ValueError('Schéma comptable vide')
 for row in cfg['schema']:
  if row.get('Base') not in ['HT','TVA','TTC'] or row.get('Sens') not in ['Débit','Crédit']: raise ValueError('Base/sens du schéma non valide')
  if not re.fullmatch(r'[A-Za-z0-9]+',str(row.get('Compte',''))): raise ValueError('Compte alphanumérique requis')
  if not clean(row.get('Libellé','')): raise ValueError('Libellé de compte obligatoire')
 for k in ['adjust_account','clearing_account']:
  if not re.fullmatch(r'[A-Za-z0-9]+',str(cfg.get(k,''))): raise ValueError('Compte alphanumérique requis : '+k)
 if cfg.get('aux') and not re.fullmatch(r'[A-Za-z0-9]+',cfg['aux']): raise ValueError('Auxiliaire alphanumérique requis')

def fec_bytes(rows):
 out=io.StringIO(newline=''); w=csv.DictWriter(out,FIELDS,delimiter='\t',lineterminator='\r\n'); w.writeheader(); w.writerows(rows)
 return out.getvalue().encode('utf-8-sig')

def zip_bytes(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items(): z.writestr(name,data)
 return out.getvalue()

def build(invoices, edited, cfg):
 config_check(cfg)
 original={i['Référence']:i for i in invoices}; rows=[]; attachments={}; controls=[]; used=set()
 def add_group(inv,ref,group,journal,journal_lib,entries):
  if not entries: return
  if sum((v for _,_,v in entries),Decimal(0))!=0: raise ValueError('Écriture déséquilibrée : '+ref+' / '+group)
  day=date.fromisoformat(str(inv['Date'])).strftime('%Y%m%d')
  for account,label,amount in entries:
   if amount==0: continue
   aux=cfg.get('aux','') if account.startswith(('401','411')) else ''
   r=dict.fromkeys(FIELDS,''); r.update(JournalCode=journal,JournalLib=clean(journal_lib),EcritureNum=ref+'-'+group,EcritureDate=day,
    CompteNum=account,CompteLib=clean(label),CompAuxNum=aux,CompAuxLib=clean(cfg.get('aux_lib','')) if aux else '',
    PieceRef=ref,PieceDate=day,EcritureLib=clean('Deliveroo '+ref+' '+group),Debit=f'{max(amount,Decimal(0)):.2f}'.replace('.',','),Credit=f'{max(-amount,Decimal(0)):.2f}'.replace('.',','))
   rows.append(r)
 for record in edited:
  if not record.get('Inclure',True): continue
  ref=record['Référence']
  if ref in used: raise ValueError('Référence répétée : '+ref)
  used.add(ref); inv=original[ref]
  if not re.fullmatch(r'[A-Za-z0-9_-]+',ref): raise ValueError('Référence PDF non sûre')
  vals={k:money(record[k]) for k in ['HT','TVA','TTC']}
  if vals['HT']+vals['TVA']!=vals['TTC']: raise ValueError(ref+' : HT + TVA ≠ TTC')
  if vals['TTC']==0: raise ValueError(ref+' : facture nulle')
  entries=[(r['Compte'],r['Libellé'],vals[r['Base']]*(1 if r['Sens']=='Débit' else -1)) for r in cfg['schema']]
  add_group(record,ref,'FAC',cfg['journal'],cfg['journal_lib'],entries)
  data=inv['_pdf']
  if cfg.get('merge_statement') and inv['_statement']:
   writer=PdfWriter()
   for part in [data,inv['_statement']]: writer.append(PdfReader(io.BytesIO(part)))
   buffer=io.BytesIO(); writer.write(buffer); data=buffer.getvalue()
  attachments[ref+'.pdf']=data
  summary=inv['_summary']
  if cfg.get('adjustments'):
   if not summary or not summary['csv_ok']: raise ValueError(ref+' : CSV/relevé contrôlés indispensables aux ajustements')
   adjref=ref+'-RELEVE'; entries=[]
   for a in summary['adjustments']:
    amount=money(a['Montant'])
    entries.extend([(cfg['clearing_account'],'Deliveroo - compte de liaison',amount),(cfg['adjust_account'],a['Libellé'],-amount)])
   if any(v for _,_,v in entries):
    add_group(record,adjref,'AJUST',cfg['adjust_journal'],'Ajustements Deliveroo',entries)
    attachments[adjref+'.pdf']=inv['_statement']
  controls.append({'Référence':ref,'Date':str(record['Date']),**{k:str(v) for k,v in vals.items()},'PDF':ref+'.pdf','Contrôle source':inv['Contrôle'],
   'Modifié':any(str(record[k])!=str(inv[k]) for k in ['Date','HT','TVA','TTC']),
   'Ventes TTC (information)':str(summary['sales']) if summary else '', 'Versement attendu (information)':str(summary['payout']) if summary else '',
   'Ajustements hors facture':str(sum((money(a['Montant']) for a in summary['adjustments']),Decimal(0))) if summary and summary['csv_ok'] else ''})
 if not rows: raise ValueError('Aucune écriture sélectionnée')
 if {r['PieceRef']+'.pdf' for r in rows} != set(attachments): raise ValueError('Rattachement PJ incomplet')
 control=io.StringIO(); w=csv.DictWriter(control,fieldnames=list(controls[0]),delimiter=';'); w.writeheader(); w.writerows(controls)
 fec=fec_bytes(rows); pj=zip_bytes(attachments)
 instructions='Importer DELIVEROO_FEC.txt dans Pennylane, puis joindre PIECES_JOINTES.zip via le trombone / Joindre une archive.\nNe pas importer le pack global comme FEC.\nFichier partiel destiné à l’import : ce n’est pas le FEC fiscal complet de l’entreprise.\n'
 pack=zip_bytes({'DELIVEROO_FEC.txt':fec,'PIECES_JOINTES.zip':pj,'CONTROLE.csv':control.getvalue().encode('utf-8-sig'),'IMPORT_PENNYLANE.txt':instructions.encode('utf-8')})
 return rows,fec,pj,pack,controls
