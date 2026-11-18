# llm-council

Skill do Claude Code que submete uma decisao dificil a um conselho de modelos de familias
diferentes (OpenAI pelo Codex CLI; Mistral e GLM pelo Mistral Vibe CLI), com revisao anonima e um veredito que o Claude
confere antes de entregar.

- **Modo leve** (padrao): 3 conselheiros, um por modelo, e um fechamento — 4 pedidos (Codex e vibe).
- **Modo completo**: 5 conselheiros, 3 revisores anonimos e o fechamento — 9 pedidos.
- **Debate** (`--debate`, em qualquer modo): segunda rodada em que cada conselheiro rebate os outros.
- **Reserva**: se um executor cai, a cadeira passa ao outro; sem os dois, `--prompts` gera os prompts para subagentes do Claude.

## Requisitos

- Windows com o `codex` (gpt-6.1-sol) instalado e logado.
- O CLI `vibe` (Mistral Vibe) logado, com `zai-glm-5-3` e `mistral-large-4` em `~/.vibe/config.toml`.
- Clonar este repositorio em `~/.claude/skills/llm-council`.

Uso: peca "passa pelo council" no Claude Code. Motor: `scripts/council.py`; testes:
`python tests/test_council.py` (nao chamam o Codex nem o vibe).

**Aviso:** o Codex e o vibe sao servicos externos. Nao mande dado pessoal, sigiloso ou credencial pelos modos
leve e completo.

## Creditos

Metodo inspirado no [LLM Council](https://github.com/karpathy/llm-council) de Andrej Karpathy e na
skill LLM Council de [Ole Lehmann](https://x.com/itsolelehmann). Redacao e codigo deste repositorio
sao proprios.
