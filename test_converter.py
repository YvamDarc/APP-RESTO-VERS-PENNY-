import copy
import io
import os
from pathlib import Path
import sys
import unittest
import zipfile
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from converter import DEFAULT, FIELDS, build, load_archives, money, csv_rows
from pypdf import PdfReader

class UnitTests(unittest.TestCase):
 def test_money(self):
  self.assertEqual(money('1 234,56'),Decimal('1234.56'))
  self.assertEqual(money('-16,50'),Decimal('-16.50'))
  with self.assertRaises(ValueError): money('NaN')
 def test_multiline_csv(self):
  blob='Orders\nNom du restaurant,Numéro de commande,Date et heure de livraison (UTC),Historique,a,b,c,d,e,f,g,Note\nR,12,2026-06-15 12:00:00,Livraison,"12,00",,,"-3,60",20,"-0,72","7,68","note\nsuite"\n'.encode()
  self.assertEqual(len(csv_rows(blob)),1)
 def test_unsafe_archive(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z: z.writestr('../invoice.pdf',b'fake')
  inv,errors,_=load_archives([('unsafe.zip',b.getvalue())])
  self.assertFalse(inv); self.assertTrue(errors)

@unittest.skipUnless(os.getenv('DELIVEROO_TEST_INPUTS'),'Archives réelles non fournies')
class RealArchives(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.uploads=[(p.name,p.read_bytes()) for p in Path(os.environ['DELIVEROO_TEST_INPUTS']).glob('*.zip')]
  cls.inv,cls.errors,_=load_archives(cls.uploads)
 def test_expected_totals(self):
  self.assertFalse(self.errors); self.assertEqual(len(self.inv),4)
  self.assertTrue(all(x['Contrôle']=='OK' for x in self.inv))
  self.assertEqual(sum(money(i['HT']) for i in self.inv),Decimal('546.61'))
  self.assertEqual(sum(money(i['TVA']) for i in self.inv),Decimal('109.33'))
 def test_exports_and_attachments(self):
  rows,fec,pj,pack,control=build(self.inv,self.inv,DEFAULT)
  self.assertEqual(len(rows),12)
  self.assertEqual(fec.decode('utf-8-sig').splitlines()[0].split('\t'),FIELDS)
  self.assertEqual(sum(money(r['Debit']) for r in rows),Decimal('655.94'))
  for ref in {r['EcritureNum'] for r in rows}:
   self.assertEqual(sum(money(r['Debit'])-money(r['Credit']) for r in rows if r['EcritureNum']==ref),0)
  with zipfile.ZipFile(io.BytesIO(pj)) as z:
   self.assertEqual(set(z.namelist()),{r['PieceRef']+'.pdf' for r in rows})
   for i in self.inv:
    pdf=PdfReader(io.BytesIO(z.read(i['Référence']+'.pdf')))
    expected=len(PdfReader(io.BytesIO(i['_pdf'])).pages)+len(PdfReader(io.BytesIO(i['_statement'])).pages)
    self.assertEqual(len(pdf.pages),expected)
  with zipfile.ZipFile(io.BytesIO(pack)) as z:
   self.assertEqual(z.read('DELIVEROO_FEC.txt'),fec)
   self.assertEqual(z.read('PIECES_JOINTES.zip'),pj)
 def test_duplicate(self):
  inv,errors,notes=load_archives(self.uploads*2)
  self.assertEqual(len(inv),4); self.assertFalse(errors); self.assertEqual(len(notes),4)
 def test_adjustments(self):
  cfg=copy.deepcopy(DEFAULT); cfg['adjustments']=True
  rows,_,pj,_,_=build(self.inv,self.inv,cfg)
  self.assertEqual(len(rows),18)
  self.assertEqual(sum(money(r['Debit']) for r in rows),Decimal('694.94'))
  self.assertEqual(sum(money(r['Debit'])-money(r['Credit']) for r in rows if r['CompteNum']=='471000'),Decimal('15.00'))
 def test_invalid_correction_and_schema(self):
  edited=copy.deepcopy(self.inv); edited[0]['HT']='999'
  with self.assertRaises(ValueError): build(self.inv,edited,DEFAULT)
  cfg=copy.deepcopy(DEFAULT); cfg['schema'][2]['Sens']='Débit'
  with self.assertRaises(ValueError): build(self.inv,self.inv,cfg)
 def test_configurable_counterparty_and_original_pdf(self):
  cfg=copy.deepcopy(DEFAULT);cfg['schema'][2]['Compte']='467DELIVEROO';cfg['merge_statement']=False
  rows,_,pj,_,_=build(self.inv,self.inv,cfg)
  self.assertTrue(any(r['CompteNum']=='467DELIVEROO' for r in rows))
  with zipfile.ZipFile(io.BytesIO(pj)) as z:
   for inv in self.inv: self.assertEqual(z.read(inv['Référence']+'.pdf'),inv['_pdf'])
 def test_exclusion(self):
  edited=copy.deepcopy(self.inv); edited[0]['Inclure']=False
  rows,_,pj,_,_=build(self.inv,edited,DEFAULT)
  self.assertEqual(len(rows),9)
  with zipfile.ZipFile(io.BytesIO(pj)) as z: self.assertEqual(len(z.namelist()),3)

if __name__=='__main__': unittest.main()
