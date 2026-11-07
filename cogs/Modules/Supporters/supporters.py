"""Vanity and tag supporters: detection, roles, economy benefits, announcements, /privacidad and the /config panel."""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.economy.constants import CREATED
from core.economy.rewards import FormatAmount
from core.mail.config import CanConfigure, Mail
from core.supporters import DEFAULTS, VanityPattern, HasTag, HasVanity, SetActive, Slug, Supporters

logger = logging.getLogger(__name__)
SCAN_MINUTES = 20
PRESENCE_BATCH = 100  # Discord's limit of members per presence request
PANEL_TIMEOUT = 600
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
_store: Supporters | None = None


def Store() -> Supporters:
    global _store
    if _store is None:
        from core.db import db

        _store = Supporters(db)
    return _store


def What(vanity: bool, tag: bool) -> str:
    return "nuestra vanity y nuestro tag" if vanity and tag else "nuestra vanity" if vanity else "nuestro tag"


class SupporterCog(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.known: dict[tuple[int, int], tuple[bool, bool]] = {}  # last seen (vanity, tag), to skip unchanged members
        self.loaded: set[int] = set()
        self.presences: set[int] = set()  # guilds whose statuses were fetched since the bot started
        self.Scan.start()

    def cog_unload(self):
        self.Scan.cancel()

    async def Load(self, guild: discord.Guild):
        """After a restart: who already had benefits, so nobody is re-announced or re-rewarded."""
        if guild.id in self.loaded:
            return
        await Store().LoadActive(guild.id)
        for Doc in await Store().state.find({"guild_id": guild.id}).to_list(length=None):
            self.known[(guild.id, Doc["user_id"])] = (bool(Doc.get("vanity")), bool(Doc.get("tag")))
        self.loaded.add(guild.id)

    async def Check(self, member: discord.Member, force: bool = False) -> bool:
        """Updates one member's roles and benefits. Returns True if they are a supporter."""
        if member.bot:
            return False
        Guild = member.guild
        await self.Load(Guild)
        Config = await Store().Get(Guild.id)
        Key = (Guild.id, member.id)
        if not Config["enabled"]:
            Vanity = Tag = False
        else:
            Vanity, Tag = HasVanity(member, Config["vanity"]), HasTag(member, Guild.id)
            if not Vanity and str(getattr(member, "status", "online")) == "offline":
                # Offline people send no status: keep what we last saw instead of taking the role away.
                Vanity = self.known.get(Key, (False, False))[0]
            if (Vanity or Tag) and (await Store().State(Guild.id, member.id)).get("opted_out"):
                Vanity = Tag = False
        if not force and self.known.get(Key, (False, False)) == (Vanity, Tag):
            return Vanity or Tag
        self.known[Key] = (Vanity, Tag)
        Before, After = await Store().Record(Guild.id, member.id, Vanity, Tag)
        SetActive(Guild.id, member.id, Config if After["supporter"] else None)
        await self.SyncRoles(member, Config, Vanity, Tag)
        if After["supporter"] and not Before.get("supporter"):
            await self.Welcome(member, Config, Vanity, Tag)
        return After["supporter"]

    async def SyncRoles(self, member: discord.Member, config: dict, vanity: bool, tag: bool):
        Want = {R for R, On in ((config["vanity_role"], vanity), (config["tag_role"], tag)) if R and On}
        for RoleId in {R for R in (config["vanity_role"], config["tag_role"]) if R}:
            Role = member.guild.get_role(RoleId)
            if not Role:
                continue
            try:
                if RoleId in Want and Role not in member.roles:
                    await member.add_roles(Role, reason="Lleva la vanity o el tag del servidor")
                elif RoleId not in Want and Role in member.roles:
                    await member.remove_roles(Role, reason="Ya no lleva la vanity o el tag del servidor")
            except discord.HTTPException as e:
                logger.warning(f"[Supporters] Couldn't update {Role.id} for {member.id}: {e}")

    async def Welcome(self, member: discord.Member, config: dict, vanity: bool, tag: bool):
        Guild = member.guild
        if config["reward"] > 0 and await Store().ClaimReward(Guild.id, member.id):
            from core.economy.service import Economy

            try:
                await Economy().Add(Guild.id, member.id, int(config["reward"]), "Gracias por apoyar (vanity o tag)", kind=CREATED, ref="supporter")
            except Exception as e:
                logger.warning(f"[Supporters] Reward failed for {member.id}: {e}")
        Channel = Guild.get_channel(config["announce_channel"] or 0)
        if Channel and await Store().ClaimAnnouncement(Guild.id, member.id):
            Text = config["message"].replace("{user}", member.mention).replace("{cosa}", What(vanity, tag)).replace("{server}", Guild.name)
            try:
                await Channel.send(Text, allowed_mentions=discord.AllowedMentions(users=[member]))
            except discord.HTTPException as e:
                logger.warning(f"[Supporters] Couldn't announce in {Channel.id}: {e}")

    # ---- events ----

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if before.activities != after.activities:
            await self.Safe(after)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if getattr(before, "primary_guild", None) != getattr(after, "primary_guild", None):
            await self.Safe(after)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if getattr(before, "primary_guild", None) == getattr(after, "primary_guild", None):
            return
        for Guild in after.mutual_guilds:
            Member = Guild.get_member(after.id)
            if Member:
                await self.Safe(Member)

    async def Safe(self, member: discord.Member):
        try:
            await self.Check(member)
        except Exception as e:
            logger.warning(f"[Supporters] Check failed for {member.id}: {e}")

    async def LoadPresences(self, guild: discord.Guild):
        """Fetches everyone's status once after a restart. A plain member fetch comes without statuses,
        and Discord's status updates are ignored for members the bot hasn't loaded yet."""
        if guild.id in self.presences:
            return
        if not guild.chunked:
            await guild.chunk()
        Ids = [M.id for M in guild.members if not M.bot]
        for Start in range(0, len(Ids), PRESENCE_BATCH):
            try:
                await guild.query_members(user_ids=Ids[Start:Start + PRESENCE_BATCH], presences=True, cache=True)
            except Exception as e:
                logger.warning(f"[Supporters] Couldn't fetch statuses in {guild.id}: {e}")
                return
        self.presences.add(guild.id)
        logger.info(f"[Supporters] Loaded statuses for {len(Ids)} members in {guild.id}")

    async def ScanGuild(self, guild: discord.Guild, force: bool = False) -> int:
        await self.LoadPresences(guild)
        Count = 0
        for Member in guild.members:
            if await self.Check(Member, force):
                Count += 1
        return Count

    @tasks.loop(minutes=SCAN_MINUTES)
    async def Scan(self):
        """Catches changes the events missed (and everyone after a restart)."""
        for Guild in self.client.guilds:
            try:
                await self.ScanGuild(Guild)
            except Exception as e:
                logger.error(f"[Supporters] Scan failed in {Guild.id}: {e}")

    @Scan.before_loop
    async def BeforeScan(self):
        await self.client.wait_until_ready()

    # ---- /privacidad ----

    @app_commands.command(name="privacidad", description="Tus datos y si participas en las recompensas por vanity o tag")
    @app_commands.guild_only()
    async def privacidad(self, interaction: discord.Interaction):
        State = await Store().State(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=PrivacyEmbed(State), view=PrivacyView(self, interaction.user, State), ephemeral=True)


def PrivacyEmbed(state: dict) -> discord.Embed:
    Out = state.get("opted_out", False)
    embed = discord.Embed(title="🔒 Tu privacidad", color=LOJI_RED)
    embed.description = (
        "**Recompensas por vanity o tag:** " + ("🚫 no participas" if Out else "✅ participas") + "\n"
        "-# Solo miramos si tu estado contiene la vanity del servidor o si llevas su tag. Nunca guardamos el texto de tu estado: "
        "solo si cumples o no, y desde cuándo.\n\n"
        "**¿Quieres que borremos tus datos?** Abre un ticket en el servidor y el staff lo hará."
    )
    return embed


class PrivacyView(discord.ui.View):
    def __init__(self, cog: SupporterCog, author, state: dict):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.cog, self.author = cog, author
        self.Toggle.label = "Volver a participar" if state.get("opted_out") else "No participar"

    @discord.ui.button(label="No participar", emoji="🔒", style=discord.ButtonStyle.grey)
    async def Toggle(self, interaction: discord.Interaction, _):
        State = await Store().State(interaction.guild.id, interaction.user.id)
        Out = not State.get("opted_out", False)
        await Store().SetOptOut(interaction.guild.id, interaction.user.id, Out)
        await self.cog.Check(interaction.user, force=True)  # removes (or gives back) roles and benefits now
        State = await Store().State(interaction.guild.id, interaction.user.id)
        await interaction.response.edit_message(embed=PrivacyEmbed(State), view=PrivacyView(self.cog, self.author, State))


# ---------------- /config panel ----------------


def Mention(guild, kind: str, value) -> str:
    Thing = guild.get_role(value or 0) if kind == "role" else guild.get_channel(value or 0)
    return Thing.mention if Thing else "*sin configurar*"


def PanelEmbed(guild: discord.Guild, config: dict, eco: dict | None = None) -> discord.Embed:
    embed = discord.Embed(title="🏷️ Vanity y tag · Configuración", color=LOJI_RED)
    embed.description = (
        ("✅ **Activado**" if config["enabled"] else "⏸️ **Desactivado**")
        + "\nQuien lleve **la vanity en su estado** o **el tag del servidor** recibe los beneficios. "
        "Tener las dos cosas no los duplica."
    )
    embed.add_field(name="🔗 Vanity", value=f"`{config['vanity']}`\n-# También detecta `.gg/{Slug(config['vanity'])}` y `/{Slug(config['vanity'])}`", inline=False)
    embed.add_field(name="🎭 Roles", value=f"> Por la vanity: {Mention(guild, 'role', config['vanity_role'])}\n> Por el tag: {Mention(guild, 'role', config['tag_role'])}", inline=False)
    Reward = FormatAmount(int(config["reward"]), eco) if eco else f"{int(config['reward'])}"
    embed.add_field(
        name="🪙 Beneficios en la economía",
        value=f"> Ganancias **x{config['multiplier']:g}** (se suma al de booster)\n> Gacha **+{config['gacha_luck']:.0%}** de suerte\n> Premio de bienvenida (una vez): {Reward}",
        inline=False,
    )
    embed.add_field(name="📣 Anuncio", value=f"{Mention(guild, 'channel', config['announce_channel'])}\n> {config['message']}"[:1024], inline=False)
    embed.set_footer(text="Los roles se quitan solos cuando alguien se quita la vanity o el tag · /privacidad para no participar")
    return embed


async def ShowPanel(interaction: discord.Interaction, author, note: str | None = None):
    from core.economy.config import EcoConfig

    Config = await Store().Get(interaction.guild.id)
    await interaction.response.edit_message(
        content=note, embed=PanelEmbed(interaction.guild, Config, await EcoConfig().Get(interaction.guild.id)), view=VanityPanel(author, Config)
    )


class Owned(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id


SETTINGS = {
    "vanity": ("Texto de la vanity", "🔗"),
    "vanity_role": ("Rol por la vanity", "🎭"),
    "tag_role": ("Rol por el tag", "🏷️"),
    "benefits": ("Beneficios de economía", "🪙"),
    "announce_channel": ("Canal de anuncios", "📣"),
    "message": ("Mensaje del anuncio", "💬"),
}


class VanityPanel(Owned):
    def __init__(self, author, config: dict):
        super().__init__(author)
        Pick = discord.ui.Select(placeholder="¿Qué quieres configurar?", options=[discord.SelectOption(label=L, value=K, emoji=E) for K, (L, E) in SETTINGS.items()], row=0)
        Pick.callback = self.Pick
        self.add_item(Pick)
        self.Toggle.label = "Desactivar" if config["enabled"] else "Activar"

    async def Pick(self, interaction: discord.Interaction):
        Key = interaction.data["values"][0]
        Config = await Store().Get(interaction.guild.id)
        if Key == "vanity":
            return await interaction.response.send_modal(TextModal(self.author, "vanity", "Texto de la vanity", Config["vanity"], 100))
        if Key == "message":
            return await interaction.response.send_modal(TextModal(self.author, "message", "Mensaje ({user}, {cosa}, {server})", Config["message"], 500, long=True))
        if Key == "benefits":
            return await interaction.response.send_modal(BenefitsModal(self.author, Config))
        await interaction.response.edit_message(content=f"**{SETTINGS[Key][0]}**", embed=None, view=PickTarget(self.author, Key))

    @discord.ui.button(label="Desactivar", emoji="⏯️", style=discord.ButtonStyle.grey, row=1)
    async def Toggle(self, interaction: discord.Interaction, _):
        Config = await Store().Get(interaction.guild.id)
        await Store().Set(interaction.guild.id, {"enabled": not Config["enabled"]})
        await ShowPanel(interaction, self.author, "✅ Activado." if not Config["enabled"] else "⏸️ Desactivado: en la próxima revisión se quitan roles y beneficios.")

    @discord.ui.button(label="Probar a alguien", emoji="🔍", style=discord.ButtonStyle.grey, row=1)
    async def Test(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="🔍 **¿A quién reviso?** Te digo qué ve el bot y qué falla.", embed=None, view=TestPick(self.author))

    @discord.ui.button(label="Revisar ahora", emoji="🔄", style=discord.ButtonStyle.blurple, row=1)
    async def Rescan(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Cog = interaction.client.get_cog("SupporterCog")
        Count = await Cog.ScanGuild(interaction.guild, force=True) if Cog else 0
        from core.economy.config import EcoConfig

        Config = await Store().Get(interaction.guild.id)
        await interaction.edit_original_response(
            content=f"🔄 Revisado: **{Count}** miembro{'s' if Count != 1 else ''} lleva{'n' if Count != 1 else ''} la vanity o el tag.",
            embed=PanelEmbed(interaction.guild, Config, await EcoConfig().Get(interaction.guild.id)), view=VanityPanel(self.author, Config),
        )


class TestPick(Owned):
    def __init__(self, author):
        super().__init__(author)
        Who = discord.ui.UserSelect(placeholder="Elige a un miembro", row=0)
        Who.callback = self.Pick
        self.add_item(Who)

    async def Pick(self, interaction: discord.Interaction):
        await interaction.response.defer()
        Member = interaction.guild.get_member(int(interaction.data["values"][0]))
        Cog = interaction.client.get_cog("SupporterCog")
        if not Member or not Cog:
            return await interaction.edit_original_response(content="❌ No encuentro a ese miembro.", view=TestPick(self.author))
        await Cog.LoadPresences(interaction.guild)
        Member = interaction.guild.get_member(Member.id) or Member
        await interaction.edit_original_response(content=None, embed=await Diagnose(Cog, Member), view=TestPick(self.author))

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back(self, interaction: discord.Interaction, _):
        await ShowPanel(interaction, self.author)


async def Diagnose(cog: SupporterCog, member: discord.Member) -> discord.Embed:
    """What the bot sees for one member, applies it, and lists anything that blocks roles or the announcement."""
    Guild, Config = member.guild, await Store().Get(member.guild.id)
    Customs = [A for A in member.activities if str(getattr(A.type, "name", A.type)) == "custom"]
    Status = " · ".join(f"`{(A.state or A.name or '')[:80]}`" for A in Customs) or "*sin estado personalizado (o desconectado/invisible)*"
    Primary = getattr(member, "primary_guild", None)
    TagText = f"`{Primary.tag}` de {'este servidor' if Primary.id == Guild.id else 'otro servidor'}" + ("" if Primary.identity_enabled else " (oculto)") if Primary and Primary.id else "*no lleva ningún tag*"
    Vanity, Tag = HasVanity(member, Config["vanity"]), HasTag(member, Guild.id)
    State = await Store().State(Guild.id, member.id)
    Problems = []
    if not Config["enabled"]:
        Problems.append("El sistema está **desactivado**.")
    if State.get("opted_out"):
        Problems.append("Esta persona eligió **no participar** (`/privacidad`).")
    Me = Guild.me
    for Key, Label in (("vanity_role", "Rol por la vanity"), ("tag_role", "Rol por el tag")):
        Role = Guild.get_role(Config[Key] or 0)
        if Config[Key] and not Role:
            Problems.append(f"{Label}: el rol ya no existe.")
        elif Role and not Me.guild_permissions.manage_roles:
            Problems.append("El bot no tiene permiso de **Gestionar roles**.")
        elif Role and Role >= Me.top_role:
            Problems.append(f"{Label}: {Role.mention} está **por encima del rol del bot**. Sube el rol del bot.")
    if not Config["vanity_role"] and not Config["tag_role"]:
        Problems.append("No hay **ningún rol** configurado (no se dan roles).")
    Channel = Guild.get_channel(Config["announce_channel"] or 0)
    if not Channel:
        Problems.append("No hay **canal de anuncios** (no se anuncia).")
    elif not Channel.permissions_for(Me).send_messages:
        Problems.append(f"El bot no puede escribir en {Channel.mention}.")
    Supporter = await cog.Check(member, force=True)
    embed = discord.Embed(title=f"🔍 {member.display_name}", color=discord.Color.green() if Supporter else discord.Color.dark_grey())
    embed.add_field(name="Estado que ve el bot", value=Status, inline=False)
    embed.add_field(name="Tag", value=TagText, inline=False)
    embed.add_field(name="Resultado", value=(
        f"Vanity: {'✅' if Vanity else '❌'} · Tag: {'✅' if Tag else '❌'} → " + ("✅ **tiene los beneficios**" if Supporter else "❌ **no cumple**")
        + f"\n-# Busco: `{Config['vanity']}` (también `.gg/{Slug(Config['vanity'])}` y `/{Slug(Config['vanity'])}`)"
    ), inline=False)
    embed.add_field(name="⚠️ Problemas" if Problems else "✅ Todo en orden", value="\n".join(f"• {P}" for P in Problems)[:1024] or "Roles y anuncio configurados correctamente.", inline=False)
    embed.set_footer(text="El premio y el anuncio solo salen la primera vez que alguien empieza a cumplir")
    return embed


class PickTarget(Owned):
    def __init__(self, author, key: str):
        super().__init__(author)
        self.key = key
        if key.endswith("role"):
            Picker = discord.ui.RoleSelect(placeholder="Elige el rol", row=0)
        else:
            Picker = discord.ui.ChannelSelect(placeholder="Elige el canal", channel_types=[discord.ChannelType.text], row=0)
        Picker.callback = self.Pick
        self.add_item(Picker)

    async def Pick(self, interaction: discord.Interaction):
        await Store().Set(interaction.guild.id, {self.key: int(interaction.data["values"][0])})
        await ShowPanel(interaction, self.author, "✅ Guardado. Pulsa **🔄 Revisar ahora** para aplicarlo a todos.")

    @discord.ui.button(label="Quitar", emoji="🧹", style=discord.ButtonStyle.grey, row=1)
    async def Clear(self, interaction: discord.Interaction, _):
        await Store().Set(interaction.guild.id, {self.key: None})
        await ShowPanel(interaction, self.author, "🧹 Quitado.")

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back(self, interaction: discord.Interaction, _):
        await ShowPanel(interaction, self.author)


class TextModal(discord.ui.Modal):
    def __init__(self, author, key: str, label: str, current: str, limit: int, long: bool = False):
        super().__init__(title=SETTINGS[key][0])
        self.author, self.key = author, key
        self.value = discord.ui.TextInput(label=label[:45], default=current, max_length=limit, style=discord.TextStyle.paragraph if long else discord.TextStyle.short)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        Value = self.value.value.strip()
        if self.key == "vanity" and not VanityPattern(Value):
            return await interaction.response.send_message("❌ Pon la vanity, por ejemplo `discord.gg/animetv`.", ephemeral=True)
        await Store().Set(interaction.guild.id, {self.key: Value or DEFAULTS[self.key]})
        await ShowPanel(interaction, self.author, "✅ Guardado.")


class BenefitsModal(discord.ui.Modal, title="Beneficios de economía"):
    def __init__(self, author, config: dict):
        super().__init__()
        self.author = author
        self.multiplier = discord.ui.TextInput(label="Multiplicador de ganancias (1 = nada)", default=f"{config['multiplier']:g}", max_length=5)
        self.luck = discord.ui.TextInput(label="Suerte extra en el gacha (%)", default=f"{config['gacha_luck'] * 100:g}", max_length=5)
        self.reward = discord.ui.TextInput(label="Premio de bienvenida (una vez, 0 = nada)", default=str(int(config["reward"])), max_length=9)
        for Item in (self.multiplier, self.luck, self.reward):
            self.add_item(Item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Multiplier = float(self.multiplier.value.replace(",", "."))
            Luck = float(self.luck.value.replace(",", ".").rstrip("%")) / 100
            Reward = int(self.reward.value.replace(".", "").replace(",", ""))
            if not (1 <= Multiplier <= 3 and 0 <= Luck <= 1 and 0 <= Reward <= 1_000_000):
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Multiplicador entre 1 y 3, suerte entre 0 y 100 %, premio entre 0 y 1.000.000.", ephemeral=True)
        await Store().Set(interaction.guild.id, {"multiplier": Multiplier, "gacha_luck": Luck, "reward": Reward})
        await ShowPanel(interaction, self.author, "✅ Beneficios guardados. Pulsa **🔄 Revisar ahora** para aplicarlos a quienes ya cumplen.")


async def OpenPanel(interaction: discord.Interaction):
    """Shown from /config (only the Tenno or server admins)."""
    from core.economy.config import EcoConfig

    if not CanConfigure(interaction.user, await Mail().Get(interaction.guild.id)):
        return await interaction.followup.send("❌ Solo el Tenno (o un administrador) configura la vanity y el tag.", ephemeral=True)
    Config = await Store().Get(interaction.guild.id)
    await interaction.edit_original_response(embed=PanelEmbed(interaction.guild, Config, await EcoConfig().Get(interaction.guild.id)), view=VanityPanel(interaction.user, Config))


async def setup(client: commands.Bot) -> None:
    await client.add_cog(SupporterCog(client))
