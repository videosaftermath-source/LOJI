# Política de privacidad de LOJI · LOJI Privacy Policy

*Última actualización / Last updated: 28/11/2026*

[Español](#español) · [English](#english)

---

## Español

LOJI es un bot privado de Discord hecho para una sola comunidad. No es público ni se puede invitar a otros servidores. Esta política explica qué datos usa, para qué y cómo pedir que se borren.

### Qué datos guardamos

En una base de datos privada (MongoDB) que solo usa el bot:

- **Tu ID de Discord.** Es la clave de todo lo demás. No guardamos tu nombre de usuario, tu correo ni tu IP.
- **Tickets de soporte:** quién lo abrió, quién lo atendió y cerró, cuándo y el motivo de cierre.
- **Datos del staff (solo miembros del staff):** rango y desde cuándo, historial de cambios de rol, medallas, cuota semanal de actividad (número de mensajes, **no su contenido**), ausencias, ascensos, infracciones y suspensiones.
- **Feedback:** la puntuación y el comentario que escribes al valorar a un miembro del staff.
- **Economía:** saldo, objetos, mascotas y fechas de los comandos que usas.
- **Recompensas por vanity o tag:** solo **si cumples o no** y desde cuándo. **Nunca guardamos el texto de tu estado.**

### Qué datos NO guardamos

- **El contenido de tus mensajes.** El bot lee los mensajes solo para:
  1. **Transcripciones de tickets:** al cerrar un ticket, la conversación de ese canal se sube como archivo `.html` a un canal privado del staff dentro de Discord. No se copia a nuestra base de datos ni a ningún servidor externo.
  2. **Respuestas automáticas:** el bot compara el mensaje con unas frases configuradas y, si coincide, responde. El mensaje no se guarda.
  3. **Filtro anti-spam de la economía:** compara tus mensajes recientes **en memoria** para no pagar mensajes repetidos. No se guarda y se borra al reiniciar.
  4. **Reporte rápido:** si varios usuarios reportan un mensaje con 🚩 en el canal donde está activado, ese mensaje y unos pocos mensajes anteriores de la conversación se envían a **Groq** (IA) para valorar si rompe las normas, y el resultado va a un canal privado del staff. Solo se envían mensajes reportados, y su texto no se guarda en nuestra base de datos.
- **Tus actividades, juegos o estado**, salvo comprobar si tu estado contiene la vanity del servidor.

### Servicios de terceros

- **Discord**, donde vive todo.
- **Groq** (IA): cuando el staff usa `/guia`, la pregunta escrita en el comando y la guía de sanciones se envían a Groq para generar la respuesta. Con el **reporte rápido**, se envían el mensaje reportado y algunos mensajes anteriores (con el nombre visible de sus autores). No se envía nada más del servidor y **no se usan datos para entrenar modelos de IA**.
- El bot se aloja en un servidor privado; la base de datos no es accesible públicamente.

### Tus opciones

- **`/privacidad`:** ver si participas en las recompensas por vanity o tag y **desactivar** la comprobación de tu estado.
- **Borrar tus datos:** abre un ticket en el servidor y el staff los borrará. Las transcripciones de tickets se guardan en Discord y se pueden borrar de la misma forma.
- Los datos se guardan mientras el bot funcione en el servidor o hasta que pidas borrarlos.

### Edad

Discord exige tener al menos 13 años (o la edad mínima de tu país). LOJI no pide ni guarda la edad de nadie.

### Cambios y contacto

Si esta política cambia, se actualiza aquí con la fecha nueva. Para cualquier duda, abre un ticket en el servidor.

---

## English

LOJI is a private Discord bot built for a single community. It is not public and can't be invited to other servers. This policy explains what data it uses, why, and how to ask for it to be deleted.

### What we store

In a private MongoDB database used only by the bot:

- **Your Discord user ID.** It is the key for everything else. We don't store your username, email or IP address.
- **Support tickets:** who opened, claimed and closed them, when, and the close reason.
- **Staff data (staff members only):** rank and since when, role change history, medals, weekly activity quota (message **counts, not content**), leave of absence, promotions, infractions and suspensions.
- **Feedback:** the rating and comment you write when rating a staff member.
- **Economy:** balance, items, pets and when you used commands.
- **Vanity/tag rewards:** only **whether you qualify** and since when. **We never store your status text.**

### What we do NOT store

- **Your message content.** The bot reads messages only for:
  1. **Ticket transcripts:** when a ticket is closed, that channel's conversation is uploaded as an `.html` file to a private staff channel inside Discord. It is not copied to our database or to any external server.
  2. **Auto-responses:** the bot compares a message with configured trigger phrases and replies when it matches. The message is not stored.
  3. **Economy anti-spam:** recent messages are compared **in memory** so repeated messages aren't rewarded. They are not stored and are cleared on restart.
  4. **Quick reports:** when several users flag a message with 🚩 in the channel where this is enabled, that message and a few earlier messages of the conversation are sent to **Groq** (AI) to judge whether it breaks the rules, and the result goes to a private staff channel. Only reported messages are sent, and their text is not stored in our database.
- **Your activities, games or status**, except for checking whether your custom status contains the server's vanity link.

### Third-party services

- **Discord**, where everything lives.
- **Groq** (AI): when staff use `/guia`, the question typed in the command and the server's sanctions guide are sent to Groq to generate the answer. With **quick reports**, the reported message and a few earlier messages (with their authors' display names) are sent. Nothing else from the server is sent and **no data is used to train AI models**.
- The bot is hosted on a private server; the database is not publicly reachable.

### Your choices

- **`/privacidad`:** see whether you take part in vanity/tag rewards and **opt out** of status checks.
- **Deleting your data:** open a ticket in the server and staff will delete it. Ticket transcripts live in Discord and can be deleted the same way.
- Data is kept while the bot runs in the server or until you ask for it to be deleted.

### Age

Discord requires users to be at least 13 (or the minimum age in your country). LOJI does not ask for or store anyone's age.

### Changes and contact

If this policy changes, it is updated here with the new date. For any question, open a ticket in the server.
