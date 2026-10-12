"""Strict tr/en translation catalog (spec §12): missing keys fail loud."""

from __future__ import annotations

from typing import Any

LANGUAGES: tuple[str, ...] = ("tr", "en")


class MissingTranslationError(KeyError):
    pass


STRINGS: dict[str, dict[str, str]] = {
    "app.title": {"tr": "NexaDesk", "en": "NexaDesk"},
    "mode.gui": {"tr": "Sohbet (GUI)", "en": "Chat (GUI)"},
    "mode.avatar": {"tr": "Avatar", "en": "Avatar"},
    "mode.choose_title": {"tr": "Mod seçin", "en": "Choose a mode"},
    "mode.choose_body": {
        "tr": "Uygulamayı hangi modda açmak istersiniz? Tercihiniz hatırlanacak.",
        "en": "Which mode should the app start in? Your choice will be remembered.",
    },
    "sidebar.new_chat": {"tr": "+ Yeni sohbet", "en": "+ New chat"},
    "sidebar.sessions": {"tr": "Geçmiş sohbetler", "en": "Chat history"},
    "sidebar.theme": {"tr": "Tema", "en": "Theme"},
    "sidebar.settings": {"tr": "Ayarlar", "en": "Settings"},
    "sidebar.switch_avatar": {"tr": "Avatar'a geç", "en": "Switch to Avatar"},
    "sidebar.collapse": {"tr": "Daralt", "en": "Collapse"},
    "sidebar.expand": {"tr": "Genişlet", "en": "Expand"},
    "chat.input_placeholder": {"tr": "Mesaj yazın…", "en": "Type a message…"},
    "chat.send": {"tr": "Gönder", "en": "Send"},
    "chat.cancel": {"tr": "İptal", "en": "Cancel"},
    "chat.history": {"tr": "Geçmiş", "en": "History"},
    "chat.tool_activity": {"tr": "Araç etkinliği", "en": "Tool activity"},
    "chat.user_prefix": {"tr": "Sen", "en": "You"},
    "chat.assistant_prefix": {"tr": "Asistan", "en": "Assistant"},
    "chat.tool_prefix": {"tr": "Araç", "en": "Tool"},
    "chat.cancelled": {"tr": "Görev iptal edildi.", "en": "Task cancelled."},
    "chat.error_prefix": {"tr": "Hata", "en": "Error"},
    "chat.error_rate_limited": {
        "tr": "Model sağlayıcısı hız limitine takıldı (429). Biraz bekleyip yeniden deneyin ya da Ayarlar'dan başka bir sağlayıcı seçin.",
        "en": "The model provider hit its rate limit (429). Wait a moment and try again, or pick another provider in Settings.",
    },
    "chat.error_unauthorized": {
        "tr": "Model sağlayıcısı API anahtarını reddetti (401). Anahtarı Ayarlar'dan kontrol edin ya da yenileyin.",
        "en": "The model provider rejected the API key (401). Check or renew the key in Settings.",
    },
    "chat.empty_title": {"tr": "Merhaba! Bir sohbet başlat.", "en": "Hi! Start a chat."},
    "chat.empty_hint": {
        "tr": "Asistana ne sormak istersiniz?",
        "en": "What would you like to ask?",
    },
    "settings.title": {"tr": "Ayarlar — NexaDesk", "en": "Settings — NexaDesk"},
    "settings.theme": {"tr": "Tema", "en": "Theme"},
    "settings.theme_dark": {"tr": "Karanlık", "en": "Dark"},
    "settings.theme_light": {"tr": "Açık", "en": "Light"},
    "settings.mode": {"tr": "Mod", "en": "Mode"},
    "settings.lang": {"tr": "Dil", "en": "Language"},
    "settings.lang_tr": {"tr": "Türkçe", "en": "Turkish"},
    "settings.lang_en": {"tr": "İngilizce", "en": "English"},
    "settings.persona": {"tr": "Persona (system prompt)", "en": "Persona (system prompt)"},
    "settings.persona_hint": {
        "tr": "Modelin kişiliği — boşsa varsayılan davranış. Kaydettikten sonra geçerli olur.",
        "en": "The model's personality — empty means default behavior. Applies after saving.",
    },
    "settings.update_check": {
        "tr": "Açılışta güncelleme kontrolü",
        "en": "Check for updates on startup",
    },
    "update.banner": {"tr": "Yeni sürüm mevcut: {tag}", "en": "New version available: {tag}"},
    "update.download": {"tr": "İndir", "en": "Download"},
    "update.dismiss": {"tr": "Kapat", "en": "Dismiss"},
    "notify.task_done_title": {"tr": "NexaDesk", "en": "NexaDesk"},
    "notify.task_done_body": {"tr": "Görev tamamlandı.", "en": "Task finished."},
    "notify.task_error_title": {"tr": "NexaDesk — hata", "en": "NexaDesk — error"},
    "settings.notify": {
        "tr": "Görev bitince masaüstü bildirimi",
        "en": "Desktop notification when a task finishes",
    },
    "settings.close_to_tray": {
        "tr": "Kapatınca tepside kal",
        "en": "Keep in tray when the window is closed",
    },
    "tray.chat": {"tr": "Sohbeti aç", "en": "Open chat"},
    "tray.avatar": {"tr": "Avatarı aç", "en": "Open avatar"},
    "tray.settings": {"tr": "Ayarlar", "en": "Settings"},
    "tray.quit": {"tr": "Çıkış", "en": "Quit"},
    "chat.attach": {"tr": "Dosya ekle", "en": "Attach file"},
    "chat.attachment": {"tr": "ek", "en": "attachment"},
    "settings.pack_title": {"tr": "Özel karakter", "en": "Custom character"},
    "settings.pack_pick": {"tr": "Fotoğraf seç…", "en": "Choose photo…"},
    "settings.pack_name": {"tr": "Paket adı", "en": "Pack name"},
    "settings.pack_build": {"tr": "Paketi oluştur", "en": "Build pack"},
    "settings.pack_delete": {"tr": "Paketi sil", "en": "Delete pack"},
    "settings.pack_deleted": {"tr": "Paket silindi: {name}", "en": "Pack deleted: {name}"},
    "settings.pack_delete_confirm": {
        "tr": "'{name}' paketi kalıcı olarak silinsin mi?",
        "en": "Permanently delete the '{name}' pack?",
    },
    "settings.pack_delete_failed": {
        "tr": "Paket silinemedi: {name}",
        "en": "Could not delete pack: {name}",
    },
    "settings.pack_delete_builtin": {
        "tr": "Dahili 'base' paketi silinemez.",
        "en": "The built-in 'base' pack cannot be deleted.",
    },
    "settings.pack_success": {"tr": "Paket oluşturuldu: {name}", "en": "Pack created: {name}"},
    "settings.pack_exists": {"tr": "Bu isim zaten var: {name}", "en": "Name already exists: {name}"},
    "settings.pack_bad_image": {"tr": "Geçersiz veya bozuk görsel.", "en": "Invalid or corrupt image."},
    "settings.save_restart_note": {
        "tr": "Kaydedildi — izinler için yeniden başlatın",
        "en": "Saved — restart for permission changes",
    },
    "setup.missing_provider.title": {
        "tr": "Model Ayarı Gerekli",
        "en": "Model Setup Required",
    },
    "setup.missing_provider.message": {
        "tr": (
            "Yapay zekâ modeli henüz yapılandırılmamış.\n\n"
            "Tamam'a bastığınızda Ayarlar penceresi açılacak — oradan modelinizi "
            "ve API anahtarınızı ayarlayıp kaydedin. Uygulama yeniden "
            "başlatılmadan kullanıma devam eder."
        ),
        "en": (
            "The AI model is not configured yet.\n\n"
            "Press OK to open the Settings window — set your model and API key "
            "there, then save. The app keeps running without a restart."
        ),
    },
    "setup.provider_ready": {
        "tr": "Model yapılandırıldı — hazır.",
        "en": "Model configured — ready.",
    },
    "settings.section_general": {"tr": "Genel", "en": "General"},
    "settings.section_provider": {"tr": "Sağlayıcı", "en": "Provider"},
    "settings.section_screen": {"tr": "Ekran kontrolü", "en": "Screen control"},
    "settings.section_permissions": {"tr": "İzinler", "en": "Permissions"},
    "settings.section_avatar": {"tr": "Avatar", "en": "Avatar"},
    "settings.provider_type": {"tr": "Sağlayıcı", "en": "Provider"},
    "settings.provider_url": {"tr": "URL (boş = varsayılan)", "en": "URL (empty = default)"},
    "settings.provider_model": {"tr": "Model", "en": "Model"},
    "settings.refresh_models": {"tr": "Modelleri getir", "en": "Fetch models"},
    "settings.provider_key": {"tr": "API anahtarı", "en": "API key"},
    "settings.sc_host": {"tr": "SC host", "en": "SC host"},
    "settings.sc_port": {"tr": "SC port", "en": "SC port"},
    "settings.sc_key": {"tr": "SC anahtarı", "en": "SC key"},
    "settings.perm_default": {"tr": "İzin (*)", "en": "Permission (*)"},
    "settings.save": {"tr": "Kaydet", "en": "Save"},
    "settings.close": {"tr": "Kapat", "en": "Close"},
    "settings.lang_restart_note": {
        "tr": "Dil değişikliği uygulandı.",
        "en": "Language changed.",
    },
    "menu.settings": {"tr": "Ayarlar…", "en": "Settings…"},
    "menu.chat": {"tr": "Sohbet", "en": "Chat"},
    "menu.avatar": {"tr": "Karakter", "en": "Character"},
    "menu.quit": {"tr": "Çıkış", "en": "Quit"},
    "menu.switch_gui": {"tr": "Sohbet'e geç", "en": "Switch to Chat"},
    "confirmation.pending": {
        "tr": "onay bekleniyor",
        "en": "awaiting approval",
    },
    "confirmation.title": {
        "tr": "Araç İzni",
        "en": "Tool Permission",
    },
    "confirmation.question_default": {
        "tr": "{name} çalıştırılsın mı?",
        "en": "Run {name}?",
    },
    "confirmation.tool_line": {
        "tr": "Araç: {name}",
        "en": "Tool: {name}",
    },
    "confirmation.allow": {"tr": "İzin Ver", "en": "Allow"},
    "confirmation.deny": {"tr": "Reddet", "en": "Deny"},
    "chat.tool_started_line": {"tr": "{name} başladı", "en": "{name} started"},
    "chat.tool_finished_ok": {"tr": "{name} bitti (Tamam)", "en": "{name} done (OK)"},
    "chat.tool_finished_fail": {"tr": "{name} bitti (Hata)", "en": "{name} done (Error)"},
    "chat.activity_running": {"tr": "▸ {name} çalışıyor…", "en": "▸ {name} running…"},
    "chat.vision_disabled": {
        "tr": "Model görüntüleri desteklemiyor — sohbet görüntüler olmadan sürüyor.",
        "en": "This model does not support images — continuing without them.",
    },
    "avatar.dragging": {
        "tr": "Beni nereye götürüyorsun?",
        "en": "Where are you taking me?",
    },
    "chat.avatar_fallback": {
        "tr": "Avatar '{name}' bozuk — 'base' kullanılıyor",
        "en": "Avatar '{name}' broken — falling back to 'base'",
    },
    "chat.avatar_selected": {
        "tr": "Avatar '{name}' seçildi — yeniden başlatın",
        "en": "Avatar '{name}' selected — restart to apply",
    },
    "sessions.delete": {"tr": "Sohbeti sil", "en": "Delete chat"},
    "sessions.delete_confirm": {
        "tr": "'{title}' sohbeti kalıcı olarak silinsin mi?",
        "en": "Permanently delete the '{title}' chat?",
    },
    "sessions.delete_cancel": {"tr": "Vazgeç", "en": "Cancel"},
}


class I18n:
    def __init__(self, lang: str = "tr") -> None:
        if lang not in LANGUAGES:
            raise ValueError(f"unknown language: {lang}")
        self._lang = lang

    @property
    def current(self) -> str:
        return self._lang

    def set_language(self, lang: str) -> None:
        if lang not in LANGUAGES:
            raise ValueError(f"unknown language: {lang}")
        self._lang = lang
        language_bridge.changed.emit(lang)

    def t(self, key: str, **fmt: Any) -> str:
        try:
            entry = STRINGS[key]
        except KeyError as exc:
            raise MissingTranslationError(key) from exc
        text = entry.get(self._lang)
        if not text:
            raise MissingTranslationError(f"{key}/{self._lang}")
        if fmt:
            return text.format_map(fmt)
        return text


from PySide6.QtCore import QObject, Signal


class _LanguageBridge(QObject):
    changed = Signal(str)


language_bridge = _LanguageBridge()
i18n = I18n("tr")
