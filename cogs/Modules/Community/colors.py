"""
Booster gradient colors: one Components V2 message with the server's gradient roles.

The roles are made by hand in Discord; LOJI reads each role's gradient and draws the swatch image (sent with
the message, so it never expires) and one gradient emoji per button (uploaded as the bot's own emojis).
Only boosters, one gradient at a time (independent of the icons); clicking yours takes it off, ✖ too.
When the boost ends the icons module takes it away along with the icon.
"""

import asyncio
import io
import logging

import discord
from discord import ui
from discord.ext import commands

from cogs.Modules.Community.icons import BoosterMention, IsBooster
from cogs.Modules.Community.panel import Back, Field, Owned, Show
from core.community import COLOR_EMOJIS, MAX_COLORS, ColorKey, Color, Fill, IconSwap, Store, ValidColor
from core.staff.medals import CleanName

logger = logging.getLogger(__name__)
SWATCH = "muestrario.png"
NO_COLOR = 0x99AAB5  # a role without color shows Discord's default grey


def Db():
    from core.db import db

    return db


def Colors(role) -> tuple[int, int]:
    """(first, second) color of a role; the same twice if it isn't a gradient."""
    First = role.colour.value or NO_COLOR
    Second = getattr(role, "secondary_colour", None)
    return First, (Second.value if Second is not None and Second.value else First)


def Ordered(guild: discord.Guild, settings: dict) -> list:
    return [R for R in (guild.get_role(I) for I in settings.get("roles") or []) if R]


# ---------------- emojis ----------------


class GradientEmojis:
    """role id -> a bot emoji drawn from its gradient (redrawn only when the colors change)."""

    def __init__(self):
        self.lock = asyncio.Lock()

    async def For(self, client, roles: list) -> dict[int, str]:
        from core.gradient_art import Emoji

        Out = {}
        async with self.lock:
            Known = {D["_id"]: D for D in await Db()[COLOR_EMOJIS].find({"_id": {"$in": [R.id for R in roles]}}).to_list(length=None)}
            Mine = None
            for R in roles:
                First, Second = Colors(R)
                Key = ColorKey(First, Second)
                Doc = Known.get(R.id)
                if Doc and Doc.get("key") == Key:
                    Out[R.id] = Doc["text"]
                    continue
                if Mine is None:
                    try:
                        Mine = {E.name: E for E in await client.fetch_application_emojis()}
                    except discord.HTTPException as e:
                        logger.warning(f"[Colors] Can't list the bot's emojis: {e}")
                        Mine = {}
                Name = f"lojic_{R.id}"
                try:
                    if Name in Mine:  # the old drawing goes
                        await Mine.pop(Name).delete()
                    Image = await asyncio.to_thread(Emoji, f"#{First:06x}", f"#{Second:06x}")
                    New = await client.create_application_emoji(name=Name, image=Image)
                except (discord.HTTPException, ValueError) as e:
                    logger.warning(f"[Colors] Couldn't make the emoji for {R.id}: {e}")
                    Out[R.id] = "🎨"
                    continue
                Out[R.id] = str(New)
                await Db()[COLOR_EMOJIS].update_one({"_id": R.id}, {"$set": {"key": Key, "text": str(New)}}, upsert=True)
        return Out


_emojis = GradientEmojis()


# ---------------- the message ----------------


def PanelView(guild: discord.Guild, settings: dict, roles: list, emojis: dict[int, str]) -> ui.LayoutView:
    Values = {"server": guild.name, "total": str(len(roles)), "booster": BoosterMention(guild)}
    View = ui.LayoutView(timeout=None)
    Box = ui.Container(accent_colour=Color(settings["color"], 0xBBA896))
    if settings["banner"]:
        Box.add_item(ui.MediaGallery(discord.MediaGalleryItem(settings["banner"])))
    Head = "\n".join(T for T in (Fill(settings["title"], Values), Fill(settings["text"], Values)) if T.strip())
    if Head:
        Box.add_item(ui.TextDisplay(Head))
    Box.add_item(ui.Separator())
    if settings["heading"]:
        Box.add_item(ui.TextDisplay(Fill(settings["heading"], Values)))
    if roles:
        Box.add_item(ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{SWATCH}")))
        Box.add_item(ui.Separator(spacing=discord.SeparatorSpacing.large))
        Buttons = [ColorButton(str(R.id), I, emojis.get(R.id)) for I, R in enumerate(roles, 1)] + [ColorButton("off")]
        for Start in range(0, len(Buttons), 5):
            Box.add_item(ui.ActionRow(*Buttons[Start:Start + 5]))
    else:
        Box.add_item(ui.TextDisplay("*Todavía no hay colores: elígelos en `/config` → Comunidad → Colores boosters.*"))
    if settings["footer"]:
        Box.add_item(ui.Separator(visible=False))
        Box.add_item(ui.TextDisplay(Fill(settings["footer"], Values)))
    View.add_item(Box)
    return View


async def Build(client, guild: discord.Guild) -> tuple[ui.LayoutView, discord.File | None]:
    from core.gradient_art import Swatch

    Settings = (await Store().Get(guild.id))["colors"]
    Roles = Ordered(guild, Settings)[:MAX_COLORS]
    Emojis = await _emojis.For(client, Roles) if Roles else {}
    File = None
    if Roles:
        Entries = [(CleanName(R.name), *Colors(R)) for R in Roles]
        File = discord.File(io.BytesIO(await asyncio.to_thread(Swatch, Entries)), filename=SWATCH)
    return PanelView(guild, Settings, Roles, Emojis), File


async def Publish(client, guild: discord.Guild, channel=None) -> str:
    Settings = (await Store().Get(guild.id))["colors"]
    Channel = channel or guild.get_channel(Settings["channel"] or 0)
    if not Channel:
        return "❌ Elige primero el canal."
    if not Ordered(guild, Settings):
        return "❌ Elige primero los roles de colores."
    View, File = await Build(client, guild)
    if Settings["message_id"] and Settings["channel"] == Channel.id:
        try:
            await Channel.get_partial_message(Settings["message_id"]).edit(view=View, attachments=[File])
            return f"✅ Actualizado en {Channel.mention}."
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            return f"❌ No pude editarlo: {e.text or e}"
    elif Settings["message_id"]:  # moved to another channel: the old message goes
        Old = guild.get_channel(Settings["channel"] or 0)
        if Old:
            try:
                await Old.get_partial_message(Settings["message_id"]).delete()
            except discord.HTTPException:
                pass
    try:
        Message = await Channel.send(view=View, file=File, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        return f"❌ No pude publicar en {Channel.mention}: {e.text or e}"
    await Store().Set(guild.id, "colors", {"channel": Channel.id, "message_id": Message.id})
    return f"✅ Publicado en {Channel.mention}."


class ColorButton(ui.DynamicItem[ui.Button], template=r"bcolor:(?P<role>\d{15,21}|off)"):
    def __init__(self, role: str, number: int | None = None, emoji: str | None = None):
        if role == "off":
            Button = ui.Button(emoji="✖️", style=discord.ButtonStyle.grey, custom_id="bcolor:off")
        else:
            Emoji = None
            try:
                Emoji = discord.PartialEmoji.from_str(emoji) if emoji else None
            except Exception:
                pass
            Button = ui.Button(label=f"{number:02d}" if number else None, emoji=Emoji, style=discord.ButtonStyle.grey, custom_id=f"bcolor:{role}")
        super().__init__(Button)
        self.role = role

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["role"])

    async def callback(self, interaction: discord.Interaction):
        Guild, Member = interaction.guild, interaction.user
        if not IsBooster(Member):
            return await interaction.response.send_message(
                f"💎 Los colores degradados son solo para {BoosterMention(Guild)}. ¡Boostea el servidor para elegir uno!",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
        Palette = set((await Store().Get(Guild.id))["colors"]["roles"] or [])
        Cog = interaction.client.get_cog("BoosterColors")
        async with (Cog.Lock(Member.id) if Cog else asyncio.Lock()):
            Member = Guild.get_member(Member.id) or Member
            Mine = {R.id for R in Member.roles}
            if self.role == "off":
                Add, Remove, What = set(), Mine & Palette, "off"
                if not Remove:
                    return await interaction.response.send_message("No llevas ningún color degradado.", ephemeral=True)
            else:
                Clicked = int(self.role)
                if Clicked not in Palette or not Guild.get_role(Clicked):
                    return await interaction.response.send_message("❌ Ese color ya no existe.", ephemeral=True)
                Add, Remove, What = IconSwap(Mine, Palette, Clicked)
            Roles = [R for R in Member.roles if R.id not in Remove and not R.is_default()] + [Guild.get_role(I) for I in Add]
            try:
                await Member.edit(roles=[R for R in Roles if R], reason="Color degradado de booster")
            except discord.HTTPException as e:
                return await interaction.response.send_message(f"❌ No pude cambiar tu color: {e.text or e}", ephemeral=True)
        New = Guild.get_role(next(iter(Add))) if Add else None
        Old = ", ".join(f"<@&{R}>" for R in Remove)
        Text = {
            "added": f"✨ Ahora llevas {New.mention if New else ''}.",
            "swapped": f"🔄 Cambiaste {Old} → {New.mention if New else ''}.",
            "removed": f"🗑️ Te quitaste {Old}.",
            "off": f"🗑️ Te quitaste {Old}.",
        }[What]
        await interaction.response.send_message(Text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        Icons = interaction.client.get_cog("BoosterIcons")
        if Icons:
            await Icons.Log(Guild, f"🎨 {Member.mention} · {Text}")


# ---------------- /config → Comunidad → Colores boosters ----------------


def SettingsEmbed(guild: discord.Guild, settings: dict) -> discord.Embed:
    Me = guild.me
    Roles = Ordered(guild, settings)
    embed = discord.Embed(title="🌈 Colores boosters", color=discord.Color.from_rgb(150, 12, 18))
    embed.description = (
        "Un solo mensaje con tus roles de **color degradado**. LOJI lee el degradado de cada rol y dibuja el muestrario "
        "y los emojis de los botones (`01`, `02`…). Solo boosters, **un color a la vez** (aparte de los iconos).\n"
        "-# Si cambias un color o un nombre en Discord, pulsa **Publicar / actualizar** y se redibuja."
    )
    Lines, Warnings = [], []
    for I, R in enumerate(Roles, 1):
        First, Second = Colors(R)
        Lines.append(f"`{I:02d}` {R.mention} · `#{First:06X}` → `#{Second:06X}`")
        if R >= Me.top_role:
            Warnings.append(f"{R.mention} está por encima del rol de LOJI: no podré ponerlo.")
        elif First == Second:
            Warnings.append(f"{R.mention} no tiene degradado (un solo color).")
    embed.add_field(name=f"Colores ({len(Roles)}/{MAX_COLORS})", value="\n".join(Lines)[:1024] or "*Elige los roles en el menú.*", inline=False)
    embed.add_field(
        name="Mensaje", value=(f"<#{settings['channel']}>" + (" · ✅ publicado" if settings.get("message_id") else "")) if settings.get("channel") else "*sin canal*",
        inline=True,
    )
    embed.add_field(name="Línea", value=f"`{settings['color']}`", inline=True)
    if Warnings:
        embed.add_field(name="⚠️ Revisa", value="\n".join(Warnings)[:1024], inline=False)
    return embed


class ColorsPanel(Owned):
    def __init__(self, author):
        super().__init__(author)
        Roles = discord.ui.RoleSelect(placeholder=f"🌈 Roles de colores (en el orden del panel, hasta {MAX_COLORS})", min_values=1, max_values=MAX_COLORS, row=0)
        Roles.callback = self.PickRoles
        self.add_item(Roles)
        Channel = discord.ui.ChannelSelect(placeholder="📍 Canal del mensaje", channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=1)
        Channel.callback = self.PickChannel
        self.add_item(Channel)
        self.add_item(Back(row=3))

    @classmethod
    async def Open(cls, interaction, author, note=None):
        Settings = (await Store().Get(interaction.guild.id))["colors"]
        await Show(interaction, SettingsEmbed(interaction.guild, Settings), cls(author), note)

    async def PickRoles(self, interaction: discord.Interaction):
        Guild = interaction.guild
        Roles = [Guild.get_role(int(V)) for V in interaction.data["values"]]
        Bad = [R.mention for R in Roles if R and (R.managed or R.is_default())]
        if Bad:
            return await interaction.response.send_message(f"❌ Esos roles son automáticos: {', '.join(Bad)}", ephemeral=True)
        await Store().Set(Guild.id, "colors", {"roles": [R.id for R in Roles if R]})
        await ColorsPanel.Open(interaction, self.author, "✅ Colores guardados en este orden. Si el orden no es el que quieres, vuelve a elegirlos uno a uno en orden.")

    async def PickChannel(self, interaction: discord.Interaction):
        await interaction.response.defer()
        Channel = interaction.guild.get_channel(int(interaction.data["values"][0]))
        Settings = (await Store().Get(interaction.guild.id))["colors"]
        if not Settings["roles"]:
            await Store().Set(interaction.guild.id, "colors", {"channel": Channel.id})
            return await ColorsPanel.Open(interaction, self.author, "✅ Canal guardado. Elige los roles y pulsa **Publicar**.")
        await ColorsPanel.Open(interaction, self.author, await Publish(interaction.client, interaction.guild, Channel))

    @discord.ui.button(label="Textos y banner", emoji="✏️", style=discord.ButtonStyle.blurple, row=2)
    async def Texts(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(ColorTexts(self.author, (await Store().Get(interaction.guild.id))["colors"]))

    @discord.ui.button(label="Color de la línea", emoji="🎨", style=discord.ButtonStyle.blurple, row=2)
    async def Line(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LineColor(self.author, (await Store().Get(interaction.guild.id))["colors"]["color"]))

    @discord.ui.button(label="Vista previa", emoji="👁️", style=discord.ButtonStyle.grey, row=2)
    async def Preview(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        View, File = await Build(interaction.client, interaction.guild)
        Kwargs = {"file": File} if File else {}
        await interaction.followup.send(view=View, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **Kwargs)

    @discord.ui.button(label="Publicar / actualizar", emoji="📤", style=discord.ButtonStyle.green, row=2)
    async def Publish_(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await ColorsPanel.Open(interaction, self.author, await Publish(interaction.client, interaction.guild))


class ColorTexts(discord.ui.Modal, title="Colores boosters"):
    def __init__(self, author, settings):
        super().__init__()
        self.author = author
        self.fields = {
            "title": Field("Título", settings["title"], 200, long=False, required=True),
            "text": Field("Texto ({server}, {booster})", settings["text"], 800),
            "heading": Field("Título de la colección ({total})", settings["heading"], 200, long=False),
            "footer": Field("Pie", settings["footer"], 600),
            "banner": Field("Banner (enlace, vacío = sin banner)", settings["banner"], 400, long=False),
        }
        for F in self.fields.values():
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        Values = {K: F.value.strip() for K, F in self.fields.items()}
        if Values["banner"] and not Values["banner"].startswith(("http://", "https://")):
            return await interaction.response.send_message("❌ El banner tiene que ser un enlace `https://` a una imagen.", ephemeral=True)
        await Store().Set(interaction.guild.id, "colors", Values)
        await ColorsPanel.Open(interaction, self.author, "✅ Guardado. Pulsa **Publicar / actualizar** para aplicarlo.")


class LineColor(discord.ui.Modal, title="Color de la línea"):
    def __init__(self, author, current):
        super().__init__()
        self.author = author
        self.value = Field("Color (hex)", current, 7, long=False, required=True)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        Value = self.value.value.strip()
        if not ValidColor(Value):
            return await interaction.response.send_message("❌ El color va en hex, por ejemplo `#BBA896`.", ephemeral=True)
        await Store().Set(interaction.guild.id, "colors", {"color": Value if Value.startswith("#") else f"#{Value}"})
        await ColorsPanel.Open(interaction, self.author, "✅ Guardado. Pulsa **Publicar / actualizar** para aplicarlo.")


class BoosterColors(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self):
        self.client.add_dynamic_items(ColorButton)

    def Lock(self, user_id: int) -> asyncio.Lock:
        return self.locks.setdefault(user_id, asyncio.Lock())


async def setup(client: commands.Bot) -> None:
    await client.add_cog(BoosterColors(client))
