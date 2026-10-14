# Deliveroo → FEC + pièces jointes Pennylane

Application Streamlit à déposer sur GitHub et lancer sur Streamlit Community Cloud.

## Mise en ligne, sans installation sur ton ordinateur

1. Décompresse `Application_Deliveroo_FEC.zip`.
2. Crée un dépôt GitHub (par exemple `deliveroo-fec-pennylane`).
3. Ajoute les fichiers **à la racine** du dépôt, notamment `app.py`, `converter.py` et `requirements.txt` (ne dépose pas seulement le ZIP).
4. Dans Streamlit Community Cloud, crée une application depuis ce dépôt et choisis `app.py` comme fichier principal. Choisis Python **3.12** dans les réglages avancés.
5. Lance l’application et ajoute les ZIP Deliveroo, sans les décompresser.

Les sources de l’application ne contiennent aucune facture client. Les documents importés sont lus en mémoire ; le cache Streamlit conserve temporairement le résultat de lecture sur le serveur de l’application. Choisis les accès à ton application en fonction des dossiers traités.

## Utilisation

- Configure le journal et les comptes dans le schéma. Les comptes peuvent être alphanumériques.
- Le schéma accepte plusieurs lignes, chacune calculée à partir de HT, TVA ou TTC. Aucun code Python à modifier.
- Charge plusieurs ZIP, même avec des sous-dossiers. Les PDF nommés `*_invoice.pdf` sont lus, puis associés à `*_statement.pdf` et `*_statement.csv` dans le même dossier.
- Contrôle ou corrige date et montants dans le tableau. Décoche les factures à exclure.
- Sauvegarde le paramétrage au format JSON pour le recharger à la prochaine utilisation.
- Télécharge le FEC et le ZIP des PJ, ou le pack global contenant les deux et le contrôle CSV.

## Schéma initial (à adapter au dossier)

| Base | Sens | Compte |
|---|---|---|
| Facture HT, frais facturés inclus | Débit | 622200 |
| TVA figurant sur la facture | Débit | 445660 |
| Total facture TTC | Crédit | 401DELIVEROO |

Le montant de TVA est lu sur le PDF, jamais recalculé à 20 % : les arrondis par commande sont conservés. Le compte de TVA doit être adapté si d’autres taux figurent sur de futures factures. Le parseur est prévu pour le modèle français fourni ; il ne ventile pas automatiquement plusieurs taux de TVA ou catégories de charges à l’intérieur d’une facture.

Le règlement du fournisseur par compensation n’est pas généré. Si tu souhaites enregistrer directement les commissions contre un compte de liaison Deliveroo, remplace le compte de la ligne TTC. Les ventes et les versements bancaires restent uniquement des informations de contrôle : les relevés ne fournissent pas leur ventilation de TVA.

### Option : ajustements hors facture

Désactivée au départ. Les lignes hors commissions du CSV (remboursement client, indemnisation de commande annulée, autres ajustements sans TVA de commission) peuvent être exportées dans un journal OD séparé, à la date de la facture.

- Paiement supplémentaire : débit 467DELIVEROO / crédit 471000.
- Remboursement client : débit 471000 / crédit 467DELIVEROO.

Les deux comptes sont modifiables. Le 471 est un compte d’attente à qualifier ; aucune TVA de vente n’est inventée. Vérifie également que ces éléments ne sont pas déjà comptabilisés dans la caisse. Cette option ne constitue pas une comptabilisation complète du relevé. La commission sur commande annulée déjà incluse dans le total de la facture n’est pas comptée deux fois.

## Import dans Pennylane

1. Décompresse le pack global si tu as choisi « Tout télécharger ».
2. Importe **DELIVEROO_FEC.txt** depuis Saisie comptable → Imports → Importer un fichier → FEC.
3. Vérifie la correspondance des journaux et des comptes.
4. Sur l’import, utilise **Joindre une archive / le trombone**, puis charge **PIECES_JOINTES.zip**.

Chaque PDF du ZIP porte exactement la référence `PieceRef` de ses écritures, avec `.pdf` uniquement dans le nom du fichier. Exemple : `res-fr-391805-170.pdf` pour `PieceRef = res-fr-391805-170`.

Par défaut le justificatif est un PDF regroupant la facture puis son relevé ; les pages d’origine sont conservées. Désactive cette option pour joindre uniquement le PDF original de la facture. Les ajustements optionnels disposent de leur propre référence et du relevé PDF associé.

Le pack global n’est pas à envoyer comme FEC. Le fichier produit est un **fichier partiel d’écritures au format FEC pour import**, pas le FEC fiscal exhaustif de l’entreprise. `ValidDate` est laissé vide. Aucune API Pennylane n’est nécessaire.

Documentation vérifiée le 14/10/2026 : https://help.pennylane.com/fr/articles/18792-importer-un-fec

## Contrôles et limites

- 18 colonnes FEC, séparateur tabulation, UTF-8 avec BOM, dates AAAAMMJJ, décimales avec virgule.
- Équilibre contrôlé pour chaque écriture, HT + TVA = TTC, PDF pour chaque référence.
- Doublons identiques supprimés au sein du lot ; même référence avec un PDF différent signalée comme conflit. Pas de mémoire des imports précédents : vérifie les doublons dans Pennylane avant réimport.
- Les CSV sont lus avec un véritable lecteur CSV : les notes sur plusieurs lignes sont conservées.
- Rapprochement des commissions et TVA CSV avec la facture ; contrôle des versements CSV/relevé et de la relation ventes − facture + ajustements = versement.
- Si un contrôle du relevé échoue, l’export des seules factures reste possible après vérification explicite. Les ajustements exigent un relevé/CSV reconnus et contrôlés.
- En cas de fichiers rejetés, ils sont affichés et exclus ; l’utilisateur doit confirmer un export partiel.
- Les modifications manuelles ne changent pas les PDF ; elles sont signalées dans `CONTROLE.csv`. Les contrôles d’extraction portent sur les sources, puis l’équilibre est revérifié sur les données corrigées.
- Les factures sont enregistrées à leur date d’émission. Pas de découpage mensuel automatique des périodes à cheval sur deux mois.
- PDF texte uniquement, pas d’OCR. Autres langues, formats de factures, avoirs avec un autre intitulé : non garantis et signalés si non reconnus.
- ZIP : 30 Mo maximum par fichier, 250 Mo de données décompressées au total, 5 000 entrées par archive. Archives imbriquées non traitées.

## Validation réalisée

Test sur les quatre ZIP transmis : quatre factures, 12 lignes par défaut, total HT 546,61 €, TVA 109,33 €, TTC 655,94 €, sans écart. Avec ajustements activés : 18 lignes, comprenant +12,00 €, −10,50 € et −16,50 € hors facture. Tests supplémentaires : doublons, dates, équilibre par pièce, intégrité des PJ, schéma modifié et données invalides. Aucun import réel dans Pennylane n’a été exécuté.

## Exécution locale (facultative)

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Tests du convertisseur sur les ZIP originaux, sans inclure les documents dans le dépôt :

```bash
python -m unittest discover -s tests
```

Pour ajouter les essais sur les quatre archives de référence : définir `DELIVEROO_TEST_INPUTS` vers leur dossier avant de lancer les tests.
