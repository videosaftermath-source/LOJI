"""/config → Quota → Anti-spam: the two levels, the alert channel, who is called on level 2, texts and banner."""


import aiohttp
import discord
from bson.binary import Binary

from core.quota_spam import DEFAULTS, Fill, Settings

LOJI_RED = discord.Color.from_rgb(150, 12, 18)
MAX_BANNER = 8 * 1024 * 1024


async def Save(interaction: discord.Interaction, changes: dict):
    await interaction.client.db["Config"].update_one(
        {"_id": interaction.guild.id}, {"$set": {f"Message Quota.AntiSpam.{K}": V for K, V in changes.items()}}, upsert=True,
    )


async def Current(interaction: discord.Interaction) -> dict:
    return Settings(await interaction.client.db["Config"].find_one({"_id": interaction.guild.id}))


def PanelEmbed(guild: discord.Guild, s: dict, has_banner: bool) -> discord.Embed:
    from cogs.Events.on_counter import NotifyMention

    embed = discord.Embed(title="🛡️ Anti-spam de la cuota", color=LOJI_RED)
    embed.description = ("✅ **Activado.**" if s["enabled"] else "⏸️ **Desactivado.**") + " Evita que escribir rápido o hacer spam infle la cuota."
    embed.add_field(
        name="⚠️ Nivel 1 · escribir rápido",
        value=f"Más de **{s['l1_count']}** mensajes en **{s['l1_seconds']} s**: los que sobran no cuentan y sale un aviso suave (se borra solo).",
        inline=False,
    )
    embed.add_field(
        name="🚨 Nivel 2 · spam",
        value=f"**{s['l2_count']}** mensajes en **{s['l2_seconds']} s**: se descuentan, no cuenta nada en **{s['pause_minutes']} min** "
        f"y sale el aviso con banner llamando a {NotifyMention(s)}.",
        inline=False,
    )
    Alerts = guild.get_channel(s.get("alert_channel") or 0)
    embed.add_field(name="📒 Alertas a administración", value=Alerts.mention if Alerts else "*sin canal*", inline=True)
    embed.add_field(name="🖼️ Banner", value="✅ guardado en LOJI" if has_banner else ("enlace (sin copia)" if s["banner_url"] else "*sin banner*"), inline=True)
    embed.set_footer(text="Pulsa Probar para ver los dos avisos (solo tú)")
    return embed


async def Open(interaction: discord.Interaction, note: str | None = None, edit: bool = True):
    s = await Current(interaction)
    Has = bool(await interaction.client.db["quota_spam_banner"].find_one({"_id": interaction.guild.id}, {"_id": 1}))
    Embed, View = PanelEmbed(interaction.guild, s, Has), AntiSpamPanel(interaction.user, s)
    if edit:
        Edit = interaction.edit_original_response if interaction.response.is_done() else interaction.response.edit_message
        return await Edit(content=note, embed=Embed, view=View)
    await interaction.followup.send(content=note, embed=Embed, view=View, ephemeral=True)


class AntiSpamPanel(discord.ui.View):
    def __init__(self, author, s: dict):
        super().__init__(timeout=600)
        self.author = author
        Channel = discord.ui.ChannelSelect(placeholder="📒 Canal de alertas para administración", channel_types=[discord.ChannelType.text], row=0)
        Channel.callback = self.PickChannel
        self.add_item(Channel)
        Who = discord.ui.MentionableSelect(placeholder="📣 A quién llamar en el nivel 2 (persona o rol)", min_values=0, max_values=1, row=1)
        Who.callback = self.PickWho
        self.add_item(Who)
        self.Toggle.label = "Desactivar" if s["enabled"] else "Activar"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Este panel no es tuyo.", ephemeral=True)
            return False
        return True

    async def PickChannel(self, interaction: discord.Interaction):
        await Save(interaction, {"alert_channel": int(interaction.data["values"][0])})
        await Open(interaction, "✅ Canal de alertas guardado.")

    async def PickWho(self, interaction: discord.Interaction):
        Values = interaction.data.get("values") or []
        Resolved = interaction.data.get("resolved") or {}
        Notify = None
        if Values:
            Notify = {"id": int(Values[0]), "type": "role" if Values[0] in (Resolved.get("roles") or {}) else "user"}
        await Save(interaction, {"notify": Notify})
        await Open(interaction, "✅ Guardado." if Notify else "🧹 Nadie: el aviso dirá «la administración».")

    @discord.ui.button(label="Activar", emoji="⏯️", style=discord.ButtonStyle.green, row=2)
    async def Toggle(self, interaction: discord.Interaction, _):
        s = await Current(interaction)
        await Save(interaction, {"enabled": not s["enabled"]})
        await Open(interaction, "✅ Activado." if not s["enabled"] else "⏸️ Desactivado: todos los mensajes del staff vuelven a contar.")

    @discord.ui.button(label="Niveles", emoji="⚙️", style=discord.ButtonStyle.blurple, row=2)
    async def Levels(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(LevelsModal(await Current(interaction)))

    @discord.ui.button(label="Textos", emoji="✏️", style=discord.ButtonStyle.blurple, row=2)
    async def Texts(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(TextsModal(await Current(interaction)))

    @discord.ui.button(label="Banner", emoji="🖼️", style=discord.ButtonStyle.blurple, row=2)
    async def Banner(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BannerModal((await Current(interaction))["banner_url"]))

    @discord.ui.button(label="Probar", emoji="👁️", style=discord.ButtonStyle.grey, row=3)
    async def Test(self, interaction: discord.Interaction, _):
        from cogs.Events.on_counter import NotifyMention, StaringEmbed

        s = await Current(interaction)
        Values = {"user": interaction.user.mention, "nombre": interaction.user.display_name, "aviso": NotifyMention(s),
                  "cantidad": s["l2_count"], "canal": interaction.channel.mention}
        await interaction.response.send_message("**Nivel 1** (en el canal, se borra a los 15 s):\n" + Fill(s["l1_text"], Values), ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())
        Embed, File = await StaringEmbed(interaction.client.db, interaction.guild.id, s, Values)
        Kwargs = {"file": File} if File else {}
        await interaction.followup.send("**Nivel 2:**", embed=Embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **Kwargs)

    @discord.ui.button(label="Restaurar textos", emoji="♻️", style=discord.ButtonStyle.red, row=3)
    async def Reset(self, interaction: discord.Interaction, _):
        await Save(interaction, {K: DEFAULTS[K] for K in ("l1_text", "l2_title", "l2_text")})
        await Open(interaction, "♻️ Textos restaurados.")


def Field(label, value, limit, long=False, required=True, placeholder=None):
    return discord.ui.TextInput(label=label[:45], default=str(value), max_length=limit, required=required, placeholder=placeholder,
                                style=discord.TextStyle.paragraph if long else discord.TextStyle.short)


def Pair(text: str, low: tuple, high: tuple) -> tuple[int, int]:
    A, B = (int(X.strip()) for X in text.split("/"))
    if not (low[0] <= A <= high[0] and low[1] <= B <= high[1]):
        raise ValueError
    return A, B


class LevelsModal(discord.ui.Modal, title="Niveles del anti-spam"):
    def __init__(self, s: dict):
        super().__init__()
        self.l1 = Field("Nivel 1: más de X mensajes / en Y segundos", f"{s['l1_count']}/{s['l1_seconds']}", 9, placeholder="6/10")
        self.l2 = Field("Nivel 2: X mensajes / en Y segundos", f"{s['l2_count']}/{s['l2_seconds']}", 9, placeholder="30/60")
        self.pause = Field("Nivel 2: minutos sin contar", s["pause_minutes"], 4)
        for F in (self.l1, self.l2, self.pause):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            L1 = Pair(self.l1.value, (2, 3), (100, 600))
            L2 = Pair(self.l2.value, (5, 10), (500, 3600))
            Pause = int(self.pause.value)
            if not 0 <= Pause <= 1440 or L2[0] <= L1[0]:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "❌ Formato `mensajes/segundos` (por ejemplo `6/10` y `30/60`); el nivel 2 tiene que pedir más mensajes que el 1.", ephemeral=True,
            )
        await Save(interaction, {"l1_count": L1[0], "l1_seconds": L1[1], "l2_count": L2[0], "l2_seconds": L2[1], "pause_minutes": Pause})
        await Open(interaction, "✅ Niveles guardados.")


class TextsModal(discord.ui.Modal, title="Textos del anti-spam"):
    def __init__(self, s: dict):
        super().__init__()
        self.l1 = Field("Nivel 1 ({user}, {nombre})", s["l1_text"], 500, long=True)
        self.title_ = Field("Nivel 2: título", s["l2_title"], 200)
        self.l2 = Field("Nivel 2: texto ({user}, {aviso}, {cantidad})", s["l2_text"], 1500, long=True)
        for F in (self.l1, self.title_, self.l2):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        await Save(interaction, {"l1_text": self.l1.value.strip(), "l2_title": self.title_.value.strip(), "l2_text": self.l2.value.strip()})
        await Open(interaction, "✅ Textos guardados. Pulsa **Probar** para verlos.")


class BannerModal(discord.ui.Modal, title="Banner del nivel 2"):
    def __init__(self, current: str):
        super().__init__()
        self.url = Field("Enlace de la imagen (vacío = sin banner)", current, 1000, required=False, placeholder="https://...")
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        Url = self.url.value.strip()
        Col = interaction.client.db["quota_spam_banner"]
        if not Url:
            await Col.delete_one({"_id": interaction.guild.id})
            await Save(interaction, {"banner_url": ""})
            return await Open(interaction, "🧹 Banner quitado.")
        if not Url.startswith(("http://", "https://")):
            return await interaction.response.send_message("❌ Tiene que ser un enlace `https://` a una imagen.", ephemeral=True)
        await interaction.response.defer()
        # Discord attachment links expire after a while: LOJI keeps its own copy of the image.
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as Session:
                async with Session.get(Url) as R:
                    Type = R.headers.get("content-type", "")
                    Data = await R.content.read(MAX_BANNER + 1)
                    if R.status != 200 or not Type.startswith("image/"):
                        raise ValueError(f"no es una imagen (HTTP {R.status})")
                    if len(Data) > MAX_BANNER:
                        raise ValueError("pesa más de 8 MB")
        except (aiohttp.ClientError, TimeoutError, ValueError) as e:
            await Save(interaction, {"banner_url": Url})
            return await Open(interaction, f"⚠️ No pude descargar la imagen ({e}). Guardé el enlace, pero si caduca, el banner dejará de verse.")
        Ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}.get(Type.split(";")[0], "png")
        await Col.update_one({"_id": interaction.guild.id}, {"$set": {"data": Binary(Data), "filename": f"loji.{Ext}", "url": Url}}, upsert=True)
        await Save(interaction, {"banner_url": Url})
        await Open(interaction, "✅ Banner guardado: LOJI tiene su propia copia, así que aunque el enlace caduque seguirá viéndose.")
