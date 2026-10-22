# Champignons du Salève

Carte 3D des habitats à champignons (cèpe de Bordeaux, autres bolets, girolle, trompette des morts, morilles) autour du Salève et du bassin genevois, avec un indice de poussée calculé chaque jour à partir de la météo Open-Meteo.

Site statique (MapLibre GL) : `index.html`, `style.css`, `app.js`, `model.js`, `data/`.

- Fond de carte, routes et sentiers : OpenStreetMap via OpenFreeMap.
- Photo aérienne : IGN (France) et swisstopo (Suisse) ; relief : Mapterhorn.
- Habitats : grille de 20 m calculée hors ligne (`scripts/`) à partir d'IGN BD Forêt V2, OFEV IFN, swisstopo swissTLM3D, BD TOPO et SITG.
- Météo : chargée dans le navigateur à chaque visite (cache 3 h).

## Régénérer les couches

Les scripts de `scripts/` attendent les téléchargements bruts (WFS IGN, WMS swisstopo, tuiles de relief) ; `export_web.py` convertit `build/` en `data/` :

```bash
python3 -I scripts/export_web.py .
```

## Déployer

```bash
vercel deploy --prod
```
