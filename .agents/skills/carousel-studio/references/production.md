# Produkcja i kontrola karuzeli

1. Potwierdź temat, cel, główny przekaz, odbiorcę, kanał i CTA. Ustal układ oraz liczbę slajdów. Zaproponuj konkretne tytuły i treści, po jednej głównej myśli na slajd. Sprawdź pisownię, obietnice i źródła faktów. Uzupełnij osobny alt text każdego kafelka.
2. Zapisz zaakceptowany brief i teksty w `.studio/inbox/<id>.json`, wzorując się na [przykładach](../../../../examples/). Pierwszy slajd ma `role: "hook"`, ostatni `role: "cta"`, środkowe `content`, `example` lub `proof`. Używaj krótkich nagłówków i rozwinięć. Pole `brief.required_facts` przyjmuje listę obiektów z `claim` i `source`. Przekaż `brand_id` i `style_id`, jeśli projekt ma korzystać z innych zapisanych profili niż domyślne.
3. Układ `photo` obsługuje `photo_asset_id` na każdym slajdzie. Opcjonalne `crop: [x, y]` określa punkt kadru od 0 do 1. Wartości `[0.5, 0.5]` wybierają środek. Dłuższy nagłówek skróć, jeśli nie mieści się w układzie. `caption` i `comment_messages` są opcjonalnymi tekstami w pliku wejściowym.
4. Uruchom `python tools/carousel.py create .studio/inbox/<id>.json`. Narzędzie zapisze projekt z przypiętymi profilami, manifest eksportu, PNG i edytowalne SVG, teksty, podgląd HTML oraz ZIP. Wynik wskaże ścieżki. Poprawki zapisz jako nowy projekt, np. `<id>-v2`, używając kolejnej wersji pliku wejściowego. Zachowaj poprzedni projekt i źródłowe pliki klienta.

## Kontrola przed przekazaniem

Otwórz każdy aktualny PNG, przejrzyj całą sekwencję i sprawdź czytelność w skali telefonu. Sprawdź marginesy, kolejność, pisownię, spójność ze stylem, zdjęcia, prawa i źródła. W podglądzie otwórz grafiki i kliknij pobranie ZIP. Gdy zmienił się eksport, obejrzyj nową wersję.

Po pozytywnej ocenie zapisz `.studio/inbox/<id>-qa.json` zgodnie z przykładem poniżej. Do `reviewed_sha256` wpisz dla każdego obejrzanego slajdu ścieżkę i sumę z `export-manifest.json`. Komenda `python tools/carousel.py review <id> .studio/inbox/<id>-qa.json` zweryfikuje te sumy i zapisze `qa/report.json`. Dla przykładów dodaj `--demo`. Status QA bez obejrzenia plików pozostaje oczekujący.

```json
{
  "reviewer": "Imię osoby lub nazwa agenta, który obejrzał slajdy",
  "notes": "Wynik oceny sekwencji, treści i rzeczywistych plików",
  "checks": {
    "readability": "passed",
    "safe_margins": "passed",
    "photo_fidelity": "passed",
    "brand_consistency": "passed",
    "facts_and_spelling": "passed"
  },
  "reviewed_sha256": {"exports/v001/slide-01.png": "suma obejrzanego pliku"}
}
```

Po akceptacji zapytaj, czy przygotować opis, jeśli klient wcześniej go nie zamówił. Przy CTA z prośbą o komentarz i obietnicą materiału przygotuj hasło, trzy odpowiedzi publiczne, pierwszą wiadomość, opcjonalny warunek obserwacji, wiadomość z materiałem i rzeczywistym linkiem oraz przypomnienie. Zapisz teksty w `captions/` przy projekcie. W `captions/manifest.json` wskaż nazwy plików i ich sumy przez `file`, `sha256`, `comment_messages_file` i `comment_messages_sha256`. Odśwież podgląd i ZIP poleceniem `python tools/przeglad_karuzeli.py <katalog-projektu>` i sprawdź aktualne wydanie.
