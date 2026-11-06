"""Mando Central settings panel (opened from /config): departments, high offices, channels and credentials."""

import discord

from core.bot.HelpEmbeds import NotYourPanel
from core.mail.config import OFFICES, CanConfigure, Department, Mail, MailError

PANEL_TIMEOUT = 600
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
# What each wizard step is for, in plain words.
HELP = {
    "staff_role": "¿Qué rol tiene **todo el staff**? Quien lo tenga podrá usar `/mail` y `/tareas`.",
    "suggestions_channel": "¿En qué canal **te llegan las sugerencias**? Pon uno privado del Mando Central.",
    "debate_channel": "¿Dónde va lo que **se debatirá**? El canal del Consejo Supremo.",
    "offices.tenno.role": "¿Cuál es el rol del **Tenno**?",
    "offices.consejo.role": "¿Cuál es el rol del **Consejo Supremo**?",
    "offices.director.role": "¿Cuál es el rol del **Director de Moderación**?",
    "profile_min_role": "¿Cuál es el **rol más bajo del staff**? Ese rol y todos los que estén por encima tendrán perfil de staff.",
}
GENERAL = {
    "staff_role": ("Rol de staff (quién puede usar /mail)", "role"),
    "suggestions_channel": ("Canal de sugerencias", "channel"),
    "debate_channel": ("Canal «Cosas por debatir» (Consejo Supremo)", "channel"),
    **{f"offices.{O}.role": (f"Rol de {Name}", "role") for O, Name in OFFICES.items()},
    "profile_min_role": ("Rol mínimo con perfil de staff", "role"),
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


def Checklist(guild: discord.Guild, config: dict) -> tuple[list[str], int, int]:
    """(lines, done, total) of what's set up."""
    Items = [
        ("Rol de staff", bool(config["staff_role"] and guild.get_role(config["staff_role"]))),
        ("Canal de sugerencias", bool(config["suggestions_channel"] and guild.get_channel(config["suggestions_channel"]))),
        ("Canal «Cosas por debatir»", bool(config["debate_channel"] and guild.get_channel(config["debate_channel"]))),
        ("Rol mínimo de perfiles", bool(config.get("profile_min_role") and guild.get_role(config["profile_min_role"]))),
    ]
    Items += [(f"Rol de {Name}", bool(config["offices"][O]["role"] and guild.get_role(config["offices"][O]["role"]))) for O, Name in OFFICES.items()]
    Items += [
        (f"{D['name']}: rol y canal", bool(D["role"] and guild.get_role(D["role"]) and D["channel"] and guild.get_channel(D["channel"])))
        for D in config["departments"]
    ]
    Done = sum(1 for _, Ok in Items if Ok)
    return [f"{'✅' if Ok else '❌'} {Name}" for Name, Ok in Items], Done, len(Items)


def PanelEmbed(guild: discord.Guild, config: dict) -> discord.Embed:
    Lines, Done, Total = Checklist(guild, config)
    embed = discord.Embed(
        title="📮 Mando Central · Configuración",
        description=(
            f"**{Done}/{Total} listo.** " + ("Todo configurado 🎉" if Done == Total else "Pulsa **🧭 Asistente** y te guío paso a paso.")
            + "\n-# " + " · ".join(Lines)
        )[:4096],
        color=LOJI_RED,
    )
    embed.add_field(
        name="⚙️ General",
        value=(
            f"> **Staff:** {Role(guild, config['staff_role'])}\n"
            f"> **Sugerencias:** {Channel(guild, config['suggestions_channel'])}\n"
            f"> **Cosas por debatir:** {Channel(guild, config['debate_channel'])}\n"
            f"> **Rol mínimo de perfiles:** {Role(guild, config.get('profile_min_role'))}"
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

    @discord.ui.button(label="Asistente", emoji="🧭", style=discord.ButtonStyle.red, row=2)
    async def Wizard(self, interaction: discord.Interaction, _):
        Config = await Mail().Get(interaction.guild.id)
        await ShowStep(interaction, self.author, WizardSteps(Config), 0)

    @discord.ui.button(label="Crear departamento", emoji="➕", style=discord.ButtonStyle.green, row=2)
    async def Create(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(DepartmentInfo(self.author))

    @discord.ui.button(label="Credenciales", emoji="🔑", style=discord.ButtonStyle.blurple, row=2)
    async def Credentials(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(
            content="🔑 **Credenciales.** Son un atajo opcional para actuar sin el rol. Elige un cargo:",
            embed=None, view=CredentialPanel(self.author),
        )


def WizardSteps(config: dict) -> list[tuple[str, str, str]]:
    """(path to save, 'role'/'channel', question) for every setting, then each department's role and channel."""
    Steps = [(Path, Kind, HELP[Path]) for Path, (_, Kind) in GENERAL.items()]
    for D in config["departments"]:
        Steps.append((f"department:{D['id']}:role", "role", f"🏢 **{D['name']}**: ¿qué rol tienen sus miembros?"))
        Steps.append((f"department:{D['id']}:channel", "channel", f"🏢 **{D['name']}**: ¿en qué canal le llegan sus tareas?"))
    return Steps


async def ShowStep(interaction: discord.Interaction, author, steps: list, index: int):
    if index >= len(steps):
        return await ShowMain(interaction, author, "🧭 **Asistente terminado.** Revisa la lista: lo que siga en ❌ lo puedes poner cuando quieras.")
    Path, Kind, Question = steps[index]
    await interaction.response.edit_message(
        content=f"🧭 **Paso {index + 1} de {len(steps)}**\n{Question}", embed=None, view=WizardStep(author, steps, index),
    )


class WizardStep(Panel):
    def __init__(self, author, steps: list, index: int):
        super().__init__(author)
        self.steps, self.index = steps, index
        Path, Kind, _ = steps[index]
        if Kind == "role":
            Picker = discord.ui.RoleSelect(placeholder="Elige el rol", row=0)
        else:
            Picker = discord.ui.ChannelSelect(placeholder="Elige el canal", channel_types=[discord.ChannelType.text], row=0)
        Picker.callback = self.Pick
        self.add_item(Picker)

    async def Pick(self, interaction: discord.Interaction):
        Path = self.steps[self.index][0]
        Value = int(interaction.data["values"][0])
        if Path.startswith("department:"):
            _, DepId, Field = Path.split(":")
            try:
                await Mail().UpdateDepartment(interaction.guild.id, DepId, {Field: Value})
            except MailError:
                pass  # deleted meanwhile: just move on
        else:
            await Mail().Set(interaction.guild.id, {Path: Value})
        await ShowStep(interaction, self.author, self.steps, self.index + 1)

    @discord.ui.button(label="Omitir", emoji="⏭️", style=discord.ButtonStyle.grey, row=1)
    async def Skip(self, interaction: discord.Interaction, _):
        await ShowStep(interaction, self.author, self.steps, self.index + 1)

    @discord.ui.button(label="Salir", emoji="✖️", style=discord.ButtonStyle.grey, row=1)
    async def Exit(self, interaction: discord.Interaction, _):
        await ShowMain(interaction, self.author)


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
        # Only you see it (the panel may be open in a public channel through /config).
        await interaction.response.send_message(
            f"🔑 Credencial de **{OFFICES[self.office]}**: ||`{Code}`||\n"
            "-# Guárdala y compártela solo con quien corresponda: no se vuelve a mostrar (se guarda cifrada).",
            ephemeral=True,
        )
