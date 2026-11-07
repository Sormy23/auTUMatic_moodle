# tum-moodle-sync

Lädt alle Dateien aus allen deinen Kursen auf [moodle.tum.de](https://www.moodle.tum.de) in einen lokalen Ordner.
Login über login.tum.de mit TUM-Kennung und Passwort. Kein Browser, keine Moodle-App nötig.

```
moodle/
└── Diskrete Strukturen (IN0015)/
    ├── 00 Allgemeines/orga.pdf
    └── 02 20. Oktober - 26. Oktober/
        ├── Loesung2.pdf
        └── Hausaufgaben Blatt 1/{Abgabe,Feedback}/…
```

Lädt nur neue und geänderte Dateien. Wird eine Datei in Moodle ersetzt, wird die lokale Kopie überschrieben.

## Konfiguration

```sh
cp config.env.example config.env
chmod 600 config.env
```

| Variable           | Bedeutung                                    | Default    |
|--------------------|----------------------------------------------|------------|
| `TUM_USER`         | TUM-Kennung, z.B. `ab12cde`                  | –          |
| `TUM_PASSWORD`     | TUM-Passwort                                 | –          |
| `MOODLE_DIR`       | Zielordner (nur bare metal)                  | `./moodle` |
| `MOODLE_STATE_DIR` | Session und Manifest (nur bare metal)        | `./.state` |
| `SYNC_INTERVAL`    | alle N Minuten wiederholen, `0` = einmal     | `0`        |

## Docker

```sh
mkdir -p moodle .state            # sonst legt Docker die Ordner als root an
docker compose up -d --build      # synchronisiert alle 120 min nach ./moodle
docker compose logs -f
```

Das Intervall stellst du mit `SYNC_INTERVAL=30 docker compose up -d` ein.
Falls deine User-ID nicht 1000 ist: `UID=$(id -u) GID=$(id -g) docker compose up -d`.

Einmalig ohne compose:

```sh
docker build -t tum-moodle-sync .
docker run --rm -v "$PWD/config.env:/app/config.env:ro" -v "$PWD/moodle:/data" -v "$PWD/.state:/state" \
  --user "$(id -u):$(id -g)" tum-moodle-sync
```

## Bare metal

Voraussetzung ist [uv](https://docs.astral.sh/uv/).

```sh
uv run tum-moodle-sync            # einmal synchronisieren
uv run tum-moodle-sync --list     # Kurse anzeigen
uv run tum-moodle-sync --dry-run  # anzeigen, was geladen würde
uv run tum-moodle-sync --course 121238 --interval 60   # nur ein Kurs, stündlich
```

Für einen regelmäßigen Sync per cron (`crontab -e`):

```
0 */2 * * * cd /pfad/zum/projekt && uv run tum-moodle-sync >> sync.log 2>&1
```

Exit-Codes: `0` ok, `1` einzelne Dateien fehlgeschlagen, `2` Login fehlgeschlagen.
