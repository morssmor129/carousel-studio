# Przykładowe karuzele

Wszystkie przykłady używają fikcyjnej marki Pracownia Przesmyk. Teksty powstały na potrzeby tego narzędzia. Element wizualny w przykładzie fotograficznym jest kompozycją z prostych figur geometrycznych generowaną lokalnie.

| Polecenie | Przykład | Pokazuje |
| --- | --- | --- |
| `python tools/carousel.py demo editorial` | Biurko, które mieści się w domu | Okładkę z obietnicą, konkretne porady i CTA |
| `python tools/carousel.py demo photo` | Paleta z jednego kadru | Osobną warstwę obrazu i rytm slajdów zdjęciowych i tekstowych |
| `python tools/carousel.py demo panorama` | Od wejścia do okna | Dwie linie wyrównane na wspólnej osi kolejnych kafelków |

`python tools/carousel.py demo all` generuje wszystkie podglądy w `.studio/examples/projects/`. [Format profilu marki i stylu](marka-demo.json) oraz pliki `editorial.json`, `photo.json` i `panorama.json` pokazują, jak agent zapisuje brief i treści przed eksportem.
