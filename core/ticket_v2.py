"""
Ticket panels in Components V2: the admin uploads only the design (JSON, without the open buttons) and LOJI
adds the panel's own open buttons, with the same custom ids Birb uses, so they work exactly as before.

- The buttons go where a text component says just "{botones}", or else at the end of the last container.
- If anything about the design fails, /tickets panel sends the usual embed (nothing stops working).
"""

import copy

from core.community import MAX_COMPONENTS, ParseCardJson

PLACEHOLDER = "{botones}"
STYLES = {"Blurple": 1, "Grey": 2, "Secondary": 2, "Green": 3, "Red": 4}


def ButtonRows(buttons: list[dict], disabled: bool = False) -> list[dict]:
    """Birb's button settings -> action rows (5 per row) as raw components."""
    Items = []
    for B in buttons:
        if not B or not B.get("custom_id"):
            continue
        Item = {"type": 2, "style": STYLES.get(B.get("style"), 2), "custom_id": B["custom_id"]}
        if B.get("label"):
            Item["label"] = str(B["label"])[:80]
        Emoji = Emoji_(B.get("emoji"))
        if Emoji:
            Item["emoji"] = Emoji
        if not B.get("label") and not Emoji:
            Item["label"] = "Abrir ticket"
        if disabled:
            Item["disabled"] = True
        Items.append(Item)
    return [{"type": 1, "components": Items[I:I + 5]} for I in range(0, len(Items), 5)]


def Emoji_(text) -> dict | None:
    """'<:name:id>' / '<a:name:id>' / '🎫' -> the emoji object Discord wants."""
    if not text:
        return None
    Text = str(text).strip()
    if Text.startswith("<") and Text.endswith(">") and ":" in Text:
        Parts = Text.strip("<>").split(":")
        if len(Parts) == 3 and Parts[2].isdigit():
            return {"name": Parts[1], "id": Parts[2], "animated": Parts[0] == "a"}
        return None
    return {"name": Text}


def Count(items: list[dict]) -> int:
    return sum(1 + Count(I.get("components") or []) + (1 if I.get("accessory") else 0) for I in items)


def Assemble(design: list[dict], rows: list[dict]) -> list[dict]:
    """The design with the open buttons put in. Raises ValueError with a message for the admin."""
    if not rows:
        raise ValueError("El panel no tiene botones: revisa que sus paneles individuales tengan su botón configurado.")
    Out = copy.deepcopy(design)

    def Replace(items: list[dict]) -> bool:
        for I, Item in enumerate(items):
            if Item.get("type") == 10 and str(Item.get("content", "")).strip() == PLACEHOLDER:
                items[I:I + 1] = copy.deepcopy(rows)
                return True
            if Item.get("components") and Item.get("type") == 17 and Replace(Item["components"]):
                return True
        return False

    if not Replace(Out):
        Containers = [Item for Item in Out if Item.get("type") == 17]
        (Containers[-1]["components"] if Containers else Out).extend(copy.deepcopy(rows))
    if Count(Out) > MAX_COMPONENTS:
        raise ValueError(
            f"Con los botones del panel el mensaje tiene {Count(Out)} componentes y Discord permite {MAX_COMPONENTS}: simplifica el diseño."
        )
    return Out


def Build(json_text: str, buttons: list[dict], disabled: bool = False) -> list[dict]:
    """Design JSON + the panel's buttons -> the components to send."""
    return Assemble(ParseCardJson(json_text), ButtonRows(buttons, disabled))


async def PanelButtons(db, guild_id: int, panel: dict) -> list[dict]:
    """The open buttons of a panel, like Birb gathers them: one per sub-panel of a multi panel."""
    if panel.get("type") != "multi":
        Button = panel.get("Button")
        return [Button] if isinstance(Button, dict) else list(Button or [])
    Buttons = []
    for Name in panel.get("Panels") or []:
        Sub = await db["Panels"].find_one({"guild": guild_id, "name": Name, "type": "single"})
        if Sub and Sub.get("Button"):
            B = Sub["Button"]
            Buttons.append({"custom_id": B.get("custom_id"), "label": B.get("label"), "style": B.get("style"), "emoji": B.get("emoji")})
    return Buttons
