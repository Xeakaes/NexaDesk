# Full-GUI Milestone — Desktop Manual Checklist

> Run from project root: `.venv/bin/python ui/app.py` (entrypoint; `python -m ui.app` also works)
> Record: PASS / FAIL / NOTE per row. Screenshots optional.

## 1. First-run chooser
- [ ] Delete/rename the `ui.json` under your config dir (see `ui.paths.ui_json_path()` — `~/.config/NexaDesk/ui.json` on Linux) if present; launch app → mode chooser dialog appears (GUI / Avatar buttons, title in Turkish).
- [ ] Pick **GUI** → main window opens; `ui.json` now has `"mode": "gui"`.
- [ ] Relaunch → no chooser, GUI opens directly.
- [ ] Delete `ui.json` again; pick **Avatar** → avatar mode opens; `ui.json` has `"mode": "avatar"`.

## 2. GUI mode — sidebar & chat
- [ ] Sidebar shows: `+ Yeni sohbet`, session list (empty first run), Tema, Ayarlar, Avatar'a geç, ☰ collapse.
- [ ] Collapse (☰) → sidebar shrinks to ~48px, list+labels hidden; expand restores 260px.
- [ ] Click **+ Yeni sohbet** → input clears, new empty session in list.
- [ ] Type message, press **Enter** → user bubble appears, assistant replies, both persisted.
- [ ] Press **Shift+Enter** → newline inserted (no send).
- [ ] Click **Gönder** button → same as Enter.
- [ ] Mid-reply, click **İptal** → activity line shows cancelled message, send re-enabled.
- [ ] Tool-using prompt (e.g. "ekran görüntüsü al") → activity line updates, tool result shown as `msg_tool` frame.
- [ ] Quit while busy → window closes within ~2s (no hang on thread join).

## 3. GUI mode — history
- [ ] Multiple sessions exist in sidebar (auto-titled from first 40 chars).
- [ ] Click an old session → transcript reloads with all prior user/assistant/tool rows.
- [ ] Restart app → sessions and messages still present (SQLite persists).

## 4. Themes
- [ ] Click **Tema** in sidebar → dark ↔ light flips live; restart keeps new theme.
- [ ] Settings → Tema combo also flips live on save (both modes).
- [ ] Light mode: text readable on all bubbles, sidebar, input, settings.

## 5. Language
- [ ] Settings → Dil: switch tr ↔ en; **all** visible labels/buttons/placeholders change live (window title, sidebar buttons, input placeholder, send/cancel, settings fields).
- [ ] No mixed-language leftovers after switch (screenshot both languages).
- [ ] Relaunch → language persists.

## 6. Avatar mode
- [ ] From GUI, click **Avatar'a geç** → process restarts into avatar mode (no dual window).
- [ ] Avatar right-click → menu shows **GUI'ye geç** → restarts into GUI.
- [ ] Settings reachable from avatar mode; same shared SettingsWindow.
- [ ] Avatar state machine: idle bobbing; thinking/working spinner; speaking on reply; error tint on failure.

## 7. Custom avatar pack (Settings → Avatar)
- [ ] Settings → Özel karakter: pick a photo (jpg/png), set pack name, click **Paket oluştur**.
- [ ] Success → status shows localized success, avatar combo gains new pack; select + save.
- [ ] Relaunch avatar mode → new pack loads, 5 states animate.
- [ ] Reuse an existing pack name (e.g. `base`) → localized "exists" error, existing pack untouched.
- [ ] Pick a corrupt/non-image file → localized "bad image" error, no partial output.

## 8. Provider & permissions (regression)
- [ ] Settings → provider URL/model/API key save & reload correctly.
- [ ] Screen-control host/port/key save & reload.
- [ ] Permission combos (default + per-tool) save & reload.

## 9. CLI regression
- [ ] `.venv/bin/python cli.py --help` still works.
- [ ] Existing test suite green: `.venv/bin/pytest tests -q` (expect 593+ passing).

## Sign-off
- Tester: _____________  Date: ___________  Build/commit: ___________
