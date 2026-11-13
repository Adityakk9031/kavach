"""Everything a family hears or reads in its own language: the warning, the takeover voice's lines, Telegram messages.

AssemblyAI streaming speech-to-text and text-to-speech both cover English, Spanish, Portuguese, German, French and Italian,
so those six are offered. Hindi is covered by speech-to-text but not yet by text-to-speech, so it waits.
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

NUM_DE = frozenset("null eins ein eine zwei zwo drei vier fünf sechs sieben acht neun".split())
NUM_FR = frozenset("zéro zero un une deux trois quatre cinq six sept huit neuf".split())
NUM_IT = frozenset("zero uno una due tre quattro cinque sei sette otto nove".split())

DE = Pack(
    code="de", tts="german", stt="de", label="German", native="Deutsch",
    decoy_name="Helmut Krüger", decoy_city="Kassel", decoy_bank="Sparbank Mitte", decoy_phone="fünf fünf fünf, null eins null null",
    opening="Hallo? Ach, Entschuldigung, ich habe Sie nicht richtig verstanden. Bitte, sprechen Sie weiter, ich höre zu.",
    stalls=("Entschuldigung, äh, die Leitung ist ganz schlecht. Können Sie das noch einmal langsam sagen?",
            "Einen Moment bitte, ich suche gerade meine Brille. Sagen Sie das bitte noch einmal.",
            "Ah, ich schreibe das auf. Können Sie es noch einmal sagen, schön langsam?"),
    examples=('Anrufer: "Ihr Konto ist gesperrt." Du: "Ach du liebe Zeit… gesperrt? Ich habe es doch heute Morgen noch benutzt. Von welcher Bank sind Sie, sagten Sie?"\n'
              'Anrufer: "Überweisen Sie das Geld jetzt." Du: "Jetzt gleich? Oh, da muss ich erst mein Sparbuch suchen… das liegt irgendwo in der Schublade. Auf welchen Namen noch mal?"\n'
              'Anrufer: "Lesen Sie mir den Code vor." Du: "Einen Code? Hm, da ist nichts gekommen, mein Telefon ist sehr alt. Falls wir unterbrochen werden, unter welcher Nummer erreiche ich Sie?"'),
    number_words=NUM_DE,
    warnings={
        "S7": "{p}, stopp… Bitte installiere nichts und teile nicht deinen Bildschirm. Schließ diese App sofort. Leg auf und ruf mich an. Ich bin da.",
        "S5": "{p}, stopp… Bitte lies diesen Code nicht vor. Keine Bank und kein Beamter fragt am Telefon nach einem Code oder einer PIN. Leg auf und ruf mich an. Ich bin da.",
        "S6": "{p}, stopp… Bitte überweise kein Geld. Ein echter Beamter verlangt am Telefon niemals eine Zahlung. Leg auf und ruf mich zuerst an. Ich bin da.",
        "S3": "{p}, stopp… Du musst nicht in diesem Gespräch bleiben. Ein echter Beamter verlangt nie, dass du es geheim hältst. Leg auf und ruf mich an. Ich bin da.",
        "S2": "{p}, stopp… Die Polizei verhaftet niemanden am Telefon. Das ist Betrug. Leg jetzt auf. Ich bin da.",
        "S1": "{p}, stopp… Ich glaube, das ist ein Betrugsanruf. Polizei und Banken drohen niemandem am Telefon. Leg auf und ruf mich an. Ich bin da.",
        "default": "{p}, stopp… Ich glaube, dieser Anruf ist nicht sicher. Bitte leg auf und ruf mich an. Ich bin da.",
    },
    t={
        "stages": {"S1": "Autorität", "S2": "Drohung", "S3": "Geheimhaltung", "S4": "Zeitdruck", "S5": "Frage nach Codes",
                   "S6": "Zahlungsforderung", "S7": "Fernzugriff"}, "none_yet": "noch keine", "risk": "Risiko {risk}/100",
        "caller": "Anrufer", "unknown": "unbekannte Nummer",
        "warn_head": "🚨 Kavach: möglicher Betrugsanruf erkannt",
        "warn_tail": "Tippe unten, um den Anruf zu beenden, oder sende eine Sprachnachricht. Sie wird auf dem Telefon von {p} abgespielt.",
        "escalate_head": "⚠️ Kavach: der Anruf spitzt sich zu",
        "takeover_head": "🛡️ Kavach hat den Anruf übernommen (die Lockvogel-Stimme spricht)",
        "end_button": "☎️ Anruf beenden",
        "report_ready": "📄 Kavach: Anruf beendet. Der Berichtsentwurf mit {n} erfassten Angabe(n) ist fertig. Tippe auf die Tasten unten, um zu sagen, ob Geld oder ein Code/eine PIN weitergegeben wurde. Prüfe dann den Entwurf und melde den Fall bei {hint}. (Nur ein Entwurf: es wurde nichts eingereicht.)",
        "doc_caption": "Entwurf der Betrugsanzeige (vor dem Einreichen prüfen)",
        "doc_caption2": "Aktualisierter Entwurf mit deinen Antworten (vor dem Einreichen prüfen)",
        "money_yes": "Geld gesendet: Ja", "money_no": "Geld gesendet: Nein", "otp_yes": "Code/PIN genannt: Ja", "otp_no": "Code/PIN genannt: Nein",
        "saved": "Gespeichert: {label} = {answer}", "money_label": "Geld gesendet", "otp_label": "Code/PIN genannt", "yes": "Ja", "no": "Nein",
        "expired": "Diese Frage ist abgelaufen.",
        "no_phone": "Das konnte ich nicht senden. Das Telefon von {p} ist gerade nicht mit Kavach verbunden.",
        "too_long": "Diese Sprachnachricht ist zu lang. Bitte unter {n} Sekunden bleiben.",
        "cannot_play": "Das konnte ich nicht abspielen: {why}.", "cannot_download": "Ich konnte diese Sprachnachricht nicht laden. Bitte versuche es noch einmal.",
        "playing": "▶️ Wird jetzt auf dem Telefon von {p} abgespielt ({n} s).",
        "no_confirm": "Das Telefon von {p} hat den Empfang nicht bestätigt. Vielleicht hat es gerade kein Internet.",
        "app_offline": "Die App von {p} ist nicht verbunden, deshalb konnte nichts abgespielt werden.",
        "already_ended": "Dieser Anruf ist schon beendet.", "ending": "Der Anruf wird beendet.",
        "could_not_cut": "⚠️ Ich konnte den Anruf auf dem Telefon von {p} nicht beenden, er läuft also noch. Kavach schützt ihn weiter. Bitte versuche, {p} anzurufen oder zu schreiben.",
        "call_ended": "☎️ Der Anruf wurde beendet. Sende jetzt eine Sprachnachricht, sie wird auf dem Telefon von {p} abgespielt.",
        "linked": "✅ Verbunden. Hier bekommst du die Kavach-Warnungen für das Telefon von {p}. Wird ein Betrugsanruf erkannt, kannst du ihn von hier beenden und eine Sprachnachricht senden, die auf dem Telefon abgespielt wird.",
        "link_bad": "Dieser Link ist abgelaufen oder wurde schon benutzt. Öffne die Kavach-App und tippe noch einmal auf „Telegram verbinden“.",
        "welcome": "Hallo! Ich bin der Kavach-Bot. Um diesen Chat mit deiner Familie zu verbinden, öffne die Kavach-App und tippe auf „Telegram verbinden“.",
        "voice_set": "Erledigt. Kavach spricht mit der Stimme {voice}, wenn es einen Anruf übernimmt.",
    },
)

FR = Pack(
    code="fr", tts="french", stt="fr", label="French", native="Français",
    decoy_name="Bernard Lefèvre", decoy_city="Angers", decoy_bank="Banque du Centre", decoy_phone="cinq cinq cinq, zéro un zéro zéro",
    opening="Allô ? Oh, pardon, je ne vous ai pas bien entendu. Continuez, je vous écoute.",
    stalls=("Pardon, euh, la ligne est très mauvaise. Vous pouvez répéter lentement ?",
            "Une petite minute, je cherche mes lunettes. Répétez, s'il vous plaît.",
            "Ah, je note. Vous pouvez le redire encore une fois, doucement ?"),
    examples=('Appelant : "Votre compte est bloqué." Toi : "Oh là là… bloqué ? Mais je m\'en suis servi ce matin. Vous êtes de quelle banque, vous m\'avez dit ?"\n'
              'Appelant : "Envoyez l\'argent maintenant." Toi : "Maintenant ? Oh, il faut d\'abord que je retrouve mon chéquier… il est dans un tiroir, je crois. C\'est à quel nom, déjà ?"\n'
              'Appelant : "Lisez-moi le code." Toi : "Un code ? Hmm, je n\'ai rien reçu, mon téléphone est très vieux. Si ça coupe, à quel numéro je peux vous rappeler ?"'),
    number_words=NUM_FR,
    warnings={
        "S7": "{p}, arrête… N'installe rien et ne partage pas ton écran. Ferme cette application tout de suite. Raccroche et appelle-moi. Je suis là.",
        "S5": "{p}, arrête… Ne donne pas ce code. Aucune banque ni aucun agent ne demande un code ou un PIN au téléphone. Raccroche et appelle-moi. Je suis là.",
        "S6": "{p}, arrête… N'envoie pas d'argent. Un vrai agent ne demande jamais de paiement au téléphone. Raccroche et appelle-moi d'abord. Je suis là.",
        "S3": "{p}, arrête… Tu n'es pas obligé de rester en ligne. Un vrai agent ne te demandera jamais de garder le secret. Raccroche et appelle-moi. Je suis là.",
        "S2": "{p}, arrête… La police n'arrête personne par téléphone. C'est une arnaque. Raccroche maintenant. Je suis là.",
        "S1": "{p}, arrête… Je crois que c'est une arnaque. La police et les banques ne menacent personne au téléphone. Raccroche et appelle-moi. Je suis là.",
        "default": "{p}, arrête… Je crois que cet appel n'est pas sûr. S'il te plaît, raccroche et appelle-moi. Je suis là.",
    },
    t={
        "stages": {"S1": "Autorité", "S2": "Menace", "S3": "Secret", "S4": "Urgence", "S5": "Demande de codes",
                   "S6": "Demande de paiement", "S7": "Accès à distance"}, "none_yet": "aucune pour l'instant", "risk": "Risque {risk}/100",
        "caller": "Appelant", "unknown": "numéro inconnu",
        "warn_head": "🚨 Kavach : appel suspect, possible arnaque",
        "warn_tail": "Touchez ci-dessous pour couper l'appel, ou envoyez un message vocal : il sera joué sur le téléphone de {p}.",
        "escalate_head": "⚠️ Kavach : l'appel s'aggrave",
        "takeover_head": "🛡️ Kavach a pris l'appel (la voix leurre parle)",
        "end_button": "☎️ Couper l'appel",
        "report_ready": "📄 Kavach : appel terminé. Le brouillon du signalement est prêt avec {n} élément(s) relevé(s). Touchez les boutons ci-dessous pour dire si de l'argent ou un code/PIN a été donné, relisez le brouillon et signalez-le à {hint}. (Brouillon seulement : rien n'a été envoyé.)",
        "doc_caption": "Brouillon du signalement de fraude (à relire avant de le déposer)",
        "doc_caption2": "Brouillon mis à jour avec vos réponses (à relire avant de le déposer)",
        "money_yes": "Argent envoyé : Oui", "money_no": "Argent envoyé : Non", "otp_yes": "Code/PIN donné : Oui", "otp_no": "Code/PIN donné : Non",
        "saved": "Enregistré : {label} = {answer}", "money_label": "Argent envoyé", "otp_label": "Code/PIN donné", "yes": "Oui", "no": "Non",
        "expired": "Cette question a expiré.",
        "no_phone": "Je n'ai pas pu l'envoyer. Le téléphone de {p} n'est pas connecté à Kavach en ce moment.",
        "too_long": "Ce message vocal est trop long. Restez sous {n} secondes.",
        "cannot_play": "Je n'ai pas pu le jouer : {why}.", "cannot_download": "Je n'ai pas pu télécharger ce message vocal. Réessayez.",
        "playing": "▶️ En cours de lecture sur le téléphone de {p} ({n} s).",
        "no_confirm": "Le téléphone de {p} n'a pas confirmé la réception. Il n'a peut-être pas d'internet en ce moment.",
        "app_offline": "L'application de {p} n'est pas connectée, le message n'a donc pas pu être joué.",
        "already_ended": "Cet appel est déjà terminé.", "ending": "Coupure de l'appel.",
        "could_not_cut": "⚠️ Je n'ai pas pu couper l'appel sur le téléphone de {p}, il est donc toujours en cours. Kavach continue de le protéger. Essayez d'appeler ou d'écrire à {p}.",
        "call_ended": "☎️ L'appel a été coupé. Envoyez un message vocal maintenant, il sera joué sur le téléphone de {p}.",
        "linked": "✅ Connecté. Vous recevrez ici les alertes Kavach du téléphone de {p}. Si une arnaque est détectée, vous pourrez couper l'appel d'ici et envoyer un message vocal qui sera joué sur son téléphone.",
        "link_bad": "Ce lien a expiré ou a déjà servi. Ouvrez l'application Kavach et touchez de nouveau « Connecter Telegram ».",
        "welcome": "Bonjour ! Je suis le bot Kavach. Pour relier cette discussion à votre famille, ouvrez l'application Kavach et touchez « Connecter Telegram ».",
        "voice_set": "C'est fait. Kavach parlera avec la voix {voice} quand il prendra un appel.",
    },
)

IT = Pack(
    code="it", tts="italian", stt="it", label="Italian", native="Italiano",
    decoy_name="Giuseppe Ferrari", decoy_city="Modena", decoy_bank="Banca del Centro", decoy_phone="cinque cinque cinque, zero uno zero zero",
    opening="Pronto? Ah, mi scusi, non ho sentito bene. Prego, continui, la ascolto.",
    stalls=("Mi scusi, eh, la linea si sente male. Può ripetere piano?",
            "Un momentino, sto cercando gli occhiali. Me lo ripeta, per favore.",
            "Ah, me lo sto scrivendo. Può dirlo ancora una volta, piano piano?"),
    examples=('Chiamante: "Il suo conto è bloccato." Tu: "Oh mamma mia… bloccato? Ma l\'ho usato stamattina. Di quale banca ha detto che è?"\n'
              'Chiamante: "Mandi i soldi adesso." Tu: "Adesso? Eh, prima devo trovare il libretto… è in un cassetto, mi pare. A nome di chi, scusi?"\n'
              'Chiamante: "Mi legga il codice." Tu: "Un codice? Mah, non è arrivato niente, il mio telefono è molto vecchio. Se cade la linea, a che numero la richiamo?"'),
    number_words=NUM_IT,
    warnings={
        "S7": "{p}, fermati… Non installare niente e non condividere lo schermo. Chiudi subito quella app. Metti giù il telefono e chiamami. Sono qui.",
        "S5": "{p}, fermati… Non dire quel codice. Nessuna banca e nessun agente chiede un codice o un PIN al telefono. Metti giù il telefono e chiamami. Sono qui.",
        "S6": "{p}, fermati… Non mandare soldi. Un vero agente non chiede mai un pagamento al telefono. Metti giù il telefono e chiama prima me. Sono qui.",
        "S3": "{p}, fermati… Non devi restare in questa chiamata. Un vero agente non ti chiede mai di tenere il segreto. Metti giù il telefono e chiamami. Sono qui.",
        "S2": "{p}, fermati… La polizia non arresta nessuno per telefono. È una truffa. Metti giù il telefono adesso. Sono qui.",
        "S1": "{p}, fermati… Credo che sia una truffa. La polizia e le banche non minacciano nessuno al telefono. Metti giù il telefono e chiamami. Sono qui.",
        "default": "{p}, fermati… Credo che questa chiamata non sia sicura. Per favore, metti giù il telefono e chiamami. Sono qui.",
    },
    t={
        "stages": {"S1": "Autorità", "S2": "Minaccia", "S3": "Segretezza", "S4": "Urgenza", "S5": "Richiesta di codici",
                   "S6": "Richiesta di pagamento", "S7": "Accesso remoto"}, "none_yet": "nessuna per ora", "risk": "Rischio {risk}/100",
        "caller": "Chiamante", "unknown": "numero sconosciuto",
        "warn_head": "🚨 Kavach: possibile chiamata truffa rilevata",
        "warn_tail": "Tocca qui sotto per chiudere la chiamata, oppure invia un messaggio vocale: verrà riprodotto sul telefono di {p}.",
        "escalate_head": "⚠️ Kavach: la chiamata sta peggiorando",
        "takeover_head": "🛡️ Kavach ha preso la chiamata (sta parlando la voce esca)",
        "end_button": "☎️ Chiudi la chiamata",
        "report_ready": "📄 Kavach: chiamata terminata. La bozza della segnalazione è pronta con {n} dato/i raccolto/i. Tocca i pulsanti qui sotto per dire se sono stati dati soldi o un codice/PIN, poi rileggi la bozza e segnala il caso a {hint}. (Solo una bozza: non è stato inviato niente.)",
        "doc_caption": "Bozza della denuncia per truffa (da rileggere prima di presentarla)",
        "doc_caption2": "Bozza aggiornata con le tue risposte (da rileggere prima di presentarla)",
        "money_yes": "Soldi inviati: Sì", "money_no": "Soldi inviati: No", "otp_yes": "Codice/PIN comunicato: Sì", "otp_no": "Codice/PIN comunicato: No",
        "saved": "Salvato: {label} = {answer}", "money_label": "Soldi inviati", "otp_label": "Codice/PIN comunicato", "yes": "Sì", "no": "No",
        "expired": "Questa domanda è scaduta.",
        "no_phone": "Non sono riuscito a inviarlo. Il telefono di {p} non è collegato a Kavach in questo momento.",
        "too_long": "Questo messaggio vocale è troppo lungo. Resta sotto i {n} secondi.",
        "cannot_play": "Non sono riuscito a riprodurlo: {why}.", "cannot_download": "Non sono riuscito a scaricare questo messaggio vocale. Riprova.",
        "playing": "▶️ In riproduzione sul telefono di {p} ({n} s).",
        "no_confirm": "Il telefono di {p} non ha confermato la ricezione. Forse adesso non ha internet.",
        "app_offline": "L'app di {p} non è collegata, quindi non è stato possibile riprodurlo.",
        "already_ended": "Quella chiamata è già terminata.", "ending": "Chiudo la chiamata.",
        "could_not_cut": "⚠️ Non sono riuscito a chiudere la chiamata sul telefono di {p}, quindi è ancora in corso. Kavach continua a proteggerla. Prova a chiamare o a scrivere a {p}.",
        "call_ended": "☎️ La chiamata è stata chiusa. Invia ora un messaggio vocale: verrà riprodotto sul telefono di {p}.",
        "linked": "✅ Collegato. Qui riceverai gli avvisi di Kavach per il telefono di {p}. Se viene rilevata una truffa potrai chiudere la chiamata da qui e inviare un messaggio vocale che verrà riprodotto sul suo telefono.",
        "link_bad": "Questo link è scaduto o è già stato usato. Apri l'app Kavach e tocca di nuovo «Collega Telegram».",
        "welcome": "Ciao! Sono il bot di Kavach. Per collegare questa chat alla tua famiglia, apri l'app Kavach e tocca «Collega Telegram».",
        "voice_set": "Fatto. Kavach parlerà con la voce {voice} quando prenderà una chiamata.",
    },
)

PACKS = {p.code: p for p in (EN, ES, PT, DE, FR, IT)}
DEFAULT = "en"


def get(code: str | None) -> Pack:
    return PACKS.get((code or DEFAULT).lower()[:2], EN)


def available() -> list[dict]:
    return [{"code": p.code, "label": p.label, "native": p.native} for p in PACKS.values()]
