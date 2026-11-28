"""/config → 🎉 Crecimiento y Entretenimiento."""

import discord

from cogs.Modules.Community.panel import Field, Owned, Show
from core.community import Store, ValidColor

LOJI_RED = discord.Color.from_rgb(150, 12, 18)


async def MainEmbed(guild: discord.Guild) -> discord.Embed:
    E = (await Store().Get(guild.id))["events"]
    embed = discord.Embed(title="🎉 Crecimiento y Entretenimiento", color=LOJI_RED)
    embed.description = "Eventos, transmisiones de anime y más para que el servidor crezca."
    Ready = E["organizer_role"] and E["channel"]
    embed.add_field(
        name="🎉 Eventos",
        value=("✅ Listo" if Ready else "⚙️ Falta configurar") + " · equipo: " + (f"<@&{E['organizer_role']}>" if E["organizer_role"] else "*sin rol*")
        + "\n-# `/evento crear · finalizar · cancelar · historial`",
        inline=False,
    )
    embed.add_field(name="📺 Anime", value="*Próximamente*", inline=False)
    return embed


class GrowthPanel(Owned):
    @discord.ui.button(label="Eventos", emoji="🎉", style=discord.ButtonStyle.blurple)
    async def Events(self, interaction: discord.Interaction, _):
        await EventsPanel.Open(interaction, self.author)

    @classmethod
    async def Open(cls, interaction, author, note=None):
        await Show(interaction, await MainEmbed(interaction.guild), cls(author), note)


async def OpenPanel(interaction: discord.Interaction):
    from core.mail.config import CanConfigure, Mail

    if not CanConfigure(interaction.user, await Mail().Get(interaction.guild.id)):
        return await interaction.followup.send("❌ Solo el Tenno (o un administrador) configura esta sección.", ephemeral=True)
    await GrowthPanel.Open(interaction, interaction.user)


def EventsEmbed(guild: discord.Guild, E: dict) -> discord.Embed:
    def Where(value, kind="channel"):
        return (f"<@&{value}>" if kind == "role" else f"<#{value}>") if value else "*sin elegir*"

    embed = discord.Embed(title="🎉 Eventos", color=LOJI_RED)
    embed.description = (
        "El equipo de eventos crea eventos con `/evento crear`: formulario sencillo (título, descripción, fecha, premios, banner), "
        "inscripción con plazas opcional, evento de Discord opcional y diseño JSON opcional. LOJI avisa antes de empezar y "
        "`/evento finalizar` reparte los premios (monedas y roles solos; lo demás, para entregar a mano)."
    )
    embed.add_field(name="👥 Equipo de eventos", value=Where(E["organizer_role"], "role"), inline=True)
    embed.add_field(name="📣 Canal de eventos", value=Where(E["channel"]), inline=True)
    embed.add_field(name="🔔 Rol a avisar", value=Where(E["ping_role"], "role") if E["ping_role"] else "*nadie*", inline=True)
    embed.add_field(name="📒 Registro", value=Where(E["log_channel"]) if E["log_channel"] else "*desactivado*", inline=True)
    embed.add_field(name="⏰ Aviso previo", value=f"{E['remind_minutes']} min antes", inline=True)
    embed.add_field(name="🎨 Línea", value=f"`{E['color']}`", inline=True)
    return embed


class EventsPanel(Owned):
    def __init__(self, author):
        super().__init__(author)
        Items = (
            (discord.ui.RoleSelect, "organizer_role", "👥 Rol del equipo de eventos", 0, 1),
            (discord.ui.ChannelSelect, "channel", "📣 Canal donde se anuncian", 1, 1),
            (discord.ui.RoleSelect, "ping_role", "🔔 Rol a avisar (opcional, vacío = nadie)", 2, 0),
            (discord.ui.ChannelSelect, "log_channel", "📒 Canal de registro (opcional, vacío = sin registro)", 3, 0),
        )
        for Kind, Key, Placeholder, Row, Min in Items:
            Extra = {"channel_types": [discord.ChannelType.text, discord.ChannelType.news]} if Kind is discord.ui.ChannelSelect else {}
            Pick = Kind(placeholder=Placeholder, min_values=Min, max_values=1, row=Row, **Extra)
            Pick.callback = self.Saver(Key)
            self.add_item(Pick)

    @classmethod
    async def Open(cls, interaction, author, note=None):
        E = (await Store().Get(interaction.guild.id))["events"]
        await Show(interaction, EventsEmbed(interaction.guild, E), cls(author), note)

    def Saver(self, key):
        async def Save(interaction: discord.Interaction):
            Values = interaction.data.get("values") or []
            await Store().Set(interaction.guild.id, "events", {key: int(Values[0]) if Values else None})
            await EventsPanel.Open(interaction, self.author, "✅ Guardado.")
        return Save

    @discord.ui.button(label="Aviso y color", emoji="⚙️", style=discord.ButtonStyle.blurple, row=4)
    async def Options(self, interaction: discord.Interaction, _):
        E = (await Store().Get(interaction.guild.id))["events"]
        await interaction.response.send_modal(EventOptions(self.author, E))

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=4)
    async def Back(self, interaction: discord.Interaction, _):
        await GrowthPanel.Open(interaction, self.author)


class EventOptions(discord.ui.Modal, title="Eventos"):
    def __init__(self, author, E):
        super().__init__()
        self.author = author
        self.minutes = Field("Avisar cuántos minutos antes", E["remind_minutes"], 4, long=False, required=True)
        self.color = Field("Color de la línea (hex)", E["color"], 7, long=False, required=True)
        self.add_item(self.minutes)
        self.add_item(self.color)

    async def on_submit(self, interaction: discord.Interaction):
        Minutes = self.minutes.value.strip()
        if not Minutes.isdigit() or not 5 <= int(Minutes) <= 1440 or not ValidColor(self.color.value):
            return await interaction.response.send_message("❌ Minutos entre 5 y 1440, y color en hex (`#BBA896`).", ephemeral=True)
        Color = self.color.value.strip()
        await Store().Set(interaction.guild.id, "events", {"remind_minutes": int(Minutes), "color": Color if Color.startswith("#") else f"#{Color}"})
        await EventsPanel.Open(interaction, self.author, "✅ Guardado.")
