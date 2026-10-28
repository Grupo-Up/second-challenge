# Contexto permanente do projeto - Agentes de IA para apoio aos cuidados de idosos

> **Instrução para o Claude:** leia este arquivo antes de propor funcionalidades, arquitetura, código ou alterações. Este documento registra a visão atual do produto. Preserve as decisões já tomadas, diferencie requisitos de hipóteses e atualize o arquivo quando houver novas decisões confirmadas pela equipe.

## 1. Visão geral

Estamos desenvolvendo uma ferramenta que utiliza agentes de inteligência artificial para **ajudar familiares e outras pessoas responsáveis a organizar os compromissos e cuidados cotidianos de uma pessoa idosa**.

A ideia central é aproveitar as informações que já aparecem nas conversas de um grupo familiar. Quando alguém comenta sobre uma consulta, exame ou outro compromisso, a ferramenta identifica os dados relevantes, verifica quem ficou responsável e pode **registrar o compromisso na agenda do responsável autorizado**.

**O objetivo é facilitar a coordenação entre as pessoas, reduzir esquecimentos e evitar que informações importantes se percam no meio das mensagens.** A IA deve apoiar a família e preservar a autonomia da pessoa idosa, não tomar decisões por ela.

## 2. Contexto e problema

Imagine um grupo de mensagens com uma pessoa idosa e familiares que participam de seus cuidados, como filhos, netos, tios e outros responsáveis. Neste documento, usamos o termo **"tutores" de maneira informal**, para indicar as pessoas que ajudam a organizar os cuidados; isso **não significa necessariamente tutela ou responsabilidade legal**.

Nesse grupo, os participantes costumam comentar, de maneira espontânea:

- Datas de consultas e exames;
- Horários e locais de compromissos;
- Quem poderá acompanhar ou levar a pessoa idosa;
- Alterações de horário, cancelamentos e remarcações;
- Lembretes e outras tarefas relacionadas à rotina de cuidados.

Hoje, essas informações podem ficar dispersas entre muitas mensagens. Alguém precisa encontrá-las, interpretar o que foi combinado e anotá-las manualmente. Isso favorece esquecimentos, informações desencontradas e dúvidas sobre quem assumiu determinada tarefa.

**Problema que queremos resolver:** transformar combinações feitas em conversas familiares em compromissos organizados, com responsáveis claros e registros em agenda, sem exigir que a família preencha formulários para cada nova informação.

## 3. Exemplo principal de uso

Cenário ilustrativo: um grupo de família inclui a idosa Dona Helena e familiares que ajudam em sua rotina.

1. Uma pessoa escreve no grupo: "A vó Helena tem consulta no cardiologista quinta-feira às 15h, na clínica do centro."
2. O sistema identifica que a mensagem descreve um possível compromisso e extrai: pessoa idosa, tipo de compromisso, data, horário e local.
3. Outro participante responde: "Eu levo ela", e o sistema relaciona a resposta ao participante correto e à consulta mencionada.
4. Depois de validar as informações e verificar a autorização de acesso, o agente de agenda cria o evento **na agenda do familiar responsável**.
5. O sistema informa ao grupo ou às pessoas envolvidas, conforme a configuração autorizada, que o compromisso foi registrado.
6. Se posteriormente alguém disser que a consulta mudou, a ferramenta deve reconhecer a atualização e evitar criar um compromisso duplicado.

**Atenção:** "quinta-feira", "amanhã" e outras datas relativas devem ser interpretadas com base na data da mensagem e no fuso horário. Em caso de ambiguidade, o sistema deve pedir esclarecimento antes de agendar.

### Exemplo de dado estruturado (meramente ilustrativo)

```json
{
  "tipo": "consulta",
  "pessoa_idosa": "Dona Helena",
  "especialidade": "cardiologia",
  "data": null,
  "horario": "15:00",
  "local": "clínica do centro",
  "responsavel": null,
  "estado": "aguardando_identificacao_do_responsavel_e_validacao_da_data"
}
```

Campos `null` não devem ser preenchidos por adivinhação. Eles são resolvidos a partir do contexto confiável da conversa ou de uma pergunta ao grupo.

## 4. Funcionamento esperado

### Entrada de informações

- O sistema recebe mensagens **somente de canais/grupos autorizados**, usando um meio de integração que ainda será definido.
- A entrada pode ser texto e, futuramente, áudios transcritos, se isso fizer parte do escopo aprovado.
- Não se deve presumir que uma API permita ler automaticamente qualquer grupo comum de WhatsApp. As limitações técnicas e as regras do canal escolhido precisam ser verificadas antes da implementação.

### Interpretação

- Identificar se uma mensagem descreve um compromisso relevante ou apenas uma conversa cotidiana.
- Extrair data, horário, local, pessoa idosa, responsável e natureza do compromisso quando esses dados estiverem disponíveis.
- Considerar mensagens relacionadas dentro da mesma conversa, inclusive quando o responsável é identificado posteriormente.
- Reconhecer atualizações, cancelamentos e remarcações.
- Detectar incerteza ou informações conflitantes e solicitar confirmação quando necessário.

### Organização e ação

- Verificar se o responsável indicado realmente aceitou ou foi autorizado a assumir a tarefa.
- Conferir se a ferramenta tem autorização para consultar ou criar eventos na agenda desse responsável.
- Evitar duplicidades e verificar conflitos de horário quando possível.
- Criar ou atualizar um evento somente com informações suficientes e com as permissões adequadas.
- Confirmar o resultado da operação; nunca informar que agendou se a API de calendário não confirmar a criação.
- Permitir correção, cancelamento e revisão humana.

## 5. Papéis sugeridos para os agentes

Esta é uma **proposta inicial de divisão de responsabilidades**, não uma arquitetura imutável.

### Agente 1 - Interpretação e validação da conversa

Responsável por identificar compromissos nas mensagens, organizar as informações, relacionar falas do mesmo assunto, reconhecer dados ausentes e formular perguntas de esclarecimento quando necessário.

**Saída esperada:** um compromisso estruturado, com indicação do que está confirmado e do que ainda precisa ser validado.

### Agente 2 - Coordenação e agenda

Responsável por identificar o tutor encarregado, conferir autorizações e disponibilidade, criar/atualizar eventos na agenda e comunicar o resultado.

**Saída esperada:** compromisso corretamente registrado ou uma explicação clara sobre o impedimento e o que precisa ser resolvido.

**Princípio:** os agentes podem colaborar, mas ações externas (como escrever no calendário de alguém) devem ter regras determinísticas de autorização e validação; não dependem exclusivamente do julgamento de uma LLM.

## 6. Pessoas envolvidas e permissões

- **Pessoa idosa:** participante central do cuidado; seus desejos, autonomia e privacidade devem ser respeitados. Estar no grupo não significa autorizar automaticamente o tratamento irrestrito de suas informações.
- **Familiares/tutores:** participantes que compartilham informações e podem assumir compromissos; cada um controla o acesso à própria agenda.
- **Responsável pela administração do grupo:** papel operacional a definir; não deve receber automaticamente acesso a dados privados de todos.
- **Sistema de IA:** organiza informações e executa apenas as ações autorizadas.

O sistema não deve decidir sozinho quem será obrigado a levar a pessoa idosa a uma consulta. Quando o responsável não estiver claramente combinado, deve perguntar ou oferecer uma opção de confirmação.

## 7. Requisitos e critérios de sucesso para o MVP

Para um primeiro protótipo, priorizar:

1. Receber mensagens de um grupo **simulado ou por uma integração explicitamente autorizada**.
2. Identificar mensagens sobre consultas e compromissos.
3. Extrair corretamente datas, horários, local e pessoa idosa, quando presentes.
4. Reconhecer o responsável a partir de mensagens do grupo, sem assumir compromissos não aceitos.
5. Pedir esclarecimentos em casos incompletos ou ambíguos.
6. Criar o evento em uma agenda de teste ou agenda autorizada.
7. Evitar eventos duplicados e permitir atualizações/cancelamentos em casos básicos.
8. Exibir um histórico mínimo das ações executadas, sem exposição desnecessária de informações sensíveis.

**Cenário de sucesso:** a família conversa normalmente sobre uma consulta, um familiar assume o acompanhamento e o sistema registra o compromisso na agenda correta, sem exigir que os usuários cadastrem manualmente todos os detalhes.

**Não considerar sucesso:** criar um evento com data inventada, atribuir responsabilidade a alguém sem confirmação ou dizer que o calendário foi atualizado quando a operação falhou.

## 8. Privacidade, segurança e ética

As conversas podem conter informações de saúde e outros dados pessoais sensíveis. O projeto deve adotar a LGPD e o princípio de minimização de dados como requisitos desde o início.

- Deixar claro para todos os participantes quais mensagens são processadas, para qual finalidade e como desativar a participação.
- Avaliar a base legal adequada para os tratamentos de dados, especialmente os relacionados à saúde; não presumir que o simples ingresso no grupo equivale a consentimento válido.
- Armazenar somente o necessário para organizar os compromissos.
- Restringir acesso a mensagens, calendários, credenciais e registros por usuário/grupo.
- Não compartilhar informações de saúde com terceiros sem fundamento e autorização adequados.
- Evitar registrar conteúdo bruto e dados sensíveis em logs de desenvolvimento.
- Não oferecer diagnóstico, prescrição ou orientação médica como se fosse profissional de saúde.
- Dar prioridade à autonomia e às decisões da pessoa idosa e de seus familiares.
- Permitir revisar, corrigir e excluir informações conforme as regras e obrigações aplicáveis.

## 9. Requisitos acadêmicos do projeto

O projeto faz parte de um desafio de desenvolvimento de uma ferramenta voltada ao bem-estar em comunidade. Conforme o escopo discutido pela equipe, devem ser contemplados:

- Pelo menos **dois agentes de IA colaborando**;
- **Uma rede neural simples**, desenvolvida e testada pela equipe;
- **Base de conhecimento** utilizada pela solução;
- **MLOps** e experimentação/avaliação do modelo;
- Uso de agentes com acesso a **API**;
- **Versionamento do código**;
- Tratamento de aspectos **éticos e de explicabilidade**;
- Referência a pelo menos **um recurso publicado nos últimos dois anos**;
- Um **MVP funcional**, demonstrável com perfis fictícios e situações simuladas.

A rede neural ainda **não tem função definitivamente escolhida**. Uma possibilidade é usá-la para classificar mensagens como compromisso, alteração/cancelamento ou conversa comum. Isso deve ser testado antes de ser adotado como decisão arquitetural.

## 10. Decisões tomadas e decisões pendentes

### Já definido pela proposta

- Público principal: grupo composto pela pessoa idosa e pessoas que participam de seus cuidados.
- Interação principal: mensagens já trocadas em um grupo.
- Valor principal: captar informações de compromissos e organizá-las na agenda de um responsável.
- A organização dos cuidados deve ser colaborativa, sem substituir a autonomia das pessoas.
- O protótipo pode usar dados fictícios e cenários simulados.
- **Framework de agentes: CrewAI**, no formato JSONC (`crew_extrair.jsonc`, `crew_responder.jsonc` e `agents/`). O motivo técnico está registrado em `ARQUITETURA.md` §11: no formato YAML, um guardrail em função Python é convertido silenciosamente em guardrail de LLM, o que trocaria as validações determinísticas do projeto por julgamento probabilístico.
- **Um agente nesta etapa**, com duas tarefas sequenciais. O segundo agente — o coordenador que confere autorização e cria eventos na agenda, previsto na seção 5 — entra junto com a integração de calendário. Até lá, o requisito de "dois agentes colaborando" da seção 9 permanece **em aberto**.
- **Memória por grupo.** O sistema guarda o compromisso pendente de cada grupo e o funde com o que a mensagem seguinte trouxer, atendendo ao passo 3 da seção 3 ("eu levo ela"). A fusão é código determinístico, não prompt: campo vazio na mensagem nova não apaga dado já confirmado. Nesta etapa o armazenamento é um dicionário em memória; **banco de dados continua em aberto**, com SQLite como próximo passo.
- **O sistema não preenche o responsável sozinho.** Quando alguém se oferece sem se identificar ("eu levo ela"), a resposta reconhece a oferta e pede o nome. Atribuir a tarefa a partir de um apelido do WhatsApp violaria a seção 6.

### Ainda não definido - não presumir como decisão

- Canal de mensagens (WhatsApp, outro mensageiro ou interface própria).
- Método autorizado de acesso às mensagens e suas eventuais limitações.
- Provedor de calendário (Google Calendar, Outlook ou outro).
- Modelo de linguagem, API, custos e infraestrutura de execução. (O protótipo usa `gpt-oss-20b` via Groq, mas isso não foi fechado como decisão de produto.)
- Papel final da rede neural, dataset e métricas de treinamento.
- Banco de dados e tecnologias definitivas do frontend/backend.
- Forma exata de confirmação dos agendamentos, notificações e controle de acesso.
- Suporte a múltiplos idosos no mesmo grupo, mensagens de áudio e outras tarefas além de compromissos.

## 11. Orientações permanentes para o Claude

Ao ajudar neste repositório:

1. **Consulte este `CLAUDE.md`** e trate-o como fonte principal do contexto do projeto.
2. **Preserve o problema central:** organizar compromissos comentados em grupos de apoio a idosos. Não transformar a proposta em rede social, aplicativo genérico de saúde, chatbot médico ou sistema para encontrar amigos sem solicitação expressa.
3. **Separe fatos de sugestões.** Se uma tecnologia ou funcionalidade não estiver definida, apresente-a como opção, não como algo já implementado ou decidido.
4. **Explique como os agentes colaboram**, quais informações trocam e onde entram as validações, a rede neural e as APIs.
5. **Priorize um MVP pequeno e demonstrável.** Prefira fluxos funcionais e testáveis a integrações complexas e pouco confiáveis.
6. **Não invente dados:** se não souber data, horário, local ou responsável, sinalize a ausência e proponha uma pergunta de esclarecimento.
7. **Não execute ações externas sem verificar autorização, identidade, permissões e condições de segurança.**
8. **Respeite a LGPD**, a segurança das informações de saúde e a privacidade das pessoas do grupo.
9. **Documente decisões novas** nesta seção ou em um registro de decisões quando a equipe efetivamente as confirmar; não reescreva unilateralmente a visão do produto.
10. Para cada implementação proposta, explique **qual problema ela resolve, por que é necessária ao MVP e como será validada**.

---

**Resumo em uma frase:** queremos que um sistema de agentes de IA acompanhe, de forma autorizada, as combinações sobre cuidados feitas em um grupo familiar e transforme compromissos, como consultas médicas, em eventos na agenda da pessoa responsável, sem perder a confirmação humana nem a privacidade.
