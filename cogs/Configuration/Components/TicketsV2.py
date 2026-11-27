"""/config → Tickets → (multi) panel: its Components V2 design. Only the look: the open buttons are Birb's own."""

import discord

from core.ticket_v2 import Build, PanelButtons

HOW = (
    "Sube un **.json** de Components V2 **sin los botones de abrir ticket**: LOJI los añade (los mismos de siempre). "
    "Van al final de la caja, o donde pongas un texto que diga solo `{botones}`.\n"
    "-# En la vista previa los botones salen desactivados. Para que se vea en el canal, vuelve a usar `/tickets panel`."
)


async def GetPanel(interaction: discord.Interaction, name: str) -> dict | None:
    return await interaction.client.db["Panels"].find_one({"guild": interaction.guild.id, "type": "multi", "name": name})


async def Preview(interaction: discord.Interaction, panel: dict, json_text: str):
    """Shows the design with the panel's buttons (disabled), privately. Raises ValueError / HTTPException."""
    from cogs.Modules.Community.community import SendJson

    Components = Build(json_text, await PanelButtons(interaction.client.db, interaction.guild.id, panel), disabled=True)
    await SendJson(interaction.client.http, 0, Components, ephemeral_token=(interaction.application_id, interaction.token))


class UploadV2(discord.ui.Modal, title="Diseño V2 del panel"):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.file = discord.ui.FileUpload(min_values=1, max_values=1)
        self.add_item(discord.ui.Label(
            text="Archivo .json (sin los botones de ticket)",
            description="Los botones los pone LOJI: al final o donde escribas {botones}.",
            component=self.file,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        File = (self.file.values or [None])[0]
        if not File or not File.filename.lower().endswith((".json", ".txt")):
            return await interaction.response.send_message("❌ Sube un archivo `.json`.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=False)
        Panel = await GetPanel(interaction, self.name)
        if not Panel:
            return await interaction.followup.send("❌ Este panel ya no existe.", ephemeral=True)
        try:
            Text = (await File.read()).decode("utf-8-sig")
            await Preview(interaction, Panel, Text)
        except UnicodeDecodeError:
            return await interaction.followup.send("❌ El archivo no está en UTF-8.", ephemeral=True)
        except ValueError as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ Discord no acepta ese diseño: {e.text or e}\nNo se ha guardado nada.", ephemeral=True)
        await interaction.client.db["Panels"].update_one(
            {"guild": interaction.guild.id, "type": "multi", "name": self.name},
            {"$set": {"V2": {"json": Text, "name": File.filename[:80]}}},
        )
        await interaction.followup.send(
            f"✅ Diseño guardado (la vista previa está arriba). Usa `/tickets panel` con **{self.name}** para publicarlo.",
            ephemeral=True,
        )


async def UploadButton(interaction: discord.Interaction, name: str):
    await interaction.response.send_modal(UploadV2(name))


async def PreviewButton(interaction: discord.Interaction, name: str):
    Panel = await GetPanel(interaction, name)
    if not Panel or not (Panel.get("V2") or {}).get("json"):
        return await interaction.response.send_message("Este panel no tiene diseño V2: usa **📄 Diseño V2**.\n" + HOW, ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=False)
    try:
        await Preview(interaction, Panel, Panel["V2"]["json"])
    except (ValueError, discord.HTTPException) as e:
        await interaction.followup.send(f"❌ El diseño ya no se puede mostrar: {getattr(e, 'text', None) or e}", ephemeral=True)


async def ClearButton(interaction: discord.Interaction, name: str):
    await interaction.client.db["Panels"].update_one(
        {"guild": interaction.guild.id, "type": "multi", "name": name}, {"$unset": {"V2": ""}},
    )
    await interaction.response.send_message(
        f"🧹 Diseño V2 quitado: **{name}** vuelve al embed de siempre. Usa `/tickets panel` para volver a publicarlo.", ephemeral=True,
    )
