import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import json
import uuid
import asyncio
import aiohttp
import re
import io
from bs4 import BeautifulSoup

load_dotenv()

# ========== 설정 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID"))
AUTH_ADMIN_CHANNEL_ID = int(os.getenv("AUTH_ADMIN_CHANNEL_ID", "1483398777904828416"))
CLASSIC_ADMIN_CHANNEL_ID = int(os.getenv("CLASSIC_ADMIN_CHANNEL_ID", "1498705911857020980"))
NEW_ACCOUNT_ALERT_CHANNEL_ID = int(os.getenv("NEW_ACCOUNT_ALERT_CHANNEL_ID", "1498713704815132714"))
DM_LOG_CHANNEL_ID = int(os.getenv("DM_LOG_CHANNEL_ID", "1498706689367474256"))
JOIN_LOG_CHANNEL_ID = int(os.getenv("JOIN_LOG_CHANNEL_ID", "0"))
HISTORY_FILE = "/data/nickname_history.json"
PENDING_FILE = "/data/pending_approvals.json"
WEEKLY_LIMIT = 1
AUTH_PENDING_FILE = "/data/auth_pending.json"
HANDS_AUTH_ROLE = "「핸즈 & 인증유저」"
JOIN_TRACKER_FILE = "/data/join_tracker.json"
DAILY_STATS_FILE = "/data/daily_stats.json"
DAILY_AUTH_LIST_FILE = "/data/daily_auth_list.json"
DAILY_DM_USERS_FILE = "/data/daily_dm_users.json"
NEXON_API_KEY = os.getenv("NEXON_API_KEY")
NEXON_API_BASE = "https://open.api.nexon.com/maplestory/v1"
MAPLE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://maplestory.nexon.com/",
}
# ==========================

# 서버명 → 역할명 매핑 (챌린저스 1~4는 모두 챌린저스 역할)
SERVER_ROLES = {
    "챌린저스1": "챌린저스",
    "챌린저스2": "챌린저스",
    "챌린저스3": "챌린저스",
    "챌린저스4": "챌린저스",
    "스카니아": "스카니아",
    "루나": "루나",
    "엘리시움": "엘리시움",
    "크로아": "크로아",
    "베라": "베라",
    "오로라": "오로라",
    "에오스": "에오스",
    "헬리오스": "헬리오스",
    "유니온": "유니온",
    "이노시스": "이노시스",
    "레드": "레드",
    "아케인": "아케인",
    "노바": "노바",
    "제니스": "제니스",
    "메이플랜드": "메이플랜드",
    "메이플플래닛": "메이플플래닛",
}

AUTH_SERVER_LIST = [
    "챌린저스1", "챌린저스2", "챌린저스3", "챌린저스4",
    "스카니아", "루나", "엘리시움", "크로아", "베라", "오로라",
    "에오스", "헬리오스", "유니온", "이노시스", "레드",
    "아케인", "노바", "제니스", "메이플랜드", "메이플플래닛"
]

auth_flow_data = {}  # user_id -> {"server": str, "method": str}
nick_flow_data = {}  # user_id -> {"server": str}

_saved_stats = {}
if os.path.exists(DAILY_STATS_FILE):
    try:
        with open(DAILY_STATS_FILE, "r", encoding="utf-8") as _f:
            _saved_stats = json.load(_f)
    except Exception:
        pass

daily_join_count = _saved_stats.get("daily_join_count", 0)
daily_leave_count = _saved_stats.get("daily_leave_count", 0)
daily_leave_has_role = _saved_stats.get("daily_leave_has_role", 0)
daily_leave_no_role = _saved_stats.get("daily_leave_no_role", 0)
daily_leave_underage = _saved_stats.get("daily_leave_underage", 0)
daily_auth_approve = _saved_stats.get("daily_auth_approve", 0)
daily_auth_reject = _saved_stats.get("daily_auth_reject", 0)
daily_bot_dm_count = _saved_stats.get("daily_bot_dm_count", 0)

weekly_join_count = _saved_stats.get("weekly_join_count", 0)
weekly_leave_count = _saved_stats.get("weekly_leave_count", 0)
weekly_leave_has_role = _saved_stats.get("weekly_leave_has_role", 0)
weekly_leave_no_role = _saved_stats.get("weekly_leave_no_role", 0)
weekly_leave_underage = _saved_stats.get("weekly_leave_underage", 0)
weekly_auth_approve = _saved_stats.get("weekly_auth_approve", 0)
weekly_auth_reject = _saved_stats.get("weekly_auth_reject", 0)
weekly_bot_dm_count = _saved_stats.get("weekly_bot_dm_count", 0)

daily_auth_list: list[dict] = []
if os.path.exists(DAILY_AUTH_LIST_FILE):
    try:
        with open(DAILY_AUTH_LIST_FILE, "r", encoding="utf-8") as _f:
            daily_auth_list = json.load(_f)
    except Exception:
        pass

daily_dm_user_ids: set[int] = set()
if os.path.exists(DAILY_DM_USERS_FILE):
    try:
        with open(DAILY_DM_USERS_FILE, "r", encoding="utf-8") as _f:
            daily_dm_user_ids = set(json.load(_f))
    except Exception:
        pass

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot._tasks_started = False


# ========== 신청 기록 관리 ==========
def ensure_data_dir():
    os.makedirs("/data", exist_ok=True)

def _load_json(path: str, default=None):
    if default is None:
        default = {}
    ensure_data_dir()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def _save_json(path: str, data, indent: int = None):
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)

def load_history() -> dict:
    return _load_json(HISTORY_FILE)

def save_history(history: dict):
    _save_json(HISTORY_FILE, history, indent=2)

def get_weekly_count(user_id: str) -> int:
    history = load_history()
    records = history.get(user_id, [])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return sum(1 for r in records if r["date"] >= cutoff)

def record_change(user_id: str, previous: str, new: str):
    history = load_history()
    if user_id not in history:
        history[user_id] = []
    history[user_id].append({
        "date": datetime.now(timezone.utc).isoformat(),
        "previous": previous,
        "new": new
    })
    save_history(history)

def load_join_tracker() -> dict:
    return _load_json(JOIN_TRACKER_FILE)

def save_join_tracker(data: dict):
    _save_json(JOIN_TRACKER_FILE, data, indent=2)

def save_daily_stats():
    _save_json(DAILY_STATS_FILE, {
        "daily_join_count": daily_join_count,
        "daily_leave_count": daily_leave_count,
        "daily_leave_has_role": daily_leave_has_role,
        "daily_leave_no_role": daily_leave_no_role,
        "daily_leave_underage": daily_leave_underage,
        "daily_auth_approve": daily_auth_approve,
        "daily_auth_reject": daily_auth_reject,
        "daily_bot_dm_count": daily_bot_dm_count,
        "weekly_join_count": weekly_join_count,
        "weekly_leave_count": weekly_leave_count,
        "weekly_leave_has_role": weekly_leave_has_role,
        "weekly_leave_no_role": weekly_leave_no_role,
        "weekly_leave_underage": weekly_leave_underage,
        "weekly_auth_approve": weekly_auth_approve,
        "weekly_auth_reject": weekly_auth_reject,
        "weekly_bot_dm_count": weekly_bot_dm_count,
    }, indent=2)

def save_daily_auth_list():
    _save_json(DAILY_AUTH_LIST_FILE, daily_auth_list, indent=2)

def save_daily_dm_users():
    _save_json(DAILY_DM_USERS_FILE, list(daily_dm_user_ids))

def load_pending() -> dict:
    return _load_json(PENDING_FILE)

def save_pending(pending: dict):
    _save_json(PENDING_FILE, pending, indent=2)

def add_pending(request_id: str, user_id: int, previous: str, new: str, new_server: str = None):
    pending = load_pending()
    pending[request_id] = {
        "user_id": user_id,
        "previous": previous,
        "new": new,
        "new_server": new_server
    }
    save_pending(pending)

def remove_pending(request_id: str):
    pending = load_pending()
    pending.pop(request_id, None)
    save_pending(pending)


async def _disable_view(interaction: discord.Interaction, view: discord.ui.View):
    for child in view.children:
        child.disabled = True
    try:
        await interaction.response.defer()
    except Exception:
        pass
    await interaction.message.edit(view=view)


async def update_server_role(member: discord.Member, new_server: str):
    new_role_name = SERVER_ROLES.get(new_server)
    if new_role_name:
        new_role = discord.utils.get(member.guild.roles, name=new_role_name)
        if new_role:
            try:
                await member.add_roles(new_role)
                return True
            except discord.Forbidden:
                return False
    return False


# ========== 인증 신청 기록 관리 ==========
def load_auth_pending() -> dict:
    return _load_json(AUTH_PENDING_FILE)

def save_auth_pending(pending: dict):
    _save_json(AUTH_PENDING_FILE, pending, indent=2)

def add_auth_pending(request_id: str, user_id: int, server: str, level: str, nickname: str, method: str, is_underage: bool = False):
    pending = load_auth_pending()
    pending[request_id] = {
        "user_id": user_id,
        "server": server,
        "level": level,
        "nickname": nickname,
        "method": method,
        "is_underage": is_underage
    }
    save_auth_pending(pending)

def remove_auth_pending(request_id: str):
    pending = load_auth_pending()
    pending.pop(request_id, None)
    save_auth_pending(pending)


# ========== 인증 - 사진 전송 여부 확인 ==========
class AuthPhotoCheckView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="✅ 네, 인증사진 보냈어요", style=discord.ButtonStyle.success, custom_id="auth_photo_yes")
    async def photo_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        auth_flow_data[interaction.user.id] = {"method": "DM"}
        view = AuthServerSelectView()
        await interaction.response.edit_message(
            content="📋 메이플 서버를 선택해주세요:",
            view=view
        )

    @discord.ui.button(label="❌ 아니요, 아직 안보냈어요", style=discord.ButtonStyle.secondary, custom_id="auth_photo_no")
    async def photo_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.user.send(
                "🍁 **메이플 디스코드 입장 안내**\n\n"
                "인증 사진을 보내시지 않으셔서 재 안내 드립니다.\n\n"
                "인증 채널을 참고 해서 사진을 꼭 먼저 보내주세요"
            )
        except discord.Forbidden:
            pass
        await interaction.response.edit_message(
            content="📨 인증 안내 DM을 발송했습니다.\n인증 사진 전송 후 다시 인증 신청 버튼을 눌러주세요!",
            view=None
        )


# ========== 인증 - 서버 선택 드롭다운 ==========
class AuthServerSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="메이플 서버를 선택하세요",
        custom_id="auth_server_select",
        options=[discord.SelectOption(label=s, value=s) for s in AUTH_SERVER_LIST]
    )
    async def server_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        server = select.values[0]
        if server in ("메이플플래닛", "메이플랜드"):
            await interaction.response.send_modal(ClassicAuthModal(server=server))
        else:
            data = auth_flow_data.get(interaction.user.id, {})
            data["server"] = server
            auth_flow_data[interaction.user.id] = data
            await interaction.response.send_modal(AuthModal())


# ========== 클래식 서버 인증 모달 (레벨 + 닉네임, 즉시 승인) ==========
class ClassicAuthModal(discord.ui.Modal, title="인증 신청"):
    level = discord.ui.TextInput(label="레벨", placeholder="숫자만 입력", max_length=4)
    nickname = discord.ui.TextInput(label="닉네임", placeholder="게임 내 캐릭터 닉네임", max_length=20)

    def __init__(self, server: str):
        super().__init__()
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        level_val = self.level.value.strip()
        if not level_val.isdigit() or int(level_val) < 1:
            await interaction.response.send_message("❌ 레벨이 잘못 적혀있습니다.", ephemeral=True)
            return

        nickname_val = self.nickname.value.strip()
        combined_nick = f"{self.server}/{level_val}/{nickname_val}"
        days = (datetime.now(timezone.utc) - interaction.user.created_at).days

        admin_channel = bot.get_channel(CLASSIC_ADMIN_CHANNEL_ID)

        # 30일 미만 계정 → 관리자 승인 필요
        if days < 30:
            if not admin_channel:
                await interaction.response.send_message("❌ 관리자 채널을 찾을 수 없습니다.", ephemeral=True)
                return
            request_id = str(uuid.uuid4())[:8]
            add_auth_pending(request_id, interaction.user.id, self.server, level_val, nickname_val, "DM", is_underage=True)
            view = AuthApproveView(request_id=request_id, is_underage=True)
            bot.add_view(view)
            await interaction.response.send_message(
                "⚠️ 디스코드 가입 30일 미만 계정은 관리자 확인 후 처리됩니다.", ephemeral=True
            )
            await admin_channel.send(
                f"🔐 **인증 신청** ({self.server}) ⚠️ 30일 미만 계정\n"
                f"신청자: {interaction.user.mention}\n"
                f"서버: **{self.server}** | 레벨: **{level_val}** | 닉네임: **{nickname_val}**\n"
                f"닉네임 변경: `{interaction.user.display_name}` → `{combined_nick}`",
                view=view
            )
            return

        # 정상 계정 → 즉시 자동 승인
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ 유저 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        old_nick = member.display_name
        try:
            await member.edit(nick=combined_nick)
        except discord.Forbidden:
            pass

        await update_server_role(member, self.server)
        await interaction.response.send_message("✅ 인증이 완료됐어요! 역할이 부여되었습니다.", ephemeral=True)

        try:
            await member.send(
                f"**{self.server} 승인 완료**\n\n"
                "★ 거래 전 주의 사항 참고 하세요★\n"
                "https://www.maplediscord.com/tip\n\n"
                "★친구초대★\n"
                "친구에게 디스코드 채널 소개 해주세요\n"
                "디스코드 초대링크 : https://discord.gg/2UwBw8dnSv\n"
                "좋은 하루 보내세요!"
            )
        except discord.Forbidden:
            pass

        if admin_channel:
            try:
                await admin_channel.send(
                    f"✅ **자동 인증 완료** ({self.server})\n"
                    f"신청자: {member.mention}\n"
                    f"닉네임 변경: `{old_nick}` → `{combined_nick}`"
                )
            except discord.Forbidden:
                pass


# ========== 인증 모달 (레벨 + 닉네임) ==========
class AuthModal(discord.ui.Modal, title="인증 신청"):
    level = discord.ui.TextInput(
        label="레벨",
        placeholder="숫자만 입력 (1~300)",
        max_length=3
    )
    nickname = discord.ui.TextInput(
        label="닉네임",
        placeholder="게임 내 캐릭터 닉네임",
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        days = (datetime.now(timezone.utc) - interaction.user.created_at).days
        if days < 30:
            try:
                await interaction.user.send(
                    f"디스코드 가입일이 30일 미만 계정은 역할 부여가 제한 됩니다.\n"
                    f"다른 디스코드 아이디로 재 신청 또는 30일 뒤에 재 신청 부탁 드립니다."
                )
            except discord.Forbidden:
                pass

        data = auth_flow_data.get(interaction.user.id, {})
        server = data.get("server")
        method = data.get("method", "DM")

        if not server:
            await interaction.response.send_message("❌ 처음부터 다시 신청해주세요.", ephemeral=True)
            return

        level_val = self.level.value.strip()
        if not level_val.isdigit() or not (1 <= int(level_val) <= 300):
            await interaction.response.send_message(
                "❌ 레벨이 잘못 적혀있습니다. 1~300 사이의 숫자만 입력해주세요.",
                ephemeral=True
            )
            return

        nickname_val = self.nickname.value.strip()
        combined_nick = f"{server}/{level_val}/{nickname_val}"

        auth_flow_data.pop(interaction.user.id, None)

        admin_channel = bot.get_channel(AUTH_ADMIN_CHANNEL_ID)
        if not admin_channel:
            await interaction.response.send_message("❌ 관리자 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        is_underage = days < 30
        request_id = str(uuid.uuid4())[:8]
        add_auth_pending(request_id, interaction.user.id, server, level_val, nickname_val, method, is_underage)

        view = AuthApproveView(request_id=request_id, is_underage=is_underage)
        bot.add_view(view)

        await interaction.response.send_message(
            "✅ 인증 신청이 완료됐어요!\n관리자 확인 후 2시간 이내에 처리됩니다.",
            ephemeral=True
        )

        nick_check = await check_nickname_changed(nickname_val)

        await admin_channel.send(
            f"🔐 **인증 신청**\n"
            f"신청자: {interaction.user.mention}\n"
            f"서버: **{server}** | 레벨: **{level_val}** | 닉네임: **{nickname_val}**\n"
            f"닉네임 변경: `{interaction.user.display_name}` → `{combined_nick}`\n"
            f"📊 닉네임 변경 이력 (3개월): {nick_check}",
            view=view
        )


# ========== 인증 관리자 승인/거절 ==========
class AuthApproveView(discord.ui.View):
    def __init__(self, request_id: str, is_underage: bool = False):
        super().__init__(timeout=None)
        self.request_id = request_id

        approve_btn = discord.ui.Button(
            label="✅ 승인",
            style=discord.ButtonStyle.success,
            custom_id=f"auth_approve_{request_id}"
        )
        reject_btn = discord.ui.Button(
            label="❌ 거절",
            style=discord.ButtonStyle.danger,
            custom_id=f"auth_reject_{request_id}"
        )
        no_photo_btn = discord.ui.Button(
            label="📷 인증사진 미첨부",
            style=discord.ButtonStyle.secondary,
            custom_id=f"auth_no_photo_{request_id}"
        )
        approve_btn.callback = self.approve
        reject_btn.callback = self.reject
        no_photo_btn.callback = self.no_photo
        self.add_item(approve_btn)
        self.add_item(reject_btn)
        self.add_item(no_photo_btn)

        if is_underage:
            underage_btn = discord.ui.Button(
                label="⚠️ 30일 미만 계정",
                style=discord.ButtonStyle.secondary,
                custom_id=f"auth_underage_{request_id}"
            )
            underage_btn.callback = self.underage
            self.add_item(underage_btn)

    def _parse_message(self, content: str):
        user_match = re.search(r'<@(\d+)>', content)
        server_match = re.search(r'서버: \*\*(.+?)\*\*', content)
        level_match = re.search(r'레벨: \*\*(.+?)\*\*', content)
        nick_match = re.search(r'닉네임: \*\*(.+?)\*\*', content)
        if not all([user_match, server_match, level_match, nick_match]):
            return None
        return {
            "user_id": int(user_match.group(1)),
            "server": server_match.group(1),
            "level": level_match.group(1),
            "nickname": nick_match.group(1),
        }

    async def approve(self, interaction: discord.Interaction):
        global daily_auth_approve, daily_auth_list
        daily_auth_approve += 1
        save_daily_stats()
        pending = load_auth_pending()
        data = pending.get(self.request_id)
        if not data:
            data = self._parse_message(interaction.message.content)
        if not data:
            await interaction.channel.send("❌ 신청 데이터를 찾을 수 없습니다.")
            return

        member = interaction.guild.get_member(data["user_id"])
        if not member:
            await interaction.channel.send("❌ 유저를 찾을 수 없습니다.")
            return

        if not all(k in data for k in ("server", "level", "nickname")):
            await interaction.channel.send("❌ 신청 데이터가 불완전합니다. 다시 신청해주세요.")
            return
        combined_nick = f"{data['server']}/{data['level']}/{data['nickname']}"

        try:
            await member.edit(nick=combined_nick)
        except discord.Forbidden:
            await interaction.channel.send("❌ 닉네임 변경 권한 부족!")
            return

        await update_server_role(member, data["server"])

        # 메이플랜드/메이플플래닛은 인증유저 역할 미부여
        if data["server"] not in ("메이플랜드", "메이플플래닛"):
            auth_role = discord.utils.get(interaction.guild.roles, name=HANDS_AUTH_ROLE)
            if auth_role:
                try:
                    await member.add_roles(auth_role)
                except discord.Forbidden:
                    pass

        remove_auth_pending(self.request_id)

        try:
            await member.send(
                "**[인증 완료]**\n\n"
                "★ 거래 전 주의 사항 참고 하세요★\n"
                "https://www.maplediscord.com/tip\n\n"
                "★친구초대★\n"
                "친구에게 디스코드 채널 소개 해주세요\n"
                "디스코드 초대링크 : https://discord.gg/2UwBw8dnSv\n"
                "좋은 하루 보내세요!"
            )
        except discord.Forbidden:
            pass

        await _disable_view(interaction, self)
        daily_auth_list.append({"user_id": member.id, "nick": combined_nick})
        save_daily_auth_list()
        await interaction.channel.send(
            f"✅ {member.mention} 인증 완료!\n닉네임: `{combined_nick}` | 역할 부여 완료"
        )

    async def reject(self, interaction: discord.Interaction):
        global daily_auth_reject
        daily_auth_reject += 1
        save_daily_stats()
        pending = load_auth_pending()
        data = pending.get(self.request_id)
        if not data:
            data = self._parse_message(interaction.message.content)

        member = None
        if data:
            member = interaction.guild.get_member(data["user_id"])
        remove_auth_pending(self.request_id)

        if member:
            try:
                await member.send(
                    "🚨 **메이플 디스코드 인증 미승인 안내**\n\n"
                    "아래와 같은 항목 중 하나에 해당하여\n"
                    "메이플 디스코드 인증이 미승인 되었습니다.\n\n"
                    "1️⃣ 디스코드 가입일이 30일 이내인 계정\n\n"
                    "2️⃣ 메이플스토리 인증 사진이 정상적으로 첨부되지 않은 경우\n"
                    "　→ 메이플 디스코드 입장 방법(인증 · 사진 전송 방법)을 참고해 주세요.\n\n"
                    "3️⃣ 캐릭터 확인 결과,\n"
                    "　최근 1주일간 레벨 변동이 없거나\n"
                    "　사냥에 필요한 장비 및 아이템이 착용되어 있지 않은 경우\n"
                    "　메소만 판매 하실경우 경매장 판매 내역도 같이 보내주세요\n\n"
                    "위 항목에 해당하지 않음에도 인증이 거절되었다면,\n"
                    "메이플 디스코드 관리자에게 문의해 주시기 바랍니다."
                )
            except discord.Forbidden:
                pass

        await _disable_view(interaction, self)
        if data:
            user_str = member.mention if member else f"`{data.get('user_id')}`"
            server = data.get('server', '?')
            nickname = data.get('nickname', '?')
            await interaction.channel.send(
                f"❌ 인증 신청 거절 완료\n"
                f"신청자: {user_str} | 서버: {server} | 닉네임: {nickname}"
            )
        else:
            await interaction.channel.send("❌ 인증 신청 거절 완료")

    async def underage(self, interaction: discord.Interaction):
        pending = load_auth_pending()
        data = pending.get(self.request_id)
        if not data:
            data = self._parse_message(interaction.message.content)

        member = None
        if data:
            member = interaction.guild.get_member(data["user_id"])
        remove_auth_pending(self.request_id)

        if member:
            try:
                await member.send(
                    "**[메이플디스코드 인증 안내]**\n\n"
                    "선생님, 저희 채널 디스코드 정책상\n"
                    "30일 미만 계정은 인증 후 역할 부여가 안됩니다.\n\n"
                    "30일 이후 재신청 하시거나\n"
                    "다른 아이디로 재신청 부탁드립니다."
                )
            except discord.Forbidden:
                pass

        await _disable_view(interaction, self)
        await interaction.channel.send("⚠️ 30일 미만 계정 안내 DM 발송 완료")

    async def no_photo(self, interaction: discord.Interaction):
        pending = load_auth_pending()
        data = pending.get(self.request_id)
        if not data:
            data = self._parse_message(interaction.message.content)

        member = None
        if data:
            member = interaction.guild.get_member(data["user_id"])

        if member:
            try:
                await member.send(
                    "**1. 인증 사진이 관리자 DM으로 오지 않았습니다.**\n"
                    "인증 채널 참고후 인증 사진을 디스코드 채널 관리자에게 보내주세요\n\n"
                    "저는 봇 이라서 저에게 보내시면 안됩니다\n\n"
                    "두곳중 한곳에 인증 사진을 보내주시면 됩니다.\n\n"
                    "- 메이플 디스코드 채널 오른쪽 상단에 있는 **[MS.D] - 관리자** 에게 보내주세요.\n"
                    "- 인증채널 dm 관리자 문의 옆에 **[MS.D] - 관리자** 에게 보내시면 됩니다"
                )
            except discord.Forbidden:
                pass

        # 인증사진 미첨부 버튼만 비활성화, 승인/거절은 유지
        for child in self.children:
            if hasattr(child, 'custom_id') and child.custom_id == f"auth_no_photo_{self.request_id}":
                child.disabled = True
        try:
            await interaction.response.defer()
        except Exception:
            pass
        await interaction.message.edit(view=self)
        await interaction.channel.send("📷 인증사진 미첨부 안내 DM 발송 완료")


# ========== 인증 버튼 패널 ==========
class AuthButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔐 인증 신청", style=discord.ButtonStyle.success, custom_id="auth_request")
    async def auth_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AuthPhotoCheckView()
        await interaction.response.send_message(
            "📸 인증 사진을 보내셨나요?",
            view=view,
            ephemeral=True
        )


@bot.tree.command(name="인증패널", description="인증 신청 버튼 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def auth_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async for message in interaction.channel.history(limit=200):
        if message.author == bot.user and message.embeds:
            if "꼭 관리자에게 인증 사진" in (message.embeds[0].description or "") or message.embeds[0].title == "인증 신청 방법":
                await message.delete()

    embed = discord.Embed(
        description="꼭 인증 사진을 보내시고 인증 신청 버튼 눌러주세요\n\n⏱️ 신청 후 **2시간 이내**에 처리됩니다.",
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=AuthButtonView())
    await interaction.followup.send("✅ 인증 패널 생성 완료!", ephemeral=True)


@auth_panel.error
async def auth_panel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ 오류 발생: {error}", ephemeral=True)


# ========== 신고 패널 재등록 (디바운스, 채널별) ==========
async def _repost_panel(channel_id: int):
    await asyncio.sleep(1)  # 1초 대기 (메시지 폭탄 시 마지막 메시지 후 1번만 실행)
    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            print(f"[REPOST] 채널을 찾을 수 없음 (id={channel_id})")
            return
        key = str(channel_id)
        old_message_id = report_panel_info.get(key)
        if old_message_id:
            try:
                old_msg = await channel.fetch_message(old_message_id)
                await old_msg.delete()
                print(f"[REPOST] 기존 패널 삭제 완료 (id={old_message_id})")
            except Exception as e:
                print(f"[REPOST] 기존 패널 삭제 실패: {e}")
        embed = discord.Embed(
            title="🚨 사기 신고 민원",
            description=(
                "✅ **사기 의심 유형** - 아래 사례는 즉시 신고해 주세요.\n\n"
                "• 당일 가입한 디스코드 계정으로 친구 추가 후 거래\n"
                "• 연락처(폰번호) 미제공\n"
                "• 게임 내 거래 없이 경매장 거래만 유도\n"
                "• 외부라 핸즈로 거래 하겠다 100% 사기입니다.\n\n"
                "아래 버튼을 눌러 신고를 접수해 주세요."
            ),
            color=discord.Color.red()
        )
        new_msg = await channel.send(embed=embed, view=ReportButtonView())
        report_panel_info[key] = new_msg.id
        save_report_panel_info(report_panel_info)
        print(f"[REPOST] 신고 패널 재등록 완료 (channel={channel_id}, id={new_msg.id})")
    except asyncio.CancelledError:
        raise  # 취소는 다시 던져야 정상 취소 처리됨
    except Exception as e:
        print(f"[REPOST] 패널 재등록 실패 (channel={channel_id}): {e}")


# ========== 봇 DM 자동 응답 ==========
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if isinstance(message.channel, discord.DMChannel):
        global daily_bot_dm_count
        if message.author.id not in daily_dm_user_ids:
            daily_dm_user_ids.add(message.author.id)
            daily_bot_dm_count += 1
            save_daily_stats()
            save_daily_dm_users()
        admin_ch = bot.get_channel(DM_LOG_CHANNEL_ID)
        if admin_ch:
            try:
                await admin_ch.send(f"📨 {message.author.mention} 님이 봇에게 DM을 보냈습니다.")
            except discord.Forbidden:
                pass
        await message.channel.send(
            "안녕하세요! 저는 메이플 디스코드 자동화 봇이에요 🤖\n"
            "저와는 직접 대화가 어려운 점 양해 부탁드려요 🙏\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📌 문의 안내\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ 인증 신청 → 인증 안내에서 인증신청 버튼을 눌러주세요\n"
            "✅ 닉네임 변경 → 닉네임 변경 버튼을 눌러주세요\n"
            "✅ 사기 신고 → 사기 신고 버튼을 눌러주세요\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "# ⚠️ 인증 사진은 여기로 보내시면 안 돼요!\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "저는 봇이라 인증 처리를 할 수 없어요 😅\n"
            "인증 사진은 서버의 인증 채널에서\n"
            "[MS.D]- 관리자 에게 직접 메시지로 보내주셔야 해요!\n\n"
            "📌 인증 채널 → 관리자에게 메시지 전송",
            file=discord.File("assets/manager.png")
        )

    # 신고 패널 채널(여러 개 가능)에 메시지 오면 패널 맨 아래로 재등록 (디바운스: 마지막 메시지 후 1초)
    if str(message.channel.id) in report_panel_info:
        cid = message.channel.id
        print(f"[REPOST] 메시지 감지 → 재등록 예약 (channel={cid})")
        existing = _report_repost_tasks.get(cid)
        if existing and not existing.done():
            existing.cancel()
        _report_repost_tasks[cid] = asyncio.create_task(_repost_panel(cid))

    await bot.process_commands(message)


# ========== 1. 신규 계정 입장 감지 ==========
@bot.event
async def on_member_join(member: discord.Member):
    global daily_join_count
    daily_join_count += 1
    save_daily_stats()
    now = datetime.now(timezone.utc)
    days = (now - member.created_at).days

    tracker = load_join_tracker()
    tracker[str(member.id)] = {
        "join_date": now.isoformat(),
        "reminders_sent": 0
    }
    save_join_tracker(tracker)

    try:
        await member.send(
            "# 🍁메이플스토리 디스코드에 오신 걸 환영합니다!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 현재는 인증 전이라 숨겨진 채널들이 안보여요\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "인증을 완료하면 여러 채널이 보입니다.\n\n"
            "💬 메이플 유저들과 자유로운 소통 채널\n"
            "🛒 서버별 안전한 거래 채널\n"
            "📢 이벤트 & 업데이트 알림 채널\n"
            "🎯 해방작업 & 직업별 정보 공유 채널\n\n"
            "지금 바로 인증해주세요!\n\n"
            "# 인증받는 방법은 인증 안내 채널을 확인 해주세요"
        )
    except discord.Forbidden:
        pass

    join_log_channel = bot.get_channel(JOIN_LOG_CHANNEL_ID)
    if join_log_channel:
        label = "🚨 30일 미만 계정" if days < 30 else ""
        try:
            await join_log_channel.send(
                f"{label} {member.mention} (`{member}`) · 계정 {days}일".strip()
            )
        except discord.Forbidden:
            pass

    if days < 30:
        try:
            await member.send(
                f"안녕하세요 {member.mention}님!\n\n"
                f"⚠️ 디스코드 계정 생성일이 **{days}일** 밖에 되지 않아 "
                f"역할 부여가 제한됩니다.\n"
                f"디스코드 가입 후 **30일이 지나면** 다시 인증 신청해 주세요.\n\n"
                f"메이플랜드는 한달 이내도 이용 가능합니다."
            )
        except discord.Forbidden:
            pass

        admin_channel = bot.get_channel(NEW_ACCOUNT_ALERT_CHANNEL_ID)
        if admin_channel:
            try:
                await admin_channel.send(
                    f"```diff\n- 🚨 한달 이내 신규 계정 입장 🚨\n```"
                    f"**유저:** {member.mention}\n"
                    f"**계정 생성:** {days}일 밖에 되지 않은 계정입니다.\n"
                    f"@here"
                )
            except discord.Forbidden:
                pass


# ========== 퇴장 감지 ==========
@bot.event
async def on_member_remove(member: discord.Member):
    global daily_leave_count, daily_leave_has_role, daily_leave_no_role, daily_leave_underage
    daily_leave_count += 1

    days = (datetime.now(timezone.utc) - member.created_at).days
    has_real_role = any(r.name != "@everyone" for r in member.roles)

    if days < 30:
        daily_leave_underage += 1
    elif has_real_role:
        daily_leave_has_role += 1
    else:
        daily_leave_no_role += 1
    save_daily_stats()

    tracker = load_join_tracker()
    tracker.pop(str(member.id), None)
    save_join_tracker(tracker)


# ========== 인증 완료 시 트래커 제거 ==========
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if len(before.roles) < len(after.roles):  # 역할이 추가됨
        tracker = load_join_tracker()
        if str(after.id) in tracker:
            tracker.pop(str(after.id))
            save_join_tracker(tracker)


# ========== 인증 리마인더 태스크 ==========
REMINDER_SCHEDULE = [
    (3, (
        "🍁 아직 인증을 완료하지 않으셨네요!\n\n"
        "인증만 하면 숨겨진 채널들이 전부 열려요 🔓\n\n"
        "📌 ★인증 안내★ 채널에서 간단하게 신청할 수 있어요!\n\n"
        " ━ 인증 방법 모를 때 연락 카카오톡 주소\n\n"
        " : https://open.kakao.com/o/gBkeVmoi"
    )),
    (7, (
        "👋 메이플 디스코드 아직 둘러보지 못하셨나요?\n\n"
        "인증하면 이런 채널들이 열려요!\n\n"
        "💬 메이플 유저들과 자유로운 소통\n"
        "🛒 서버별 안전한 거래 채널\n"
        "📢 이벤트 & 업데이트 알림\n"
        "🎯 해방작업 & 직업별 정보 공유\n\n"
        "📌 지금 바로 ★인증 안내★ 채널에서 신청해보세요!\n\n"
        " ━ 인증 방법 모를 때 연락 카카오톡 주소\n\n"
        " : https://open.kakao.com/o/gBkeVmoi"
    )),
    (15, (
        "🍁 아직 저희와 함께하지 않으셨네요 😊\n\n"
        "메이플 유저라면 꼭 알아야 할 정보들이 매일 올라오고 있어요!\n\n"
        "지금 인증하면 놓쳤던 정보들을 바로 확인할 수 있어요 📋\n"
        "📌 ★인증 안내★ 채널에서 신청해주세요!\n\n"
        " ━ 인증 방법 모를 때 연락 카카오톡 주소\n\n"
        " : https://open.kakao.com/o/gBkeVmoi"
    )),
    (30, (
        "🎉 이번 달 메이플 이벤트 놓치고 계신 거 알고 계세요?\n\n"
        "인증 유저들은 지금 이런 정보들을 공유하고 있어요!\n"
        "📢 최신 업데이트 & 이벤트 정보\n"
        "🛒 안전한 거래 채널\n"
        "🎯 해방작업 & 직업별 공략\n\n"
        "한 번만 인증하면 전부 볼 수 있어요 😊\n"
        "📌 ★인증 안내★ 채널에서 지금 신청해보세요!\n\n"
        " ━ 인증 방법 모를 때 연락 카카오톡 주소\n\n"
        " : https://open.kakao.com/o/gBkeVmoi"
    )),
]

async def reminder_task():
    KST = timezone(timedelta(hours=9))
    while True:
        now = datetime.now(timezone.utc)
        next_check = (datetime.now(KST) + timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_check.astimezone(timezone.utc) - now).total_seconds())

        tracker = load_join_tracker()
        to_remove = []
        now = datetime.now(timezone.utc)

        for user_id, info in list(tracker.items()):
            join_date = datetime.fromisoformat(info["join_date"])
            days_since = (now - join_date).days
            sent = info["reminders_sent"]

            if sent >= len(REMINDER_SCHEDULE):
                to_remove.append(user_id)
                continue

            required_days, message = REMINDER_SCHEDULE[sent]
            if days_since >= required_days:
                for guild in bot.guilds:
                    member = guild.get_member(int(user_id))
                    if member:
                        has_role = any(r.name != "@everyone" for r in member.roles)
                        if has_role:
                            to_remove.append(user_id)
                            break
                        try:
                            await member.send(message)
                            info["reminders_sent"] += 1
                        except discord.Forbidden:
                            pass
                        break

        for uid in to_remove:
            tracker.pop(uid, None)

        save_join_tracker(tracker)


# ========== 제휴 홍보 자동 게시 (6시간마다) ==========
AFFILIATE_CHANNEL_IDS = [
    1118494847179960340,  # 챌린저스
    1082016291617001502,  # 루나
    1082016795310956675,  # 스카니아
    1082016810901196890,  # 엘리시움
    1082017109690830969,  # 크로아
    1082017206755410062,  # 베라
    1082134678162649118,  # 오로라
    1082017256583737405,  # 기타서버
    1082017648860221540,  # 에오스
    1083767692323979334,  # 헬리오스
    1213334794419576863,  # 추가 채널
    1081216317597687870,  # 대화방
]

AFFILIATE_MESSAGE = (
    "🍁 메이플스토리 디스코드 - 제휴\n\n"
    "<#1202611017310277652> 💶 MVP 작업 / 매달 이벤트 진행\n"
    "<#1201063176171683911> 🍁 급처 문의 (메소 & 아이템 거래)\n"
    "<#1319583564714610708> ✅ 안전거래 사이트\n"
    "<#1412842413977768036> ⚔️ 보스 대행 전문팀"
)

async def affiliate_promo_task():
    KST = timezone(timedelta(hours=9))
    while True:
        now = datetime.now(KST)
        # 다음 발송 시각 계산 (08:00 또는 20:00)
        candidates = [
            now.replace(hour=8, minute=0, second=0, microsecond=0),
            now.replace(hour=20, minute=0, second=0, microsecond=0),
        ]
        next_send = min(t for t in candidates if t > now) if any(t > now for t in candidates) \
            else now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
        await asyncio.sleep((next_send - now).total_seconds())

        for channel_id in AFFILIATE_CHANNEL_IDS:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(AFFILIATE_MESSAGE)
                except discord.Forbidden:
                    print(f"[AFFILIATE] 권한 없음: {channel_id}")
                except Exception as e:
                    print(f"[AFFILIATE] 오류 ({channel_id}): {e}")


# ========== 일일 요약 (매일 자정 KST) ==========
async def daily_summary_task():
    global daily_join_count, daily_leave_count, daily_leave_has_role, daily_leave_no_role, daily_leave_underage, daily_auth_approve, daily_auth_reject, daily_bot_dm_count
    global weekly_join_count, weekly_leave_count, weekly_leave_has_role, weekly_leave_no_role, weekly_leave_underage, weekly_auth_approve, weekly_auth_reject, weekly_bot_dm_count
    global daily_auth_list, daily_dm_user_ids
    KST = timezone(timedelta(hours=9))
    while True:
        now = datetime.now(KST)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_midnight - now).total_seconds())

        summary_date = datetime.now(KST) - timedelta(days=1)
        date_str = summary_date.strftime("%Y-%m-%d")
        join_log_channel = bot.get_channel(JOIN_LOG_CHANNEL_ID)

        weekly_join_count += daily_join_count
        weekly_leave_count += daily_leave_count
        weekly_leave_has_role += daily_leave_has_role
        weekly_leave_no_role += daily_leave_no_role
        weekly_leave_underage += daily_leave_underage
        weekly_auth_approve += daily_auth_approve
        weekly_auth_reject += daily_auth_reject
        weekly_bot_dm_count += daily_bot_dm_count

        if join_log_channel:
            try:
                await join_log_channel.send(
                    f"📊 **{date_str} 일일 요약**\n"
                    f"👋 입장: {daily_join_count}명 · 퇴장: {daily_leave_count}명\n"
                    f"🤖 봇 DM 수신: {daily_bot_dm_count}명\n\n"
                    f"**퇴장 분석**\n"
                    f"├ 인증 역할 있던 유저: {daily_leave_has_role}명\n"
                    f"├ 역할 없던 유저 (미인증): {daily_leave_no_role}명\n"
                    f"└ 30일 미만 계정: {daily_leave_underage}명\n\n"
                    f"**인증 처리**\n"
                    f"├ 승인: {daily_auth_approve}건\n"
                    f"└ 거절: {daily_auth_reject}건"
                )
            except discord.Forbidden:
                pass

            if summary_date.weekday() == 6:
                week_start = (summary_date - timedelta(days=6)).strftime("%Y-%m-%d")
                week_end = summary_date.strftime("%Y-%m-%d")
                try:
                    await join_log_channel.send(
                        f"📅 **주간 요약 ({week_start} ~ {week_end})**\n"
                        f"👋 입장: {weekly_join_count}명 · 퇴장: {weekly_leave_count}명\n"
                        f"🤖 봇 DM 수신: {weekly_bot_dm_count}명\n\n"
                        f"**퇴장 분석**\n"
                        f"├ 인증 역할 있던 유저: {weekly_leave_has_role}명\n"
                        f"├ 역할 없던 유저 (미인증): {weekly_leave_no_role}명\n"
                        f"└ 30일 미만 계정: {weekly_leave_underage}명\n\n"
                        f"**인증 처리**\n"
                        f"├ 승인: {weekly_auth_approve}건\n"
                        f"└ 거절: {weekly_auth_reject}건"
                    )
                except discord.Forbidden:
                    pass
                weekly_join_count = 0
                weekly_leave_count = 0
                weekly_leave_has_role = 0
                weekly_leave_no_role = 0
                weekly_leave_underage = 0
                weekly_auth_approve = 0
                weekly_auth_reject = 0
                weekly_bot_dm_count = 0

        auth_admin_channel = bot.get_channel(AUTH_ADMIN_CHANNEL_ID)
        if auth_admin_channel:
            snapshot = list(daily_auth_list)
            if snapshot:
                lines = []
                for entry in snapshot:
                    guild = auth_admin_channel.guild
                    member = guild.get_member(entry["user_id"])
                    mention = member.mention if member else f"<@{entry['user_id']}>"
                    lines.append(f"신청자: {mention}")
                body = "\n".join(lines)
                try:
                    await auth_admin_channel.send(
                        f"📋 **{date_str} 핸즈인증 승인 목록** (총 {len(snapshot)}명)\n\n{body}"
                    )
                except discord.Forbidden:
                    pass
            else:
                try:
                    await auth_admin_channel.send(
                        f"📋 **{date_str} 핸즈인증 승인 목록** — 오늘 승인된 인원이 없습니다."
                    )
                except discord.Forbidden:
                    pass

        daily_join_count = 0
        daily_leave_count = 0
        daily_leave_has_role = 0
        daily_leave_no_role = 0
        daily_leave_underage = 0
        daily_auth_approve = 0
        daily_auth_reject = 0
        daily_bot_dm_count = 0
        daily_auth_list = []
        daily_dm_user_ids = set()
        save_daily_stats()
        save_daily_auth_list()
        save_daily_dm_users()


# ========== 닉네임 패널 자동 재생성 ==========
async def refresh_nickname_panel(channel: discord.TextChannel):
    async for message in channel.history(limit=200):
        if message.author == bot.user and message.embeds:
            if message.embeds[0].title == "📝 닉네임 변경 신청":
                await message.delete()
                break
    embed = discord.Embed(
        title="📝 닉네임 변경 신청",
        description=(
            "아래 버튼을 눌러 닉네임 변경을 신청하세요.\n\n"
            "**절차:**\n"
            "1️⃣ 버튼 클릭\n"
            "2️⃣ 서버 선택\n"
            "3️⃣ 레벨 / 닉네임 입력\n"
            "4️⃣ 관리자 확인 후 변경 완료\n\n"
            "⏱️ 신청 후 **1시간 이내**에 변경됩니다."
        ),
        color=discord.Color.blue()
    )
    await channel.send(embed=embed, view=NicknameButtonView())


# ========== 2. 닉네임 변경 - 서버 선택 드롭다운 ==========
class NickServerSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="메이플 서버를 선택하세요",
        custom_id="nick_server_select",
        options=[discord.SelectOption(label=s, value=s) for s in AUTH_SERVER_LIST]
    )
    async def server_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        server = select.values[0]
        if server in ("메이플플래닛", "메이플랜드"):
            await interaction.response.send_modal(ClassicNickModal(server=server))
        else:
            nick_flow_data[interaction.user.id] = {"server": server}
            await interaction.response.send_modal(NicknameModal())


# ========== 2. 닉네임 변경 신청 모달 ==========
class NicknameModal(discord.ui.Modal, title="닉네임 변경 신청"):
    level = discord.ui.TextInput(
        label="레벨",
        placeholder="숫자만 입력 (1~300)",
        max_length=3
    )
    new_nickname = discord.ui.TextInput(
        label="닉네임",
        placeholder="게임 내 캐릭터 닉네임",
        max_length=20
    )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"[모달 에러] {type(error).__name__}: {error}")
        try:
            await interaction.response.send_message(f"❌ 오류 발생: {error}", ephemeral=True)
        except Exception:
            await interaction.followup.send(f"❌ 오류 발생: {error}", ephemeral=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        weekly_count = get_weekly_count(user_id)
        previous_nickname = interaction.user.display_name

        data = nick_flow_data.get(interaction.user.id, {})
        server_input = data.get("server")

        if not server_input:
            await interaction.response.send_message("❌ 처음부터 다시 신청해주세요.", ephemeral=True)
            return

        level_input = self.level.value.strip()

        # 레벨 유효성 검사
        if not level_input.isdigit() or not (1 <= int(level_input) <= 300):
            await interaction.response.send_message(
                "❌ 레벨이 잘못 적혀있습니다. 1~300 사이의 숫자만 입력해주세요.",
                ephemeral=True
            )
            return

        combined_nickname = f"{server_input}/{level_input}/{self.new_nickname.value.strip()}"
        nick_flow_data.pop(interaction.user.id, None)

        admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if not admin_channel:
            await interaction.response.send_message(
                "❌ 관리자 채널을 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True
            )
            return

        # 7일 내 1번 미만 → 자동 변경
        if weekly_count < WEEKLY_LIMIT:
            try:
                await interaction.user.edit(nick=combined_nickname)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ 봇 권한 부족! 관리자에게 문의하세요.", ephemeral=True
                )
                return

            await update_server_role(interaction.user, server_input)
            record_change(user_id, previous_nickname, combined_nickname)

            try:
                await admin_channel.send(
                    f"🔄 **닉네임 자동 변경**\n"
                    f"유저: {interaction.user.mention}\n"
                    f"`{previous_nickname}` → `{combined_nickname}`\n"
                    f"서버 역할: {SERVER_ROLES.get(server_input, '없음')} 부여"
                )
            except discord.Forbidden:
                pass

            await interaction.response.send_message(
                f"✅ **{previous_nickname}** 에서 **{combined_nickname}** 으로 변경됐습니다!",
                ephemeral=True
            )
            await refresh_nickname_panel(interaction.channel)

        # 7일 내 2번 이상 → 관리자 승인 필요
        else:
            request_id = str(uuid.uuid4())[:8]
            add_pending(request_id, interaction.user.id, previous_nickname, combined_nickname, server_input)

            view = ApproveView(request_id=request_id)
            bot.add_view(view)

            try:
                await admin_channel.send(
                    f"⚠️ **닉네임 변경 승인 필요**\n"
                    f"신청자: {interaction.user.mention}\n"
                    f"`{previous_nickname}` → `{combined_nickname}`\n"
                    f"서버 역할 변경: {SERVER_ROLES.get(server_input, '없음')}\n"
                    f"7일 내 {weekly_count}회 변경 이력",
                    view=view
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ 관리자 채널 전송 실패. 관리자에게 문의하세요.", ephemeral=True
                )
                return

            await interaction.response.send_message(
                "⚠️ 7일 내 변경 횟수를 초과하여 관리자 승인이 필요합니다.\n"
                "승인 후 1~3시간 이내에 변경됩니다.",
                ephemeral=True
            )
            await refresh_nickname_panel(interaction.channel)


# ========== 3. 관리자 승인/거절 버튼 ==========
class ApproveView(discord.ui.View):
    def __init__(self, request_id: str):
        super().__init__(timeout=None)
        self.request_id = request_id

        approve_btn = discord.ui.Button(
            label="✅ 승인",
            style=discord.ButtonStyle.success,
            custom_id=f"approve_{request_id}"
        )
        reject_btn = discord.ui.Button(
            label="❌ 거절",
            style=discord.ButtonStyle.danger,
            custom_id=f"reject_{request_id}"
        )
        approve_btn.callback = self.approve
        reject_btn.callback = self.reject
        self.add_item(approve_btn)
        self.add_item(reject_btn)

    async def approve(self, interaction: discord.Interaction):
        pending = load_pending()
        data = pending.get(self.request_id)
        if not data:
            await interaction.channel.send("❌ 이미 처리된 신청입니다.")
            return

        member = interaction.guild.get_member(data["user_id"])
        if not member:
            await interaction.channel.send("❌ 유저를 찾을 수 없습니다.")
            return

        try:
            await member.edit(nick=data["new"])
        except discord.Forbidden:
            await interaction.channel.send("❌ 봇 권한 부족!")
            return

        if data.get("new_server"):
            await update_server_role(member, data["new_server"])

        record_change(str(data["user_id"]), data["previous"], data["new"])
        remove_pending(self.request_id)

        try:
            await member.send(f"✅ **{data['previous']}** 에서 **{data['new']}** 으로 변경됐습니다!")
        except discord.Forbidden:
            pass

        await _disable_view(interaction, self)
        await interaction.channel.send(
            f"✅ {member.mention} 닉네임 변경 완료!\n`{data['previous']}` → `{data['new']}`"
        )

    async def reject(self, interaction: discord.Interaction):
        pending = load_pending()
        data = pending.get(self.request_id)
        if not data:
            try:
                await interaction.response.send_message("❌ 이미 처리된 신청입니다.", ephemeral=True)
            except Exception:
                await interaction.channel.send("❌ 이미 처리된 신청입니다.")
            return

        member = interaction.guild.get_member(data["user_id"])
        remove_pending(self.request_id)

        if member:
            try:
                await member.send("❌ 닉네임 변경 신청이 거절됐습니다. 관리자에게 문의해주세요.")
            except discord.Forbidden:
                pass

        await _disable_view(interaction, self)
        await interaction.channel.send("❌ 닉네임 변경 신청 거절 완료")


# ========== 4. 닉네임 변경 버튼 패널 ==========
class NicknameButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 닉네임 변경 신청", style=discord.ButtonStyle.primary, custom_id="nickname_request")
    async def request_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = NickServerSelectView()
        await interaction.response.send_message(
            "📋 메이플 서버를 선택해주세요:",
            view=view,
            ephemeral=True
        )


@bot.tree.command(name="닉네임패널", description="닉네임 변경 신청 버튼 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def nickname_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async for message in interaction.channel.history(limit=200):
        if message.author == bot.user and message.embeds:
            if message.embeds[0].title == "📝 닉네임 변경 신청":
                await message.delete()

    embed = discord.Embed(
        title="📝 닉네임 변경 신청",
        description=(
            "아래 버튼을 눌러 닉네임 변경을 신청하세요.\n\n"
            "**절차:**\n"
            "1️⃣ 버튼 클릭\n"
            "2️⃣ 서버 / 레벨 / 닉네임 입력\n"
            "3️⃣ 관리자 확인 후 변경 완료\n\n"
            "⏱️ 관리자에게 닉네임 변경신청이 제출되고 승인이 되면 **1~3시간 이내**에 변경됩니다."
        ),
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=embed, view=NicknameButtonView())
    await interaction.followup.send("✅ 패널 생성 완료!", ephemeral=True)


@nickname_panel.error
async def nickname_panel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ 오류 발생: {error}", ephemeral=True)


# ========== 신고 민원 ==========
REPORT_ADMIN_CHANNEL_ID = int(os.getenv("REPORT_ADMIN_CHANNEL_ID", "1483774833761452213"))
REPORT_MANAGER_ID = 1059792897509163028
REPORT_FILE = "/data/reports.json"

REPORT_REASONS = [
    "입금 후 연락 두절",
    "연락처(핸드폰번호) 제공 거부",
    "게임 내 직거래 회피 및 경매장 거래 유도",
    "메소 보유 확인 거부",
    "사기 의심 정황",
    "기타 사유",
]

report_flow_data = {}  # user_id -> {"reason": str}
_report_repost_tasks: dict[int, asyncio.Task] = {}  # channel_id -> Task
REPORT_PANEL_INFO_FILE = "/data/report_panel_info.json"


def load_report_panel_info() -> dict:
    data = _load_json(REPORT_PANEL_INFO_FILE)
    # migrate old format: {"channel_id": ..., "message_id": ...} → {str(channel_id): message_id}
    if "channel_id" in data:
        return {str(data["channel_id"]): data.get("message_id")} if data.get("channel_id") else {}
    return data


def save_report_panel_info(data: dict):
    _save_json(REPORT_PANEL_INFO_FILE, data)


report_panel_info = load_report_panel_info()  # {str(channel_id): message_id}


def load_reports() -> dict:
    return _load_json(REPORT_FILE)


def save_reports(data: dict):
    _save_json(REPORT_FILE, data, indent=2)


def get_report_count(target_nick: str) -> int:
    reports = load_reports()
    return sum(1 for r in reports.values() if r.get("target_nick") == target_nick)


def add_report(report_id: str, reporter_id: int, target_nick: str, reason: str, target_id: int | None = None):
    reports = load_reports()
    reports[report_id] = {
        "reporter_id": reporter_id,
        "target_id": target_id,
        "target_nick": target_nick,
        "reason": reason,
        "date": datetime.now(timezone.utc).isoformat()
    }
    save_reports(reports)


def find_member_by_nick(guild: discord.Guild, nick: str) -> discord.Member | None:
    nick_lower = nick.lower().strip()
    for member in guild.members:
        display = (member.nick or member.display_name or "").lower()
        # 서버/레벨/닉네임 형식에서 마지막 닉네임 부분만 비교
        last_part = display.split("/")[-1].strip()
        if nick_lower == last_part or nick_lower == display:
            return member
    return None


# ========== 신고 사유 선택 뷰 ==========
class ReportReasonSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.reason = None

    @discord.ui.select(
        placeholder="신고 사유를 선택하세요",
        custom_id="report_reason_select",
        options=[discord.SelectOption(label=r, value=r) for r in REPORT_REASONS]
    )
    async def reason_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        report_flow_data[interaction.user.id] = {"reason": select.values[0]}
        await interaction.response.send_modal(ReportModal())


# ========== 신고 모달 ==========
class ReportModal(discord.ui.Modal, title="사기 신고 민원"):
    target_nick = discord.ui.TextInput(
        label="서버/레벨을 제외하고 닉네임만 적어주세요",
        placeholder="상대방 채널 닉네임만 입력 (모르면 '모름' 입력)",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = report_flow_data.get(interaction.user.id)
        if not data:
            await interaction.response.send_message("❌ 다시 처음부터 신청해주세요.", ephemeral=True)
            return

        reason = data["reason"]
        target_nick_val = self.target_nick.value.strip()
        report_id = str(uuid.uuid4())[:8]

        target_member = find_member_by_nick(interaction.guild, target_nick_val) if target_nick_val != "모름" else None

        add_report(report_id, interaction.user.id, target_nick_val, reason, target_member.id if target_member else None)
        report_count = get_report_count(target_nick_val)

        reporter_mention = interaction.user.mention
        target_mention = target_member.mention if target_member else f"`{target_nick_val}` (미확인)"

        report_channel = bot.get_channel(REPORT_ADMIN_CHANNEL_ID)
        if report_channel:
            view = ReportAdminView(
                report_id=report_id,
                reporter_id=interaction.user.id,
                target_id=target_member.id if target_member else None,
                target_nick=target_nick_val,
                reason=reason
            )
            bot.add_view(view)
            await report_channel.send(
                f"🚨 **사기 신고 접수**\n"
                f"신고자: {reporter_mention}\n"
                f"피신고자: {target_mention}\n"
                f"신고 사유: **{reason}**\n"
                f"누적 신고 횟수: **{report_count}회**",
                view=view
            )

        # 관리자 DM
        manager = interaction.guild.get_member(REPORT_MANAGER_ID)
        if manager:
            try:
                await manager.send(
                    f"🚨 **사기 신고 접수**\n"
                    f"신고자: {reporter_mention}\n"
                    f"피신고자: {target_mention}\n"
                    f"신고 사유: **{reason}**\n"
                    f"누적 신고 횟수: **{report_count}회**"
                )
            except discord.Forbidden:
                pass

        # 신고자에게 DM
        try:
            await interaction.user.send(
                "신고는 관리자에게 즉시 전달 되었습니다.\n"
                "신속하게 처리 도와드리겠습니다. 추가 문의가 있다면 관리자에게 DM을 보내주세요.\n\n"
                "추가로 사기를 당하셨다면 아래 주소를 참고해서 경찰에 신고해주세요.\n"
                "https://maplesayo.com/공지사항/?mod=document&uid=6"
            )
        except discord.Forbidden:
            pass

        report_flow_data.pop(interaction.user.id, None)

        await interaction.response.send_message(
            "✅ 신고가 접수됐습니다. 관리자에게 즉시 전달됩니다.",
            ephemeral=True
        )


# ========== 관리자 신고 처리 버튼 ==========
class ReportAdminView(discord.ui.View):
    def __init__(self, report_id: str, reporter_id: int, target_id: int | None, target_nick: str, reason: str):
        super().__init__(timeout=None)
        self.report_id = report_id
        self.reporter_id = reporter_id
        self.target_id = target_id
        self.target_nick = target_nick
        self.reason = reason

        notify_btn = discord.ui.Button(
            label="📣 알림발송",
            style=discord.ButtonStyle.primary,
            custom_id=f"report_notify_{report_id}"
        )
        role_btn = discord.ui.Button(
            label="🗑️ 역할 빼기",
            style=discord.ButtonStyle.danger,
            custom_id=f"report_role_{report_id}"
        )
        confirm_btn = discord.ui.Button(
            label="✅ 확인 완료",
            style=discord.ButtonStyle.secondary,
            custom_id=f"report_confirm_{report_id}"
        )
        notify_btn.callback = self.notify
        role_btn.callback = self.remove_role
        confirm_btn.callback = self.confirm
        self.add_item(notify_btn)
        self.add_item(role_btn)
        self.add_item(confirm_btn)

    async def notify(self, interaction: discord.Interaction):
        if not self.target_id:
            await interaction.response.send_message("❌ 피신고자 ID를 특정할 수 없습니다.", ephemeral=True)
            return

        target_member = interaction.guild.get_member(self.target_id)
        reporter_member = interaction.guild.get_member(self.reporter_id)

        if not target_member:
            await interaction.response.send_message("❌ 피신고자를 찾을 수 없습니다.", ephemeral=True)
            return

        try:
            reporter_name = reporter_member.display_name if reporter_member else "알 수 없음"
            await target_member.send(
                f"**[메이플디스코드 신고 알림]**\n\n"
                f"{reporter_name}님이 **{self.reason}** 사유로 신고하였습니다.\n\n"
                "신고 내용이 허위거나 문제가 있다고 생각하시면 관리자에게 DM을 보내주세요."
            )
            await interaction.response.send_message("✅ 피신고자에게 알림 DM 발송 완료", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 피신고자 DM 발송 실패 (DM 차단)", ephemeral=True)

    async def remove_role(self, interaction: discord.Interaction):
        if not self.target_id:
            await interaction.response.send_message("❌ 피신고자 ID를 특정할 수 없습니다.", ephemeral=True)
            return

        target_member = interaction.guild.get_member(self.target_id)
        if not target_member:
            await interaction.response.send_message("❌ 피신고자를 찾을 수 없습니다.", ephemeral=True)
            return

        removed = []
        for role in target_member.roles:
            if role.name == "@everyone":
                continue
            try:
                await target_member.remove_roles(role)
                removed.append(role.name)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(
            f"✅ {target_member.display_name} 역할 제거 완료\n제거된 역할: {', '.join(removed) if removed else '없음'}",
            ephemeral=True
        )

    async def confirm(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("✅ 신고 처리 완료로 표시됐습니다.", ephemeral=True)


# ========== 신고 버튼 패널 ==========
class ReportButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚨 사기 신고 민원", style=discord.ButtonStyle.danger, custom_id="report_request")
    async def report_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ReportReasonSelectView()
        await interaction.response.send_message(
            "📋 신고 사유를 선택해주세요:",
            view=view,
            ephemeral=True
        )


@bot.tree.command(name="신고패널", description="사기 신고 민원 패널 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def report_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async for message in interaction.channel.history(limit=50):
        if message.author == bot.user and message.embeds:
            if message.embeds[0].title == "🚨 사기 신고 민원":
                await message.delete()

    embed = discord.Embed(
        title="🚨 사기 신고 민원",
        description=(
            "✅ **사기 의심 유형** - 아래 사례는 즉시 신고해 주세요.\n\n"
            "• 당일 가입한 디스코드 계정으로 친구 추가 후 거래\n"
            "• 연락처(폰번호) 미제공\n"
            "• 게임 내 거래 없이 경매장 거래만 유도\n"
            "• 핸즈로만 메소 확인 유도\n\n"
            "아래 버튼을 눌러 신고를 접수해 주세요."
        ),
        color=discord.Color.red()
    )
    panel_msg = await interaction.channel.send(embed=embed, view=ReportButtonView())
    report_panel_info[str(interaction.channel.id)] = panel_msg.id
    save_report_panel_info(report_panel_info)
    await interaction.followup.send("✅ 신고 패널 생성 완료!", ephemeral=True)


@report_panel.error
async def report_panel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)
    else:
        try:
            await interaction.response.send_message(f"❌ 오류 발생: {error}", ephemeral=True)
        except Exception:
            pass


async def check_nickname_changed(nickname: str) -> str:
    if not NEXON_API_KEY:
        return "조회 불가"
    headers = {"x-nxopen-api-key": NEXON_API_KEY}
    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    # 최근 → 과거 순으로 체크해서 직전 닉네임을 정확히 잡음
    check_days = [7, 14, 30, 60, 90]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{NEXON_API_BASE}/id",
                params={"character_name": nickname},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return "캐릭터 없음"
                ocid = (await resp.json()).get("ocid")
            if not ocid:
                return "캐릭터 없음"

            async with session.get(
                f"{NEXON_API_BASE}/character/basic",
                params={"ocid": ocid, "date": yesterday},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[NEXON API] character/basic 실패 status={resp.status} body={body[:200]}")
                    return "조회 실패"
                current_name = (await resp.json()).get("character_name")

            for days in check_days:
                check_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
                async with session.get(
                    f"{NEXON_API_BASE}/character/basic",
                    params={"ocid": ocid, "date": check_date},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    old_name = (await resp.json()).get("character_name")
                    if old_name and old_name != current_name:
                        return f"⚠️ 변경 있음 (`{old_name}` → `{current_name}`)"

        return "✅ 변경 없음"
    except Exception as e:
        print(f"[NEXON API] 조회 실패 nickname={nickname} error={type(e).__name__}: {e}")
        return "조회 실패"


async def fetch_event_detail(event_url: str) -> tuple[str | None, bytes | None]:
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession() as session:
            async with session.get(event_url, headers=MAPLE_HEADERS, timeout=timeout) as resp:
                html = await resp.text()

            title = None
            title_tag = BeautifulSoup(html, "html.parser").find("title")
            if title_tag:
                segment = re.split(r"\s*[-|]\s*", title_tag.get_text(strip=True))[0].strip()
                if segment:
                    title = segment

            all_imgs = re.findall(r'https://(?:lwi|file)\.nexon\.com/maplestory/[^\s"\'<>]+\.(?:png|jpg|jpeg|gif)', html)
            event_img_url = next(
                (u for u in all_imgs if "/common/" not in u and re.search(r'/20\d{2}/', u)),
                None
            )

            img_data = None
            if event_img_url:
                async with session.get(event_img_url, timeout=timeout) as resp:
                    img_data = await resp.read()

        return title, img_data
    except Exception:
        return None, None


async def send_maple_event(channel, event: dict):
    detail_title, img_data = await fetch_event_detail(event["url"])
    title = detail_title or event["title"]

    embed = discord.Embed(
        title=title,
        url=event["url"],
        description=event["date"] if event["date"] else None,
        color=discord.Color.orange()
    )
    embed.set_footer(text="🍁 메이플스토리 이벤트 업데이트")

    try:
        if img_data:
            img_file = discord.File(io.BytesIO(img_data), filename="event.png")
            embed.set_image(url="attachment://event.png")
            await channel.send(embed=embed, file=img_file)
        else:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"[MAPLE_NEWS] 전송 실패 ({event['id']}): {e}")


# ========== 메이플 뉴스 테스트 ==========
@bot.tree.command(name="메이플뉴스테스트", description="최신 이벤트 1개를 채널에 전송 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def maple_news_test(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        events = await fetch_maple_events()
        if not events:
            await interaction.followup.send("❌ 이벤트를 가져오지 못했습니다.", ephemeral=True)
            return
        event = events[0]
        channel = bot.get_channel(MAPLE_NEWS_CHANNEL_ID)
        await send_maple_event(channel, event)
        await interaction.followup.send("✅ 테스트 전송 완료!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 오류: {e}", ephemeral=True)


# ========== 메이플스토리 이벤트 뉴스 자동 알림 ==========
MAPLE_NEWS_CHANNEL_ID = 1083586012086816791
MAPLE_EVENT_URL = "https://maplestory.nexon.com/News/Event"
MAPLE_EVENTS_FILE = "/data/maple_events_posted.json"


def load_posted_events() -> set:
    return set(_load_json(MAPLE_EVENTS_FILE, default=[]))

def save_posted_events(posted: set):
    _save_json(MAPLE_EVENTS_FILE, list(posted))


async def fetch_maple_events() -> list[dict]:
    async with aiohttp.ClientSession() as session:
        async with session.get(MAPLE_EVENT_URL, headers=MAPLE_HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            html = await resp.text()

    event_ids = list(dict.fromkeys(re.findall(r'/News/Event/(\d+)', html)))

    soup = BeautifulSoup(html, "html.parser")
    events = []

    for event_id in event_ids:
        a = soup.find("a", href=lambda h: h and f"/News/Event/{event_id}" in h)
        if not a:
            continue

        img_tag = a.find("img")
        thumbnail = img_tag.get("src") if img_tag else None

        for tag in a.find_all("img"):
            tag.decompose()
        title = a.get_text(separator=" ", strip=True)
        if not title:
            title = f"이벤트 {event_id}"

        li = a.find_parent("li")
        date_text = ""
        if li:
            full = li.get_text(separator=" ", strip=True)
            date_text = full.replace(title, "").strip()

        events.append({
            "id": event_id,
            "title": title,
            "date": date_text,
            "url": f"https://maplestory.nexon.com/News/Event/{event_id}",
            "thumbnail": thumbnail,
        })

    return events


async def maple_news_task():
    await bot.wait_until_ready()
    posted = load_posted_events()

    while True:
        try:
            events = await fetch_maple_events()
            new_events = [e for e in events if e["id"] not in posted]

            if not posted:
                for e in events:
                    posted.add(e["id"])
                save_posted_events(posted)
            elif new_events:
                channel = bot.get_channel(MAPLE_NEWS_CHANNEL_ID)
                for event in reversed(new_events):
                    if channel:
                        await send_maple_event(channel, event)
                    posted.add(event["id"])
                save_posted_events(posted)
                print(f"[MAPLE_NEWS] 새 이벤트 {len(new_events)}개 전송 완료")

        except Exception as e:
            print(f"[MAPLE_NEWS] 오류: {e}")

        await asyncio.sleep(3600)


# ========== 게임 역할 버튼 ==========
GAME_ROLE_CHANNEL_ID = 1213334715663130645


class GameRoleView(discord.ui.View):
    def __init__(self, guild_id: int = None):
        super().__init__(timeout=None)
        if guild_id:
            self.add_item(discord.ui.Button(
                label="메이플본서버",
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{guild_id}/1081075118761066556",
                row=0
            ))
        mapleland_btn = discord.ui.Button(label="메이플랜드", style=discord.ButtonStyle.primary, custom_id="game_role_mapleland", row=0)
        mapleland_btn.callback = self._mapleland
        self.add_item(mapleland_btn)

        mapleplanet_btn = discord.ui.Button(label="메이플플래닛", style=discord.ButtonStyle.primary, custom_id="game_role_mapleplanet", row=0)
        mapleplanet_btn.callback = self._mapleplanet
        self.add_item(mapleplanet_btn)

    async def _mapleland(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ClassicAuthModal(server="메이플랜드"))

    async def _mapleplanet(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ClassicAuthModal(server="메이플플래닛"))


@bot.tree.command(name="게임역할패널", description="게임 역할 선택 버튼 패널 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def game_role_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        channel = await bot.fetch_channel(GAME_ROLE_CHANNEL_ID)
    except Exception:
        await interaction.followup.send("❌ 채널을 찾을 수 없습니다.", ephemeral=True)
        return
    embed = discord.Embed(
        title="서버 역할 선택",
        description="메이플 본서버 유저는 메이플 본서버 인증 해주세요.\n메이플클래식 유저 해당서버 버튼 클릭",
        color=discord.Color.green()
    )
    await channel.send(embed=embed, view=GameRoleView(guild_id=interaction.guild.id))
    await interaction.followup.send("✅ 게임 역할 패널이 생성되었습니다!", ephemeral=True)


@game_role_panel.error
async def game_role_panel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)


# ========== 클래식 닉네임 변경 모달 ==========
class ClassicNickModal(discord.ui.Modal, title="닉네임 변경 신청"):
    level = discord.ui.TextInput(label="레벨", placeholder="숫자만 입력", max_length=4)
    new_nickname = discord.ui.TextInput(label="닉네임", placeholder="변경할 캐릭터 닉네임", max_length=20)

    def __init__(self, server: str):
        super().__init__()
        self.server = server

    async def on_submit(self, interaction: discord.Interaction):
        level_val = self.level.value.strip()
        if not level_val.isdigit() or int(level_val) < 1:
            await interaction.response.send_message("❌ 레벨이 잘못 적혀있습니다.", ephemeral=True)
            return

        nick_val = self.new_nickname.value.strip()
        combined_nick = f"{self.server}/{level_val}/{nick_val}"

        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ 유저 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        old_nick = member.display_name
        try:
            await member.edit(nick=combined_nick)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇 권한 부족! 관리자에게 문의하세요.", ephemeral=True)
            return

        await update_server_role(member, self.server)
        await interaction.response.send_message(
            f"✅ 닉네임이 변경됐어요!\n`{old_nick}` → `{combined_nick}`", ephemeral=True
        )

        admin_channel = bot.get_channel(CLASSIC_ADMIN_CHANNEL_ID)
        if admin_channel:
            try:
                await admin_channel.send(
                    f"🔄 **닉네임 변경 완료** ({self.server})\n"
                    f"유저: {member.mention}\n"
                    f"닉네임 변경: `{old_nick}` → `{combined_nick}`"
                )
            except discord.Forbidden:
                pass


# ========== 클래식 닉네임 변경 버튼 패널 ==========
class ClassicNickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        planet_btn = discord.ui.Button(
            label="메이플플래닛 닉네임변경",
            style=discord.ButtonStyle.primary,
            custom_id="classic_nick_mapleplanet",
            row=0
        )
        planet_btn.callback = self._mapleplanet
        self.add_item(planet_btn)

        land_btn = discord.ui.Button(
            label="메이플랜드 닉네임변경",
            style=discord.ButtonStyle.success,
            custom_id="classic_nick_mapleland",
            row=0
        )
        land_btn.callback = self._mapleland
        self.add_item(land_btn)

    async def _mapleplanet(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ClassicNickModal(server="메이플플래닛"))

    async def _mapleland(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ClassicNickModal(server="메이플랜드"))


@bot.tree.command(name="클래식닉네임패널", description="메이플랜드/메이플플래닛 닉네임 변경 패널 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def classic_nick_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📝 클래식 닉네임 변경 신청",
        description=(
            "메이플플래닛 / 메이플랜드 전용 닉네임 변경 신청 패널입니다.\n\n"
            "**절차:**\n"
            "1️⃣ 해당 서버 버튼 클릭\n"
            "2️⃣ 레벨 / 변경할 닉네임 입력\n"
            "3️⃣ 즉시 닉네임 변경 완료\n\n"
            "⚠️ 변경 후 관리자에게 자동으로 알림이 전송됩니다."
        ),
        color=discord.Color.purple()
    )
    await interaction.channel.send(embed=embed, view=ClassicNickView())
    await interaction.response.send_message("✅ 클래식 닉네임 변경 패널이 생성됐습니다!", ephemeral=True)


@classic_nick_panel.error
async def classic_nick_panel_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 관리자 권한이 필요합니다.", ephemeral=True)



@bot.event
async def on_ready():
    await bot.tree.sync()
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)
    bot.add_view(NicknameButtonView())
    bot.add_view(AuthButtonView())
    bot.add_view(ReportButtonView())
    bot.add_view(GameRoleView())
    bot.add_view(ClassicNickView())

    pending = load_pending()
    for request_id in pending:
        bot.add_view(ApproveView(request_id=request_id))

    auth_pending = load_auth_pending()
    for request_id, data in auth_pending.items():
        bot.add_view(AuthApproveView(request_id=request_id, is_underage=data.get("is_underage", False)))

    reports = load_reports()
    for report_id, r in reports.items():
        bot.add_view(ReportAdminView(
            report_id=report_id,
            reporter_id=r.get("reporter_id", 0),
            target_id=r.get("target_id"),
            target_nick=r.get("target_nick", ""),
            reason=r.get("reason", "")
        ))

    if not bot._tasks_started:
        bot._tasks_started = True
        asyncio.create_task(daily_summary_task())
        asyncio.create_task(reminder_task())
        asyncio.create_task(affiliate_promo_task())
        asyncio.create_task(maple_news_task())
    print(f"✅ {bot.user} 온라인! | 대기 중인 승인: {len(pending)}건 | 인증 대기: {len(auth_pending)}건 | 신고 복구: {len(reports)}건")


bot.run(BOT_TOKEN)
