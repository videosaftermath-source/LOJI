"""/config → Comunidad: supporter welcome card, missions board and overflow chat."""

import discord

from core.community import MAX_BOARD_QUESTS, Store, ValidColor

LOJI_RED = discord.Color.from_rgb(150, 12, 18)
TIMEOUT = 600


class Owned(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=TIMEOUT)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Este panel no es tuyo.", ephemeral=True)
            return False
        return True


async def Show(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View, note: str | None = None):
    Edit = interaction.edit_original_response if interaction.response.is_done() else interaction.response.edit_message
    await Edit(content=note, embed=embed, view=view)


def Where(guild, value, kind="channel") -> str:
    Thing = guild.get_role(value or 0) if kind == "role" else guild.get_channel(value or 0)
    return Thing.mention if Thing else "*sin elegir*"


# ======================= main =======================


async def MainEmbed(guild: discord.Guild) -> discord.Embed:
    from cogs.Modules.Community.community import BoardQuests

    C = await Store().Get(guild.id)
    B, O = C["board"], C["overflow"]
    embed = discord.Embed(title="🌸 Comunidad", color=LOJI_RED)
    embed.description = "Sistemas para la comunidad. La tarjeta de supporters está en `/config` → **Vanity y tag**."
    Count = len(await BoardQuests(guild.id))
    embed.add_field(
        name="🪙 Tablero de misiones",
        value=(f"Publicado en {Where(guild, B['channel'])}" if B["message_id"] else "*Sin publicar*")
        + f" · {Count} misión{'es' if Count != 1 else ''}\n-# Las misiones con botón de reclamar, en un canal.",
        inline=False,
    )
    Boost = C["boost"]
    embed.add_field(
        name="💎 Boosts",
        value=("✅ Activado" if Boost["enabled"] else "⏸️ Desactivado") + f" · {Where(guild, Boost['channel'])}"
        + "\n-# Tarjeta de agradecimiento cuando alguien boostea.",
        inline=False,
    )
    from cogs.Modules.Community.icons import Panels

    Count_ = len(await Panels(guild.id))
    embed.add_field(
        name="🎨 Iconos boosters",
        value=f"{Count_} panel{'es' if Count_ != 1 else ''}\n-# Roles con icono que solo los boosters pueden ponerse (uno a la vez).",
        inline=False,
    )
    embed.add_field(
        name="💬 Chat extra (General 2)",
        value=(("🟢 Abierto ahora" if O["is_open"] else "✅ Activado") if O["enabled"] else "⏸️ Desactivado")
        + f" · {Where(guild, O['main'])} → {Where(guild, O['extra'])}\n-# Se abre cuando el chat principal está lleno y se cierra solo.",
        inline=False,
    )
    return embed


class MainPanel(Owned):
    @discord.ui.button(label="Tablero de misiones", emoji="🪙", style=discord.ButtonStyle.blurple)
    async def Board(self, interaction: discord.Interaction, _):
        await BoardPanel.Open(interaction, self.author)

    @discord.ui.button(label="Boosts", emoji="💎", style=discord.ButtonStyle.blurple)
    async def Boost(self, interaction: discord.Interaction, _):
        await BoostPanel.Open(interaction, self.author)

    @discord.ui.button(label="Iconos boosters", emoji="🎨", style=discord.ButtonStyle.blurple)
    async def Icons(self, interaction: discord.Interaction, _):
        from cogs.Modules.Community.icons_panel import IconsHome

        await IconsHome.Open(interaction, self.author)

    @discord.ui.button(label="Chat extra", emoji="💬", style=discord.ButtonStyle.blurple)
    async def Overflow(self, interaction: discord.Interaction, _):
        await OverflowPanel.Open(interaction, self.author)

    @classmethod
    async def Open(cls, interaction: discord.Interaction, author, note: str | None = None):
        await Show(interaction, await MainEmbed(interaction.guild), cls(author), note)


async def OpenPanel(interaction: discord.Interaction):
    """From /config (only the Tenno or admins)."""
    from core.mail.config import CanConfigure, Mail

    if not CanConfigure(interaction.user, await Mail().Get(interaction.guild.id)):
        return await interaction.followup.send("❌ Solo el Tenno (o un administrador) configura la comunidad.", ephemeral=True)
    await MainPanel.Open(interaction, interaction.user)


class Back(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=row)

    async def callback(self, interaction: discord.Interaction):
        await MainPanel.Open(interaction, self.view.author)


def Field(label, value, limit, long=True, required=False, placeholder=None):
    return discord.ui.TextInput(
        label=label[:45], default=value, max_length=limit, required=required, placeholder=placeholder,
        style=discord.TextStyle.paragraph if long else discord.TextStyle.short,
    )


# ======================= board =======================


async def BoardEmbed(guild) -> discord.Embed:
    from cogs.Modules.Community.community import BoardQuests

    B = (await Store().Get(guild.id))["board"]
    Quests = await BoardQuests(guild.id)
    embed = discord.Embed(title="🪙 Tablero de misiones", color=LOJI_RED)
    embed.description = (
        "Un mensaje fijo con las misiones activas y un botón **Reclamar** en cada una, más **Ver mi progreso**.\n"
        "Las misiones se crean en `/config` → Economía → Misiones; el tablero se actualiza solo al crearlas, pausarlas o borrarlas."
    )
    embed.add_field(name="Canal", value=Where(guild, B["channel"]) + (" · ✅ publicado" if B["message_id"] else " · *sin publicar*"), inline=True)
    embed.add_field(name="Misiones", value=f"{len(Quests)} (máximo {MAX_BOARD_QUESTS} en el tablero)", inline=True)
    embed.add_field(name="Título", value=B["title"][:1024], inline=False)
    embed.add_field(name="Banner", value=B["banner"] or "*sin banner*", inline=False)
    embed.set_footer(text="Nuevos objetivos: minutos en voz, llevar el tag o la vanity, boostear (estos dos, una vez por cuenta)")
    return embed


class BoardPanel(Owned):
    def __init__(self, author):
        super().__init__(author)
        Pick = discord.ui.ChannelSelect(placeholder="📍 Canal del tablero", channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=0)
        Pick.callback = self.PickChannel
        self.add_item(Pick)
        self.add_item(Back(row=2))

    @classmethod
    async def Open(cls, interaction, author, note=None):
        await Show(interaction, await BoardEmbed(interaction.guild), cls(author), note)

    async def PickChannel(self, interaction: discord.Interaction):
        Channel = int(interaction.data["values"][0])
        await Store().Set(interaction.guild.id, "board", {"channel": Channel})
        await BoardPanel.Open(interaction, self.author, "✅ Canal guardado. Pulsa **Publicar**.")

    @discord.ui.button(label="Publicar / actualizar", emoji="📤", style=discord.ButtonStyle.green, row=1)
    async def Publish(self, interaction: discord.Interaction, _):
        from cogs.Modules.Community.community import PublishBoard

        await interaction.response.defer()
        Result = await PublishBoard(interaction.guild)
        await BoardPanel.Open(interaction, self.author, Result)

    @discord.ui.button(label="Textos y banner", emoji="✏️", style=discord.ButtonStyle.blurple, row=1)
    async def Texts(self, interaction: discord.Interaction, _):
        B = (await Store().Get(interaction.guild.id))["board"]
        await interaction.response.send_modal(BoardTexts(self.author, B))

    @discord.ui.button(label="Vista previa", emoji="👁️", style=discord.ButtonStyle.grey, row=1)
    async def Preview(self, interaction: discord.Interaction, _):
        from cogs.Modules.Community.community import BoardView

        await interaction.response.send_message(view=await BoardView(interaction.guild), ephemeral=True)

    @discord.ui.button(label="Moneda y botones", emoji="🪙", style=discord.ButtonStyle.blurple, row=2)
    async def Coin(self, interaction: discord.Interaction, _):
        B = (await Store().Get(interaction.guild.id))["board"]
        await interaction.response.send_modal(BoardCoin(self.author, B))

    @discord.ui.button(label="Misiones de ejemplo", emoji="🪄", style=discord.ButtonStyle.grey, row=2)
    async def Examples(self, interaction: discord.Interaction, _):
        """Creates the default missions (25 messages, 15 min of voice, tag, boost) that aren't there yet."""
        from core.community import EXAMPLE_QUESTS
        from core.economy.registry import Eco
        from core.economy.service import EconomyError

        Existing = {Q["name"].lower() for Q in await Eco().quests.List(interaction.guild.id)}
        Made, Problem = [], None
        for Quest in EXAMPLE_QUESTS:
            if Quest["name"].lower() in Existing:
                continue
            try:
                await Eco().quests.Create(interaction.guild.id, {**Quest, "reward_item": None})
                Made.append(Quest["name"])
            except EconomyError as e:
                Problem = str(e)
                break
        if Made:
            interaction.client.dispatch("quests_changed", interaction.guild.id)
        Note = (f"🪄 Creadas: **{', '.join(Made)}**." if Made else "Las misiones de ejemplo ya existían.") + (f"\n❌ {Problem}" if Problem else "")
        await BoardPanel.Open(interaction, self.author, Note + "\n-# Puedes cambiarlas o borrarlas en `/config` → Economía → Misiones.")

    @discord.ui.button(label="Restaurar textos", emoji="♻️", style=discord.ButtonStyle.red, row=1)
    async def Reset(self, interaction: discord.Interaction, _):
        await Store().Reset(interaction.guild.id, "board", ["title", "description", "footer", "color", "banner", "coin", "claim_label", "progress_label"])
        await BoardPanel.Open(interaction, self.author, "♻️ Textos restaurados. Pulsa **Publicar** para aplicarlo.")


class BoardCoin(discord.ui.Modal, title="Moneda y botones"):
    def __init__(self, author, B):
        super().__init__()
        self.author = author
        self.coin = Field("Emoji de la moneda", B["coin"], 80, long=False, required=True, placeholder="<:moneda:123...>")
        self.claim = Field("Texto del botón de cada misión", B["claim_label"], 40, long=False, required=True)
        self.progress = Field("Texto del botón de progreso", B["progress_label"], 40, long=False, required=True)
        for F in (self.coin, self.claim, self.progress):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.Modules.Community.community import Emoji

        if not Emoji(self.coin.value):
            return await interaction.response.send_message("❌ Ese emoji no vale. Pega un emoji normal o uno del servidor (`<:nombre:id>`).", ephemeral=True)
        await Store().Set(interaction.guild.id, "board", {
            "coin": self.coin.value.strip(), "claim_label": self.claim.value.strip(), "progress_label": self.progress.value.strip(),
        })
        await BoardPanel.Open(interaction, self.author, "✅ Guardado. Pulsa **Publicar / actualizar** para aplicarlo al tablero.")


class BoardTexts(discord.ui.Modal, title="Tablero de misiones"):
    def __init__(self, author, B):
        super().__init__()
        self.author = author
        self.fields = {
            "title": Field("Título ({server})", B["title"], 200, long=False, required=True),
            "description": Field("Descripción", B["description"], 600),
            "footer": Field("Pie", B["footer"], 600),
            "banner": Field("Banner (enlace a una imagen)", B["banner"], 400, long=False, placeholder="https://..."),
            "color": Field("Color (hex)", B["color"], 7, long=False, required=True),
        }
        for F in self.fields.values():
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        Values = {K: F.value.strip() for K, F in self.fields.items()}
        if not ValidColor(Values["color"]):
            return await interaction.response.send_message("❌ El color va en hex, por ejemplo `#57F287`.", ephemeral=True)
        if Values["banner"] and not Values["banner"].startswith(("http://", "https://")):
            return await interaction.response.send_message("❌ El banner tiene que ser un enlace `https://` a una imagen.", ephemeral=True)
        Values["color"] = Values["color"] if Values["color"].startswith("#") else f"#{Values['color']}"
        await Store().Set(interaction.guild.id, "board", Values)
        await BoardPanel.Open(interaction, self.author, "✅ Guardado. Pulsa **Publicar / actualizar** para aplicarlo al tablero.")


# ======================= overflow =======================


def OverflowEmbed(guild, O: dict) -> discord.Embed:
    embed = discord.Embed(title="💬 Chat extra (General 2)", color=LOJI_RED)
    embed.description = (
        (("🟢 **Abierto ahora.**" if O["is_open"] else "✅ **Activado** (cerrado ahora).") if O["enabled"] else "⏸️ **Desactivado.**")
        + "\nCuando el chat principal se llena, el bot abre el chat extra y lo anuncia. Si el extra se queda tranquilo, "
        "avisa y lo cierra un minuto después (si alguien escribe, se cancela)."
    )
    embed.add_field(name="Chats", value=f"Principal: {Where(guild, O['main'])}\nExtra: {Where(guild, O['extra'])}", inline=True)
    embed.add_field(
        name="Quién escribe", value=f"{Where(guild, O['role'], 'role') if O['role'] else '@everyone'}\n"
        + ("Cerrado = **oculto**" if O["mode"] == "hide" else "Cerrado = **visible, solo lectura**"),
        inline=True,
    )
    embed.add_field(
        name="Umbrales",
        value=f"> Abre: **{O['open_messages']}** mensajes en **{O['open_seconds']} s** de al menos **{O['open_authors']}** personas\n"
        f"> Cierra: menos de **{O['close_below']}** mensajes en **{O['idle_minutes']} min** (mínimo **{O['min_open_minutes']} min** abierto)",
        inline=False,
    )
    Lines = [("🟢", "text_open"), ("⏳", "text_warn"), ("🔒", "text_close"), ("📢", "text_main")]
    embed.add_field(name="Mensajes", value="\n".join(f"{E} {O[K].splitlines()[0] if O[K] else '*no se envía*'}" for E, K in Lines)[:1024], inline=False)
    embed.set_footer(text="El bot necesita Gestionar canales/permisos en el chat extra")
    return embed


class OverflowPanel(Owned):
    def __init__(self, author, O: dict):
        super().__init__(author)
        for Key, Placeholder, Row in (("main", "💬 Chat principal (el que se llena)", 0), ("extra", "➕ Chat extra (el que se abre)", 1)):
            Pick = discord.ui.ChannelSelect(placeholder=Placeholder, channel_types=[discord.ChannelType.text], row=Row)
            Pick.callback = self.Saver(Key)
            self.add_item(Pick)
        Role = discord.ui.RoleSelect(placeholder="🎭 Quién escribe al abrir (vacío = @everyone)", min_values=0, row=2)
        Role.callback = self.SaveRole
        self.add_item(Role)
        self.Toggle.label = "Desactivar" if O["enabled"] else "Activar"
        self.Force.label = "Cerrar ya" if O["is_open"] else "Abrir ya"
        self.Force.emoji = "🔒" if O["is_open"] else "🔓"
        self.add_item(Back(row=3))

    @classmethod
    async def Open(cls, interaction, author, note=None):
        O = (await Store().Get(interaction.guild.id))["overflow"]
        await Show(interaction, OverflowEmbed(interaction.guild, O), cls(author, O), note)

    def Saver(self, key):
        async def Save(interaction: discord.Interaction):
            await Store().Set(interaction.guild.id, "overflow", {key: int(interaction.data["values"][0])})
            await OverflowPanel.Open(interaction, self.author, "✅ Guardado.")
        return Save

    async def SaveRole(self, interaction: discord.Interaction):
        Values = interaction.data.get("values") or []
        await Store().Set(interaction.guild.id, "overflow", {"role": int(Values[0]) if Values else None})
        await OverflowPanel.Open(interaction, self.author, "✅ Guardado.")

    @discord.ui.button(label="Activar", emoji="⏯️", style=discord.ButtonStyle.green, row=3)
    async def Toggle(self, interaction: discord.Interaction, _):
        O = (await Store().Get(interaction.guild.id))["overflow"]
        if not O["enabled"]:
            Problem = Check(interaction.guild, O)
            if Problem:
                return await OverflowPanel.Open(interaction, self.author, f"❌ {Problem}")
        await Store().Set(interaction.guild.id, "overflow", {"enabled": not O["enabled"]})
        Cog = interaction.client.get_cog("Community")
        if not O["enabled"] and not O["is_open"] and Cog:
            try:  # start closed: read-only (or hidden) until the main chat fills up
                await Cog.SetAccess(interaction.guild, O, False)
            except discord.HTTPException as e:
                return await OverflowPanel.Open(interaction, self.author, f"⚠️ Activado, pero no pude cerrar el chat extra: {e.text or e}")
        await OverflowPanel.Open(interaction, self.author, "✅ Activado." if not O["enabled"] else "⏸️ Desactivado (si estaba abierto, sigue abierto: ciérralo con **Cerrar ya**).")

    @discord.ui.button(label="Umbrales", emoji="⚙️", style=discord.ButtonStyle.blurple, row=3)
    async def Limits(self, interaction: discord.Interaction, _):
        O = (await Store().Get(interaction.guild.id))["overflow"]
        await interaction.response.send_modal(OverflowLimits(self.author, O))

    @discord.ui.button(label="Mensajes", emoji="✏️", style=discord.ButtonStyle.blurple, row=3)
    async def Texts(self, interaction: discord.Interaction, _):
        O = (await Store().Get(interaction.guild.id))["overflow"]
        await interaction.response.send_modal(OverflowTexts(self.author, O))

    @discord.ui.button(label="Abrir ya", emoji="🔓", style=discord.ButtonStyle.grey, row=3)
    async def Force(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Cog = interaction.client.get_cog("Community")
        O = (await Store().Get(interaction.guild.id))["overflow"]
        Problem = Check(interaction.guild, O)
        if Problem or not Cog:
            return await OverflowPanel.Open(interaction, self.author, f"❌ {Problem or 'El módulo no está cargado.'}")
        async with Cog.Lock(interaction.guild.id):
            O = (await Store().Get(interaction.guild.id))["overflow"]
            if O["is_open"]:
                await Cog.Close(interaction.guild, O)
            else:
                await Cog.Open(interaction.guild, O)
        await OverflowPanel.Open(interaction, self.author, "🔒 Cerrado." if O["is_open"] else "🔓 Abierto.")


def Check(guild: discord.Guild, O: dict) -> str | None:
    Main, Extra = guild.get_channel(O["main"] or 0), guild.get_channel(O["extra"] or 0)
    if not Main or not Extra:
        return "Elige primero el chat principal y el chat extra."
    if Main.id == Extra.id:
        return "El chat principal y el extra tienen que ser distintos."
    Perms = Extra.permissions_for(guild.me)
    if not (Perms.manage_channels or Perms.manage_roles) or not Perms.send_messages:
        return f"Al bot le falta **Gestionar canales** (o permisos) y **Enviar mensajes** en {Extra.mention}."
    return None


def Number(text: str, low: int, high: int) -> int:
    Value = int(text.strip())
    if not low <= Value <= high:
        raise ValueError
    return Value


class OverflowLimits(discord.ui.Modal, title="Umbrales del chat extra"):
    def __init__(self, author, O):
        super().__init__()
        self.author = author
        self.open = Field("Abrir: mensajes / segundos", f"{O['open_messages']}/{O['open_seconds']}", 9, long=False, required=True, placeholder="30/60")
        self.authors = Field("Abrir: personas distintas mínimas", str(O["open_authors"]), 3, long=False, required=True)
        self.close = Field("Cerrar: menos de X mensajes / en Y minutos", f"{O['close_below']}/{O['idle_minutes']}", 9, long=False, required=True, placeholder="5/10")
        self.minimum = Field("Minutos mínimos abierto", str(O["min_open_minutes"]), 4, long=False, required=True)
        self.mode = Field("Cerrado: 'lectura' (visible) u 'oculto'", "oculto" if O["mode"] == "hide" else "lectura", 10, long=False, required=True)
        for F in (self.open, self.authors, self.close, self.minimum, self.mode):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Messages, Seconds = self.open.value.split("/")
            Below, Minutes = self.close.value.split("/")
            Mode = {"lectura": "lock", "oculto": "hide"}[self.mode.value.strip().lower()]
            Changes = {
                "open_messages": Number(Messages, 3, 500), "open_seconds": Number(Seconds, 10, 3600),
                "open_authors": Number(self.authors.value, 1, 100),
                "close_below": Number(Below, 1, 500), "idle_minutes": Number(Minutes, 1, 240),
                "min_open_minutes": Number(self.minimum.value, 1, 1440), "mode": Mode,
            }
        except (ValueError, KeyError):
            return await interaction.response.send_message(
                "❌ Revisa el formato: `30/60`, `4`, `5/10`, `15` y `lectura` u `oculto`.", ephemeral=True,
            )
        await Store().Set(interaction.guild.id, "overflow", Changes)
        await OverflowPanel.Open(interaction, self.author, "✅ Umbrales guardados.")


class OverflowTexts(discord.ui.Modal, title="Mensajes del chat extra"):
    def __init__(self, author, O):
        super().__init__()
        self.author = author
        self.fields = {
            "text_open": Field("Al abrir (1.ª línea = título)", O["text_open"], 600, required=True),
            "text_warn": Field("Aviso antes de cerrar", O["text_warn"], 600, required=True),
            "text_close": Field("Al cerrar", O["text_close"], 600, required=True),
            "text_main": Field("Aviso en el principal (vacío = no)", O["text_main"], 600),
        }
        for F in self.fields.values():
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        Values = {K: F.value.strip() for K, F in self.fields.items()}
        Values["notice_main"] = bool(Values["text_main"])
        await Store().Set(interaction.guild.id, "overflow", Values)
        await OverflowPanel.Open(
            interaction, self.author, "✅ Mensajes guardados. Variables: `{principal}` `{extra}` `{server}`.",
        )


# ======================= boost card =======================


def BoostEmbed(guild, B: dict) -> discord.Embed:
    from core.community import BOOST_VARS, ParseButtons

    embed = discord.Embed(title="💎 Tarjeta de boost", color=LOJI_RED)
    embed.description = (
        ("✅ **Activada.**" if B["enabled"] else "⏸️ **Desactivada.**")
        + " Cuando alguien boostea, LOJI publica la tarjeta en el canal elegido (una vez por boost).\n"
        "Las ventajas por defecto son las de la **economía** (`/config` → Economía → Boosters): si las cambias allí, la tarjeta se actualiza sola.\n"
        "Pulsa **Vista previa** para verla contigo."
    )
    embed.add_field(name="Canal", value=Where(guild, B["channel"]), inline=True)
    embed.add_field(
        name="Modo", value=f"📄 **JSON** (`{B.get('json_name') or 'archivo'}`)" if B.get("json") else "🧩 Diseño sencillo", inline=True,
    )
    if B.get("json"):
        embed.add_field(
            name="📄 Modo JSON activo",
            value="Se publica tu JSON (con las variables rellenadas). Los textos, aspecto y botones de abajo no se usan "
            "hasta que pulses **Quitar JSON**.",
            inline=False,
        )
    embed.add_field(name="Aspecto", value=f"Color `{B['color']}` · Imagen: `{B['thumbnail']}`", inline=True)
    embed.add_field(name="Título", value=B["title"][:1024], inline=False)
    embed.add_field(name="Ventajas", value=B["benefits"][:1024] or "—", inline=False)
    Buttons = ParseButtons(B["buttons"])
    embed.add_field(
        name="Botones",
        value="\n".join(f"{X['emoji'] or ''} {X['label']} → {X['target'] or '*sin destino: no se muestra*'}" for X in Buttons)[:1024] or "—",
        inline=False,
    )
    embed.add_field(name="Variables", value=BOOST_VARS + "\n-# Una línea con una variable vacía no se muestra (p. ej. `{premio}` si no hay premio).", inline=False)
    return embed


class BoostPanel(Owned):
    def __init__(self, author, B: dict):
        super().__init__(author)
        Pick = discord.ui.ChannelSelect(placeholder="📍 Canal donde se anuncia", channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=0)
        Pick.callback = self.PickChannel
        self.add_item(Pick)
        self.Toggle.label = "Desactivar" if B["enabled"] else "Activar"
        self.add_item(Back(row=2))

    @classmethod
    async def Open(cls, interaction, author, note=None):
        B = (await Store().Get(interaction.guild.id))["boost"]
        await Show(interaction, BoostEmbed(interaction.guild, B), cls(author, B), note)

    async def PickChannel(self, interaction: discord.Interaction):
        await Store().Set(interaction.guild.id, "boost", {"channel": int(interaction.data["values"][0])})
        await BoostPanel.Open(interaction, self.author, "✅ Canal guardado.")

    @discord.ui.button(label="Activar", emoji="⏯️", style=discord.ButtonStyle.green, row=1)
    async def Toggle(self, interaction: discord.Interaction, _):
        B = (await Store().Get(interaction.guild.id))["boost"]
        if not B["enabled"] and not interaction.guild.get_channel(B["channel"] or 0):
            return await BoostPanel.Open(interaction, self.author, "❌ Elige primero el canal.")
        await Store().Set(interaction.guild.id, "boost", {"enabled": not B["enabled"]})
        await BoostPanel.Open(interaction, self.author, "✅ Activada." if not B["enabled"] else "⏸️ Desactivada.")

    @discord.ui.button(label="Textos", emoji="✏️", style=discord.ButtonStyle.blurple, row=1)
    async def Texts(self, interaction: discord.Interaction, _):
        B = (await Store().Get(interaction.guild.id))["boost"]
        await interaction.response.send_modal(BoostTexts(self.author, B))

    @discord.ui.button(label="Aspecto y botones", emoji="🎨", style=discord.ButtonStyle.blurple, row=1)
    async def Look(self, interaction: discord.Interaction, _):
        B = (await Store().Get(interaction.guild.id))["boost"]
        await interaction.response.send_modal(CardLook(self.author, B, "boost", BoostPanel))

    @discord.ui.button(label="Subir JSON", emoji="📄", style=discord.ButtonStyle.blurple, row=2)
    async def UploadJson(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BoostJsonModal(self.author))

    @discord.ui.button(label="Quitar JSON", emoji="🧹", style=discord.ButtonStyle.grey, row=2)
    async def ClearJson(self, interaction: discord.Interaction, _):
        await Store().Set(interaction.guild.id, "boost", {"json": "", "json_name": ""})
        await BoostPanel.Open(interaction, self.author, "🧹 JSON quitado: vuelve el diseño sencillo.")

    @discord.ui.button(label="Vista previa", emoji="👁️", style=discord.ButtonStyle.grey, row=1)
    async def Preview(self, interaction: discord.Interaction, _):
        from cogs.Modules.Community.community import BoostCard, BoostJson, SendJson

        B = (await Store().Get(interaction.guild.id))["boost"]
        if B.get("json"):
            await interaction.response.defer(ephemeral=True, thinking=False)
            try:
                await SendJson(interaction.client.http, 0, await BoostJson(interaction.user), ephemeral_token=(interaction.application_id, interaction.token))
            except (ValueError, discord.HTTPException) as e:
                await interaction.followup.send(f"❌ El JSON no se puede mostrar: {getattr(e, 'text', None) or e}", ephemeral=True)
            return
        await interaction.response.send_message(
            view=await BoostCard(interaction.user, "-# Vista previa (como si acabaras de boostear)"), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Restaurar", emoji="♻️", style=discord.ButtonStyle.red, row=1)
    async def Reset(self, interaction: discord.Interaction, _):
        from core.community import BOOST

        await Store().Reset(interaction.guild.id, "boost", [K for K in BOOST if K not in ("enabled", "channel")])
        await BoostPanel.Open(interaction, self.author, "♻️ Textos y aspecto restaurados.")


class BoostJsonModal(discord.ui.Modal, title="Tarjeta de boost en JSON"):
    def __init__(self, author):
        super().__init__()
        self.author = author
        self.file = discord.ui.FileUpload(min_values=1, max_values=1)
        self.add_item(discord.ui.Label(
            text="Archivo .json (Components V2)",
            description="Puedes usar {user}, {fecha}, {server}, {premio}... Solo botones de enlace.",
            component=self.file,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.Modules.Community.community import BoostValues, SendJson
        from core.community import FillJson, ParseCardJson
        from core.economy.config import EcoConfig

        File = (self.file.values or [None])[0]
        if not File or not File.filename.lower().endswith((".json", ".txt")):
            return await interaction.response.send_message("❌ Sube un archivo `.json`.", ephemeral=True)
        await interaction.response.defer()
        try:
            Text = (await File.read()).decode("utf-8-sig")
            Components = ParseCardJson(Text)
        except UnicodeDecodeError:
            return await interaction.followup.send("❌ El archivo no está en UTF-8.", ephemeral=True)
        except ValueError as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)
        # Discord is the real judge: only saved if the preview goes through.
        C = await Store().Get(interaction.guild.id)
        Values = BoostValues(interaction.user, await EcoConfig().Get(interaction.guild.id), C["board"])
        try:
            await SendJson(interaction.client.http, 0, FillJson(Components, Values), ephemeral_token=(interaction.application_id, interaction.token))
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ Discord no acepta ese JSON: {e.text or e}\nNo se ha guardado nada.", ephemeral=True)
        await Store().Set(interaction.guild.id, "boost", {"json": Text, "json_name": File.filename[:80]})
        await BoostPanel.Open(interaction, self.author, "✅ JSON guardado (la vista previa está abajo). Desde ahora la tarjeta usa tu diseño.")


class BoostTexts(discord.ui.Modal, title="Textos de la tarjeta de boost"):
    def __init__(self, author, B):
        super().__init__()
        self.author = author
        self.fields = {
            "title": Field("Título", B["title"], 200, long=False, required=True),
            "intro": Field("Línea bajo el título ({fecha}...)", B["intro"], 400),
            "benefits": Field("Ventajas (una por línea)", B["benefits"], 1500),
            "footer": Field("Pie (bajo la línea)", B["footer"], 600),
        }
        for F in self.fields.values():
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        await Store().Set(interaction.guild.id, "boost", {K: F.value.strip() for K, F in self.fields.items()})
        await BoostPanel.Open(interaction, self.author, "✅ Textos guardados. Mira la **Vista previa**.")


class CardLook(discord.ui.Modal, title="Color, imagen y botones"):
    """Shared by the cards in Comunidad: saves color, image and link buttons of one section."""

    def __init__(self, author, card: dict, section: str, panel):
        super().__init__()
        self.author, self.section, self.panel = author, section, panel
        self.color = Field("Color (hex)", card["color"], 7, long=False, required=True, placeholder="#F47FFF")
        self.thumbnail = Field("Imagen: avatar, servidor, ninguna o un enlace", card["thumbnail"], 400, long=False, required=True)
        self.buttons = Field("Botones: Etiqueta | emoji | #canal o enlace", card["buttons"], 600, placeholder="Roles especiales | ✨ | #booster-roles")
        for F in (self.color, self.thumbnail, self.buttons):
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.Modules.Supporters.supporters import ResolveChannel
        from core.community import ButtonUrl, ParseButtons

        Color, Thumb = self.color.value.strip(), self.thumbnail.value.strip()
        if not ValidColor(Color):
            return await interaction.response.send_message("❌ El color va en hex, por ejemplo `#F47FFF`.", ephemeral=True)
        if Thumb not in ("avatar", "servidor", "ninguna") and not Thumb.startswith(("http://", "https://")):
            return await interaction.response.send_message("❌ Imagen: `avatar`, `servidor`, `ninguna` o un enlace a una imagen.", ephemeral=True)
        Lines = []
        for Line in self.buttons.value.strip().splitlines():
            Parts = [P.strip() for P in Line.split("|")]
            if len(Parts) >= 3 and Parts[2]:
                Parts[2] = ResolveChannel(interaction.guild, Parts[2])
            Lines.append(" | ".join(Parts))
        Buttons = "\n".join(Lines)
        Bad = [B["label"] for B in ParseButtons(Buttons) if B["target"] and "{" not in B["target"] and not ButtonUrl(B["target"], interaction.guild.id)]
        if Bad:
            return await interaction.response.send_message(
                f"❌ No entiendo el destino de: **{', '.join(Bad)}**. Usa `#nombre-del-canal`, el ID del canal o un enlace `https://`.", ephemeral=True,
            )
        await Store().Set(interaction.guild.id, self.section, {"color": Color if Color.startswith("#") else f"#{Color}", "thumbnail": Thumb, "buttons": Buttons})
        await self.panel.Open(interaction, self.author, "✅ Guardado. Mira la **Vista previa**.")
