"""/anime and /horario anime: the weekly anime streams in the auditorium."""

import io
import logging
from datetime import timedelta

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from cogs.Modules.Community.panel import Field, Owned, Show
from core.anime import DAYS, SHOWS, EpisodeText, Finished, NextAt, Now, ParseTime, Stage
from core.community import Store as Community

logger = logging.getLogger(__name__)
MAX_SHOWS = 30
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
PLUM = discord.Color.from_rgb(187, 168, 150)


def Db():
    from core.db import db

    return db


async def Settings(guild_id: int) -> dict:
    return (await Community().Get(guild_id))["anime"]


async def Offset(guild_id: int) -> int:
    try:
        from core.economy.config import EcoConfig

        return int((await EcoConfig().Get(guild_id))["activity"].get("utc_offset", 0))
    except Exception:
        return 0


def CanRun(member: discord.Member, settings: dict) -> bool:
    from core.ticket_access import IsAdmin

    return IsAdmin(member) or any(R.id == settings.get("team_role") for R in member.roles)


async def Shows(guild_id: int) -> list[dict]:
    Docs = await Db()[SHOWS].find({"guild_id": guild_id}).to_list(length=None)
    return sorted(Docs, key=lambda S: (S["day"], S["hour"], S["minute"]))


async def ScheduleImage(guild: discord.Guild) -> discord.File:
    import asyncio

    from core.anime_art import Schedule

    All = await Shows(guild.id)
    Names = {}
    for S in All:
        M = guild.get_member(S.get("streamer") or 0)
        if M:
            Names[M.id] = M.display_name
    Png = await asyncio.to_thread(Schedule, All, guild.name, Names)
    return discord.File(io.BytesIO(Png), filename="horario.png")


def ScheduleView(guild: discord.Guild) -> ui.LayoutView:
    View = ui.LayoutView(timeout=None)
    Box = ui.Container(accent_colour=PLUM)
    Box.add_item(ui.TextDisplay(f"## 📺 Horario de anime\nTransmisiones en el auditorio de **{guild.name}** ✦"))
    Box.add_item(ui.MediaGallery(discord.MediaGalleryItem("attachment://horario.png")))
    Box.add_item(ui.TextDisplay("-# ✦ Se actualiza solo · avisamos unos minutos antes de cada transmisión ✦"))
    View.add_item(Box)
    return View


async def RefreshSchedule(guild: discord.Guild):
    """Keeps the posted schedule up to date after any change."""
    Ref = (await Settings(guild.id)).get("schedule_message")
    Channel = guild.get_channel(Ref["channel"]) if Ref else None
    if not Channel:
        return
    try:
        await Channel.get_partial_message(Ref["id"]).edit(view=ScheduleView(guild), attachments=[await ScheduleImage(guild)])
    except discord.HTTPException as e:
        logger.warning(f"[Anime] Couldn't refresh the schedule: {e}")


async def ShowChoices(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=f"{S['title']} · {DAYS[S['day']]} {S['hour']:02d}:{S['minute']:02d}"[:100], value=S["_id"])
        for S in await Shows(interaction.guild.id) if current.lower() in S["title"].lower()
    ][:25]


DAY_CHOICES = [app_commands.Choice(name=D, value=I) for I, D in enumerate(DAYS)]


class AiredButton(ui.DynamicItem[ui.Button], template=r"an:(?P<id>[A-Z0-9]{8}):(?P<key>\d{12}):(?P<n>[0-3])"):
    """After a stream: how many episodes were shown (0 = it didn't happen)."""

    def __init__(self, show_id: str, key: str, n: int):
        Label = f"{n} episodio{'s' if n != 1 else ''}" if n else "No se emitió"
        super().__init__(ui.Button(label=Label, emoji="✅" if n else "❌", style=discord.ButtonStyle.green if n else discord.ButtonStyle.grey,
                                   custom_id=f"an:{show_id}:{key}:{n}"))
        self.show_id, self.key, self.n = show_id, key, n

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["id"], match["key"], int(match["n"]))

    async def callback(self, interaction: discord.Interaction):
        Show_ = await Db()[SHOWS].find_one({"_id": self.show_id})
        if not Show_:
            return await interaction.response.send_message("❌ Ese anime ya no está en el horario.", ephemeral=True)
        S = await Settings(Show_["guild_id"])
        Guild = interaction.client.get_guild(Show_["guild_id"])
        Member = Guild.get_member(interaction.user.id) if Guild else None
        if interaction.user.id != Show_.get("streamer") and not (Member and CanRun(Member, S)):
            return await interaction.response.send_message("❌ Solo quien transmite o el equipo de anime.", ephemeral=True)
        Done = await Db()[SHOWS].find_one_and_update(
            {"_id": self.show_id, "marked": {"$ne": self.key}},
            {"$inc": {"episode": self.n}, "$push": {"marked": {"$each": [self.key], "$slice": -20}}}, return_document=True,
        )
        if not Done:
            return await interaction.response.send_message("Esta transmisión ya se marcó.", ephemeral=True)
        Text = (f"✅ Apuntado: **{self.n} episodio{'s' if self.n != 1 else ''}** de **{Done['title']}**. La próxima vez toca el **{EpisodeText(Done)}**."
                if self.n else f"❌ Apuntado: **{Done['title']}** no se emitió esta vez.")
        if Finished(Done):
            Text += "\n🎉 ¡Se terminó el anime! Quítalo del horario con `/anime quitar` cuando quieras."
        await interaction.response.edit_message(content=Text, view=None)
        if Guild:
            await RefreshSchedule(Guild)


def AiredView(show_id: str, key: str) -> ui.View:
    View = ui.View(timeout=None)
    for N in (1, 2, 3, 0):
        View.add_item(AiredButton(show_id, key, N))
    return View


class Anime(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.Tick.start()

    async def cog_load(self):
        self.client.add_dynamic_items(AiredButton)

    def cog_unload(self):
        self.Tick.cancel()

    anime = app_commands.Group(name="anime", description="Horario de transmisiones de anime", guild_only=True)
    horario = app_commands.Group(name="horario", description="Horarios", guild_only=True)

    async def Allowed(self, interaction: discord.Interaction) -> bool:
        if not CanRun(interaction.user, await Settings(interaction.guild.id)):
            await interaction.response.send_message("❌ Solo el equipo de anime (o la administración).", ephemeral=True)
            return False
        return True

    @horario.command(name="anime", description="El horario de anime de la semana, en imagen")
    async def horario_anime(self, interaction: discord.Interaction):
        if not await Shows(interaction.guild.id):
            return await interaction.response.send_message("📺 Todavía no hay animes en el horario.", ephemeral=True)
        await interaction.response.defer()
        await interaction.followup.send(file=await ScheduleImage(interaction.guild))

    @anime.command(name="añadir", description="Añadir un anime al horario semanal")
    @app_commands.describe(titulo="Nombre del anime", dia="Qué día se transmite", hora="A qué hora (21:00)", encargado="Quién lo transmite",
                           episodio="Por qué episodio vais (el próximo que toca)", total="Episodios totales (opcional)")
    @app_commands.choices(dia=DAY_CHOICES)
    async def añadir(self, interaction: discord.Interaction, titulo: app_commands.Range[str, 1, 80], dia: int, hora: str,
                     encargado: discord.Member, episodio: app_commands.Range[int, 1, 5000] = 1, total: app_commands.Range[int, 1, 5000] | None = None):
        from core.economy.shop import NewId

        if not await self.Allowed(interaction):
            return
        try:
            H, M = ParseTime(hora)
        except ValueError:
            return await interaction.response.send_message("❌ La hora va como `21:00`.", ephemeral=True)
        if await Db()[SHOWS].count_documents({"guild_id": interaction.guild.id}) >= MAX_SHOWS:
            return await interaction.response.send_message(f"❌ Máximo {MAX_SHOWS} animes en el horario.", ephemeral=True)
        Show_ = {"_id": NewId(8), "guild_id": interaction.guild.id, "title": titulo.strip(), "day": dia, "hour": H, "minute": M,
                 "streamer": encargado.id, "episode": episodio, "total": total, "done": {}, "marked": []}
        await Db()[SHOWS].insert_one(Show_)
        await interaction.response.send_message(
            f"📺 **{Show_['title']}** · {DAYS[dia]} {H:02d}:{M:02d} · {encargado.mention} · {EpisodeText(Show_)}.", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await RefreshSchedule(interaction.guild)

    @anime.command(name="editar", description="Cambiar día, hora, encargado o episodios de un anime")
    @app_commands.autocomplete(anime=ShowChoices)
    @app_commands.choices(dia=DAY_CHOICES)
    @app_commands.describe(episodio="El próximo episodio que toca", total="Episodios totales (0 = sin total)")
    async def editar(self, interaction: discord.Interaction, anime: str, titulo: str | None = None, dia: int | None = None, hora: str | None = None,
                     encargado: discord.Member | None = None, episodio: app_commands.Range[int, 1, 5000] | None = None,
                     total: app_commands.Range[int, 0, 5000] | None = None):
        if not await self.Allowed(interaction):
            return
        Changes = {}
        if titulo:
            Changes["title"] = titulo.strip()[:80]
        if dia is not None:
            Changes["day"] = dia
        if hora:
            try:
                Changes["hour"], Changes["minute"] = ParseTime(hora)
            except ValueError:
                return await interaction.response.send_message("❌ La hora va como `21:00`.", ephemeral=True)
        if encargado:
            Changes["streamer"] = encargado.id
        if episodio is not None:
            Changes["episode"] = episodio
        if total is not None:
            Changes["total"] = total or None
        if not Changes:
            return await interaction.response.send_message("Dime qué cambiar (título, día, hora, encargado, episodio o total).", ephemeral=True)
        Show_ = await Db()[SHOWS].find_one_and_update({"_id": anime, "guild_id": interaction.guild.id}, {"$set": Changes}, return_document=True)
        if not Show_:
            return await interaction.response.send_message("❌ Elige un anime de la lista.", ephemeral=True)
        await interaction.response.send_message(
            f"✏️ **{Show_['title']}** · {DAYS[Show_['day']]} {Show_['hour']:02d}:{Show_['minute']:02d} · <@{Show_['streamer']}> · {EpisodeText(Show_)}.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )
        await RefreshSchedule(interaction.guild)

    @anime.command(name="quitar", description="Quitar un anime del horario")
    @app_commands.autocomplete(anime=ShowChoices)
    async def quitar(self, interaction: discord.Interaction, anime: str):
        if not await self.Allowed(interaction):
            return
        Show_ = await Db()[SHOWS].find_one_and_delete({"_id": anime, "guild_id": interaction.guild.id})
        if not Show_:
            return await interaction.response.send_message("❌ Elige un anime de la lista.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ **{Show_['title']}** quitado del horario.", ephemeral=True)
        await RefreshSchedule(interaction.guild)

    # ---------------- reminders ----------------

    @tasks.loop(minutes=1)
    async def Tick(self):
        Now_ = Now()
        try:
            All = await Db()[SHOWS].find({}).to_list(length=None)
        except Exception as e:
            return logger.warning(f"[Anime] Check failed: {e!r}")
        Cache: dict[int, tuple[dict, int]] = {}
        for Show_ in All:
            Guild = self.client.get_guild(Show_["guild_id"])
            if not Guild:
                continue
            if Guild.id not in Cache:
                Cache[Guild.id] = (await Settings(Guild.id), await Offset(Guild.id))
            S, Off = Cache[Guild.id]
            What, Key = Stage(Show_, Now_, Off, int(S["staff_minutes"]), int(S["remind_minutes"]))
            if not What or Finished(Show_):
                continue
            Done = await Db()[SHOWS].update_one({"_id": Show_["_id"], f"done.{Key}": {"$ne": What}}, {"$addToSet": {f"done.{Key}": What}})
            if not Done.modified_count:
                continue
            try:
                await self.Act(Guild, Show_, S, What, Key, NextAt(Show_, Now_ - timedelta(minutes=2), Off))
            except Exception as e:
                logger.warning(f"[Anime] {What} for {Show_['_id']} failed: {e!r}")
            if len(Show_.get("done") or {}) > 12:  # forget old airings
                Old = sorted(Show_["done"])[:-6]
                await Db()[SHOWS].update_one({"_id": Show_["_id"]}, {"$unset": {f"done.{K}": "" for K in Old}})

    async def Act(self, guild: discord.Guild, show: dict, s: dict, what: str, key: str, start):
        Stage_ = f"<#{s['stage']}>" if s.get("stage") else "el auditorio"
        Title = f"**{show['title']}** · {EpisodeText(show)}"
        Streamer = guild.get_member(show.get("streamer") or 0)
        if what == "staff":
            Text = f"🎙️ {Streamer.mention if Streamer else ''} te toca transmitir {Title} {discord.utils.format_dt(start, 'R')} en {Stage_}."
            await self.ToStaff(guild, s, Streamer, Text)
            return
        Channel = guild.get_channel(s.get("channel") or 0)
        Role = guild.get_role(s.get("ping_role") or 0)
        if what == "viewers" and Channel:
            Embed = discord.Embed(title=f"📺 {show['title']}"[:256], color=PLUM,
                                  description=f"**{EpisodeText(show)}** empieza {discord.utils.format_dt(start, 'R')} en {Stage_}.\n-# Transmite {Streamer.mention if Streamer else 'el equipo de anime'}")
            await Channel.send(Role.mention if Role else None, embed=Embed, allowed_mentions=discord.AllowedMentions(roles=[Role] if Role else False))
        if what == "start":
            if Channel:
                await Channel.send(f"🔴 {Role.mention + ' ' if Role else ''}¡Empieza {Title} en {Stage_}!",
                                   allowed_mentions=discord.AllowedMentions(roles=[Role] if Role else False))
            # The streamer marks how many episodes were shown (and the count moves on).
            Mark = key.replace("-", "").replace("T", "").replace(":", "")
            await self.ToStaff(guild, s, Streamer, f"📋 {Streamer.mention if Streamer else ''} cuando termines, marca cuántos episodios de **{show['title']}** se emitieron:",
                               view=AiredView(show["_id"], Mark))

    async def ToStaff(self, guild: discord.Guild, s: dict, streamer, text: str, view: ui.View | None = None):
        Channel = guild.get_channel(s.get("staff_channel") or 0)
        Kwargs = {"view": view} if view else {}
        try:
            if Channel:
                await Channel.send(text.replace("  ", " "), allowed_mentions=discord.AllowedMentions(users=True), **Kwargs)
            elif streamer:
                await streamer.send(text.replace("  ", " "), **Kwargs)
        except discord.HTTPException:
            pass

    @Tick.before_loop
    async def BeforeTick(self):
        await self.client.wait_until_ready()


# ---------------- /config → Crecimiento y Entretenimiento → Anime ----------------


async def AnimeEmbed(guild: discord.Guild) -> discord.Embed:
    S = await Settings(guild.id)
    All = await Shows(guild.id)

    def Where(value, kind="channel"):
        return (f"<@&{value}>" if kind == "role" else f"<#{value}>") if value else "*sin elegir*"

    embed = discord.Embed(title="📺 Anime", color=LOJI_RED)
    embed.description = (
        "Horario semanal de transmisiones. El equipo gestiona con `/anime añadir · editar · quitar`; cualquiera ve "
        "`/horario anime`. LOJI avisa al encargado, luego al público, anuncia el inicio y el encargado marca cuántos episodios se emitieron."
    )
    embed.add_field(name="👥 Equipo de anime", value=Where(S["team_role"], "role"), inline=True)
    embed.add_field(name="🎭 Auditorio", value=Where(S["stage"]), inline=True)
    embed.add_field(name="📣 Avisos al público", value=Where(S["channel"]) + (f"\n🔔 {Where(S['ping_role'], 'role')}" if S["ping_role"] else ""), inline=True)
    embed.add_field(name="🎙️ Avisos al encargado", value=(Where(S["staff_channel"]) if S["staff_channel"] else "por MD") + f" · {S['staff_minutes']} min antes", inline=True)
    embed.add_field(name="⏰ Aviso al público", value=f"{S['remind_minutes']} min antes", inline=True)
    Posted = S.get("schedule_message")
    embed.add_field(name="🗓️ Horario publicado", value=f"<#{Posted['channel']}>" if Posted else "*no*", inline=True)
    Lines = [f"`{DAYS[X['day']][:3]} {X['hour']:02d}:{X['minute']:02d}` **{X['title']}** · <@{X['streamer']}> · {EpisodeText(X)}" for X in All]
    embed.add_field(name=f"Animes ({len(All)})", value="\n".join(Lines)[:1024] or "Ninguno: usa `/anime añadir`.", inline=False)
    return embed


class AnimePanel(Owned):
    def __init__(self, author):
        super().__init__(author)
        Items = (
            (ui.RoleSelect, "team_role", "👥 Rol del equipo de anime", 0, 1, {}),
            (ui.ChannelSelect, "stage", "🎭 Auditorio (escenario o voz)", 1, 1, {"channel_types": [discord.ChannelType.stage_voice, discord.ChannelType.voice]}),
            (ui.ChannelSelect, "channel", "📣 Canal de avisos al público", 2, 1, {"channel_types": [discord.ChannelType.text, discord.ChannelType.news]}),
            (ui.RoleSelect, "ping_role", "🔔 Rol a avisar (opcional, vacío = nadie)", 3, 0, {}),
        )
        for Kind, Key, Placeholder, Row, Min, Extra in Items:
            Pick = Kind(placeholder=Placeholder, min_values=Min, max_values=1, row=Row, **Extra)
            Pick.callback = self.Saver(Key)
            self.add_item(Pick)

    @classmethod
    async def Open(cls, interaction, author, note=None):
        await Show(interaction, await AnimeEmbed(interaction.guild), cls(author), note)

    def Saver(self, key):
        async def Save(interaction: discord.Interaction):
            Values = interaction.data.get("values") or []
            await Community().Set(interaction.guild.id, "anime", {key: int(Values[0]) if Values else None})
            await AnimePanel.Open(interaction, self.author, "✅ Guardado.")
        return Save

    @ui.button(label="Avisos", emoji="⏰", style=discord.ButtonStyle.blurple, row=4)
    async def Reminders(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(RemindersModal(self.author, await Settings(interaction.guild.id)))

    @ui.button(label="Publicar horario", emoji="📤", style=discord.ButtonStyle.green, row=4)
    async def Publish(self, interaction: discord.Interaction, _):
        S = await Settings(interaction.guild.id)
        Channel = interaction.guild.get_channel(S.get("channel") or 0)
        if not Channel:
            return await AnimePanel.Open(interaction, self.author, "❌ Elige primero el canal de avisos (ahí se publica el horario).")
        await interaction.response.defer()
        Old = S.get("schedule_message")
        if Old:
            try:
                await interaction.guild.get_channel(Old["channel"]).get_partial_message(Old["id"]).delete()
            except (discord.HTTPException, AttributeError):
                pass
        try:
            Sent = await Channel.send(view=ScheduleView(interaction.guild), file=await ScheduleImage(interaction.guild))
        except discord.HTTPException as e:
            return await AnimePanel.Open(interaction, self.author, f"❌ No pude publicar: {e.text or e}")
        await Community().Set(interaction.guild.id, "anime", {"schedule_message": {"channel": Channel.id, "id": Sent.id}})
        await AnimePanel.Open(interaction, self.author, f"✅ Horario publicado en {Channel.mention}: se actualizará solo con cada cambio.")

    @ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=4)
    async def Back(self, interaction: discord.Interaction, _):
        from cogs.Modules.Growth.panel import GrowthPanel

        await GrowthPanel.Open(interaction, self.author)


class RemindersModal(ui.Modal, title="Avisos del anime"):
    def __init__(self, author, s: dict):
        super().__init__()
        self.author = author
        self.viewers = Field("Avisar al público: minutos antes", s["remind_minutes"], 4, long=False, required=True)
        self.staff = Field("Avisar al encargado: minutos antes", s["staff_minutes"], 4, long=False, required=True)
        Default = [discord.SelectDefaultValue(id=s["staff_channel"], type=discord.SelectDefaultValueType.channel)] if s.get("staff_channel") else []
        self.channel = ui.ChannelSelect(channel_types=[discord.ChannelType.text], min_values=0, max_values=1, required=False, default_values=Default)
        self.add_item(self.viewers)
        self.add_item(self.staff)
        self.add_item(ui.Label(text="Canal del staff para los avisos", description="Vacío = se le avisa por MD.", component=self.channel))

    async def on_submit(self, interaction: discord.Interaction):
        V, St = self.viewers.value.strip(), self.staff.value.strip()
        if not (V.isdigit() and St.isdigit() and 1 <= int(V) <= 720 and 1 <= int(St) <= 1440):
            return await interaction.response.send_message("❌ Minutos entre 1 y 720 (público) y entre 1 y 1440 (encargado).", ephemeral=True)
        Channel = self.channel.values[0].id if self.channel.values else None
        await Community().Set(interaction.guild.id, "anime", {"remind_minutes": int(V), "staff_minutes": int(St), "staff_channel": Channel})
        await AnimePanel.Open(interaction, self.author, "✅ Avisos guardados.")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Anime(client))
