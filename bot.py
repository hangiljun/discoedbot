import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import json
import uuid

load_dotenv()

# ========== 설정 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID"))
AUTH_ADMIN_CHANNEL_ID = int(os.getenv("AUTH_ADMIN_CHANNEL_ID", "1483398777904828416"))
HISTORY_FILE = "/data/nickname_history.json"
PENDING_FILE = "/data/pending_approvals.json"
WEEKLY_LIMIT = 1
AUTH_PENDING_FILE = "/data/auth_pending.json"
HANDS_AUTH_ROLE = "「핸즈 & 인증유저」"
# ==========================

# 서버명 → 역할명 매핑
SERVER_ROLES = {
    "챌린저스": "챌린저스",
    "베라": "베라",
    "크로아": "크로아",
    "루나": "루나",
    "스카니아": "스카니아",
    "오로라": "오로라",
    "이노시스": "이노시스",
    "레드": "레드",
    "에오스": "에오스/헬리오스",
    "제니스": "제니스",
    "엘리시움": "엘리시움",
    "유니온": "유니온",
    "아케인": "아케인",
    "노바": "노바",
    "헬리오스": "에오스/헬리오스",
}

AUTH_SERVER_LIST = [
    "챌린저스", "스카니아", "베라", "루나", "엘리시움", "크로아",
    "유니온", "이노시스", "레드", "오로라", "아케인",
    "노바", "에오스", "헬리오스"
]

auth_flow_data = {}  # user_id -> {"server": str, "method": str}
nick_flow_data = {}  # user_id -> {"server": str}

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ========== 신청 기록 관리 ==========
def ensure_data_dir():
    os.makedirs("/data", exist_ok=True)

def load_history() -> dict:
    ensure_data_dir()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history: dict):
    ensure_data_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

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

def load_pending() -> dict:
    ensure_data_dir()
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_pending(pending: dict):
    ensure_data_dir()
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

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


# ========== 역할 변경 ==========
async def update_server_role(member: discord.Member, new_server: str):
    """기존 서버 역할 제거 후 새 서버 역할 부여"""
    # 기존 서버 역할 제거
    for role_name in SERVER_ROLES.values():
        role = discord.utils.get(member.guild.roles, name=role_name)
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

    # 새 서버 역할 부여
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
    ensure_data_dir()
    if os.path.exists(AUTH_PENDING_FILE):
        with open(AUTH_PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_auth_pending(pending: dict):
    ensure_data_dir()
    with open(AUTH_PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

def add_auth_pending(request_id: str, user_id: int, server: str, level: str, nickname: str, method: str):
    pending = load_auth_pending()
    pending[request_id] = {
        "user_id": user_id,
        "server": server,
        "level": level,
        "nickname": nickname,
        "method": method
    }
    save_auth_pending(pending)

def remove_auth_pending(request_id: str):
    pending = load_auth_pending()
    pending.pop(request_id, None)
    save_auth_pending(pending)


# ========== 핸즈 인증 - 서버 선택 드롭다운 ==========
class AuthServerSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="메이플 서버를 선택하세요",
        custom_id="auth_server_select",
        options=[discord.SelectOption(label=s, value=s) for s in AUTH_SERVER_LIST]
    )
    async def server_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        auth_flow_data[interaction.user.id] = {"server": select.values[0]}
        view = AuthPhotoMethodView()
        await interaction.response.edit_message(
            content=f"✅ 서버: **{select.values[0]}**\n\n📸 핸즈 인증 사진을 어디로 보내셨나요?",
            view=view
        )


# ========== 핸즈 인증 - DM/카톡 선택 ==========
class AuthPhotoMethodView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="💬 DM", style=discord.ButtonStyle.primary, custom_id="auth_method_dm")
    async def dm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = auth_flow_data.get(interaction.user.id, {})
        data["method"] = "DM"
        auth_flow_data[interaction.user.id] = data
        await interaction.response.send_modal(AuthModal())

    @discord.ui.button(label="🟡 카카오톡", style=discord.ButtonStyle.secondary, custom_id="auth_method_kakao")
    async def kakao_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = auth_flow_data.get(interaction.user.id, {})
        data["method"] = "카카오톡"
        auth_flow_data[interaction.user.id] = data
        await interaction.response.send_modal(AuthModal())


# ========== 핸즈 인증 모달 (레벨 + 닉네임) ==========
class AuthModal(discord.ui.Modal, title="핸즈 인증 신청"):
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
        # 디스코드 가입일 30일 미만 체크 (차단 없이 DM만)
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
        method = data.get("method")

        if not server or not method:
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

        admin_channel = bot.get_channel(AUTH_ADMIN_CHANNEL_ID)
        if not admin_channel:
            await interaction.response.send_message("❌ 관리자 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        request_id = str(uuid.uuid4())[:8]
        add_auth_pending(request_id, interaction.user.id, server, level_val, nickname_val, method)

        view = AuthApproveView(request_id=request_id)
        bot.add_view(view)

        await admin_channel.send(
            f"🔐 **핸즈 인증 신청**\n"
            f"신청자: {interaction.user.mention}\n"
            f"서버: **{server}** | 레벨: **{level_val}** | 닉네임: **{nickname_val}**\n"
            f"닉네임 변경: `{interaction.user.display_name}` → `{combined_nick}`\n"
            f"사진 전송 방법: **{method}**",
            view=view
        )

        auth_flow_data.pop(interaction.user.id, None)

        await interaction.response.send_message(
            "✅ 핸즈 인증 신청이 완료됐어요!\n관리자 확인 후 2시간 이내에 처리됩니다.",
            ephemeral=True
        )


# ========== 핸즈 인증 관리자 승인/거절 ==========
class AuthApproveView(discord.ui.View):
    def __init__(self, request_id: str):
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
        approve_btn.callback = self.approve
        reject_btn.callback = self.reject
        self.add_item(approve_btn)
        self.add_item(reject_btn)

    async def approve(self, interaction: discord.Interaction):
        pending = load_auth_pending()
        data = pending.get(self.request_id)
        if not data:
            await interaction.response.send_message("❌ 이미 처리된 신청입니다.", ephemeral=True)
            return

        member = interaction.guild.get_member(data["user_id"])
        if not member:
            await interaction.response.send_message("❌ 유저를 찾을 수 없습니다.", ephemeral=True)
            return

        combined_nick = f"{data['server']}/{data['level']}/{data['nickname']}"

        try:
            await member.edit(nick=combined_nick)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 닉네임 변경 권한 부족!", ephemeral=True)
            return

        # 서버 역할 부여
        await update_server_role(member, data["server"])

        # 핸즈 & 인증유저 역할 부여
        auth_role = discord.utils.get(interaction.guild.roles, name=HANDS_AUTH_ROLE)
        if auth_role:
            try:
                await member.add_roles(auth_role)
            except discord.Forbidden:
                pass

        remove_auth_pending(self.request_id)

        # 유저에게 DM 전송
        try:
            await member.send(
                "**[핸즈인증 완료]**\n\n"
                "★ 거래 전 주의 사항 참고 하세요★\n"
                "https://www.maplediscord.com/tip\n\n"
                "★친구초대★\n"
                "친구에게 디스코드 채널 소개 해주세요\n"
                "디스코드 초대링크 : https://discord.gg/2UwBw8dnSv\n"
                "좋은 하루 보내세요!"
            )
        except discord.Forbidden:
            pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            f"✅ {member.mention} 핸즈 인증 완료!\n닉네임: `{combined_nick}` | 역할 부여 완료"
        )

    async def reject(self, interaction: discord.Interaction):
        pending = load_auth_pending()
        data = pending.get(self.request_id)
        if not data:
            await interaction.response.send_message("❌ 이미 처리된 신청입니다.", ephemeral=True)
            return

        member = interaction.guild.get_member(data["user_id"])
        remove_auth_pending(self.request_id)

        if member:
            try:
                await member.send(
                    "**[메이플디스코드 핸즈인증 거절]**\n\n"
                    "메이플디스코드 핸즈인증 승인이 거절 되었습니다.\n"
                    "사유는 아래 중 하나 입니다. 참고해주세요.\n\n"
                    "1️⃣ 디스코드 가입일이 30일 이내 계정\n\n"
                    "2️⃣ 핸즈인증 사진이 첨부되지 않았어요\n"
                    "　　게임 내 사진 및 메이플스토리 핸즈인증 사진을 보내주세요\n\n"
                    "3️⃣ 캐릭터를 검색해보니 아이템이 하나도 없거나\n"
                    "　　최근 육성하지 않으신 분인 것 같습니다\n\n"
                    "위와 같은 내용에 해당되지 않는데 거절이 되었다면\n"
                    "메이플 디스코드 관리자에게 문의 주세요"
                )
            except discord.Forbidden:
                pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("❌ 핸즈 인증 신청 거절 완료")


# ========== 핸즈 인증 버튼 패널 ==========
class AuthButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔐 핸즈 인증 신청", style=discord.ButtonStyle.success, custom_id="auth_request")
    async def auth_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AuthServerSelectView()
        await interaction.response.send_message(
            "📋 메이플 서버를 선택해주세요:",
            view=view,
            ephemeral=True
        )


@bot.tree.command(name="인증패널", description="핸즈 인증 신청 버튼 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def auth_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async for message in interaction.channel.history(limit=50):
        if message.author == bot.user and message.embeds:
            if message.embeds[0].title == "🍁 핸즈 인증 신청":
                await message.delete()

    embed = discord.Embed(
        title="핸즈인증 신청 방법",
        description=(
            "**절차:**\n"
            "1️⃣ 카카오톡 또는 우측상단 관리자에게\n"
            "2️⃣ 핸즈사진 + 게임 내 사진, 디스코드 닉네임 전달 후\n"
            "3️⃣ 아래 버튼 클릭\n"
            "4️⃣ 서버 선택\n"
            "5️⃣ 인증 사진 보낸 위치 선택 (카톡 / DM)\n"
            "6️⃣ 메이플 레벨 및 닉네임 입력\n"
            "7️⃣ 관리자 확인 후 역할 부여\n\n"
            "⏱️ 신청 후 **2시간 이내**에 처리됩니다."
        ),
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


# ========== 봇 DM 자동 응답 ==========
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if isinstance(message.channel, discord.DMChannel):
        await message.channel.send(
            "안녕하세요! 저는 로봇이에요 🤖\n관리자에게 DM을 보내주세요."
        )
    await bot.process_commands(message)


# ========== 1. 신규 계정 입장 감지 ==========
@bot.event
async def on_member_join(member: discord.Member):
    now = datetime.now(timezone.utc)
    days = (now - member.created_at).days

    if days < 30:
        try:
            await member.send(
                f"안녕하세요 {member.mention}님!\n\n"
                f"⚠️ 디스코드 계정 생성일이 **{days}일** 밖에 되지 않아 "
                f"역할 부여가 제한됩니다.\n"
                f"디스코드 가입 후 **30일이 지나면** 다시 핸즈인증 신청해 주세요.\n\n"
                f"메이플랜드는 한달 이내도 이용 가능합니다."
            )
        except discord.Forbidden:
            pass

        admin_channel = bot.get_channel(AUTH_ADMIN_CHANNEL_ID)
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


# ========== 닉네임 패널 자동 재생성 ==========
async def refresh_nickname_panel(channel: discord.TextChannel):
    async for message in channel.history(limit=50):
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
        nick_flow_data[interaction.user.id] = {"server": select.values[0]}
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
            await interaction.response.send_message("❌ 이미 처리된 신청입니다.", ephemeral=True)
            return

        member = interaction.guild.get_member(data["user_id"])
        if not member:
            await interaction.response.send_message("❌ 유저를 찾을 수 없습니다.", ephemeral=True)
            return

        try:
            await member.edit(nick=data["new"])
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇 권한 부족!", ephemeral=True)
            return

        if data.get("new_server"):
            await update_server_role(member, data["new_server"])

        record_change(str(data["user_id"]), data["previous"], data["new"])
        remove_pending(self.request_id)

        try:
            await member.send(f"✅ **{data['previous']}** 에서 **{data['new']}** 으로 변경됐습니다!")
        except discord.Forbidden:
            pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            f"✅ {member.mention} 닉네임 변경 완료!\n`{data['previous']}` → `{data['new']}`"
        )

    async def reject(self, interaction: discord.Interaction):
        pending = load_pending()
        data = pending.get(self.request_id)
        if not data:
            await interaction.response.send_message("❌ 이미 처리된 신청입니다.", ephemeral=True)
            return

        member = interaction.guild.get_member(data["user_id"])
        remove_pending(self.request_id)

        if member:
            try:
                await member.send("❌ 닉네임 변경 신청이 거절됐습니다. 관리자에게 문의해주세요.")
            except discord.Forbidden:
                pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("❌ 닉네임 변경 신청 거절 완료")


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

    async for message in interaction.channel.history(limit=50):
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


@bot.event
async def on_ready():
    await bot.tree.sync()
    for guild in bot.guilds:
        await bot.tree.sync(guild=guild)
    bot.add_view(NicknameButtonView())
    bot.add_view(AuthButtonView())

    pending = load_pending()
    for request_id in pending:
        bot.add_view(ApproveView(request_id=request_id))

    auth_pending = load_auth_pending()
    for request_id in auth_pending:
        bot.add_view(AuthApproveView(request_id=request_id))

    print(f"✅ {bot.user} 온라인! | 대기 중인 승인: {len(pending)}건 | 인증 대기: {len(auth_pending)}건")


bot.run(BOT_TOKEN)
