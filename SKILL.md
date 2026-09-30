---
name: llm-council
description: Roda uma decisao dificil por varios modelos de familias diferentes (Gemini e Claude, pelo agy), com revisao anonima e fechamento conferido pelo Claude. Use SO quando o usuario pedir explicitamente - "council", "llm-council", "roda o council", "passa pelo council", "quero varias opinioes sobre essa decisao". Nao use por iniciativa propria nem para fato, calculo, resumo, texto ou o que se resolve medindo.
---

# llm-council - varias opinioes independentes sobre uma decisao

Uma decisao, analisada por modelos de **familias diferentes** (Gemini e Claude, pelo agy), cada um
com uma lente; um modelo fecha a analise e o Claude **confere** antes de entregar. Metodo inspirado
no LLM Council de Andrej Karpathy e na skill de Ole Lehmann; redacao propria.

O motor e `scripts/council.py`, sobre a skill `call-agy`. Chame o script; nao remonte o fluxo na mao.

---

## Quando vale

Vale para decisao com opcoes reais e custo de errar: ferramenta ou arquitetura, construir ou nao,
qual caminho priorizar, um plano antes de executar.

Nao vale quando a resposta e fato, calculo ou algo que um teste resolve (faca o teste), nem para
pedido de resumo, texto ou codigo, nem para decisao facil de desfazer. Se o usuario disse que a cota
do agy esta no fim, avise o custo antes.

---

## Modos

| Modo | Quando | Pedidos ao agy | Custo aproximado |
|---|---|---|---|
| **leve** (padrao) | a maioria das decisoes | 3 conselheiros + fechamento = 4 | ~160 mil tokens; 2 no balde Claude |
| **completo** | o usuario pediu, ou a decisao e cara de desfazer | 5 + 3 revisores + fechamento = 9 | ~360 mil tokens; 3 no balde Claude |
| **sigiloso** | a decisao envolve dado sigiloso (processo, investigacao, dado pessoal, extrato, credencial) | 3 subagentes do Claude | cota do Claude Code; nada vai ao agy |

Antes de rodar, diga em uma linha: modo, pedidos e balde. Retentativas somam tempo (ate 4 por
pedido, 300 s cada); o script mostra o progresso de cada fase.

Lentes e modelos (definidos em `council.py`):

| Lente | Pergunta que ela faz | Modelo | Leve | Completo |
|---|---|---|---|---|
| auditor | o que pode falhar, quanto custa, que premissa esta sem prova | Gemini 3.1 Pro (High) | sim | sim |
| evidencia | que dado, medicao ou teste barato decidiria; o que esta sendo afirmado sem prova | Claude Sonnet 4.6 (Thinking) | sim | sim |
| operador | o menor passo verificavel desta semana e o que ele provaria | Gemini 3.8 Flash (High) | sim | sim |
| alternativa | o caminho fora das opcoes dadas que renderia mais com o mesmo esforco | Gemini 3.8 Flash (High) | - | sim |
| estranho | o que soa estranho para quem chega agora; recebe so a pergunta | Gemini 3.1 Pro (High) | - | sim |

Fechamento: `SYNTH_MODEL` da call-agy (Claude Opus 4.6 Thinking, via agy). Revisores do completo:
um por modelo. Revisores veem so a decisao e os pareceres; o fechamento ve tambem o contexto. IDs
conferidos em 2026-09-30, junto com a secao "Catalogo de modelos" da call-agy.

---

## Passo 1 - sigilo e enquadramento

1. **Sigilo primeiro.** Envolve dado sigiloso ou credencial -> **modo sigiloso**. Na duvida, sigiloso.
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

O script usa pasta de trabalho vazia (`~/.agy-council-cwd`), sorteia as letras, corta pareceres
longos e trata a cota: **Gemini esgotado** -> as cadeiras e revisores Gemini passam ao Claude Sonnet
do agy (com aviso de menos diversidade); **Claude tambem esgotado** -> para.

Saida JSON: `status`, `veredito`, `respostas` (letra, lente, modelo, texto), `revisoes`,
`chamadas`, `baldes`, `avisos`. Codigo 0 ok, 1 nao fechou, 2 entrada invalida, 3 cota.

| status | O que fazer |
|---|---|
| `OK` | passo 3 |
| `COTA` | **pare e avise o usuario para trocar a conta**; mostre as `respostas` que ja vieram; nao espere a cota voltar nem troque por subagente |
| `POUCAS_RESPOSTAS` | diga quem nao respondeu (`avisos`) e ofereca rodar de novo; nao feche voce como se fosse o conselho |
| `SINTESE_FALHOU` | mostre os pareceres e ofereca repetir so o fechamento |

## Passo 2-S - modo sigiloso

Nada vai ao agy. Gere os prompts com o mesmo texto do motor:

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
Conselho: <tema> (modo leve · 4 pedidos · gemini 2 / claude 2)
...
Conferencia
- conferi: ...
- alegado, nao conferi: ...
```

Avisos do script (cadeira sem resposta, reserva Sonnet) em uma linha no fim. Registro em arquivo,
apenas a pedido: na pasta de trabalho dele, com o caminho completo.

---

## Manutencao

- IDs em `scripts/council.py` (`PRO`, `SONNET`, `FLASH`); fechamento = `SYNTH_MODEL` da call-agy.
  Revise quando a call-agy revisar o catalogo.
- Testes puros (agy simulado, sem cota): `python tests/test_council.py`.
