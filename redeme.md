# Dokumentacja projektu — Math Drawing Editor

## 1. Cel projektu

Celem projektu jest stworzenie webowej aplikacji do tworzenia rysunków matematycznych, które można później eksportować do LaTeX/TikZ. Projekt początkowo był prostym edytorem grafów/trasy, natomiast obecnie został rozbudowany w kierunku ogólnego edytora rysunków matematycznych.

Aktualna wersja obsługuje trzy główne tryby pracy:

- **Grafy** — tworzenie wierzchołków i krawędzi.
- **Geometria** — tworzenie punktów, odcinków, okręgów i wielokątów.
- **Wykresy** — tworzenie wykresów z danych punktowych i funkcji.

Aplikacja przechowuje rysunki w sposób strukturalny, czyli nie jako sam obraz, ale jako zbiór obiektów z typem, danymi, stylem i kolejnością renderowania. Dzięki temu rysunek można później edytować, eksportować do TikZ/pgfplots oraz zapisywać/importować jako JSON.

---

## 2. Technologie

Projekt jest aplikacją Django.

Aktualnie używane technologie:

- Python 3,
- Django,
- SQLite,
- HTML,
- CSS,
- JavaScript,
- SVG jako główny obszar rysowania,
- TikZ/pgfplots jako format eksportu do LaTeX.

---

## 3. Uruchamianie projektu

### 3.1. Utworzenie środowiska wirtualnego

W katalogu projektu, czyli tam gdzie znajduje się plik `manage.py`, należy wykonać:

```bash
python3 -m venv venv
```

### 3.2. Aktywacja środowiska

Na macOS / Linux:

```bash
source venv/bin/activate
```

Na Windows CMD:

```bash
venv\Scripts\activate.bat
```

Na Windows PowerShell:

```bash
venv\Scripts\Activate.ps1
```

### 3.3. Instalacja zależności

```bash
pip install -r requirements.txt
```

### 3.4. Migracje

```bash
python3 manage.py migrate
```

### 3.5. Uruchomienie testów

```bash
python3 manage.py test routes -v 1
```

### 3.6. Uruchomienie serwera

```bash
python3 manage.py runserver
```

Aplikacja będzie dostępna pod adresem:

```text
http://127.0.0.1:8000/
```

---

## 4. Główna architektura danych

Aktualna część MVP opiera się na dwóch głównych modelach:

```text
Drawing
DrawingObject
```

### 4.1. `Drawing`

`Drawing` reprezentuje cały rysunek użytkownika.

Przechowuje między innymi:

- właściciela rysunku,
- tytuł,
- opis,
- tryb rysunku,
- ustawienia canvasa,
- ustawienia eksportu,
- datę utworzenia,
- datę aktualizacji.

Rysunek może być w jednym z trybów:

```text
graph
geometry
plot
```

Tryb decyduje o tym, jakie typy obiektów mogą znajdować się w rysunku.

### 4.2. `DrawingObject`

`DrawingObject` reprezentuje pojedynczy obiekt na rysunku.

Każdy obiekt ma:

- `object_id` — identyfikator obiektu w obrębie rysunku,
- `type` — typ obiektu,
- `data` — dane obiektu,
- `style` — styl obiektu,
- `order` — kolejność renderowania,
- `created_at`,
- `updated_at`.

Przykład obiektu:

```json
{
  "object_id": "A",
  "type": "geometry.point",
  "data": {
    "x": 100,
    "y": 200,
    "label": "A"
  },
  "style": {
    "stroke": "#111827",
    "fill": "#ffffff",
    "strokeWidth": 2
  },
  "order": 0
}
```

---

## 5. Tryby rysunku

Przy tworzeniu nowego rysunku użytkownik wybiera jeden z trzech trybów:

```text
Graf
Geometria
Wykresy
```

Opcja „Wszystko” została usunięta, aby nie mieszać różnych rodzajów obiektów w jednym rysunku.

### 5.1. Tryb grafowy

Tryb grafowy służy do tworzenia grafów.

Obsługiwane typy obiektów:

```text
graph.vertex
graph.edge
```

Dostępne narzędzia:

- wierzchołek,
- krawędź nieskierowana,
- krawędź skierowana.

Krawędź skierowana i nieskierowana są technicznie tym samym typem obiektu:

```text
graph.edge
```

Różnią się stylem:

```json
{
  "directed": true
}
```

albo:

```json
{
  "directed": false
}
```

Wierzchołków grafowych nie można używać w obiektach geometrycznych. To znaczy, że `graph.vertex` może być połączony wyłącznie przez `graph.edge`.

### 5.2. Tryb geometryczny

Tryb geometryczny służy do tworzenia prostych konstrukcji geometrycznych.

Obsługiwane typy obiektów:

```text
geometry.point
geometry.segment
geometry.circle
geometry.polygon
```

Obiekty geometryczne używają tylko punktów typu:

```text
geometry.point
```

Nie można użyć `graph.vertex` jako punktu w okręgu, odcinku lub wielokącie.

### 5.3. Tryb wykresów

Tryb wykresów służy do tworzenia wykresów z danych i funkcji.

Głównym typem obiektu jest:

```text
plot.chart
```

Jeden rysunek wykresowy zakłada jeden obiekt `plot.chart`, który może zawierać:

- wiele serii danych,
- funkcje,
- ustawienia osi,
- legendę,
- style serii.

---

## 6. Obiekty grafowe

### 6.1. Wierzchołek grafu

Typ:

```text
graph.vertex
```

Przykładowa struktura:

```json
{
  "type": "graph.vertex",
  "data": {
    "x": 100,
    "y": 150,
    "label": "v_1"
  },
  "style": {
    "stroke": "#111827",
    "fill": "#ffffff",
    "radius": 7
  }
}
```

### 6.2. Krawędź grafowa

Typ:

```text
graph.edge
```

Przykładowa struktura:

```json
{
  "type": "graph.edge",
  "data": {
    "source": "v1",
    "target": "v2",
    "label": "e"
  },
  "style": {
    "stroke": "#111827",
    "strokeWidth": 2,
    "directed": true
  }
}
```

Pole `directed` decyduje o tym, czy krawędź jest skierowana.

W eksporcie TikZ:

- `directed: true` daje `->`,
- `directed: false` daje `-`.

---

## 7. Obiekty geometryczne

### 7.1. Punkt

Typ:

```text
geometry.point
```

Przykład:

```json
{
  "type": "geometry.point",
  "data": {
    "x": 100,
    "y": 200,
    "label": "A"
  }
}
```

Punkty można:

- tworzyć kliknięciem,
- przesuwać,
- stylować,
- używać jako elementów zależnych dla odcinków, okręgów i wielokątów.

### 7.2. Odcinek

Typ:

```text
geometry.segment
```

Odcinek jest zależny od dwóch punktów geometrycznych.

Przykład:

```json
{
  "type": "geometry.segment",
  "data": {
    "source": "A",
    "target": "B",
    "label": "AB"
  }
}
```

Tworzenie odcinka:

1. użytkownik wybiera narzędzie „Odcinek”,
2. klika pierwsze miejsce na canvasie,
3. aplikacja tworzy pierwszy punkt,
4. użytkownik klika drugie miejsce,
5. aplikacja tworzy drugi punkt i odcinek między punktami.

Jeżeli użytkownik kliknie istniejący punkt geometryczny, zostanie on użyty jako koniec odcinka.

### 7.3. Okrąg

Typ:

```text
geometry.circle
```

Okrąg jest zależny od dwóch punktów:

- `center` — środek,
- `point` — punkt na okręgu.

Przykład:

```json
{
  "type": "geometry.circle",
  "data": {
    "center": "A",
    "point": "B",
    "label": "c"
  }
}
```

Tworzenie okręgu:

1. użytkownik wybiera narzędzie „Okrąg”,
2. klika miejsce środka,
3. aplikacja tworzy punkt środka,
4. użytkownik klika punkt na okręgu,
5. aplikacja tworzy drugi punkt i okrąg.

Po przesunięciu środka lub punktu na okręgu okrąg aktualizuje się automatycznie.

### 7.4. Wielokąt

Typ:

```text
geometry.polygon
```

Wielokąt jest zależny od listy punktów.

Przykład:

```json
{
  "type": "geometry.polygon",
  "data": {
    "points": ["A", "B", "C"],
    "closed": true,
    "label": "T"
  }
}
```

Tworzenie wielokąta:

1. użytkownik wybiera narzędzie „Wielokąt”,
2. klika kolejne punkty/wierzchołki,
3. aplikacja automatycznie tworzy punkty geometryczne,
4. kliknięcie pierwszego punktu kończy i domyka wielokąt.

Po przesunięciu dowolnego wierzchołka wielokąt zmienia kształt.

---

## 8. Obiekt tekstowy LaTeX

Typ:

```text
text.latex
```

Służy do umieszczania tekstu matematycznego na rysunku.

Przykład:

```json
{
  "type": "text.latex",
  "data": {
    "x": 120,
    "y": 180,
    "text": "\\alpha + \\beta"
  },
  "style": {
    "fill": "#111827",
    "fontSize": 18
  }
}
```

W edytorze tekst jest renderowany jako SVG `<text>`, natomiast w eksporcie TikZ trafia do węzła:

```latex
\node at (...) {$ \alpha + \beta $};
```

---

## 9. Wykresy

### 9.1. `plot.chart`

Tryb wykresów używa obiektu:

```text
plot.chart
```

Obiekt przechowuje:

- serie danych,
- funkcje,
- ustawienia osi,
- legendę,
- style.

Przykładowa struktura:

```json
{
  "type": "plot.chart",
  "data": {
    "series": [
      {
        "label": "Seria A",
        "points": [[0, 0], [1, 2], [2, 3]],
        "plotType": "line_markers",
        "style": {
          "stroke": "#2563eb"
        }
      }
    ],
    "functions": [
      {
        "expression": "x^2",
        "domainMin": -5,
        "domainMax": 5,
        "label": "x^2",
        "style": {
          "stroke": "#16a34a"
        }
      }
    ],
    "axis": {
      "title": "Tytuł wykresu",
      "xLabel": "x",
      "yLabel": "y",
      "xMin": null,
      "xMax": null,
      "yMin": null,
      "yMax": null
    },
    "legend": {
      "show": true
    }
  }
}
```

### 9.2. Wiele serii danych

Dane można wpisywać w panelu pod wykresem.

Przykład:

```text
# label=Seria A; color=#2563eb; type=line_markers
0,0
1,2
2,3

# label=Seria B; color=#dc2626; type=scatter
0,1
1,3
2,4
```

Serie rozdzielane są pustą linią.

### 9.3. Funkcje

Funkcje można wpisywać w formacie:

```text
wyrażenie; xmin; xmax; etykieta; kolor
```

Przykład:

```text
x^2; -5; 5; x^2; #16a34a
sin(deg(x)); -6.28; 6.28; sin(x); #9333ea
```

Eksport do LaTeX korzysta z `pgfplots`.

---

## 10. Canvas i interakcja użytkownika

Edytor używa SVG jako obszaru rysowania.

Obsługiwane akcje:

- kliknięcie w canvas tworzy obiekt,
- kliknięcie obiektu zaznacza go,
- `Ctrl`/`Shift` + klik dodaje do zaznaczenia,
- przeciągnięcie pustego miejsca tworzy prostokąt zaznaczenia,
- zaznaczone obiekty można przesuwać,
- wiele zaznaczonych obiektów można przesuwać razem,
- zaznaczone obiekty można usuwać,
- zaznaczone obiekty można duplikować,
- można zmieniać styl zaznaczonych obiektów,
- można zmieniać etykietę lub treść zaznaczonego obiektu.

---

## 11. Zaznaczanie prostokątne

W trybie zaznaczania można przeciągnąć prostokątną pętlę po canvasie.

Obiekty znajdujące się w zaznaczonym prostokącie zostają zaznaczone.

Z `Ctrl`/`Shift` zaznaczenie prostokątne dodaje obiekty do obecnego zaznaczenia zamiast zastępować całe zaznaczenie.

---

## 12. Style

Każdy obiekt ma pole `style`.

Przykładowe obsługiwane właściwości:

```json
{
  "stroke": "#111827",
  "fill": "#ffffff",
  "strokeWidth": 2,
  "radius": 7,
  "showLabel": true,
  "directed": false
}
```

Panel stylu pozwala zmieniać:

- kolor linii/obrysu,
- kolor wypełnienia,
- grubość linii,
- promień punktów,
- widoczność etykiet,
- skierowanie krawędzi grafowej.

Istnieje też panel domyślnego stylu nowych obiektów. Ustawiony tam styl obowiązuje dla kolejnych tworzonych obiektów aż do następnej zmiany.

---

## 13. Ustawienia rysunku

Model `Drawing` ma pole:

```python
settings = models.JSONField(default=dict, blank=True)
```

Przechowywane są w nim ustawienia canvasa i eksportu.

Przykład:

```json
{
  "canvas": {
    "width": 900,
    "height": 520,
    "gridSize": 50,
    "showGrid": true,
    "snapToGrid": false
  },
  "tikz": {
    "scale": 100
  }
}
```

Użytkownik może zmieniać:

- szerokość canvasa,
- wysokość canvasa,
- rozmiar siatki,
- widoczność siatki,
- snap do siatki,
- skalę eksportu TikZ.

---

## 14. Snap do siatki

Po włączeniu opcji `snapToGrid`:

- nowe punkty są tworzone na najbliższym przecięciu siatki,
- przesuwane punkty są przyciągane do siatki,
- punkty tworzone automatycznie przy odcinku, okręgu i wielokącie również podlegają snapowaniu.

---

## 15. Kolejność obiektów

Każdy `DrawingObject` ma pole:

```text
order
```

Określa ono kolejność renderowania.

W UI dostępne są akcje:

- `Na wierzch`,
- `Pod spód`,
- `Wyżej`,
- `Niżej`.

Kolejność jest zapisywana w bazie i zachowywana po odświeżeniu strony.

Eksport TikZ również uwzględnia kolejność obiektów.

---

## 16. Undo / redo

Edytor posiada lokalną historię operacji.

Obsługiwane operacje:

- dodanie obiektu,
- usunięcie obiektu,
- przesunięcie,
- zmiana stylu,
- zmiana etykiety,
- duplikowanie,
- zmiana kolejności.

Historia działa lokalnie w aktualnej sesji przeglądarki. Po odświeżeniu strony historia jest czyszczona.

---

## 17. Eksport TikZ / pgfplots

Aplikacja umożliwia eksport rysunku do LaTeX/TikZ.

Dla grafów i geometrii generowany jest kod TikZ.

Przykłady:

```latex
\coordinate (A) at (1, 4);
\fill (A) circle (1.5pt);
\draw (A) -- (B);
```

Dla wykresów generowany jest kod `pgfplots`.

Przykład:

```latex
\begin{tikzpicture}
\begin{axis}
\addplot coordinates {
  (0,0)
  (1,2)
};
\end{axis}
\end{tikzpicture}
```

W edytorze dostępne są:

- pobranie kodu TikZ,
- podgląd kodu TikZ,
- kopiowanie kodu TikZ do schowka.

---

## 18. Eksport/import JSON

Dodano możliwość eksportu całego rysunku do JSON.

Eksportowany JSON zawiera:

- wersję schematu,
- tytuł,
- tryb rysunku,
- ustawienia,
- listę obiektów,
- dane obiektów,
- style,
- kolejność.

Przykład:

```json
{
  "schema_version": 1,
  "title": "Mój rysunek",
  "mode": "geometry",
  "settings": {
    "canvas": {
      "width": 900,
      "height": 520
    }
  },
  "objects": [
    {
      "object_id": "A",
      "type": "geometry.point",
      "data": {
        "x": 100,
        "y": 200,
        "label": "A"
      },
      "style": {
        "stroke": "#111827"
      },
      "order": 0
    }
  ]
}
```

Import JSON tworzy nowy rysunek na koncie aktualnie zalogowanego użytkownika.

Import sprawdza:

- poprawność JSON,
- poprawność trybu,
- unikalność `object_id`,
- poprawność typów obiektów,
- zgodność typów z trybem,
- poprawność zależności między obiektami.

---

## 19. API

### 19.1. Lista rysunków

```text
GET /drawings/
```

### 19.2. Tworzenie rysunku

```text
GET  /drawings/create/
POST /drawings/create/
```

### 19.3. Szczegóły rysunku

```text
GET /drawings/<id>/
```

### 19.4. Usunięcie rysunku

```text
POST /drawings/<id>/delete/
```

### 19.5. Obiekty rysunku

```text
GET    /drawings/<drawing_id>/objects/
POST   /drawings/<drawing_id>/objects/
GET    /drawings/<drawing_id>/objects/<object_id>/
PATCH  /drawings/<drawing_id>/objects/<object_id>/
PUT    /drawings/<drawing_id>/objects/<object_id>/
DELETE /drawings/<drawing_id>/objects/<object_id>/
```

### 19.6. Ustawienia rysunku

```text
GET   /drawings/<id>/settings/
PATCH /drawings/<id>/settings/
PUT   /drawings/<id>/settings/
```

### 19.7. Eksport TikZ

```text
GET /drawings/<id>/export/tikz/
```

### 19.8. Podgląd TikZ

```text
GET /drawings/<id>/export/tikz/preview/
```

### 19.9. Eksport JSON

```text
GET /drawings/<id>/export/json/
```

### 19.10. Import JSON

```text
GET  /drawings/import/
POST /drawings/import/
```

---

## 20. Walidacja

Backend waliduje tworzone i importowane obiekty.

Przykładowe zasady:

- `graph.edge` może łączyć tylko `graph.vertex`,
- `geometry.segment` może łączyć tylko `geometry.point`,
- `geometry.circle` może używać tylko `geometry.point`,
- `geometry.polygon` może używać tylko `geometry.point`,
- obiekty grafowe nie są dozwolone w rysunku geometrycznym,
- obiekty geometryczne nie są dozwolone w rysunku grafowym,
- obiekty wykresowe są dozwolone w trybie wykresów,
- `object_id` musi być unikalne w obrębie rysunku,
- dane wykresu muszą być poprawnymi liczbami,
- zakres osi musi spełniać warunek min < max.

---

## 21. Bezpieczeństwo

Wszystkie rysunki są przypisane do użytkowników.

Aplikacja sprawdza, czy użytkownik jest właścicielem rysunku przy:

- wyświetlaniu rysunku,
- edycji obiektów,
- eksporcie TikZ,
- eksporcie JSON,
- usuwaniu rysunku,
- zmianie ustawień.

Użytkownik nie powinien mieć dostępu do cudzych rysunków.

---

## 22. Testy

Projekt posiada rozbudowaną bazę testów.

Aktualnie testy obejmują między innymi:

- modele `Drawing` i `DrawingObject`,
- widoki listy i szczegółów rysunków,
- kontrolę właściciela rysunków,
- API obiektów,
- walidację typów,
- tryby rysunków,
- eksport TikZ,
- eksport pgfplots,
- import/eksport JSON,
- ustawienia rysunku,
- snap do siatki,
- style,
- kolejność obiektów,
- podstawowe elementy UI.

Na aktualnym etapie liczba testów wynosi:

```text
140
```

Do sprawdzania projektu używane są komendy:

```bash
python3 manage.py check
python3 manage.py makemigrations --check --dry-run
python3 manage.py test routes -v 1
node --check routes/static/routes/drawing_editor.js
```

---

## 23. Część legacy

Pierwotny edytor oparty na modelach:

```text
Route
Point
Edge
```

nie został całkowicie usunięty, ale został odsunięty do części legacy.

Główna aplikacja rozwijana jest wokół modeli:

```text
Drawing
DrawingObject
```

Docelowo stary edytor może zostać usunięty albo wykorzystany do migracji starych danych do nowego modelu.

---

## 24. Funkcjonalności świadomie odłożone

Na ten moment nie zostały jeszcze wdrożone:

- trwałe grupowanie obiektów,
- pełna architektura pluginów,
- import PNG z rozpoznawaniem rysunku,
- OCR etykiet,
- eksport SVG,
- eksport PNG,
- relatywne etykiety,
- zaawansowany edytor funkcji.

Grupowanie było eksperymentalnie testowane, ale zostało wycofane, ponieważ wymaga dokładniejszego projektu interakcji.

Architektura pluginów jest planowana, ale nie została jeszcze zaimplementowana. Aktualna struktura typów obiektów, np. `graph.*`, `geometry.*`, `plot.*`, przygotowuje projekt pod późniejsze wprowadzenie pluginów.

---

## 25. Możliwe dalsze kroki

Najbliższe możliwe kierunki rozwoju:

1. Poprawa UI wykresów:
   - osobna lista serii,
   - dodawanie/usuwanie serii przez formularz,
   - wygodniejsza edycja funkcji.

2. Eksport SVG.

3. Eksport PNG.

4. Rozbudowa stylów:
   - przezroczystość,
   - typ linii,
   - styl punktów,
   - opacity wypełnienia.

5. Relatywne etykiety:
   - etykieta nad/pod/lewo/prawo względem punktu,
   - etykieta powiązana z obiektem.

6. Dokumentacja planowanej architektury pluginów.

7. Późniejszy powrót do grupowania obiektów.

8. Import PNG i rozpoznawanie prostych rysunków przy użyciu narzędzi computer vision/OCR.

---

## 26. Podsumowanie

Aktualna wersja projektu jest już czymś więcej niż prostym edytorem grafów. Powstał strukturalny edytor rysunków matematycznych oparty o `Drawing` i `DrawingObject`, obsługujący grafy, geometrię oraz wykresy.

Najważniejsze osiągnięcia obecnego etapu:

- wprowadzenie ogólnego modelu danych,
- trzy tryby rysunku,
- interaktywny canvas SVG,
- obiekty grafowe,
- obiekty geometryczne,
- wykresy z danych i funkcji,
- stylowanie obiektów,
- snap do siatki,
- eksport TikZ/pgfplots,
- import/eksport JSON,
- testy dla głównych funkcjonalności.

Projekt jest przygotowany do dalszej rozbudowy w kierunku pełnego edytora matematycznego oraz późniejszej architektury pluginowej.
