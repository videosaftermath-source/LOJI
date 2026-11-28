"""/guia: the staff asks the sanctions guide (2 questions per 24 h, one configurable role). Settings live in /config."""

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.guide import (
    ALLOWED, PER_DAY, QUESTION_MAX, ApproxTokens, Ask, Aware, ExtractText, Guide, GuideError, MaskKey, Provider, ValidKey,
)

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
PANEL_TIMEOUT = 600
_store: Guide | None = None


def Store() -> Guide:
    global _store
    if _store is None:
        from core.db import db

        _store = Guide(db)
    return _store


# ---------------- /config panel ----------------


async def PanelEmbed(guild: discord.Guild) -> discord.Embed:
    Doc = await Store().Get(guild.id) or {}
    Key = await Store().Key(guild.id)
    Role = guild.get_role(Doc.get("role") or 0)
    embed = discord.Embed(title="📚 Guía de sanciones", color=LOJI_RED)
    embed.description = (
        f"El staff con el rol elegido pregunta con `/guia` (**{PER_DAY} preguntas cada 24 h**). "
        "Se responde solo con lo que dice la guía; cada pregunta es independiente (sin memoria)."
    )
    if Doc.get("text"):
        Updated = Doc.get("updated_at")
        embed.add_field(
            name="📄 Guía cargada",
            value=f"`{Doc.get('filename', 'guía')}` · ~{ApproxTokens(Doc['text']):,} tokens".replace(",", ".")
            + (f"\nActualizada {discord.utils.format_dt(Aware(Updated), 'R')} por <@{Doc.get('updated_by')}>" if Updated else ""),
            inline=False,
        )
    else:
        embed.add_field(name="📄 Guía", value="❌ Todavía no hay guía. Pulsa **Subir guía**.", inline=False)
    embed.add_field(name="🎭 Quién puede preguntar", value=Role.mention if Role else "❌ *sin configurar*", inline=True)
    embed.add_field(
        name=f"🔑 Key de la IA · {Provider(Key)['name']}" if Key else "🔑 Key de la IA",
        value=MaskKey(Key) + (" *(del .env)*" if Key and not Doc.get("groq_key") else ""),
        inline=True,
    )
    embed.set_footer(text=f"Modelo: {Provider(Key)['model']} ({Provider(Key)['name']}) · también lo usan el autoreporte y LOJI (chat)")
    return embed


class GuidePanel(discord.ui.View):
    def __init__(self, author, back=None):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author, self.back = author, back
        Pick = discord.ui.RoleSelect(placeholder="🎭 Rol que puede preguntar", min_values=0, max_values=1, row=0)
        Pick.callback = self.PickRole
        self.add_item(Pick)
        if back is None:
            self.remove_item(self.Back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Este panel no es tuyo.", ephemeral=True)
            return False
        return True

    async def Refresh(self, interaction: discord.Interaction, note: str | None = None):
        Edit = interaction.response.edit_message if not interaction.response.is_done() else interaction.edit_original_response
        await Edit(content=note, embed=await PanelEmbed(interaction.guild), view=GuidePanel(self.author, self.back))

    async def PickRole(self, interaction: discord.Interaction):
        Values = interaction.data.get("values") or []
        await Store().SetRole(interaction.guild.id, int(Values[0]) if Values else None)
        await self.Refresh(interaction, "✅ Rol guardado." if Values else "🧹 Rol quitado: nadie puede preguntar.")

    @discord.ui.button(label="Subir guía", emoji="📤", style=discord.ButtonStyle.green, row=1)
    async def Upload(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(UploadModal(self))

    @discord.ui.button(label="Descargar guía actual", emoji="📥", style=discord.ButtonStyle.grey, row=1)
    async def Download(self, interaction: discord.Interaction, _):
        Doc = await Store().Get(interaction.guild.id) or {}
        if not Doc.get("text"):
            return await interaction.response.send_message("Todavía no hay guía cargada.", ephemeral=True)
        File = discord.File(io.BytesIO(Doc["text"].encode("utf-8")), filename="guia-sanciones-actual.txt")
        await interaction.response.send_message(
            "📥 Esto es exactamente lo que lee el bot (el texto que sacó de tu archivo).", file=File, ephemeral=True,
        )

    @discord.ui.button(label="Key de la IA", emoji="🔑", style=discord.ButtonStyle.blurple, row=1)
    async def SetKey(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(KeyModal(self))

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back(self, interaction: discord.Interaction, _):
        await self.back(interaction)

    @discord.ui.button(label="Autoreporte", emoji="🚩", style=discord.ButtonStyle.blurple, row=2)
    async def AutoReport(self, interaction: discord.Interaction, _):
        from cogs.Modules.Guide.autoreport import OpenPanel

        await OpenPanel(interaction, self.author, self.back)


class UploadModal(discord.ui.Modal, title="Subir guía de sanciones"):
    def __init__(self, panel: GuidePanel):
        super().__init__()
        self.panel = panel
        self.file = discord.ui.FileUpload(min_values=1, max_values=1)
        self.add_item(discord.ui.Label(text="Archivo de la guía", description="Word (.docx), .txt o .md. Reemplaza la anterior.", component=self.file))

    async def on_submit(self, interaction: discord.Interaction):
        Files = self.file.values or []
        if not Files:
            return await interaction.response.send_message("❌ No llegó ningún archivo.", ephemeral=True)
        Attachment = Files[0]
        if not Attachment.filename.lower().endswith(ALLOWED + (".doc",)):
            return await interaction.response.send_message("❌ Sube la guía como Word (.docx), .txt o .md.", ephemeral=True)
        await interaction.response.defer()
        try:
            Text = ExtractText(Attachment.filename, await Attachment.read())
        except GuideError as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except discord.HTTPException:
            return await interaction.followup.send("❌ No pude descargar el archivo. Inténtalo otra vez.", ephemeral=True)
        await Store().Save(interaction.guild.id, Text, Attachment.filename, interaction.user.id)
        await self.panel.Refresh(
            interaction,
            f"✅ Guía cargada: **{len(Text):,} caracteres** (~{ApproxTokens(Text):,} tokens). Ya se usa en `/guia`.".replace(",", ".")
            + "\n-# Si tenía tablas o formato especial, revisa cómo quedó con **Descargar guía actual**.",
        )


class KeyModal(discord.ui.Modal, title="Key de la IA (DeepSeek o Groq)"):
    def __init__(self, panel: GuidePanel):
        super().__init__()
        self.panel = panel
        self.key = discord.ui.TextInput(
            label="Key (vacío = usar la del .env)", placeholder="DeepSeek: sk-...   ·   Groq: gsk_...", required=False, max_length=200,
        )
        self.add_item(self.key)

    async def on_submit(self, interaction: discord.Interaction):
        Key = self.key.value.strip()
        if Key and not ValidKey(Key):
            return await interaction.response.send_message("❌ Las keys de DeepSeek empiezan por `sk-` y las de Groq por `gsk_`.", ephemeral=True)
        await Store().SetKey(interaction.guild.id, Key or None)
        await self.panel.Refresh(interaction, f"🔑 Key de **{Provider(Key)['name']}** guardada: `/guia`, el autoreporte y LOJI (chat) la usan desde ya." if Key else "🔑 Key borrada: se usará la del .env (`DEEPSEEK_API_KEY` o `GROQ_API_KEY`) si existe.")


# ---------------- /guia ----------------


class GuideCog(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @app_commands.command(name="guia", description="Pregunta una duda a la guía de sanciones (2 cada 24 h)")
    @app_commands.describe(pregunta="Tu duda, concreta. Ej.: ¿cuánto mute por spam reincidente?")
    @app_commands.guild_only()
    async def guia(self, interaction: discord.Interaction, pregunta: app_commands.Range[str, 5, QUESTION_MAX]):
        Doc = await Store().Get(interaction.guild.id) or {}
        Role = Doc.get("role")
        if not Role or Role not in {R.id for R in interaction.user.roles}:
            return await interaction.response.send_message(
                "❌ `/guia` es solo para el staff con el rol configurado." if Role else "❌ Todavía no se eligió quién puede usar `/guia` (`/config` → Mando Central → Guía de sanciones).",
                ephemeral=True,
            )
        if not Doc.get("text"):
            return await interaction.response.send_message("❌ Todavía no hay guía cargada.", ephemeral=True)
        Key = await Store().Key(interaction.guild.id)
        if not Key:
            return await interaction.response.send_message("❌ Falta la key de la IA (`/config` → Mando Central → Guía de sanciones).", ephemeral=True)
        Left, Free = await Store().Remaining(interaction.guild.id, interaction.user.id)
        if not Left:
            return await interaction.response.send_message(
                f"⏳ Ya usaste tus {PER_DAY} preguntas de las últimas 24 h. La siguiente se libera {discord.utils.format_dt(Free, 'R')}.",
                ephemeral=True,
            )
        await interaction.response.defer(thinking=True)  # the answer is public

        async def Private(text: str):
            """Errors stay private: remove the public 'thinking...' and tell only the asker."""
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                pass
            await interaction.followup.send(text, ephemeral=True)

        try:
            Answer = await Ask(Key, Doc["text"], pregunta, interaction.guild.name)
        except GuideError as e:
            return await Private(f"❌ {e}")
        except Exception as e:
            logger.exception(f"[Guide] Unexpected error: {e!r}")
            return await Private("❌ Algo falló al preguntar. No se te ha descontado la pregunta.")
        await Store().Count(interaction.guild.id, interaction.user.id)  # only answered questions count
        embed = discord.Embed(title="📚 Guía de sanciones", color=LOJI_RED)
        embed.add_field(name="❓ Pregunta", value=pregunta[:1024], inline=False)
        embed.description = Answer[:4000]
        Updated = Doc.get("updated_at")
        embed.set_footer(
            text=f"Te queda{'n' if Left - 1 != 1 else ''} {Left - 1} pregunta{'s' if Left - 1 != 1 else ''} en estas 24 h"
            + (f" · Guía del {Updated:%d/%m/%Y}" if Updated else "")
            + " · Revisa la guía ante la duda"
        )
        embed.set_author(name=f"Pregunta de {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(GuideCog(client))
