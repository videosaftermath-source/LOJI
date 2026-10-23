import io
import json
import re

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.bot.emojis import Emojis
from core.bot.permissions import Permissions

LINK = re.compile(r"channels/(\d+)/(\d+)/(\d+)")
EMBED_KEYS = ("title", "description", "url", "color", "author", "footer", "image", "thumbnail", "fields", "timestamp")


def Clean(embed: dict) -> dict:
    """Keeps only what the Discord API (and message.style/discohook) accept."""
    E = {k: embed[k] for k in EMBED_KEYS if embed.get(k) not in (None, "", [], {})}
    for Key in ("image", "thumbnail"):
        if Key in E:
            E[Key] = {"url": E[Key].get("url")} if E[Key].get("url") else None
    if "author" in E:
        E["author"] = {k: v for k, v in E["author"].items() if k in ("name", "url", "icon_url") and v}
    if "footer" in E:
        E["footer"] = {k: v for k, v in E["footer"].items() if k in ("text", "icon_url") and v}
    if "fields" in E:
        E["fields"] = [
            {"name": F.get("name", ""), "value": F.get("value", ""), "inline": bool(F.get("inline"))}
            for F in E["fields"][:25]
        ]
    return {k: v for k, v in E.items() if v}


def IsEmpty(embed: dict) -> bool:
    return not any(
        embed.get(k) for k in ("title", "description", "fields", "image", "thumbnail")
    ) and not (embed.get("author") or {}).get("name") and not (embed.get("footer") or {}).get("text")


def FromMessage(message: discord.Message) -> dict:
    return {
        "content": message.content or "",
        "embeds": [Clean(E.to_dict()) for E in message.embeds if E.type == "rich"],
    }


def ParseJSON(text: str) -> dict:
    """Accepts message.style / discohook JSON, a bare message, a list of embeds or one embed."""
    Data = json.loads(text)
    if isinstance(Data, dict) and isinstance(Data.get("messages"), list) and Data["messages"]:
        Data = Data["messages"][0].get("data", {})  # discohook backup/share
    if isinstance(Data, list):
        Data = {"embeds": Data}
    if not isinstance(Data, dict):
        raise ValueError("El JSON no es un mensaje.")
    if "embeds" not in Data and "content" not in Data:
        Data = {"embeds": [Data]}
    Embeds = [Clean(E) for E in (Data.get("embeds") or []) if isinstance(E, dict)][:10]
    return {"content": str(Data.get("content") or "")[:2000], "embeds": Embeds}


def ToJSON(data: dict) -> str:
    return json.dumps(
        {"content": data.get("content") or None, "embeds": data.get("embeds", [])},
        indent=2,
        ensure_ascii=False,
    )


def ParseColor(value: str):
    value = value.strip().lstrip("#")
    if not value:
        return None
    try:
        return int(value, 16) if not value.isdigit() or len(value) == 6 else int(value)
    except ValueError:
        raise ValueError("Color inválido. Usa un hex como `#5865F2`.")


def ParseLink(link: str):
    Match = LINK.search(link or "")
    return tuple(int(x) for x in Match.groups()) if Match else None


async def FetchBotMessage(ctx: commands.Context, link: str):
    Parsed = ParseLink(link)
    if not Parsed or Parsed[0] != ctx.guild.id:
        return None, "Ese enlace no es de un mensaje de este servidor."
    Channel = ctx.guild.get_channel_or_thread(Parsed[1])
    if not Channel:
        return None, "No encuentro ese canal."
    try:
        Message = await Channel.fetch_message(Parsed[2])
    except discord.HTTPException:
        return None, "No encuentro ese mensaje."
    if Message.author.id != ctx.bot.user.id:
        return None, "Solo puedo editar mensajes enviados por mí."
    return Message, None


class TextModal(discord.ui.Modal):
    """Modal whose inputs map to keys; on submit hands the values to `apply`."""

    def __init__(self, title: str, inputs: list, apply):
        super().__init__(title=title)
        self.apply = apply
        self.inputs = {}
        for Key, Label, Default, Max, Long in inputs:
            Input = discord.ui.TextInput(
                label=Label,
                default=str(Default)[:Max] if Default not in (None, "") else None,
                max_length=Max,
                required=False,
                style=discord.TextStyle.paragraph if Long else discord.TextStyle.short,
            )
            self.inputs[Key] = Input
            self.add_item(Input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.apply(interaction, {k: v.value.strip() for k, v in self.inputs.items()})
        except ValueError as e:
            await interaction.response.send_message(f"{Emojis.no} {e}", ephemeral=True)


class EmbedSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Embed", row=0)

    async def callback(self, interaction: discord.Interaction):
        Editor: EmbedEditor = self.view
        if self.values[0] == "add":
            Editor.data["embeds"].append({"description": "Nueva descripción"})
            Editor.index = len(Editor.data["embeds"]) - 1
        else:
            Editor.index = int(self.values[0])
        await Editor.Render(interaction)


class FieldSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Campos", row=1)

    async def callback(self, interaction: discord.Interaction):
        Editor: EmbedEditor = self.view
        Embed = Editor.Current()
        if Embed is None:
            return await interaction.response.send_message("Primero añade un embed.", ephemeral=True)
        Fields = Embed.setdefault("fields", [])
        Index = None if self.values[0] == "add" else int(self.values[0])
        Field = Fields[Index] if Index is not None else {}

        async def Apply(i: discord.Interaction, v: dict):
            if not v["name"] and not v["value"]:
                if Index is not None:
                    Fields.pop(Index)
            else:
                New = {
                    "name": v["name"] or "​",
                    "value": v["value"] or "​",
                    "inline": v["inline"].lower() in ("si", "sí", "s", "yes", "y", "true", "1"),
                }
                if Index is None:
                    Fields.append(New)
                else:
                    Fields[Index] = New
            Editor.data["embeds"][Editor.index] = Clean(Embed)
            await Editor.Render(i)

        await interaction.response.send_modal(
            TextModal(
                "Campo" if Index is not None else "Añadir campo",
                [
                    ("name", "Nombre (vacío + valor vacío = borrar)", Field.get("name"), 256, False),
                    ("value", "Valor", Field.get("value"), 1024, True),
                    ("inline", "¿En línea? (sí/no)", "sí" if Field.get("inline") else "no", 3, False),
                ],
                Apply,
            )
        )


class EmbedEditor(discord.ui.View):
    def __init__(self, author: discord.Member, data: dict, channel=None, message=None):
        super().__init__(timeout=1800)
        self.author = author
        self.data = data
        self.data.setdefault("embeds", [])
        self.index = 0
        self.channel = channel  # send a new message here...
        self.message = message  # ...or edit this one
        self.EmbedSelect = EmbedSelect()
        self.FieldSelect = FieldSelect()
        self.add_item(self.EmbedSelect)
        self.add_item(self.FieldSelect)
        self.Finish.label = "Guardar cambios" if message else "Enviar"
        self.Refresh()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True

    def Current(self):
        Embeds = self.data["embeds"]
        if not Embeds:
            return None
        self.index = min(self.index, len(Embeds) - 1)
        return Embeds[self.index]

    def Refresh(self):
        Embeds = self.data["embeds"]
        Options = [
            discord.SelectOption(
                label=f"Embed {i + 1}: {(E.get('title') or E.get('description') or '...')[:80]}",
                value=str(i),
                default=i == self.index,
            )
            for i, E in enumerate(Embeds)
        ]
        if len(Embeds) < 10:
            Options.append(discord.SelectOption(label="Añadir embed", value="add", emoji="➕"))
        self.EmbedSelect.options = Options

        Fields = (self.Current() or {}).get("fields", [])
        Options = [
            discord.SelectOption(label=f"{i + 1}. {F.get('name', '')[:90] or '(sin nombre)'}", value=str(i))
            for i, F in enumerate(Fields)
        ]
        if len(Fields) < 25:
            Options.insert(0, discord.SelectOption(label="Añadir campo", value="add", emoji="➕"))
        self.FieldSelect.options = Options
        self.FieldSelect.disabled = not Embeds
        self.RemoveEmbed.disabled = not Embeds

    def Preview(self):
        Embeds = []
        for E in self.data["embeds"]:
            E = dict(E)
            if IsEmpty(E):
                E["description"] = "*(embed vacío)*"
            Embeds.append(discord.Embed.from_dict(E))
        Content = self.data.get("content") or None
        if not Content and not Embeds:
            Content = "*(mensaje vacío: añade contenido o un embed)*"
        return Content, Embeds

    async def Render(self, interaction: discord.Interaction):
        self.Refresh()
        Content, Embeds = self.Preview()
        try:
            await interaction.response.edit_message(content=Content, embeds=Embeds, view=self)
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"{Emojis.no} Discord no acepta eso: `{e.text[:300]}`", ephemeral=True
            )

    async def EditCurrent(self, interaction, title, inputs, apply):
        if self.Current() is None:
            return await interaction.response.send_message("Primero añade un embed.", ephemeral=True)
        await interaction.response.send_modal(TextModal(title, inputs, apply))

    @discord.ui.button(label="Contenido", style=discord.ButtonStyle.grey, row=2)
    async def Content(self, interaction: discord.Interaction, _):
        async def Apply(i, v):
            self.data["content"] = v["content"]
            await self.Render(i)

        await interaction.response.send_modal(
            TextModal("Contenido", [("content", "Texto fuera del embed", self.data.get("content"), 2000, True)], Apply)
        )

    @discord.ui.button(label="Cuerpo", style=discord.ButtonStyle.blurple, row=2)
    async def Body(self, interaction: discord.Interaction, _):
        E = self.Current() or {}

        async def Apply(i, v):
            Color = ParseColor(v["color"]) if v["color"] else None
            for Key in ("title", "description", "url"):
                E[Key] = v[Key] or None
            E["color"] = Color
            self.data["embeds"][self.index] = Clean(E)
            await self.Render(i)

        await self.EditCurrent(
            interaction,
            "Cuerpo del embed",
            [
                ("title", "Título", E.get("title"), 256, False),
                ("description", "Descripción", E.get("description"), 4000, True),
                ("url", "Enlace del título", E.get("url"), 500, False),
                ("color", "Color (hex, ej. #5865F2)", f"#{E['color']:06X}" if E.get("color") else None, 9, False),
            ],
            Apply,
        )

    @discord.ui.button(label="Autor", style=discord.ButtonStyle.grey, row=2)
    async def Author(self, interaction: discord.Interaction, _):
        E = self.Current() or {}
        A = E.get("author") or {}

        async def Apply(i, v):
            E["author"] = {"name": v["name"], "icon_url": v["icon_url"], "url": v["url"]}
            self.data["embeds"][self.index] = Clean(E)
            await self.Render(i)

        await self.EditCurrent(
            interaction,
            "Autor",
            [
                ("name", "Nombre", A.get("name"), 256, False),
                ("icon_url", "URL del icono", A.get("icon_url"), 500, False),
                ("url", "Enlace", A.get("url"), 500, False),
            ],
            Apply,
        )

    @discord.ui.button(label="Pie", style=discord.ButtonStyle.grey, row=2)
    async def Footer(self, interaction: discord.Interaction, _):
        E = self.Current() or {}
        F = E.get("footer") or {}

        async def Apply(i, v):
            E["footer"] = {"text": v["text"], "icon_url": v["icon_url"]}
            if v["timestamp"].lower() in ("si", "sí", "s", "yes", "y"):
                E["timestamp"] = E.get("timestamp") or discord.utils.utcnow().isoformat()
            else:
                E.pop("timestamp", None)
            self.data["embeds"][self.index] = Clean(E)
            await self.Render(i)

        await self.EditCurrent(
            interaction,
            "Pie",
            [
                ("text", "Texto", F.get("text"), 2048, True),
                ("icon_url", "URL del icono", F.get("icon_url"), 500, False),
                ("timestamp", "¿Mostrar fecha? (sí/no)", "sí" if E.get("timestamp") else "no", 3, False),
            ],
            Apply,
        )

    @discord.ui.button(label="Imágenes", style=discord.ButtonStyle.grey, row=2)
    async def Images(self, interaction: discord.Interaction, _):
        E = self.Current() or {}

        async def Apply(i, v):
            E["image"] = {"url": v["image"]} if v["image"] else None
            E["thumbnail"] = {"url": v["thumbnail"]} if v["thumbnail"] else None
            self.data["embeds"][self.index] = Clean(E)
            await self.Render(i)

        await self.EditCurrent(
            interaction,
            "Imágenes",
            [
                ("image", "Imagen grande (URL)", (E.get("image") or {}).get("url"), 500, False),
                ("thumbnail", "Miniatura (URL)", (E.get("thumbnail") or {}).get("url"), 500, False),
            ],
            Apply,
        )

    @discord.ui.button(label="Quitar embed", style=discord.ButtonStyle.red, row=3)
    async def RemoveEmbed(self, interaction: discord.Interaction, _):
        if self.data["embeds"]:
            self.data["embeds"].pop(self.index)
            self.index = max(0, self.index - 1)
        await self.Render(interaction)

    @discord.ui.button(label="Exportar JSON", emoji="📤", style=discord.ButtonStyle.grey, row=3)
    async def Export(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "Pega este JSON en https://message.style (botón **JSON**) o https://discohook.org (**JSON Data Editor**), edítalo allí y vuelve con **Importar JSON**.",
            file=discord.File(io.BytesIO(ToJSON(self.data).encode()), "embed.json"),
            ephemeral=True,
        )

    @discord.ui.button(label="Importar JSON", emoji="📥", style=discord.ButtonStyle.grey, row=3)
    async def Import(self, interaction: discord.Interaction, _):
        async def Apply(i, v):
            try:
                self.data = ParseJSON(v["json"])
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                raise ValueError(f"JSON inválido: {e}")
            self.index = 0
            await self.Render(i)

        await interaction.response.send_modal(
            TextModal("Importar JSON", [("json", "Pega aquí el JSON", None, 4000, True)], Apply)
        )

    @discord.ui.button(label="Guardar plantilla", emoji="💾", style=discord.ButtonStyle.grey, row=3)
    async def SaveTemplate(self, interaction: discord.Interaction, _):
        async def Apply(i, v):
            if not v["name"]:
                raise ValueError("Ponle un nombre.")
            await i.client.db["EmbedTemplates"].update_one(
                {"guild_id": i.guild.id, "name": v["name"]},
                {"$set": {"data": self.data, "author": i.user.id}},
                upsert=True,
            )
            await i.response.send_message(
                f"{Emojis.tick} Plantilla **{v['name']}** guardada. Úsala con `/embed crear plantilla:{v['name']}`.",
                ephemeral=True,
            )

        await interaction.response.send_modal(
            TextModal("Guardar plantilla", [("name", "Nombre", None, 50, False)], Apply)
        )

    @discord.ui.button(label="Enviar", style=discord.ButtonStyle.green, row=4)
    async def Finish(self, interaction: discord.Interaction, _):
        Embeds = self.data["embeds"]
        if any(IsEmpty(E) for E in Embeds):
            return await interaction.response.send_message(
                f"{Emojis.no} Hay un embed vacío. Rellénalo o quítalo.", ephemeral=True
            )
        if not self.data.get("content") and not Embeds:
            return await interaction.response.send_message(
                f"{Emojis.no} El mensaje está vacío.", ephemeral=True
            )
        Content = self.data.get("content") or None
        Built = [discord.Embed.from_dict(E) for E in Embeds]
        try:
            if self.message:
                await self.message.edit(content=Content, embeds=Built)
                Target = self.message
            else:
                Target = await self.channel.send(content=Content, embeds=Built)
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"{Emojis.no} Discord lo rechazó: `{e.text[:300]}`", ephemeral=True
            )
        self.stop()
        await interaction.response.edit_message(
            content=f"{Emojis.tick} {'Mensaje actualizado' if self.message else 'Enviado'}: {Target.jump_url}\n-# Para volver a editarlo: `/embed editar enlace:{Target.jump_url}`",
            embeds=[],
            view=None,
        )

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.red, row=4)
    async def Cancel(self, interaction: discord.Interaction, _):
        self.stop()
        await interaction.response.edit_message(content="Cancelado.", embeds=[], view=None)


async def TemplateAutocomplete(interaction: discord.Interaction, current: str):
    Templates = (
        await interaction.client.db["EmbedTemplates"]
        .find({"guild_id": interaction.guild.id, "name": {"$regex": re.escape(current), "$options": "i"}})
        .to_list(length=25)
    )
    return [app_commands.Choice(name=T["name"], value=T["name"]) for T in Templates]


class Embeds(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    async def LoadData(self, ctx, archivo, plantilla):
        if archivo:
            if archivo.size > 100_000:
                raise ValueError("El archivo es demasiado grande.")
            return ParseJSON((await archivo.read()).decode("utf-8"))
        if plantilla:
            T = await self.client.db["EmbedTemplates"].find_one({"guild_id": ctx.guild.id, "name": plantilla})
            if not T:
                raise ValueError(f"No existe la plantilla **{plantilla}**.")
            return T["data"]
        return None

    async def Open(self, ctx, data, channel=None, message=None):
        Editor = EmbedEditor(ctx.author, data, channel=channel, message=message)
        Content, Embeds = Editor.Preview()
        await ctx.send(content=Content, embeds=Embeds, view=Editor, ephemeral=True)

    @commands.hybrid_group(name="embed", description="Crear y editar embeds")
    async def embed(self, ctx: commands.Context):
        pass

    @embed.command(name="crear", description="Crear un embed nuevo y enviarlo a un canal")
    @app_commands.describe(
        canal="Dónde se enviará",
        archivo="Opcional: un .json de message.style o discohook",
        plantilla="Opcional: empezar desde una plantilla guardada",
    )
    @app_commands.autocomplete(plantilla=TemplateAutocomplete)
    @Permissions("Admin")
    async def crear(
        self,
        ctx: commands.Context,
        canal: discord.TextChannel,
        archivo: discord.Attachment = None,
        plantilla: str = None,
    ):
        try:
            Data = await self.LoadData(ctx, archivo, plantilla)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        await self.Open(
            ctx,
            Data or {"content": "", "embeds": [{"title": "Título", "description": "Descripción", "color": 0x5865F2}]},
            channel=canal,
        )

    @embed.command(name="editar", description="Editar un mensaje que ya envió el bot")
    @app_commands.describe(
        enlace="Enlace del mensaje (clic derecho → Copiar enlace del mensaje)",
        archivo="Opcional: reemplazarlo por un .json de message.style o discohook",
    )
    @Permissions("Admin")
    async def editar(self, ctx: commands.Context, enlace: str, archivo: discord.Attachment = None):
        Message, Error = await FetchBotMessage(ctx, enlace)
        if Error:
            return await ctx.send(f"{Emojis.no} {Error}", ephemeral=True)
        try:
            Data = await self.LoadData(ctx, archivo, None) or FromMessage(Message)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            return await ctx.send(f"{Emojis.no} {e}", ephemeral=True)
        await self.Open(ctx, Data, message=Message)

    @embed.command(name="exportar", description="Sacar el JSON de un mensaje para editarlo en message.style")
    @app_commands.describe(enlace="Enlace del mensaje")
    @Permissions("Admin")
    async def exportar(self, ctx: commands.Context, enlace: str):
        Parsed = ParseLink(enlace)
        Channel = ctx.guild.get_channel_or_thread(Parsed[1]) if Parsed and Parsed[0] == ctx.guild.id else None
        try:
            Message = await Channel.fetch_message(Parsed[2]) if Channel else None
        except discord.HTTPException:
            Message = None
        if not Message:
            return await ctx.send(f"{Emojis.no} No encuentro ese mensaje.", ephemeral=True)
        await ctx.send(
            "Pega este JSON en https://message.style o https://discohook.org, edítalo y luego usa `/embed editar` con el archivo.",
            file=discord.File(io.BytesIO(ToJSON(FromMessage(Message)).encode()), "embed.json"),
            ephemeral=True,
        )

    @embed.command(name="plantillas", description="Ver las plantillas guardadas")
    @Permissions("Admin")
    async def plantillas(self, ctx: commands.Context):
        Templates = await self.client.db["EmbedTemplates"].find({"guild_id": ctx.guild.id}).to_list(length=100)
        if not Templates:
            return await ctx.send("No hay plantillas. Guárdalas desde el editor con **Guardar plantilla**.", ephemeral=True)
        await ctx.send(
            embed=discord.Embed(
                title="Plantillas",
                description="\n".join(f"- **{T['name']}** · <@{T.get('author')}>" for T in Templates),
                color=discord.Color.dark_embed(),
            ),
            ephemeral=True,
        )

    @embed.command(name="borrar-plantilla", description="Borrar una plantilla")
    @app_commands.autocomplete(nombre=TemplateAutocomplete)
    @Permissions("Admin")
    async def borrar_plantilla(self, ctx: commands.Context, nombre: str):
        Result = await self.client.db["EmbedTemplates"].delete_one({"guild_id": ctx.guild.id, "name": nombre})
        await ctx.send(
            f"{Emojis.tick} Plantilla borrada." if Result.deleted_count else f"{Emojis.no} No existe esa plantilla.",
            ephemeral=True,
        )


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Embeds(client))
