# Guida docente · Redazione PA agentica (20–25 minuti)

**Obiettivo:** far vedere il confine fra automazione (avvio periodico del workflow), skill/metodo (regole editoriali) e agente (scelta dinamica della notizia e delle verifiche) e il punto in cui la persona conserva il controllo.

## Sequenza consigliata

**0–3 minuti — Domanda iniziale.** «Se impostassi un feed RSS che ogni mattina genera automaticamente un riassunto, avrei già creato un agente?» No: sarebbe essenzialmente un'automazione con un componente AI.

**3–7 minuti — Modalità DEMO.** Esegui Actions → Ricerca → DEMO. Mostra la nuova Issue, spiega che questa fase simula la selezione senza chiamare modelli. In aula offline/quote esaurite puoi comunque condurre la dimostrazione concettuale.

**7–13 minuti — Modalità LIVE.** Scegli un RSS pubblico insieme all'aula, esegui LIVE e apri la Issue generata. Se l'agente decide di scartare tutti gli articoli, è un esito sensato: non forzare un post.

**13–18 minuti — Valutazione.** Chiedi ai partecipanti: «Quale frase pubblichereste? Dove la verifichereste? Cosa è nella fonte e cosa è una rielaborazione?». Correggi il testo nella pagina e usa RIVEDI.

**18–22 minuti — GO o SCARTA.** Se il post è verificato, usa GO su un account di prova. In caso contrario usa SCARTA. Mostra la registrazione nel thread della Issue.

**22–25 minuti — Debrief.** «L'IA ha potuto selezionare e proporre. Perché non ha ricevuto le credenziali social? Che cosa succede se non riesce a leggere una fonte?».

## Preparazione indispensabile PRIMA della lezione

- Repository pubblico e GitHub Pages funzionanti.
- Una simulazione DEMO già testata.
- API key Groq Free valida, modello configurato disponibile e quote sufficienti.
- Account Bluesky di prova con App Password valida; `publishing_enabled=true` soltanto nel momento della demo live.
- Un RSS *di riserva* che sia accessibile con HTTP da GitHub Actions, oltre a quello suggerito dall'aula.
- Una Issue LIVE pronta come piano B se il feed dell'aula restituisce 403 o il modello esaurisce le quote.

## Domande di verifica didattica

1. L'agente decide tutto? **No:** sceglie quali fonti approfondire e se proporre, entro un numero ristretto di tentativi. Non decide di pubblicare.
2. Perché il sistema può terminare senza una proposta? **Perché la fonte può essere insufficiente o fuori tema.**
3. Perché GitHub Issues? **Perché documenta proposta, revisioni e autorizzazione**, con identità autenticata.
4. Chi corregge un errore pubblicato? **Le persone responsabili dell'account e del processo.** L'automazione non sostituisce il presidio editoriale.
5. Il gratuito è adatto alla produzione PA? **Non automaticamente:** servono valutazione contrattuale, privacy, sicurezza, resilienza e governance.

## Il confine che va dichiarato con chiarezza

Il modello riceve testo da fonti pubbliche, potenzialmente inesatto o manipolato, e una lista limitata di azioni di sola lettura. Se il modello propone un post non supportato dalle fonti, l'operatore deve rifiutarlo o correggerlo. Non utilizzare la demo come canale ufficiale dell'Ente.
