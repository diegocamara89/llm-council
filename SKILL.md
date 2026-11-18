---
name: llm-council
description: Roda uma decisao dificil por varios modelos de familias diferentes (OpenAI pelo Codex; Mistral e GLM pelo vibe), com revisao anonima e fechamento conferido pelo Claude. Use SO quando o usuario pedir explicitamente - "council", "llm-council", "roda o council", "passa pelo council", "quero varias opinioes sobre essa decisao". Nao use por iniciativa propria nem para fato, calculo, resumo, texto ou o que se resolve medindo.
---

# llm-council - varias opinioes independentes sobre uma decisao

Uma decisao, analisada por modelos de **familias diferentes** (OpenAI pelo Codex; Mistral e GLM pelo vibe),
cada um com uma lente; um modelo fecha a analise e o Claude **confere** antes de entregar. Metodo inspirado
no LLM Council de Andrej Karpathy e na skill de Ole Lehmann; redacao propria.

O motor e `scripts/council.py`, sobre o CLI `codex` (gpt-6.1-sol) e o CLI `vibe`. Chame o script; nao remonte o fluxo na mao.

---

## Quando vale

Vale para decisao com opcoes reais e custo de errar: ferramenta ou arquitetura, construir ou nao,
qual caminho priorizar, um plano antes de executar.

Nao vale quando a resposta e fato, calculo ou algo que um teste resolve (faca o teste), nem para
pedido de resumo, texto ou codigo, nem para decisao facil de desfazer. Se o usuario disse que a cota
do Codex ou do vibe esta no fim, avise o custo antes.

---

## Modos

| Modo | Quando | Pedidos | Custo aproximado |
|---|---|---|---|
| **leve** (padrao) | a maioria das decisoes | 3 conselheiros + fechamento = 4 | 4 pedidos (1 no Codex, 3 no vibe); tempo ainda nao medido com o Codex |
| **completo** | o usuario pediu, ou a decisao e cara de desfazer | 5 + 3 revisores + fechamento = 9 | nao medido |

O texto da decisao vai a servicos externos (Codex e vibe): mande so o que o usuario autoriza;
credencial e senha nao. Sem Codex nem vibe, `--prompts` gera os prompts para 3 subagentes do Claude
(`model: sonnet`, "Nao leia arquivos nem use ferramentas"): sao tres visoes do mesmo modelo e gastam cota do Claude Code.

**Debate** (`--debate`, soma a leve ou completo): segunda rodada em que cada conselheiro, com a mesma
lente e o mesmo modelo, le os outros pareceres por letra, rebate o mais fragil de cada um e fecha com
"Posicao final". O fechamento diz quem mudou de posicao e por qual argumento. Use quando o usuario
pedir debate, ou quando os pareceres da primeira rodada brigarem sem que se veja quem tem razao.
Custo: +3 pedidos no leve (7 no total), +5 no completo (14); tokens: estimativa de ~1,7x o modo base, nao medida.

Antes de rodar, diga em uma linha: modo e pedidos. Retentativas somam tempo (ate 4 por
pedido, 300 s cada); o script mostra o progresso de cada fase.

Lentes e modelos (definidos em `council.py`; escolha de 17/11/2026 por diversidade de familia, **sem nota
medida de julgamento**: os testes da avaliacao-vibe medem acerto com gabarito, nao qualidade de decisao):

| Lente | Pergunta que ela faz | Modelo | Leve | Completo |
|---|---|---|---|---|
| auditor | o que pode falhar, quanto custa, que premissa esta sem prova | Codex gpt-6.1-sol | sim | sim |
| evidencia | que dado, medicao ou teste barato decidiria; o que esta sendo afirmado sem prova | GLM 5.3, vibe | sim | sim |
| operador | o menor passo verificavel desta semana e o que ele provaria | Mistral Large 4, vibe | sim | sim |
| alternativa | o caminho fora das opcoes dadas que renderia mais com o mesmo esforco | Mistral Large 4, vibe | - | sim |
| estranho | o que soa estranho para quem chega agora; recebe so a pergunta | GLM 5.3, vibe | - | sim |

Fechamento: GLM 5.3 (vibe); se cair, Mistral Large 4 e depois Codex. Revisores do completo: Codex, GLM 5.3 e
Large 4 (tres familias). Revisores veem so a decisao e os pareceres; o fechamento ve tambem o contexto.
Versoes anteriores usavam o agy (Gemini); ficaram de fora o Gemini 4 Argon (errou fato atual da web) e o Carbon (estourou 300 s num conselho real). Pedido ao Codex: limite de 240 s e 1 repeticao, depois reserva no vibe.

**Escolha dos modelos pelo ambiente:** `COUNCIL_CODEX_MODEL`, `COUNCIL_VIBE_MODEL_1` e `COUNCIL_VIBE_MODEL_2` (apelidos do `~/.vibe/config.toml`).
Os padroes (gpt-6.1-sol, zai-glm-5-3, mistral-large-4) foram os de melhor nota na avaliacao do autor.

**Reserva entre executores:** pedido que falha (cota, erro, vazio, timeout) e refeito no outro: Codex -> vibe GLM 5.3;
vibe -> Codex. O aviso diz quem foi refeito. Repetir modelo entre cadeiras e aceito.

---

## Passo 1 - sigilo e enquadramento

1. **Credencial primeiro.** Credencial ou senha nunca vao no texto. Dado de caso pode ir (ver acima), mas escreva so o necessario.
2. **Nao** leia `memory/`, pastas de caso nem "arquivos de contexto" genericos para enriquecer a
   pergunta. Use o que o usuario disse e os arquivos que ele citou, e escreva **voce** um resumo
   curto; nunca cole conteudo bruto.
3. **Confira os fatos do enunciado** antes de enviar: premissa falsa no enunciado ja produziu
   opiniao unanime e errada. Nao inclua a sua hipotese nem resultado de rodada anterior.
4. Decisao + resumo: ate **4 mil caracteres** (o script recusa acima).
5. Havendo resumo de contexto, **mostre ao usuario o texto** antes de enviar.

## Passo 2 - rodar (leve ou completo)

Grave a decisao e o resumo em `.txt` na pasta temporaria da sessao e rode:

```bash
python ~/.claude/skills/llm-council/scripts/council.py --modo leve --pergunta decisao.txt --contexto resumo.txt
```

Com debate: acrescente `--debate`. Cada item de `respostas` ganha `replica` (vazia se aquela cadeira
falhou na segunda rodada; o aviso diz qual).

O script usa pasta de trabalho vazia (`~/.council-cwd`), sorteia as letras, corta pareceres
longos e faz a reserva entre executores (ver acima). So para com `COTA` quando Codex e vibe estao sem cota.

Saida JSON: `status`, `veredito`, `respostas` (letra, `papel` = lente, modelo, texto), `revisoes`,
`chamadas`, `baldes`, `avisos`. Codigo 0 ok, 1 nao fechou, 2 entrada invalida, 3 cota.

| status | O que fazer |
|---|---|
| `OK` | passo 3 |
| `COTA` | Codex e vibe sem cota: **pare e avise o usuario** (conferir o limite do Codex e o painel do vibe); mostre as `respostas` que ja vieram; nao espere a cota voltar; so rode `--prompts` com subagentes se ele pedir |
| `POUCAS_RESPOSTAS` | diga quem nao respondeu (`avisos`) e ofereca rodar de novo; nao feche voce como se fosse o conselho |
| `SINTESE_FALHOU` | mostre os pareceres e ofereca repetir so o fechamento |

## Passo 2-S - reserva sem Codex nem vibe

So a pedido do usuario (ou com os dois executores fora). Gere os prompts com o mesmo texto do motor:

```bash
python ~/.claude/skills/llm-council/scripts/council.py --prompts --modo leve --pergunta decisao.txt --contexto resumo.txt
```

Lance **3 subagentes em paralelo** (ferramenta Agent, `model: sonnet`), um prompt cada, e acrescente
no inicio: "Nao leia arquivos nem use ferramentas: responda so com o texto abaixo." O fechamento e
seu, no formato do passo 4. Avise que sao tres visoes do mesmo modelo e que gasta cota do Claude Code.

## Passo 3 - conferencia (obrigatoria)

Quem responde ao usuario e voce, nao o fechamento.

1. Pegue a secao "Premissas a conferir".
2. Confira cada uma que der (arquivo, medida, teste, documentacao): **conferi** / **nao conferi** /
   **falsa**.
3. Premissa central falsa: diga isso primeiro e **nao endosse** a resposta.
4. Pareceres do mesmo modelo valem como um so.

## Passo 4 - entregar no chat

Entregue como mensagem normal da conversa, em portugues do Brasil. Cabecalho com `chamadas` e `baldes` do JSON;
depois as secoes do fechamento (resposta curta, argumentos que se sustentam, riscos e lacunas,
desacordo que continua, proximo passo) e, no fim, a conferencia:

```
Conselho: <tema> (modo leve · 4 pedidos · codex 1 / vibe 3)
...
Conferencia
- conferi: ...
- alegado, nao conferi: ...
```

Avisos do script (cadeira sem resposta, reserva Sonnet) em uma linha no fim. Registro em arquivo,
apenas a pedido: na pasta de trabalho dele, com o caminho completo.

---

## Manutencao

- IDs em `scripts/council.py` (`CODEX`, `GLM`, `LARGE`, `PRESIDENTES`, `RESERVA`); modelos do vibe
  so existem se estiverem em `~/.vibe/config.toml`. Revise quando a avaliacao dos modelos mudar.
- O padrao de erro de cota do vibe (`_RE_COTA_VIBE`) nao foi verificado contra um limite real: se nao casar, o
  erro vira `ERROR` e a cadeira cai na reserva do mesmo jeito.
- Testes puros (Codex e vibe simulados, sem cota): `python tests/test_council.py`.
