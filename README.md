# Champignons du Salève

Carte 3D des habitats à champignons (cèpe de Bordeaux, autres bolets, girolle, trompette des morts, morilles) du Salève et du bassin genevois jusqu'aux Bornes, aux Glières et au nord d'Annecy, avec un indice de poussée calculé chaque jour à partir de la météo Open-Meteo.

Site statique (MapLibre GL) : `index.html`, `style.css`, `app.js`, `model.js`, `data/`.

- Fond de carte, routes et sentiers : OpenStreetMap via OpenFreeMap.
- Photo aérienne : IGN (France) et swisstopo (Suisse) ; relief : Mapterhorn.
- Habitats : grille de 20 m calculée hors ligne (`scripts/`) à partir d'IGN BD Forêt V2, OFEV IFN, swisstopo swissTLM3D, BD TOPO et SITG.
- Météo : chargée dans le navigateur à chaque visite (cache 3 h).

## Régénérer les couches

La zone et la taille de la grille sont dans `scripts/config.py`. Les données brutes vont dans `raw/` (non versionné) :

```bash
python3 scripts/fetch_raw.py
python3 scripts/build_layers.py
```

Si la zone ou la grille change, reporter les valeurs en tête de `app.js` (vérifiées au chargement contre `data/meta.json`).

## Déployer

```bash
vercel deploy --prod
```
