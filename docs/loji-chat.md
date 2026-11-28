# 🤖 LOJI (chat)
`/config` → **🎉 Crecimiento y Entretenimiento** → **🤖 LOJI (chat)**. Usa la key de IA de `/guia` (DeepSeek o Groq).

- **Canal** donde conversa (uno) y **canal de alertas** del staff (opcional).
- **📤 Subir personalidad:** el `.txt` / `.md` / `.docx` con quién es LOJI y cómo habla (hasta ~10.000 tokens).
- **Cuándo entra:** menos de **4 personas** y menos de **10 mensajes** en **5 min**, durante **2 min** seguidos, y al menos
  **20 min** después de su última salida. **Cuándo se va:** con 4+ personas en 5 min, dice la **despedida** y se duerme.
  Todo en **⚙️ Umbrales**.
- Mientras está: espera unos segundos a que la gente termine de escribir, "está escribiendo…", 1–2 mensajes cortos,
  nunca dos veces seguidas sin respuesta. Al entrar lee lo último del canal para sumarse a la conversación.
- **🧠 Límites y memoria:** mensajes al día (150), tokens de contexto (10.000), días que recuerda las conversaciones (7)
  y las cosas de la gente (14).
- **👀 Modo observación:** no habla; el panel muestra cuándo habría entrado en los últimos 7 días, para ajustar los umbrales.
- **Seguridad** (por encima de la personalidad): nada sexual ni de ligar, nada de política real, no pide datos personales,
  ignora a quien intenta cambiarle las reglas, y si alguien parece estar muy mal le responde con cariño y avisa al staff (💗).
- **Interruptor** (`/loji interruptor` o el botón ⏯️ del panel), **solo con la credencial del Tenno**:
  🗣️ **Que hable ya** (aunque el chat esté activo; se queda hasta que la calles, como mucho un mensaje cada ~15 s y
  respetando el límite diario), 😴 **Que se calle ya** (se despide), ⏯️ **Encender / apagar el modo automático**.
- **Privacidad:** `/loji olvidame` borra lo de esa persona y deja de guardarlo (otra vez = deshacer).
