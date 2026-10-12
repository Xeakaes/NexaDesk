# NexaDesk — Desktop AI Assistant

[![CI](https://github.com/Xeakaes/NexaDesk/actions/workflows/ci.yml/badge.svg)](https://github.com/Xeakaes/NexaDesk/actions/workflows/ci.yml)
[![Release](https://github.com/Xeakaes/NexaDesk/actions/workflows/release.yml/badge.svg)](https://github.com/Xeakaes/NexaDesk/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Xeakaes/NexaDesk/blob/main/LICENSE)

**NexaDesk** is an open-source desktop AI assistant for Linux and Windows: a local-first chat GUI, an animated pixel-art avatar mode, and built-in screen-control tools — all in one PySide6 app.

Run local models with **Ollama**, or connect cloud providers (**Groq, GitHub Copilot *(experimental, unofficial API)*, NVIDIA, Google, OpenAI-compatible**). Dark and light themes, Turkish and English UI, instant mode switching.

## Why NexaDesk?

- **Chat GUI** — Ollama-style interface with tool calling, SQLite history, selectable transcript, right-click chat deletion, and a coral-accent dark/light design
- **Avatar mode** — pixel-art character with speech bubble and state animations (idle / thinking / working / speaking / error); the bubble lists your past sessions
- **Screen control** — screenshot, OCR (bundled on-device engine), mouse/keyboard, window management; the server ships embedded, zero extra install
- **Local-first** — your keys stay in `config/secrets.json` (never committed); history lives in a local SQLite DB
- **Provider flexible** — Ollama (fully local), Groq, GitHub Copilot (experimental, unofficial API), NVIDIA NIM, Google Gemini, or any OpenAI-compatible endpoint
- **TR / EN** — full bilingual UI with instant language switching

## Install

### Linux (`.deb`)

```bash
sudo dpkg -i NexaDesk_<version>_amd64.deb
```

### Linux (portable tar.gz)

```bash
tar -xzf NexaDesk_<version>_linux_amd64.tar.gz
./NexaDesk/NexaDesk
```

### Windows (`.zip`)

Extract `NexaDesk_<version>_windows_x64.zip` and run `NexaDesk.exe`.

Prebuilt binaries for every release: [github.com/Xeakaes/NexaDesk/releases](https://github.com/Xeakaes/NexaDesk/releases)

## First run

On first launch NexaDesk asks which mode to use (Chat GUI / Avatar). The choice is saved to `config/ui.json` and can be changed any time from the sidebar or right-click menu.

Provider and API keys are configured in the **Settings** window (five tabs: General, Provider, Screen control, Permissions, Avatar).

## Configuration locations

Running from source (development):

| File | Location |
|---|---|
| Settings | `config/settings.json` |
| Secret keys | `config/secrets.json` (0600) |
| UI preferences | `config/ui.json` |
| Chat history | `~/.local/share/NexaDesk/history.db` |

In a packaged build, settings move to the user config directory:

| OS | Location |
|---|---|
| Linux | `~/.config/NexaDesk/` |
| Windows | `%APPDATA%\NexaDesk\` |

`config/secrets.json` is never included in the package or the repository.

## Build from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-packaging.txt
.venv/bin/pytest tests -q          # run all tests
.venv/bin/python -m ui.app         # launch the app
```

### Packaging (Linux)

```bash
bash packaging/build_linux.sh      # PyInstaller + tar.gz + deb (requires nfpm)
```

### Screen control

The screen-control client and server are embedded under `vendor/sc_server/`. When screen control is enabled and port 8745 is free, the app spawns itself as a subprocess with `--serve-screen-control`. Tokens and API keys are stored in the user configuration directory.

## Tech stack

Python 3.12 · PySide6 (Qt 6) · SQLite · Pillow · RapidOCR (ONNX) · QSS theming · PyInstaller

## License

MIT — see [LICENSE](LICENSE).

---

---

# NexaDesk — Masaüstü AI Asistanı (Türkçe)

**NexaDesk**, Linux ve Windows için açık kaynaklı masaüstü AI asistanı: yerel çalışan sohbet arayüzü, animasyonlu piksel-art avatar modu ve yerleşik ekran kontrolü araçları — hepsi tek hafif PySide6 uygulamasında.

Yerel modelleri **Ollama** ile çalıştırın veya bulut sağlayıcılarına bağlanın (**Groq, GitHub Copilot *(deneysel, resmi olmayan API)*, NVIDIA, Google, OpenAI-uyumlu**). Karanlık/açık tema, Türkçe/İngilizce arayüz, anında mod geçişi.

## NexaDesk neden?

- **Sohbet (GUI) modu** — tool çağırma, SQLite geçmiş, seçilebilir sohbet metni, sağ tıkla sohbet silme, mercan vurgulu karanlık/açık tasarım
- **Avatar modu** — piksel-art karakter, konuşma balonu ve durum animasyonları (boşta / düşünüyor / çalışıyor / konuşuyor / hata); balon eski oturumlarınızı listeler
- **Ekran kontrolü** — screenshot, OCR (paket içinde yerel motor), fare/klavye, pencere yönetimi; sunucu paketin içinde gömülü, ek kurulum yok
- **Yerel öncelikli** — anahtarlarınız `config/secrets.json`'da kalır (asla commit edilmez); geçmiş yerel SQLite DB'de
- **Sağlayıcı esnekliği** — Ollama (tamamen yerel), Groq, GitHub Copilot (deneysel, resmi olmayan API), NVIDIA NIM, Google Gemini veya OpenAI-uyumlu herhangi bir uç nokta
- **TR / EN** — tam iki dilli arayüz, anında dil değişimi

## Kurulum

### Linux (`.deb`)

```bash
sudo dpkg -i NexaDesk_<sürüm>_amd64.deb
```

### Linux (taşınabilir tar.gz)

```bash
tar -xzf NexaDesk_<sürüm>_linux_amd64.tar.gz
./NexaDesk/NexaDesk
```

### Windows (`.zip`)

`NexaDesk_<sürüm>_windows_x64.zip` dosyasını çıkarıp `NexaDesk.exe`'yi çalıştırın.

Hazır binary'ler: [github.com/Xeakaes/NexaDesk/releases](https://github.com/Xeakaes/NexaDesk/releases)

## İlk çalıştırma

İlk açılışta NexaDesk hangi modda açılacağını sorar (Sohbet GUI / Avatar). Seçim `config/ui.json`'a yazılır; kenar çubuğundan veya sağ tık menüsünden her zaman değiştirilebilir.

Sağlayıcı ve API anahtarları **Ayarlar** penceresinden yapılandırılır (beş sekme: Genel, Sağlayıcı, Ekran kontrolü, İzinler, Avatar).

## Yapılandırma konumları

Kaynak ağaçtan (geliştirme) çalışırken:

| Dosya | Konum |
|---|---|
| Ayarlar | `config/settings.json` |
| Gizli anahtarlar | `config/secrets.json` (0600) |
| UI tercihleri | `config/ui.json` |
| Sohbet geçmişi | `~/.local/share/NexaDesk/history.db` |

Paketlenmiş sürümde ayarlar kullanıcı dizinine taşınır:

| İşletim Sistemi | Konum |
|---|---|
| Linux | `~/.config/NexaDesk/` |
| Windows | `%APPDATA%\NexaDesk\` |

`config/secrets.json` ne pakete ne de depoya dahil edilir.

## Kaynaktan derleme

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-packaging.txt
.venv/bin/pytest tests -q          # tüm testler
.venv/bin/python -m ui.app         # uygulamayı başlat
```

### Paket oluşturma (Linux)

```bash
bash packaging/build_linux.sh      # PyInstaller + tar.gz + deb (nfpm gerekir)
```

### Ekran kontrolü

Ekran kontrolü istemcisi ve sunucusu `vendor/sc_server/` altında gömülüdür. Uygulama, ekran kontrolü etkinse ve port 8745 boşta değilse kendini `--serve-screen-control` bayrağıyla alt süreç olarak başlatır. Token ve API anahtarları kullanıcı yapılandırma dizininde saklanır.

## Teknoloji yığını

Python 3.12 · PySide6 (Qt 6) · SQLite · Pillow · RapidOCR (ONNX) · QSS temalama · PyInstaller

## Lisans

MIT — bkz. [LICENSE](LICENSE).
