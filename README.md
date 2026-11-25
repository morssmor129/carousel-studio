# Carousel Studio

Lokalny agent do tworzenia karuzel. Ustalasz z nim markę i styl w rozmowie, a on zapisuje ustawienia, przygotowuje slajdy i oddaje gotowe pliki do pobrania. Do składu i eksportu wystarczy Python z Pillow. Canva jest opcjonalna.

## Pierwsze uruchomienie

1. Pobierz paczkę i otwórz jej rozpakowany folder jako projekt w agencie, który ma dostęp do lokalnych plików i może uruchamiać polecenia. Agent zaczyna od `AGENTS.md`.
2. Wklej do czatu **„Skonfiguruj ze mną Carousel Studio dla mojej marki i zróbmy pierwszą karuzelę”.** Agent zapyta o markę i preferencje. Możesz dołączyć własne realizacje, 2–5 zrzutów konkretnych postów lub linki i wskazać, co Ci się w nich podoba. Przykłady są opcjonalne.
3. Po eksporcie otwórz `PRZEGLAD_KARUZEL.html`. Możesz przejrzeć slajdy w kolejności, skopiować teksty lub pobrać ZIP z PNG, edytowalnymi SVG, podglądem i tekstami. Jeśli link z czatu nie otwiera podglądu, otwórz HTML w przeglądarce z poziomu menedżera plików. Zostaw go obok katalogów z grafikami i `downloads`.

Potrzebny jest Python 3.10+ z Pillow oraz font systemowy Arial, DejaVu Sans lub Liberation Sans. Agent może użyć działającego interpretera w swoim środowisku. Gdy brakuje Pillow, zainstaluj zależność w lokalnym środowisku projektu.

**Windows (PowerShell)**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/carousel.py init
```

**macOS i Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/carousel.py init
```

## Przykłady bez własnych materiałów

Zobacz [gotowe dema ze zdjęciami stockowymi](demos/README.md). Są tam porównanie szablonów, trzy karuzele weselne, podglądy slajdów, paczki ZIP i źródła zdjęć.

Poproś w czacie **„Pokaż mi trzy przykładowe karuzele”.** Możesz też użyć `python tools/carousel.py demo all` z interpreterem, w którym jest Pillow. Przykłady zapisują się w `.studio/examples/projects/` i zwracają linki do własnych podglądów i ZIP-ów. [Opisy układów i pliki wejściowe](examples/README.md)

## Gdzie są pliki

| Katalog | Zawartość |
| --- | --- |
| `.agents/skills/carousel-studio/` | Instrukcje agenta, puste szablony i narzędzia do obsługi biblioteki oraz QA |
| `examples/` | Odtwarzalne przykłady fikcyjnej marki |
| `demos/` | Gotowe karuzele demonstracyjne, podglądy, ZIP-y i źródła zdjęć stockowych |
| `tools/` | Konfiguracja, skład, podgląd i eksport |
| `.studio/` | Lokalne profile, referencje, zdjęcia, projekty, eksporty i raporty. Katalog jest ignorowany przez Git. |

Projekt używa zapisanej kopii marki i stylu. Poprawki eksportuj pod nowym ID projektu, żeby zachować wcześniejszą paczkę i jej podgląd. Źródło SVG zachowuje edytowalne teksty i kształty oraz użyte kadry jako warstwy. Dla zgodności wyglądu przy edycji SVG zainstaluj font użyty podczas eksportu. PNG zawiera kompletny wygląd slajdu.

[Instrukcje konfiguracji w czacie](.agents/skills/carousel-studio/references/onboarding.md) · [Jak zrobić i sprawdzić eksport](.agents/skills/carousel-studio/references/production.md)
