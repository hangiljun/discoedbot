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
HISTORY_FILE = "/data/nickname_history.json"
PENDING_FILE = "/data/pending_approvals.json"
WEEKLY_LIMIT = 1
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
}

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

        admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
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


# ========== 2. 닉네임 변경 신청 모달 ==========
class NicknameModal(discord.ui.Modal, title="닉네임 변경 신청"):
    server = discord.ui.TextInput(
        label="서버",
        placeholder="예) 크로아, 베라, 스카니아, 루나, 오로라 등",
        max_length=20
    )
    level = discord.ui.TextInput(
        label="레벨",
        placeholder="예) 285",
        max_length=10
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

        server_input = self.server.value.strip()
        level_input = self.level.value.strip()

        # 레벨 유효성 검사
        if not level_input.isdigit() or not (1 <= int(level_input) <= 300):
            await interaction.response.send_message(
                "❌ 레벨은 **숫자**만 입력 가능하며 **1~300** 사이여야 합니다.\n예) 285",
                ephemeral=True
            )
            return

        # 서버 유효성 검사
        if server_input not in SERVER_ROLES:
            server_list = ", ".join(SERVER_ROLES.keys())
            await interaction.response.send_message(
                f"❌ 서버명을 정확히 입력해주세요.\n가능한 서버: **{server_list}**",
                ephemeral=True
            )
            return

        combined_nickname = f"{server_input}/{level_input}/{self.new_nickname.value.strip()}"

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
        await interaction.response.send_modal(NicknameModal())


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
    bot.add_view(NicknameButtonView())

    pending = load_pending()
    for request_id in pending:
        bot.add_view(ApproveView(request_id=request_id))

    print(f"✅ {bot.user} 온라인! | 대기 중인 승인: {len(pending)}건")


bot.run(BOT_TOKEN)
