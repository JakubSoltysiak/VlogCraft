# VlogCraft Studio 3 — prywatny edytor do vlogów

**Windows 11:** rozpakuj ZIP i uruchom `START_WINDOWS.cmd`. Jeśli nie masz Pythona 3 i FFmpeg, najpierw uruchom `INSTALL_WINDOWS_DEPS.cmd` (używa bezpłatnego `winget`). Przeglądarka otworzy lokalny edytor — okno konsoli musi pozostać uruchomione.

## Import nagrań większych niż 4,5 GB

- **LINK FILES** — natywne okno wyboru plików, bez kopiowania. Najlepsze do dużych filmów na SSD. Oryginały muszą pozostać w tym samym katalogu.
- **Przeciągnij plik z Eksploratora** — działa także z filmami większymi niż 4,5 GB: plik jest lokalnie kopiowany do `workspace/media/` porcjami po 8 MiB, bez wczytywania całości do RAM. Potrzeba tyle dodatkowego wolnego miejsca, ile zajmuje film. Pliki **nie trafiają do chmury**.
- Pliki z biblioteki można przeciągać na dowolną kompatybilną ścieżkę obrazu/dźwięku. MP4/MOV/MKV, obrazy i audio są obsługiwane przez FFmpeg.

## Możliwości

Wiele ścieżek wideo i audio, warstwy, nakładki, picture-in-picture, swobodna oś czasu, przycinanie, dzielenie (`S`), duplikowanie (`Ctrl+D`), cofanie (`Ctrl+Z`), przyciąganie, głośność, zanikanie, prędkość nagrania, korekta kolorystyczna, napisy/tytuły. Eksport MP4 H.264/AAC do **4K 60 FPS**. Opcjonalne generowanie lekkich proxy 720p do dużych nagrań HEVC.

**AI DIRECTOR:** bezpłatnie wygeneruj krótki film do oceny i prześlij go do tego czatu; mogę dać konkretne uwagi. Bezpośrednie wywołania API OpenAI są opcjonalne i osobno płatne. Propozycje AI trzeba najpierw obejrzeć i zaakceptować; ich wpływ ogranicza się do głównej sekwencji na ścieżce V1.

## Ograniczenia

To działający prototyp z własnym interfejsem, **nie pełny odpowiednik Adobe Premiere Pro**. Nie ma jeszcze profesjonalnych keyframe'ów, stabilizacji obrazu, śledzenia ruchu, maskowania, multicamu, zaawansowanych narzędzi korekcji kolorów ani eksportu ProRes/HDR10+. Podgląd zależy od obsługi kodeków w przeglądarce (przy HEVC/HDR wygeneruj proxy). Eksport 4K jest wymagający, a krótki testowy render jest zalecany przed pełnym montażem. Algorytm sprawdzono na sztucznych plikach o rozmiarze >4 GiB i krótkich ujęciach testowych, **nie na Twoich prawdziwych filmach 4,5 GB w Windows**.

Projekt zapisuje się w `workspace/project.json`. Kopiuj ten folder podczas robienia kopii zapasowej oraz zachowuj oryginalne nagrania w niezmienionej lokalizacji.

Pełna dokumentacja i testy: `README_EN.md`.
