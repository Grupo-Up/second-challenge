import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';

import qrcode from 'qrcode-terminal';

// Endereco da API que executa os agentes de IA
const API_AGENTE = process.env.API_AGENTE ?? 'http://localhost:8000/agente';

// Quanto esperar pela API antes de desistir. Sem isso o bot espera para
// sempre, e o grupo fica preso no "ainda estou analisando".
const TIMEOUT_API = 90_000;

// Comandos que acionam os agentes. A chave vai para a API e decide por
// onde a mensagem entra no grafo.
const COMANDOS = {
  '!agenda': 'agenda',
  '!compromisso': 'compromisso',
  '!andamento': 'andamento',
  '!duvida': 'duvida',
};

// Comandos que o proprio bot responde, sem chamar a API
const AJUDA =
  'Comandos deste assistente:\n\n' +
  '!agenda <informacao> - informa uma consulta, exame ou retorno, ' +
  'o horario, o local ou quem vai acompanhar.\n' +
  'Exemplo: !agenda a vo Helena tem consulta no cardiologista quinta as 15h\n\n' +
  '!compromisso - mostra o que ja esta combinado e o que ainda falta.\n\n' +
  '!andamento <pergunta> - pergunta sobre o compromisso em aberto.\n' +
  'Exemplo: !andamento quem vai levar a vo?\n\n' +
  '!duvida <pergunta> - pergunta sobre o cuidado da pessoa idosa, ' +
  'respondida a partir do Guia do Cuidador.\n' +
  'Exemplo: !duvida como prevenir quedas em casa?\n\n' +
  '!ajuda - mostra esta lista.\n\n' +
  'Nada e gravado em agenda nesta etapa: o assistente apenas organiza ' +
  'a informacao e confirma com o grupo.\n\n' +
  'As respostas do !duvida vem do Guia do Cuidador e nao substituem a ' +
  'avaliacao de um profissional de saude.';

// Tira acento para variantes acentuadas do comando valerem igual
function semAcento(texto) {
  return texto.normalize('NFD').replace(/[̀-ͯ]/g, '');
}

// Separa o comando do resto da mensagem
function lerComando(conteudo) {
  const [primeira, ...resto] = conteudo.trim().split(/\s+/);
  const comando = semAcento(primeira).toLowerCase();

  return { comando, texto: resto.join(' ').trim() };
}

// Grupos com um pedido ainda em andamento
const emAndamento = new Set();

// Responde tambem as mensagens do proprio numero, para testar sozinho
const RESPONDER_PROPRIAS = process.env.RESPONDER_PROPRIAS === '1';

// Com DEBUG_BOT=1 registra o estado da conexao e os metadados de cada
// evento recebido, antes dos descartes. So metadados: nenhum conteudo de
// mensagem vai para o log (CLAUDE.md, secao 8).
const DEBUG_BOT = process.env.DEBUG_BOT === '1';

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
// O grupo vai junto: e ele que separa o compromisso de uma familia do de
// outra, e o que liga "eu levo ela" a consulta combinada antes.
async function consultarAgente(mensagem, dataMensagem, grupo, autor, comando) {
  const resposta = await fetch(API_AGENTE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      mensagem,
      data_mensagem: dataMensagem,
      grupo,
      autor,
      comando,
    }),
    signal: AbortSignal.timeout(TIMEOUT_API),
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

    if (DEBUG_BOT) {
      console.log(
        '[debug] connection.update:',
        connection ?? '(sem mudanca)',
        '| qr:',
        qr ? 'sim' : 'nao',
        '| statusCode:',
        lastDisconnect?.error?.output?.statusCode ?? '-',
      );
    }

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
    // Antes de qualquer descarte: e aqui que se ve se a mensagem chegou
    if (DEBUG_BOT) {
      for (const msg of messages) {
        console.log(
          '[debug] upsert | type:',
          type,
          '| fromMe:',
          msg.key.fromMe === true,
          '| jid:',
          msg.key.remoteJid,
          '| tem texto:',
          extrairTexto(msg.message).length > 0,
        );
      }
    }

    if (type !== 'notify') return;

    for (const msg of messages) {
      // Ignora mensagens enviadas pelo próprio bot
      if (msg.key.fromMe && !RESPONDER_PROPRIAS) continue;

      const grupo = msg.key.remoteJid;

      // Processa apenas mensagens de grupos
      if (!grupo?.endsWith('@g.us')) continue;

      const conteudo = extrairTexto(msg.message).trim();

      // Conversa comum nao e processada, para nao mandar o grupo inteiro
      // para a API (CLAUDE.md, secao 8)
      if (!conteudo.startsWith('!')) continue;

      const { comando, texto: pedido } = lerComando(conteudo);

      // Registra apenas o grupo e qual comando foi usado. Conteudo de
      // mensagem nao vai para o log: pode conter dados de saude e outros
      // dados pessoais (CLAUDE.md, secao 8).
      console.log('ID do grupo:', grupo, '| comando:', comando);

      // Comando de teste
      if (comando === '!ping') {
        try {
          await bot.sendMessage(grupo, { text: 'Bot funcionando!' });
        } catch (erro) {
          console.error('Erro ao responder:', erro);
        }
        continue;
      }

      // A ajuda e respondida aqui mesmo: nao depende da API estar no ar,
      // que e justamente quando a pessoa mais precisa dela
      if (comando === '!ajuda' || !COMANDOS[comando]) {
        try {
          await bot.sendMessage(grupo, { text: AJUDA });
        } catch (erro) {
          console.error('Erro ao responder:', erro);
        }
        continue;
      }

      // !compromisso nao leva texto; os outros precisam
      if (!pedido && comando !== '!compromisso') {
        const SEM_TEXTO = {
          '!andamento':
            'Escreva a pergunta depois do comando. Exemplo: !andamento quem vai levar a vo?',
          '!duvida':
            'Escreva a pergunta depois do comando. Exemplo: !duvida como prevenir quedas em casa?',
        };

        await bot.sendMessage(grupo, {
          text:
            SEM_TEXTO[comando] ??
            'Escreva a informacao depois do comando. Exemplo: !agenda a vo Helena tem consulta no cardiologista quinta-feira as 15h.',
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

        // Nome de quem escreveu. E o que permite resolver "eu levo ela":
        // sem ele, "eu" nao identifica ninguem e o responsavel fica nulo.
        const autor = msg.pushName ?? null;

        const resposta = await consultarAgente(
          pedido,
          dataMensagem,
          grupo,
          autor,
          COMANDOS[comando],
        );

        await bot.sendMessage(grupo, { text: resposta });
      } catch (erro) {
        console.error('Erro ao consultar o agente:', erro);

        await bot.sendMessage(grupo, {
          text:
            erro.name === 'TimeoutError'
              ? 'A analise demorou demais e foi cancelada. Tente de novo em instantes.'
              : 'Nao consegui analisar a mensagem agora. Tente de novo em instantes.',
        });
      } finally {
        emAndamento.delete(grupo);
        await bot.sendPresenceUpdate('paused', grupo);
      }
    }
  });
}

iniciarBot().catch(console.error);
