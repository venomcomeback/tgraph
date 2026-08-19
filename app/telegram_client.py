"""
TGraph - Telethon Sarmalayıcı
Session yönetimi, proxy desteği, üye tarama/ekleme, spam testi.
"""
import os
import datetime
from typing import Optional, Dict, Any, List, Callable

from telethon import TelegramClient, functions, errors
from telethon.tl.types import (
    UserStatusOnline, UserStatusOffline, UserStatusRecently,
    UserStatusLastWeek, UserStatusLastMonth, ChannelParticipantsSearch,
)
from telethon.tl.functions.channels import (
    GetParticipantsRequest, InviteToChannelRequest, JoinChannelRequest,
)
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, UserNotMutualContactError,
    PeerFloodError, UserChannelsTooMuchError, ChatWriteForbiddenError,
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError,
    UserAlreadyParticipantError,
)

from .config import SESSIONS_DIR


def build_proxy(proxy: Optional[Dict[str, Any]]):
    """DB proxy kaydını Telethon proxy tuple'ına çevirir."""
    if not proxy or not proxy.get("host"):
        return None
    try:
        import socks
    except ImportError:
        return None
    ptype = (proxy.get("proxy_type") or "socks5").lower()
    proxy_type = socks.SOCKS5 if ptype == "socks5" else socks.HTTP
    host = proxy.get("host")
    port = int(proxy.get("port") or 0)
    username = proxy.get("username") or None
    password = proxy.get("password") or None
    if username:
        return (proxy_type, host, port, True, username, password)
    return (proxy_type, host, port)


def session_path(session_name: str) -> str:
    """Session dosyasının tam yolu (.session uzantısız Telethon bekler)."""
    name = session_name
    if name.endswith(".session"):
        name = name[:-8]
    if os.path.isabs(name):
        return name
    return os.path.join(SESSIONS_DIR, name)


class TGClient:
    """Tek bir Telegram hesabı için Telethon istemci sarmalayıcısı."""

    def __init__(self, session_name: str, api_id: int, api_hash: str,
                 proxy: Optional[Dict[str, Any]] = None):
        self.session_name = session_name
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.proxy = proxy
        self.client: Optional[TelegramClient] = None

    def _make_client(self) -> TelegramClient:
        return TelegramClient(
            session_path(self.session_name),
            self.api_id,
            self.api_hash,
            proxy=build_proxy(self.proxy),
            device_model="TGraph",
            system_version="1.0",
            app_version="1.0.0",
        )

    async def connect(self) -> bool:
        if self.client is None:
            self.client = self._make_client()
        if not self.client.is_connected():
            await self.client.connect()
        return await self.client.is_user_authorized()

    async def disconnect(self):
        if self.client and self.client.is_connected():
            await self.client.disconnect()

    async def get_me(self) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        me = await self.client.get_me()
        if not me:
            return None
        return {
            "id": me.id,
            "phone": me.phone or "",
            "username": me.username or "",
            "first_name": me.first_name or "",
            "last_name": me.last_name or "",
            "name": (f"{me.first_name or ''} {me.last_name or ''}").strip(),
        }

    # ------------------------------------------------------------------ #
    #  Giriş akışı (OTP + 2FA)
    # ------------------------------------------------------------------ #
    async def send_code(self, phone: str):
        if self.client is None:
            self.client = self._make_client()
        if not self.client.is_connected():
            await self.client.connect()
        return await self.client.send_code_request(phone)

    async def sign_in(self, phone: str, code: str, phone_code_hash: str = None,
                      password: str = None):
        """OTP kod ve gerekirse 2FA şifresi ile giriş yapar."""
        try:
            await self.client.sign_in(
                phone=phone, code=code, phone_code_hash=phone_code_hash
            )
        except SessionPasswordNeededError:
            if not password:
                raise
            await self.client.sign_in(password=password)
        return await self.get_me()

    async def sign_in_password(self, password: str):
        await self.client.sign_in(password=password)
        return await self.get_me()

    # ------------------------------------------------------------------ #
    #  Grup katılma
    # ------------------------------------------------------------------ #
    async def join_group(self, link: str):
        link = link.strip()
        if "joinchat/" in link or "/+" in link:
            invite_hash = link.split("joinchat/")[-1].split("/+")[-1].replace("+", "")
            invite_hash = invite_hash.split("/")[-1]
            try:
                return await self.client(ImportChatInviteRequest(invite_hash))
            except UserAlreadyParticipantError:
                return await self.client.get_entity(link)
        else:
            username = link.replace("https://t.me/", "").replace("@", "").strip("/")
            try:
                return await self.client(JoinChannelRequest(username))
            except UserAlreadyParticipantError:
                return await self.client.get_entity(username)

    async def get_entity(self, link: str):
        link = link.strip()
        if link.startswith("https://t.me/") or link.startswith("t.me/"):
            link = link.split("t.me/")[-1].strip("/")
        if not ("joinchat" in link or link.startswith("+")):
            link = link.replace("@", "")
        return await self.client.get_entity(link)

    # ------------------------------------------------------------------ #
    #  Üye tarama
    # ------------------------------------------------------------------ #
    @staticmethod
    def _last_seen_label(status) -> str:
        if isinstance(status, UserStatusOnline):
            return "Çevrimiçi"
        if isinstance(status, UserStatusOffline):
            return status.was_online.strftime("%Y-%m-%d %H:%M") if status.was_online else "Çevrimdışı"
        if isinstance(status, UserStatusRecently):
            return "Yakınlarda"
        if isinstance(status, UserStatusLastWeek):
            return "Son hafta"
        if isinstance(status, UserStatusLastMonth):
            return "Son ay"
        return "Bilinmiyor"

    @staticmethod
    def _last_seen_days(status) -> Optional[int]:
        """Son görülmeyi gün cinsinden yaklaşık döndürür (filtreleme için)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        if isinstance(status, UserStatusOnline):
            return 0
        if isinstance(status, UserStatusRecently):
            return 1
        if isinstance(status, UserStatusLastWeek):
            return 7
        if isinstance(status, UserStatusLastMonth):
            return 30
        if isinstance(status, UserStatusOffline) and status.was_online:
            delta = now - status.was_online
            return delta.days
        return None

    async def scrape_members(self, group_link: str,
                             progress_cb: Optional[Callable[[int, int], None]] = None,
                             should_stop: Optional[Callable[[], bool]] = None,
                             filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Grup üyelerini tarar ve filtreye uyanları döndürür."""
        filters = filters or {}
        entity = await self.get_entity(group_link)
        result: List[Dict[str, Any]] = []

        exclude_bots = filters.get("exclude_bots", False)
        require_phone = filters.get("require_phone", False)
        last_seen_max_days = filters.get("last_seen_days", None)
        lang_filter = (filters.get("lang", "") or "").strip().lower()

        total = 0
        try:
            full = await self.client.get_entity(entity)
            total = getattr(full, "participants_count", 0) or 0
        except Exception:
            total = 0

        offset = 0
        limit = 200
        collected = 0
        while True:
            if should_stop and should_stop():
                break
            try:
                participants = await self.client(GetParticipantsRequest(
                    channel=entity,
                    filter=ChannelParticipantsSearch(""),
                    offset=offset,
                    limit=limit,
                    hash=0,
                ))
            except FloodWaitError as e:
                raise e
            if not participants.users:
                break
            for user in participants.users:
                collected += 1
                # Filtreler
                if exclude_bots and user.bot:
                    continue
                if require_phone and not user.phone:
                    continue
                days = self._last_seen_days(user.status)
                if last_seen_max_days is not None:
                    if days is None or days > last_seen_max_days:
                        continue
                if lang_filter and (user.lang_code or "").lower() != lang_filter:
                    continue
                result.append({
                    "user_id": user.id,
                    "access_hash": user.access_hash,
                    "username": user.username or "",
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "phone": user.phone or "",
                    "last_seen": self._last_seen_label(user.status),
                    "lang_code": user.lang_code or "",
                    "is_bot": 1 if user.bot else 0,
                    "group_source": group_link,
                })
            offset += len(participants.users)
            if progress_cb:
                progress_cb(collected, max(total, collected))
            if len(participants.users) < limit:
                break
        return result

    # ------------------------------------------------------------------ #
    #  Üye ekleme
    # ------------------------------------------------------------------ #
    async def add_member(self, target_group, member: Dict[str, Any], by_username: bool = False):
        """
        Tek bir üyeyi hedef gruba ekler.
        Dönüş: (success: bool, message: str)
        FloodWaitError yukarı fırlatılır (worker yakalar).
        """
        try:
            if by_username and member.get("username"):
                user_entity = await self.client.get_entity(member["username"])
            else:
                from telethon.tl.types import InputPeerUser
                user_entity = InputPeerUser(
                    int(member["user_id"]), int(member.get("access_hash") or 0)
                )
            await self.client(InviteToChannelRequest(target_group, [user_entity]))
            return True, "Eklendi"
        except FloodWaitError:
            raise
        except PeerFloodError:
            return False, "PeerFlood - Hesap spam limitine takıldı"
        except UserPrivacyRestrictedError:
            return False, "Gizlilik ayarları eklemeye izin vermiyor"
        except UserNotMutualContactError:
            return False, "Karşılıklı kişi değil"
        except UserChannelsTooMuchError:
            return False, "Kullanıcı çok fazla grupta"
        except UserAlreadyParticipantError:
            return True, "Zaten üye"
        except ChatWriteForbiddenError:
            return False, "Gruba yazma izni yok"
        except (ValueError, TypeError) as e:
            return False, f"Geçersiz kullanıcı: {e}"
        except Exception as e:
            return False, f"Hata: {e}"

    # ------------------------------------------------------------------ #
    #  Spam testi (@SpamBot)
    # ------------------------------------------------------------------ #
    async def check_spam_status(self) -> Dict[str, str]:
        """@SpamBot'a mesaj atıp cevabı yorumlar."""
        try:
            spambot = await self.client.get_entity("SpamBot")
            await self.client.send_message(spambot, "/start")
            import asyncio
            await asyncio.sleep(2)
            messages = await self.client.get_messages(spambot, limit=1)
            if not messages:
                return {"status": "unknown", "detail": "Cevap alınamadı"}
            text = messages[0].message or ""
            low = text.lower()
            if "no limits" in low or "free as a bird" in low or "good news" in low:
                return {"status": "ok", "detail": "Kısıtlama yok"}
            if "is limited until" in low or "restricted" in low or "will be able to" in low:
                return {"status": "spam", "detail": text[:200]}
            if "banned" in low:
                return {"status": "banned", "detail": text[:200]}
            return {"status": "ok", "detail": text[:200]}
        except FloodWaitError as e:
            return {"status": "spam", "detail": f"FloodWait: {e.seconds}s"}
        except Exception as e:
            return {"status": "banned", "detail": f"Bağlanamadı: {e}"}
