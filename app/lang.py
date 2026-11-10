"""Everything a family hears or reads in its own language: the warning, the takeover voice's lines, Telegram messages.

AssemblyAI streaming speech-to-text and text-to-speech both cover English, Spanish and Portuguese (and German, French and
Italian), so those three are launched. Hindi is covered by speech-to-text but not yet by text-to-speech, so it waits.
Adding a language means adding one `Pack` here: nothing else in the server hard-codes English.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Pack:
    code: str  # what the app sends
    tts: str  # AssemblyAI TTS `language` (full name)
    stt: str  # AssemblyAI streaming speech-to-text language code
    label: str  # in English, for the model prompts
    native: str  # what the language is called in itself, shown in the app
    # --- the takeover voice: a made-up older person, never real details ---
    decoy_name: str
    decoy_city: str
    decoy_bank: str
    decoy_phone: str
    opening: str
    stalls: tuple[str, str, str]
    examples: str
    number_words: frozenset
    # --- the family-voice warning, {p} is how the parent is addressed ---
    warnings: dict = field(default_factory=dict)
    # --- Telegram ---
    t: dict = field(default_factory=dict)


NUM_EN = frozenset("zero one two three four five six seven eight nine oh".split())
NUM_ES = frozenset("cero uno una dos tres cuatro cinco seis siete ocho nueve".split())
NUM_PT = frozenset("zero um uma dois duas três tres quatro cinco seis sete oito nove".split())

STAGE_EN = {"S1": "Authority", "S2": "Threat", "S3": "Secrecy", "S4": "Urgency", "S5": "Credential request",
            "S6": "Payment request", "S7": "Remote access"}

EN = Pack(
    code="en", tts="english", stt="en", label="English", native="English",
    decoy_name="Harold Peterson", decoy_city="Springfield", decoy_bank="First Community Bank", decoy_phone="five five five, zero one zero zero",
    opening="Hello? Oh, sorry, I did not hear you properly. Please go on, I am listening.",
    stalls=("Sorry, uh, the line is not very clear. Can you say that again, slowly?",
            "One minute please, I am looking for my glasses. Please say that again.",
            "Ah, I am writing it down. Can you say it once more, slowly?"),
    examples=('Caller: "Your account is frozen." You: "Oh dear… frozen? Hmm, I only used it this morning. Which bank did you say you are from?"\n'
              'Caller: "Send the money now." You: "Now? Oh, I must find my checkbook first… it is in the drawer somewhere. What name is it in again?"\n'
              'Caller: "Read me the code." You: "A code? Hmm, nothing has come, my phone is very old. If we get cut off, what number can I call you back on?"'),
    number_words=NUM_EN,
    warnings={
        "S7": "{p}, stop… Please do not install anything or share your screen. Close that app right now. Put the phone down, and call me. I'm right here.",
        "S5": "{p}, stop… Please do not read out that code. No bank or officer ever asks for a code or a PIN on a call. Put the phone down, and call me. I'm right here.",
        "S6": "{p}, stop… Please do not send any money. A real officer never asks for payment on a phone call. Put the phone down, and call me first. I'm right here.",
        "S3": "{p}, stop… You do not have to stay on this call. A real officer will never ask you to keep it secret. Put the phone down, and call me. I'm right here.",
        "S2": "{p}, stop… The police never arrest anyone on a phone call. This is a scam. Put the phone down now. I'm right here.",
        "S1": "{p}, stop… I think this is a scam call. Police and banks do not threaten people on the phone. Put the phone down, and call me. I'm right here.",
        "default": "{p}, stop… I think this call is not safe. Please put the phone down, and call me. I'm right here.",
    },
    t={
        "stages": STAGE_EN, "none_yet": "none yet", "risk": "Risk {risk}/100", "caller": "Caller", "unknown": "unknown number",
        "warn_head": "🚨 Kavach: possible scam call detected",
        "warn_tail": "Tap below to end the call, or send a voice note and it will play on {p}'s phone.",
        "escalate_head": "⚠️ Kavach: the call is escalating",
        "takeover_head": "🛡️ Kavach has taken over the call (decoy persona is talking)",
        "end_button": "☎️ End the call",
        "report_ready": "📄 Kavach: call ended. Report draft ready with {n} captured detail(s). Please tap the buttons below to say whether money or a code/PIN was shared, then review the draft and report it to {hint}. (Draft only: nothing was submitted.)",
        "doc_caption": "Fraud report draft (review before filing)",
        "doc_caption2": "Updated report draft with your answers (review before filing)",
        "money_yes": "Money sent: Yes", "money_no": "Money sent: No", "otp_yes": "Code/PIN shared: Yes", "otp_no": "Code/PIN shared: No",
        "saved": "Saved: {label} = {answer}", "money_label": "Money sent", "otp_label": "Code/PIN shared", "yes": "Yes", "no": "No",
        "expired": "This question has expired.",
        "no_phone": "I could not send this. {p}'s phone is not connected to Kavach right now.",
        "too_long": "That voice note is too long. Keep it under {n} seconds.",
        "cannot_play": "I could not play that: {why}.", "cannot_download": "I could not download that voice note. Please try again.",
        "playing": "▶️ Playing on {p}'s phone now ({n} s).",
        "no_confirm": "{p}'s phone did not confirm it got this. It may have no internet right now.",
        "app_offline": "{p}'s app is not connected, so it could not be played.",
        "already_ended": "That call has already ended.", "ending": "Ending the call.",
        "could_not_cut": "⚠️ I could not cut {p}'s phone call, so it is still on. Kavach is still protecting it. Please try ringing or messaging {p}.",
        "call_ended": "☎️ The call was ended. Send a voice note now and it will play on {p}'s phone.",
        "linked": "✅ Connected. You will get Kavach alerts for {p}'s phone here. When a scam call is detected you can end it from here, and send a voice note that plays on {p}'s phone.",
        "link_bad": "That link has expired or was already used. Open the Kavach app and tap “Connect Telegram” again.",
        "welcome": "Hi! I am the Kavach bot. To connect this chat to your family, open the Kavach app and tap “Connect Telegram”.",
        "voice_set": "Done. Kavach will speak in voice {voice} when it takes over a call.",
    },
)

ES = Pack(
    code="es", tts="spanish", stt="es", label="Spanish", native="Español",
    decoy_name="Manuel Ortega", decoy_city="Valencia", decoy_bank="Banco del Sur", decoy_phone="cinco cinco cinco, cero uno cero cero",
    opening="¿Hola? Ay, perdone, no le oí bien. Siga, siga, le escucho.",
    stalls=("Perdone, eh, la línea se oye mal. ¿Me lo puede repetir despacio?",
            "Un momentito, que estoy buscando mis gafas. Repítamelo, por favor.",
            "Ah, lo estoy apuntando. ¿Me lo repite otra vez, despacio?"),
    examples=('Llamante: "Su cuenta está bloqueada." Tú: "Ay, Dios mío… ¿bloqueada? Pero si la usé esta mañana. ¿De qué banco dice que llama?"\n'
              'Llamante: "Envíe el dinero ya." Tú: "¿Ahora? Uy, primero tengo que buscar la libreta… está en el cajón, creo. ¿A nombre de quién era?"\n'
              'Llamante: "Dígame el código." Tú: "¿Un código? Mmm, no me ha llegado nada, mi móvil es muy viejo. Si se corta, ¿a qué número le puedo llamar?"'),
    number_words=NUM_ES,
    warnings={
        "S7": "{p}, para… No instales nada ni compartas la pantalla. Cierra esa aplicación ahora mismo. Cuelga el teléfono y llámame. Estoy aquí.",
        "S5": "{p}, para… No digas ese código. Ningún banco ni agente te pide un código o un PIN por teléfono. Cuelga el teléfono y llámame. Estoy aquí.",
        "S6": "{p}, para… No envíes dinero. Un agente de verdad nunca pide un pago por teléfono. Cuelga el teléfono y llámame primero. Estoy aquí.",
        "S3": "{p}, para… No tienes que seguir en esta llamada. Un agente de verdad nunca te pide guardar el secreto. Cuelga el teléfono y llámame. Estoy aquí.",
        "S2": "{p}, para… La policía nunca detiene a nadie por teléfono. Esto es una estafa. Cuelga el teléfono ahora. Estoy aquí.",
        "S1": "{p}, para… Creo que esta llamada es una estafa. La policía y los bancos no amenazan a nadie por teléfono. Cuelga el teléfono y llámame. Estoy aquí.",
        "default": "{p}, para… Creo que esta llamada no es segura. Por favor, cuelga el teléfono y llámame. Estoy aquí.",
    },
    t={
        "stages": {"S1": "Autoridad", "S2": "Amenaza", "S3": "Secreto", "S4": "Urgencia", "S5": "Petición de códigos",
                   "S6": "Petición de pago", "S7": "Acceso remoto"}, "none_yet": "ninguna todavía", "risk": "Riesgo {risk}/100",
        "caller": "Llamante", "unknown": "número desconocido",
        "warn_head": "🚨 Kavach: posible llamada de estafa detectada",
        "warn_tail": "Toca abajo para cortar la llamada, o envía una nota de voz y sonará en el teléfono de {p}.",
        "escalate_head": "⚠️ Kavach: la llamada se está agravando",
        "takeover_head": "🛡️ Kavach ha tomado la llamada (habla el personaje señuelo)",
        "end_button": "☎️ Cortar la llamada",
        "report_ready": "📄 Kavach: llamada terminada. Borrador del informe listo con {n} dato(s) capturado(s). Toca los botones para decir si se envió dinero o un código/PIN, revisa el borrador y denúncialo a {hint}. (Solo un borrador: no se ha presentado nada.)",
        "doc_caption": "Borrador del informe de fraude (revísalo antes de presentarlo)",
        "doc_caption2": "Borrador actualizado con tus respuestas (revísalo antes de presentarlo)",
        "money_yes": "Dinero enviado: Sí", "money_no": "Dinero enviado: No", "otp_yes": "Código/PIN compartido: Sí", "otp_no": "Código/PIN compartido: No",
        "saved": "Guardado: {label} = {answer}", "money_label": "Dinero enviado", "otp_label": "Código/PIN compartido", "yes": "Sí", "no": "No",
        "expired": "Esta pregunta ha caducado.",
        "no_phone": "No pude enviarlo. El teléfono de {p} no está conectado a Kavach ahora mismo.",
        "too_long": "Esa nota de voz es demasiado larga. Que dure menos de {n} segundos.",
        "cannot_play": "No pude reproducirla: {why}.", "cannot_download": "No pude descargar esa nota de voz. Inténtalo de nuevo.",
        "playing": "▶️ Sonando ahora en el teléfono de {p} ({n} s).",
        "no_confirm": "El teléfono de {p} no confirmó que la recibió. Puede que no tenga internet ahora.",
        "app_offline": "La aplicación de {p} no está conectada, así que no se pudo reproducir.",
        "already_ended": "Esa llamada ya terminó.", "ending": "Cortando la llamada.",
        "could_not_cut": "⚠️ No pude cortar la llamada del teléfono de {p}, así que sigue en curso. Kavach sigue protegiéndola. Intenta llamar o escribir a {p}.",
        "call_ended": "☎️ La llamada se cortó. Envía una nota de voz ahora y sonará en el teléfono de {p}.",
        "linked": "✅ Conectado. Recibirás aquí las alertas de Kavach del teléfono de {p}. Si se detecta una llamada de estafa podrás cortarla desde aquí y enviar una nota de voz que sonará en su teléfono.",
        "link_bad": "Ese enlace ha caducado o ya se usó. Abre la aplicación Kavach y toca «Conectar Telegram» otra vez.",
        "welcome": "¡Hola! Soy el bot de Kavach. Para conectar este chat con tu familia, abre la aplicación Kavach y toca «Conectar Telegram».",
        "voice_set": "Listo. Kavach hablará con la voz {voice} cuando tome una llamada.",
    },
)

PT = Pack(
    code="pt", tts="portuguese", stt="pt", label="Portuguese", native="Português",
    decoy_name="Antônio Silva", decoy_city="Campinas", decoy_bank="Banco do Sul", decoy_phone="cinco cinco cinco, zero um zero zero",
    opening="Alô? Ah, desculpe, eu não ouvi direito. Pode continuar, estou ouvindo.",
    stalls=("Desculpe, é, a linha está ruim. O senhor pode repetir devagar?",
            "Um minutinho, estou procurando meus óculos. Repita, por favor.",
            "Ah, estou anotando. Pode repetir mais uma vez, devagar?"),
    examples=('Ligante: "Sua conta foi bloqueada." Você: "Ai, meu Deus… bloqueada? Mas eu usei hoje de manhã. De que banco o senhor disse que é?"\n'
              'Ligante: "Mande o dinheiro agora." Você: "Agora? Ih, primeiro preciso achar minha caderneta… está na gaveta, acho. Em nome de quem é mesmo?"\n'
              'Ligante: "Me diga o código." Você: "Código? Hum, não chegou nada, meu celular é muito velho. Se a ligação cair, para qual número eu ligo de volta?"'),
    number_words=NUM_PT,
    warnings={
        "S7": "{p}, pare… Não instale nada nem compartilhe a tela. Feche esse aplicativo agora. Desligue o telefone e me ligue. Estou aqui.",
        "S5": "{p}, pare… Não diga esse código. Nenhum banco ou policial pede código ou senha por telefone. Desligue o telefone e me ligue. Estou aqui.",
        "S6": "{p}, pare… Não envie dinheiro. Um policial de verdade nunca pede pagamento por telefone. Desligue o telefone e me ligue primeiro. Estou aqui.",
        "S3": "{p}, pare… Você não precisa continuar nessa ligação. Um policial de verdade nunca pede segredo. Desligue o telefone e me ligue. Estou aqui.",
        "S2": "{p}, pare… A polícia nunca prende ninguém por telefone. Isso é golpe. Desligue o telefone agora. Estou aqui.",
        "S1": "{p}, pare… Acho que essa ligação é um golpe. Polícia e bancos não ameaçam ninguém por telefone. Desligue o telefone e me ligue. Estou aqui.",
        "default": "{p}, pare… Acho que essa ligação não é segura. Por favor, desligue o telefone e me ligue. Estou aqui.",
    },
    t={
        "stages": {"S1": "Autoridade", "S2": "Ameaça", "S3": "Sigilo", "S4": "Urgência", "S5": "Pedido de códigos",
                   "S6": "Pedido de pagamento", "S7": "Acesso remoto"}, "none_yet": "nenhuma ainda", "risk": "Risco {risk}/100",
        "caller": "Ligante", "unknown": "número desconhecido",
        "warn_head": "🚨 Kavach: possível ligação de golpe detectada",
        "warn_tail": "Toque abaixo para encerrar a ligação, ou envie uma mensagem de voz e ela tocará no telefone de {p}.",
        "escalate_head": "⚠️ Kavach: a ligação está piorando",
        "takeover_head": "🛡️ Kavach assumiu a ligação (o personagem isca está falando)",
        "end_button": "☎️ Encerrar a ligação",
        "report_ready": "📄 Kavach: ligação encerrada. Rascunho do relatório pronto com {n} dado(s) capturado(s). Toque nos botões para dizer se dinheiro ou um código/senha foi compartilhado, revise o rascunho e registre a ocorrência em {hint}. (Apenas rascunho: nada foi enviado.)",
        "doc_caption": "Rascunho do relatório de fraude (revise antes de registrar)",
        "doc_caption2": "Rascunho atualizado com suas respostas (revise antes de registrar)",
        "money_yes": "Dinheiro enviado: Sim", "money_no": "Dinheiro enviado: Não", "otp_yes": "Código/senha compartilhado: Sim", "otp_no": "Código/senha compartilhado: Não",
        "saved": "Salvo: {label} = {answer}", "money_label": "Dinheiro enviado", "otp_label": "Código/senha compartilhado", "yes": "Sim", "no": "Não",
        "expired": "Esta pergunta expirou.",
        "no_phone": "Não consegui enviar. O telefone de {p} não está conectado ao Kavach agora.",
        "too_long": "Essa mensagem de voz é longa demais. Mantenha abaixo de {n} segundos.",
        "cannot_play": "Não consegui tocar: {why}.", "cannot_download": "Não consegui baixar essa mensagem de voz. Tente de novo.",
        "playing": "▶️ Tocando agora no telefone de {p} ({n} s).",
        "no_confirm": "O telefone de {p} não confirmou que recebeu. Pode estar sem internet agora.",
        "app_offline": "O aplicativo de {p} não está conectado, então não foi possível tocar.",
        "already_ended": "Essa ligação já terminou.", "ending": "Encerrando a ligação.",
        "could_not_cut": "⚠️ Não consegui encerrar a ligação do telefone de {p}, então ela continua. O Kavach continua protegendo. Tente ligar ou mandar mensagem para {p}.",
        "call_ended": "☎️ A ligação foi encerrada. Envie uma mensagem de voz agora e ela tocará no telefone de {p}.",
        "linked": "✅ Conectado. Você receberá aqui os alertas do Kavach do telefone de {p}. Se uma ligação de golpe for detectada, você poderá encerrá-la daqui e enviar uma mensagem de voz que tocará no telefone dele(a).",
        "link_bad": "Esse link expirou ou já foi usado. Abra o aplicativo Kavach e toque em “Conectar Telegram” de novo.",
        "welcome": "Oi! Sou o bot do Kavach. Para conectar este chat à sua família, abra o aplicativo Kavach e toque em “Conectar Telegram”.",
        "voice_set": "Pronto. O Kavach falará com a voz {voice} quando assumir uma ligação.",
    },
)

PACKS = {p.code: p for p in (EN, ES, PT)}
DEFAULT = "en"


def get(code: str | None) -> Pack:
    return PACKS.get((code or DEFAULT).lower()[:2], EN)


def available() -> list[dict]:
    return [{"code": p.code, "label": p.label, "native": p.native} for p in PACKS.values()]
