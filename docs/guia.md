# Guía de sanciones (`/guia`)

El staff le pregunta dudas a la guía de sanciones. La responde **openai/gpt-oss-120b** (Groq) **usando solo lo que dice la guía**.

## Configurar (`/config` → Mando Central → 📚 Guía de sanciones)
- **📤 Subir guía:** Word (`.docx`), `.txt` o `.md`. Reemplaza a la anterior y se aplica al momento.
- **📥 Descargar guía actual:** el texto exacto que lee el bot. Sirve para comprobar cómo quedaron las tablas.
- **🎭 Rol:** quién puede preguntar.
- **🔑 Key de Groq:** se guarda en la base de datos. Si la dejas vacía, se usa `GROQ_API_KEY` del `.env`.

## Uso
- `/guia pregunta:...`: la respuesta solo la ve quien pregunta y cita la sección de la guía. Si la guía no cubre la duda, lo dice.
- **2 preguntas por persona cada 24 horas**, contadas desde cada pregunta.
- Si falla Groq (límite por minuto, sin conexión…), **no se descuenta** la pregunta.
- **Sin memoria:** cada pregunta es independiente. Solo se guarda la hora de cada pregunta, para el límite.

## Consejo
Los títulos numerados (por ejemplo, "3.2 Spam reincidente") hacen que las respuestas citen bien. Los títulos de Word se conservan.
