"""/anuncio: a ready-made LOJI announcement. Admins only write the title and text."""

import io
import os

import discord
from discord import app_commands
from discord.ext import commands

from cogs.Modules.Utilities.info import LOJI_RED

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "announce")
DEFAULT_BANNER = os.path.join(ASSETS, "banner.png")
DEFAULT_ICON = os.path.join(ASSETS, "icono.png")
DEFAULT_AUTHOR = "Departamento Administrativo ESS"
FOOTER = "Transmitido por LOJI"
PREVIEW_TIMEOUT = 600
MAX_IMAGE_BYTES = 8 * 1024 * 1024
TITLE_MAX = 256
TEXT_MAX = 4000  # a modal text box holds 4000 (the embed allows 4096)

# Discord can't change fonts in embeds, so the author line uses Unicode small capitals.
SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ",
)


def Fancy(text: str) -> str:
    return text.lower().translate(SMALL_CAPS)


def CheckImage(attachment: discord.Attachment | None):
    if attachment is None:
        return
    if not (attachment.content_type or "").startswith("image/"):
        raise ValueError(f"`{attachment.filename}` no es una imagen.")
    if attachment.size > MAX_IMAGE_BYTES:
        raise ValueError(f"`{attachment.filename}` pesa demasiado (máximo 8 MB).")


async def ReadImage(attachment: discord.Attachment | None, default: str, name: str) -> tuple[bytes, str]:
    """(bytes, file name) of an uploaded image, or the default one. Uploaded images are re-sent
    with the message because Discord's links to command attachments expire."""
    if attachment is None:
        with open(default, "rb") as F:
            return F.read(), f"{name}.png"
    Extension = os.path.splitext(attachment.filename)[1].lower() or ".png"
    return await attachment.read(), f"{name}{Extension}"


class Draft:
    """Everything needed to build (and rebuild) the announcement."""

    def __init__(self, author: str, banner: discord.Attachment | None, icon: discord.Attachment | None, mention: discord.Role | None):
        self.title = ""
        self.text = ""
        self.author = author
        self.uploads = (banner, icon)
        self.banner: tuple[bytes, str] | None = None
        self.icon: tuple[bytes, str] | None = None
        self.mention = mention

    async def Load(self):
        if self.banner is None:
            self.banner = await ReadImage(self.uploads[0], DEFAULT_BANNER, "banner")
            self.icon = await ReadImage(self.uploads[1], DEFAULT_ICON, "icono")

    def Content(self) -> str | None:
        if not self.mention:
            return None
        return "@everyone" if self.mention.is_default() else self.mention.mention

    def Build(self, sender: discord.ClientUser) -> tuple[discord.Embed, list[discord.File]]:
        embed = discord.Embed(title=self.title, description=self.text, color=LOJI_RED, timestamp=discord.utils.utcnow())
        Icon = f"attachment://{self.icon[1]}"
        embed.set_author(name=Fancy(self.author)[:256], icon_url=Icon)
        embed.set_thumbnail(url=Icon)
        embed.set_image(url=f"attachment://{self.banner[1]}")
        embed.set_footer(text=FOOTER, icon_url=sender.display_avatar.url)
        Files = [discord.File(io.BytesIO(self.banner[0]), self.banner[1]), discord.File(io.BytesIO(self.icon[0]), self.icon[1])]
        return embed, Files


class TextModal(discord.ui.Modal, title="Anuncio"):
    def __init__(self, draft: Draft, channel: discord.abc.Messageable, preview: "Preview | None" = None):
        super().__init__()
        self.draft = draft
        self.channel = channel
        self.preview = preview
        self.heading = discord.ui.TextInput(label="Título", max_length=TITLE_MAX, default=draft.title or None)
        self.body = discord.ui.TextInput(
            label="Descripción", style=discord.TextStyle.paragraph, max_length=TEXT_MAX, default=draft.text or None
        )
        self.add_item(self.heading)
        self.add_item(self.body)

    async def on_submit(self, interaction: discord.Interaction):
        self.draft.title, self.draft.text = self.heading.value.strip(), self.body.value.strip()
        if not self.preview:
            # Downloading uploaded images can take a moment.
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                await self.draft.Load()
            except discord.HTTPException:
                return await interaction.followup.send("❌ No pude descargar la imagen. Prueba a subirla otra vez.", ephemeral=True)
        View = self.preview or Preview(interaction.user, self.draft, self.channel)
        embed, Files = self.draft.Build(interaction.client.user)
        Note = f"👀 **Vista previa** · se enviará en {self.channel.mention}" + (f" mencionando {self.draft.Content()}" if self.draft.mention else "")
        if self.preview:
            await interaction.response.edit_message(content=Note, embed=embed, attachments=Files, view=View)
        else:
            await interaction.followup.send(Note, embed=embed, files=Files, view=View, ephemeral=True)


class Preview(discord.ui.View):
    def __init__(self, author: discord.abc.User, draft: Draft, channel: discord.abc.Messageable):
        super().__init__(timeout=PREVIEW_TIMEOUT)
        self.author = author
        self.draft = draft
        self.channel = channel

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    @discord.ui.button(label="Enviar", emoji="📢", style=discord.ButtonStyle.red)
    async def Send(self, interaction: discord.Interaction, _):
        embed, Files = self.draft.Build(interaction.client.user)
        Mentions = discord.AllowedMentions(everyone=True, roles=True, users=False)
        try:
            Message = await self.channel.send(content=self.draft.Content(), embed=embed, files=Files, allowed_mentions=Mentions)
        except discord.Forbidden:
            return await interaction.response.send_message(f"❌ No tengo permiso para escribir o subir imágenes en {self.channel.mention}.", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content=f"✅ Anuncio enviado: {Message.jump_url}", embed=None, attachments=[], view=None)

    @discord.ui.button(label="Editar texto", emoji="✏️", style=discord.ButtonStyle.grey)
    async def Edit(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(TextModal(self.draft, self.channel, preview=self))

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.grey)
    async def Cancel(self, interaction: discord.Interaction, _):
        self.stop()
        await interaction.response.edit_message(content="Anuncio cancelado.", embed=None, attachments=[], view=None)


class Announce(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(name="anuncio", description="Publica un anuncio con el diseño de LOJI (solo escribe título y texto)")
    @app_commands.describe(
        canal="Dónde publicarlo (por defecto, este canal)",
        mencion="A quién mencionar (elige @everyone o un rol)",
        autor=f"Texto de arriba (por defecto: {DEFAULT_AUTHOR})",
        imagen="Banner grande (por defecto, el de LOJI)",
        icono="Icono de la esquina (por defecto, el dragón)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def anuncio(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        mencion: discord.Role | None = None,
        autor: app_commands.Range[str, 1, 200] | None = None,
        imagen: discord.Attachment | None = None,
        icono: discord.Attachment | None = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Solo los administradores pueden publicar anuncios.", ephemeral=True)
        try:
            CheckImage(imagen)
            CheckImage(icono)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        Draft_ = Draft(autor or DEFAULT_AUTHOR, imagen, icono, mencion)
        await interaction.response.send_modal(TextModal(Draft_, canal or interaction.channel))


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Announce(client))
