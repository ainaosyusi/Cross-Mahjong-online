import asyncio
import logging
import random
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
    result_thread_id: int = 0
    player_ids: list[int] = field(default_factory=list)


class GroupView(discord.ui.View):
    def __init__(self, cog: "GroupCog", match_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_id = match_id

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="withdraw")
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_withdraw(interaction, self.match_id)

    @discord.ui.button(label="追加募集", style=discord.ButtonStyle.primary, custom_id="extra_recruit")
    async def extra_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_extra_recruit(interaction, self.match_id)

    @discord.ui.button(label="グループ解散", style=discord.ButtonStyle.secondary, custom_id="disband")
    async def disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_disband(interaction, self.match_id)


class ExtraRecruitCountView(discord.ui.View):
    """追加募集人数選択"""

    def __init__(self, cog: "GroupCog", match_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.match_id = match_id

    @discord.ui.button(label="1人", style=discord.ButtonStyle.primary)
    async def one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._post_extra_recruit(interaction, self.match_id, 1)

    @discord.ui.button(label="2人", style=discord.ButtonStyle.primary)
    async def two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._post_extra_recruit(interaction, self.match_id, 2)

    @discord.ui.button(label="3人", style=discord.ButtonStyle.primary)
    async def three(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._post_extra_recruit(interaction, self.match_id, 3)


class ExtraJoinView(discord.ui.View):
    """マッチングチャンネルに出す追加参加ボタン"""

    def __init__(self, cog: "GroupCog", match_id: int, needed: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.match_id = match_id
        self.needed = needed

    @discord.ui.button(label="この卓に参加", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_extra_join(interaction, self.match_id, self)


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

        # ボイスチャンネル作成（権限を対戦者のみに制限）
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
        }
        for uid in user_ids:
            member = guild.get_member(uid)
            if member:
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)

        vc = await guild.create_voice_channel(
            name=f"対戦卓-{match_id:03d}",
            overwrites=overwrites,
        )

        # 対戦結果チャンネルに専用スレッドを作成
        result_channel = self.bot.get_channel(config.RESULT_CHANNEL_ID)
        result_thread = None
        if result_channel:
            try:
                result_thread = await result_channel.create_thread(
                    name=f"対戦卓-{match_id:03d} 結果",
                    type=discord.ChannelType.public_thread,
                )
            except discord.HTTPException as e:
                log.warning("結果スレッドの作成に失敗: %s", e)

        # DB更新
        await queries.update_match_channel_ids(match_id, str(thread.id), str(vc.id))

        # MatchInfo 保存
        info = MatchInfo(
            match_id=match_id,
            match_type=match_type,
            thread_id=thread.id,
            voice_channel_id=vc.id,
            result_thread_id=result_thread.id if result_thread else 0,
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
        embed.add_field(
            name="🔊 専用ボイスチャンネル",
            value=f"<#{vc.id}> が作成されました。\nこのボイスチャンネルは**この卓のメンバーだけが参加可能**です。",
            inline=False,
        )
        embed.add_field(
            name="",
            value="部屋番号を共有してゲームを開始してください。",
            inline=False,
        )
        if result_thread:
            embed.add_field(
                name="📸 対戦後のお願い",
                value=f"対戦が終わったら <#{result_thread.id}> にスクリーンショットを投稿してください。自動で結果を認識します。",
                inline=False,
            )
        else:
            embed.add_field(
                name="📸 対戦後のお願い",
                value=f"対戦が終わったら <#{config.RESULT_CHANNEL_ID}> にスクリーンショットを投稿するか、`/result` コマンドで結果を入力してください。",
                inline=False,
            )

        view = GroupView(self, match_id)
        await thread.send(content=mentions, embed=embed, view=view)

        # 結果スレッドにも案内
        if result_thread:
            result_embed = discord.Embed(
                title=f"📸 対戦卓-{match_id:03d} 結果投稿用スレッド",
                description=(
                    f"{type_label}の対戦結果をここに投稿してください。\n\n"
                    "**使い方：**\n"
                    "・雀魂の終局画面スクショを送信 → 自動で順位・スコアを認識\n"
                    "・認識結果が表示されたら「確定」ボタンで記録\n"
                    "・認識失敗時は `/result` コマンドで手動入力\n\n"
                    "誤認識があった場合はダッシュボードから修正できます。"
                ),
                color=discord.Color.blue(),
            )
            await result_thread.send(content=mentions, embed=result_embed, silent=True)

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
                replacement_id = candidates[0]  # 早い者順
                queue.remove(replacement_id)
                info.player_ids.append(replacement_id)

                guild = self.bot.get_guild(config.GUILD_ID)
                rep_member = guild.get_member(replacement_id) if guild else None
                rep_name = rep_member.display_name if rep_member else str(replacement_id)

                rep_member_id = await queries.upsert_member(str(replacement_id), rep_name)
                await queries.add_match_player(match_id, rep_member_id)

                # VCに権限追加
                if guild and rep_member:
                    vc = guild.get_channel(info.voice_channel_id)
                    if vc:
                        await vc.set_permissions(rep_member, view_channel=True, connect=True, speak=True)

                replacement = replacement_id

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

    async def handle_extra_recruit(self, interaction: discord.Interaction, match_id: int) -> None:
        """追加募集ボタン押下 → 人数選択ビューを表示"""
        info = self.active_matches.get(match_id)
        if info is None:
            await interaction.response.send_message("このグループは既に解散しています。", ephemeral=True)
            return
        await interaction.response.send_message(
            "追加で募集する人数を選択してください：",
            view=ExtraRecruitCountView(self, match_id),
            ephemeral=True,
        )

    async def _post_extra_recruit(
        self, interaction: discord.Interaction, match_id: int, needed: int
    ) -> None:
        """マッチングチャンネルに追加募集を投稿"""
        info = self.active_matches.get(match_id)
        if info is None:
            await interaction.response.send_message("グループが見つかりません。", ephemeral=True)
            return

        matching_channel = self.bot.get_channel(config.MATCHING_CHANNEL_ID)
        announce_ch = self.bot.get_channel(config.ANNOUNCE_CHANNEL_ID)

        embed = discord.Embed(
            title=f"📢 対戦卓-{match_id:03d} が追加募集中",
            description=(
                f"**あと {needed} 人** の参加者を募集しています！\n"
                f"下のボタンを押すと参加できます。"
            ),
            color=discord.Color.orange(),
        )

        view = ExtraJoinView(self, match_id, needed)
        if matching_channel:
            msg = await matching_channel.send(embed=embed, view=view)

        if announce_ch:
            announce_embed = discord.Embed(
                title="📢 追加募集のお知らせ",
                description=(
                    f"対戦卓-{match_id:03d} が **あと {needed} 人** を追加募集中！\n"
                    f"<#{config.MATCHING_CHANNEL_ID}> で参加できます。"
                ),
                color=discord.Color.orange(),
            )
            announce_msg = await announce_ch.send(embed=announce_embed)
            # 1時間後自動削除
            asyncio.create_task(self._auto_delete(announce_msg, 3600))

        await interaction.response.send_message(
            f"✅ {needed}人の追加募集を投稿しました。", ephemeral=True
        )

    async def handle_extra_join(
        self, interaction: discord.Interaction, match_id: int, view: ExtraJoinView
    ) -> None:
        """追加募集ボタン経由で参加"""
        info = self.active_matches.get(match_id)
        if info is None:
            await interaction.response.send_message(
                "このグループは既に解散しています。", ephemeral=True
            )
            # ボタンを無効化
            for child in view.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=view)
            except discord.HTTPException:
                pass
            return

        user = interaction.user
        if user.id in info.player_ids:
            await interaction.response.send_message(
                "既にこの卓のメンバーです。", ephemeral=True
            )
            return

        info.player_ids.append(user.id)
        member_id = await queries.upsert_member(str(user.id), user.display_name)
        await queries.add_match_player(match_id, member_id)

        # VC権限追加
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild:
            vc = guild.get_channel(info.voice_channel_id)
            if vc and isinstance(user, discord.Member):
                await vc.set_permissions(user, view_channel=True, connect=True, speak=True)

        # スレッドに通知
        thread = self.bot.get_channel(info.thread_id)
        if thread:
            await thread.send(f"🎉 <@{user.id}> が追加で参加しました！")

        # 募集人数を減らす
        view.needed -= 1
        if view.needed <= 0:
            for child in view.children:
                child.disabled = True
            try:
                await interaction.message.edit(
                    content="募集終了",
                    view=view,
                )
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"✅ 対戦卓-{match_id:03d} に参加しました。", ephemeral=True
        )

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

        # スレッド削除
        thread = self.bot.get_channel(info.thread_id)
        if thread and isinstance(thread, discord.Thread):
            try:
                await thread.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        del self.active_matches[match_id]
        log.info("グループ解散: match_id=%d", match_id)

    @staticmethod
    async def _auto_delete(msg: discord.Message, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

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
