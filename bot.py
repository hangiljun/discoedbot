import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import os
import json

load_dotenv()

# ========== 설정 ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID"))
HISTORY_FILE = "/data/nickname_history.json"
WEEKLY_LIMIT = 1  # 7일 내 자동 변경 허용 횟수 (1 = 첫번째만 자동, 2번째부터 관리자 승인)
# ==========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ========== 신청 기록 관리 ==========
def load_history() -> dict:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_weekly_count(user_id: str) -> int:
    """7일 내 닉네임 변경 횟수 반환"""
    history = load_history()
    records = history.get(user_id, [])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return sum(1 for r in records if r["date"] >= cutoff)

def record_change(user_id: str, previous: str, new: str):
    """변경 기록 저장"""
    history = load_history()
    if user_id not in history:
        history[user_id] = []
    history[user_id].append({
        "date": datetime.now(timezone.utc).isoformat(),
        "previous": previous,
        "new": new
    })
    save_history(history)


# ========== 1. 신규 계정 입장 감지 ==========
@bot.event
async def on_member_join(member: discord.Member):
    now = datetime.now(timezone.utc)
    created = member.created_at
    days = (now - created).days

    if days < 30:
        # 유저에게 DM 발송
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

        # 관리자 채널에 알림 발송
        admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if admin_channel:
            embed = discord.Embed(
                title="⚠️ 신규 계정 입장 감지",
                color=discord.Color.yellow(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="유저", value=member.mention, inline=True)
            embed.add_field(name="계정 생성일", value=f"{created.strftime('%Y-%m-%d')}", inline=True)
            embed.add_field(name="계정 나이", value=f"{days}일", inline=True)
            embed.set_footer(text=f"유저 ID: {member.id}")
            try:
                await admin_channel.send(embed=embed)
            except discord.Forbidden:
                await admin_channel.send(
                    f"⚠️ **신규 계정 입장 감지**\n"
                    f"유저: {member.mention} | 계정 생성: {days}일 | 생성일: {created.strftime('%Y-%m-%d')}"
                )


# ========== 2. 닉네임 변경 신청 모달 ==========
class NicknameModal(discord.ui.Modal, title="닉네임 변경 신청"):
    previous_nickname = discord.ui.TextInput(
        label="이전 닉네임",
        placeholder="현재 사용 중인 게임 내 캐릭터 닉네임",
        max_length=32
    )
    new_nickname = discord.ui.TextInput(
        label="변경할 닉네임",
        placeholder="새로 사용할 게임 내 캐릭터 닉네임",
        max_length=32
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        weekly_count = get_weekly_count(user_id)

        print(f"[닉네임신청] 유저: {interaction.user} | 7일내 횟수: {weekly_count} | 제한: {WEEKLY_LIMIT} | 파일존재: {os.path.exists(HISTORY_FILE)}")

        admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
        if not admin_channel:
            await interaction.response.send_message(
                "❌ 관리자 채널을 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True
            )
            return

        # 7일 내 2번 미만 → 자동 변경
        if weekly_count < WEEKLY_LIMIT:
            try:
                await interaction.user.edit(nick=self.new_nickname.value)
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ 봇 권한 부족! 관리자에게 문의하세요.", ephemeral=True
                )
                return

            record_change(user_id, self.previous_nickname.value, self.new_nickname.value)

            # 관리자 채널에 자동 변경 기록
            log_embed = discord.Embed(
                title="🔄 닉네임 자동 변경",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            log_embed.add_field(name="유저", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="\u200b", value="\u200b", inline=True)
            log_embed.add_field(name="\u200b", value="\u200b", inline=True)
            log_embed.add_field(name="이전 닉네임", value=self.previous_nickname.value, inline=True)
            log_embed.add_field(name="→", value="\u200b", inline=True)
            log_embed.add_field(name="변경 닉네임", value=self.new_nickname.value, inline=True)
            log_embed.set_footer(text=f"유저 ID: {user_id} | 7일 내 {weekly_count + 1}/{WEEKLY_LIMIT}회 사용")
            log_content = (
                f"🔄 **닉네임 자동 변경**\n"
                f"유저: {interaction.user.mention}\n"
                f"`{self.previous_nickname.value}` → `{self.new_nickname.value}`"
            )
            try:
                await admin_channel.send(content=log_content, embed=log_embed)
            except discord.Forbidden:
                await admin_channel.send(content=log_content)

            await interaction.response.send_message(
                f"✅ **{self.previous_nickname.value}** 에서 **{self.new_nickname.value}** 으로 변경됐습니다!",
                ephemeral=True
            )

        # 7일 내 2번 이상 → 관리자 승인 필요
        else:
            review_embed = discord.Embed(
                title="⚠️ 닉네임 변경 승인 필요",
                description=f"7일 내 {weekly_count}회 변경 이력으로 관리자 승인이 필요합니다.",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            review_embed.add_field(name="신청자", value=interaction.user.mention, inline=True)
            review_embed.add_field(name="\u200b", value="\u200b", inline=True)
            review_embed.add_field(name="\u200b", value="\u200b", inline=True)
            review_embed.add_field(name="이전 닉네임", value=self.previous_nickname.value, inline=True)
            review_embed.add_field(name="→", value="\u200b", inline=True)
            review_embed.add_field(name="변경 닉네임", value=self.new_nickname.value, inline=True)
            review_embed.set_footer(text=f"유저 ID: {user_id} | 7일 내 {weekly_count}/{WEEKLY_LIMIT}회 사용")

            view = ApproveView(
                user=interaction.user,
                previous_nickname=self.previous_nickname.value,
                new_nickname=self.new_nickname.value
            )

            content = (
                f"⚠️ **닉네임 변경 승인 필요**\n"
                f"신청자: {interaction.user.mention}\n"
                f"이전 닉네임: `{self.previous_nickname.value}` → 변경 닉네임: `{self.new_nickname.value}`\n"
                f"7일 내 {weekly_count}회 변경 이력"
            )
            try:
                await admin_channel.send(content=content, embed=review_embed, view=view)
            except discord.Forbidden:
                await admin_channel.send(content=content, view=view)
            await interaction.response.send_message(
                "⚠️ 7일 내 변경 횟수를 초과하여 관리자 승인이 필요합니다.\n"
                "승인 후 1~3시간 이내에 변경됩니다.",
                ephemeral=True
            )


# ========== 3. 관리자 승인/거절 버튼 ==========
class ApproveView(discord.ui.View):
    def __init__(self, user: discord.Member, previous_nickname: str, new_nickname: str):
        super().__init__(timeout=None)
        self.user = user
        self.previous_nickname = previous_nickname
        self.new_nickname = new_nickname

    @discord.ui.button(label="✅ 승인", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.user.edit(nick=self.new_nickname)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 봇 권한 부족! (봇 역할이 대상 유저보다 높아야 합니다)", ephemeral=True
            )
            return

        record_change(str(self.user.id), self.previous_nickname, self.new_nickname)

        log_embed = discord.Embed(
            title="✅ 닉네임 변경 승인 완료",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.add_field(name="대상 유저", value=self.user.mention, inline=True)
        log_embed.add_field(name="\u200b", value="\u200b", inline=True)
        log_embed.add_field(name="\u200b", value="\u200b", inline=True)
        log_embed.add_field(name="이전 닉네임", value=self.previous_nickname, inline=True)
        log_embed.add_field(name="→", value="\u200b", inline=True)
        log_embed.add_field(name="변경된 닉네임", value=self.new_nickname, inline=True)
        log_embed.add_field(name="처리한 관리자", value=interaction.user.mention, inline=False)
        log_embed.set_footer(text=f"유저 ID: {self.user.id}")

        try:
            await self.user.send(f"✅ **{self.previous_nickname}** 에서 **{self.new_nickname}** 으로 변경됐습니다!")
        except discord.Forbidden:
            pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=log_embed)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        log_embed = discord.Embed(
            title="❌ 닉네임 변경 거절",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        log_embed.add_field(name="대상 유저", value=self.user.mention, inline=True)
        log_embed.add_field(name="이전 닉네임", value=self.previous_nickname, inline=True)
        log_embed.add_field(name="변경 요청 닉네임", value=self.new_nickname, inline=True)
        log_embed.add_field(name="처리한 관리자", value=interaction.user.mention, inline=False)
        log_embed.set_footer(text=f"유저 ID: {self.user.id}")

        try:
            await self.user.send("❌ 닉네임 변경 신청이 거절됐습니다. 관리자에게 문의해주세요.")
        except discord.Forbidden:
            pass

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=log_embed)


# ========== 4. 닉네임 변경 버튼 패널 ==========
class NicknameButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 닉네임 변경 신청", style=discord.ButtonStyle.primary, custom_id="nickname_request")
    async def request_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NicknameModal())


@tree.command(name="닉네임패널", description="닉네임 변경 신청 버튼 생성 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def nickname_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    # 기존 패널 메시지 삭제
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
            "2️⃣ 이전 닉네임 / 변경할 닉네임 입력\n"
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
    await tree.sync()
    bot.add_view(NicknameButtonView())
    print(f"✅ {bot.user} 온라인!")


bot.run(BOT_TOKEN)
