import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';

import qrcode from 'qrcode-terminal';

// Endereco da API que executa os agentes de IA
const API_AGENTE = process.env.API_AGENTE ?? 'http://localhost:8000/agente';

// Comando que aciona os agentes
const COMANDO = '!agenda';

// Grupos com um pedido ainda em andamento
const emAndamento = new Set();

// Responde tambem as mensagens do proprio numero, para testar sozinho
const RESPONDER_PROPRIAS = process.env.RESPONDER_PROPRIAS === '1';

// Algumas mensagens chegam embrulhadas (mensagens temporarias,
// visualizacao unica), entao desembrulha antes de ler o texto
function extrairTexto(message) {
  if (!message) return '';

  const interno =
    message.ephemeralMessage?.message ??
    message.viewOnceMessage?.message ??
    message.viewOnceMessageV2?.message ??
    message.documentWithCaptionMessage?.message;

  if (interno) return extrairTexto(interno);

  return message.conversation ?? message.extendedTextMessage?.text ?? '';
}

// Envia a mensagem para a API e devolve a resposta dos agentes.
// A data serve de referencia para "amanha", "quinta-feira" e afins.
async function consultarAgente(mensagem, dataMensagem) {
  const resposta = await fetch(API_AGENTE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mensagem, data_mensagem: dataMensagem }),
  });

  if (!resposta.ok) {
    throw new Error(`API respondeu ${resposta.status}`);
  }

  const dados = await resposta.json();
  return dados.resposta;
}

async function iniciarBot() {
  // Salva a autenticação do WhatsApp
  const { state, saveCreds } = await useMultiFileAuthState('./auth');

  // Cria a conexão com o WhatsApp
  const bot = makeWASocket({
    auth: state,
  });

  // Atualiza as credenciais
  bot.ev.on('creds.update', saveCreds);

  // Monitora o estado da conexão
  bot.ev.on('connection.update', (update) => {
    const { connection, qr, lastDisconnect } = update;

    if (qr) {
      qrcode.generate(qr, { small: true });
    }

    if (connection === 'open') {
      console.log('Bot conectado ao WhatsApp!');
    }

    if (connection === 'close') {
      const status = lastDisconnect?.error?.output?.statusCode;

      if (status !== DisconnectReason.loggedOut) {
        console.log('Reconectando...');
        setTimeout(() => {
          iniciarBot().catch(console.error);
        }, 3000);
      } else {
        console.log('Sessão desconectada.');
      }
    }
  });

  // Escuta novas mensagens
  bot.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;

    for (const msg of messages) {
      // Ignora mensagens enviadas pelo próprio bot
      if (msg.key.fromMe && !RESPONDER_PROPRIAS) continue;

      const grupo = msg.key.remoteJid;

      // Processa apenas mensagens de grupos
      if (!grupo?.endsWith('@g.us')) continue;

      const conteudo = extrairTexto(msg.message).trim();

      // Registra apenas o grupo e se o comando foi reconhecido.
      // Conteudo de mensagem nao vai para o log: pode conter dados de
      // saude e outros dados pessoais (CLAUDE.md, secao 8).
      console.log(
        'ID do grupo:',
        grupo,
        '| comando reconhecido:',
        conteudo.startsWith(COMANDO) || conteudo === '!ping' ? 'sim' : 'nao',
      );

      // Responde ao comando de teste
      if (conteudo === '!ping') {
        try {
          await bot.sendMessage(grupo, {
            text: 'Bot funcionando!',
          });
        } catch (erro) {
          console.error('Erro ao responder:', erro);
        }
        continue;
      }

      // Aciona os agentes apenas com o comando, para nao chamar
      // a API a cada mensagem do grupo
      if (!conteudo.startsWith(COMANDO)) continue;

      const pedido = conteudo.slice(COMANDO.length).trim();

      if (!pedido) {
        await bot.sendMessage(grupo, {
          text: `Escreva a informacao depois do comando. Exemplo: ${COMANDO} a vo Helena tem consulta no cardiologista quinta-feira as 15h.`,
        });
        continue;
      }

      // Evita varios pedidos simultaneos do mesmo grupo
      if (emAndamento.has(grupo)) {
        await bot.sendMessage(grupo, {
          text: 'Ainda estou analisando a mensagem anterior. Aguarde um instante.',
        });
        continue;
      }

      emAndamento.add(grupo);

      try {
        // Os agentes levam alguns segundos, entao mostra "digitando"
        await bot.sendPresenceUpdate('composing', grupo);

        // Data em que a mensagem chegou, referencia para datas relativas
        const dataMensagem = new Date(
          (Number(msg.messageTimestamp) || Math.floor(Date.now() / 1000)) * 1000,
        )
          .toLocaleDateString('sv-SE', { timeZone: 'America/Sao_Paulo' });

        const resposta = await consultarAgente(pedido, dataMensagem);

        await bot.sendMessage(grupo, { text: resposta });
      } catch (erro) {
        console.error('Erro ao consultar o agente:', erro);

        await bot.sendMessage(grupo, {
          text: 'Nao consegui analisar a mensagem agora. Tente de novo em instantes.',
        });
      } finally {
        emAndamento.delete(grupo);
        await bot.sendPresenceUpdate('paused', grupo);
      }
    }
  });
}

iniciarBot().catch(console.error);
