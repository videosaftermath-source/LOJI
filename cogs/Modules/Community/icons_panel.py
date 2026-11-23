"""/config → Comunidad → Paneles de iconos: create, edit, publish and delete booster icon panels."""

from datetime import datetime, timezone

import discord

from cogs.Modules.Community.icons import CheckEmoji, Db, Panel, Panels, PanelView, Publish, RefreshAll, SavePanel
from cogs.Modules.Community.panel import Back, Field, Owned, Show, Where
from core.community import ICON_PANELS, MAX_ICONS, PANEL_DEFAULTS, Store, ValidColor

LOJI_RED = discord.Color.from_rgb(150, 12, 18)


# ---------------- list ----------------


async def HomeEmbed(guild: discord.Guild) -> discord.Embed:
    All = await Panels(guild.id)
    S = (await Store().Get(guild.id))["icons"]
    embed = discord.Embed(title="🎨 Paneles de iconos para boosters", color=LOJI_RED)
    embed.description = (
        "Cada panel tiene de 1 a 5 iconos (rol + emoji) con su botón. Solo quien **boostea** puede ponérselos, "
        "**uno a la vez** entre todos los paneles; pulsar el que lleva lo quita. Al dejar de boostear, LOJI se lo quita y le avisa por MD.\n"
        "-# El booster se reconoce por el rol automático de Discord; LOJI lo revisa cada hora por si Discord falla."
    )
    Lines = []
    for I, P in enumerate(All, 1):
        Where_ = f"<#{P['channel']}>" if P.get("message_id") else "*sin publicar*"
        Lines.append(f"**{I}. {P['name']}** · {len(P.get('items') or [])}/{MAX_ICONS} iconos · {Where_}")
    embed.add_field(name=f"Paneles ({len(All)})", value="\n".join(Lines)[:1024] or "Ninguno todavía: pulsa **➕ Nuevo panel**.", inline=False)
    embed.add_field(name="Título de la sección", value=f"`{S['heading']}`", inline=True)
    embed.add_field(name="Registro", value=Where(guild, S["log"]) if S["log"] else "*desactivado*", inline=True)
    return embed


class IconsHome(Owned):
    def __init__(self, author, panels: list[dict]):
        super().__init__(author)
        if panels:
            Pick = discord.ui.Select(
                placeholder="✏️ Editar un panel",
                options=[discord.SelectOption(label=f"{I}. {P['name']}"[:100], value=P["panel_id"]) for I, P in enumerate(panels[:25], 1)],
                row=0,
            )
            Pick.callback = self.Pick
            self.add_item(Pick)
        self.add_item(Back(row=2))

    @classmethod
    async def Open(cls, interaction, author, note=None):
        await Show(interaction, await HomeEmbed(interaction.guild), cls(author, await Panels(interaction.guild.id)), note)

    async def Pick(self, interaction: discord.Interaction):
        await PanelEditor.Open(interaction, self.author, interaction.data["values"][0])

    @discord.ui.button(label="Nuevo panel", emoji="➕", style=discord.ButtonStyle.green, row=1)
    async def New(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(PanelTexts(self.author, None))

    @discord.ui.button(label="Ajustes", emoji="⚙️", style=discord.ButtonStyle.blurple, row=1)
    async def Settings(self, interaction: discord.Interaction, _):
        await IconSettings.Open(interaction, self.author)

    @discord.ui.button(label="Actualizar todos", emoji="🔄", style=discord.ButtonStyle.grey, row=1)
    async def Refresh(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        Problems = await RefreshAll(interaction.guild)
        await IconsHome.Open(interaction, self.author, "🔄 Paneles actualizados." + ("\n" + "\n".join(Problems) if Problems else ""))


# ---------------- settings ----------------


class IconSettings(Owned):
    def __init__(self, author):
        super().__init__(author)
        Log = discord.ui.ChannelSelect(placeholder="📒 Canal de registro (quién se pone o quita iconos)", channel_types=[discord.ChannelType.text], row=0)
        Log.callback = self.PickLog
        self.add_item(Log)

    @classmethod
    async def Open(cls, interaction, author, note=None):
        await Show(interaction, await HomeEmbed(interaction.guild), cls(author), note or "⚙️ **Ajustes de los paneles de iconos**")

    async def PickLog(self, interaction: discord.Interaction):
        await Store().Set(interaction.guild.id, "icons", {"log": int(interaction.data["values"][0])})
        await IconSettings.Open(interaction, self.author, "✅ Registro activado.")

    @discord.ui.button(label="Sin registro", emoji="🧹", style=discord.ButtonStyle.grey, row=1)
    async def NoLog(self, interaction: discord.Interaction, _):
        await Store().Set(interaction.guild.id, "icons", {"log": None})
        await IconSettings.Open(interaction, self.author, "🧹 Registro desactivado.")

    @discord.ui.button(label="Título de la sección", emoji="✏️", style=discord.ButtonStyle.blurple, row=1)
    async def Heading(self, interaction: discord.Interaction, _):
        S = (await Store().Get(interaction.guild.id))["icons"]
        await interaction.response.send_modal(HeadingModal(self.author, S["heading"]))

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back_(self, interaction: discord.Interaction, _):
        await IconsHome.Open(interaction, self.author)


class HeadingModal(discord.ui.Modal, title="Título de la sección de iconos"):
    def __init__(self, author, current):
        super().__init__()
        self.author = author
        self.value = Field("Título ({n} = número, {total} = paneles)", current, 100, long=False, required=True)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        await Store().Set(interaction.guild.id, "icons", {"heading": self.value.value.strip()})
        await interaction.response.defer()
        await RefreshAll(interaction.guild)
        await IconSettings.Open(interaction, self.author, "✅ Título guardado y paneles actualizados.")


# ---------------- one panel ----------------


async def EditorEmbed(guild: discord.Guild, panel: dict) -> discord.Embed:
    P = {**PANEL_DEFAULTS, **panel}
    embed = discord.Embed(title=f"🎨 {P['name']}", color=LOJI_RED)
    embed.description = (
        "1️⃣ **Textos** (banner, texto, aclaración, color) · 2️⃣ elige los **roles** en el menú · 3️⃣ pon sus **emojis** · "
        "4️⃣ elige el **canal** y se publica. Si cambias algo después, pulsa **Publicar / actualizar** y se edita el mismo mensaje."
    )
    Items = P.get("items") or []
    embed.add_field(
        name=f"Iconos ({len(Items)}/{MAX_ICONS})",
        value="\n".join(f"{I['emoji']} <@&{I['role']}>" for I in Items) or "*Ninguno: elige los roles en el menú.*",
        inline=False,
    )
    embed.add_field(name="Canal", value=(f"<#{P['channel']}>" + (" · ✅ publicado" if P.get("message_id") else "")) if P.get("channel") else "*sin elegir*", inline=True)
    embed.add_field(name="Color", value=f"`{P['color']}`", inline=True)
    embed.add_field(name="Banner", value=P["banner"] or "*sin banner*", inline=False)
    return embed


class PanelEditor(Owned):
    def __init__(self, author, panel: dict):
        super().__init__(author)
        self.panel_id = panel["panel_id"]
        Roles = discord.ui.RoleSelect(placeholder=f"🎭 Roles de los iconos (1 a {MAX_ICONS}, en orden)", min_values=1, max_values=MAX_ICONS, row=0)
        Roles.callback = self.PickRoles
        self.add_item(Roles)
        Channel = discord.ui.ChannelSelect(placeholder="📍 Canal donde se publica", channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=1)
        Channel.callback = self.PickChannel
        self.add_item(Channel)
        self.Emojis.disabled = not panel.get("items")

    @classmethod
    async def Open(cls, interaction, author, panel_id: str, note=None):
        P = await Panel(interaction.guild.id, panel_id)
        if not P:
            return await IconsHome.Open(interaction, author, "❌ Ese panel ya no existe.")
        await Show(interaction, await EditorEmbed(interaction.guild, P), cls(author, P), note)

    async def PickRoles(self, interaction: discord.Interaction):
        Guild, Me = interaction.guild, interaction.guild.me
        Roles = [Guild.get_role(int(V)) for V in interaction.data["values"]]
        Problems = [
            f"{R.mention}: " + ("es un rol automático" if R.managed or R.is_default() else "está por encima del rol de LOJI")
            for R in Roles if R and (R.managed or R.is_default() or R >= Me.top_role)
        ]
        if Problems:
            return await interaction.response.send_message("❌ No puedo usar:\n" + "\n".join(Problems), ephemeral=True)
        Others = {I["role"]: P["name"] for P in await Panels(Guild.id) if P["panel_id"] != self.panel_id for I in P.get("items", [])}
        Taken = [f"{R.mention} (ya está en **{Others[R.id]}**)" for R in Roles if R and R.id in Others]
        if Taken:
            return await interaction.response.send_message("❌ Cada rol solo puede estar en un panel:\n" + "\n".join(Taken), ephemeral=True)
        P = await Panel(Guild.id, self.panel_id)
        Current = {I["role"]: I["emoji"] for I in P.get("items") or []}
        await interaction.response.send_modal(EmojiModal(self.author, self.panel_id, [R for R in Roles if R], Current))

    async def PickChannel(self, interaction: discord.Interaction):
        await interaction.response.defer()
        Channel = interaction.guild.get_channel(int(interaction.data["values"][0]))
        P = await Panel(interaction.guild.id, self.panel_id)
        if not P.get("items"):
            await SavePanel(interaction.guild.id, self.panel_id, {"channel": Channel.id})
            return await PanelEditor.Open(interaction, self.author, self.panel_id, "✅ Canal guardado. Pon los iconos y pulsa **Publicar**.")
        Result = await Publish(interaction.guild, P, Channel)
        if Result.startswith("✅") and not P.get("message_id"):
            await RefreshAll(interaction.guild)  # the others now say 1/N with the new total
        await PanelEditor.Open(interaction, self.author, self.panel_id, Result)

    @discord.ui.button(label="Textos", emoji="✏️", style=discord.ButtonStyle.blurple, row=2)
    async def Texts(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(PanelTexts(self.author, await Panel(interaction.guild.id, self.panel_id)))

    @discord.ui.button(label="Emojis", emoji="😀", style=discord.ButtonStyle.blurple, row=2)
    async def Emojis(self, interaction: discord.Interaction, _):
        P = await Panel(interaction.guild.id, self.panel_id)
        Roles = [R for R in (interaction.guild.get_role(I["role"]) for I in P.get("items") or []) if R]
        await interaction.response.send_modal(EmojiModal(self.author, self.panel_id, Roles, {I["role"]: I["emoji"] for I in P["items"]}))

    @discord.ui.button(label="Vista previa", emoji="👁️", style=discord.ButtonStyle.grey, row=2)
    async def Preview(self, interaction: discord.Interaction, _):
        All = await Panels(interaction.guild.id)
        P = next(X for X in All if X["panel_id"] == self.panel_id)
        Number = [X["panel_id"] for X in All].index(self.panel_id) + 1
        Heading = (await Store().Get(interaction.guild.id))["icons"]["heading"]
        await interaction.response.send_message(
            view=PanelView(interaction.guild, P, Number, len(All), Heading), ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Publicar / actualizar", emoji="📤", style=discord.ButtonStyle.green, row=3)
    async def Publish_(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        P = await Panel(interaction.guild.id, self.panel_id)
        Result = await Publish(interaction.guild, P)
        await PanelEditor.Open(interaction, self.author, self.panel_id, Result)

    @discord.ui.button(label="Borrar", emoji="🗑️", style=discord.ButtonStyle.red, row=3)
    async def Delete(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            content="⚠️ **¿Borrar este panel?** Se borra el mensaje publicado. Quien lleve uno de sus iconos **lo conserva** hasta que se lo quite.",
            embed=None, view=ConfirmDelete(self.author, self.panel_id),
        )

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=3)
    async def Back_(self, interaction: discord.Interaction, _):
        await IconsHome.Open(interaction, self.author)


class ConfirmDelete(Owned):
    def __init__(self, author, panel_id):
        super().__init__(author)
        self.panel_id = panel_id

    @discord.ui.button(label="Sí, borrar", emoji="🗑️", style=discord.ButtonStyle.red)
    async def Yes(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        P = await Panel(interaction.guild.id, self.panel_id)
        if P and P.get("message_id"):
            Channel = interaction.guild.get_channel(P.get("channel") or 0)
            if Channel:
                try:
                    await Channel.get_partial_message(P["message_id"]).delete()
                except discord.HTTPException:
                    pass
        await Db()[ICON_PANELS].delete_one({"guild_id": interaction.guild.id, "panel_id": self.panel_id})
        await RefreshAll(interaction.guild)
        await IconsHome.Open(interaction, self.author, f"🗑️ Panel **{(P or {}).get('name', '')}** borrado.")

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.grey)
    async def No(self, interaction: discord.Interaction, _):
        await PanelEditor.Open(interaction, self.author, self.panel_id)


class PanelTexts(discord.ui.Modal):
    def __init__(self, author, panel: dict | None):
        super().__init__(title="Nuevo panel de iconos" if panel is None else "Textos del panel")
        self.author, self.panel = author, panel
        P = {**PANEL_DEFAULTS, "name": "", **(panel or {})}
        self.fields = {
            "name": Field("Nombre (solo lo ves tú)", P["name"], 60, long=False, required=True, placeholder="Iconos Pokémon"),
            "banner": Field("Banner (enlace a imagen, vacío = sin banner)", P["banner"], 400, long=False, placeholder="https://..."),
            "text": Field("Texto ({booster} = rol de booster)", P["text"], 1500, required=True),
            "footer": Field("Aclaración de abajo", P["footer"], 600),
            "color": Field("Color de la línea (hex)", P["color"], 7, long=False, required=True),
        }
        for F in self.fields.values():
            self.add_item(F)

    async def on_submit(self, interaction: discord.Interaction):
        from core.economy.shop import NewId

        Values = {K: F.value.strip() for K, F in self.fields.items()}
        if not ValidColor(Values["color"]):
            return await interaction.response.send_message("❌ El color va en hex, por ejemplo `#C9C9D1`.", ephemeral=True)
        if Values["banner"] and not Values["banner"].startswith(("http://", "https://")):
            return await interaction.response.send_message("❌ El banner tiene que ser un enlace `https://` a una imagen.", ephemeral=True)
        Values["color"] = Values["color"] if Values["color"].startswith("#") else f"#{Values['color']}"
        if self.panel is None:
            PanelId = NewId(8)
            await Db()[ICON_PANELS].insert_one({
                "guild_id": interaction.guild.id, "panel_id": PanelId, "items": [], "channel": None, "message_id": None,
                "created_at": datetime.now(timezone.utc), **Values,
            })
            return await PanelEditor.Open(interaction, self.author, PanelId, "✅ Panel creado. Ahora elige los **roles** en el menú.")
        await SavePanel(interaction.guild.id, self.panel["panel_id"], Values)
        await PanelEditor.Open(interaction, self.author, self.panel["panel_id"], "✅ Guardado. Pulsa **Publicar / actualizar** para aplicarlo.")


class EmojiModal(discord.ui.Modal, title="Emojis de los iconos"):
    def __init__(self, author, panel_id: str, roles: list, current: dict):
        super().__init__()
        self.author, self.panel_id, self.roles = author, panel_id, roles[:MAX_ICONS]
        self.inputs = []
        for R in self.roles:
            Input = Field(f"Emoji de {R.name}"[:45], current.get(R.id, ""), 80, long=False, required=True, placeholder="<:nombre:id> o 🌟")
            self.inputs.append(Input)
            self.add_item(Input)

    async def on_submit(self, interaction: discord.Interaction):
        Items, Problems = [], []
        for R, Input in zip(self.roles, self.inputs):
            Emoji, Problem = CheckEmoji(interaction.client, Input.value)
            if Problem:
                Problems.append(f"**{R.name}**: {Problem}")
            else:
                Items.append({"role": R.id, "emoji": str(Emoji)})
        if Problems:
            return await interaction.response.send_message(
                "❌ " + "\n❌ ".join(Problems) + "\n-# Los emojis personalizados tienen que ser de un servidor donde esté LOJI.", ephemeral=True,
            )
        await SavePanel(interaction.guild.id, self.panel_id, {"items": Items})
        P = await Panel(interaction.guild.id, self.panel_id)
        Note = "✅ Iconos guardados."
        if P.get("message_id"):
            await interaction.response.defer()
            Note += " " + await Publish(interaction.guild, P)
        else:
            Note += " Elige el **canal** para publicarlo." if not P.get("channel") else " Pulsa **Publicar**."
        await PanelEditor.Open(interaction, self.author, self.panel_id, Note)
