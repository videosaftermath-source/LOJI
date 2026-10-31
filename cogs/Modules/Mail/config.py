"""/buzon: configuration of departments, high offices, channels and credentials."""

import discord
from discord.ext import commands

from core.bot.HelpEmbeds import NotYourPanel
from core.mail.config import OFFICES, CanConfigure, Department, Mail, MailError

PANEL_TIMEOUT = 600
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
GENERAL = {
    "staff_role": ("Rol de staff (quién puede usar /mail)", "role"),
    "suggestions_channel": ("Canal de sugerencias", "channel"),
    "debate_channel": ("Canal «Cosas por debatir» (Consejo Supremo)", "channel"),
    **{f"offices.{O}.role": (f"Rol de {Name}", "role") for O, Name in OFFICES.items()},
}


def Role(guild: discord.Guild, role_id) -> str:
    return f"<@&{role_id}>" if role_id and guild.get_role(role_id) else "*sin configurar*"


def Channel(guild: discord.Guild, channel_id) -> str:
    return f"<#{channel_id}>" if channel_id and guild.get_channel(channel_id) else "*sin configurar*"


def GetPath(config: dict, path: str):
    Value = config
    for Part in path.split("."):
        Value = Value.get(Part) if isinstance(Value, dict) else None
    return Value


def PanelEmbed(guild: discord.Guild, config: dict) -> discord.Embed:
    embed = discord.Embed(title="📮 Buzón · Configuración", color=LOJI_RED)
    embed.add_field(
        name="⚙️ General",
        value=(
            f"> **Staff:** {Role(guild, config['staff_role'])}\n"
            f"> **Sugerencias:** {Channel(guild, config['suggestions_channel'])}\n"
            f"> **Cosas por debatir:** {Channel(guild, config['debate_channel'])}"
        ),
        inline=False,
    )
    embed.add_field(
        name="👑 Cargos",
        value="\n".join(
            f"> **{Name}:** {Role(guild, config['offices'][O]['role'])} · "
            f"{'🔑 credencial lista' if config['offices'][O].get('credential') else '🔓 sin credencial'}"
            for O, Name in OFFICES.items()
        ),
        inline=False,
    )
    Lines = []
    for D in config["departments"]:
        Group = f" *({D['group']})*" if D.get("group") else ""
        Lines.append(f"> **{D['name']}**{Group} · {Role(guild, D['role'])} · {Channel(guild, D['channel'])}")
    embed.add_field(name="🏢 Departamentos", value="\n".join(Lines)[:1024] or "Ninguno.", inline=False)
    embed.set_footer(text="Los permisos van por rol. Las credenciales son un atajo opcional de los cargos.")
    return embed


class Panel(discord.ui.View):
    """Base: only the person who opened it can use it."""

    def __init__(self, author: discord.abc.User):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(embed=NotYourPanel(), ephemeral=True)
            return False
        return True


async def ShowMain(interaction: discord.Interaction, author, note: str | None = None):
    Config = await Mail().Get(interaction.guild.id)
    await interaction.response.edit_message(content=note, embed=PanelEmbed(interaction.guild, Config), view=MainPanel(author, Config))


class MainPanel(Panel):
    def __init__(self, author, config: dict):
        super().__init__(author)
        General = discord.ui.Select(
            placeholder="⚙️ General y cargos",
            options=[discord.SelectOption(label=Label[:100], value=Path) for Path, (Label, _) in GENERAL.items()],
            row=0,
        )
        General.callback = self.PickGeneral
        self.add_item(General)
        if config["departments"]:
            Departments = discord.ui.Select(
                placeholder="🏢 Configurar un departamento",
                options=[discord.SelectOption(label=D["name"], value=D["id"], description=(D.get("group") or None)) for D in config["departments"]],
                row=1,
            )
            Departments.callback = self.PickDepartment
            self.add_item(Departments)

    async def PickGeneral(self, interaction: discord.Interaction):
        Path = interaction.data["values"][0]
        Label, Kind = GENERAL[Path]
        await interaction.response.edit_message(content=f"**{Label}**", embed=None, view=PickTarget(self.author, Path, Kind))

    async def PickDepartment(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        D = Department(Config, interaction.data["values"][0])
        if not D:
            return await ShowMain(interaction, self.author, "Ese departamento ya no existe.")
        await interaction.response.edit_message(content=None, embed=DepartmentEmbed(interaction.guild, D), view=DepartmentPanel(self.author, D))

    @discord.ui.button(label="Crear departamento", emoji="➕", style=discord.ButtonStyle.green, row=2)
    async def Create(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(DepartmentInfo(self.author))

    @discord.ui.button(label="Credenciales", emoji="🔑", style=discord.ButtonStyle.blurple, row=2)
    async def Credentials(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            content="🔑 **Credenciales.** Son un atajo opcional para actuar sin el rol. Elige un cargo:",
            embed=None, view=CredentialPanel(self.author),
        )


class PickTarget(Panel):
    """Pick a role or a channel for a general setting."""

    def __init__(self, author, path: str, kind: str):
        super().__init__(author)
        self.path = path
        if kind == "role":
            Picker = discord.ui.RoleSelect(placeholder="Elige el rol", row=0)
        else:
            Picker = discord.ui.ChannelSelect(placeholder="Elige el canal", channel_types=[discord.ChannelType.text], row=0)
        Picker.callback = self.Pick
        self.add_item(Picker)

    async def Pick(self, interaction: discord.Interaction):
        await Mail().Set(interaction.guild.id, {self.path: int(interaction.data["values"][0])})
        await ShowMain(interaction, self.author, "✅ Guardado.")

    @discord.ui.button(label="Quitar", emoji="🧹", style=discord.ButtonStyle.grey, row=1)
    async def Clear(self, interaction: discord.Interaction, _):
        await Mail().Set(interaction.guild.id, {self.path: None})
        await ShowMain(interaction, self.author, "🧹 Quitado.")

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back(self, interaction: discord.Interaction, _):
        await ShowMain(interaction, self.author)


def DepartmentEmbed(guild: discord.Guild, department: dict) -> discord.Embed:
    embed = discord.Embed(title=f"🏢 {department['name']}", color=LOJI_RED)
    if department.get("group"):
        embed.description = f"Grupo: **{department['group']}**"
    embed.add_field(name="Rol", value=Role(guild, department["role"]), inline=True)
    embed.add_field(name="Canal de tareas", value=Channel(guild, department["channel"]), inline=True)
    embed.set_footer(text="Quien tenga el rol puede reclamar y cerrar las tareas de este departamento.")
    return embed


class DepartmentPanel(Panel):
    def __init__(self, author, department: dict):
        super().__init__(author)
        self.department = department
        self.confirming = False
        RolePick = discord.ui.RoleSelect(placeholder="Rol del departamento", row=0)
        RolePick.callback = self.SetRole
        ChannelPick = discord.ui.ChannelSelect(placeholder="Canal donde llegan sus tareas", channel_types=[discord.ChannelType.text], row=1)
        ChannelPick.callback = self.SetChannel
        self.add_item(RolePick)
        self.add_item(ChannelPick)

    async def Save(self, interaction: discord.Interaction, changes: dict):
        try:
            D = await Mail().UpdateDepartment(interaction.guild.id, self.department["id"], changes)
        except MailError as e:
            return await ShowMain(interaction, self.author, f"❌ {e}")
        await interaction.response.edit_message(content="✅ Guardado.", embed=DepartmentEmbed(interaction.guild, D), view=DepartmentPanel(self.author, D))

    async def SetRole(self, interaction: discord.Interaction):
        await self.Save(interaction, {"role": int(interaction.data["values"][0])})

    async def SetChannel(self, interaction: discord.Interaction):
        await self.Save(interaction, {"channel": int(interaction.data["values"][0])})

    @discord.ui.button(label="Renombrar", emoji="✏️", style=discord.ButtonStyle.blurple, row=2)
    async def Rename(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(DepartmentInfo(self.author, self.department))

    @discord.ui.button(label="Borrar", emoji="🗑️", style=discord.ButtonStyle.red, row=2)
    async def Remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.confirming:
            self.confirming = True
            button.label = "¿Seguro? Pulsa otra vez"
            return await interaction.response.edit_message(view=self)
        await Mail().RemoveDepartment(interaction.guild.id, self.department["id"])
        await ShowMain(interaction, self.author, f"🗑️ Borrado **{self.department['name']}**.")

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=2)
    async def Back(self, interaction: discord.Interaction, _):
        await ShowMain(interaction, self.author)


class DepartmentInfo(discord.ui.Modal):
    def __init__(self, author, department: dict | None = None):
        super().__init__(title="Renombrar departamento" if department else "Nuevo departamento")
        self.author = author
        self.department = department
        self.name = discord.ui.TextInput(label="Nombre", max_length=50, default=(department or {}).get("name"))
        self.group = discord.ui.TextInput(label="Grupo (opcional, ej. Mod Senior)", max_length=50, required=False, default=(department or {}).get("group") or None)
        self.add_item(self.name)
        self.add_item(self.group)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if self.department:
                await Mail().UpdateDepartment(interaction.guild.id, self.department["id"], {"name": self.name.value.strip(), "group": self.group.value.strip()})
                Note = "✏️ Renombrado."
            else:
                D = await Mail().AddDepartment(interaction.guild.id, self.name.value, self.group.value)
                Note = f"➕ Creado **{D['name']}**. Elígelo en el menú para ponerle rol y canal."
        except MailError as e:
            Note = f"❌ {e}"
        await ShowMain(interaction, self.author, Note)


class CredentialPanel(Panel):
    def __init__(self, author):
        super().__init__(author)
        Pick = discord.ui.Select(placeholder="¿De qué cargo?", options=[discord.SelectOption(label=Name, value=O) for O, Name in OFFICES.items()], row=0)
        Pick.callback = self.Pick
        self.add_item(Pick)

    async def Pick(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CredentialModal(self.author, interaction.data["values"][0]))

    @discord.ui.button(label="Volver", emoji="⬅️", style=discord.ButtonStyle.grey, row=1)
    async def Back(self, interaction: discord.Interaction, _):
        await ShowMain(interaction, self.author)


class CredentialModal(discord.ui.Modal):
    def __init__(self, author, office: str):
        super().__init__(title=f"Credencial · {OFFICES[office]}"[:45])
        self.author = author
        self.office = office
        self.code = discord.ui.TextInput(
            label="Nueva credencial (vacío = generar una)", placeholder="Letra y 4 números, ej. M-1808", max_length=7, required=False,
        )
        self.add_item(self.code)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            Code = await Mail().SetCredential(interaction.guild.id, self.office, self.code.value.strip())
        except MailError as e:
            return await ShowMain(interaction, self.author, f"❌ {e}")
        await ShowMain(
            interaction, self.author,
            f"🔑 Credencial de **{OFFICES[self.office]}**: ||`{Code}`||\n"
            "-# Guárdala y compártela solo con quien corresponda: no se vuelve a mostrar (se guarda cifrada).",
        )


class MailSetup(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.hybrid_group(name="buzon", description="Buzón de sugerencias y tareas del staff")
    @commands.guild_only()
    async def buzon(self, ctx: commands.Context):
        pass

    @buzon.command(name="config", description="Configura departamentos, cargos, canales y credenciales")
    async def config(self, ctx: commands.Context):
        Config = await Mail().Get(ctx.guild.id)
        if not CanConfigure(ctx.author, Config):
            return await ctx.send("❌ Solo el Tenno (o un administrador del servidor) puede configurar el buzón.", ephemeral=True)
        await ctx.send(embed=PanelEmbed(ctx.guild, Config), view=MainPanel(ctx.author, Config), ephemeral=True)

    @buzon.command(name="departamentos", description="Cómo está organizado el staff")
    async def departamentos(self, ctx: commands.Context):
        Config = await Mail().Get(ctx.guild.id)
        embed = PanelEmbed(ctx.guild, Config)
        embed.title = "📮 Departamentos del staff"
        embed.set_footer(text="Tu rol decide en qué departamento puedes reclamar tareas.")
        await ctx.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(client: commands.Bot) -> None:
    await client.add_cog(MailSetup(client))
