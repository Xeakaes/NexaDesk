from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.bubble import BubbleWindow
from ui.gui.main_window import ChatWindow
from ui.history import HistoryStore


def _app():
    return QApplication.instance() or QApplication([])


class RecordingRuntime:
    def __init__(self, win):
        self._win = win
        self.calls = []

    def begin_task(self, sid, text, images=None):
        self.calls.append((sid, text, images))
        return "tid"

    def run_task(self, tid):
        pass

    def cancel_active_task(self):
        pass


def _win(tmp_path):
    app = _app()
    store = HistoryStore(tmp_path / "h.db")
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    win = ChatWindow(history=store, settings_path=settings)
    win._runtime = RecordingRuntime(win)
    return app, win


def _img(tmp_path) -> str:
    from PIL import Image

    p = tmp_path / "shot.png"
    Image.new("RGB", (32, 32), (200, 30, 30)).save(p)
    return str(p)


def test_pick_attachments_adds_chip(tmp_path, monkeypatch):
    app, win = _win(tmp_path)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([_img(tmp_path)], "")),
    )
    win._pick_attachments()
    assert len(win._pending_attachments) == 1
    assert not win._chip_bar.isHidden()
    win.close()


def test_attach_plus_button_lives_in_the_input_row(tmp_path, monkeypatch):
    # The "+" affordance is embedded at the far left of the message input
    # (ChatGPT-style), not a separate button next to Send.
    app, win = _win(tmp_path)
    plus = win._attach_plus
    # It is inside the input row container, to the left of the text edit.
    assert plus.parent() is win._input_row
    row_l = win._input_row.layout()
    assert row_l.indexOf(plus) == 0
    assert row_l.indexOf(win._chat_input) > 0
    # Clicking it opens the file picker (same flow as before).
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([_img(tmp_path)], "")),
    )
    plus.click()
    assert len(win._pending_attachments) == 1
    win.close()


def test_remove_attachment_hides_chip_bar(tmp_path, monkeypatch):
    app, win = _win(tmp_path)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([_img(tmp_path)], "")),
    )
    win._pick_attachments()
    win._remove_attachment(win._pending_attachments[0])
    assert win._pending_attachments == []
    assert win._chip_bar.isHidden()
    win.close()


def test_send_passes_images_to_runtime(tmp_path, monkeypatch):
    app, win = _win(tmp_path)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([_img(tmp_path)], "")),
    )
    win._pick_attachments()
    win._chat_input.setPlainText("buna bak")
    win._send()
    # _send starts a thread; join by draining
    import time

    for _ in range(50):
        if win._runtime.calls:
            break
        time.sleep(0.02)
    assert win._runtime.calls
    sid, text, images = win._runtime.calls[0]
    assert "buna bak" in text
    assert images and images[0].startswith("data:image/png;base64,")
    assert win._pending_attachments == []
    win.close()


def test_text_attachment_inlined_in_prompt(tmp_path, monkeypatch):
    app, win = _win(tmp_path)
    md = tmp_path / "note.md"
    md.write_text("önemli not", encoding="utf-8")
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(md)], "")),
    )
    win._pick_attachments()
    win._chat_input.setPlainText("özetle")
    win._send()
    import time

    for _ in range(50):
        if win._runtime.calls:
            break
        time.sleep(0.02)
    _, text, images = win._runtime.calls[0]
    assert "önemli not" in text and "note.md" in text
    assert not images  # empty list collapses to None on the wire
    win.close()


def test_bubble_send_passes_images(monkeypatch, tmp_path):
    app = _app()
    sent = []

    def on_send(text, images=None):
        sent.append((text, images))

    bubble = BubbleWindow(on_send=on_send, on_cancel=lambda: None)
    img = _img(tmp_path)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([img], "")),
    )
    bubble._pick_attachments()
    assert len(bubble._pending_attachments) == 1
    bubble._input.setText("bak")
    bubble._send()
    assert sent and sent[0][1] and sent[0][1][0].startswith("data:image/png;base64,")
    bubble.deleteLater()


def test_pick_attachments_reports_rejected_count(monkeypatch, tmp_path):
    # B74: a rejected file (too big, bad type, unreadable) was skipped with
    # no feedback at all — the user thinks the attach silently worked.
    from ui.attachments import AttachmentError

    app = _app()
    good = tmp_path / "ok.txt"
    good.write_text("hello", encoding="utf-8")
    bad = tmp_path / "big.png"
    bad.write_bytes(b"x")  # load_attachment will reject via monkeypatch

    calls = []

    def fake_load(path):
        calls.append(path)
        if path.name == "big.png":
            raise AttachmentError("too large")
        from ui.attachments import Attachment

        return Attachment(name=path.name, kind="text", content="hello")

    monkeypatch.setattr("ui.attachments.load_attachment", fake_load)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(bad), str(good)], "")),
    )
    win = ChatWindow(history=HistoryStore(tmp_path / "h.db"))
    win._pick_attachments()
    assert len(win._pending_attachments) == 1
    assert "1" in win._activity.text()  # rejected count surfaced
    win.hide()


def test_bubble_pick_attachments_reports_rejected_count(monkeypatch, tmp_path):
    from ui.attachments import Attachment, AttachmentError

    app = _app()
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"x")

    def fake_load(path):
        raise AttachmentError("nope")

    monkeypatch.setattr("ui.attachments.load_attachment", fake_load)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(bad)], "")),
    )
    bubble = BubbleWindow(on_send=lambda t, i=None: None, on_cancel=lambda: None)
    bubble._pick_attachments()
    assert "1" in bubble._activity.text()
    bubble.deleteLater()
