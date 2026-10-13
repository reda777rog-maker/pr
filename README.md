# Studio de films IA

Une application web qui fabrique un court-métrage complet à partir d'une simple idée :

1. **Scénario.** Claude écrit le film : titre, accroche, découpage en plans, narration,
   description visuelle de chaque plan, mouvement de caméra et palette de couleurs.
2. **Visuels.** Chaque plan est illustré, au choix :
   - **Illustrations animées** : paysages peints par le programme (ville, mer, forêt, montagnes,
     espace) avec mouvements de caméra et particules lumineuses. Gratuit, tout est calculé sur votre machine ;
   - **Images IA** : une image réaliste par plan, générée par un modèle texte→image sur [Replicate](https://replicate.com) ;
   - **Vidéo IA** : un vrai clip vidéo par plan, généré par un modèle texte→vidéo sur Replicate.
3. **Voix off.** La narration est lue par synthèse vocale (gTTS), dans la langue du film.
4. **Montage.** ffmpeg assemble le carton de titre, les plans avec fondus, la voix,
   les sous-titres incrustés et le carton de fin dans un fichier MP4 en 16:9 ou en 9:16.

## Installation

Prérequis : Python 3.10 ou plus récent, et [ffmpeg](https://ffmpeg.org/download.html) installé et
accessible dans le `PATH`.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # puis renseignez vos clés dans .env
```

| Variable | Rôle |
| --- | --- |
| `ANTHROPIC_API_KEY` | **Obligatoire.** Clé de l'API Claude ([console.anthropic.com](https://console.anthropic.com)), utilisée pour écrire le scénario. |
| `REPLICATE_API_TOKEN` | Optionnel. Active les modes « Images IA » et « Vidéo IA ». |
| `REPLICATE_IMAGE_MODEL` | Modèle texte→image (par défaut `black-forest-labs/flux-schnell`). |
| `REPLICATE_VIDEO_MODEL` | Modèle texte→vidéo (par défaut `minimax/video-01`). |
| `CLAUDE_MODEL` | Modèle Claude (par défaut `claude-opus-5-5`). |
| `FILMS_DIR` | Dossier des films générés (par défaut `films/`). |

## Lancement

```bash
python -m app                      # puis ouvrez http://127.0.0.1:8000
```

Saisissez votre idée, choisissez le style, la langue, le nombre de plans, le format et le type de
visuels, puis cliquez sur **Créer le film**. La page affiche l'avancement et le scénario au fur et
à mesure, puis le lecteur vidéo et les boutons de téléchargement (MP4 et sous-titres `.srt`).
L'historique de vos films est conservé dans `films/`.

## Bon à savoir

- **Temps de fabrication.** En mode illustrations, un film de 6 plans prend environ une minute.
  En mode vidéo IA, chaque clip prend une à plusieurs minutes chez Replicate ; les plans sont
  générés en parallèle, quatre à la fois.
- **Coûts.** Le scénario coûte quelques centimes d'API Claude. Les images et surtout les vidéos
  Replicate sont facturées par Replicate, selon le modèle choisi.
- **Résilience.** Si la génération IA d'un plan échoue, le plan est remplacé par une illustration
  locale. Si la synthèse vocale est indisponible (pas d'accès Internet), le film est monté sans
  voix mais avec ses sous-titres. Dans les deux cas, un avertissement s'affiche.
- **Changer de modèle Replicate.** Le mode images envoie `prompt`, `aspect_ratio` et
  `output_format`, le mode vidéo envoie seulement `prompt`. Un modèle qui attend d'autres
  paramètres demande d'adapter `app/visuals.py`.

## Structure

```
app/
  main.py         API web (FastAPI) et pages statiques
  pipeline.py     enchaînement des étapes et suivi des films en arrière-plan
  screenplay.py   écriture du scénario par Claude (sortie structurée)
  visuals.py      illustrations procédurales et appels à Replicate
  voice.py        voix off (gTTS)
  editor.py       animation des plans, sous-titres et montage ffmpeg
  static/         interface web (HTML, CSS, JavaScript)
tests/            tests automatisés (pytest)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Les tests fabriquent de vrais films avec ffmpeg, mais remplacent Claude, la voix et Replicate par
des doublures : ils ne nécessitent ni clé API ni accès Internet.
