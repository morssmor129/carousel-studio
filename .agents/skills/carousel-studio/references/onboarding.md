# Konfiguracja marki w czacie

Uruchom `python tools/carousel.py init` z katalogu narzędzia. Użyj działającego Pythona 3.10+ z Pillow. Jeśli `.studio/studio.json` zawiera markę i styl, odczytaj profile z `.studio/brands/<id>/brand.json` i `.studio/styles/<id>/style.json`. Zainicjowanie folderu można powtarzać.

Wykorzystaj to, co użytkownik już podał. Zbierz pozostałe informacje w krótkiej rozmowie.

1. **Marka.** Ustal nazwę, ofertę, odbiorców, ton i ewentualne zwroty, których unikać.
2. **Materiały.** Zbierz kolory, logo, fonty i zdjęcia oraz informacje o prawie do użycia. Ustal ID marki przed importem. Przy braku logo użyj nazwy, a przy braku fontów użyj dostępnego kroju systemowego. Zdjęcia oraz referencje są opcjonalne. Jeżeli użytkownik podaje konkretny font, do odwzorowania go w lokalnym eksporcie potrzebujesz pliku fontu, do którego użycia ma prawo. Zgodę na zastąpienie fontu uzyskaj w podsumowaniu.
3. **Preferencje i inspiracje.** Zapytaj, jakie zdjęcia, układy i typografia pasują do marki oraz czego unikać. Poproś opcjonalnie o 2–5 własnych realizacji, zrzutów konkretnych postów lub linków. Możesz użyć pytania **„Podeślij screeny konkretnych postów lub karuzel, które Ci się podobają. Napisz przy każdym, co warto wykorzystać jako inspirację i czego unikać”.** Jeśli klient podaje link i screen, zapisz oba przy tej samej referencji. Wyciągnij z referencji zasady składu. Wykorzystanie obcego zdjęcia lub grafiki w eksporcie wymaga osobnego potwierdzenia praw.
4. **Kierunek.** Zaproponuj `editorial`, `photo` lub `panorama` na podstawie odpowiedzi i przykładów. Gdy klient potrzebuje punktu odniesienia, pokaż neutralne karuzele z `examples/`. Domyślnie proponuj 1080 × 1350 i 5–6 slajdów. Zmień format do potrzeb projektu.
5. **Akceptacja.** Pokaż podsumowanie marki, stylu i materiałów. Po potwierdzeniu zapisz plik konfiguracyjny w `.studio/inbox/` i uruchom `python tools/carousel.py configure .studio/inbox/marka.json`. Zwrócone ID są zapamiętane jako domyślne. Zmiany zatwierdzonego profilu zapisuj pod nowym ID, żeby starsze projekty zachowały historię.

## Format pliku do konfiguracji

[Przykładowa konfiguracja fikcyjnej marki](../../../../examples/marka-demo.json) pokazuje wymagane pola `brand` i `style`. `style.layout` to jeden z trzech układów. `style.height` obsługuje 1080, 1350 albo 1440 przy szerokości 1080. Uzupełnij `style.color_roles` kolorami HEX. Kontrast tekstu i tła jest sprawdzany przy zapisie.

Gdy masz pliki klienta, przed importem przeszukaj `.studio/registry/assets.json`. Zdjęcie, logo, font lub zrzut referencji zarejestruj poleceniem poniżej. Podaj rzeczywiste źródło i zakres prawa przekazany przez klienta. Wybierz `photo` dla zdjęcia, `graphic` dla logo lub fontu i `reference` dla zrzutu do analizy. Dla zbioru zdjęć podaj przy każdym właściwą markę.

```sh
python tools/carousel.py import-asset .studio/inbox/zdjecie.jpg --kind photo --brand moja-marka --source "Plik od właściciela marki" --rights "Zgoda na użycie w karuzelach tej marki"
```

Pomiń `--rights` przy nieustalonych prawach. Narzędzie rozpozna identyczny plik na podstawie SHA-256. Możesz dodać nowe potwierdzone pochodzenie do tego samego zasobu przez ponowny import. Grafiki wykorzystywane w eksporcie muszą mieć potwierdzenie dla wybranej marki. Zrzut referencyjny służy do analizy.

W pliku konfiguracji `brand.media` może zawierać `logo`, `heading_font` i `body_font`, z wartościami `asset_id` zwróconymi przez import. Przy fontach podaj też ich nazwy w `brand.fonts.heading` i `brand.fonts.body`. Fonty przyjmują TTF/OTF. Logo i zdjęcia przyjmują statyczne PNG, JPEG lub WebP. Wnioski z referencji zapisz przy stylu w `reference_notes`, a źródła i zakres praw w `.studio/registry/references.json`.

Po konfiguracji przejdź do briefu i eksportu [pierwszej karuzeli](production.md).
