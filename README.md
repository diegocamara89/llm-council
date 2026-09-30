# llm-council

Skill do Claude Code que submete uma decisao dificil a um conselho de modelos de familias
diferentes (Gemini e Claude, pelo Antigravity CLI), com revisao anonima e um veredito que o Claude
confere antes de entregar.

- **Modo leve** (padrao): 3 conselheiros, um por modelo, e um fechamento — 4 pedidos ao agy.
- **Modo completo**: 5 conselheiros, 3 revisores anonimos e o fechamento — 9 pedidos.
- **Modo sigiloso**: para assunto que nao pode sair do Claude; roda com subagentes dele.

## Requisitos

- Windows com o [agy](https://antigravity.google/cli) instalado e logado.
- A skill [call-agy](https://github.com/diegocamara89/call-agy) em `~/.claude/skills/call-agy`.
- Clonar este repositorio em `~/.claude/skills/llm-council`.

Uso: peca "passa pelo council" no Claude Code. Motor: `scripts/council.py`; testes:
`python tests/test_council.py` (nao chamam o agy).

**Aviso:** o agy e um servico externo. Nao mande dado pessoal, sigiloso ou credencial pelos modos
leve e completo.

## Creditos

Metodo inspirado no [LLM Council](https://github.com/karpathy/llm-council) de Andrej Karpathy e na
skill LLM Council de [Ole Lehmann](https://x.com/itsolelehmann). Redacao e codigo deste repositorio
sao proprios.
