"""
council.py - motor do /llm-council sobre a skill call-agy (agy = Antigravity CLI).

Modos:
    leve     (padrao) 3 conselheiros, um por modelo, sem revisao cruzada; presidente Opus.
    completo 5 conselheiros + 3 revisores anonimos (um por modelo); presidente Opus.
O modo sigiloso (assunto que nao pode sair do Claude) NAO passa por aqui: roda com subagentes do
Claude usando os prompts de --prompts (ver SKILL.md).

Uso:
    python council.py --modo leve --pergunta pergunta.txt [--contexto contexto.txt]
    python council.py --prompts --modo leve --pergunta pergunta.txt [--contexto contexto.txt]
Saida: JSON no stdout; progresso por fase no stderr.
Codigo: 0 ok, 1 o conselho nao fechou, 2 entrada invalida, 3 cota do agy esgotada.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "call-agy" / "scripts"))
from agy import SYNTH_MODEL, THINK_TIMEOUT, call_agy_parallel  # noqa: E402

# Pasta vazia de trabalho do agy: sem ela ele comecaria na pasta pessoal do usuario.
CWD = Path.home() / ".agy-council-cwd"
LIMITE_PERGUNTA = 4000    # pergunta + contexto
CORTE_RESPOSTA = 3000     # cada resposta, ao entrar no prompt de revisor/presidente
CORTE_REVISAO = 2000
TETO_PROMPT = 30000       # o prompt vai por argv (limite do Windows ~32767)

PRO, SONNET, FLASH = "Gemini 3.1 Pro (High)", "Claude Sonnet 4.6 (Thinking)", "Gemini 3.8 Flash (High)"
RESERVA_GEMINI = SONNET   # cota do Gemini esgotada: a cadeira vai para o Claude Sonnet do agy

# papel -> (lente, modelo). Lentes proprias (tres delas ecoam perspectivas classicas de analise; as de
# evidencia e alternativa sao desta skill), inspiradas no metodo de Karpathy e na skill de Ole Lehmann.
PAPEIS: dict[str, tuple[str, str]] = {
    "auditor": ("Sua lente e o risco. Liste o que pode falhar, quanto custa se falhar e qual premissa "
                "sustenta a proposta sem prova.", PRO),
    "evidencia": ("Sua lente e a prova. Diga que dado, medicao ou teste barato decidiria a questao, e o que "
                  "hoje esta sendo afirmado sem esse dado.", SONNET),
    "operador": ("Sua lente e a execucao. Diga o menor passo verificavel desta semana, o esforco e o que "
                 "o resultado desse passo provaria.", FLASH),
    "alternativa": ("Sua lente e a opcao ausente. Diga que outro caminho, fora das opcoes dadas, usaria o "
                    "mesmo esforco com resultado melhor.", FLASH),
    "estranho": ("Sua lente e a de quem chega agora, sem historico. Diga o que soa estranho, obscuro ou "
                 "desproporcional.", PRO),
}
MODOS = {"leve": ["auditor", "evidencia", "operador"],
         "completo": ["auditor", "evidencia", "operador", "alternativa", "estranho"]}
MINIMO = {"leve": 2, "completo": 3}
REVISORES = [PRO, SONNET, FLASH]


def _corta(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[:n] + " [cortado]"


def prompt_conselheiro(papel: str, pergunta: str, contexto: str) -> str:
    lente, _ = PAPEIS[papel]
    # "estranho" recebe so a pergunta: o papel dele depende de nao ter o contexto.
    corpo = pergunta if papel == "estranho" or not contexto else f"{pergunta}\n\nCONTEXTO:\n{contexto}"
    return (
        f"Voce opina numa decisao ao lado de outros analistas. {lente}\n"
        "Nao leia arquivos nem rode comandos: use so o texto abaixo. Escreva em portugues do Brasil, "
        "no maximo 300 palavras, com posicao definida e as incertezas declaradas. Nao diga qual e a sua lente.\n"
        "Feche com: 'Premissas que assumi:' e 'O que mudaria minha opiniao:'.\n\n"
        f"DECISAO EM ANALISE:\n{corpo}"
    )


def _anonimo(respostas: list[dict]) -> str:
    return "\n\n".join(f"[{r['letra']}]\n{_corta(r['texto'], CORTE_RESPOSTA)}" for r in respostas)


def prompt_revisor(pergunta: str, respostas: list[dict]) -> str:
    return (
        "Voce recebe pareceres anonimos, marcados por letra, sobre a mesma decisao. Em portugues do Brasil, "
        "ate 200 palavras, faca tres coisas: aponte a afirmacao mais fragil de cada parecer; diga que "
        "evidencia resolveria a principal discordancia entre eles; e cite um fator capaz de mudar a "
        "decisao que nao aparece em parecer algum.\n\n"
        f"DECISAO:\n{pergunta}\n\n{_anonimo(respostas)}"
    )


def prompt_presidente(pergunta: str, contexto: str, respostas: list[dict], revisoes: list[str],
                      faltaram: list[str]) -> str:
    grupos: dict[str, list[str]] = {}
    for r in respostas:
        grupos.setdefault(r["modelo"], []).append(r["letra"])
    mesmo = "; ".join(" e ".join(v) for v in grupos.values() if len(v) > 1)
    partes = [
        "Voce fecha a analise de um grupo. Escreva em portugues do Brasil nesta ordem: "
        "### Resposta curta (uma frase) / ### Argumentos que se sustentam / ### Riscos e lacunas / "
        "### Desacordo que continua / ### Premissas a conferir (fatos verificaveis de que a resposta "
        "depende) / ### Proximo passo.",
        "Pareceres do MESMO modelo valem como um so" + (f" ({mesmo})." if mesmo else "."),
        "Posicao firme nao e prova: pese pelos argumentos, nao pelo tom.",
    ]
    if not revisoes:
        partes.append("Nao houve revisao cruzada: cite voce o fator capaz de mudar a decisao que ficou fora de todos os pareceres.")
    if faltaram:
        partes.append("Nao responderam (nao invente o que diriam): " + ", ".join(faltaram) + ".")
    partes.append(f"DECISAO:\n{pergunta}" + (f"\n\nCONTEXTO:\n{contexto}" if contexto else ""))
    partes.append(_anonimo(respostas))
    if revisoes:
        partes.append("REVISOES:\n" + "\n\n".join(_corta(r, CORTE_REVISAO) for r in revisoes))
    return "\n\n".join(partes)


def _balde(modelo: str) -> str:
    return "claude" if modelo.lower().startswith("claude") else "gemini"


def _rodar(fase: str, jobs: list[dict], rotulos: list[str], out: dict):
    """Roda a fase; cadeira Gemini sem cota e refeita no Sonnet do agy. Devolve (resultados, jobs)."""
    CWD.mkdir(exist_ok=True)
    for j in jobs:
        if len(j["prompt"]) > TETO_PROMPT:
            raise ValueError(f"prompt de {fase} com {len(j['prompt'])} caracteres passa do teto {TETO_PROMPT}")
    res = call_agy_parallel(jobs, max_concurrency=5, retries=3, timeout=THINK_TIMEOUT, cwd=str(CWD))
    for j in jobs:
        out["baldes"][_balde(j["model"])] += 1
    out["chamadas"] += len(jobs)
    refazer = [i for i, r in enumerate(res) if r.status == "QUOTA_EXHAUSTED" and _balde(jobs[i]["model"]) == "gemini"]
    if refazer:
        out["avisos"].append(f"{fase}: cota do Gemini esgotada; " + ", ".join(rotulos[i] for i in refazer)
                             + " refeitos no Claude Sonnet do agy (menos diversidade)")
        for i in refazer:
            jobs[i] = {**jobs[i], "model": RESERVA_GEMINI}
        novos = call_agy_parallel([jobs[i] for i in refazer], max_concurrency=5, retries=3,
                                  timeout=THINK_TIMEOUT, cwd=str(CWD))
        for i, r in zip(refazer, novos):
            res[i] = r
        out["baldes"]["claude"] += len(refazer)
        out["chamadas"] += len(refazer)
    for rot, r in zip(rotulos, res):
        print(f"[{fase}] {rot}: {r.status} ({r.model}, {r.elapsed_s:.0f}s)", file=sys.stderr, flush=True)
    return res, jobs


def rodar_council(pergunta: str, contexto: str = "", modo: str = "leve", seed: int | None = None) -> dict:
    """Devolve {status, modo, veredito, respostas, revisoes, chamadas, baldes, avisos}.

    status: OK | COTA (cota do agy esgotada, inclusive a do Claude) | POUCAS_RESPOSTAS | SINTESE_FALHOU.
    `respostas` volta preenchida mesmo quando o conselho nao fecha (o que ja foi pago nao se perde).
    `chamadas` conta pedidos ao agy, sem as retentativas internas.
    """
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo!r}")
    if len(pergunta) + len(contexto) > LIMITE_PERGUNTA:
        raise ValueError(f"pergunta + contexto passam de {LIMITE_PERGUNTA} caracteres: resuma antes")
    papeis = MODOS[modo]
    out = {"status": "OK", "modo": modo, "veredito": "", "respostas": [], "revisoes": [],
           "chamadas": 0, "baldes": {"gemini": 0, "claude": 0}, "avisos": []}

    jobs = [{"prompt": prompt_conselheiro(p, pergunta, contexto), "model": PAPEIS[p][1]} for p in papeis]
    res, jobs = _rodar("conselheiros", jobs, papeis, out)

    boas = [(p, j["model"], r.text.strip()) for p, j, r in zip(papeis, jobs, res) if r.ok and r.text.strip()]
    faltaram = [f"{p} ({r.status})" for p, r in zip(papeis, res) if not (r.ok and r.text.strip())]
    # Letras sorteadas por codigo: quem revisa nao sabe qual lente escreveu o que.
    sorteio = random.Random(seed) if seed is not None else random.SystemRandom()
    sorteio.shuffle(boas)
    respostas = [{"letra": chr(65 + i), "papel": p, "modelo": m, "texto": t} for i, (p, m, t) in enumerate(boas)]
    out["respostas"] = respostas

    if any(r.status == "QUOTA_EXHAUSTED" for r in res):
        out.update(status="COTA")
        out["avisos"].append("cota do agy esgotada (Claude inclusive): trocar a conta")
        return out
    if len(boas) < MINIMO[modo]:
        out.update(status="POUCAS_RESPOSTAS")
        out["avisos"].append("nao responderam: " + ", ".join(faltaram))
        return out

    if modo == "completo":
        rjobs = [{"prompt": prompt_revisor(pergunta, respostas), "model": m} for m in REVISORES]
        rv, rjobs = _rodar("revisao", rjobs, REVISORES, out)
        if any(r.status == "QUOTA_EXHAUSTED" for r in rv):
            out.update(status="COTA")
            out["avisos"].append("cota do agy esgotada na revisao (Claude inclusive): trocar a conta")
            return out
        out["revisoes"] = [f"(revisor {j['model']}) {r.text.strip()}" for j, r in zip(rjobs, rv) if r.ok and r.text.strip()]
        falhos = [f"{j['model']} ({r.status})" for j, r in zip(rjobs, rv) if not (r.ok and r.text.strip())]
        if falhos:
            out["avisos"].append("revisores sem resposta: " + ", ".join(falhos))

    pjob = [{"prompt": prompt_presidente(pergunta, contexto, respostas, out["revisoes"], faltaram), "model": SYNTH_MODEL}]
    [pres], _ = _rodar("presidente", pjob, ["presidente"], out)
    if pres.status == "QUOTA_EXHAUSTED":
        out.update(status="COTA")
        out["avisos"].append("cota do Claude no agy esgotada no presidente: trocar a conta")
    elif not (pres.ok and pres.text.strip()):
        out.update(status="SINTESE_FALHOU")
        out["avisos"].append(f"presidente: {pres.status} {pres.error or ''}".strip())
    else:
        out["veredito"] = pres.text.strip()
    if faltaram:
        out["avisos"].append("conselheiros sem resposta: " + ", ".join(faltaram))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Motor do /llm-council sobre o agy.")
    ap.add_argument("--modo", default="leve", choices=list(MODOS))
    ap.add_argument("--pergunta", required=True, help="arquivo .txt com a pergunta enquadrada")
    ap.add_argument("--contexto", help="arquivo .txt com o resumo de contexto escrito pelo Claude")
    ap.add_argument("--prompts", action="store_true", help="so imprime os prompts (modo sigiloso)")
    a = ap.parse_args(argv)
    try:
        pergunta = Path(a.pergunta).read_text(encoding="utf-8").strip()
        contexto = Path(a.contexto).read_text(encoding="utf-8").strip() if a.contexto else ""
        if len(pergunta) + len(contexto) > LIMITE_PERGUNTA:
            raise ValueError(f"pergunta + contexto passam de {LIMITE_PERGUNTA} caracteres: resuma antes")
        if a.prompts:
            print(json.dumps({p: prompt_conselheiro(p, pergunta, contexto) for p in MODOS[a.modo]},
                             ensure_ascii=False, indent=2))
            return 0
        out = rodar_council(pergunta, contexto, a.modo)
    except (OSError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 3 if out["status"] == "COTA" else (0 if out["status"] == "OK" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
