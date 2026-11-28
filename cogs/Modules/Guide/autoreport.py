"""Quick reports (🚩 reactions → the /guia model reviews the message against the rules → report card for staff)."""

import asyncio
import io
import logging
import time

import discord
from discord import ui
from discord.ext import commands

from core.autoreport import CONTEXT_MESSAGES, DAY, MAX_CHANNELS, MAX_RULES_CHARS, REPORTS, SYSTEM, Abuse, Now, ParseVerdict, Settings, UserPrompt
from core.guide import ALLOWED, ExtractText, GuideError

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
ABUSE_ALERT_EVERY = 6 * 3600  # one abuse alert per reporter every 6 h


def Store():
    from cogs.Modules.Guide.guide import Store as GuideStore

    return GuideStore()


def Db():
    from core.db import db

    return db


async def Config(guild_id: int) -> tuple[dict, dict]:
    Doc = await Store().Get(guild_id) or {}
    return Doc, Settings(Doc)


async def SaveSettings(guild_id: int, changes: dict):
    await Store().guides.update_one({"_id": guild_id}, {"$set": {f"autoreport.{K}": V for K, V in changes.items()}}, upsert=True)


def Quote(text: str, limit: int = 1000) -> str:
    Text = (text or "").strip()[:limit] or "*(sin texto)*"
    return "\n".join(f"> {L}" for L in Text.splitlines()[:15])


# ---------------- the report card ----------------


async def CardEmbed(guild: discord.Guild, report: dict) -> discord.Embed:
    V = report.get("verdict")
    Color = discord.Color.light_grey()
    if V:
        Color = (discord.Color.red() if V["confianza"] != "baja" else discord.Color.orange()) if V["sancionable"] else discord.Color.green()
    embed = discord.Embed(title="🚩 Reporte rápido", url=report["jump"], color=Color, timestamp=Now())
    embed.set_author(name=f"{report['author_name']} ({report['author_id']})", icon_url=report.get("author_avatar") or None)
    Files = f"\n-# 📎 {report['attachments']} adjunto(s): la IA no ve imágenes." if report.get("attachments") else ""
    embed.description = f"{Quote(report['content'])}{Files}\n\n🔗 [Ir al mensaje]({report['jump']}) · <#{report['channel_id']}>"
    if V:
        Verdict = "⚠️ **Parece sancionable**" if V["sancionable"] else "✅ **No parece sancionable**"
        embed.add_field(name="🤖 Veredicto de LOJI", value=f"{Verdict}\n{V['motivo'] or '—'}"[:1024], inline=False)
        if V["norma"]:
            embed.add_field(name="📜 Norma", value=V["norma"][:1024], inline=False)
        if V["sancionable"] and V["sugerencia"]:
            embed.add_field(name="⚖️ Sugerencia", value=V["sugerencia"][:1024], inline=False)
    else:
        embed.add_field(name="🤖 Veredicto de LOJI", value=f"❔ **Sin revisar** · {report.get('note') or 'no se pudo consultar a la IA'}", inline=False)
    embed.add_field(name="🙋 Reportado por", value=" ".join(f"<@{R}>" for R in report["reporters"])[:1024], inline=True)
    History = await Db()[REPORTS].count_documents({"guild_id": guild.id, "author_id": report["author_id"], "_id": {"$ne": report["_id"]}})
    False_ = await Db()[REPORTS].count_documents({"guild_id": guild.id, "reporters": {"$in": report["reporters"]}, "status": "false"})
    embed.add_field(
        name="📊 Historial",
        value=f"Reportes previos de <@{report['author_id']}>: **{History}**\nFalsas alarmas de quienes reportan: **{False_}**",
        inline=True,
    )
    embed.set_footer(
        text=(f"Confianza: {V['confianza']} · " if V else "") + f"La IA puede equivocarse: revisa el contexto · ID {report['_id']}",
        icon_url=guild.me.display_avatar.url if guild.me else None,
    )
    return embed


class ReportButton(ui.DynamicItem[ui.Button], template=r"qr:(?P<id>[A-Z0-9]{8}):(?P<act>fa|ok)"):
    def __init__(self, report_id: str, act: str):
        Labels = {"fa": ("Falsa alarma", "✅", discord.ButtonStyle.grey), "ok": ("Se actuará", "⚖️", discord.ButtonStyle.red)}
        Label, Emoji, Style = Labels[act]
        super().__init__(ui.Button(label=Label, emoji=Emoji, style=Style, custom_id=f"qr:{report_id}:{act}"))
        self.report_id, self.act = report_id, act

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["id"], match["act"])

    async def callback(self, interaction: discord.Interaction):
        from core.mail.config import Mail
        from core.ticket_access import IsTicketStaff

        if not IsTicketStaff(interaction.user, [], await Mail().Get(interaction.guild.id)):
            return await interaction.response.send_message("❌ Solo el staff puede resolver reportes.", ephemeral=True)
        Status = "false" if self.act == "fa" else "act"
        Done = await Db()[REPORTS].find_one_and_update(
            {"_id": self.report_id, "guild_id": interaction.guild.id, "status": None},
            {"$set": {"status": Status, "handled_by": interaction.user.id, "handled_at": Now()}},
        )
        if not Done:
            return await interaction.response.send_message("Este reporte ya lo resolvió otra persona.", ephemeral=True)
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.dark_grey() if Status == "false" else LOJI_RED
        embed.add_field(
            name="📌 Resolución",
            value=("✅ **Falsa alarma**" if Status == "false" else "⚖️ **Se actuará**") + f" · {interaction.user.mention} {discord.utils.format_dt(Now(), 'R')}",
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=None)


def CardView(report_id: str) -> ui.View:
    View = ui.View(timeout=None)
    View.add_item(ReportButton(report_id, "fa"))
    View.add_item(ReportButton(report_id, "ok"))
    return View


# ---------------- the cog ----------------


class AutoReport(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.locks: dict[int, asyncio.Lock] = {}
        self.alerted: dict[tuple[int, int], float] = {}

    async def cog_load(self):
        self.client.add_dynamic_items(ReportButton)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not payload.guild_id or (payload.member and payload.member.bot):
            return
        Doc, S = await Config(payload.guild_id)
        if not S["enabled"] or payload.channel_id not in S["channels"] or str(payload.emoji) != S["emoji"]:
            return
        Lock = self.locks.setdefault(payload.message_id, asyncio.Lock())
        async with Lock:
            if await Db()[REPORTS].find_one({"message_id": payload.message_id}, {"_id": 1}):
                return  # already reported
            Guild = self.client.get_guild(payload.guild_id)
            Channel = Guild.get_channel(payload.channel_id) if Guild else None
            if not Channel:
                return
            try:
                Message = await Channel.fetch_message(payload.message_id)
            except discord.HTTPException:
                return
            if Message.author.bot:
                return
            Reaction = next((R for R in Message.reactions if str(R.emoji) == S["emoji"]), None)
            if not Reaction:
                return
            Reporters = [U.id async for U in Reaction.users() if not U.bot and U.id != Message.author.id]
            if len(Reporters) < int(S["threshold"]):
                return
            try:
                await self.Report(Guild, Channel, Message, Reporters, Doc, S)
            except Exception as e:
                logger.exception(f"[AutoReport] Report failed for {Message.id}: {e!r}")

    async def Report(self, guild, channel, message: discord.Message, reporters: list[int], doc: dict, s: dict):
        from core.economy.shop import NewId

        Report = {
            "_id": NewId(8), "guild_id": guild.id, "message_id": message.id, "channel_id": channel.id, "jump": message.jump_url,
            "author_id": message.author.id, "author_name": message.author.display_name, "author_avatar": message.author.display_avatar.url,
            "content": message.content or "", "attachments": len(message.attachments), "reporters": reporters,
            "at": Now(), "status": None, "verdict": None, "ai": False, "note": "",
        }
        Report["verdict"], Report["note"], Report["ai"] = await self.Review(guild, channel, message, doc, s)
        Card = await CardEmbed(guild, Report)
        # The message text lives only in the card (in Discord), not in our database.
        await Db()[REPORTS].insert_one({K: V for K, V in Report.items() if K not in ("content", "author_avatar")})
        Staff = guild.get_channel(s["staff_channel"] or 0)
        if not Staff:
            return logger.warning(f"[AutoReport] No staff channel in {guild.id}")
        Role = guild.get_role(s.get("ping_role") or 0)
        Sent = await Staff.send(
            content=Role.mention if Role else None, embed=Card, view=CardView(Report["_id"]),
            allowed_mentions=discord.AllowedMentions(roles=[Role] if Role else False, users=False),
        )
        await Db()[REPORTS].update_one({"_id": Report["_id"]}, {"$set": {"card": {"channel": Staff.id, "id": Sent.id}}})
        await self.CheckAbuse(guild, Staff, Report, s)

    async def Review(self, guild, channel, message, doc: dict, s: dict) -> tuple[dict | None, str, bool]:
        """(verdict, note when there's none, whether the AI was used)."""
        Key = await Store().Key(guild.id)
        Rules = doc.get("rules_text")
        if not Rules:
            return None, "no hay normas cargadas (`/config` → Mando Central → Guía → Autoreporte)", False
        if not Key:
            return None, "falta la key de Groq", False
        Used = await Db()[REPORTS].count_documents({"guild_id": guild.id, "ai": True, "at": {"$gte": Now() - DAY}})
        if Used >= int(s["daily_limit"]):
            return None, f"límite diario de revisiones con IA alcanzado ({s['daily_limit']})", False
        if not (message.content or "").strip():
            return None, "el mensaje no tiene texto (la IA no ve imágenes)", False
        Context = []
        try:
            async for M in channel.history(limit=CONTEXT_MESSAGES, before=message):
                if M.content:
                    Context.append({"author": M.author.display_name, "content": M.content})
        except discord.HTTPException:
            pass
        from core.guide import Complete

        try:
            Text, _ = await Complete(
                Key, SYSTEM.format(server=guild.name, rules=Rules),
                UserPrompt({"author": message.author.display_name, "content": message.content}, list(reversed(Context))),
                json_mode=True,
            )
            return ParseVerdict(Text), "", True
        except GuideError as e:
            return None, str(e), False
        except ValueError:
            return None, "la IA respondió algo que no entendí", True

    async def CheckAbuse(self, guild, staff, report: dict, s: dict):
        Recent = await Db()[REPORTS].find({"guild_id": guild.id, "at": {"$gte": Now() - DAY}}).to_list(length=None)
        for Reporter in report["reporters"]:
            Problems = Abuse(Recent, Reporter, report["author_id"], Now(), s)
            Key = (guild.id, Reporter)
            if not Problems or time.monotonic() - self.alerted.get(Key, -1e9) < ABUSE_ALERT_EVERY:
                continue
            self.alerted[Key] = time.monotonic()
            embed = discord.Embed(
                title="🚨 Posible abuso del reporte rápido",
                description=f"<@{Reporter}> " + " y ".join(Problems) + ".\n-# Puede ser alguien muy atento… o alguien usando 🚩 para molestar. Revisa sus reportes.",
                color=discord.Color.dark_red(), timestamp=Now(),
            )
            Falses = await Db()[REPORTS].count_documents({"guild_id": guild.id, "reporters": Reporter, "status": "false"})
            embed.add_field(name="Falsas alarmas suyas", value=str(Falses), inline=True)
            try:
                await staff.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass


# ---------------- /config → Mando Central → Guía de sanciones → Autoreporte ----------------


async def PanelEmbed(guild: discord.Guild) -> discord.Embed:
    Doc, S = await Config(guild.id)
    Used = await Db()[REPORTS].count_documents({"guild_id": guild.id, "ai": True, "at": {"$gte": Now() - DAY}})
    embed = discord.Embed(title="🚩 Autoreporte", color=LOJI_RED)
    embed.description = (
        ("✅ **Activado.**" if S["enabled"] else "⏸️ **Desactivado.**")
        + f" Cuando un mensaje de los canales vigilados recibe **{S['threshold']}× {S['emoji']}** de personas distintas, LOJI lo revisa "
        "con la IA según vuestras normas y manda la ficha al staff (sea sancionable o no). Solo se envía a la IA el mensaje reportado y un poco de contexto."
    )
    embed.add_field(
        name=f"👁️ Canales vigilados ({len(S['channels'])})", value=" ".join(f"<#{C}>" for C in S["channels"])[:1024] or "*sin elegir*", inline=True,
    )
    embed.add_field(name="📥 Fichas al staff", value=f"<#{S['staff_channel']}>" if S["staff_channel"] else "*sin elegir*", inline=True)
    embed.add_field(name="🔔 Avisar a", value=f"<@&{S['ping_role']}>" if S.get("ping_role") else "*nadie*", inline=True)
    Rules = Doc.get("rules_text")
    embed.add_field(
        name="📜 Normas", value=f"`{Doc.get('rules_filename', 'normas')}` · ~{len(Rules) // 4:,} tokens".replace(",", ".") if Rules else "❌ Sube el `.txt` de normas",
        inline=True,
    )
    embed.add_field(name="🤖 Revisiones hoy", value=f"{Used}/{S['daily_limit']}", inline=True)
    embed.add_field(name="🚨 Abuso", value=f"{S['abuse_reports']} reportes/24 h · {S['abuse_pair']} al mismo usuario", inline=True)
    embed.set_footer(text="Cada revisión cuesta muy poco (normas + mensaje); el límite diario evita sustos en la factura")
    return embed


class AutoReportPanel(ui.View):
    def __init__(self, author, back=None, channels: list | None = None):
        super().__init__(timeout=600)
        self.author, self.back = author, back
        Watched = ui.ChannelSelect(
            placeholder="👁️ Canales vigilados (marca o desmarca)", channel_types=[discord.ChannelType.text],
            min_values=0, max_values=MAX_CHANNELS, row=0,
            default_values=[discord.SelectDefaultValue(id=C, type=discord.SelectDefaultValueType.channel) for C in (channels or [])][:MAX_CHANNELS],
        )
        Watched.callback = self.PickWatched
        self.add_item(Watched)
        Pick = ui.ChannelSelect(placeholder="📥 Canal del staff (fichas)", channel_types=[discord.ChannelType.text], row=1)
        Pick.callback = self.Saver("staff_channel")
        self.add_item(Pick)
        Role = ui.RoleSelect(placeholder="🔔 Rol a avisar con cada ficha (opcional)", min_values=0, max_values=1, row=2)
        Role.callback = self.PickRole
        self.add_item(Role)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Este panel no es tuyo.", ephemeral=True)
            return False
        return True

    async def Refresh(self, interaction: discord.Interaction, note: str | None = None):
        Edit = interaction.edit_original_response if interaction.response.is_done() else interaction.response.edit_message
        _, S = await Config(interaction.guild.id)
        View = AutoReportPanel(self.author, self.back, S["channels"])
        View.Toggle.label = "Desactivar" if S["enabled"] else "Activar"
        await Edit(content=note, embed=await PanelEmbed(interaction.guild), view=View)

    def Saver(self, key):
        async def Save(interaction: discord.Interaction):
            await SaveSettings(interaction.guild.id, {key: int(interaction.data["values"][0])})
            await self.Refresh(interaction, "✅ Guardado.")
        return Save

    async def PickWatched(self, interaction: discord.Interaction):
        # The menu shows the current ones already ticked: what comes back is the whole new list.
        Channels = [int(V) for V in interaction.data.get("values") or []]
        await SaveSettings(interaction.guild.id, {"channels": Channels, "channel": None})
        await self.Refresh(interaction, f"✅ {len(Channels)} canal{'es' if len(Channels) != 1 else ''} vigilado{'s' if len(Channels) != 1 else ''}.")

    async def PickRole(self, interaction: discord.Interaction):
        Values = interaction.data.get("values") or []
        await SaveSettings(interaction.guild.id, {"ping_role": int(Values[0]) if Values else None})
        await self.Refresh(interaction, "✅ Guardado.")

    @ui.button(label="Activar", emoji="⏯️", style=discord.ButtonStyle.green, row=3)
    async def Toggle(self, interaction: discord.Interaction, _):
        Doc, S = await Config(interaction.guild.id)
        if not S["enabled"] and not (S["channels"] and S["staff_channel"]):
            return await self.Refresh(interaction, "❌ Elige primero los canales vigilados y el canal del staff.")
        await SaveSettings(interaction.guild.id, {"enabled": not S["enabled"]})
        Tip = "" if Doc.get("rules_text") else "\n⚠️ Aún no hay normas: las fichas llegarán sin la opinión de la IA."
        await self.Refresh(interaction, ("✅ Activado." + Tip) if not S["enabled"] else "⏸️ Desactivado.")

    @ui.button(label="Ajustes", emoji="⚙️", style=discord.ButtonStyle.blurple, row=3)
    async def Options(self, interaction: discord.Interaction, _):
        _, S = await Config(interaction.guild.id)
        await interaction.response.send_modal(OptionsModal(self, S))

    @ui.button(label="Subir normas", emoji="📤", style=discord.ButtonStyle.blurple, row=3)
    async def Upload(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(RulesModal(self))

    @ui.button(label="Descargar normas", emoji="📥", style=discord.ButtonStyle.grey, row=3)
    async def Download(self, interaction: discord.Interaction, _):
        Doc, _ = await Config(interaction.guild.id)
        if not Doc.get("rules_text"):
            return await interaction.response.send_message("Todavía no hay normas cargadas.", ephemeral=True)
        await interaction.response.send_message(
            "📥 Esto es exactamente lo que lee la IA.", ephemeral=True,
            file=discord.File(io.BytesIO(Doc["rules_text"].encode("utf-8")), filename="normas-actuales.txt"),
        )

    @ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=4)
    async def Back(self, interaction: discord.Interaction, _):
        from cogs.Modules.Guide.guide import GuidePanel, PanelEmbed as GuideEmbed

        await interaction.response.edit_message(content=None, embed=await GuideEmbed(interaction.guild), view=GuidePanel(self.author, self.back))


async def OpenPanel(interaction: discord.Interaction, author, back=None):
    _, S = await Config(interaction.guild.id)
    View = AutoReportPanel(author, back, S["channels"])
    View.Toggle.label = "Desactivar" if S["enabled"] else "Activar"
    await interaction.response.edit_message(content=None, embed=await PanelEmbed(interaction.guild), view=View)


class OptionsModal(ui.Modal, title="Ajustes del autoreporte"):
    def __init__(self, panel: AutoReportPanel, s: dict):
        super().__init__()
        self.panel = panel
        self.emoji = ui.TextInput(label="Emoji de reporte", default=s["emoji"], max_length=60)
        self.threshold = ui.TextInput(label="Reacciones necesarias (personas distintas)", default=str(s["threshold"]), max_length=2)
        self.limit = ui.TextInput(label="Revisiones con IA al día (máximo)", default=str(s["daily_limit"]), max_length=4)
        self.abuse = ui.TextInput(label="Abuso: reportes en 24 h / al mismo usuario", default=f"{s['abuse_reports']}/{s['abuse_pair']}", max_length=7)
        for F in (self.emoji, self.threshold, self.limit, self.abuse):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Threshold, Limit = int(self.threshold.value), int(self.limit.value)
            Reports, Pair = (int(X) for X in self.abuse.value.split("/"))
            if not (1 <= Threshold <= 20 and 0 <= Limit <= 2000 and 2 <= Reports <= 100 and 2 <= Pair <= 50):
                raise ValueError
            Emoji = str(discord.PartialEmoji.from_str(self.emoji.value.strip()))
        except ValueError:
            return await interaction.response.send_message("❌ Reacciones 1–20, revisiones 0–2000 y abuso como `5/3`.", ephemeral=True)
        await SaveSettings(interaction.guild.id, {"emoji": Emoji, "threshold": Threshold, "daily_limit": Limit, "abuse_reports": Reports, "abuse_pair": Pair})
        await self.panel.Refresh(interaction, "✅ Ajustes guardados.")


class RulesModal(ui.Modal, title="Normas para el autoreporte"):
    def __init__(self, panel: AutoReportPanel):
        super().__init__()
        self.panel = panel
        self.file = ui.FileUpload(min_values=1, max_values=1)
        self.add_item(ui.Label(text="Archivo de normas", description="Word (.docx), .txt o .md. Reemplaza las anteriores.", component=self.file))

    async def on_submit(self, interaction: discord.Interaction):
        File = (self.file.values or [None])[0]
        if not File or not File.filename.lower().endswith(ALLOWED + (".doc",)):
            return await interaction.response.send_message("❌ Sube las normas como Word (.docx), .txt o .md.", ephemeral=True)
        await interaction.response.defer()
        try:
            Text = ExtractText(File.filename, await File.read())
        except GuideError as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)
        if len(Text) > MAX_RULES_CHARS:
            return await interaction.followup.send(f"❌ Las normas son demasiado largas (máximo {MAX_RULES_CHARS:,} caracteres).".replace(",", "."), ephemeral=True)
        await Store().guides.update_one(
            {"_id": interaction.guild.id},
            {"$set": {"rules_text": Text, "rules_filename": File.filename, "rules_updated": Now()}}, upsert=True,
        )
        await self.panel.Refresh(interaction, f"✅ Normas cargadas (~{len(Text) // 4:,} tokens).".replace(",", "."))


async def setup(client: commands.Bot) -> None:
    await client.add_cog(AutoReport(client))
