import logging
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import queries

log = logging.getLogger("group")


@dataclass
class MatchInfo:
    match_id: int
    match_type: int
    thread_id: int
    voice_channel_id: int
    player_ids: list[int] = field(default_factory=list)


class GroupView(discord.ui.View):
    def __init__(self, cog: "GroupCog", match_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_id = match_id

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="withdraw")
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_withdraw(interaction, self.match_id)

    @discord.ui.button(label="グループ解散", style=discord.ButtonStyle.secondary, custom_id="disband")
    async def disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_disband(interaction, self.match_id)


class GroupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_matches: dict[int, MatchInfo] = {}

    async def create_match_group(self, user_ids: list[int], match_type: int) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            return

        # DB登録
        match_id = await queries.create_match(match_type)
        for uid in user_ids:
            member_id = await queries.upsert_member(str(uid), str(uid))
            await queries.add_match_player(match_id, member_id)

        # スレッド作成
        matching_channel = self.bot.get_channel(config.MATCHING_CHANNEL_ID)
        thread = await matching_channel.create_thread(
            name=f"対戦卓-{match_id:03d}",
            type=discord.ChannelType.public_thread,
        )

        # ボイスチャンネル作成
        vc = await guild.create_voice_channel(
            name=f"対戦卓-{match_id:03d}",
        )

        # DB更新
        await queries.update_match_channel_ids(match_id, str(thread.id), str(vc.id))

        # MatchInfo 保存
        info = MatchInfo(
            match_id=match_id,
            match_type=match_type,
            thread_id=thread.id,
            voice_channel_id=vc.id,
            player_ids=list(user_ids),
        )
        self.active_matches[match_id] = info

        # メンバー表示名を取得してメンション作成
        mentions = " ".join(f"<@{uid}>" for uid in user_ids)
        type_label = "4人戦" if match_type == 4 else "3人戦"

        embed = discord.Embed(
            title=f"🎉 {type_label} マッチング成立！",
            color=discord.Color.gold(),
        )
        embed.add_field(name="メンバー", value=mentions, inline=False)
        embed.add_field(name="ボイスチャンネル", value=f"🔊 対戦卓-{match_id:03d}", inline=False)
        embed.add_field(
            name="",
            value="部屋番号を共有してゲームを開始してください。",
            inline=False,
        )
        embed.add_field(
            name="📸 対戦後のお願い",
            value=f"対戦が終わったら <#{config.RESULT_CHANNEL_ID}> にスクリーンショットを投稿するか、`/result` コマンドで結果を入力してください。",
            inline=False,
        )

        view = GroupView(self, match_id)
        await thread.send(content=mentions, embed=embed, view=view)

        # メンバー表示名を更新
        for uid in user_ids:
            member = guild.get_member(uid)
            if member:
                await queries.upsert_member(str(uid), member.display_name)

        log.info("マッチング成立: match_id=%d type=%d players=%s", match_id, match_type, user_ids)

    async def handle_withdraw(self, interaction: discord.Interaction, match_id: int) -> None:
        info = self.active_matches.get(match_id)
        if info is None:
            await interaction.response.send_message("このグループは既に解散しています。", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in info.player_ids:
            await interaction.response.send_message("このグループのメンバーではありません。", ephemeral=True)
            return

        # 辞退処理
        info.player_ids.remove(user_id)
        member = await queries.get_member_by_discord_id(str(user_id))
        if member:
            await queries.remove_match_player(match_id, member["id"])

        # 補充試行
        matching_cog = self.bot.get_cog("MatchingCog")
        replacement = None
        if matching_cog:
            queue = matching_cog.queue
            if info.match_type == 4:
                candidates = queue.get_queue_4()
            else:
                candidates = queue.get_queue_3()

            if candidates:
                import random
                replacement_id = random.choice(candidates)
                queue.remove(replacement_id)
                info.player_ids.append(replacement_id)

                guild = self.bot.get_guild(config.GUILD_ID)
                rep_member = guild.get_member(replacement_id) if guild else None
                rep_name = rep_member.display_name if rep_member else str(replacement_id)

                rep_member_id = await queries.upsert_member(str(replacement_id), rep_name)
                await queries.add_match_player(match_id, rep_member_id)

                replacement = replacement_id

        thread = self.bot.get_channel(info.thread_id)

        if replacement:
            await interaction.response.send_message(
                f"⚠️ <@{user_id}> が辞退しました。\n"
                f"待機キューから <@{replacement}> が補充されました。",
            )
            if matching_cog:
                await matching_cog._update_display()
        else:
            await interaction.response.send_message(
                f"⚠️ <@{user_id}> が辞退しました。\n"
                f"補充できるメンバーがいないため、グループを解散します。",
            )
            await self._disband_match(match_id)

    async def handle_disband(self, interaction: discord.Interaction, match_id: int) -> None:
        info = self.active_matches.get(match_id)
        if info is None:
            await interaction.response.send_message("このグループは既に解散しています。", ephemeral=True)
            return

        await interaction.response.send_message("グループを解散します。")
        await self._disband_match(match_id)

    async def _disband_match(self, match_id: int) -> None:
        info = self.active_matches.get(match_id)
        if info is None:
            return

        await queries.update_match_status(match_id, "disbanded")

        # ボイスチャンネル削除
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild:
            vc = guild.get_channel(info.voice_channel_id)
            if vc:
                try:
                    await vc.delete()
                except discord.NotFound:
                    pass

        # スレッドアーカイブ
        thread = self.bot.get_channel(info.thread_id)
        if thread and isinstance(thread, discord.Thread):
            try:
                await thread.send("このグループは解散しました。")
                await thread.edit(archived=True)
            except discord.NotFound:
                pass

        del self.active_matches[match_id]
        log.info("グループ解散: match_id=%d", match_id)

    @app_commands.command(name="disband", description="対戦グループを解散します")
    async def disband_command(self, interaction: discord.Interaction):
        # スレッドIDからマッチを特定
        for mid, info in self.active_matches.items():
            if info.thread_id == interaction.channel_id:
                await interaction.response.send_message("グループを解散します。")
                await self._disband_match(mid)
                return
        await interaction.response.send_message("対戦スレッド内で使用してください。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GroupCog(bot))
