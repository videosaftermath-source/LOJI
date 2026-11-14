import discord
from sentry_sdk import metrics

from core.bot.emojis import Emojis

HOW = f"{Emojis.help} Cómo arreglarlo"


class Support(discord.ui.View):
    """Used to link Birb's support server. Kept (empty) because many messages still pass it."""

    def __init__(self):
        super().__init__()


def Problem(text: str, fix: str | None = None, color=None) -> discord.Embed:
    embed = discord.Embed(description=f"```\n{text}\n```", color=color or discord.Color.brand_red())
    if fix:
        embed.add_field(name=HOW, value=fix)
    return embed


def NoPermission(permission: str):
    return Problem(
        f"Este comando necesita permisos de {permission.lower()}.",
        f"> 1. Revisa `/config` → **Permisos**.\n> 2. Comprueba que tienes el rol de la categoría `{permission.lower()}`.",
    )


def NoSetupPermissions():
    return Problem(
        "Los permisos todavía no están configurados.",
        "> 1. Configúralos en `/config` → **Permisos**.\n> 2. Comprueba que tienes el rol que pide este comando.",
    )


def NoAdvancedPermission():
    return Problem(
        "Este comando necesita permisos avanzados.",
        "> 1. Revisa `/config` → **Permisos**.\n> 2. Comprueba que tienes el rol que pide este comando.",
    )


def ChannelNotFound():
    return Problem(
        "No encuentro el canal de esto.",
        "> 1. En `/config`, entra en el módulo y elige el canal.\n> 2. Comprueba que puedo **ver el canal**, **leer** y **enviar mensajes** ahí.",
    )


def CustomError(error: str):
    return Problem(error)


def NoPermissionChannel(channel: discord.TextChannel):
    return Problem(
        f"No puedo enviar mensajes en #{getattr(channel, 'name', channel)}.",
        "> 1. Dame permiso para **ver el canal** y **enviar mensajes** ahí.",
    )


def NoPremium():
    metrics.count("Popup:Premium", 1)
    return Problem("Esta función no está disponible en este servidor.", color=discord.Color.blurple())


def NotYourPanel():
    return Problem("Este panel no es tuyo: ábrelo tú con el comando.")


def GlobalMaintenance(reason: str):
    return discord.Embed(
        description="```\nEl bot está en mantenimiento.\n```", color=discord.Color.brand_red()
    ).add_field(name="Motivo", value=f"> {reason}")


def NoChannelSet():
    return Problem("Este módulo no tiene canal configurado.", "> 1. En `/config`, entra en el módulo y elige el canal.")


def ModuleNotEnabled():
    return Problem(
        "Este módulo no está activado.",
        "> 1. Ve a `/config` → **Módulos** y márcalo.\n> 2. Vuelve al menú de `/config`: ya te saldrá para configurarlo.",
    )


def BotNotConfigured():
    return Problem("Todavía no estoy configurado.", "> 1. Usa `/config` para configurarme.")


def ModuleNotSetup():
    return Problem("Este módulo todavía no está configurado.", "> 1. Usa `/config` y prepara el módulo.")
