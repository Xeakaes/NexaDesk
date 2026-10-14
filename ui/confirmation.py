"""Ask-confirmation dialog for permission=ask tools (spec §7)."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from ui.i18n import i18n


def _build_dialog(parent, tool_name: str, question: str, arguments: dict | None = None):
    """Build the allow/deny dialog. Returns (dialog, choice) where choice is a
    mutable dict {"allow": bool} updated live by the Allow button.

    QDialogButtonBox has no clickedButton(); we track the choice via the dict.
    Closing with X/ESC emits rejected -> choice stays False -> deny (safe default).
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(i18n.t("confirmation.title"))
    layout = QVBoxLayout(dlg)
    q_lbl = QLabel(question or i18n.t("confirmation.question_default", name=tool_name))
    q_lbl.setWordWrap(True)
    layout.addWidget(q_lbl)
    tool_lbl = QLabel(i18n.t("confirmation.tool_line", name=tool_name))
    tool_lbl.setObjectName("muted")
    layout.addWidget(tool_lbl)
    if arguments:
        args_view = QTextEdit(dlg)
        args_view.setReadOnly(True)
        args_view.setPlainText(json.dumps(arguments, indent=2, ensure_ascii=False))
        args_view.setMaximumHeight(160)
        layout.addWidget(args_view)
    buttons = QDialogButtonBox(dlg)
    allow = buttons.addButton(
        i18n.t("confirmation.allow"), QDialogButtonBox.ButtonRole.AcceptRole
    )
    deny = buttons.addButton(
        i18n.t("confirmation.deny"), QDialogButtonBox.ButtonRole.RejectRole
    )
    # QPushButton#outline does not match buttons hosted by QDialogButtonBox
    # (Qt stylesheet quirk); the attribute selector does.
    deny.setProperty("outline", True)
    deny.style().unpolish(deny)
    deny.style().polish(deny)
    choice = {"allow": False}
    allow.clicked.connect(lambda: choice.__setitem__("allow", True))
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    allow.setDefault(False)
    deny.setDefault(True)
    dlg.resize(420, dlg.sizeHint().height())
    return dlg, choice


def ask_confirmation(
    parent,
    tool_name: str,
    question: str,
    arguments: dict | None = None,
) -> bool:
    """Modal allow/deny dialog. Returns True if the user allows the tool call.

    Late replies are safe: the runtime treats a reply for an already-cancelled
    or already-resolved confirmation as a no-op (spec §7 / M0 plan).
    """
    dlg, choice = _build_dialog(parent, tool_name, question, arguments)
    dlg.exec()
    # B85: the dialog stole focus; restore it so subsequent keystrokes (and
    # the xdotool --window capture) target the app, not a closed dialog.
    if parent is not None:
        parent.activateWindow()
        parent.raise_()
    return choice["allow"]
