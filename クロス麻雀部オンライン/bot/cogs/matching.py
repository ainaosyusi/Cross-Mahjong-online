import asyncio
import json
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import queries
from services.queue import QueueService
from services.timeutil import is_active, INACTIVE_MESSAGE

log = logging.getLogger("matching")

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "matching_state.json")


def _save_state(message_id: int, channel_id: int, part: int = 1) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump({"message_id": message_id, "channel_id": channel_id, "part": part}, f)


def _load_state() -> dict | None:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _clear_state() -> None:
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass


class MatchingView(discord.ui.View):
    def __init__(self, cog: "MatchingCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="4人戦に参加", style=discord.ButtonStyle.primary, custom_id="join_4")
    async def join_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, "4")

    @discord.ui.button(label="3人戦に参加", style=discord.ButtonStyle.primary, custom_id="join_3")
    async def join_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, "3")

    @discord.ui.button(label="両方に参加", style=discord.ButtonStyle.success, custom_id="join_both")
    async def join_both(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, "both")

    @discord.ui.button(label="参加取消", style=discord.ButtonStyle.secondary, custom_id="cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_cancel(interaction)

    @discord.ui.button(label="📣 募集通知", style=discord.ButtonStyle.secondary, custom_id="notify_announce", row=1)
    async def notify_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_notify_announce(interaction)


class MatchingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = QueueService()
        self.recruitment_message: discord.Message | None = None
        self.current_part: int = 1
        self.last_notify_time: float = 0.0  # 募集通知の最終実行時刻（UNIX秒）

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(MatchingView(self))
        # 再起動後に募集メッセージを復元
        state = _load_state()
        if state:
            try:
                ch = self.bot.get_channel(state["channel_id"])
                if ch:
                    self.recruitment_message = await ch.fetch_message(state["message_id"])
                    self.current_part = state.get("part", self._detect_current_part())
                    log.info("募集メッセージを復元: %s（%d部）", state["message_id"], self.current_part)
            except (discord.NotFound, discord.HTTPException):
                _clear_state()
                self.recruitment_message = None

        # 稼働時間内なのに募集メッセージがない場合、自動で募集開始
        if self.recruitment_message is None and is_active():
            part = self._detect_current_part()
            log.info("稼働時間内のため募集を自動開始（%d部）", part)
            await self.start_recruitment(part=part)

    @staticmethod
    def _detect_current_part() -> int:
        from services.timeutil import now_jst
        hour = now_jst().hour
        return 2 if hour < config.ACTIVE_END_HOUR else 1

    async def start_recruitment(self, part: int = 1) -> None:
        channel = self.bot.get_channel(config.MATCHING_CHANNEL_ID)
        if channel is None:
            log.error("マッチングチャンネルが見つかりません: %s", config.MATCHING_CHANNEL_ID)
            return

        # 前の部の募集メッセージを削除
        if self.recruitment_message:
            try:
                await self.recruitment_message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            self.recruitment_message = None

        self.queue.clear()
        self.current_part = part
        embed = self._build_embed()
        view = MatchingView(self)
        self.recruitment_message = await channel.send(embed=embed, view=view)
        _save_state(self.recruitment_message.id, channel.id, part)
        log.info("募集開始（%d部）", part)

        # アナウンスチャンネルに通知
        announce_ch = self.bot.get_channel(config.ANNOUNCE_CHANNEL_ID)
        if announce_ch:
            if part == 1:
                time_range = "20:00〜24:00"
            else:
                time_range = "0:00〜4:00"
            embed = discord.Embed(
                title=f"🀄 麻雀部 第{part}部 開催！",
                description=(
                    f"**{time_range}** まで対戦できます。\n\n"
                    f"<#{config.MATCHING_CHANNEL_ID}> で参加ボタンを押してください。\n\n"
                    "📊 [成績ダッシュボード](https://mj.kyoten-hub.com)"
                ),
                color=discord.Color.green(),
            )
            await announce_ch.send(embed=embed)

    async def handle_join(self, interaction: discord.Interaction, entry_type: str) -> None:
        if not is_active():
            await interaction.response.send_message(INACTIVE_MESSAGE, ephemeral=True)
            return
        user = interaction.user
        if self.queue.is_in_queue(user.id):
            self.queue.remove(user.id)

        prev_count_4 = self.queue.count_4()
        prev_count_3 = self.queue.count_3()
        self.queue.add(user.id, entry_type, user.display_name)
        await queries.upsert_member(str(user.id), user.display_name)

        labels = {"4": "4人戦", "3": "3人戦", "both": "両方"}
        await interaction.response.send_message(
            f"{labels[entry_type]}に参加登録しました。", ephemeral=True
        )
        await self._update_display()

        # あと1人通知（カウント変化で閾値をまたいだ時のみ）
        new_count_4 = self.queue.count_4()
        new_count_3 = self.queue.count_3()
        if prev_count_4 < 3 <= new_count_4 < 4:
            await self._announce_one_more(4)
        if prev_count_3 < 2 <= new_count_3 < 3:
            await self._announce_one_more(3)

        await self._try_match(interaction.channel)

    async def handle_notify_announce(self, interaction: discord.Interaction) -> None:
        """募集通知ボタン: 1時間に1回、現在の待機状況をアナウンスに投稿"""
        if not is_active():
            await interaction.response.send_message(INACTIVE_MESSAGE, ephemeral=True)
            return

        import time
        now = time.time()
        elapsed = now - self.last_notify_time
        cooldown = 3600  # 1時間

        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            mins = remaining // 60
            secs = remaining % 60
            await interaction.response.send_message(
                f"⏳ 次の募集通知まで **{mins}分{secs}秒** お待ちください。",
                ephemeral=True,
            )
            return

        announce_ch = self.bot.get_channel(config.ANNOUNCE_CHANNEL_ID)
        if not announce_ch:
            await interaction.response.send_message(
                "アナウンスチャンネルが見つかりません。", ephemeral=True
            )
            return

        count_4 = self.queue.count_4()
        count_3 = self.queue.count_3()
        total = count_4 + count_3

        if total == 0:
            desc = "現在、待機中の参加者はまだいません。\n一緒に打てる方を募集中です！"
        else:
            desc = (
                f"**現在 {total} 人が待機中！**\n"
                f"・4人戦：{count_4}人\n"
                f"・3人戦：{count_3}人\n\n"
                f"参加可能な方はぜひ！"
            )

        embed = discord.Embed(
            title="📣 麻雀 募集中！",
            description=(
                f"{desc}\n\n"
                f"<#{config.MATCHING_CHANNEL_ID}> で参加ボタンを押してください。"
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"通知者: {interaction.user.display_name}")
        msg = await announce_ch.send(embed=embed)
        asyncio.create_task(self._auto_delete(msg, 3600))

        self.last_notify_time = now
        await interaction.response.send_message(
            "📣 募集通知を送信しました。", ephemeral=True
        )

    async def _announce_one_more(self, match_type: int) -> None:
        """残り1人通知（1時間後に自動削除）"""
        announce_ch = self.bot.get_channel(config.ANNOUNCE_CHANNEL_ID)
        if not announce_ch:
            return
        embed = discord.Embed(
            title=f"🔔 麻雀参加あと1人！",
            description=(
                f"**{match_type}人戦** の参加者があと1人で揃います！\n"
                f"<#{config.MATCHING_CHANNEL_ID}> で参加ボタンを押してください。"
            ),
            color=discord.Color.orange(),
        )
        msg = await announce_ch.send(embed=embed)
        # 1時間後に自動削除
        asyncio.create_task(self._auto_delete(msg, 3600))

    @staticmethod
    async def _auto_delete(msg: discord.Message, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def handle_cancel(self, interaction: discord.Interaction) -> None:
        if not is_active():
            await interaction.response.send_message(INACTIVE_MESSAGE, ephemeral=True)
            return
        user = interaction.user
        if not self.queue.is_in_queue(user.id):
            await interaction.response.send_message("参加登録されていません。", ephemeral=True)
            return

        self.queue.remove(user.id)
        await interaction.response.send_message("参加を取り消しました。", ephemeral=True)
        await self._update_display()

    async def _try_match(self, channel) -> None:
        # 4人戦優先
        selected = self.queue.try_match_4()
        if selected:
            group_cog = self.bot.get_cog("GroupCog")
            if group_cog:
                await group_cog.create_match_group(selected, config.MATCH_TYPE_4)
            await self._update_display()
            await self._try_match(channel)
            return

        # 3人戦
        selected = self.queue.try_match_3()
        if selected:
            group_cog = self.bot.get_cog("GroupCog")
            if group_cog:
                await group_cog.create_match_group(selected, config.MATCH_TYPE_3)
            await self._update_display()
            await self._try_match(channel)

    async def _update_display(self) -> None:
        if self.recruitment_message is None:
            return
        try:
            embed = self._build_embed()
            await self.recruitment_message.edit(embed=embed)
        except discord.NotFound:
            self.recruitment_message = None

    def _build_embed(self) -> discord.Embed:
        part_label = f"第{self.current_part}部" if hasattr(self, "current_part") else ""
        embed = discord.Embed(
            title=f"🀄 麻雀部 {part_label} 開催中！",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="待機状況",
            value=(
                f"4人戦：**{self.queue.count_4()}人** 待機中\n"
                f"3人戦：**{self.queue.count_3()}人** 待機中"
            ),
            inline=False,
        )
        # 参加者一覧
        names_4 = [self.queue.get_name(uid) for uid in self.queue.get_queue_4()]
        names_3 = [self.queue.get_name(uid) for uid in self.queue.get_queue_3() if uid not in self.queue.get_queue_4()]
        members_text = ""
        if names_4:
            members_text += f"**4人戦待ち:** {', '.join(names_4)}\n"
        if names_3:
            members_text += f"**3人戦待ち:** {', '.join(names_3)}\n"
        if members_text:
            embed.add_field(name="参加者", value=members_text, inline=False)
        return embed

    @app_commands.command(name="start_matching", description="手動で募集を開始します")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_matching_command(self, interaction: discord.Interaction):
        part = self._detect_current_part()
        await interaction.response.send_message(f"第{part}部の募集を開始します。", ephemeral=True)
        await self.start_recruitment(part=part)

    @app_commands.command(name="stop_matching", description="募集を停止します")
    @app_commands.checks.has_permissions(administrator=True)
    async def stop_matching_command(self, interaction: discord.Interaction):
        self.queue.clear()
        if self.recruitment_message:
            try:
                embed = discord.Embed(
                    title="🀄 本日の募集は終了しました",
                    color=discord.Color.greyple(),
                )
                await self.recruitment_message.edit(embed=embed, view=None)
            except discord.NotFound:
                pass
            self.recruitment_message = None
        _clear_state()
        await interaction.response.send_message("募集を停止しました。", ephemeral=True)
        log.info("募集停止")


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchingCog(bot))
