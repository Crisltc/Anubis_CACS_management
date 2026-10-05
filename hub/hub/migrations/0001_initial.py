"""
Schéma initial du Hub.

Migration UNIQUE : le schéma décrit dans docs/ est l'état de départ, il n'y a
pas d'historique de migrations à rejouer. Les suivantes s'ajouteront
normalement avec `makemigrations`.

Elle crée aussi la page wiki `faq` : la barre de navigation pointe vers
/wiki/faq/, cette page DOIT donc exister dès le premier démarrage.
"""

import django.db.models.deletion
import hub.models
from decimal import Decimal
from django.db import migrations, models


FAQ_CONTENT = """## Questions fréquentes

Cette page est un wiki comme les autres : **complète-la** dès qu'une question
revient deux fois.

### Je ne trouve pas un composant dans le local
Cherche-le dans le [catalogue](/stock/) : sa fiche indique l'emplacement.
S'il n'y est pas, ajoute-le — c'est trente secondes.

### J'ai pris des composants, que dois-je faire ?
[Sortie rapide](/stock/sortie/) : cherche, tape la quantité, valide. Le stock
est la somme des mouvements, donc il se met à jour tout seul.

### Le stock affiché ne correspond pas au bac
Ouvre la fiche du composant → « Corriger l'inventaire ». Un mouvement
d'ajustement est ajouté ; on ne réécrit jamais l'historique, on le prolonge.

### Comment savoir si on peut monter N cartes ?
Page de la carte → **Faisabilité**. Le bouton « Liste d'achat (CSV) » donne
les manquants groupés par fournisseur.
"""


def create_faq(apps, schema_editor):
    """La navigation pointe vers /wiki/faq/ : la page doit exister."""
    WikiPage = apps.get_model("hub", "WikiPage")
    WikiPage.objects.get_or_create(
        slug="faq", defaults={"title": "FAQ", "content_md": FAQ_CONTENT})


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Board',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, verbose_name='nom')),
                ('status', models.CharField(choices=[('conception', 'Conception'), ('routage', 'Routage'), ('fabrication', 'Fabrication'), ('assemblage', 'Assemblage'), ('test', 'Test'), ('integration', 'Intégration'), ('vol', 'Vol'), ('resultat', 'Résultat')], default='conception', max_length=15, verbose_name='étape')),
                ('manager', models.CharField(blank=True, max_length=60, verbose_name='responsable')),
                ('target_date', models.DateField(blank=True, null=True, verbose_name='date cible')),
                ('notes', models.TextField(blank=True, verbose_name='notes (Markdown)')),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['project', 'name'],
            },
        ),
        migrations.CreateModel(
            name='ColumnProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True, verbose_name='nom')),
                ('mapping', models.JSONField(default=dict)),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True, verbose_name='emplacement')),
                ('note', models.CharField(blank=True, max_length=120, verbose_name='précision')),
            ],
            options={
                'verbose_name': 'emplacement',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(blank=True, unique=True)),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='nom')),
                ('description', models.TextField(blank=True, verbose_name='description (Markdown)')),
                ('team', models.TextField(blank=True, help_text='Un nom par ligne, ou séparés par des virgules.', verbose_name='équipe')),
                ('campaign_year', models.CharField(blank=True, help_text='Ex. « 2026-2027 » — sert au classement des archives.', max_length=20, verbose_name='campagne')),
                ('status', models.CharField(choices=[('actif', 'Actif'), ('archive', 'Archivé')], default='actif', max_length=10)),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['status', '-created'],
            },
        ),
        migrations.CreateModel(
            name='WikiPage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(blank=True, unique=True)),
                ('title', models.CharField(max_length=200, unique=True, verbose_name='titre')),
                ('content_md', models.TextField(blank=True, verbose_name='contenu (Markdown)')),
                ('pdf', models.FileField(blank=True, upload_to='wiki/', verbose_name='PDF intégré')),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['title'],
            },
        ),
        migrations.CreateModel(
            name='BomImport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('filename', models.CharField(max_length=200)),
                ('headers', models.JSONField(default=list)),
                ('raw_rows', models.JSONField(default=list)),
                ('status', models.CharField(choices=[('mapping', 'Colonnes à mapper'), ('matching', 'Rapprochement en cours'), ('done', 'Nomenclature enregistrée')], default='mapping', max_length=10)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.CharField(max_length=60)),
                ('board', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bom_imports', to='hub.board')),
                ('profile', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='hub.columnprofile')),
            ],
            options={
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='BomImportLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('row_index', models.PositiveIntegerField()),
                ('designators', models.CharField(blank=True, max_length=300)),
                ('qty', models.DecimalField(decimal_places=2, default=Decimal('1'), max_digits=12)),
                ('value', models.CharField(blank=True, max_length=80)),
                ('package', models.CharField(blank=True, max_length=40)),
                ('mpn', models.CharField(blank=True, max_length=120)),
                ('manufacturer', models.CharField(blank=True, max_length=120)),
                ('lcsc', models.CharField(blank=True, max_length=40, verbose_name='réf fournisseur')),
                ('dnp', models.BooleanField(default=False, verbose_name='non monté (DNP)')),
                ('status', models.CharField(choices=[('auto', 'Validée automatiquement'), ('review', 'À arbitrer'), ('nomatch', 'Sans correspondance'), ('ignored', 'Ignorée')], default='review', max_length=10)),
                ('matched_score', models.PositiveIntegerField(default=0)),
                ('matched_reason', models.CharField(blank=True, max_length=200)),
                ('bom_import', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='hub.bomimport')),
            ],
            options={
                'ordering': ['row_index'],
            },
        ),
        migrations.CreateModel(
            name='Part',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Convention : « RES 10k 0603 1% » pour les passifs, le MPN pour les actifs.', max_length=140, unique=True, verbose_name='nom')),
                ('category', models.CharField(choices=[('resistance', 'Résistance'), ('condensateur', 'Condensateur'), ('inductance', 'Inductance'), ('diode', 'Diode / LED'), ('transistor', 'Transistor / MOSFET'), ('ci', 'Circuit intégré'), ('connecteur', 'Connecteur'), ('module', 'Module'), ('mecanique', 'Mécanique / visserie'), ('autre', 'Autre')], default='autre', max_length=14, verbose_name='catégorie')),
                ('value', models.CharField(blank=True, max_length=40, verbose_name='valeur')),
                ('package', models.CharField(blank=True, max_length=40, verbose_name='boîtier')),
                ('mpn', models.CharField(blank=True, max_length=120, verbose_name='réf fabricant (MPN)')),
                ('manufacturer', models.CharField(blank=True, max_length=80, verbose_name='fabricant')),
                ('min_qty', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=12, verbose_name="seuil d'alerte")),
                ('supplier', models.CharField(blank=True, help_text='LCSC, Mouser, RS, Würth…', max_length=60, verbose_name='fournisseur')),
                ('sku', models.CharField(blank=True, max_length=60, verbose_name='réf fournisseur')),
                ('supplier_url', models.URLField(blank=True, verbose_name='page produit')),
                ('unit_price', models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True, verbose_name='prix unitaire (EUR)')),
                ('datasheet_url', models.URLField(blank=True, verbose_name='datasheet')),
                ('datasheet_pdf', models.FileField(blank=True, upload_to='datasheets/', verbose_name='datasheet (PDF)')),
                ('photo', models.FileField(blank=True, upload_to='composants/')),
                ('notes', models.TextField(blank=True, verbose_name='notes')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='parts', to='hub.location')),
            ],
            options={
                'verbose_name': 'composant',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Movement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('delta', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='quantité (signée)')),
                ('kind', models.CharField(choices=[('entree', 'Entrée'), ('sortie', 'Sortie'), ('inventaire', "Correction d'inventaire")], default='sortie', max_length=10, verbose_name='type')),
                ('author', models.CharField(max_length=60, verbose_name='par')),
                ('reason', models.CharField(blank=True, max_length=200, verbose_name='motif')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('board', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='movements', to='hub.board')),
                ('part', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movements', to='hub.part')),
            ],
            options={
                'verbose_name': 'mouvement',
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='MatchCandidate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.PositiveIntegerField()),
                ('reason', models.CharField(max_length=200)),
                ('line', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='candidates', to='hub.bomimportline')),
                ('part', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='hub.part')),
            ],
            options={
                'ordering': ['-score'],
            },
        ),
        migrations.AddField(
            model_name='bomimportline',
            name='matched_part',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='hub.part'),
        ),
        migrations.CreateModel(
            name='Post',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('author', models.CharField(max_length=60, verbose_name='auteur')),
                ('text_md', models.TextField(blank=True, verbose_name='texte (Markdown)')),
                ('stage', models.CharField(blank=True, choices=[('conception', 'Conception'), ('routage', 'Routage'), ('fabrication', 'Fabrication'), ('assemblage', 'Assemblage'), ('test', 'Test'), ('integration', 'Intégration'), ('vol', 'Vol'), ('resultat', 'Résultat')], max_length=15, verbose_name='étape')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('board', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='posts', to='hub.board')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='posts', to='hub.project')),
            ],
            options={
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='Photo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.FileField(upload_to=hub.models.photo_path)),
                ('thumb', models.FileField(upload_to=hub.models.photo_path)),
                ('caption', models.CharField(blank=True, max_length=200, verbose_name='légende')),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='hub.post')),
            ],
        ),
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('author', models.CharField(max_length=60, verbose_name='auteur')),
                ('text', models.TextField(verbose_name='commentaire')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='hub.post')),
            ],
            options={
                'ordering': ['created'],
            },
        ),
        migrations.CreateModel(
            name='Document',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200, verbose_name='titre')),
                ('doc_type', models.CharField(choices=[('rce', 'Rapport RCE'), ('final', 'Rapport final'), ('passation', 'Passation'), ('procedure', 'Procédure / Tuto'), ('datasheet', 'Datasheets'), ('autre', 'Autre')], default='final', max_length=12, verbose_name='type')),
                ('authors', models.CharField(blank=True, max_length=200, verbose_name='auteur·e·s')),
                ('date', models.DateField(blank=True, null=True, verbose_name='date du document')),
                ('pdf', models.FileField(upload_to='documents/')),
                ('source_zip', models.FileField(blank=True, null=True, upload_to='documents/')),
                ('thumb', models.FileField(blank=True, null=True, upload_to='documents/')),
                ('text_content', models.TextField(blank=True, editable=False)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.CharField(max_length=60)),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documents', to='hub.project')),
            ],
            options={
                'ordering': ['-date', '-created'],
            },
        ),
        migrations.AddField(
            model_name='board',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='boards', to='hub.project'),
        ),
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200, verbose_name='titre')),
                ('column', models.CharField(choices=[('todo', 'À faire'), ('doing', 'En cours'), ('blocked', 'Bloqué'), ('done', 'Fait')], default='todo', max_length=10)),
                ('assignee', models.CharField(blank=True, max_length=60, verbose_name='qui')),
                ('target_date', models.DateField(blank=True, null=True, verbose_name='pour le')),
                ('position', models.PositiveIntegerField(default=0)),
                ('board', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='hub.board')),
            ],
            options={
                'ordering': ['column', 'position', 'id'],
            },
        ),
        migrations.CreateModel(
            name='WikiRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_md', models.TextField()),
                ('author', models.CharField(max_length=60)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='revisions', to='hub.wikipage')),
            ],
            options={
                'ordering': ['-created'],
            },
        ),
        migrations.CreateModel(
            name='BoardStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stage', models.CharField(choices=[('conception', 'Conception'), ('routage', 'Routage'), ('fabrication', 'Fabrication'), ('assemblage', 'Assemblage'), ('test', 'Test'), ('integration', 'Intégration'), ('vol', 'Vol'), ('resultat', 'Résultat')], max_length=15, verbose_name='étape')),
                ('notes', models.TextField(blank=True, verbose_name='notes (Markdown)')),
                ('non_applicable', models.BooleanField(default=False, verbose_name='non applicable')),
                ('na_reason', models.CharField(blank=True, max_length=200, verbose_name='raison')),
                ('board', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stages', to='hub.board')),
            ],
            options={
                'unique_together': {('board', 'stage')},
            },
        ),
        migrations.CreateModel(
            name='BomLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qty', models.DecimalField(decimal_places=2, default=Decimal('1'), max_digits=12, verbose_name='quantité par carte')),
                ('designators', models.CharField(blank=True, max_length=300)),
                ('board', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bom_lines', to='hub.board')),
                ('part', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bom_lines', to='hub.part')),
            ],
            options={
                'ordering': ['designators', 'id'],
                'unique_together': {('board', 'part')},
            },
        ),
        migrations.AlterUniqueTogether(
            name='board',
            unique_together={('project', 'name')},
        ),
        migrations.RunPython(create_faq, migrations.RunPython.noop),
    ]
