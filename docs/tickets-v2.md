# Tickets: panel en Components V2, autocierre y tickets anteriores

## 📄 Panel de abrir ticket en V2 (paneles multi)
`/config` → Tickets → tu panel multi → **📄 Diseño V2**.
- Sube un `.json` de Components V2 **sin los botones de abrir ticket** (banner, textos, separadores, botones de enlace…).
- LOJI añade los botones del panel (los mismos de siempre, con su texto, emoji, color e identificador):
  al final de la caja, o donde pongas un texto que diga solo `{botones}`.
- Te enseña la vista previa (con los botones desactivados) y **solo guarda si Discord lo acepta**.
- Publica con `/tickets panel` como siempre. Si el diseño fallara al enviarse, sale el embed de siempre y te lo dice.
- **👁️ Vista previa V2** y **🧹 Quitar V2** (vuelve al embed de siempre).
- Lo de dentro del ticket no cambia.

## ⏳ Autocierre (por panel, activado por defecto)
Cuando el staff fue el último en escribir y el usuario no responde:
- a las **24 h** se le avisa de que el ticket se cerrará en 12 h;
- a las **36 h** se cierra solo, con transcripción y MD ("Cerrado automáticamente: el usuario no respondió en 36 h").
- Si alguien escribe, el aviso se anula. Si quien espera es el usuario, nunca se cierra solo.
- Se activa o desactiva en `/config` → Tickets → panel → **⏳ Autocierre**.
- Un ticket cerrado así sin nadie que lo reclamara no ofrece valorar a nadie.

## 📂 Tickets anteriores
El mensaje de apertura del ticket muestra cuántos tickets cerrados tiene ya esa persona (si tiene alguno).
